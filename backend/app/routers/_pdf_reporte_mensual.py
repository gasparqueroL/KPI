"""Generador del reporte mensual ejecutivo PDF.

Una sola página A4 con:
- Header (período, fecha emisión)
- KPIs principales (ventas, margen, ticket, clientes únicos) con delta vs mes anterior
- Top 5 productos por margen
- Top 5 clientes
- Top 5 vendedores
- Alertas activas

Pensado para mandar al contador o guardar como reporte mensual del negocio.
Reusa `_estilos_pdf` y formato de moneda del módulo de extracto.
"""
from datetime import date
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.routers._pdf_extracto import _estilos_pdf, _fmt_money_strict


def _formato_kpi_valor(valor, unidad: str) -> str:
    """Formato compacto para tabla de KPIs en el PDF."""
    if valor is None:
        return "—"
    if unidad in ("ARS", "ARS/empleado"):
        return _fmt_money_strict(valor)
    if unidad == "%":
        return f"{valor:.1f}%"
    if unidad == "ratio":
        return f"{valor:.2f}"
    if unidad in ("score", "‰"):
        return f"{valor:.1f}{' ‰' if unidad == '‰' else ''}"
    # Default: número con 1 decimal si no es entero
    if isinstance(valor, float) and valor != int(valor):
        return f"{valor:.1f}"
    return str(int(valor)) if isinstance(valor, (int, float)) else str(valor)


def _delta_label(delta_pct: float | None) -> str:
    """Renderiza el delta % vs período anterior con flecha y color HTML.

    Para delta=0 usa una raya horizontal en gris (no un punto): es más
    obvio que significa "sin cambio" que el `•` ambiguo."""
    if delta_pct is None:
        return '<font color="#94a3b8">—</font>'
    if delta_pct > 0:
        return f'<font color="#16a34a">▲ {delta_pct:.1f}%</font>'
    if delta_pct < 0:
        return f'<font color="#dc2626">▼ {abs(delta_pct):.1f}%</font>'
    return '<font color="#94a3b8">▬ 0.0%</font>'


def _kpi_card_para_tabla(
    estilo_kpi, estilo_sub, label: str, valor: str, delta_html: str
):
    """Devuelve un Paragraph para usar como celda KPI dentro de una Table."""
    return [
        Paragraph(f"<b>{label}</b>", estilo_sub),
        Paragraph(f'<font size="14"><b>{valor}</b></font>', estilo_kpi),
        Paragraph(delta_html, estilo_sub),
    ]


