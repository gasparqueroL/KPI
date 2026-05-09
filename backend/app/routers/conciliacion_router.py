"""Endpoints de conciliación facturado vs ingreso real."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.kpis import conciliacion

router = APIRouter(prefix="/api/conciliacion", tags=["conciliacion"])


@router.get("/resumen")
def resumen(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
):
    return conciliacion.conciliacion(db, desde=desde, hasta=hasta)


@router.get("/discrepancias")
def discrepancias(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    limite: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return conciliacion.lista_discrepancias(db, desde=desde, hasta=hasta, limite=limite, offset=offset)


@router.get("/cta-cte-emitidas")
def cta_cte_emitidas(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    limite: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Ventas EMITIDAS como cuenta corriente en el período (no descuenta cobranzas)."""
    return conciliacion.cuentas_corrientes_emitidas(db, desde=desde, hasta=hasta, limite=limite)


# Endpoint legacy — redirige a la versión renombrada
@router.get("/cuentas-corrientes", deprecated=True)
def cuentas_corrientes(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    limite: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return conciliacion.cuentas_corrientes_emitidas(db, desde=desde, hasta=hasta, limite=limite)


@router.get("/sin-cobro")
def sin_cobro(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    limite: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return conciliacion.lista_sin_cobro(db, desde=desde, hasta=hasta, limite=limite, offset=offset)
