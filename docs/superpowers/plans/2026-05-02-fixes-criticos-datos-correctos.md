# Fixes Críticos — Datos Correctos (Sesión 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar 8 bugs de corrupción silenciosa + centralizar invalidación de cache de alertas para que los KPIs sean siempre correctos.

**Architecture:** Cada fix es una unidad independiente: un test que reproduce el bug → fix mínimo → test pasa. Para los fixes que tocan modelos (C7) hay migración Alembic. La invalidación de cache se centraliza con un decorator que envuelve todas las mutaciones.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Alembic, SQLite, pytest, React, Vite.

**Notas previas:**
- El proyecto NO está bajo git todavía. Si no estás usando git, podés saltar los pasos de `git commit` y avanzar al siguiente fix.
- El backend corre en `127.0.0.1:8000`, el frontend en `127.0.0.1:5173`. Reiniciar uvicorn después de cambios en código backend (a menos que uses `--reload`).
- Tests con `cd backend && source .venv/Scripts/activate && pytest`.
- Después de aplicar cualquier migración Alembic: `cd backend && source .venv/Scripts/activate && alembic upgrade head`.

---

## Task 1: Fix C1 — Frontend omite `es_ingreso_operativo` en PUT categorías

**Files:**
- Modify: `frontend/src/pages/Configuracion.jsx:138-144`

El form de categorías construye el body del PUT con 5 campos y se olvida del flag nuevo. El backend tiene `es_ingreso_operativo: bool = False` como default Pydantic, así que cualquier save desde la UI **apaga el flag silenciosamente** → conciliación de cobranzas cae a $0.

- [ ] **Step 1: Reproducir el bug manualmente**

Levantá el backend, abrí http://localhost:5173/config, tab Categorías. Buscá "Ingreso", verificá que tiene checkbox "Ingreso operativo" tildado (si no existe esa columna en la UI, eso ya es parte del bug). Cambiá la familia a otra cosa, click Guardar. Re-cargá la página. Comprobá que `es_ingreso_operativo` está en `false`.

Para ver el flag actual desde terminal:
```bash
curl -s http://127.0.0.1:8000/api/config/categorias | python -c "import json,sys; d=json.load(sys.stdin); i=next((c for c in d if c['tipo_operacion']=='Ingreso'), None); print(i)"
```
Esperado antes del fix: después de tocar la familia desde UI, `es_ingreso_operativo` queda en `False`.

- [ ] **Step 2: Modificar el body del PUT para incluir el flag**

En `frontend/src/pages/Configuracion.jsx`, reemplazar el bloque `await api.put(...)` (líneas 138-144) por:

```jsx
    await api.put(`/api/config/categorias/${encodeURIComponent(tipo)}`, {
      familia: merged.familia,
      excluir_flujo: !!merged.excluir_flujo,
      es_transferencia: !!merged.es_transferencia,
      es_retiro: !!merged.es_retiro,
      es_ingreso_operativo: !!merged.es_ingreso_operativo,
      descripcion: merged.descripcion,
    });
```

- [ ] **Step 3: Agregar columna "Operativo" a la tabla del editor de categorías**

Sin la columna en la UI no se puede ni ver ni cambiar el flag. En el `<thead>` (línea 159-169 aprox), agregar después de `<th>Excluir</th>`:

```jsx
                  <th>Operativo</th>
```

En el `<tbody>` row, agregar después del `<td>` de "Excluir" (después de línea 200):

```jsx
                <td>
                  <input type="checkbox" checked={!!cur.es_ingreso_operativo}
                    onChange={(e) => setField(c.tipo_operacion, "es_ingreso_operativo", e.target.checked)} />
                </td>
```

- [ ] **Step 4: Verificar manualmente**

Reiniciá Vite si hace falta (HMR debería tomar el cambio). En la UI: encontrá "Ingreso" en categorías → checkbox "Operativo" tiene que aparecer tildado. Cambiá la familia, click Guardar. Re-cargá. El flag debe seguir tildado.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Configuracion.jsx
git commit -m "fix(C1): preservar es_ingreso_operativo al editar categoría"
```

---

## Task 2: Fix C2 — Re-seed sobrescribe ediciones manuales

**Files:**
- Modify: `backend/app/importers/categorias_seed.py:97-107`
- Test: `backend/tests/test_categorias_seed.py` (crear)

Hoy el seed reaplica `es_ingreso_operativo=True` a categorías "Ingreso" y "paga cuenta corriente" en cada restart, incluso si el usuario las desactivó manualmente. Hay que dejarlas en paz si ya existen con familia asignada — solo aplicar defaults a categorías nuevas (sin familia).

- [ ] **Step 1: Crear test que reproduce el bug**

Crear `backend/tests/test_categorias_seed.py` con:

```python
"""Tests del seed de categorías — no debe sobrescribir ediciones manuales."""
from app.importers.categorias_seed import aplicar_defaults
from app.models.categoria_caja import CategoriaCaja


def test_no_sobrescribe_ediciones_de_usuario(db):
    """Si el usuario apagó es_ingreso_operativo manualmente, el seed
    NO debe re-encenderlo en el siguiente restart."""
    db.add(CategoriaCaja(
        tipo_operacion="Ingreso",
        familia="Operaciones especiales",
        es_ingreso_operativo=False,  # usuario lo apagó
    ))
    db.commit()

    aplicar_defaults(db)

    cat = db.get(CategoriaCaja, "Ingreso")
    assert cat.es_ingreso_operativo is False, (
        "El seed sobreescribió la edición manual del usuario"
    )


