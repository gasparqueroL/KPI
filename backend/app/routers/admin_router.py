"""Endpoints administrativos: backup/restore de la BD."""

import json
import shutil
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from sqlalchemy import func, inspect

from app.core.config import DATA_DIR, DB_PATH
from app.db import Base, get_db
from app.models.cierre_caja import CierreCaja
from app.models.movimiento_caja import MovimientoCaja
from app.models.pago_aplicado import PagoAplicado
from app.models.proveedor import FacturaProveedor, Proveedor
from app.models.venta import Venta, DetalleVenta

router = APIRouter(prefix="/api/admin", tags=["admin"])

BACKUPS_DIR = DATA_DIR / "backups"
BACKUPS_DIR.mkdir(exist_ok=True)


@router.post("/backup")
def crear_backup():
    """Genera un backup .bak con timestamp y devuelve la ruta."""
    if not DB_PATH.exists():
        raise HTTPException(404, "No hay BD para respaldar")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUPS_DIR / f"kpi_{ts}.db"
    shutil.copy2(DB_PATH, dest)

    return {
        "ok": True,
        "archivo": dest.name,
        "ruta": str(dest),
        "tamaño_bytes": dest.stat().st_size,
        "creado": datetime.now().isoformat(),
    }


@router.get("/backups")
def listar_backups():
    """Lista los backups disponibles ordenados por fecha desc."""
    if not BACKUPS_DIR.exists():
        return []
    items = []
    for p in sorted(BACKUPS_DIR.glob("kpi_*.db"), reverse=True):
        st = p.stat()
        items.append({
            "archivo": p.name,
            "tamaño_bytes": st.st_size,
            "tamaño_kb": round(st.st_size / 1024, 1),
            "creado": datetime.fromtimestamp(st.st_mtime).isoformat(),
        })
    return items


@router.delete("/backups/{archivo}")
def eliminar_backup(archivo: str):
    """Borra un backup específico."""
    # Validar que el nombre sea un backup nuestro (evitar path traversal)
    if not archivo.startswith("kpi_") or not archivo.endswith(".db"):
        raise HTTPException(400, "Nombre de backup inválido")
    p = BACKUPS_DIR / archivo
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "Backup no encontrado")
    if p.resolve().parent != BACKUPS_DIR.resolve():
        raise HTTPException(400, "Ruta inválida")
    p.unlink()
    return {"ok": True, "archivo": archivo}


def backup_diario_si_corresponde() -> str | None:
    """Crea un backup automático al startup si todavía no hay uno de hoy.
    Retorna el nombre del backup creado o None si ya existía."""
    if not DB_PATH.exists():
        return None
    from app.kpis._fechas import hoy_ar
    hoy = hoy_ar().strftime("%Y%m%d")
    ya_hay = list(BACKUPS_DIR.glob(f"kpi_{hoy}_*.db"))
    if ya_hay:
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUPS_DIR / f"kpi_{ts}.db"
    shutil.copy2(DB_PATH, dest)
    return dest.name


def rotar_backups(max_retenidos: int | None = None) -> list[str]:
    """Rota backups: deja los `max_retenidos` más recientes (default 30
    o env var `BACKUPS_MAX_RETENIDOS`), borra el resto. Retorna lista
    de archivos eliminados.

    Sin esto, `data/backups/` crece sin límite — el repo ya tiene 6
    backups (~2 GB con BD de 365 MB). Con políticas de retención típicas
    (1 mes), 30 backups es razonable.
    """
    import os
    if max_retenidos is None:
        max_retenidos = int(os.getenv("BACKUPS_MAX_RETENIDOS", "30"))
    backups = sorted(BACKUPS_DIR.glob("kpi_*.db"), reverse=True)
    a_borrar = backups[max_retenidos:]
    eliminados = []
    for p in a_borrar:
        try:
            p.unlink()
            eliminados.append(p.name)
        except OSError:
            pass  # otro proceso lo borró, o permisos — log y seguir
    return eliminados


