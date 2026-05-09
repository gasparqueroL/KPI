"""Endpoints para aplicar pagos parciales a ventas (refactor sesión 4)."""

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.kpis import pagos_aplicados as kpi_pa
from app.routers._cache_helpers import invalida_alertas

router = APIRouter(prefix="/api/pagos-aplicados", tags=["pagos-aplicados"])


class AplicarPagoIn(BaseModel):
    id_pedido: str
    id_movimiento: int
    monto: float | None = None  # si None, aplica el mínimo entre saldo de venta y disponible del mov


class PagoAplicadoOut(BaseModel):
    id: int
    monto_aplicado: float


class AplicacionVenta(BaseModel):
    id_pago_aplicado: int
    id_movimiento: int
    fecha_pago: str
    tipo_operacion: str
    detalle: str | None
    caja_destino: str | None
    monto_aplicado: float
    monto_total_movimiento: float


class AplicacionMovimiento(BaseModel):
    id_pago_aplicado: int
    id_pedido: str
    fecha_venta: str
    cliente: str | None
    total_venta: float
    monto_aplicado: float


class SaldoVentaOut(BaseModel):
    saldo_venta: float
    aplicaciones: list[AplicacionVenta]


class DisponibleMovimientoOut(BaseModel):
    disponible: float
    aplicaciones: list[AplicacionMovimiento]


@router.post("", response_model=dict)
@invalida_alertas
def aplicar(data: AplicarPagoIn, db: Session = Depends(get_db)):
    try:
        monto = Decimal(str(data.monto)) if data.monto is not None else None
        p = kpi_pa.aplicar_pago(db, data.id_pedido, data.id_movimiento, monto)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            "Conflicto de concurrencia al aplicar el pago. "
            "Reintentá la operación.",
        )
    return {"ok": True, "id": p.id, "monto_aplicado": float(p.monto)}


@router.delete("/{id_pago_aplicado}")
@invalida_alertas
def desaplicar(id_pago_aplicado: int, db: Session = Depends(get_db)):
    try:
        afectados = kpi_pa.desaplicar_pago(db, id_pago_aplicado)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, **afectados}


@router.get("/venta/{id_pedido}", response_model=SaldoVentaOut)
def aplicaciones_venta(id_pedido: str, db: Session = Depends(get_db)):
    saldo = kpi_pa.saldo_venta(db, id_pedido)
    if saldo is None:
        raise HTTPException(404, f"Venta {id_pedido} no existe")
    return {
        "saldo_venta": float(saldo),
        "aplicaciones": kpi_pa.aplicaciones_de_venta(db, id_pedido),
    }


@router.get("/movimiento/{id_movimiento}", response_model=DisponibleMovimientoOut)
def aplicaciones_movimiento(id_movimiento: int, db: Session = Depends(get_db)):
    disp = kpi_pa.disponible_movimiento(db, id_movimiento)
    if disp is None:
        raise HTTPException(
            404,
            f"Movimiento {id_movimiento} no existe o no es ingreso puro "
            "(no aplica como cobranza).",
        )
    return {
        "disponible": float(disp),
        "aplicaciones": kpi_pa.aplicaciones_de_movimiento(db, id_movimiento),
    }