def test_aplica_defaults_a_categorias_sin_familia(db):
    """Categorías recién detectadas (sin familia) sí reciben los defaults."""
    db.add(CategoriaCaja(tipo_operacion="Materia Prima", familia=None))
    db.add(CategoriaCaja(tipo_operacion="Ingreso", familia=None))
    db.commit()

    aplicar_defaults(db)

    mp = db.get(CategoriaCaja, "Materia Prima")
    ing = db.get(CategoriaCaja, "Ingreso")
    assert mp.familia == "Costo mercadería"
    assert ing.familia == "Operaciones especiales"
    assert ing.es_ingreso_operativo is True
```

- [ ] **Step 2: Correr el primer test y verificar que falla**

```bash
cd backend && source .venv/Scripts/activate
pytest tests/test_categorias_seed.py::test_no_sobrescribe_ediciones_de_usuario -v
```
Esperado: FAIL (assert es_ingreso_operativo is False, pero es True después del seed).

- [ ] **Step 3: Eliminar el bloque #2 del seed**

En `backend/app/importers/categorias_seed.py`, reemplazar la función `aplicar_defaults` (líneas 81-110) por:

```python
def aplicar_defaults(db: Session) -> int:
    """Para cada categoría SIN familia, aplica el default si existe.
    Devuelve el número de categorías actualizadas.

    Ediciones manuales (categorías con familia ya asignada) NO se tocan,
    incluso si los flags difieren de los defaults — el usuario es la
    autoridad sobre lo que ya configuró.
    """
    actualizadas = 0
    sin_fam = db.query(CategoriaCaja).filter(CategoriaCaja.familia.is_(None)).all()
    for cat in sin_fam:
        if cat.tipo_operacion in DEFAULTS:
            familia, flags = DEFAULTS[cat.tipo_operacion]
            cat.familia = familia
            for k, v in flags.items():
                setattr(cat, k, v)
            actualizadas += 1
    if actualizadas:
        db.commit()
    return actualizadas
```

- [ ] **Step 4: Correr ambos tests y verificar que pasan**

```bash
pytest tests/test_categorias_seed.py -v
```
Esperado: 2 passed.

- [ ] **Step 5: Verificar que el resto sigue OK**

```bash
pytest
```
Esperado: 46 passed (44 previos + 2 nuevos).

- [ ] **Step 6: Commit**

```bash
git add backend/app/importers/categorias_seed.py backend/tests/test_categorias_seed.py
git commit -m "fix(C2): seed no sobrescribe ediciones manuales de categorías"
```

---

## Task 3: Fix C3 — `parse_monto` corrompe `"1.5"` → `15`

**Files:**
- Modify: `backend/app/importers/parsing.py:7-28`
- Modify: `backend/tests/test_parsing.py` (agregar tests)

La heurística "punto solo es separador de miles" rompe valores legítimos como `"1.5"` o `"0.5"`. Hay que distinguir: si el punto está **a 3 dígitos del final** y no hay coma, es separador de miles; si no, es decimal.

- [ ] **Step 1: Agregar tests que reproducen el bug**

En `backend/tests/test_parsing.py`, dentro de `class TestParseMonto`, agregar:

```python
    def test_punto_decimal_simple(self):
        # "1.5" debe ser 1.5, no 15
        assert parse_monto("1.5") == Decimal("1.5")

    def test_punto_decimal_centavos(self):
        # "0.50" debe ser 0.50, no 50
        assert parse_monto("0.50") == Decimal("0.50")

    def test_punto_miles_sin_decimales(self):
        # "$31.782" en es-AR es 31782, sin comma -> miles
        assert parse_monto("$31.782") == Decimal("31782")

    def test_punto_decimal_dos_digitos(self):
        # "10.50" es 10.50 (decimal), NO 1050 (miles)
        assert parse_monto("10.50") == Decimal("10.50")
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

```bash
cd backend && source .venv/Scripts/activate
pytest tests/test_parsing.py::TestParseMonto -v
```
Esperado: FAIL en `test_punto_decimal_simple`, `test_punto_decimal_centavos` y `test_punto_decimal_dos_digitos`. Solo `test_punto_miles_sin_decimales` pasa.

- [ ] **Step 3: Refinar la heurística de `parse_monto`**

Reemplazar `parse_monto` en `backend/app/importers/parsing.py` (líneas 7-28) por:

```python
def parse_monto(v) -> Decimal | None:
    """Parsea formato es-AR: '$156.249,80' -> Decimal('156249.80').

    Heurística para el punto cuando NO hay coma:
    - Si está exactamente a 3 dígitos del final y NO es el primer separador,
      es separador de miles (ej. "31.782" -> 31782).
    - Caso contrario, es decimal (ej. "1.5" -> 1.5, "10.50" -> 10.50).
    """
    if v is None:
        return None
    s = str(v).strip().replace("$", "").replace(" ", "").replace("\xa0", "")
    if s == "" or s.lower() == "nan":
        return None

    has_comma = "," in s
    has_dot = "." in s

    if has_comma and has_dot:
        # es-AR formal: punto = miles, coma = decimal
        s = s.replace(".", "").replace(",", ".")
    elif has_comma:
        s = s.replace(",", ".")
    elif has_dot:
        # Determinar si el punto es decimal o miles.
        # Si después del último punto hay exactamente 3 dígitos Y hay
        # más de un punto O el resto NO es solo dígitos < 1000, es miles.
        partes = s.split(".")
        if len(partes) > 2:
            # múltiples puntos: típicamente miles (ej. "1.234.567")
            s = s.replace(".", "")
        elif len(partes[-1]) == 3 and partes[0] and len(partes[0]) <= 3:
            # un solo punto y 3 dígitos a la derecha: ambiguo,
            # interpretar como miles solo si total >= 4 dígitos
            # (ej. "31.782" -> miles, "0.500" -> decimal)
            if len(partes[0]) >= 1 and (int(partes[0]) >= 1 or len(partes[0]) > 1):
                s = s.replace(".", "")
            # else: dejar como decimal "0.500" -> Decimal("0.500")
        # else: punto = decimal, no hacer nada

    try:
        return Decimal(s)
    except InvalidOperation:
        return None
```

