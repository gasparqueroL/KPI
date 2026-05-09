"""Endpoints para listar/buscar/editar ventas (drill-down)."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app.core.config import TOLERANCIA_DISCREPANCIA_ARS
from app.db import get_db
from app.importers.cajas_helper import get_or_create_caja
from app.kpis.comerciales import _filtro_fecha
from app.models.venta import DetalleVenta, Venta
from app.routers._cache_helpers import invalida_alertas

router = APIRouter(prefix="/api/ventas", tags=["ventas"])


@router.get("/vendedores")
def lista_vendedores(db: Session = Depends(get_db)):
    """Vendedores únicos con conteo de pedidos."""
    rows = db.query(
        Venta.vendedor,
        func.count(Venta.id_pedido).label("pedidos"),
    ).filter(Venta.vendedor.isnot(None)).group_by(Venta.vendedor).order_by(
        func.count(Venta.id_pedido).desc()
    ).all()
    return [{"vendedor": r.vendedor, "pedidos": r.pedidos} for r in rows]


@router.get("/clientes-buscar")
def clientes_buscar(
    q: str | None = Query(None, description="texto a buscar en nombre o id"),
    limite: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Búsqueda rápida de clientes por nombre o id (para autocomplete).
    Devuelve top clientes por cantidad de pedidos si no hay query."""
    base = db.query(
        Venta.id_cliente,
        Venta.cliente,
        func.count(Venta.id_pedido).label("pedidos"),
    ).filter(Venta.id_cliente.isnot(None))

    if q:
        try:
            id_num = int(q)
            base = base.filter((Venta.cliente.ilike(f"%{q}%")) | (Venta.id_cliente == id_num))
        except ValueError:
            base = base.filter(Venta.cliente.ilike(f"%{q}%"))

    rows = base.group_by(Venta.id_cliente, Venta.cliente).order_by(
        func.count(Venta.id_pedido).desc()
    ).limit(limite).all()

    return [
        {"id_cliente": r.id_cliente, "cliente": r.cliente, "pedidos": r.pedidos}
        for r in rows
    ]


@router.get("/buscar")
def buscar(
    vendedor: str | None = Query(None),
    cliente: str | None = Query(None),
    id_cliente: int | None = Query(None),
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    limite: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Venta)
    if vendedor:
        q = q.filter(Venta.vendedor == vendedor)
    if cliente:
        q = q.filter(Venta.cliente.ilike(f"%{cliente}%"))
    if id_cliente:
        q = q.filter(Venta.id_cliente == id_cliente)
    q = _filtro_fecha(q, Venta.fecha, desde, hasta)

    total = q.count()
    rows = q.order_by(Venta.fecha.desc()).offset(offset).limit(limite).all()
    return {
        "total": total,
        "items": [
            {
                "id_pedido": v.id_pedido,
                "id_venta": v.id_venta,
                "fecha": v.fecha.isoformat(),
                "cliente": v.cliente,
                "id_cliente": v.id_cliente,
                "vendedor": v.vendedor,
                "total": float(v.total),
                "caja1": v.caja1,
                "caja2": v.caja2,
                "es_cuenta_corriente": v.es_cuenta_corriente,
                "discrepancia_pago": v.discrepancia_pago,
            }
            for v in rows
        ],
    }


class EditarVenta(BaseModel):
    cliente: str | None = None
    id_cliente: int | None = None
    vendedor: str | None = None
    total: float | None = None
    caja1: str | None = None
    monto_pago1: float | None = None
    pago_v1: bool | None = None
    caja2: str | None = None
    monto_pago2: float | None = None
    pago_v2: bool | None = None
    es_cuenta_corriente: bool | None = None
    limpiar_caja2: bool = False


