"""Endpoints para operación diaria de cajas: alta de movimientos,
verificación de cobros, feed de actividad reciente."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.importers.base import hash_row
from app.importers.cajas_helper import get_or_create_caja, get_or_create_categoria
from app.importers.parsing import normalize_str, parse_date_es, parse_monto
from app.kpis import caja as kpi_caja
from app.kpis._fechas import hoy_ar
from app.kpis.cierres import caja_esta_bloqueada
from app.models.caja import Caja
from app.models.categoria_caja import CategoriaCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.venta import Venta
from app.routers._cache_helpers import invalida_alertas
from app.routers._pdf_resumen_diario import render_resumen_diario_pdf

router = APIRouter(prefix="/api/caja-diaria", tags=["caja-diaria"])


# ===== Crear movimiento =====

def _verificar_no_bloqueado(db, m):
    """Si el movimiento toca una caja con cierre que cubre su fecha, raisea 403."""
    for caja in (m.caja_origen, m.caja_destino):
        if caja and caja_esta_bloqueada(db, caja, m.fecha):
            raise HTTPException(
                403,
                f"La caja '{caja}' está cerrada hasta una fecha posterior a la "
                f"del movimiento ({m.fecha.isoformat()}). Reabrí el cierre desde "
                "Cierres si necesitás editar movimientos viejos."
            )


class NuevoMovimiento(BaseModel):
    fecha: date | None = None  # default: hoy
    tipo_operacion: str
    detalle: str | None = None
    monto: float = Field(gt=0)
    caja_origen: str | None = None  # nombre_normalizado o display
    caja_destino: str | None = None
    id_cliente_relacionado: int | None = None


@router.post("/movimiento")
@invalida_alertas
def crear_movimiento(
    data: NuevoMovimiento,
    db: Session = Depends(get_db),
):
    if not data.tipo_operacion.strip():
        raise HTTPException(400, "tipo_operacion es obligatorio")
    if not data.caja_origen and not data.caja_destino:
        raise HTTPException(400, "Hay que indicar al menos caja_origen o caja_destino")

    fecha = data.fecha or hoy_ar()
    monto = Decimal(str(data.monto))
    detalle = normalize_str(data.detalle) or None

    cache_cats: dict = {}
    cache_cajas: dict = {}
    creadas_cats: list = []
    creadas_cajas: list = []

    get_or_create_categoria(db, data.tipo_operacion, cache_cats, creadas_cats)

    caja_origen_obj = (
        get_or_create_caja(db, data.caja_origen, cache_cajas, creadas_cajas)
        if data.caja_origen else None
    )
    caja_destino_obj = (
        get_or_create_caja(db, data.caja_destino, cache_cajas, creadas_cajas)
        if data.caja_destino else None
    )
    db.flush()

    origen_norm = caja_origen_obj.nombre_normalizado if caja_origen_obj else None
    destino_norm = caja_destino_obj.nombre_normalizado if caja_destino_obj else None

    # Bloqueo: no permitir alta retroactiva en cajas con cierre que cubra la fecha
    for cj in (origen_norm, destino_norm):
        if cj and caja_esta_bloqueada(db, cj, fecha):
            raise HTTPException(
                403,
                f"La caja '{cj}' tiene un cierre que cubre la fecha {fecha.isoformat()}. "
                "Reabrí el cierre desde Cierres antes de cargar movimientos retroactivos."
            )

    h = hash_row(
        fecha.isoformat(), data.tipo_operacion, detalle or "",
        str(monto), origen_norm or "", destino_norm or "",
    )

    # Si por casualidad existe el mismo movimiento (alta dos veces seguidas),
    # no crear duplicado.
    existente = db.query(MovimientoCaja).filter(MovimientoCaja.hash_dedupe == h).first()
    if existente is not None:
        raise HTTPException(409, "Ya existe un movimiento idéntico (mismo día, monto, cajas y detalle).")

    mov = MovimientoCaja(
        fecha=fecha,
        tipo_operacion=data.tipo_operacion.strip(),
        detalle=detalle,
        monto=monto,
        caja_origen=origen_norm,
        caja_destino=destino_norm,
        id_cliente_relacionado=data.id_cliente_relacionado,
        hash_dedupe=h,
    )
    db.add(mov)
    # Race: check-then-act arriba puede pasar dos veces simultáneas. El
    # UNIQUE constraint en hash_dedupe es el guard real. Atrapamos solo
    # el error específico — otros IntegrityError (FK rota, NOT NULL,
    # otros constraints futuros) deben propagarse con stack para no
    # devolver "movimiento idéntico" engañoso.
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        msg = str(getattr(e, "orig", e)).lower()
        if "hash_dedupe" in msg or "unique" in msg and "movimiento" in msg:
            raise HTTPException(409, "Ya existe un movimiento idéntico (race condition al crear).")
        # Otra violación de integridad: re-raise con detalle genérico
        # + log. No devolver 409 engañoso.
        import logging
        logging.getLogger("kpi").exception("IntegrityError en crear_movimiento")
        raise HTTPException(500, "Error de integridad al crear movimiento. Revisar logs.")
    db.refresh(mov)

    return {
        "ok": True,
        "id": mov.id,
        "fecha": mov.fecha.isoformat(),
        "cajas_creadas": creadas_cajas,
        "categorias_creadas": creadas_cats,
    }


@router.delete("/movimiento/{movimiento_id}")
@invalida_alertas
def eliminar_movimiento(movimiento_id: int, db: Session = Depends(get_db)):
    m = db.get(MovimientoCaja, movimiento_id)
    if m is None:
        raise HTTPException(404, "Movimiento no encontrado")
    _verificar_no_bloqueado(db, m)
    db.delete(m)
    db.commit()
    return {"ok": True}


class EditarMovimiento(BaseModel):
    fecha: date | None = None
    tipo_operacion: str | None = None
    detalle: str | None = None
    monto: float | None = None
    caja_origen: str | None = None  # nombre_normalizado o display
    caja_destino: str | None = None
    limpiar_caja_origen: bool = False  # explícito porque None ≠ "limpiar"
    limpiar_caja_destino: bool = False
    id_cliente_relacionado: int | None = None
    limpiar_cliente: bool = False


@router.patch("/movimiento/{movimiento_id}")
@invalida_alertas
def editar_movimiento(
    movimiento_id: int,
    data: EditarMovimiento,
    db: Session = Depends(get_db),
):
    m = db.get(MovimientoCaja, movimiento_id)
    if m is None:
        raise HTTPException(404, "Movimiento no encontrado")

    _verificar_no_bloqueado(db, m)  # estado actual

    if data.fecha is not None:
        m.fecha = data.fecha
    if data.tipo_operacion is not None:
        cache_cats: dict = {}
        get_or_create_categoria(db, data.tipo_operacion, cache_cats, [])
        m.tipo_operacion = data.tipo_operacion.strip()
    if data.detalle is not None:
        m.detalle = normalize_str(data.detalle) or None
    if data.monto is not None:
        if data.monto <= 0:
            raise HTTPException(400, "monto debe ser > 0")
        m.monto = Decimal(str(data.monto))

    cache_cajas: dict = {}
    if data.limpiar_caja_origen:
        m.caja_origen = None
    elif data.caja_origen is not None:
        obj = get_or_create_caja(db, data.caja_origen, cache_cajas, [])
        m.caja_origen = obj.nombre_normalizado if obj else None

    if data.limpiar_caja_destino:
        m.caja_destino = None
    elif data.caja_destino is not None:
        obj = get_or_create_caja(db, data.caja_destino, cache_cajas, [])
        m.caja_destino = obj.nombre_normalizado if obj else None

    if not m.caja_origen and not m.caja_destino:
        db.rollback()
        raise HTTPException(400, "El movimiento debe tener al menos caja_origen o caja_destino")

    # Estado nuevo: si bloquea, rollback antes de raise para que la sesión
    # no quede con cambios pendientes (defensivo aunque get_db descarte).
    try:
        _verificar_no_bloqueado(db, m)
    except HTTPException:
        db.rollback()
        raise

    # Cliente vinculado (cobranzas operativas)
    if hasattr(data, "id_cliente_relacionado") and data.id_cliente_relacionado is not None:
        m.id_cliente_relacionado = data.id_cliente_relacionado
    elif hasattr(data, "limpiar_cliente") and data.limpiar_cliente:
        m.id_cliente_relacionado = None

    db.flush()
    # Recomputar hash con los nuevos valores
    nuevo_hash = hash_row(
        m.fecha.isoformat(), m.tipo_operacion, m.detalle or "",
        str(m.monto), m.caja_origen or "", m.caja_destino or "",
    )
    if nuevo_hash != m.hash_dedupe:
        existente = db.query(MovimientoCaja).filter(
            MovimientoCaja.hash_dedupe == nuevo_hash,
            MovimientoCaja.id != m.id,
        ).first()
        if existente is not None:
            db.rollback()
            raise HTTPException(
                409,
                f"Ya existe otro movimiento con esos mismos datos (id={existente.id}). "
                "Cambiá algún campo (detalle, monto o fecha) para diferenciarlo."
            )
        m.hash_dedupe = nuevo_hash

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Conflicto de unicidad al guardar el movimiento.")

    return {"ok": True, "id": m.id}


# ===== Feed de movimientos recientes =====

@router.get("/movimientos-recientes")
def movimientos_recientes(
    desde: date | None = Query(None, description="default: hoy"),
    hasta: date | None = Query(None, description="default: hoy"),
    limite: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    if desde is None and hasta is None:
        desde = hasta = hoy_ar()
    elif desde and not hasta:
        hasta = hoy_ar()
    elif hasta and not desde:
        desde = hasta - timedelta(days=7)

    q = db.query(MovimientoCaja).filter(
        MovimientoCaja.fecha >= desde,
        MovimientoCaja.fecha <= hasta,
    ).order_by(desc(MovimientoCaja.id)).limit(limite)

    movs = q.all()

    # Resolver nombre del cliente vinculado para mostrar en el feed
    ids_clientes = {m.id_cliente_relacionado for m in movs if m.id_cliente_relacionado}
    nombres_cli: dict = {}
    if ids_clientes:
        for cid, cnom in db.query(Venta.id_cliente, Venta.cliente).filter(
            Venta.id_cliente.in_(ids_clientes)
        ).distinct().all():
            if cid not in nombres_cli and cnom:
                nombres_cli[cid] = cnom

    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "items": [
            {
                "id": m.id,
                "fecha": m.fecha.isoformat(),
                "tipo_operacion": m.tipo_operacion,
                "detalle": m.detalle,
                "monto": float(m.monto),
                "caja_origen": m.caja_origen,
                "caja_destino": m.caja_destino,
                "tipo": "transferencia" if (m.caja_origen and m.caja_destino) else (
                    "ingreso" if m.caja_destino else "egreso"
                ),
                "id_cliente_relacionado": m.id_cliente_relacionado,
                "cliente_nombre": nombres_cli.get(m.id_cliente_relacionado),
            }
            for m in movs
        ],
    }


# ===== Verificación de cobros =====

@router.get("/cobros-pendientes")
def cobros_pendientes(
    caja: str | None = Query(None, description="filtrar por caja (nombre_normalizado)"),
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    limite: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Ventas con al menos una caja sin verificar (pago_v1=False con caja1, o pago_v2=False con caja2)."""
    cond_caja1 = (Venta.caja1.isnot(None)) & (Venta.pago_v1 == False)
    cond_caja2 = (Venta.caja2.isnot(None)) & (Venta.pago_v2 == False)
    base = db.query(Venta).filter(cond_caja1 | cond_caja2)

    if caja:
        base = base.filter(or_(
            (Venta.caja1 == caja) & (Venta.pago_v1 == False),
            (Venta.caja2 == caja) & (Venta.pago_v2 == False),
        ))
    if desde:
        base = base.filter(Venta.fecha >= desde)
    if hasta:
        base = base.filter(Venta.fecha <= datetime.combine(hasta, datetime.max.time()))

    total = base.count()
    rows = base.order_by(Venta.fecha.desc()).offset(offset).limit(limite).all()

    items = []
    for v in rows:
        falta = []
        if v.caja1 and not v.pago_v1:
            falta.append({"caja_idx": 1, "caja": v.caja1, "monto": float(v.monto_pago1 or 0)})
        if v.caja2 and not v.pago_v2:
            falta.append({"caja_idx": 2, "caja": v.caja2, "monto": float(v.monto_pago2 or 0)})
        items.append({
            "id_pedido": v.id_pedido,
            "fecha": v.fecha.isoformat(),
            "cliente": v.cliente,
            "vendedor": v.vendedor,
            "total": float(v.total),
            "pendientes": falta,
        })
    return {"total": total, "items": items}