async def scheduler_backups() -> None:
    """Loop async que cada hora chequea si hace falta crear backup
    diario y rota los viejos. Lanzado en lifespan de FastAPI.

    No usa APScheduler para evitar dependencia extra: un loop simple
    `await asyncio.sleep(3600)` alcanza para el caso de uso (1 backup
    por día, retención mensual).
    """
    import asyncio
    import logging
    logger = logging.getLogger("kpi")
    while True:
        try:
            bk = backup_diario_si_corresponde()
            if bk:
                logger.info("Backup periódico creado: %s", bk)
            eliminados = rotar_backups()
            if eliminados:
                logger.info("Backups rotados (eliminados): %s", eliminados)
        except Exception as e:
            logger.exception("Error en scheduler de backups: %r", e)
        # Chequea cada hora — el guard `backup_diario_si_corresponde`
        # asegura idempotencia (1 por día, no 24).
        await asyncio.sleep(3600)


@router.post("/backups/rotar")
def endpoint_rotar(max_retenidos: int = 30):
    """Manual: aplica la política de retención. Útil para forzar
    cleanup sin esperar al scheduler."""
    if max_retenidos < 1:
        raise HTTPException(400, "max_retenidos debe ser >= 1")
    eliminados = rotar_backups(max_retenidos=max_retenidos)
    return {"ok": True, "eliminados": eliminados, "cantidad": len(eliminados)}


@router.post("/backups/{archivo}/restore")
def endpoint_restore(archivo: str):
    """Restore desde un backup. Hace una copia de seguridad ANTES del
    restore (`kpi_pre-restore_*.db`) para poder revertir."""
    if not archivo.startswith("kpi_") or not archivo.endswith(".db"):
        raise HTTPException(400, "Nombre de backup inválido")
    src = BACKUPS_DIR / archivo
    if not src.exists() or not src.is_file():
        raise HTTPException(404, "Backup no encontrado")
    if src.resolve().parent != BACKUPS_DIR.resolve():
        raise HTTPException(400, "Ruta inválida")
    if not DB_PATH.exists():
        raise HTTPException(404, "BD actual no existe — nada que restaurar sobre")
    # Snapshot antes de pisar
    pre_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pre = BACKUPS_DIR / f"kpi_pre-restore_{pre_ts}.db"
    shutil.copy2(DB_PATH, pre)
    # Restore
    shutil.copy2(src, DB_PATH)
    return {
        "ok": True,
        "restaurado_de": archivo,
        "snapshot_pre_restore": pre.name,
        "advertencia": "Reiniciá el server para que la app vea el restore.",
    }


@router.get("/auth-status")
def auth_status():
    """Indica si hay API key configurada (para debug/setup)."""
    from app.core.auth import auth_activa
    return {"auth_activa": auth_activa()}


def _serializar_modelo(obj) -> dict:
    """Convierte una row ORM a dict serializable a JSON. Incluye TODAS las
    columnas del modelo (no solo las "expuestas") porque esto es un backup
    crudo: la dueña debe poder restaurar la DB exactamente como está."""
    out = {}
    for col in inspect(obj).mapper.column_attrs:
        v = getattr(obj, col.key)
        if isinstance(v, datetime):
            # Forzamos UTC en serialización para no depender de TZ del host.
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            out[col.key] = v.isoformat()
        elif isinstance(v, date):
            out[col.key] = v.isoformat()
        elif isinstance(v, Decimal):
            out[col.key] = str(v)  # str preserva precisión, float la pierde
        else:
            out[col.key] = v
    return out


