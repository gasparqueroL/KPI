"""Helper compartido para generar PDFs de extracto (cliente / proveedor).

Diseño: una sola función `render_extracto_pdf` que recibe:
- `titulo`: ej. "Extracto cliente" o "Extracto proveedor"
- `entidad`: dict con datos a mostrar en el header (nombre, cuit, contacto, ID, ...)
- `totales`: dict con saldo_actual, total_debe, total_haber
- `eventos`: lista de dicts con fecha/tipo/descripcion/debe/haber/saldo

Usa reportlab (ya en deps). Layout simple A4 con tabla paginada automática.
"""
from datetime import date
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.core.formato import fmt_money_ar


def _estilos_pdf():
    """Estilos compartidos entre `render_extracto_pdf` y `render_aging_pdf`.
    Factor para evitar redefinir los mismos ParagraphStyle dos veces."""
    base = getSampleStyleSheet()
    return {
        "base": base,
        "titulo": ParagraphStyle(
            "tit", parent=base["Heading1"],
            fontSize=16, spaceAfter=4, textColor=colors.HexColor("#0f172a"),
        ),
        "sub": ParagraphStyle(
            "sub", parent=base["Normal"],
            fontSize=10, textColor=colors.HexColor("#475569"),
        ),
        "kpi": ParagraphStyle(
            "kpi", parent=base["Normal"],
            fontSize=11, textColor=colors.HexColor("#0f172a"),
        ),
        "celda": ParagraphStyle(
            "celda", parent=base["Normal"], fontSize=8, leading=10,
        ),
    }


# Thin wrappers sobre `fmt_money_ar` (single source of truth). Mantenemos
# los nombres `_fmt_money` y `_fmt_money_strict` para no romper imports en
# `_pdf_resumen_diario.py` y `_pdf_reporte_mensual.py` que dependen de ellos.
#
# Behavior change introducido al migrar: AMBOS wrappers (default y strict)
# pasan negativos de `$-1.234` (US-style, signo entre $ y dígitos) a
# `-$1.234` (AR Excel-style, signo antes). Importante para `_fmt_money_strict`
# en saldos negativos del resumen diario (`_pdf_resumen_diario.py:106`).
# Es la corrección que ya se aplicó a alertas — ahora consistente entre
# todas las superficies que la dueña ve. Behavior congelado por
# `tests/test_formato.py::test_negativo_signo_antes_del_simbolo_excel_style`.
def _fmt_money(v) -> str:
    return fmt_money_ar(v)


def _fmt_money_strict(v) -> str:
    """Versión que SIEMPRE muestra el monto, incluso si es 0 (para totales).

    **CONTRATO** (no romper sin pensar): `v or 0` es DELIBERADO. Preserva
    el comportamiento original `_fmt_money_strict(None) → "$0"`. Sin el
    `or 0`, el shared `fmt_money_ar(None, strict=True)` devuelve `"-"`
    (semántica "valor desconocido"). Los PDFs llaman a este wrapper para
    celdas de totales/saldos donde una celda con `None` debe rendear como
    `$0` (importe medido, dio cero) en vez de `"-"` (sin medición).

    Si futuros mantenedores "simplifican" quitando el `or 0`, los PDFs
    empiezan a mostrar "-" en celdas de saldo $0 — UX peor para la dueña.
    """
    return fmt_money_ar(v or 0, strict=True)