@router.patch("/{id_pedido}")
@invalida_alertas
def editar_venta(
    id_pedido: str,
    data: EditarVenta,
    db: Session = Depends(get_db),
):
    v = db.get(Venta, id_pedido)
    if v is None:
        raise HTTPException(404, "Venta no encontrada")

    if data.cliente is not None:
        v.cliente = data.cliente.strip() or None
    if data.id_cliente is not None:
        v.id_cliente = data.id_cliente
    if data.vendedor is not None:
        v.vendedor = data.vendedor.strip() or None
    if data.total is not None:
        if data.total <= 0:
            raise HTTPException(400, "total debe ser > 0")
        v.total = Decimal(str(data.total))
    if data.es_cuenta_corriente is not None:
        v.es_cuenta_corriente = data.es_cuenta_corriente

    cache_cajas: dict = {}

    if data.caja1 is not None:
        if data.caja1.strip() == "":
            v.caja1 = None
        else:
            obj = get_or_create_caja(db, data.caja1, cache_cajas, [])
            v.caja1 = obj.nombre_normalizado if obj else None
    if data.monto_pago1 is not None:
        v.monto_pago1 = Decimal(str(data.monto_pago1)) if data.monto_pago1 > 0 else None
    if data.pago_v1 is not None:
        v.pago_v1 = data.pago_v1

    if data.limpiar_caja2:
        v.caja2 = None
        v.monto_pago2 = None
        v.pago_v2 = False
    else:
        if data.caja2 is not None:
            if data.caja2.strip() == "":
                v.caja2 = None
            else:
                obj = get_or_create_caja(db, data.caja2, cache_cajas, [])
                v.caja2 = obj.nombre_normalizado if obj else None
        if data.monto_pago2 is not None:
            v.monto_pago2 = Decimal(str(data.monto_pago2)) if data.monto_pago2 > 0 else None
        if data.pago_v2 is not None:
            v.pago_v2 = data.pago_v2

    # Recalcular flags derivados
    suma_pagos = (v.monto_pago1 or Decimal(0)) + (v.monto_pago2 or Decimal(0))
    v.discrepancia_pago = (
        not v.es_cuenta_corriente
        and suma_pagos > Decimal(0)
        and abs(suma_pagos - v.total) > TOLERANCIA_DISCREPANCIA_ARS
    )
    v1_ok = (not v.caja1) or v.pago_v1
    v2_ok = (not v.caja2) or v.pago_v2
    v.helper_v = bool(v1_ok and v2_ok and (v.caja1 or v.caja2))

    db.flush()
    db.commit()
    return {"ok": True, "id_pedido": id_pedido}


@router.get("/{id_venta}/detalle")
def detalle_venta(id_venta: str, db: Session = Depends(get_db)):
    venta = db.query(Venta).filter(Venta.id_venta == id_venta).first()
    if venta is None:
        raise HTTPException(404, "Venta no encontrada")
    detalle = db.query(DetalleVenta).filter(DetalleVenta.id_venta == id_venta).all()

    suma_subtotal = sum(float(d.subtotal or 0) for d in detalle)
    suma_cst = sum(float(d.cst or 0) for d in detalle if d.categoria_linea in ("mercaderia", "bonificacion"))
    margen = suma_subtotal - suma_cst

    return {
        "venta": {
            "id_pedido": venta.id_pedido,
            "id_venta": venta.id_venta,
            "fecha": venta.fecha.isoformat(),
            "cliente": venta.cliente,
            "vendedor": venta.vendedor,
            "total": float(venta.total),
            "caja1": venta.caja1,
            "monto_pago1": float(venta.monto_pago1) if venta.monto_pago1 else None,
            "caja2": venta.caja2,
            "monto_pago2": float(venta.monto_pago2) if venta.monto_pago2 else None,
            "es_cuenta_corriente": venta.es_cuenta_corriente,
            "discrepancia_pago": venta.discrepancia_pago,
        },
        "detalle": [
            {
                "producto": d.producto,
                "lista_precios": d.lista_precios,
                "cantidad": float(d.cantidad),
                "precio_unitario": float(d.precio_unitario),
                "subtotal": float(d.subtotal),
                "cst": float(d.cst) if d.cst else None,
                "categoria_linea": d.categoria_linea,
            }
            for d in detalle
        ],
        "totales": {
            "suma_subtotal": suma_subtotal,
            "suma_cst": suma_cst,
            "margen_bruto": margen,
            "margen_pct": (margen / suma_subtotal * 100) if suma_subtotal else 0,
        },
    }