@router.get("/cobros-pendientes-resumen")
def cobros_pendientes_resumen(db: Session = Depends(get_db)):
    """Conteo y monto pendiente agrupado por caja."""
    from sqlalchemy import literal, union_all

    q1 = db.query(
        Venta.caja1.label("caja"),
        func.coalesce(Venta.monto_pago1, 0).label("monto"),
    ).filter(Venta.caja1.isnot(None), Venta.pago_v1 == False)

    q2 = db.query(
        Venta.caja2.label("caja"),
        func.coalesce(Venta.monto_pago2, 0).label("monto"),
    ).filter(Venta.caja2.isnot(None), Venta.pago_v2 == False)

    sub = union_all(q1, q2).subquery()
    rows = db.query(
        sub.c.caja,
        func.count().label("pendientes"),
        func.sum(sub.c.monto).label("monto"),
    ).group_by(sub.c.caja).order_by(func.sum(sub.c.monto).desc()).all()

    return [
        {"caja": r.caja, "pendientes": r.pendientes, "monto_total": float(r.monto or 0)}
        for r in rows
    ]


class VerificarItem(BaseModel):
    id_pedido: str
    caja_idx: int  # 1 o 2


class VerificarBulk(BaseModel):
    items: list[VerificarItem]


@router.post("/verificar-bulk")
@invalida_alertas
def verificar_bulk(data: VerificarBulk, db: Session = Depends(get_db)):
    """Marca múltiples cobros como verificados en una sola transacción."""
    actualizadas = 0
    for it in data.items:
        v = db.get(Venta, it.id_pedido)
        if v is None:
            continue
        if it.caja_idx == 1 and v.caja1:
            v.pago_v1 = True
        elif it.caja_idx == 2 and v.caja2:
            v.pago_v2 = True
        else:
            continue
        # Actualizar helper_v si AMBAS están verificadas (o si solo hay una)
        v1_ok = (not v.caja1) or v.pago_v1
        v2_ok = (not v.caja2) or v.pago_v2
        v.helper_v = v1_ok and v2_ok
        actualizadas += 1
    db.commit()
    return {"ok": True, "actualizadas": actualizadas}