def render_extracto_pdf(
    *,
    titulo: str,
    entidad: dict[str, Any],
    totales: dict[str, Any],
    eventos: list[dict[str, Any]],
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
    estilo_titulo = estilos["titulo"]
    estilo_sub = estilos["sub"]
    estilo_kpi = estilos["kpi"]

    flow = []
    flow.append(Paragraph(titulo, estilo_titulo))
    nombre = entidad.get("nombre") or "(sin nombre)"
    flow.append(Paragraph(f"<b>{nombre}</b>", estilo_kpi))

    # Datos secundarios opcionales en una sola línea
    detalles = []
    if entidad.get("id") is not None:
        detalles.append(f"ID: {entidad['id']}")
    if entidad.get("cuit"):
        detalles.append(f"CUIT: {entidad['cuit']}")
    if entidad.get("contacto"):
        detalles.append(f"Contacto: {entidad['contacto']}")
    if detalles:
        flow.append(Paragraph(" · ".join(detalles), estilo_sub))

    flow.append(Paragraph(
        f"Emitido: {date.today().isoformat()}", estilo_sub
    ))
    flow.append(Spacer(1, 8 * mm))

    # KPIs en una mini-tabla horizontal: saldo / debe / haber
    saldo = totales.get("saldo_actual", 0)
    debe = totales.get("total_debe", 0)
    haber = totales.get("total_haber", 0)
    color_saldo_hex = "#dc2626" if saldo > 0 else "#16a34a"
    kpi_tbl = Table(
        [[
            Paragraph("<b>Saldo actual</b>", estilo_sub),
            Paragraph("<b>Total debe</b>", estilo_sub),
            Paragraph("<b>Total haber</b>", estilo_sub),
        ], [
            Paragraph(f'<font size="14" color="{color_saldo_hex}"><b>{_fmt_money_strict(saldo)}</b></font>', estilo_kpi),
            Paragraph(f'<font size="14">{_fmt_money_strict(debe)}</font>', estilo_kpi),
            Paragraph(f'<font size="14">{_fmt_money_strict(haber)}</font>', estilo_kpi),
        ]],
        colWidths=[60 * mm, 60 * mm, 60 * mm],
    )
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    flow.append(kpi_tbl)
    flow.append(Spacer(1, 6 * mm))

    # Tabla de eventos
    if not eventos:
        flow.append(Paragraph("Sin movimientos.", estilo_sub))
    else:
        header = ["Fecha", "Tipo", "Descripción", "Debe", "Haber", "Saldo"]
        rows = [header]
        # Descripcion puede ser larga → la envolvemos en Paragraph para
        # que wrappee dentro de la celda.
        estilo_celda = estilos["celda"]
        for e in eventos:
            rows.append([
                Paragraph((e.get("fecha") or "")[:10], estilo_celda),
                Paragraph(e.get("tipo") or "", estilo_celda),
                Paragraph(e.get("descripcion") or "", estilo_celda),
                Paragraph(_fmt_money(e.get("debe")), estilo_celda),
                Paragraph(_fmt_money(e.get("haber")), estilo_celda),
                Paragraph(_fmt_money_strict(e.get("saldo", 0)), estilo_celda),
            ])

        tbl = Table(
            rows,
            colWidths=[20 * mm, 22 * mm, 75 * mm, 22 * mm, 22 * mm, 24 * mm],
            repeatRows=1,
        )
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("TOPPADDING", (0, 0), (-1, 0), 6),
            ("ALIGN", (3, 0), (-1, -1), "RIGHT"),  # debe/haber/saldo derecha
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(tbl)

    doc.build(flow)
    return buf.getvalue()


def render_aging_pdf(
    *,
    titulo: str,
    items: list[dict[str, Any]],
    totales: dict[str, Any],
    nombre_columna: str = "Cliente",
) -> bytes:
    """Genera PDF de aging completo: tabla con cliente/proveedor + 4 buckets
    + total. Pensado para imprimir y revisar con contador. Página A4 horizontal
    si hay muchos items, vertical si son pocos.

    `items`: cada uno con `{nombre, bucket_0_30, bucket_31_60, bucket_61_90,
        bucket_90_mas, total}` (el caller mapea sus campos antes de llamar).
    `totales`: dict con los mismos buckets más `total`."""
    buf = BytesIO()
    # Vertical para listas chicas (≤25), horizontal para más (cabe más texto en cliente)
    pagesize = A4 if len(items) <= 25 else (A4[1], A4[0])
    doc = SimpleDocTemplate(
        buf, pagesize=pagesize,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=titulo,
    )
    estilos = _estilos_pdf()
    estilo_titulo = estilos["titulo"]
    estilo_sub = estilos["sub"]
    estilo_celda = estilos["celda"]

    flow = []
    flow.append(Paragraph(titulo, estilo_titulo))
    flow.append(Paragraph(
        f"Emitido: {date.today().isoformat()} · {len(items)} {nombre_columna.lower()}s con saldo pendiente",
        estilo_sub,
    ))
    flow.append(Spacer(1, 6 * mm))

    if not items:
        flow.append(Paragraph("Sin saldos pendientes.", estilo_sub))
        doc.build(flow)
        return buf.getvalue()

    header = [nombre_columna, "0-30 días", "31-60", "61-90", "+90", "Total"]
    rows = [header]
    for it in items:
        rows.append([
            Paragraph(str(it.get("nombre") or "(sin nombre)"), estilo_celda),
            Paragraph(_fmt_money(it.get("bucket_0_30")), estilo_celda),
            Paragraph(_fmt_money(it.get("bucket_31_60")), estilo_celda),
            Paragraph(_fmt_money(it.get("bucket_61_90")), estilo_celda),
            Paragraph(_fmt_money(it.get("bucket_90_mas")), estilo_celda),
            Paragraph(_fmt_money_strict(it.get("total", 0)), estilo_celda),
        ])
    # Fila de totales
    rows.append([
        Paragraph("<b>TOTALES</b>", estilo_celda),
        Paragraph(f"<b>{_fmt_money_strict(totales.get('bucket_0_30', 0))}</b>", estilo_celda),
        Paragraph(f"<b>{_fmt_money_strict(totales.get('bucket_31_60', 0))}</b>", estilo_celda),
        Paragraph(f"<b>{_fmt_money_strict(totales.get('bucket_61_90', 0))}</b>", estilo_celda),
        Paragraph(f"<b>{_fmt_money_strict(totales.get('bucket_90_mas', 0))}</b>", estilo_celda),
        Paragraph(f"<b>{_fmt_money_strict(totales.get('total', 0))}</b>", estilo_celda),
    ])

    # Anchos calculados sobre el ancho útil de la página (descontando márgenes).
    ancho_util = pagesize[0] - 30 * mm
    col_nombre = ancho_util * 0.40
    col_bucket = ancho_util * 0.12
    col_total = ancho_util * 0.12

    tbl = Table(
        rows,
        colWidths=[col_nombre, col_bucket, col_bucket, col_bucket, col_bucket, col_total],
        repeatRows=1,
    )
    tbl.setStyle(TableStyle([
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        # Buckets coloreados — 90+ rojo, 61-90 ámbar fuerte, 31-60 ámbar suave
        ("BACKGROUND", (4, 1), (4, -2), colors.HexColor("#fee2e2")),  # bucket_90_mas
        ("BACKGROUND", (3, 1), (3, -2), colors.HexColor("#fef3c7")),  # bucket_61_90
        # Totales (última fila)
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.HexColor("#0f172a")),
        # General
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    flow.append(tbl)
    doc.build(flow)
    return buf.getvalue()


def slug_filename(nombre: str | None, fallback: str) -> str:
    """Sanitiza un nombre para usarlo como filename: sin espacios, sin
    barras, máximo 50 chars. Si viene vacío, usa el fallback."""
    base = (nombre or fallback).replace(" ", "_").replace("/", "_").replace("\\", "_")
    return base[:50]
