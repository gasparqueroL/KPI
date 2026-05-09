"""Endpoints de cierre de caja."""

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.kpis import cierres as kpi_cierres
from app.kpis._fechas import hoy_ar
from app.models.caja import Caja
from app.models.cierre_caja import CierreCaja
from app.routers._cache_helpers import invalida_alertas

router = APIRouter(prefix="/api/cierres", tags=["cierres"])


@router.get("")
def listar(
    caja: str | None = Query(None),
    limite: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return kpi_cierres.cierres(db, caja=caja, limite=limite)


@router.get("/auditoria")
def auditoria(
    tolerancia: float | None = Query(
        None,
        ge=0,
        description="ARS de diferencia tolerable. Si no se pasa, usa la env var UMBRAL_CIERRE_DIFF_ARS (default 100).",
    ),
    solo_con_diff: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Detecta cierres cuyo saldo declarado no coincide con el calculado.

    Causas típicas:
    - Error humano al cargar el saldo declarado.
    - Movimientos cargados retroactivamente sobre fechas ya cerradas.
    - CSV importado con filas en fechas bloqueadas.

    `tolerancia`: pequeñas diferencias de redondeo no son alertas. Sin
    parámetro usa el mismo umbral que la regla de alerta — así el contador
    de la alerta y los ítems de la UI nunca se desincronizan.
    `solo_con_diff=False`: lista TODOS los cierres con su delta (útil para
    auditoría contable completa)."""
    if tolerancia is None:
        tol = kpi_cierres.umbrales_auditoria_cierre()["tolerancia"]
    else:
        tol = Decimal(str(tolerancia))
    return kpi_cierres.auditar_cierres(
        db, tolerancia=tol, solo_con_diff=solo_con_diff
    )


@router.get("/saldo-actual")
def saldo_actual(
    caja: str = Query(..., description="nombre_normalizado de la caja"),
    fecha: date = Query(...),
    db: Session = Depends(get_db),
):
    """Calcula el saldo TEÓRICO al cierre de esa fecha. Útil para
    pre-llenar el form de cierre."""
    c = db.get(Caja, caja)
    if c is None:
        raise HTTPException(404, f"Caja '{caja}' no existe")
    if c.archivado_at is not None:
        raise HTTPException(
            400,
            f"Caja '{c.nombre_display}' está archivada. "
            "Desarchivala antes de calcular saldo / cerrar.",
        )
    saldo = kpi_cierres.saldo_caja_al(db, caja, fecha)
    return {"caja": caja, "fecha": fecha.isoformat(), "saldo_calculado": float(saldo)}


class NuevoCierre(BaseModel):
    fecha: date
    caja: str
    saldo_cierre: float | None = None
    observaciones: str | None = None


@router.post("")
@invalida_alertas
def cerrar(data: NuevoCierre, db: Session = Depends(get_db)):
    if data.fecha > hoy_ar():
        raise HTTPException(400, "No se puede cerrar caja con fecha futura.")
    caja_obj = db.get(Caja, data.caja)
    if caja_obj is None:
        raise HTTPException(404, f"Caja '{data.caja}' no existe")
    if caja_obj.archivado_at is not None:
        raise HTTPException(
            400,
            f"Caja '{caja_obj.nombre_display}' está archivada. "
            "Desarchivala antes de cerrar.",
        )

    existente = db.query(CierreCaja).filter(
        CierreCaja.fecha == data.fecha, CierreCaja.caja == data.caja
    ).first()
    if existente is not None:
        raise HTTPException(
            409,
            f"Ya hay un cierre para {data.caja} en {data.fecha.isoformat()} "
            f"(saldo {existente.saldo_cierre}).",
        )

    saldo = (
        Decimal(str(data.saldo_cierre))
        if data.saldo_cierre is not None
        else kpi_cierres.saldo_caja_al(db, data.caja, data.fecha)
    )

    c = CierreCaja(
        fecha=data.fecha, caja=data.caja, saldo_cierre=saldo,
        observaciones=data.observaciones,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {
        "ok": True, "id": c.id,
        "saldo_cierre": float(c.saldo_cierre),
        "fecha": c.fecha.isoformat(),
    }


@router.delete("/{cierre_id}")
@invalida_alertas
def reabrir(
    cierre_id: int,
    cascada: bool = Query(False, description="Si hay cierres posteriores, borrarlos también."),
    db: Session = Depends(get_db),
):
    c = db.get(CierreCaja, cierre_id)
    if c is None:
        raise HTTPException(404, "Cierre no encontrado")
    posteriores = db.query(CierreCaja).filter(
        CierreCaja.caja == c.caja,
        CierreCaja.fecha > c.fecha,
    ).all()
    if posteriores and not cascada:
        fechas = ", ".join(p.fecha.isoformat() for p in posteriores)
        raise HTTPException(
            409,
            f"Hay {len(posteriores)} cierre(s) posterior(es) en '{c.caja}' "
            f"({fechas}). Reabrí esos primero, o llamá con ?cascada=true "
            "para borrarlos todos en una sola operación."
        )
    if cascada:
        for p in posteriores:
            db.delete(p)
    db.delete(c)
    db.commit()
    return {"ok": True, "borrados": 1 + len(posteriores) if cascada else 1}
