"""Endpoints para KPIs de caja/finanzas."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.kpis import caja

router = APIRouter(prefix="/api/kpis/caja", tags=["kpis-caja"])


@router.get("/resumen")
def resumen(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
):
    return caja.resumen_caja(db, desde=desde, hasta=hasta)


@router.get("/saldos")
def saldos(db: Session = Depends(get_db)):
    return caja.saldos_por_caja(db)


@router.get("/saldo-total")
def saldo_total(db: Session = Depends(get_db)):
    return caja.saldo_total(db)


@router.get("/flujo")
def flujo(
    periodo: str = Query("mes", regex="^(dia|semana|mes|anio)$"),
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
):
    try:
        return caja.flujo_caja(db, periodo=periodo, desde=desde, hasta=hasta)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/actividad-dia")
def actividad_dia(
    fecha: date | None = Query(None, description="YYYY-MM-DD. Default: hoy AR"),
    db: Session = Depends(get_db),
):
    """Resumen rápido de actividad del día (ventas, cobros, gastos, top familias)."""
    # Coherencia con `/api/caja-diaria/resumen-diario.pdf`: fecha futura → 400
    # en lugar de devolver ceros silenciosos (la dueña confunde "0 hoy" con
    # "no hay datos" cuando en realidad pidió un día que aún no existe).
    from app.kpis._fechas import hoy_ar
    if fecha is not None and fecha > hoy_ar():
        raise HTTPException(400, "fecha futura: no hay actividad para reportar")
    return caja.actividad_dia(db, fecha=fecha)


@router.get("/movimientos-por-familia")
def movimientos_por_familia(
    familia: str = Query(..., min_length=1),
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    limite: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Drill-down de gastos: movimientos individuales de una familia.
    Alimenta el modal del pie chart de composición."""
    return caja.movimientos_por_familia(
        db, familia=familia, desde=desde, hasta=hasta, limite=limite,
    )


@router.get("/composicion-gastos")
def composicion_gastos(
    agrupar_por: str = Query("familia", regex="^(tipo_operacion|familia)$"),
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    incluir_transferencias: bool = Query(False),
    incluir_retiros: bool = Query(False),
    db: Session = Depends(get_db),
):
    try:
        return caja.composicion_gastos(
            db, desde=desde, hasta=hasta, agrupar_por=agrupar_por,
            incluir_transferencias=incluir_transferencias,
            incluir_retiros=incluir_retiros,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/top-gastos")
def top_gastos(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    limite: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return caja.top_gastos(db, desde=desde, hasta=hasta, limite=limite)
