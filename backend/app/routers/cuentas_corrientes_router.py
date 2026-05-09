"""Endpoints de cuentas corrientes por cliente."""

import csv
import io
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.kpis import cuentas_corrientes as kpi_cc
from app.models.categoria_caja import CategoriaCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta
from app.routers._cache_helpers import invalida_alertas
from app.routers._pdf_extracto import render_aging_pdf, render_extracto_pdf, slug_filename

router = APIRouter(prefix="/api/cuentas-corrientes", tags=["cuentas-corrientes"])


@router.get("/clientes")
def listar_clientes(db: Session = Depends(get_db)):
    return kpi_cc.clientes_con_cuenta(db)


@router.get("/{id_cliente}/ledger")
def ledger(id_cliente: int, db: Session = Depends(get_db)):
    # 404 si no hay ningún registro de ese cliente — protege deep links a
    # IDs borrados/inválidos para que el frontend pueda mostrar toast en
    # lugar de quedar en "Cargando..." perpetuo.
    existe = db.query(Venta.id_cliente).filter(
        Venta.id_cliente == id_cliente
    ).first()
    if existe is None:
        raise HTTPException(404, "Cliente no encontrado o sin actividad registrada")
    return kpi_cc.ledger_cliente(db, id_cliente)


def _safe_csv_field(v) -> str:
    """Protege contra CSV injection (Excel/Sheets/LibreOffice ejecutan
    fórmulas si el valor empieza con =, +, -, @, tab, CR o LF) y reemplaza
    newlines embebidos por espacios para que un valor con `\\n=cmd` no
    quede en una segunda línea interpretable como fórmula por Excel."""
    if v is None:
        return ""
    s = str(v).replace("\r", " ").replace("\n", " ")
    if s and s[0] in ("=", "+", "-", "@", "\t"):
        return "'" + s
    return s


@router.get("/{id_cliente}/extracto.csv")
def extracto_csv(id_cliente: int, db: Session = Depends(get_db)):
    """Descarga el extracto del cliente como CSV (Excel-compatible)."""
    data = kpi_cc.ledger_cliente(db, id_cliente)

    buf = io.StringIO()
    # BOM (U+FEFF) para que Excel detecte UTF-8 correctamente
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";")  # ; para que Excel es-AR lo abra en columnas
    w.writerow([_safe_csv_field(f"Extracto cliente: {data['cliente']} (ID {data['id_cliente']})")])
    w.writerow([f"Saldo actual: {data['saldo_actual']:.2f}"])
    w.writerow([f"Total debe: {data['total_debe']:.2f}  -  Total haber: {data['total_haber']:.2f}"])
    w.writerow([])
    w.writerow(["Fecha", "Tipo", "Descripción", "Debe", "Haber", "Saldo"])
    for e in data["eventos"]:
        w.writerow([
            e["fecha"][:10],
            _safe_csv_field(e["tipo"]),
            _safe_csv_field(e["descripcion"]),
            f"{e['debe']:.2f}" if e["debe"] else "",
            f"{e['haber']:.2f}" if e["haber"] else "",
            f"{e['saldo']:.2f}",
        ])
    buf.seek(0)
    nombre_safe = (data["cliente"] or f"cliente_{id_cliente}").replace(" ", "_").replace("/", "_")[:50]
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="extracto_{nombre_safe}.csv"'},
    )


@router.get("/{id_cliente}/extracto.pdf")
def extracto_pdf(id_cliente: int, db: Session = Depends(get_db)):
    """Descarga el extracto del cliente como PDF (para mandar por mail/whatsapp)."""
    data = kpi_cc.ledger_cliente(db, id_cliente)
    pdf = render_extracto_pdf(
        titulo="Extracto de cuenta corriente",
        entidad={
            "id": data["id_cliente"],
            "nombre": data["cliente"],
        },
        totales={
            "saldo_actual": data["saldo_actual"],
            "total_debe": data["total_debe"],
            "total_haber": data["total_haber"],
        },
        eventos=data["eventos"],
    )
    nombre_safe = slug_filename(data["cliente"], f"cliente_{id_cliente}")
    hoy = date.today().isoformat()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="extracto_{nombre_safe}_{hoy}.pdf"'},
    )


@router.get("/aging")
def aging(db: Session = Depends(get_db)):
    return kpi_cc.aging_cobros(db)


