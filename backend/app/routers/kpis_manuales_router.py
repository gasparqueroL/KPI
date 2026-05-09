"""Endpoints para gestionar KPIs cargados manualmente por la dueña.

`GET /catalogo` — devuelve el catálogo de códigos por área (lo consume el form)
`GET /` — lista todos los valores del último año (para tabla resumen)
`GET /{periodo}` — todos los valores cargados para ese mes (YYYY-MM)
`PUT /{periodo}` — bulk upsert de varios valores para un mes
`DELETE /{periodo}/{codigo}` — borra un dato puntual
"""
import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.kpis.catalogo_manuales import CATALOGO, codigos_validos, por_codigo
from app.models.kpi_manual import KpiManual

router = APIRouter(prefix="/api/kpis-manuales", tags=["kpis-manuales"])


def _validar_periodo(periodo: str) -> None:
    """YYYY-MM con validación básica."""
    if not periodo or len(periodo) != 7 or periodo[4] != "-":
        raise HTTPException(400, "Período debe ser YYYY-MM")
    try:
        anio = int(periodo[:4])
        mes = int(periodo[5:])
    except ValueError:
        raise HTTPException(400, "Período debe ser YYYY-MM")
    if not (2000 <= anio <= 2099 and 1 <= mes <= 12):
        raise HTTPException(400, "Período fuera de rango razonable")


def _validar_valor_kpi(codigo: str, valor, cat: dict) -> str | None:
    """Devuelve mensaje de error si el valor está fuera del rango definido
    por el catálogo, o None si es válido. Acepta valor como Decimal o
    numérico — convierte min/max a Decimal antes de comparar para evitar
    `Decimal vs float` que tira TypeError en algunos casos."""
    meta = cat.get(codigo)
    if meta is None:
        return f"Código desconocido: {codigo}"
    if "min_valor" in meta and Decimal(str(valor)) < Decimal(str(meta["min_valor"])):
        return f"'{codigo}' debe ser >= {meta['min_valor']} (recibido: {valor})"
    if "max_valor" in meta and Decimal(str(valor)) > Decimal(str(meta["max_valor"])):
        return f"'{codigo}' debe ser <= {meta['max_valor']} (recibido: {valor})"
    return None


# Pares (subset, total) que requieren `subset <= total`. Validación
# cruzada para evitar derivados >100% o sin sentido ("ganaste 50 pero
# cerraste 10"). Solo aplica cuando AMBOS valores se mandan en el mismo
# bulk_upsert; no chequeamos contra valores ya guardados (evita race).
PARES_COHERENCIA: list[tuple[str, str, str]] = [
    ("leads_ganados_mes", "leads_cerrados_mes", "leads_ganados <= leads_cerrados"),
    ("reclamos_recurrentes_mes", "reclamos_mes", "recurrentes <= total reclamos"),
    ("entregas_a_tiempo_mes", "entregas_total_mes", "entregas a tiempo <= entregas totales"),
    ("horas_inactividad_mes", "horas_productivas_mes", "inactividad <= horas productivas"),
    ("procesos_automatizados", "procesos_total", "automatizados <= total"),
    ("bajas_mes", "empleados_inicio_mes", "bajas <= empleados al inicio"),
]


def _validar_coherencia(values_by_codigo: dict[str, float | None]) -> str | None:
    """Cruza pares conocidos. Devuelve mensaje si hay inconsistencia,
    None si pasa. Solo valida pares donde ambos valores están presentes
    en el mismo upsert."""
    for subset_key, total_key, descripcion in PARES_COHERENCIA:
        s = values_by_codigo.get(subset_key)
        t = values_by_codigo.get(total_key)
        if s is None or t is None:
            continue
        if Decimal(str(s)) > Decimal(str(t)):
            return f"Inconsistencia: {descripcion}. Recibido {subset_key}={s}, {total_key}={t}."
    return None


