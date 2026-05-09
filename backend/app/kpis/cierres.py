"""Lógica de cierre de caja: cálculo de saldo histórico y verificación de bloqueo."""

import os
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session


def umbrales_auditoria_cierre() -> dict[str, Decimal]:
    """Single source of truth para tolerancia y escalado de severidad
    en la auditoría de cierres. Lo consumen tanto el endpoint
    `/api/cierres/auditoria` (default `tolerancia`) como la regla de
    alerta `cierres_con_diff` — sin esto, configurar la env var
    desincroniza alerta vs UI (la dueña ve "0" en una y "5" en la otra).

    - `tolerancia`: $diff por debajo del cual se considera ruido (default 100 ARS).
    - `umbral_critica`: si el peor diff_abs supera este valor, severidad
      pasa a CRÍTICA (default 5000 = 50× tolerancia, suficiente señal de
      problema serio en una PyME chica)."""
    return {
        "tolerancia": Decimal(str(os.getenv("UMBRAL_CIERRE_DIFF_ARS", "100"))),
        "umbral_critica": Decimal(str(os.getenv("UMBRAL_CIERRE_DIFF_CRITICO_ARS", "5000"))),
    }

from app.models.cierre_caja import CierreCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta


def saldo_caja_al(db: Session, caja: str, fecha: date) -> Decimal:
    """Saldo de una caja al CIERRE del día `fecha` (incluye ese día)."""
    fin = datetime.combine(fecha, time.max)

    ing_v1 = db.query(func.coalesce(func.sum(Venta.monto_pago1), 0)).filter(
        Venta.caja1 == caja, Venta.fecha <= fin
    ).scalar()
    ing_v2 = db.query(func.coalesce(func.sum(Venta.monto_pago2), 0)).filter(
        Venta.caja2 == caja, Venta.fecha <= fin
    ).scalar()
    ing_mov = db.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)).filter(
        MovimientoCaja.caja_destino == caja, MovimientoCaja.fecha <= fecha
    ).scalar()
    egr_mov = db.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)).filter(
        MovimientoCaja.caja_origen == caja, MovimientoCaja.fecha <= fecha
    ).scalar()

    return Decimal(str(ing_v1 or 0)) + Decimal(str(ing_v2 or 0)) \
        + Decimal(str(ing_mov or 0)) - Decimal(str(egr_mov or 0))


def fecha_ultimo_cierre(db: Session, caja: str) -> date | None:
    """Devuelve la fecha del último cierre para esa caja, o None si no hay."""
    res = db.query(func.max(CierreCaja.fecha)).filter(CierreCaja.caja == caja).scalar()
    return res


def caja_esta_bloqueada(db: Session, caja: str, fecha: date) -> bool:
    """Si existe un cierre cuya fecha >= `fecha` para esa caja, está bloqueada.

    Usa EXISTS (no MAX): si reabren un cierre intermedio, los cierres
    anteriores siguen vigentes y siguen bloqueando sus fechas. Si usara
    MAX(fecha), reabrir el último cierre desbloquearía meses anteriores
    aunque haya cierres intermedios todavía vigentes.
    """
    return db.query(CierreCaja.id).filter(
        CierreCaja.caja == caja,
        CierreCaja.fecha >= fecha,
    ).first() is not None


def auditar_cierres(
    db: Session,
    tolerancia: Decimal = Decimal("100"),
    solo_con_diff: bool = True,
) -> list[dict[str, Any]]:
    """Para cada CierreCaja, compara el saldo declarado con el saldo
    calculado al día del cierre. Devuelve los que tienen diferencia
    mayor que `tolerancia` (default $100 ARS — pequeñas redondeos no
    son señal de error).

    Útil para detectar:
    - Errores humanos al ingresar el saldo declarado en el cierre.
    - Movimientos cargados retroactivamente DESPUÉS del cierre que
      cambiaron el saldo histórico (no debería pasar por el bloqueo,
      pero si se reabrió y volvió a cerrar puede haber drift).
    - Importaciones de CSV que tocaron fechas ya cerradas.

    Si `solo_con_diff=False` devuelve todos los cierres con su diff
    (útil para reportes contables que quieren ver todos los cierres
    aunque estén OK).
    """
    cierres_q = db.query(CierreCaja).order_by(
        CierreCaja.fecha.desc(), CierreCaja.id.desc()
    ).all()

    out = []
    for c in cierres_q:
        declarado = Decimal(str(c.saldo_cierre))
        calculado = saldo_caja_al(db, c.caja, c.fecha)
        diff = calculado - declarado
        diff_abs = abs(diff)
        # `solo_con_diff` filtra por superar tolerancia (no por diff != 0):
        # con tolerancia 100, un diff de exactamente 100 NO se reporta. Esto
        # alinea con `tiene_diff` abajo que también usa `> tolerancia`.
        if solo_con_diff and diff_abs <= tolerancia:
            continue
        out.append({
            "id": c.id,
            "fecha": c.fecha.isoformat(),
            "caja": c.caja,
            "saldo_declarado": float(declarado),
            "saldo_calculado": float(calculado),
            "diff": float(diff),
            "diff_abs": float(diff_abs),
            # tiene_diff = "supera tolerancia", no "diff != 0". Un cierre
            # con diff_abs == tolerancia tiene tiene_diff=False (es ruido
            # esperable). El consumidor de `solo_con_diff=False` (auditoría
            # contable completa) puede leer este flag para sub-filtrar.
            "tiene_diff": diff_abs > tolerancia,
            "observaciones": c.observaciones,
        })
    return out


def cierres(db: Session, caja: str | None = None, limite: int = 100) -> list[dict[str, Any]]:
    q = db.query(CierreCaja).order_by(CierreCaja.fecha.desc(), CierreCaja.id.desc())
    if caja:
        q = q.filter(CierreCaja.caja == caja)
    return [
        {
            "id": c.id,
            "fecha": c.fecha.isoformat(),
            "caja": c.caja,
            "saldo_cierre": float(c.saldo_cierre),
            "observaciones": c.observaciones,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in q.limit(limite).all()
    ]
