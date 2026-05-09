"""Endpoints para gestionar casos a revisar (filas que no pasaron validación)."""

import json
from datetime import datetime
from typing import Any

import pandas as pd
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.importers.detalle_ventas import import_detalle_ventas
from app.importers.movimientos_caja import import_movimientos_caja
from app.importers.ventas import import_ventas
from app.models.caso_revisar import CasoRevisar
from app.routers._cache_helpers import invalida_alertas

IMPORTERS = {
    "ventas": import_ventas,
    "detalle_ventas": import_detalle_ventas,
    "movimientos_caja": import_movimientos_caja,
}

router = APIRouter(prefix="/api/casos-revisar", tags=["casos-revisar"])


def _serializar(c: CasoRevisar) -> dict[str, Any]:
    try:
        datos = json.loads(c.datos_originales) if c.datos_originales else {}
    except json.JSONDecodeError:
        datos = {"_raw": c.datos_originales}
    return {
        "id": c.id,
        "fuente": c.fuente,
        "motivo_codigo": c.motivo_codigo,
        "motivo_descripcion": c.motivo_descripcion,
        "datos_originales": datos,
        "estado": c.estado,
        "correccion": json.loads(c.correccion) if c.correccion else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        "archivado_at": c.archivado_at.isoformat() if c.archivado_at else None,
    }


@router.get("/resumen")
def resumen(db: Session = Depends(get_db)):
    """Conteos por fuente, motivo y estado. Excluye archivados; reporta
    `archivados` aparte para que la dueña vea cuántos hay sin que
    contaminen los conteos por estado."""
    activos = db.query(CasoRevisar).filter(CasoRevisar.archivado_at.is_(None))
    por_estado = dict(
        db.query(CasoRevisar.estado, func.count())
        .filter(CasoRevisar.archivado_at.is_(None))
        .group_by(CasoRevisar.estado).all()
    )
    por_fuente = [
        {"fuente": f, "motivo_codigo": m, "estado": e, "cantidad": n}
        for (f, m, e, n) in db.query(
            CasoRevisar.fuente,
            CasoRevisar.motivo_codigo,
            CasoRevisar.estado,
            func.count(),
        ).filter(CasoRevisar.archivado_at.is_(None)).group_by(
            CasoRevisar.fuente, CasoRevisar.motivo_codigo, CasoRevisar.estado
        ).order_by(func.count().desc()).all()
    ]
    archivados_count = db.query(CasoRevisar).filter(
        CasoRevisar.archivado_at.isnot(None)
    ).count()
    return {
        "total": activos.count(),
        "archivados": archivados_count,
        "por_estado": por_estado,
        "agrupado": por_fuente,
    }


