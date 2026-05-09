"""Endpoint de alertas automáticas con cache TTL."""

import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.kpis.alertas import evaluar_alertas

router = APIRouter(prefix="/api/alertas", tags=["alertas"])

# Cache simple: {"data": ..., "ts": ...}
# Las alertas se evaluan con queries pesadas; el frontend pollea cada 60s
# desde toda página, así que cachear con TTL corto baja drásticamente la carga.
_CACHE_TTL = 30  # segundos
_cache: dict = {"data": None, "ts": 0.0}


def _construir_payload(db: Session) -> dict:
    alertas = evaluar_alertas(db)
    return {
        "total": len(alertas),
        "criticas": sum(1 for a in alertas if a["severidad"] == "critica"),
        "atencion": sum(1 for a in alertas if a["severidad"] == "atencion"),
        "info": sum(1 for a in alertas if a["severidad"] == "info"),
        "alertas": alertas,
    }


def obtener_alertas_cacheadas(db: Session) -> list[dict]:
    """Devuelve solo la lista de alertas, usando el cache TTL.

    Sirve para callers que NO necesitan el payload con totales/severidad
    (p.ej. el reporte mensual PDF). Garantiza no re-computar las queries
    pesadas si el cache está caliente."""
    now = time.time()
    if _cache["data"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]["alertas"]
    payload = _construir_payload(db)
    _cache["data"] = payload
    _cache["ts"] = now
    return payload["alertas"]


@router.get("")
def listar(
    refresh: bool = Query(False, description="Ignorar cache y recomputar"),
    db: Session = Depends(get_db),
):
    now = time.time()
    if not refresh and _cache["data"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    payload = _construir_payload(db)
    _cache["data"] = payload
    _cache["ts"] = now
    return payload


def invalidar_cache():
    """Llamar después de operaciones que cambian las alertas (import, asignar, etc.)."""
    _cache["data"] = None
    _cache["ts"] = 0.0