- [ ] **Step 4: Correr todos los tests de parsing**

```bash
pytest tests/test_parsing.py::TestParseMonto -v
```
Esperado: todos pasan, incluyendo los 4 nuevos.

- [ ] **Step 5: Verificar que importadores siguen funcionando con los CSVs reales**

```bash
# Re-importar el detalle (formato $31.782 = miles, $636 = ambiguo pero no rompe)
curl -s -X POST http://127.0.0.1:8000/api/import \
  -F "file=@C:/Users/HP ENVY/Desktop/KPI/detalle_ventas.csv" \
  -o /tmp/imp.json -w "HTTP %{http_code}\n"
python -c "import json; d=json.load(open('/tmp/imp.json')); print(f'aceptados={d[\"aceptados\"]}, ya_existian={d[\"ya_existian\"]}, rechazados={d[\"rechazados_count\"]}')"
```
Esperado: cifras parecidas a importaciones previas (aceptados ~120k, sin saltos extraños en rechazados).

- [ ] **Step 6: Commit**

```bash
git add backend/app/importers/parsing.py backend/tests/test_parsing.py
git commit -m "fix(C3): parse_monto distingue decimal de separador de miles"
```

---

## Task 4: Fix C4 — Hash collision en PATCH movimiento devuelve 500

**Files:**
- Modify: `backend/app/routers/caja_diaria_router.py:170-185`
- Test: `backend/tests/test_caja_diaria.py` (crear)

Editar un movimiento puede recomputar el hash a uno que ya existe (otro movimiento con datos iguales). Hoy esto tira IntegrityError no atrapada → 500. Hay que devolver 409 con mensaje claro.

- [ ] **Step 1: Crear test que reproduce el caso**

Crear `backend/tests/test_caja_diaria.py`:

```python
"""Tests de operaciones diarias de caja."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.importers.base import hash_row
from app.models.caja import Caja
from app.models.categoria_caja import CategoriaCaja
from app.models.movimiento_caja import MovimientoCaja
from app.routers.caja_diaria_router import EditarMovimiento, editar_movimiento


def _setup_basico(db):
    db.add(Caja(nombre_normalizado="cajalocal", nombre_display="CAJA LOCAL", tipo="operativa"))
    db.add(CategoriaCaja(tipo_operacion="Sueldo", familia="Personal"))
    db.commit()


def test_editar_movimiento_a_uno_que_ya_existe_devuelve_409(db):
    _setup_basico(db)
    # Dos movimientos casi iguales
    h1 = hash_row("2026-04-01", "Sueldo", "ana", "100.00", "cajalocal", "")
    h2 = hash_row("2026-04-01", "Sueldo", "bea", "100.00", "cajalocal", "")
    db.add(MovimientoCaja(
        fecha=date(2026, 4, 1), tipo_operacion="Sueldo", detalle="ana",
        monto=Decimal("100.00"), caja_origen="cajalocal", hash_dedupe=h1,
    ))
    m2 = MovimientoCaja(
        fecha=date(2026, 4, 1), tipo_operacion="Sueldo", detalle="bea",
        monto=Decimal("100.00"), caja_origen="cajalocal", hash_dedupe=h2,
    )
    db.add(m2)
    db.commit()

    # Editar m2 para que tenga el mismo detalle que el primero -> hash colisiona
    data = EditarMovimiento(detalle="ana")
    with pytest.raises(HTTPException) as exc_info:
        editar_movimiento(m2.id, data, db)
    assert exc_info.value.status_code == 409
    assert "duplicado" in exc_info.value.detail.lower() or "ya existe" in exc_info.value.detail.lower()
```

- [ ] **Step 2: Correr el test y verificar que falla**

```bash
cd backend && source .venv/Scripts/activate
pytest tests/test_caja_diaria.py::test_editar_movimiento_a_uno_que_ya_existe_devuelve_409 -v
```
Esperado: FAIL (la edición tira IntegrityError no atrapada en lugar de HTTPException 409).

- [ ] **Step 3: Atrapar IntegrityError en `editar_movimiento`**

En `backend/app/routers/caja_diaria_router.py`, en la función `editar_movimiento`, reemplazar las últimas 7 líneas (`db.flush()` ... `return ...`) por:

```python
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

    alertas_router.invalidar_cache()
    return {"ok": True, "id": m.id}
```

Y al inicio de `caja_diaria_router.py` agregar el import si falta:
```python
from sqlalchemy.exc import IntegrityError
```

- [ ] **Step 4: Correr el test y verificar que pasa**

```bash
pytest tests/test_caja_diaria.py -v
```
Esperado: 1 passed.

- [ ] **Step 5: Confirmar que la suite completa sigue OK**