def _serializar(k: KpiManual) -> dict[str, Any]:
    return {
        "periodo": k.periodo,
        "codigo": k.codigo,
        "valor": float(k.valor),
        "nota": k.nota,
        "updated_at": k.updated_at.isoformat() if k.updated_at else None,
    }


@router.get("/catalogo")
def catalogo():
    """Catálogo de códigos manuales agrupados por área. El frontend arma
    el form con esto."""
    por_area: dict[str, list[dict]] = {}
    for c in CATALOGO:
        por_area.setdefault(c["area"], []).append(c)
    return {"areas": por_area}


@router.get("")
def listar(db: Session = Depends(get_db)):
    """Todos los valores cargados, ordenados por período desc + código."""
    rows = db.query(KpiManual).order_by(
        KpiManual.periodo.desc(), KpiManual.codigo
    ).all()
    return [_serializar(r) for r in rows]


@router.get("/template-csv")
def template_csv():
    """Devuelve un CSV de ejemplo para importar — incluye los códigos
    válidos como filas comentadas con sus labels y unidades."""
    from fastapi.responses import Response
    lines = ["periodo,codigo,valor,nota"]
    lines.append("# Ejemplo: descomenta y completa. Una fila por (mes, código).")
    lines.append("# 2026-04,activos_totales,1500000,")
    lines.append("# 2026-04,nps,45,Encuesta del Q2")
    lines.append("# Códigos disponibles (label - unidad):")
    for c in CATALOGO:
        rng = ""
        if "min_valor" in c or "max_valor" in c:
            mn = c.get("min_valor", "—")
            mx = c.get("max_valor", "—")
            rng = f" (rango {mn}..{mx})"
        lines.append(f"# {c['codigo']} - {c['label']} ({c['unidad']}){rng}")
    contenido = "\n".join(lines).encode("utf-8")
    return Response(
        content=contenido,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="kpis_manuales_template.csv"'},
    )


@router.get("/{periodo}")
def por_periodo(periodo: str, db: Session = Depends(get_db)):
    """Todos los valores cargados para un período específico (YYYY-MM)."""
    _validar_periodo(periodo)
    rows = db.query(KpiManual).filter(KpiManual.periodo == periodo).all()
    return {
        "periodo": periodo,
        "valores": [_serializar(r) for r in rows],
    }


class ValorEntry(BaseModel):
    codigo: str
    valor: float | None  # None = borrar
    nota: str | None = None


class BulkUpsertBody(BaseModel):
    valores: list[ValorEntry]


@router.put("/{periodo}")
def bulk_upsert(
    periodo: str,
    data: BulkUpsertBody = Body(...),
    db: Session = Depends(get_db),
):
    """Upsert masivo de valores para un período. Si `valor` es None, borra
    el código (útil para deshacer un dato cargado por error)."""
    _validar_periodo(periodo)
    cat = por_codigo()
    for v in data.valores:
        if v.valor is None:
            if v.codigo not in cat:
                raise HTTPException(400, f"Código desconocido: {v.codigo}")
            continue
        err = _validar_valor_kpi(v.codigo, v.valor, cat)
        if err:
            raise HTTPException(400, err)
    # Validación cruzada de pares conocidos (subset <= total) DESPUÉS
    # de validar valores individuales — solo aplica si ambos valores
    # están en este mismo upsert.
    valores_dict = {v.codigo: v.valor for v in data.valores if v.valor is not None}
    err_coh = _validar_coherencia(valores_dict)
    if err_coh:
        raise HTTPException(400, err_coh)

    upserted = 0
    deleted = 0
    for v in data.valores:
        existente = db.get(KpiManual, (periodo, v.codigo))
        if v.valor is None:
            if existente is not None:
                db.delete(existente)
                deleted += 1
            continue
        if existente:
            existente.valor = Decimal(str(v.valor))
            existente.nota = v.nota
            existente.updated_at = datetime.utcnow()
        else:
            db.add(KpiManual(
                periodo=periodo,
                codigo=v.codigo,
                valor=Decimal(str(v.valor)),
                nota=v.nota,
            ))
        upserted += 1
    db.commit()
    return {"ok": True, "upserted": upserted, "deleted": deleted}


