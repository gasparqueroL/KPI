"""Endpoints para gestionar objetivos/targets de KPIs derivados.

GET /  → todos los objetivos cargados
PUT /{codigo}  → upsert (valor + nota)
DELETE /{codigo}  → quitar objetivo
"""
import csv
import io
import logging
import time as _time
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.kpis import derivados as kpi_derivados
from app.kpis._fechas import hoy_ar
from app.kpis.derivados import metadata, mejor_si, rango_objetivo
from app.models.kpi_objetivo import KpiObjetivo


def _validar_rango_objetivo(codigo: str, valor: float) -> str | None:
    """Devuelve mensaje de error si valor está fuera del rango duro
    definido para ese KPI, o None si pasa. Rangos solo aplican a KPIs
    con techo matemático real (NPS, scores 1-10, %s con tope) — para
    KPIs sin cota lógica (ARS, ratios), acepta cualquier valor."""
    mn, mx = rango_objetivo(codigo)
    if mn is not None and valor < mn:
        return f"'{codigo}' debe ser >= {mn} (recibido: {valor})"
    if mx is not None and valor > mx:
        return f"'{codigo}' debe ser <= {mx} (recibido: {valor})"
    return None

router = APIRouter(prefix="/api/kpis-objetivos", tags=["kpis-objetivos"])


