"""PDF de resumen diario de caja: saldos por caja + movimientos del día.

Pensado para que la dueña cierre el día y archive el resumen impreso.
"""
from datetime import date
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.routers._pdf_extracto import _estilos_pdf, _fmt_money_strict


def render_resumen_diario_pdf(
    *,
    fecha: date,
    saldos_por_caja: list[dict[str, Any]],
    movimientos: list[dict[str, Any]],
    totales_dia: dict[str, Any],
) -> bytes:
    """Genera el PDF del resumen del día.

    `saldos_por_caja`: snapshot al cierre (mismo dato que muestra `/api/caja/saldos`).
    `movimientos`: lista de movs del día con `tipo_operacion`, `monto`, `caja_origen`,
        `caja_destino`, `detalle`.
    `totales_dia`: `{ingresos_operativos, egresos_operativos, transferencias, neto}`.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Resumen diario {fecha.isoformat()}",
    )
    estilos = _estilos_pdf()
    e_titulo = estilos["titulo"]
    e_sub = estilos["sub"]
    e_kpi = estilos["kpi"]
    e_celda = estilos["celda"]

    flow = []
    flow.append(Paragraph(f"Resumen diario de caja · {fecha.strftime('%d/%m/%Y')}", e_titulo))
    flow.append(Paragraph(
        f"Generado: {date.today().strftime('%d/%m/%Y')} · "
        f"{len(movimientos)} movimientos del día",
        e_sub,
    ))
    flow.append(Spacer(1, 5 * mm))

    # Resumen de totales del día (cards horizontales)
    ingresos = totales_dia.get("ingresos_operativos", 0)
    egresos = totales_dia.get("egresos_operativos", 0)
    neto = totales_dia.get("neto", 0)
    color_neto = "#16a34a" if neto >= 0 else "#dc2626"
    cells = [[
        Paragraph(
            f'<font size="9" color="#475569"><b>Ingresos del día</b></font><br/>'
            f'<font size="14" color="#16a34a"><b>{_fmt_money_strict(ingresos)}</b></font>',
            e_kpi,
        ),
        Paragraph(
            f'<font size="9" color="#475569"><b>Egresos del día</b></font><br/>'
            f'<font size="14" color="#dc2626"><b>{_fmt_money_strict(egresos)}</b></font>',
            e_kpi,
        ),
        Paragraph(
            f'<font size="9" color="#475569"><b>Neto del día</b></font><br/>'
            f'<font size="14" color="{color_neto}"><b>{_fmt_money_strict(neto)}</b></font>',
            e_kpi,
        ),
    ]]
    tot_tbl = Table(cells, colWidths=[60 * mm, 60 * mm, 60 * mm])
    tot_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    flow.append(tot_tbl)
    flow.append(Spacer(1, 5 * mm))

    # Saldos por caja calculados HASTA el día reportado (inclusive).
    # Reproducible: el mismo PDF impreso hoy o mañana da los mismos números
    # para una fecha pasada.
    flow.append(Paragraph(
        f"<b>Saldos por caja al cierre del {fecha.strftime('%d/%m/%Y')}</b>", e_kpi
    ))
    if not saldos_por_caja:
        flow.append(Paragraph("Sin cajas configuradas.", e_sub))
    else:
        rows_s = [["Caja", "Tipo", "Saldo"]]
        total_general = 0.0
        for s in saldos_por_caja:
            saldo_v = float(s.get("saldo", 0) or 0)
            # Saldo negativo en rojo — alinea con el indicador visual de
            # la UI y con la alerta crítica preexistente "caja en negativo".
            if saldo_v < 0:
                saldo_html = f'<font color="#dc2626"><b>{_fmt_money_strict(saldo_v)}</b></font>'
            else:
                saldo_html = _fmt_money_strict(saldo_v)
            rows_s.append([
                Paragraph(s.get("caja") or "-", e_celda),
                Paragraph(s.get("tipo") or "-", e_celda),
                Paragraph(saldo_html, e_celda),
            ])
            total_general += saldo_v
        total_color = "#dc2626" if total_general < 0 else "#0f172a"
        rows_s.append([
            Paragraph("<b>TOTAL</b>", e_celda),
            Paragraph("", e_celda),
            Paragraph(
                f'<font color="{total_color}"><b>{_fmt_money_strict(total_general)}</b></font>',
                e_celda,
            ),
        ])
        sal_tbl = Table(rows_s, colWidths=[80 * mm, 50 * mm, 50 * mm], repeatRows=1)
        sal_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
            ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.HexColor("#0f172a")),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8fafc")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(sal_tbl)

    flow.append(Spacer(1, 5 * mm))

    # Movimientos del día
    flow.append(Paragraph("<b>Movimientos del día</b>", e_kpi))
    if not movimientos:
        flow.append(Paragraph("Sin movimientos registrados en esta fecha.", e_sub))
    else:
        rows_m = [["Tipo", "Detalle", "Origen → Destino", "Monto"]]
        for m in movimientos:
            origen = m.get("caja_origen") or ""
            destino = m.get("caja_destino") or ""
            ruta = " → ".join(filter(None, [origen, destino])) or "-"
            rows_m.append([
                Paragraph(m.get("tipo_operacion") or "-", e_celda),
                Paragraph(m.get("detalle") or "", e_celda),
                Paragraph(ruta, e_celda),
                Paragraph(_fmt_money_strict(m.get("monto", 0)), e_celda),
            ])
        mov_tbl = Table(rows_m, colWidths=[35 * mm, 70 * mm, 50 * mm, 25 * mm], repeatRows=1)
        mov_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(mov_tbl)

    doc.build(flow)
    return buf.getvalue()