# ===== Sugerencias para autocomplete =====

@router.get("/sugerencias")
def sugerencias(db: Session = Depends(get_db)):
    """Datos para poblar el form de nuevo movimiento."""
    cajas = db.query(Caja).filter(
        Caja.activa == True,  # noqa: E712
        Caja.archivado_at.is_(None),
    ).order_by(Caja.nombre_display).all()
    cats = db.query(CategoriaCaja).order_by(CategoriaCaja.tipo_operacion).all()

    # Top categorías más usadas (para sugerir primero)
    top_cats = db.query(
        MovimientoCaja.tipo_operacion,
        func.count().label("usos"),
    ).group_by(MovimientoCaja.tipo_operacion).order_by(desc("usos")).limit(10).all()

    return {
        "cajas": [
            {"nombre_normalizado": c.nombre_normalizado, "nombre_display": c.nombre_display, "tipo": c.tipo}
            for c in cajas
        ],
        "categorias": [
            {"tipo_operacion": c.tipo_operacion, "familia": c.familia,
             "es_transferencia": c.es_transferencia, "es_retiro": c.es_retiro}
            for c in cats
        ],
        "categorias_top": [{"tipo_operacion": r.tipo_operacion, "usos": r.usos} for r in top_cats],
    }


@router.get("/resumen-diario.pdf")
def resumen_diario_pdf(
    fecha: date | None = Query(None, description="YYYY-MM-DD. Default: hoy"),
    db: Session = Depends(get_db),
):
    """PDF de resumen del día: saldos al cierre + movimientos del día.
    Pensado para imprimir y archivar al final de la jornada."""
    if fecha is None:
        fecha = hoy_ar()
    if fecha > hoy_ar():
        raise HTTPException(400, "fecha futura: no hay movimientos para reportar")

    # Saldos al cierre del día solicitado (inclusive). Usa el helper que
    # filtra por `fecha <= fecha_corte`, así un PDF retroactivo del martes
    # impreso un jueves muestra los saldos del martes — no los del jueves.
    saldos = kpi_caja.saldos_por_caja_al(db, fecha)

    # Movimientos del día. Orden por id (refleja orden de carga, auditable).
    movs = db.query(MovimientoCaja).filter(
        MovimientoCaja.fecha == fecha
    ).order_by(MovimientoCaja.id).all()

    # Totales del día — separamos operativos de transferencias para no
    # inflar ingresos/egresos con movimientos entre cajas propias.
    ingresos = Decimal(0)
    egresos = Decimal(0)
    for m in movs:
        es_op_pura = m.caja_origen and not m.caja_destino  # egreso puro
        es_in_pura = m.caja_destino and not m.caja_origen  # ingreso puro
        if es_in_pura:
            ingresos += Decimal(str(m.monto))
        elif es_op_pura:
            egresos += Decimal(str(m.monto))
        # Transferencias (origen + destino) no cuentan como flujo neto.

    movs_dicts = [
        {
            "tipo_operacion": m.tipo_operacion,
            "detalle": m.detalle,
            "caja_origen": m.caja_origen,
            "caja_destino": m.caja_destino,
            "monto": float(m.monto),
        }
        for m in movs
    ]

    pdf = render_resumen_diario_pdf(
        fecha=fecha,
        saldos_por_caja=saldos,
        movimientos=movs_dicts,
        totales_dia={
            "ingresos_operativos": float(ingresos),
            "egresos_operativos": float(egresos),
            "neto": float(ingresos - egresos),
        },
    )
    hoy = date.today().isoformat()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="resumen_diario_{fecha.isoformat()}_{hoy}.pdf"'},
    )