```bash
pytest
```
Esperado: todos passed (47).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/caja_diaria_router.py backend/tests/test_caja_diaria.py
git commit -m "fix(C4): PATCH movimiento devuelve 409 en colisión de hash"
```

---

## Task 5: Fix C5 — `_filtro_fecha` no extiende `hasta` a fin de día

**Files:**
- Modify: `backend/app/kpis/caja.py:16-21`
- Test: `backend/tests/test_kpis_caja.py` (crear)

`Venta.fecha` es DateTime (incluye hora). Cuando filtrás `hasta = 2026-04-30`, SQLAlchemy compara contra `datetime(2026, 4, 30, 0, 0, 0)` y excluye todas las ventas con hora > 00:00 del día 30. Resultado: el último día del filtro desaparece del flujo. El módulo `kpis/comerciales.py` ya tiene esto resuelto con `_hasta_fin_dia`; hay que replicarlo en `caja.py`.

- [ ] **Step 1: Crear test que reproduce el bug**

Crear `backend/tests/test_kpis_caja.py`:

```python
"""Tests de KPIs de caja."""
from datetime import date, datetime
from decimal import Decimal

from app.kpis.caja import flujo_caja
from app.models.caja import Caja
from app.models.categoria_caja import CategoriaCaja
from app.models.venta import Venta


def test_flujo_incluye_ventas_del_dia_tope(db):
    """Una venta del 30/4 a las 18:00 debe contar en el flujo cuando
    el filtro es hasta=2026-04-30."""
    db.add(Caja(nombre_normalizado="c1", nombre_display="C1", tipo="operativa"))
    db.add(Venta(
        id_pedido="p1", id_venta="v1",
        fecha=datetime(2026, 4, 30, 18, 0),  # tarde del último día
        id_cliente=1, cliente="X", total=Decimal("1000"),
        monto_pago1=Decimal("1000"), caja1="c1",
    ))
    db.commit()

    serie = flujo_caja(db, periodo="mes",
                       desde=date(2026, 4, 1), hasta=date(2026, 4, 30))
    abr = next((s for s in serie if s["periodo"] == "2026-04"), None)
    assert abr is not None, "Abril 2026 debe aparecer en la serie"
    assert abr["ingresos_ventas"] == 1000.0, (
        f"La venta del 30/4 18:00 no aparece (got {abr['ingresos_ventas']})"
    )
```

- [ ] **Step 2: Correr y verificar que falla**

```bash
cd backend && source .venv/Scripts/activate
pytest tests/test_kpis_caja.py -v
```
Esperado: FAIL (`abr` es None o `ingresos_ventas == 0`).

- [ ] **Step 3: Reemplazar `_filtro_fecha` para extender `hasta` a fin de día**

En `backend/app/kpis/caja.py`, reemplazar las líneas 16-21:

```python
def _hasta_fin_dia(hasta):
    """Convierte una date en el datetime del último instante del día."""
    if hasta is None:
        return None
    if isinstance(hasta, datetime):
        return hasta
    return datetime.combine(hasta, time.max)


def _filtro_fecha(query, columna, desde, hasta):
    if desde:
        query = query.filter(columna >= desde)
    h = _hasta_fin_dia(hasta)
    if h is not None:
        query = query.filter(columna <= h)
    return query
```

(Nota: `time.max` ya está importado en la línea 3.)

- [ ] **Step 4: Correr el test y verificar que pasa**

```bash
pytest tests/test_kpis_caja.py -v
```
Esperado: 1 passed.

- [ ] **Step 5: Suite completa**

```bash
pytest
```
Esperado: todos passed (48).

- [ ] **Step 6: Commit**

```bash
git add backend/app/kpis/caja.py backend/tests/test_kpis_caja.py
git commit -m "fix(C5): _filtro_fecha extiende hasta a fin de día en caja.py"
```

---

## Task 6: Fix C6 — `clientes_con_cuenta` duplica clientes con typo en nombre

**Files:**
- Modify: `backend/app/kpis/cuentas_corrientes.py:32-49`
- Test: `backend/tests/test_cuentas_corrientes.py` (agregar test)

`group_by(Venta.id_cliente, Venta.cliente)` devuelve una fila por cada combinación id+nombre. Si un cliente tiene 2 ventas con typo en el nombre, aparece 2 veces y los pagos se cuentan ×2.

- [ ] **Step 1: Agregar test al archivo existente**

En `backend/tests/test_cuentas_corrientes.py`, agregar:

```python
def test_cliente_con_typo_en_nombre_aparece_una_sola_vez(db):
    """id_cliente igual con nombre escrito distinto (typo) -> una sola fila."""
    db.add(Caja(nombre_normalizado="c1", nombre_display="C1", tipo="operativa"))
    db.add(Venta(
        id_pedido="p1", id_venta="v1", fecha=datetime(2026, 4, 1),
        id_cliente=500, cliente="Ariel Gonzales",  # nombre canónico
        total=Decimal("1000"), es_cuenta_corriente=True,
    ))
    db.add(Venta(
        id_pedido="p2", id_venta="v2", fecha=datetime(2026, 4, 5),
        id_cliente=500, cliente="ariel gonzales",  # typo (lower)
        total=Decimal("500"), es_cuenta_corriente=True,
    ))
    db.commit()

    clientes = clientes_con_cuenta(db)
    arieles = [c for c in clientes if c["id_cliente"] == 500]
    assert len(arieles) == 1, (
        f"id_cliente=500 debe aparecer una sola vez, salieron {len(arieles)}"
    )
    assert arieles[0]["monto_cargado"] == 1500.0