@router.get("/aging.pdf")
def aging_pdf(db: Session = Depends(get_db)):
    """PDF imprimible del aging completo de clientes con saldo pendiente."""
    data = kpi_cc.aging_cobros(db)
    items = [
        {
            "nombre": it.get("cliente") or f"(ID {it['id_cliente']})",
            "bucket_0_30": it["bucket_0_30"],
            "bucket_31_60": it["bucket_31_60"],
            "bucket_61_90": it["bucket_61_90"],
            "bucket_90_mas": it["bucket_90_mas"],
            "total": it["total"],
        }
        for it in data["items"]
    ]
    pdf = render_aging_pdf(
        titulo="Aging de cuentas a cobrar",
        items=items,
        totales=data["totales"],
        nombre_columna="Cliente",
    )
    hoy = date.today().isoformat()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="aging_clientes_{hoy}.pdf"'},
    )


@router.get("/dso")
def dso_endpoint(
    dias: int = Query(90, ge=7, le=365),
    db: Session = Depends(get_db),
):
    return kpi_cc.dso(db, dias_ventana=dias)


@router.get("/movimientos-sin-asignar")
def movimientos_sin_asignar(
    busqueda: str | None = Query(None),
    limite: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return kpi_cc.movimientos_sin_asignar(db, busqueda=busqueda, limite=limite)


class AsignarMovimiento(BaseModel):
    id_cliente: int


@router.post("/movimiento/{movimiento_id}/asignar")
@invalida_alertas
def asignar_movimiento(
    movimiento_id: int,
    data: AsignarMovimiento,
    db: Session = Depends(get_db),
):
    m = db.get(MovimientoCaja, movimiento_id)
    if m is None:
        raise HTTPException(404, "Movimiento no encontrado")

    # Solo se pueden asignar movimientos que sean cobranzas operativas
    # (categoría flag es_ingreso_operativo) y que sean ingreso puro
    # (caja_destino presente, caja_origen vacío). Esto evita corromper el
    # ledger asignando egresos o transferencias a un cliente.
    cat = db.get(CategoriaCaja, m.tipo_operacion)
    if cat is None or not cat.es_ingreso_operativo:
        raise HTTPException(
            400,
            f"La categoría '{m.tipo_operacion}' no está marcada como ingreso operativo. "
            "Configurá el flag en Configuración → Categorías si corresponde.",
        )
    if m.caja_origen is not None or m.caja_destino is None:
        raise HTTPException(
            400,
            "Solo se pueden asignar movimientos de ingreso puro a un cliente "
            "(caja_destino presente, sin caja_origen).",
        )

    existe = db.query(Venta.id_cliente).filter(Venta.id_cliente == data.id_cliente).limit(1).first()
    if not existe:
        raise HTTPException(400, f"Cliente {data.id_cliente} no existe en ventas")

    m.id_cliente_relacionado = data.id_cliente
    db.commit()
    return {"ok": True}


@router.post("/movimiento/{movimiento_id}/desasignar")
@invalida_alertas
def desasignar_movimiento(movimiento_id: int, db: Session = Depends(get_db)):
    m = db.get(MovimientoCaja, movimiento_id)
    if m is None:
        raise HTTPException(404, "Movimiento no encontrado")
    m.id_cliente_relacionado = None
    db.commit()
    return {"ok": True}


class MarcarCtaCte(BaseModel):
    es_cuenta_corriente: bool
    forzar: bool = False


@router.post("/venta/{id_pedido}/marcar-cta-cte")
@invalida_alertas
def marcar_venta_cta_cte(
    id_pedido: str,
    data: MarcarCtaCte,
    db: Session = Depends(get_db),
):
    v = db.get(Venta, id_pedido)
    if v is None:
        raise HTTPException(404, "Venta no encontrada")

    # Si se está DESMARCANDO una venta cta cte que tiene cliente,
    # advertir si hay movimientos de cobranza vinculados al cliente que
    # podrían quedar como crédito huérfano sin esa contraparte.
    if v.es_cuenta_corriente and not data.es_cuenta_corriente and not data.forzar:
        if v.id_cliente:
            n_movs = db.query(MovimientoCaja).filter(
                MovimientoCaja.id_cliente_relacionado == v.id_cliente,
                MovimientoCaja.caja_destino.isnot(None),
            ).count()
            if n_movs > 0:
                raise HTTPException(
                    409,
                    f"El cliente tiene {n_movs} cobranzas asignadas en su ledger. "
                    "Desmarcar esta venta puede generar saldo negativo huérfano. "
                    "Re-enviar con `forzar: true` si igual querés desmarcarla.",
                )

    v.es_cuenta_corriente = data.es_cuenta_corriente
    db.commit()
    return {"ok": True}