@router.post("/import-csv")
def importar_csv(
    file: UploadFile = File(..., description="CSV con columnas periodo,codigo,valor[,nota]"),
    db: Session = Depends(get_db),
):
    """Bulk import desde CSV. Una fila por (período, código). Idempotente:
    re-importar pisa el valor existente.

    Formato esperado (header obligatorio):
      periodo,codigo,valor,nota
      2026-04,activos_totales,150000,
      2026-04,nps,42,Encuesta Q2

    Atomicidad: una sola transacción al final. Filas con error de
    validación conocido (período/código/rango) se devuelven en
    `errores` SIN agregarse a la sesión — esas no abortan el import.
    Si una fila válida explota en `db.add` por una excepción inesperada
    (constraint, lock), todo el batch se descarta — la dueña re-corrige
    el CSV completo.
    """
    raw = file.file.read()
    # Probamos UTF-8 con BOM (default de Excel moderno) → cp1252 (Excel
    # español Windows, "Guardar como CSV") → latin-1 (último recurso).
    text = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(400, "Encoding del CSV no soportado (probá UTF-8)")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "periodo" not in reader.fieldnames or \
       "codigo" not in reader.fieldnames or "valor" not in reader.fieldnames:
        raise HTTPException(
            400,
            "CSV debe tener columnas: periodo, codigo, valor[, nota]. "
            f"Recibido: {reader.fieldnames}",
        )

    cat = por_codigo()
    insertados = 0
    actualizados = 0
    errores: list[dict] = []
    for i, row in enumerate(reader, start=2):  # 2 = segunda línea (después del header)
        periodo = (row.get("periodo") or "").strip()
        codigo = (row.get("codigo") or "").strip()
        valor_raw = (row.get("valor") or "").strip()
        nota = (row.get("nota") or "").strip() or None

        try:
            _validar_periodo(periodo)
        except HTTPException as e:
            errores.append({"linea": i, "motivo": e.detail, "fila": row})
            continue
        if codigo not in cat:
            errores.append({"linea": i, "motivo": f"Código desconocido: {codigo}", "fila": row})
            continue
        if not valor_raw:
            errores.append({"linea": i, "motivo": "Valor vacío", "fila": row})
            continue
        try:
            valor = Decimal(valor_raw.replace(",", "."))
        except Exception:
            errores.append({"linea": i, "motivo": f"Valor no parseable: {valor_raw!r}", "fila": row})
            continue

        err = _validar_valor_kpi(codigo, valor, cat)
        if err:
            errores.append({"linea": i, "motivo": err, "fila": row})
            continue

        existente = db.get(KpiManual, (periodo, codigo))
        if existente:
            existente.valor = valor
            existente.nota = nota
            existente.updated_at = datetime.utcnow()
            actualizados += 1
        else:
            db.add(KpiManual(
                periodo=periodo, codigo=codigo, valor=valor, nota=nota,
            ))
            insertados += 1
    db.commit()
    return {
        "ok": True,
        "insertados": insertados,
        "actualizados": actualizados,
        "errores": errores,
        "total_procesados": insertados + actualizados + len(errores),
    }