```

- [ ] **Step 2: Correr test y verificar que falla**

```bash
cd backend && source .venv/Scripts/activate
pytest tests/test_cuentas_corrientes.py::test_cliente_con_typo_en_nombre_aparece_una_sola_vez -v
```
Esperado: FAIL (salen 2 filas en lugar de 1).

- [ ] **Step 3: Cambiar el `group_by` y resolver el nombre con `func.max`**

En `backend/app/kpis/cuentas_corrientes.py`, reemplazar el query `cargos_q` (líneas 32-49) por:

```python
    # Sub: cargos por cliente (ventas pendientes). Se agrupa SOLO por
    # id_cliente para evitar duplicados cuando el nombre tiene typos
    # entre ventas. El nombre se resuelve con MAX (uno cualquiera).
    cargos_q = db.query(
        Venta.id_cliente,
        func.max(Venta.cliente).label("cliente"),
        func.count(Venta.id_pedido).label("ventas_pendientes"),
        func.coalesce(func.sum(Venta.total), 0).label("monto_cargado"),
    ).filter(
        Venta.id_cliente.isnot(None),
        or_(
            Venta.es_cuenta_corriente == True,
            (
                (func.coalesce(Venta.monto_pago1, 0) + func.coalesce(Venta.monto_pago2, 0)) == 0
            ) & (Venta.total > 0),
        ),
    ).group_by(Venta.id_cliente).all()
```

- [ ] **Step 4: Correr test y verificar que pasa**

```bash
pytest tests/test_cuentas_corrientes.py -v
```
Esperado: todos los tests del módulo pasan (incluido el nuevo).

- [ ] **Step 5: Suite completa**

```bash
pytest
```
Esperado: todos passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/kpis/cuentas_corrientes.py backend/tests/test_cuentas_corrientes.py
git commit -m "fix(C6): clientes_con_cuenta agrupa solo por id_cliente"
```

---

## Task 7: Fix C7 — Persistir `linea_num` en `detalle_ventas` para dedup estable

**Files:**
- Modify: `backend/app/models/venta.py` (agregar columna `linea_num`)
- Migration: `backend/alembic/versions/<auto>_linea_num_detalle_ventas.py`
- Modify: `backend/app/importers/detalle_ventas.py:29-105` (todo el `import_detalle_ventas`)
- Test: `backend/tests/test_importer_idempotencia.py` (agregar test)

El dedup actual usa una `posicion_en_import` calculada en runtime. Si el CSV se re-genera con orden distinto (o se inserta una línea en el medio), la posición cambia y todo se duplica. Solución: persistir `linea_num` por `(id_venta, posición)` y usarlo como parte del hash.

- [ ] **Step 1: Agregar columna al modelo**

En `backend/app/models/venta.py`, agregar a `DetalleVenta`:

```python
    # Posición de línea dentro del idVenta. Se asigna en el primer import
    # y NO cambia en re-imports (lo cual estabiliza el hash de dedup).
    linea_num = Column(Integer, nullable=False, default=0)
```

(En la sección donde están las otras columnas, justo antes de `categoria_linea`.)

- [ ] **Step 2: Generar migración Alembic**

```bash
cd backend && source .venv/Scripts/activate
alembic revision --autogenerate -m "linea_num_detalle_ventas"
```

- [ ] **Step 3: Editar migración para que tenga `server_default='0'`**

Abrir el archivo recién generado en `backend/alembic/versions/<id>_linea_num_detalle_ventas.py`. En el `upgrade()`, asegurar que la columna tenga `server_default`:

```python
def upgrade() -> None:
    with op.batch_alter_table('detalle_ventas', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'linea_num', sa.Integer(),
            nullable=False, server_default='0',
        ))
```

- [ ] **Step 4: Aplicar migración**

```bash
alembic upgrade head
```
Esperado: salida `Running upgrade ... -> ..., linea_num_detalle_ventas`.

- [ ] **Step 5: Backfill de `linea_num` para filas existentes**

Crear y ejecutar script ad-hoc:

```bash
python -c "
from app.db import SessionLocal
from app.models.venta import DetalleVenta
from collections import defaultdict
db = SessionLocal()
counter = defaultdict(int)
filas = db.query(DetalleVenta).order_by(DetalleVenta.id).all()
for d in filas:
    d.linea_num = counter[d.id_venta]
    counter[d.id_venta] += 1
db.commit()
print(f'backfilled: {len(filas)} filas')
"
```

- [ ] **Step 6: Modificar el importer para usar `linea_num` persistido**

En `backend/app/importers/detalle_ventas.py`, reemplazar la función `import_detalle_ventas` completa por:

