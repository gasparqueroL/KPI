"""Endpoints para configurar categorías de caja y mergear cajas."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.caja import Caja
from app.models.categoria_caja import CategoriaCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta
from app.routers._cache_helpers import invalida_alertas

router = APIRouter(prefix="/api/config", tags=["configuracion"])


# ===== Categorías =====

FAMILIAS = [
    "Costo mercadería",
    "Logística / Envíos",
    "Personal",
    "Gastos fijos",
    "Gastos operativos",
    "Marketing",
    "Inversión / Capex",
    "Salud",
    "Ajustes / Pérdidas",
    "Operaciones especiales",
    "Sin clasificar",
]


class CategoriaUpdate(BaseModel):
    """PATCH parcial real: campos no enviados se preservan. Default None
    = "no tocar". Sin esto, agregar un flag nuevo al modelo + olvidarse
    de mandarlo desde el frontend lo borraría silenciosamente cada vez
    que se edita otro campo (bug detectado en review)."""
    familia: str | None = None
    excluir_flujo: bool | None = None
    es_transferencia: bool | None = None
    es_retiro: bool | None = None
    es_ingreso_operativo: bool | None = None
    es_costo_fijo: bool | None = None
    descripcion: str | None = None


@router.get("/familias")
def listar_familias():
    return FAMILIAS


@router.get("/categorias")
def listar_categorias(db: Session = Depends(get_db)):
    cats = db.query(CategoriaCaja).order_by(
        CategoriaCaja.familia, CategoriaCaja.tipo_operacion
    ).all()

    conteos = dict(
        db.query(MovimientoCaja.tipo_operacion, func.count())
        .group_by(MovimientoCaja.tipo_operacion).all()
    )
    montos = dict(
        db.query(MovimientoCaja.tipo_operacion, func.sum(MovimientoCaja.monto))
        .group_by(MovimientoCaja.tipo_operacion).all()
    )

    return [
        {
            "tipo_operacion": c.tipo_operacion,
            "familia": c.familia,
            "excluir_flujo": c.excluir_flujo,
            "es_transferencia": c.es_transferencia,
            "es_retiro": c.es_retiro,
            "es_ingreso_operativo": c.es_ingreso_operativo,
            "es_costo_fijo": c.es_costo_fijo,
            "descripcion": c.descripcion,
            "movimientos": conteos.get(c.tipo_operacion, 0),
            "monto_total": float(montos.get(c.tipo_operacion, 0) or 0),
        }
        for c in cats
    ]


@router.put("/categorias/{tipo_operacion}")
@invalida_alertas
def actualizar_categoria(
    tipo_operacion: str,
    data: CategoriaUpdate,
    db: Session = Depends(get_db),
):
    cat = db.get(CategoriaCaja, tipo_operacion)
    if cat is None:
        raise HTTPException(404, f"Categoría '{tipo_operacion}' no encontrada")
    # PATCH parcial: solo asignar campos enviados explícitamente. Como
    # `familia` y `descripcion` son nullable=True legítimamente, esos
    # se setean siempre que la request los traiga (incluso None).
    update_data = data.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(cat, k, v)
    db.commit()
    return {"ok": True, "tipo_operacion": tipo_operacion}


# ===== Cajas =====

@router.get("/cajas")
def listar_cajas(
    incluir_archivadas: bool = Query(False, description="Si False (default), oculta cajas archivadas"),
    solo_archivadas: bool = Query(False, description="Si True, lista únicamente las archivadas"),
    db: Session = Depends(get_db),
):
    q = db.query(Caja)
    if solo_archivadas:
        q = q.filter(Caja.archivado_at.isnot(None))
    elif not incluir_archivadas:
        q = q.filter(Caja.archivado_at.is_(None))
    cajas = q.order_by(Caja.nombre_display).all()

    v1 = dict(db.query(Venta.caja1, func.count()).filter(Venta.caja1.isnot(None)).group_by(Venta.caja1).all())
    v2 = dict(db.query(Venta.caja2, func.count()).filter(Venta.caja2.isnot(None)).group_by(Venta.caja2).all())
    mo = dict(db.query(MovimientoCaja.caja_origen, func.count()).filter(MovimientoCaja.caja_origen.isnot(None)).group_by(MovimientoCaja.caja_origen).all())
    md = dict(db.query(MovimientoCaja.caja_destino, func.count()).filter(MovimientoCaja.caja_destino.isnot(None)).group_by(MovimientoCaja.caja_destino).all())

    return [
        {
            "nombre_normalizado": c.nombre_normalizado,
            "nombre_display": c.nombre_display,
            "tipo": c.tipo,
            "activa": c.activa,
            "archivado_at": c.archivado_at.isoformat() if c.archivado_at else None,
            "uso_total": (v1.get(c.nombre_normalizado, 0) + v2.get(c.nombre_normalizado, 0)
                          + mo.get(c.nombre_normalizado, 0) + md.get(c.nombre_normalizado, 0)),
            "ventas_como_caja1": v1.get(c.nombre_normalizado, 0),
            "ventas_como_caja2": v2.get(c.nombre_normalizado, 0),
            "movimientos_origen": mo.get(c.nombre_normalizado, 0),
            "movimientos_destino": md.get(c.nombre_normalizado, 0),
        }
        for c in cajas
    ]


class CajaUpdate(BaseModel):
    nombre_display: str | None = None
    tipo: str | None = None
    activa: bool | None = None


@router.put("/cajas/{nombre_normalizado}")
@invalida_alertas
def actualizar_caja(
    nombre_normalizado: str,
    data: CajaUpdate,
    db: Session = Depends(get_db),
):
    c = db.get(Caja, nombre_normalizado)
    if c is None:
        raise HTTPException(404, "Caja no encontrada")
    if data.nombre_display is not None:
        c.nombre_display = data.nombre_display
    if data.tipo is not None:
        c.tipo = data.tipo
    if data.activa is not None:
        c.activa = data.activa
    db.commit()
    return {"ok": True}


class MergeRequest(BaseModel):
    desde: str  # nombre_normalizado de la caja a eliminar
    hacia: str  # nombre_normalizado de la caja que absorbe


@router.post("/cajas/merge")
@invalida_alertas
def merge_cajas(req: MergeRequest, db: Session = Depends(get_db)):
    if req.desde == req.hacia:
        raise HTTPException(400, "Origen y destino son la misma caja")
    src = db.get(Caja, req.desde)
    dst = db.get(Caja, req.hacia)
    if src is None:
        raise HTTPException(404, f"Caja origen '{req.desde}' no existe")
    if dst is None:
        raise HTTPException(404, f"Caja destino '{req.hacia}' no existe")
    if not dst.activa:
        raise HTTPException(
            400,
            f"La caja destino '{dst.nombre_display}' está inactiva. "
            "Activala antes de mergear, o elegí otra caja destino."
        )
    if dst.archivado_at is not None:
        raise HTTPException(
            400,
            f"La caja destino '{dst.nombre_display}' está archivada. "
            "Desarchivala antes de mergear, o elegí otra caja destino."
        )

    try:
        # Reasignar todas las referencias en una sola transacción
        n_v1 = db.query(Venta).filter(Venta.caja1 == req.desde).update(
            {Venta.caja1: req.hacia}, synchronize_session=False
        )
        n_v2 = db.query(Venta).filter(Venta.caja2 == req.desde).update(
            {Venta.caja2: req.hacia}, synchronize_session=False
        )
        n_mo = db.query(MovimientoCaja).filter(MovimientoCaja.caja_origen == req.desde).update(
            {MovimientoCaja.caja_origen: req.hacia}, synchronize_session=False
        )
        n_md = db.query(MovimientoCaja).filter(MovimientoCaja.caja_destino == req.desde).update(
            {MovimientoCaja.caja_destino: req.hacia}, synchronize_session=False
        )
        db.delete(src)
        db.commit()
    except Exception:
        # No filtrar el mensaje crudo: puede revelar estructura interna.
        # Loggeamos para diagnóstico y devolvemos genérico.
        import logging
        logging.exception("Error al mergear cajas")
        db.rollback()
        raise HTTPException(500, "Error al mergear cajas. Revisar logs del servidor.")

    return {
        "ok": True,
        "desde": req.desde,
        "hacia": req.hacia,
        "registros_actualizados": {
            "ventas_caja1": n_v1,
            "ventas_caja2": n_v2,
            "movimientos_origen": n_mo,
            "movimientos_destino": n_md,
        },
    }


# ===== Archivado de cajas =====

@router.post("/cajas/archivar-inactivas")
@invalida_alertas
def archivar_cajas_inactivas(db: Session = Depends(get_db)):
    """Bulk: archiva cajas que NO tienen movimientos ni ventas asociadas y
    no están ya archivadas. Pensado para limpiar las ~84 cajas vacías que
    quedan tras imports antiguos. NO toca cajas con uso (esas requieren
    decisión manual: archivar implica sacarlas del listado de saldos).

    Race-condition de un solo usuario: entre la lectura de `en_uso` y el
    UPDATE, alguien podría importar un CSV que referencia una caja
    candidata. La caja entra en uso pero igual la archivamos. Riesgo
    bajo (1 usuario humano), aceptable.
    """
    en_uso: set[str] = set()
    for col in (Venta.caja1, Venta.caja2, MovimientoCaja.caja_origen, MovimientoCaja.caja_destino):
        en_uso.update(r[0] for r in db.query(col).filter(col.isnot(None)).distinct().all())

    q = db.query(Caja).filter(Caja.archivado_at.is_(None))
    if en_uso:
        q = q.filter(~Caja.nombre_normalizado.in_(en_uso))
    candidatas = q.all()

    ahora = datetime.utcnow()
    archivadas: list[str] = []
    try:
        for c in candidatas:
            c.archivado_at = ahora
            archivadas.append(c.nombre_display)
        db.commit()
    except Exception:
        import logging
        logging.exception("Error al archivar inactivas")
        db.rollback()
        raise HTTPException(500, "Error al archivar inactivas. Revisar logs del servidor.")
    return {"ok": True, "archivadas": len(archivadas), "nombres": archivadas}


@router.post("/cajas/{nombre_normalizado}/archivar")
@invalida_alertas
def archivar_caja(nombre_normalizado: str, db: Session = Depends(get_db)):
    c = db.get(Caja, nombre_normalizado)
    if c is None:
        raise HTTPException(404, "Caja no encontrada")
    if c.archivado_at is None:
        c.archivado_at = datetime.utcnow()
        db.commit()
    return {"ok": True, "nombre_display": c.nombre_display, "archivado_at": c.archivado_at.isoformat()}


@router.post("/cajas/{nombre_normalizado}/desarchivar")
@invalida_alertas
def desarchivar_caja(nombre_normalizado: str, db: Session = Depends(get_db)):
    c = db.get(Caja, nombre_normalizado)
    if c is None:
        raise HTTPException(404, "Caja no encontrada")
    if c.archivado_at is not None:
        c.archivado_at = None
        db.commit()
    return {"ok": True, "nombre_display": c.nombre_display}