@router.get("")
def listar(
    fuente: str | None = Query(None),
    estado: str | None = Query("pendiente"),
    motivo_codigo: str | None = Query(None),
    q: str | None = Query(None, description="Búsqueda libre en motivo_descripcion y datos_originales"),
    incluir_archivados: bool = Query(False, description="Si False (default), oculta los casos con archivado_at"),
    solo_archivados: bool = Query(False, description="Si True, lista únicamente los archivados"),
    limite: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(CasoRevisar)
    # Default: ocultar archivados. solo_archivados tiene precedencia para
    # que la vista "ver archivados" pueda mostrar los casos archivados.
    if solo_archivados:
        query = query.filter(CasoRevisar.archivado_at.isnot(None))
    elif not incluir_archivados:
        query = query.filter(CasoRevisar.archivado_at.is_(None))
    if fuente:
        query = query.filter(CasoRevisar.fuente == fuente)
    if estado:
        query = query.filter(CasoRevisar.estado == estado)
    if motivo_codigo:
        query = query.filter(CasoRevisar.motivo_codigo == motivo_codigo)
    if q:
        # Búsqueda case-insensitive en `motivo_descripcion` y `datos_originales`
        # (que es JSON serializado como string). Útil para encontrar casos
        # de un cliente, producto o fecha específicos sin abrir cada uno.
        # En SQLite `ilike` cae a `LIKE` case-insensitive por default.
        patron = f"%{q}%"
        query = query.filter(or_(
            CasoRevisar.motivo_descripcion.ilike(patron),
            CasoRevisar.datos_originales.ilike(patron),
        ))

    total = query.count()
    rows = query.order_by(CasoRevisar.id.desc()).offset(offset).limit(limite).all()
    return {
        "total": total,
        "limite": limite,
        "offset": offset,
        "items": [_serializar(c) for c in rows],
    }


class DescartarBulkBody(BaseModel):
    ids: list[int]


@router.post("/descartar-bulk")
@invalida_alertas
def descartar_bulk(data: DescartarBulkBody, db: Session = Depends(get_db)):
    """Descarta múltiples casos en una transacción.

    Útil cuando hay N casos del mismo motivo todos con error sistemático
    (típico tras un import problemático). En vez de descartarlos uno por
    uno, la dueña selecciona y manda un solo POST.

    No-op para IDs no encontrados o ya descartados (idempotente). Devuelve
    cuántos efectivamente se descartaron.
    """
    if not data.ids:
        raise HTTPException(400, "ids no puede estar vacío")
    if len(data.ids) > 500:
        raise HTTPException(400, "máximo 500 ids por bulk")
    n = (
        db.query(CasoRevisar)
        .filter(CasoRevisar.id.in_(data.ids), CasoRevisar.estado != "descartado")
        .update(
            {CasoRevisar.estado: "descartado", CasoRevisar.updated_at: datetime.utcnow()},
            synchronize_session=False,
        )
    )
    db.commit()
    return {"ok": True, "descartados": n}


@router.post("/archivar-resueltos")
@invalida_alertas
def archivar_resueltos(db: Session = Depends(get_db)):
    """Bulk: archiva todos los casos con estado descartado o corregido que
    NO estén ya archivados. La dueña usa esto para limpiar la lista después
    de resolver un batch grande."""
    ahora = datetime.utcnow()
    n = (
        db.query(CasoRevisar)
        .filter(
            CasoRevisar.estado.in_(["descartado", "corregido"]),
            CasoRevisar.archivado_at.is_(None),
        )
        .update(
            {CasoRevisar.archivado_at: ahora, CasoRevisar.updated_at: ahora},
            synchronize_session=False,
        )
    )
    db.commit()
    return {"ok": True, "archivados": n}


@router.get("/{caso_id}/sugerencias-caja")
def sugerencias_caja(caso_id: int, limite: int = Query(8, ge=1, le=20),
                     db: Session = Depends(get_db)):
    """Sugerencias rankeadas de cajas para resolver un caso `sin_caja`.

    Para casos de movimientos_caja con motivo sin_caja: ranking por
    `tipo_operacion` histórico (cuál es la caja_origen/caja_destino
    más usada para ese tipo). Devuelve top N candidatas.

    Decisión: agregamos `direccion` a cada sugerencia (origen/destino/
    transferencia) basada en la frecuencia con la que esa caja aparece
    como `caja_origen` vs `caja_destino` para ese tipo. Eso le permite
    al frontend pre-llenar SALIDAS o ENTRADAS sin pedirle al usuario
    que elija de qué lado.
    """
    from app.models.caja import Caja
    from app.models.movimiento_caja import MovimientoCaja

    c = db.get(CasoRevisar, caso_id)
    if c is None:
        raise HTTPException(404, "Caso no encontrado")
    if c.archivado_at is not None:
        raise HTTPException(400, "Caso archivado: desarchivá antes de pedir sugerencias")
    if c.estado != "pendiente":
        raise HTTPException(400, f"Caso ya está '{c.estado}', no admite sugerencias")
    if c.fuente != "movimientos_caja":
        return {"sugerencias": [], "razon": "Solo aplica a casos de movimientos_caja"}

    try:
        datos = json.loads(c.datos_originales) if c.datos_originales else {}
    except json.JSONDecodeError:
        datos = {}
    tipo_op = (datos.get("Tipo de Operación") or "").strip()
    if not tipo_op:
        return {"sugerencias": [], "razon": "Sin tipo_operacion en datos originales"}

    # Frecuencias: cuántas veces apareció cada caja en cada lado para este tipo.
    origen_counts = dict(
        db.query(MovimientoCaja.caja_origen, func.count())
        .filter(
            MovimientoCaja.tipo_operacion == tipo_op,
            MovimientoCaja.caja_origen.isnot(None),
        ).group_by(MovimientoCaja.caja_origen).all()
    )
    destino_counts = dict(
        db.query(MovimientoCaja.caja_destino, func.count())
        .filter(
            MovimientoCaja.tipo_operacion == tipo_op,
            MovimientoCaja.caja_destino.isnot(None),
        ).group_by(MovimientoCaja.caja_destino).all()
    )

    # Solo cajas activas (no archivadas) que aparecieron alguna vez.
    todas_norm = set(origen_counts) | set(destino_counts)
    cajas = {
        c.nombre_normalizado: c.nombre_display
        for c in db.query(Caja).filter(
            Caja.archivado_at.is_(None),
            Caja.nombre_normalizado.in_(todas_norm) if todas_norm else False,
        ).all()
    }

    sug = []
    for norm, display in cajas.items():
        n_org = origen_counts.get(norm, 0)
        n_dst = destino_counts.get(norm, 0)
        total = n_org + n_dst
        if total == 0:
            continue
        # Direccion: la mayoritaria. Si n_org domina, ponemos la caja en SALIDAS
        # (es egreso); si n_dst domina, en ENTRADAS (ingreso); empate → ambas.
        if n_org > 0 and n_dst == 0:
            direccion = "salida"
        elif n_dst > 0 and n_org == 0:
            direccion = "entrada"
        elif n_org >= n_dst * 3:
            direccion = "salida"
        elif n_dst >= n_org * 3:
            direccion = "entrada"
        else:
            direccion = "ambas"
        sug.append({
            "nombre_normalizado": norm,
            "nombre_display": display,
            "usos_origen": n_org,
            "usos_destino": n_dst,
            "total_usos": total,
            "direccion": direccion,
        })

    sug.sort(key=lambda s: s["total_usos"], reverse=True)
    return {
        "tipo_operacion": tipo_op,
        "sugerencias": sug[:limite],
    }


@router.get("/{caso_id}")
def detalle(caso_id: int, db: Session = Depends(get_db)):
    c = db.get(CasoRevisar, caso_id)
    if c is None:
        raise HTTPException(404, "Caso no encontrado")
    return _serializar(c)


@router.post("/{caso_id}/descartar")
@invalida_alertas
def descartar(caso_id: int, db: Session = Depends(get_db)):
    c = db.get(CasoRevisar, caso_id)
    if c is None:
        raise HTTPException(404, "Caso no encontrado")
    c.estado = "descartado"
    c.updated_at = datetime.utcnow()
    db.commit()
    return _serializar(c)


@router.post("/{caso_id}/marcar-pendiente")
@invalida_alertas
def marcar_pendiente(caso_id: int, db: Session = Depends(get_db)):
    c = db.get(CasoRevisar, caso_id)
    if c is None:
        raise HTTPException(404, "Caso no encontrado")
    c.estado = "pendiente"
    c.updated_at = datetime.utcnow()
    db.commit()
    return _serializar(c)


@router.post("/{caso_id}/archivar")
@invalida_alertas
def archivar(caso_id: int, db: Session = Depends(get_db)):
    """Marca un caso como archivado. No afecta su estado (descartado/corregido/
    pendiente), solo lo oculta de las vistas por default. Idempotente: si
    ya estaba archivado, no actualiza el timestamp ni updated_at."""
    c = db.get(CasoRevisar, caso_id)
    if c is None:
        raise HTTPException(404, "Caso no encontrado")
    if c.archivado_at is None:
        c.archivado_at = datetime.utcnow()
        c.updated_at = datetime.utcnow()
        db.commit()
    return _serializar(c)


@router.post("/{caso_id}/desarchivar")
@invalida_alertas
def desarchivar(caso_id: int, db: Session = Depends(get_db)):
    c = db.get(CasoRevisar, caso_id)
    if c is None:
        raise HTTPException(404, "Caso no encontrado")
    if c.archivado_at is not None:
        c.archivado_at = None
        c.updated_at = datetime.utcnow()
        db.commit()
    return _serializar(c)


@router.post("/{caso_id}/reintentar")
@invalida_alertas
def reintentar(
    caso_id: int,
    datos_corregidos: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
):
    """Reintenta importar la fila con los datos corregidos por el usuario.

    - Si pasa todas las validaciones: marca el caso como `corregido`,
      guarda los datos finales, e inserta la fila en la tabla destino.
    - Si vuelve a fallar: NO crea un caso nuevo (sería duplicado),
      devuelve el nuevo motivo y deja el caso original pendiente.
    """
    c = db.get(CasoRevisar, caso_id)
    if c is None:
        raise HTTPException(404, "Caso no encontrado")
    if c.estado != "pendiente":
        raise HTTPException(400, f"Caso ya está en estado '{c.estado}', no se puede reintentar")

    importer = IMPORTERS.get(c.fuente)
    if importer is None:
        raise HTTPException(400, f"Fuente desconocida: {c.fuente}")

    df = pd.DataFrame([datos_corregidos])
    result = importer(db, df, crear_casos=False)

    if result.aceptados >= 1:
        c.estado = "corregido"
        c.correccion = json.dumps(datos_corregidos, ensure_ascii=False)
        c.updated_at = datetime.utcnow()
        db.commit()
        return {
            "ok": True,
            "mensaje": "Fila importada correctamente",
            "caso": _serializar(c),
        }

    if result.ya_existian >= 1:
        c.estado = "corregido"
        c.correccion = json.dumps(datos_corregidos, ensure_ascii=False)
        c.motivo_descripcion = "Ya existía en BD (probable corrección de duplicado previo)"
        c.updated_at = datetime.utcnow()
        db.commit()
        return {
            "ok": True,
            "mensaje": "Ya existía en BD, marcado como resuelto",
            "caso": _serializar(c),
        }

    if result.rechazados:
        rech = result.rechazados[0]
        return {
            "ok": False,
            "mensaje": f"Sigue fallando: {rech.descripcion}",
            "nuevo_motivo_codigo": rech.motivo,
            "caso": _serializar(c),
        }

    return {
        "ok": False,
        "mensaje": "No se pudo determinar el resultado del reintento",
        "caso": _serializar(c),
    }