def render_reporte_mensual_pdf(
    *,
    titulo: str,
    rango: dict[str, Any],
    rango_anterior: dict[str, Any],
    kpis: dict[str, Any],
    top_productos: list[dict[str, Any]],
    top_clientes: list[dict[str, Any]],
    top_vendedores: list[dict[str, Any]],
    alertas: list[dict[str, Any]],
    margen_op: dict[str, Any] | None = None,
    dpo: dict[str, Any] | None = None,
    dependencia: dict[str, Any] | None = None,
    objetivos_resumen: dict[str, Any] | None = None,
    kpis_derivados: list[dict[str, Any]] | None = None,
) -> bytes:
    """Genera el PDF y devuelve los bytes."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=titulo,
    )
    estilos = _estilos_pdf()
    e_titulo = estilos["titulo"]
    e_sub = estilos["sub"]
    e_kpi = estilos["kpi"]
    e_celda = estilos["celda"]

    flow = []
    flow.append(Paragraph(titulo, e_titulo))
    flow.append(Paragraph(
        f"Período: <b>{rango['desde']}</b> a <b>{rango['hasta']}</b> "
        f"({rango['dias']} días) — comparado contra "
        f"<b>{rango_anterior['desde']}</b> a <b>{rango_anterior['hasta']}</b>",
        e_sub,
    ))
    flow.append(Paragraph(f"Emitido: {date.today().isoformat()}", e_sub))
    flow.append(Spacer(1, 5 * mm))

    # KPIs en una grilla 2x2 con delta vs mes anterior
    k = kpis
    margen_pct_actual = k["margen_bruto"].get("margen_pct_actual", 0)
    cells = [
        [
            _kpi_card_para_tabla(e_kpi, e_sub, "Ventas",
                                 _fmt_money_strict(k["ventas"]["actual"]),
                                 _delta_label(k["ventas"]["delta_pct"])),
            _kpi_card_para_tabla(e_kpi, e_sub,
                                 f"Margen bruto ({margen_pct_actual:.1f}%)",
                                 _fmt_money_strict(k["margen_bruto"]["actual"]),
                                 _delta_label(k["margen_bruto"]["delta_pct"])),
        ],
        [
            _kpi_card_para_tabla(e_kpi, e_sub, "Ticket promedio",
                                 _fmt_money_strict(k["ticket_promedio"]["actual"]),
                                 _delta_label(k["ticket_promedio"]["delta_pct"])),
            _kpi_card_para_tabla(e_kpi, e_sub, "Clientes únicos",
                                 f"{k['clientes_unicos']['actual']:,}".replace(",", "."),
                                 _delta_label(k["clientes_unicos"]["delta_pct"])),
        ],
    ]
    kpi_tbl = Table(cells, colWidths=[90 * mm, 90 * mm])
    kpi_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    flow.append(kpi_tbl)
    flow.append(Spacer(1, 5 * mm))

    # Bloque financiero adicional: margen operativo + DPO + concentración.
    # Solo se muestra si el caller pasó los datos (compat con callers viejos).
    if margen_op or dpo or dependencia:
        flow.append(Paragraph("<b>Indicadores financieros</b>", e_kpi))
        fin_rows = []
        if margen_op:
            mop_pct = margen_op.get("margen_operativo_pct")
            mop_val = margen_op.get("margen_operativo", 0)
            fin_rows.append([
                Paragraph("Margen operativo del período", e_celda),
                Paragraph(_fmt_money_strict(mop_val), e_celda),
                Paragraph(f"{mop_pct:.1f}% sobre ingresos" if mop_pct is not None else "—", e_sub),
            ])
            fin_rows.append([
                Paragraph("Egresos operativos", e_celda),
                Paragraph(_fmt_money_strict(margen_op.get("egresos_operativos", 0)), e_celda),
                Paragraph("excluye transferencias y retiros", e_sub),
            ])
        if dpo and dpo.get("dpo_dias") is not None:
            fin_rows.append([
                Paragraph("DPO (días promedio de pago)", e_celda),
                Paragraph(f"{dpo['dpo_dias']:.1f} días", e_celda),
                Paragraph(f"{dpo.get('facturas_consideradas', 0)} facturas saldadas", e_sub),
            ])
        if dependencia and dependencia.get("concentracion", {}).get("top_1_pct") is not None:
            top1 = dependencia["concentracion"]["top_1_pct"]
            top1_nom = (dependencia.get("top") or [{}])[0].get("nombre", "—")
            fin_rows.append([
                Paragraph("Concentración top 1 proveedor", e_celda),
                Paragraph(f"{top1:.1f}%", e_celda),
                Paragraph(f"{top1_nom}", e_sub),
            ])
        if fin_rows:
            ftbl = Table(fin_rows, colWidths=[60 * mm, 40 * mm, 80 * mm])
            ftbl.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            flow.append(ftbl)
            flow.append(Spacer(1, 5 * mm))

    # Tres tablas top en columnas — armadas como sub-tablas dentro de una grilla
    t_prod = _tabla_top(
        ["#", "Producto", "Margen", "%"],
        [(i + 1, p["producto"], _fmt_money_strict(p["margen"]), f"{p['margen_pct']:.1f}%")
         for i, p in enumerate(top_productos)],
        e_celda,
        col_widths=[6 * mm, 36 * mm, 18 * mm, 10 * mm],
    )
    t_cli = _tabla_top(
        ["#", "Cliente", "Ventas"],
        [(i + 1, c.get("cliente") or f"(ID {c.get('id_cliente')})", _fmt_money_strict(c["ventas"]))
         for i, c in enumerate(top_clientes)],
        e_celda,
        col_widths=[6 * mm, 38 * mm, 22 * mm],
    )
    t_vend = _tabla_top(
        ["#", "Vendedor", "Ventas", "Margen"],
        [(i + 1, v["vendedor"], _fmt_money_strict(v["ventas"]), _fmt_money_strict(v["margen"]))
         for i, v in enumerate(top_vendedores)],
        e_celda,
        col_widths=[6 * mm, 28 * mm, 18 * mm, 18 * mm],
    )

    flow.append(Paragraph("<b>Top 5 productos por margen</b>", e_kpi))
    flow.append(t_prod)
    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph("<b>Top 5 clientes por ventas</b>", e_kpi))
    flow.append(t_cli)
    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph("<b>Top 5 vendedores</b>", e_kpi))
    flow.append(t_vend)
    flow.append(Spacer(1, 5 * mm))

    # KPIs manuales / derivados (NPS, ROA, rotación, etc.) — solo se
    # muestra si el caller pasó datos. Mostramos hasta 12 KPIs con
    # status ok para no inflar el PDF — los faltan no aportan al lector.
    if kpis_derivados:
        ok_kpis = [k for k in kpis_derivados if k.get("status") == "ok"
                   and k.get("valor") is not None]
        if ok_kpis:
            flow.append(Paragraph("<b>KPIs del período</b>", e_kpi))
            kpi_rows = [["Área", "KPI", "Valor", "Objetivo"]]
            for k in ok_kpis[:12]:
                valor_str = _formato_kpi_valor(k.get("valor"), k.get("unidad", ""))
                obj = k.get("objetivo")
                if obj is not None:
                    op = "≤" if k.get("mejor_si") == "bajar" else "≥"
                    cumple = k.get("cumple_objetivo")
                    icon = " ✓" if cumple is True else " ✗" if cumple is False else ""
                    obj_str = f"{op} {_formato_kpi_valor(obj, k.get('unidad', ''))}{icon}"
                else:
                    obj_str = "—"
                kpi_rows.append([
                    Paragraph(k.get("area", ""), e_celda),
                    Paragraph(k.get("label", k.get("codigo", "")), e_celda),
                    Paragraph(valor_str, e_celda),
                    Paragraph(obj_str, e_celda),
                ])
            ktbl = Table(kpi_rows, colWidths=[24 * mm, 90 * mm, 35 * mm, 31 * mm], repeatRows=1)
            ktbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            flow.append(ktbl)
            flow.append(Spacer(1, 4 * mm))

    # Resumen de cumplimiento de objetivos (línea compacta).
    if objetivos_resumen and objetivos_resumen.get("total", 0) > 0:
        total = objetivos_resumen["total"]
        cumplen = objetivos_resumen.get("cumplen", 0)
        no_cumplen = objetivos_resumen.get("no_cumplen", 0)
        sin_valor = objetivos_resumen.get("sin_valor", 0)
        periodo_eval = objetivos_resumen.get("periodo_evaluado", "")
        flow.append(Paragraph(
            f"<b>Cumplimiento de objetivos ({periodo_eval}):</b> "
            f"<font color='#16a34a'>{cumplen} cumplen</font> · "
            f"<font color='#dc2626'>{no_cumplen} no cumplen</font> · "
            f"<font color='#94a3b8'>{sin_valor} sin valor</font> "
            f"de {total} totales.",
            e_sub,
        ))
        flow.append(Spacer(1, 3 * mm))

    # Alertas activas (al final, marcando situación)
    flow.append(Paragraph("<b>Alertas activas al cierre del período</b>", e_kpi))
    if not alertas:
        flow.append(Paragraph("Sin alertas activas.", e_sub))
    else:
        rows = [["Severidad", "Título"]]
        for a in alertas[:8]:  # capamos a 8 para que entre todo en 1 página
            rows.append([
                Paragraph(a["severidad"].upper(), e_celda),
                Paragraph(a["titulo"], e_celda),
            ])
        atbl = Table(rows, colWidths=[25 * mm, 155 * mm], repeatRows=1)
        atbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(atbl)

    doc.build(flow)
    return buf.getvalue()


def _tabla_top(headers, filas, estilo_celda, col_widths):
    """Helper para tablas top compactas con header oscuro."""
    rows = [headers]
    for f in filas:
        rows.append([Paragraph(str(c), estilo_celda) for c in f])
    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        # Última columna(s) numérica — alineadas derecha. Detección
        # heurística: las columnas distintas a las dos primeras (#, nombre).
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tbl
