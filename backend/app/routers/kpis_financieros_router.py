"""Endpoints para los KPIs financieros computados (N1)."""
import time as _time
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.kpis import financieros

router = APIRouter(prefix="/api/kpis/financieros", tags=["kpis-financieros"])

# Cache simple para los 2 endpoints más caros (`crecimiento_sostenido`
# itera 12 meses; `punto_equilibrio` 4 queries). El usuario refresca
# /direccion varias veces — sin esto, cada F5 dispara ~80 queries.
# TTL=5min: corto porque depende de movimientos del día.
_cache: dict = {}
_TTL = 300.0


def _cached(key: tuple, fn):
    now = _time.time()
    entry = _cache.get(key)
    if entry and (now - entry[0]) < _TTL:
        return entry[1]
    data = fn()
    _cache[key] = (now, data)
    return data


def _invalidar_cache_financieros():
    """Llamar tras imports/cambios que afectan flujo. Por ahora no se
    invoca desde import_router — el TTL de 5min cubre el caso de uso."""
    _cache.clear()


@router.get("/margen-operativo")
def margen_operativo(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
):
    return financieros.margen_operativo(db, desde=desde, hasta=hasta)


@router.get("/margen-operativo-serie")
def margen_operativo_serie(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
):
    return financieros.margen_operativo_serie(db, desde=desde, hasta=hasta)


@router.get("/ebitda")
def ebitda(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
):
    return financieros.ebitda_aproximado(db, desde=desde, hasta=hasta)


@router.get("/dpo")
def dpo(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
):
    return financieros.dpo_promedio(db, desde=desde, hasta=hasta)


@router.get("/dependencia-proveedores")
def dependencia_proveedores(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    top: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return financieros.dependencia_proveedores(db, desde=desde, hasta=hasta, top=top)


@router.get("/punto-equilibrio")
def punto_equilibrio(
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
):
    return _cached(
        ("pe", desde, hasta),
        lambda: financieros.punto_equilibrio(db, desde=desde, hasta=hasta),
    )


@router.get("/crecimiento-sostenido")
def crecimiento_sostenido(
    meses: int = Query(12, ge=2, le=24),
    db: Session = Depends(get_db),
):
    return _cached(
        ("crecimiento", meses),
        lambda: financieros.crecimiento_sostenido(db, meses=meses),
    )