@router.get("/export.json")
def exportar_todo(db: Session = Depends(get_db)):
    """Backup completo de los datos del sistema en JSON.

    Útil para:
    - Llevarse una copia offline (mandar al contador, archivar a fin de año).
    - Migrar a otro sistema sin depender del archivo .db (que es binario).
    - Auditar el contenido completo en herramientas externas (Excel, jq).

    NO es lo mismo que `/api/admin/backup` que copia el archivo .db crudo:
    aquel es más rápido pero solo restaurable en SQLite del mismo schema.
    Este JSON es portable y legible.
    """
    tablas = {
        "ventas": Venta,
        "detalle_ventas": DetalleVenta,
        "movimientos_caja": MovimientoCaja,
        "proveedores": Proveedor,
        "facturas_proveedor": FacturaProveedor,
        "cierres_caja": CierreCaja,
        "pagos_aplicados": PagoAplicado,
    }
    payload = {
        "exportado_en": datetime.now(timezone.utc).isoformat(),
        "schema_version": "2026-05",  # mover a env/config si se versiona
        "tablas": {},
    }
    for nombre, modelo in tablas.items():
        rows = db.query(modelo).all()
        payload["tablas"][nombre] = [_serializar_modelo(r) for r in rows]
        payload["tablas"][f"{nombre}__total"] = len(rows)

    contenido = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    hoy = date.today().isoformat()
    return Response(
        content=contenido,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="kpi_export_{hoy}.json"'},
    )


@router.get("/movimientos-duplicados-sospechosos")
def movimientos_duplicados_sospechosos(db: Session = Depends(get_db)):
    """Detecta movimientos de caja que probablemente son duplicados.

    Estrategia: agrupa por `(fecha, monto, caja_origen, caja_destino,
    tipo_operacion)`. El `hash_dedupe` ya bloquea duplicados exactos en
    el import, pero un duplicado puede pasar si el detalle es distinto
    ("Pago fact 123" vs "Pago factura 123") — esos son los que detectamos.

    Solo grupos con 2+ movs. NO los borra: la dueña los inspecciona y
    decide qué hacer (puede ser un pago real al mismo proveedor el mismo
    día, no necesariamente error)."""
    rows = (
        db.query(
            MovimientoCaja.fecha,
            MovimientoCaja.monto,
            MovimientoCaja.caja_origen,
            MovimientoCaja.caja_destino,
            MovimientoCaja.tipo_operacion,
            func.count(MovimientoCaja.id).label("cantidad"),
        )
        .group_by(
            MovimientoCaja.fecha,
            MovimientoCaja.monto,
            MovimientoCaja.caja_origen,
            MovimientoCaja.caja_destino,
            MovimientoCaja.tipo_operacion,
        )
        .having(func.count(MovimientoCaja.id) >= 2)
        .all()
    )

    grupos = []
    for r in rows:
        # Cargar las filas individuales del grupo para mostrar el detalle.
        movs = (
            db.query(MovimientoCaja)
            .filter(
                MovimientoCaja.fecha == r.fecha,
                MovimientoCaja.monto == r.monto,
                MovimientoCaja.caja_origen.is_(r.caja_origen) if r.caja_origen is None else MovimientoCaja.caja_origen == r.caja_origen,
                MovimientoCaja.caja_destino.is_(r.caja_destino) if r.caja_destino is None else MovimientoCaja.caja_destino == r.caja_destino,
                MovimientoCaja.tipo_operacion == r.tipo_operacion,
            )
            .order_by(MovimientoCaja.id)
            .all()
        )
        grupos.append({
            "fecha": r.fecha.isoformat(),
            "monto": float(r.monto),
            "caja_origen": r.caja_origen,
            "caja_destino": r.caja_destino,
            "tipo_operacion": r.tipo_operacion,
            "cantidad": r.cantidad,
            "movimientos": [
                {
                    "id": m.id,
                    "detalle": m.detalle,
                    "id_cliente_relacionado": m.id_cliente_relacionado,
                    "id_factura_proveedor": m.id_factura_proveedor,
                }
                for m in movs
            ],
        })

    # Mayor monto primero (más impacto si es duplicado real).
    grupos.sort(key=lambda g: g["monto"], reverse=True)
    return {"total_grupos": len(grupos), "grupos": grupos}