@router.delete("/{periodo}/{codigo}")
def eliminar(periodo: str, codigo: str, db: Session = Depends(get_db)):
    _validar_periodo(periodo)
    obj = db.get(KpiManual, (periodo, codigo))
    if obj is None:
        raise HTTPException(404, "Valor no encontrado")
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.get("/{periodo}/derivados.csv")
def derivados_csv(periodo: str, db: Session = Depends(get_db)):
    """Exporta los KPIs derivados de un mes como CSV: una fila por KPI
    con valor, valor del año anterior, delta %, objetivo y cumplimiento.
    Pensado para mandar al contador o archivar offline."""
    from fastapi.responses import Response
    from app.kpis import derivados as kpi_derivados
    _validar_periodo(periodo)
    r = kpi_derivados.kpis_del_mes_con_comparativa(db, periodo)
    lines = [
        "area,codigo,label,valor,unidad,valor_anterior,delta_pct,objetivo,cumple,status,formula"
    ]
    for k in r["kpis"]:
        def _str(v):
            if v is None:
                return ""
            if isinstance(v, bool):
                return "si" if v else "no"
            return str(v)
        # CSV-safe: escapar comas en label/formula con comillas dobles.
        def _q(s):
            s = str(s) if s is not None else ""
            if "," in s or '"' in s or "\n" in s:
                return '"' + s.replace('"', '""') + '"'
            return s
        lines.append(",".join([
            _q(k.get("area", "")),
            _q(k["codigo"]),
            _q(k.get("label", "")),
            _str(k.get("valor")),
            _q(k.get("unidad", "")),
            _str(k.get("valor_anterior")),
            _str(k.get("delta_pct")),
            _str(k.get("objetivo")),
            _str(k.get("cumple_objetivo")),
            _q(k.get("status", "")),
            _q(k.get("formula", "")),
        ]))
    contenido = "\n".join(lines).encode("utf-8-sig")  # BOM Excel-friendly
    return Response(
        content=contenido,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="kpis_derivados_{periodo}.csv"'},
    )


@router.get("/{periodo}/derivados")
def derivados(
    periodo: str,
    incluir_comparativa: bool = True,
    db: Session = Depends(get_db),
):
    """Computa todos los KPIs derivados (combinando manual + computado)
    para el período. Devuelve uno por KPI con status (ok/parcial/faltan).

    Si `incluir_comparativa=true` (default), agrega `valor_anterior` y
    `delta_pct` contra el mismo mes del año anterior. Costo: corre el
    cómputo 2x — desactivar si solo se quiere el snapshot del mes."""
    from app.kpis import derivados as kpi_derivados
    _validar_periodo(periodo)
    if incluir_comparativa:
        return kpi_derivados.kpis_del_mes_con_comparativa(db, periodo)
    return kpi_derivados.kpis_del_mes(db, periodo)


@router.get("/derivados/historico/{codigo}")
def historico_derivado(
    codigo: str,
    meses: int = 12,
    db: Session = Depends(get_db),
):
    """Time series de un KPI derivado en los últimos N meses (default 12).

    Performance: usa `solo_codigos={codigo}` para que `kpis_del_mes`
    salte el cómputo de los otros 30 KPIs. ~10x más rápido que computar
    todo y descartar.

    Label/unidad vienen de la lookup constante `derivados._META`, no
    del valor computado — robusto si en una iteración el código no
    aparece (por filtros internos)."""
    from datetime import date as _date
    from app.kpis import derivados as kpi_derivados
    if meses < 1 or meses > 36:
        raise HTTPException(400, "meses debe estar entre 1 y 36")

    meta = kpi_derivados.metadata(codigo)
    if meta is None:
        raise HTTPException(404, f"KPI '{codigo}' no existe")

    from app.kpis._fechas import hoy_ar
    hoy = hoy_ar()
    solo = {codigo}
    out = []
    for i in range(meses - 1, -1, -1):
        anio = hoy.year + (hoy.month - 1 - i) // 12
        mes = ((hoy.month - 1 - i) % 12) + 1
        periodo = f"{anio:04d}-{mes:02d}"
        kpis = kpi_derivados.kpis_del_mes(db, periodo, solo_codigos=solo)["kpis"]
        target = kpis[0] if kpis else None
        out.append({
            "periodo": periodo,
            "valor": target["valor"] if target else None,
            "status": target["status"] if target else "faltan",
        })
    return {
        "codigo": codigo,
        "label": meta["label"],
        "unidad": meta["unidad"],
        "puntos": out,
    }