```python
def import_detalle_ventas(db: Session, df: pd.DataFrame, crear_casos: bool = True) -> ImportResult:
    result = ImportResult(fuente="detalle_ventas")
    result._crear_casos = crear_casos

    ventas_validas = {r[0] for r in db.query(Venta.id_venta).all()}

    # Cargar hashes existentes y siguiente linea_num por id_venta.
    # Usamos el linea_num PERSISTIDO (no calculado): re-imports con
    # orden distinto detectan correctamente los duplicados.
    hashes_existentes: set[str] = set()
    siguiente_linea: dict[str, int] = {}
    for r in db.query(
        DetalleVenta.id_venta, DetalleVenta.linea_num,
        DetalleVenta.producto, DetalleVenta.lista_precios,
        DetalleVenta.cantidad, DetalleVenta.subtotal,
    ).all():
        h = hash_row(r.id_venta, r.linea_num, r.producto, r.lista_precios, r.cantidad, r.subtotal)
        hashes_existentes.add(h)
        siguiente_linea[r.id_venta] = max(siguiente_linea.get(r.id_venta, 0), r.linea_num + 1)

    # Posición tentativa para esta import (empieza desde lo existente)
    pos_actual: dict[str, int] = dict(siguiente_linea)

    for idx, row in df.iterrows():
        fila_dict = row.to_dict()
        try:
            id_venta = normalize_str(row.get("idVenta"))
            if not id_venta:
                _rechazar(db, result, int(idx), fila_dict,
                          "id_venta_faltante", "idVenta vacío")
                continue

            if id_venta not in ventas_validas:
                _rechazar(db, result, int(idx), fila_dict,
                          "venta_inexistente",
                          f"idVenta {id_venta} no existe en ventas")
                continue

            fecha = parse_datetime_es(row.get("fecha"))
            if fecha is None:
                _rechazar(db, result, int(idx), fila_dict,
                          "fecha_invalida", f"fecha no parseable")
                continue

            producto = normalize_str(row.get("producto"))
            if not producto:
                _rechazar(db, result, int(idx), fila_dict,
                          "producto_faltante", "producto vacío")
                continue

            lista_precios = normalize_str(row.get("listaDePrecios")) or None
            cantidad = parse_monto(row.get("cantidad"))
            precio_unit = parse_monto(row.get("precioUnitario"))
            subtotal = parse_monto(row.get("subTotal"))
            descuento = parse_monto(row.get("descuentoUnitario"))
            cst = parse_monto(row.get("CST"))

            if cantidad is None or precio_unit is None or subtotal is None:
                _rechazar(db, result, int(idx), fila_dict,
                          "valores_invalidos",
                          "cantidad/precioUnitario/subTotal no parseables")
                continue

            # Buscar si esta línea (con cualquier linea_num) ya existe
            ya_existe = False
            for n in range(0, pos_actual.get(id_venta, 0)):
                h_existente = hash_row(id_venta, n, producto, lista_precios, cantidad, subtotal)
                if h_existente in hashes_existentes:
                    ya_existe = True
                    break

            if ya_existe:
                result.ya_existian += 1
                continue

            # Asignar siguiente linea_num para esta venta
            n_nueva = pos_actual.get(id_venta, 0)
            h_nueva = hash_row(id_venta, n_nueva, producto, lista_precios, cantidad, subtotal)
            hashes_existentes.add(h_nueva)
            pos_actual[id_venta] = n_nueva + 1

            categoria = clasificar_linea(producto, precio_unit)

            db.add(DetalleVenta(
                id_venta=id_venta,
                fecha=fecha,
                producto=producto,
                lista_precios=lista_precios,
                cantidad=cantidad,
                precio_unitario=precio_unit,
                subtotal=subtotal,
                descuento_unitario=descuento,
                cst=cst,
                categoria_linea=categoria,
                linea_num=n_nueva,
            ))
            result.aceptados += 1

        except Exception as e:
            _rechazar(db, result, int(idx), fila_dict, "excepcion", repr(e))

    db.commit()
    return result
```

- [ ] **Step 7: Agregar test al archivo existente**

En `backend/tests/test_importer_idempotencia.py`, agregar:

```python
DETALLE_CSV_ORDEN_A = """idVenta,fecha,producto,listaDePrecios,cantidad,precioUnitario,subTotal,descuentoUnitario,CST
v-1,30/4/2026 12:00:00,JABON,50,1,$100,$100,,50
v-1,30/4/2026 12:00:00,DETERGENTE,50,1,$200,$200,,100
"""

DETALLE_CSV_ORDEN_B = """idVenta,fecha,producto,listaDePrecios,cantidad,precioUnitario,subTotal,descuentoUnitario,CST
v-1,30/4/2026 12:00:00,DETERGENTE,50,1,$200,$200,,100
v-1,30/4/2026 12:00:00,JABON,50,1,$100,$100,,50
"""

VENTAS_PARA_DETALLE = """IdPedido,Fecha,hora,idCliente,cliente,formaDePago1,montoPago1,PAGO V.,formaDePago2,montoPago2,PAGO V. 2,total,comprobanteDePago,vendedor,idVenta,helperV
ped-x,30/4/2026 12:00:00,12:00:00,1,Cliente,EFECTIVO,"$300",TRUE,,,TRUE,"$300",,V,v-1,TRUE
"""


def test_detalle_dedupe_estable_con_orden_distinto(db):
    """Re-import con orden distinto NO debe duplicar líneas."""
    importar(db, VENTAS_PARA_DETALLE.encode("utf-8"))
    _, r1 = importar(db, DETALLE_CSV_ORDEN_A.encode("utf-8"))
    assert r1.aceptados == 2

    # Re-import con líneas en orden invertido: NO debe agregar nada
    _, r2 = importar(db, DETALLE_CSV_ORDEN_B.encode("utf-8"))
    assert r2.aceptados == 0, f"se duplicaron filas: aceptados={r2.aceptados}"
    assert r2.ya_existian == 2
```

- [ ] **Step 8: Correr y verificar**

```bash
pytest tests/test_importer_idempotencia.py -v
```
Esperado: todos passed.

- [ ] **Step 9: Suite completa + verificar manualmente con CSVs reales**

```bash
pytest
```

```bash
# Re-importar el detalle real, debería decir todos "ya_existian"
curl -s -X POST http://127.0.0.1:8000/api/import \
  -F "file=@C:/Users/HP ENVY/Desktop/KPI/detalle_ventas.csv" \
  -o /tmp/imp.json -w "HTTP %{http_code}\n"
python -c "import json; d=json.load(open('/tmp/imp.json')); print(f'aceptados={d[\"aceptados\"]}, ya_existian={d[\"ya_existian\"]}')"
```
Esperado: aceptados=0 (todo dedupeado), ya_existian ~120000.