@router.get("/clientes-duplicados-sospechosos")
def clientes_duplicados_sospechosos(db: Session = Depends(get_db)):
    """Detecta `id_cliente` distintos que probablemente son la misma persona
    con typos/inconsistencias en el nombre (ej. "Acme SA" vs "Acme S.A.").

    Estrategia: normaliza el nombre (lower, sin tildes, sin puntuación,
    sin sufijos comunes SA/SRL/SL/CA, espacios colapsados). Si dos ids
    normalizan al mismo string, los reportamos como grupo. Es heurística
    intencional — falsos positivos son aceptables (la dueña decide), pero
    falsos negativos (no detectar duplicado real) son lo que nos importa.

    NO fusiona: devuelve los grupos para inspección manual. La fusión
    requiere updates en Venta + MovimientoCaja + PagoAplicado y tiene
    riesgos que no resolvemos automáticamente."""
    import re
    import unicodedata

    def normalizar(nombre: str) -> str:
        if not nombre:
            return ""
        # Quitar tildes/diacríticos: "café" → "cafe"
        s = unicodedata.normalize("NFKD", nombre)
        s = "".join(c for c in s if not unicodedata.combining(c))
        s = s.lower()
        # Quitar puntuación común (puntos, comas, guiones, paréntesis)
        s = re.sub(r"[.,;:\-_/()\\]", " ", s)
        # Quitar sufijos comunes de razón social SOLO al final del nombre.
        # Anclar con `\s+...\s*$`: si no anclamos, "Don Sa Pedro" → "don pedro"
        # (matchea "Sa" en medio del nombre y agrupa con cualquier "Don Pedro").
        s = re.sub(
            r"\s+(s\s*a|s\s*r\s*l|s\s*l|c\s*a|s\s*a\s*s)\s*$",
            "",
            s,
        )
        # Colapsar espacios
        s = re.sub(r"\s+", " ", s).strip()
        return s

    # Una sola pasada agrupando por id_cliente con MAX(cliente).
    rows = (
        db.query(
            Venta.id_cliente,
            func.max(Venta.cliente).label("cliente"),
            func.count(Venta.id_pedido).label("pedidos"),
            func.coalesce(func.sum(Venta.total), 0).label("total_ventas"),
            func.max(Venta.fecha).label("ultima_venta"),
        )
        .filter(Venta.id_cliente.isnot(None), Venta.cliente.isnot(None))
        .group_by(Venta.id_cliente)
        .all()
    )

    grupos: dict[str, list[dict]] = {}
    for r in rows:
        norm = normalizar(r.cliente or "")
        if not norm:
            continue
        grupos.setdefault(norm, []).append({
            "id_cliente": r.id_cliente,
            "cliente": r.cliente,
            "pedidos": r.pedidos,
            "total_ventas": float(r.total_ventas or 0),
            "ultima_venta": r.ultima_venta.isoformat() if r.ultima_venta else None,
        })

    # Solo grupos con 2+ ids (los con 1 son únicos, no duplicados).
    sospechosos = [
        {
            "nombre_normalizado": k,
            "clientes": sorted(v, key=lambda c: c["pedidos"], reverse=True),
        }
        for k, v in grupos.items()
        if len(v) >= 2
    ]
    # Más sospechosos al inicio = los que más pedidos suman (impacto mayor).
    sospechosos.sort(
        key=lambda g: sum(c["pedidos"] for c in g["clientes"]),
        reverse=True,
    )
    return {"total_grupos": len(sospechosos), "grupos": sospechosos}