def _serializar(o: KpiObjetivo) -> dict:
    # Detectar objetivos huérfanos: si el código se eliminó del catálogo
    # de derivados en el futuro, marcamos para que el frontend muestre
    # warning + ofrezca limpiar.
    meta = metadata(o.codigo)
    return {
        "codigo": o.codigo,
        "valor_objetivo": float(o.valor_objetivo),
        "nota": o.nota,
        "mejor_si": mejor_si(o.codigo),
        "label": meta["label"] if meta else None,
        "huerfano": meta is None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


@router.get("")
def listar(db: Session = Depends(get_db)):
    rows = db.query(KpiObjetivo).order_by(KpiObjetivo.codigo).all()
    return [_serializar(o) for o in rows]


class ObjetivoBody(BaseModel):
    valor_objetivo: float
    nota: str | None = None


@router.put("/{codigo}")
def upsert(
    codigo: str,
    data: ObjetivoBody = Body(...),
    db: Session = Depends(get_db),
):
    if metadata(codigo) is None:
        raise HTTPException(404, f"KPI '{codigo}' no existe")
    err = _validar_rango_objetivo(codigo, data.valor_objetivo)
    if err:
        raise HTTPException(400, err)
    existente = db.get(KpiObjetivo, codigo)
    if existente:
        existente.valor_objetivo = Decimal(str(data.valor_objetivo))
        existente.nota = data.nota
        existente.updated_at = datetime.utcnow()
    else:
        db.add(KpiObjetivo(
            codigo=codigo,
            valor_objetivo=Decimal(str(data.valor_objetivo)),
            nota=data.nota,
        ))
    db.commit()
    _invalidar_cache_resumen()
    _invalidar_cache_heatmap()
    obj = db.get(KpiObjetivo, codigo)
    return _serializar(obj)


# Cache simple en proceso: el resumen evalúa el mes anterior cerrado
# que NO cambia hasta el día 1 de cada mes. Con 30 objetivos cargados
# son ~30-50 queries por hit. TTL 1h alcanza para el caso real (la
# dueña refresca el dashboard varias veces al día).
#
# IMPORTANTE: cache es por proceso. Funciona con uvicorn single-worker
# (el setup actual). Con `--workers 2+`, cada worker tiene su propio
# diccionario y `_invalidar_cache_resumen()` solo invalida en uno —
# los otros sirven datos viejos hasta TTL. Si se escala a múltiples
# workers, mover a Redis o usar tabla SQLite con transacción.
_resumen_cache: dict = {"ts": 0.0, "key": None, "data": None}
_RESUMEN_TTL = 3600.0


def _invalidar_cache_resumen():
    _resumen_cache["ts"] = 0.0
    _resumen_cache["key"] = None
    _resumen_cache["data"] = None


@router.get("/resumen")
def resumen(db: Session = Depends(get_db)):
    """Resumen panorámico para mostrar en /direccion: cuántos objetivos
    están cumpliendo en el mes anterior cerrado vs total cargados.
    Devuelve {total, cumplen, no_cumplen, sin_valor, periodo_evaluado}."""
    objetivos = db.query(KpiObjetivo).all()
    # Cache key: codigos cargados + última updated_at (cambia si la dueña
    # editó un objetivo). Si nada cambió, cache hit.
    key = (
        frozenset(o.codigo for o in objetivos),
        max((o.updated_at for o in objetivos if o.updated_at), default=None),
    )
    now = _time.time()
    if (_resumen_cache["key"] == key
            and (now - _resumen_cache["ts"]) < _RESUMEN_TTL):
        return _resumen_cache["data"]
    if not objetivos:
        out = {
            "total": 0, "cumplen": 0, "no_cumplen": 0, "sin_valor": 0,
            "huerfanos": 0, "periodo_evaluado": None,
        }
        _resumen_cache["ts"] = now
        _resumen_cache["key"] = key
        _resumen_cache["data"] = out
        return out
    hoy = hoy_ar()
    ultimo_mes_anterior = hoy.replace(day=1) - timedelta(days=1)
    periodo_anterior = f"{ultimo_mes_anterior.year:04d}-{ultimo_mes_anterior.month:02d}"
    codigos = {o.codigo for o in objetivos}
    objetivos_dict = {o.codigo: float(o.valor_objetivo) for o in objetivos}
    r = kpi_derivados.kpis_del_mes(db, periodo_anterior, solo_codigos=codigos)
    # Iterar sobre OBJETIVOS, no sobre el output de kpis_del_mes: si un
    # objetivo apunta a un código huérfano (eliminado del catálogo),
    # `kpis_del_mes` no devuelve nada para él — sin este iter sobre
    # objetivos, total != cumplen+no_cumplen+sin_valor (silencioso).
    kpis_por_codigo = {k["codigo"]: k for k in r["kpis"]}
    cumplen = no_cumplen = sin_valor = huerfanos = 0
    for o in objetivos:
        k = kpis_por_codigo.get(o.codigo)
        if k is None:
            # Código huérfano: el catálogo lo perdió. Sumamos a huerfanos
            # como categoría propia para que se vea explícito en /direccion.
            huerfanos += 1
            continue
        if k["valor"] is None:
            sin_valor += 1
            continue
        obj = float(o.valor_objetivo)
        if k["mejor_si"] == "bajar":
            if k["valor"] <= obj:
                cumplen += 1
            else:
                no_cumplen += 1
        else:
            if k["valor"] >= obj:
                cumplen += 1
            else:
                no_cumplen += 1
    out = {
        "total": len(objetivos),
        "cumplen": cumplen,
        "no_cumplen": no_cumplen,
        "sin_valor": sin_valor,
        "huerfanos": huerfanos,
        "periodo_evaluado": periodo_anterior,
    }
    _resumen_cache["ts"] = now
    _resumen_cache["key"] = key
    _resumen_cache["data"] = out
    return out


# Cache del heatmap: misma justificación que /resumen — el período base
# es mes anterior cerrado, no cambia hasta el día 1 del mes siguiente.
_heatmap_cache: dict = {"ts": 0.0, "key": None, "data": None}


def _invalidar_cache_heatmap():
    _heatmap_cache["ts"] = 0.0
    _heatmap_cache["key"] = None
    _heatmap_cache["data"] = None


@router.get("/heatmap")
def heatmap(meses: int = 6, db: Session = Depends(get_db)):
    """Matriz cumplimiento de objetivos × período. Devuelve los últimos
    N meses como columnas y los KPIs con objetivo cargado como filas.
    Cada celda: {valor, objetivo, cumple, status}.

    Performance: una llamada a `kpis_del_mes` por mes (con todos los
    códigos a la vez) — N queries por mes × N meses, O(N) totales.
    Cache TTL=1h igual que /resumen.
    """
    if meses < 1 or meses > 12:
        raise HTTPException(400, "meses debe estar entre 1 y 12")
    objetivos = db.query(KpiObjetivo).order_by(KpiObjetivo.codigo).all()
    # Cache key incluye `meses` además del frozenset de objetivos: si
    # se pide otro rango de meses, miss.
    key = (
        meses,
        frozenset(o.codigo for o in objetivos),
        max((o.updated_at for o in objetivos if o.updated_at), default=None),
    )
    now = _time.time()
    if (_heatmap_cache["key"] == key
            and (now - _heatmap_cache["ts"]) < _RESUMEN_TTL):
        return _heatmap_cache["data"]

    if not objetivos:
        out = {"periodos": [], "kpis": []}
        _heatmap_cache["ts"] = now
        _heatmap_cache["key"] = key
        _heatmap_cache["data"] = out
        return out

    objetivos_dict = {o.codigo: float(o.valor_objetivo) for o in objetivos}
    codigos = set(objetivos_dict.keys())

    # Generar lista de períodos (más viejo a más reciente).
    hoy = hoy_ar()
    # Empezamos desde el mes anterior cerrado (no el mes en curso, igual
    # que /resumen) y vamos hacia atrás.
    base = hoy.replace(day=1) - timedelta(days=1)  # último día del mes anterior
    periodos = []
    for i in range(meses - 1, -1, -1):
        anio = base.year + (base.month - 1 - i) // 12
        mes = ((base.month - 1 - i) % 12) + 1
        periodos.append(f"{anio:04d}-{mes:02d}")

    # Computar todos los KPIs por mes — solo_codigos limita el cómputo.
    por_mes: dict[str, dict[str, dict]] = {}
    for p in periodos:
        r = kpi_derivados.kpis_del_mes(db, p, solo_codigos=codigos)
        por_mes[p] = {k["codigo"]: k for k in r["kpis"]}

    # Armar filas: una por código (huérfanos al final con flag).
    kpis_out = []
    for o in objetivos:
        meta = metadata(o.codigo)
        celdas = []
        for p in periodos:
            k = por_mes[p].get(o.codigo)
            if k is None or k["valor"] is None:
                celdas.append({
                    "periodo": p, "valor": None, "objetivo": objetivos_dict[o.codigo],
                    "cumple": None, "status": "faltan",
                })
                continue
            obj = objetivos_dict[o.codigo]
            cumple = (k["valor"] <= obj) if k["mejor_si"] == "bajar" else (k["valor"] >= obj)
            celdas.append({
                "periodo": p, "valor": k["valor"], "objetivo": obj,
                "cumple": cumple, "status": "ok",
            })
        kpis_out.append({
            "codigo": o.codigo,
            "label": meta["label"] if meta else o.codigo,
            "area": meta["area"] if meta else "—",
            "unidad": meta["unidad"] if meta else "",
            "mejor_si": mejor_si(o.codigo),
            "huerfano": meta is None,
            "celdas": celdas,
        })
    # Orden estable: por área (alfabético) → label. Mejor UX que el
    # orden de inserción (impredecible) y agrupa visualmente.
    kpis_out.sort(key=lambda k: (k["area"], k["label"]))
    out = {"periodos": periodos, "kpis": kpis_out}
    _heatmap_cache["ts"] = now
    _heatmap_cache["key"] = key
    _heatmap_cache["data"] = out
    return out


@router.get("/template-csv")
def template_csv():
    """Template CSV para cargar objetivos en bulk."""
    lines = ["codigo,valor_objetivo,nota"]
    lines.append("# Una fila por KPI con su target. Ejemplo:")
    lines.append("# nps,50,Mejorar atencion al cliente")
    lines.append("# rotacion,10,Limite tolerable de rotacion")
    lines.append("# Códigos disponibles (label - mejor_si):")
    for codigo, meta in kpi_derivados.todos_los_codigos():
        # Reusar `mejor_si` evita drift: si en el futuro se agrega un KPI
        # a MENOS_ES_MEJOR en derivados.py, el template muestra el operador
        # correcto sin tener que duplicar el set acá.
        ms = mejor_si(codigo)
        op = "≤" if ms == "bajar" else "≥"
        lines.append(f"# {codigo} - {meta['label']} (cumple si valor {op} target)")
    contenido = "\n".join(lines).encode("utf-8")
    return Response(
        content=contenido,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="kpis_objetivos_template.csv"'},
    )


@router.post("/import-csv")
def importar_csv(
    file: UploadFile = File(..., description="CSV con columnas codigo,valor_objetivo[,nota]"),
    db: Session = Depends(get_db),
):
    """Bulk import de objetivos. Una fila por código. Idempotente:
    re-importar pisa el target existente. Atomicidad: una sola transacción
    al final; filas con error conocido no se agregan a la sesión."""
    raw = file.file.read()
    text = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(400, "Encoding del CSV no soportado")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "codigo" not in reader.fieldnames or \
       "valor_objetivo" not in reader.fieldnames:
        raise HTTPException(
            400,
            "CSV debe tener columnas: codigo, valor_objetivo[, nota]. "
            f"Recibido: {reader.fieldnames}",
        )
    insertados = 0
    actualizados = 0
    errores: list[dict] = []
    for i, row in enumerate(reader, start=2):
        codigo = (row.get("codigo") or "").strip()
        v_raw = (row.get("valor_objetivo") or "").strip()
        nota = (row.get("nota") or "").strip() or None
        if not codigo:
            errores.append({"linea": i, "motivo": "Código vacío", "fila": row})
            continue
        if metadata(codigo) is None:
            errores.append({"linea": i, "motivo": f"Código desconocido: {codigo}", "fila": row})
            continue
        if not v_raw:
            errores.append({"linea": i, "motivo": "valor_objetivo vacío", "fila": row})
            continue
        try:
            valor = Decimal(v_raw.replace(",", "."))
        except Exception:
            errores.append({"linea": i, "motivo": f"Valor no parseable: {v_raw!r}", "fila": row})
            continue
        err = _validar_rango_objetivo(codigo, float(valor))
        if err:
            errores.append({"linea": i, "motivo": err, "fila": row})
            continue
        existente = db.get(KpiObjetivo, codigo)
        if existente:
            existente.valor_objetivo = valor
            existente.nota = nota
            existente.updated_at = datetime.utcnow()
            actualizados += 1
        else:
            db.add(KpiObjetivo(codigo=codigo, valor_objetivo=valor, nota=nota))
            insertados += 1
    # Atomicidad real: TODO o NADA. Si el commit falla por integridad,
    # las filas válidas también se descartan — la dueña reintenta con
    # CSV corregido. Errores de validación (formato, código, parseo)
    # no llegan a la sesión.
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logging.getLogger("kpi").exception("Commit del import objetivos falló")
        raise HTTPException(500, f"Error al persistir: {e}")
    _invalidar_cache_resumen()
    _invalidar_cache_heatmap()
    return {
        "ok": True,
        "insertados": insertados,
        "actualizados": actualizados,
        "errores": errores,
    }


@router.delete("/{codigo}")
def eliminar(codigo: str, db: Session = Depends(get_db)):
    obj = db.get(KpiObjetivo, codigo)
    if obj is None:
        raise HTTPException(404, "Objetivo no encontrado")
    db.delete(obj)
    db.commit()
    _invalidar_cache_resumen()
    _invalidar_cache_heatmap()
    return {"ok": True}
