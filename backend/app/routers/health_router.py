"""Health check endpoint para deploy / monitoreo."""

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(prefix="/api/health", tags=["health"])

_STARTED_AT = time.time()


@router.get("")
def health_check(db: Session = Depends(get_db)):
    """Devuelve 200 si la app responde y la DB está reachable.
    503 si la DB no responde — útil para load balancers o scripts de deploy."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        # No incluimos el error real para no filtrar info del stack/DB,
        # solo la categoría. Logs internos siguen capturando el detalle.
        raise HTTPException(503, "DB no responde")
    return {
        "status": "ok",
        "uptime_segundos": round(time.time() - _STARTED_AT, 1),
    }