@router.get("/freeze-status")
def freeze_status(db: Session = Depends(get_db)):
    """Cuántos movimientos siguen usando el camino legacy
    `id_cliente_relacionado` sin tener `pago_aplicado` correspondiente.

    Sirve para visualizar cuán vieja es la deuda técnica del sistema dual.
    Cuando este número se acerque a 0 (todos migrados o reasignados a
    pago_aplicado), se puede ejecutar la migración B documentada en
    `docs/superpowers/plans/migracion-pago-aplicado-futura.md` con bajo
    riesgo. Si no decrece, el `<details>` del form quizás sea muy permisivo.
    """
    # Subquery: ids de movimientos que YA tienen al menos un pago_aplicado
    sub_aplicados = db.query(PagoAplicado.id_movimiento).distinct().subquery()

    legacy_total = db.query(MovimientoCaja).filter(
        MovimientoCaja.id_cliente_relacionado.isnot(None),
    ).count()
    legacy_sin_aplicar = db.query(MovimientoCaja).filter(
        MovimientoCaja.id_cliente_relacionado.isnot(None),
        MovimientoCaja.id.notin_(sub_aplicados),
    ).count()

    # `legacy_con_pago_aplicado`: NO necesariamente fueron "migrados" — un
    # movimiento puede haberse creado manualmente con ambos campos, o haber
    # recibido una aplicación posterior por la UI nueva. Lo único que afirma
    # esta cifra es que tiene cobertura granular, no migración histórica.
    return {
        "legacy_total": legacy_total,
        "legacy_sin_pago_aplicado": legacy_sin_aplicar,
        "legacy_con_pago_aplicado": legacy_total - legacy_sin_aplicar,
    }


@router.get("/ultima-actividad")
def ultima_actividad(db: Session = Depends(get_db)):
    """Última fila creada por tabla principal — proxy razonable de
    "cuándo fue el último import". No es preciso si el dueño edita una
    fila vieja (no actualiza created_at), pero para el caso típico de
    "subí el CSV de ventas hace X" funciona.

    Notas:
    - Los `created_at` se guardan en UTC (algunos modelos con
      `datetime.utcnow` naive, otros tz-aware). Para que el frontend no
      los interprete como hora local AR (UTC-3, lo cual mostraría un
      import reciente "en el futuro"), serializamos siempre con sufijo
      `Z` explícito.
    - Para `FacturaProveedor` aplicamos el mismo filtro `anulada=False`
      en última_carga y en total_filas, así el dueño no ve "0 facturas
      pero última carga: hoy" cuando todas se anularon.
    """
    def _serializar_utc(ts) -> str | None:
        if ts is None:
            return None
        if not hasattr(ts, "isoformat"):
            return str(ts)
        # Si es naive, asumimos UTC (lo que generó datetime.utcnow).
        # Si ya es aware, lo dejamos tal cual.
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()

    def _ultimo(query):
        ts = query.scalar()
        return _serializar_utc(ts)

    cant_ventas = db.query(Venta).count()
    cant_movs = db.query(MovimientoCaja).count()

    fact_q = db.query(FacturaProveedor).filter(
        FacturaProveedor.anulada == False  # noqa: E712
    )
    cant_facts = fact_q.count()

    return {
        "ventas": {
            "ultima_carga": _ultimo(db.query(func.max(Venta.created_at))),
            "total_filas": cant_ventas,
        },
        "movimientos_caja": {
            "ultima_carga": _ultimo(db.query(func.max(MovimientoCaja.created_at))),
            "total_filas": cant_movs,
        },
        "facturas_proveedor": {
            # Misma query con filtro anulada=False para consistencia.
            "ultima_carga": _ultimo(
                db.query(func.max(FacturaProveedor.created_at)).filter(
                    FacturaProveedor.anulada == False  # noqa: E712
                )
            ),
            "total_filas": cant_facts,
        },
    }


@router.get("/info")
def info_sistema():
    """Info útil: tamaño BD, # backups, etc.

    NO devolvemos el path absoluto de la BD para evitar filtrar info del
    sistema de archivos (username, estructura). Solo el nombre del archivo.
    """
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    backups = list(BACKUPS_DIR.glob("kpi_*.db")) if BACKUPS_DIR.exists() else []
    backups_size = sum(b.stat().st_size for b in backups)
    return {
        "db_existe": DB_PATH.exists(),
        "db_archivo": DB_PATH.name,  # solo nombre, no path absoluto
        "db_tamano_kb": round(db_size / 1024, 1),
        "backups_count": len(backups),
        "backups_tamano_kb": round(backups_size / 1024, 1),
        "ultimo_backup": max((b.stat().st_mtime for b in backups), default=None),
    }