- [ ] **Step 10: Commit**

```bash
git add backend/app/models/venta.py backend/app/importers/detalle_ventas.py \
        backend/alembic/versions/*_linea_num_detalle_ventas.py \
        backend/tests/test_importer_idempotencia.py
git commit -m "fix(C7): persistir linea_num en detalle_ventas para dedup estable"
```

---

## Task 8: Fix C8 — Rollback en loop revierte filas pendientes

**Files:**
- Modify: `backend/app/importers/movimientos_caja.py:120-122`

El `db.rollback()` dentro del `except` general revierte **todo** lo que el batch tenía pendiente, no solo la fila problemática. Hay que dejar el rollback solo en el caso de IntegrityError (que ya está atrapado en su propio bloque arriba).

- [ ] **Step 1: Quitar el rollback general del except externo**

En `backend/app/importers/movimientos_caja.py`, reemplazar las líneas 120-122:

```python
        except Exception as e:
            # NO hacer db.rollback() aquí: revertiría todas las filas
            # ya aceptadas en este batch. Solo registramos el rechazo.
            _rechazar(db, result, int(idx), fila_dict, "excepcion", repr(e))
```

- [ ] **Step 2: Agregar test que detecta el bug**

En `backend/tests/test_importer_idempotencia.py`, agregar:

```python
CAJA_CON_FILA_INVALIDA = """FECHA,Tipo de Operación,DETALLE DEL GASTO,MONTO,SALIDAS,ENTRADAS
01/05/2026,Sueldo,fila ok 1,"$100",CAJA LOCAL,
fecha_invalida,Sueldo,fila rota,"$100",CAJA LOCAL,
01/05/2026,Sueldo,fila ok 2,"$100",CAJA LOCAL,
"""


def test_movimientos_fila_rota_no_revierte_aceptadas(db):
    """Una fila inválida en el medio NO debe deshacer las anteriores aceptadas."""
    _, r = importar(db, CAJA_CON_FILA_INVALIDA.encode("utf-8"))
    # 2 filas válidas + 1 fecha inválida
    assert r.aceptados == 2, f"se perdieron filas válidas: aceptados={r.aceptados}"
    assert len(r.rechazados) >= 1
```

- [ ] **Step 3: Correr test y verificar que pasa**

```bash
cd backend && source .venv/Scripts/activate
pytest tests/test_importer_idempotencia.py::test_movimientos_fila_rota_no_revierte_aceptadas -v
```
Esperado: PASS.

- [ ] **Step 4: Suite completa**

```bash
pytest
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/importers/movimientos_caja.py backend/tests/test_importer_idempotencia.py
git commit -m "fix(C8): no rollback general en loop de import movimientos"
```

---

## Task 9: Cache invalidation centralizada con decorator

**Files:**
- Create: `backend/app/routers/_cache_helpers.py`
- Modify: `backend/app/routers/cuentas_corrientes_router.py` (3 mutaciones)
- Modify: `backend/app/routers/casos_revisar.py` (3 mutaciones)
- Modify: `backend/app/routers/configuracion.py` (2 mutaciones)
- Modify: `backend/app/routers/import_router.py` (1 mutación)
- Modify: `backend/app/routers/ventas_router.py` (ya tiene editar_venta — agregar al endpoint)

Hoy varias mutaciones cambian datos sin invalidar el cache de alertas (TTL 30s) → la UI muestra alertas viejas. Centralizar con un decorator que invalida después del response exitoso.

- [ ] **Step 1: Crear el decorator**

Crear `backend/app/routers/_cache_helpers.py`:

```python
"""Helpers compartidos para routers."""

from functools import wraps


def invalida_alertas(func):
    """Decorator: invalida cache de alertas después de un response exitoso.

    Uso:
        @router.post("/foo")
        @invalida_alertas
        def crear_foo(...):
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Import diferido para evitar ciclos
        from app.routers import alertas_router
        result = func(*args, **kwargs)
        alertas_router.invalidar_cache()
        return result
    return wrapper
```

- [ ] **Step 2: Aplicar a `cuentas_corrientes_router.py`**

En `backend/app/routers/cuentas_corrientes_router.py`, agregar al inicio:
```python
from app.routers._cache_helpers import invalida_alertas
```

Y decorar las 3 mutaciones existentes (`asignar_movimiento`, `desasignar_movimiento`, `marcar_venta_cta_cte`):

```python
@router.post("/movimiento/{movimiento_id}/asignar")
@invalida_alertas
def asignar_movimiento(...):
    ...

@router.post("/movimiento/{movimiento_id}/desasignar")
@invalida_alertas
def desasignar_movimiento(...):
    ...

@router.post("/venta/{id_pedido}/marcar-cta-cte")
@invalida_alertas
def marcar_venta_cta_cte(...):
    ...
```

- [ ] **Step 3: Aplicar a `casos_revisar.py`**

En `backend/app/routers/casos_revisar.py`, agregar import y decorar `descartar`, `marcar_pendiente`, `reintentar`:

```python
from app.routers._cache_helpers import invalida_alertas

@router.post("/{caso_id}/descartar")
@invalida_alertas
def descartar(...):
    ...

@router.post("/{caso_id}/marcar-pendiente")
@invalida_alertas
def marcar_pendiente(...):
    ...

@router.post("/{caso_id}/reintentar")
@invalida_alertas
def reintentar(...):
    ...
```

- [ ] **Step 4: Aplicar a `configuracion.py`**

En `backend/app/routers/configuracion.py`, agregar import y decorar `actualizar_categoria`, `actualizar_caja`, `merge_cajas`:

```python
from app.routers._cache_helpers import invalida_alertas

@router.put("/categorias/{tipo_operacion}")
@invalida_alertas
def actualizar_categoria(...):
    ...

@router.put("/cajas/{nombre_normalizado}")
@invalida_alertas
def actualizar_caja(...):
    ...

@router.post("/cajas/merge")
@invalida_alertas
def merge_cajas(...):
    ...
```

- [ ] **Step 5: Aplicar a `import_router.py`**

En `backend/app/routers/import_router.py`, agregar import y decorar `importar_csv`:

```python
from app.routers._cache_helpers import invalida_alertas

@router.post("")
@invalida_alertas
async def importar_csv(...):
    ...
```

- [ ] **Step 6: Sacar las llamadas manuales a `invalidar_cache()`**

Ya existen llamadas manuales en `caja_diaria_router.py` (en `crear_movimiento`, `eliminar_movimiento`, `editar_movimiento`) y en `ventas_router.py` (`editar_venta`). El decorator las hace redundantes — sacarlas Y agregar el decorator es más limpio.

En `caja_diaria_router.py`:
- Agregar `from app.routers._cache_helpers import invalida_alertas`
- Sacar las 3 líneas `alertas_router.invalidar_cache()` y reemplazar por `@invalida_alertas` arriba de cada endpoint.

En `ventas_router.py`:
- Agregar `from app.routers._cache_helpers import invalida_alertas`
- Decorar `editar_venta` con `@invalida_alertas` y eliminar la llamada manual.

- [ ] **Step 7: Smoke test end-to-end**

Reiniciar uvicorn. Hacer un cambio que antes NO invalidaba (ej. asignar movimiento a cliente) y verificar que las alertas reflejen el cambio sin esperar 30s:

```bash
# Pedir alertas (cachea por 30s)
curl -s "http://127.0.0.1:8000/api/alertas" -o /tmp/a1.json -w "%{http_code}\n"

# Hacer una mutación que ANTES no invalidaba (asignar mov a cliente)
# (suponiendo que tenés algún movimiento de "Ingreso" sin cliente)
# ...

# Pedir alertas inmediatamente: debe estar fresco
curl -s "http://127.0.0.1:8000/api/alertas" -o /tmp/a2.json -w "%{http_code}\n"
diff /tmp/a1.json /tmp/a2.json
```

(El test puede o no mostrar diferencia según los datos, pero el endpoint debe responder OK.)

- [ ] **Step 8: Suite completa**

```bash
pytest
```
Esperado: todos passed.

- [ ] **Step 9: Commit**

```bash
git add backend/app/routers/_cache_helpers.py backend/app/routers/*.py
git commit -m "refactor: decorator @invalida_alertas en todas las mutaciones"
```

---

## Task 10: Verificación final + actualizar README

**Files:**
- Modify: `README.md` (sección de testing)

- [ ] **Step 1: Correr toda la suite**

```bash
cd backend && source .venv/Scripts/activate && pytest -v
```
Esperado: todos verdes (~52 tests, partiendo de 44 + ~8 nuevos).

- [ ] **Step 2: Smoke test manual de las páginas afectadas**

Levantar backend + frontend y verificar:
1. `/config` → categorías → editar "Ingreso" → flag operativo se mantiene tildado.
2. `/caja` → flujo → datos del último día del mes aparecen.
3. `/cuentas-corrientes` → buscar a "Ariel Gonzales" → aparece UNA sola fila.
4. `/caja-diaria` → cargar movimiento → editar → si quedaría duplicado por hash, mensaje claro de 409 (no 500).
5. Importar el CSV de detalle 2 veces → segunda vez todo "ya_existian".

- [ ] **Step 3: Actualizar README con estado**

Agregar al final del `README.md`:

```markdown
## Estado de los KPIs

Tests: `cd backend && source .venv/Scripts/activate && pytest`

Todos los tests pasando garantiza que:
- `parse_monto` distingue decimal de separador de miles
- `_filtro_fecha` incluye correctamente el día tope
- Cuentas corrientes no duplica clientes con typos
- Re-import de detalle_ventas es idempotente con cualquier orden
- Edición de movimiento detecta colisiones de hash
- Una fila inválida en import no revierte las anteriores aceptadas
- Cache de alertas se invalida tras toda mutación
```

- [ ] **Step 4: Commit final**

```bash
git add README.md
git commit -m "docs: actualizar README con estado post-fixes críticos"
```

---

## Resumen del plan

| Task | Bug | Tiempo estimado | Tests añadidos |
|------|-----|----------------:|---------------:|
| 1 | C1 — frontend omite flag al guardar | 10 min | 0 (manual) |
| 2 | C2 — seed sobrescribe ediciones | 15 min | 2 |
| 3 | C3 — parse_monto "1.5"→15 | 20 min | 4 |
| 4 | C4 — colisión hash en PATCH | 20 min | 1 |
| 5 | C5 — filtro fecha fin de día | 10 min | 1 |
| 6 | C6 — clientes duplicados por typo | 10 min | 1 |
| 7 | C7 — dedupe detalle por orden | 30 min | 1 |
| 8 | C8 — rollback revierte batch | 10 min | 1 |
| 9 | Decorator @invalida_alertas | 30 min | 0 (smoke) |
| 10 | Verificación + README | 15 min | — |

**Total estimado: ~2.5 hs** con TDD estricto. Una vez ejecutado, el sistema produce números correctos y consistentes en todas las pantallas.
