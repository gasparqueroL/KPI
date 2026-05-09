# Review — Sesión 1 Data Correctness + Cache Invalidation

## Resumen
**2 críticos / 4 importantes / 5 menores**

Sesión sólida. Las 8 áreas declaradas se atacaron de forma consistente y los tests cubren los regresores principales (idempotencia con orden distinto, fila rota que no rompe el batch, fin de día en filtro de fechas, parse_monto con casos es-AR). El diseño general es correcto. Los críticos detectados son ambigüedades del parser sobre formato en-US (que hoy no se usa pero el código no lo bloquea) y un endpoint de mutación masiva sin invalidación de cache.

---

## Strengths

- `parse_monto` cubre correctamente todos los casos es-AR conocidos (`$156.249,80`, `$31.782`, `$-5.300,00`, `$1.234.567,89`) y maneja bien `0.500` vs `31.782` con la heurística `abs(int(parte_entera)) >= 1`.
- `_filtro_fecha` (en `kpis/comerciales.py` y `kpis/caja.py`) usa `datetime.combine(hasta, time.max)` para incluir el último día completo, con un test específico (`test_flujo_incluye_ventas_del_dia_tope`) que verifica que una venta del 30/4 a las 18:00 cae dentro de `hasta=2026-04-30`.
- Dedupe de `detalle_ventas` realmente estable: `linea_num` se persiste en la primera importación y NO se recalcula en re-imports. El test `test_detalle_dedupe_estable_con_orden_distinto` confirma que invertir el orden del CSV no genera duplicados.
- `_norm_dec` (en `detalle_ventas.py:18`) protege el hash de la "trampa" de Decimal: `format(Decimal(d).normalize(), "f")` evita tanto los ceros de cola del round-trip a `Numeric` (`1` → `1.0000` → `1`) como la notación científica de `normalize()` (`Decimal("100").normalize() == 1E+2`).
- `editar_movimiento` (PATCH en `caja_diaria_router.py:155`) recalcula `hash_dedupe` correctamente cuando cambian campos del hash, hace **check explícito de colisión** contra otros movimientos antes del commit, y rollback + 409 si hay choque. Es el patrón correcto.
- Loop de import resiliente: las excepciones por fila no propagan ni hacen `db.rollback()` global, y el comentario en `movimientos_caja.py:121-122` documenta el porqué. Test `test_movimientos_fila_rota_no_revierte_aceptadas` cubre el caso.
- `clientes_con_cuenta` agrupa solo por `id_cliente` con `MAX(cliente)` para resolver el nombre — ya no se duplica un cliente cuando hay typos en el nombre entre ventas (`cuentas_corrientes.py:42-55`).
- `@invalida_alertas` aplicado consistentemente en 22 mutaciones revisadas (importar, asignar/desasignar movimiento, marcar cta cte, descartar/reintentar caso, crear/editar/eliminar movimiento, crear/editar venta, configurar categorías/cajas, etc.).
- `clientes_con_cuenta` también suma clientes que SOLO tienen pagos sin venta marcada (saldo negativo huérfano), evitando "esconder" créditos a favor del cliente.

---

## Critical

### C1. `backend/app/importers/parsing.py:21-49` — `parse_monto` interpreta silenciosamente formato en-US como decimal en lugar de rechazar o detectar

```python
elif has_comma:
    s = s.replace(",", ".")
```

Casos verificados con la implementación actual:

| Input         | Resultado | Esperado es-AR | Esperado en-US |
|---------------|-----------|----------------|----------------|
| `"1,234.56"`  | `1.23456` | (n/a)          | `1234.56`      |
| `"15,000"`    | `15.000`  | `15` (3 dec)   | `15000`        |
| `"1,500"`     | `1.500`   | `1.500`        | `1500`         |
| `"1,234"`     | `1.234`   | `1.234`        | `1234`         |

El proyecto declara que solo entran CSVs en formato es-AR, pero `parse_monto` recibe valores tipiados como string sin verificar la fuente. Si en algún momento se carga un export con formato en-US (por ejemplo de un sistema externo, copy-paste de un cliente, o un futuro importer de bancos), valores como `"1,234.56"` se ingestan como `1.23456` **sin error**, y la fila pasa el resto de validaciones (es positivo, no es None). El bug se propaga silenciosamente al cálculo de KPIs.

El caso `"1,234.56"` con coma+punto es especialmente perverso: el código asume "es-AR formal: punto = miles, coma = decimal" y aplica `.replace(".", "").replace(",", ".")` → `"1,23456"` → `"1.23456"`. Cualquier cifra en formato anglosajón con miles + decimales se reduce ~3 órdenes de magnitud.

**Impacto**: ventas/movimientos/CST con magnitud incorrecta sin alarma. KPIs de margen y cobertura se vuelven inválidos. Viola el principio rector "solo entra al sistema lo que es válido y consistente" — actualmente entra todo y se silencia el error.

**Fix sugerido**: detectar el orden relativo de la última coma vs último punto cuando aparecen ambos:

```python
if has_comma and has_dot:
    if s.rfind(",") > s.rfind("."):
        # es-AR: punto = miles, coma = decimal
        s = s.replace(".", "").replace(",", ".")
    else:
        # en-US: coma = miles, punto = decimal
        s = s.replace(",", "")
elif has_comma:
    # Solo coma. AMBIGUO. Heurística simétrica al caso "solo punto":
    # si la parte después de la coma tiene exactamente 3 dígitos y la
    # parte entera (en valor absoluto) >= 1, tratar como miles.
    partes = s.split(",")
    if len(partes) == 2 and len(partes[1]) == 3 and partes[0]:
        try:
            if abs(int(partes[0])) >= 1:
                s = s.replace(",", "")  # "1,234" → 1234
            else:
                s = s.replace(",", ".")
        except ValueError:
            s = s.replace(",", ".")
    else:
        s = s.replace(",", ".")
```

Y agregar tests que **fallen ruidosamente** ante un input ambiguo o explícitamente rechacen formatos no es-AR cuando el contexto lo requiera (ej. flag `formato="es_AR"` que rechace inputs con punto separador decimal en presencia de coma a la izquierda).

---

### C2. `backend/app/routers/caja_diaria_router.py:374` — `verificar-bulk` no decora `@invalida_alertas` y muta `helper_v` masivamente

```python
@router.post("/verificar-bulk")
def verificar_bulk(data: VerificarBulk, db: Session = Depends(get_db)):
    """Marca múltiples cobros como verificados en una sola transacción."""
    actualizadas = 0
    for it in data.items:
        v = db.get(Venta, it.id_pedido)
        ...
        v.helper_v = v1_ok and v2_ok
        actualizadas += 1
    db.commit()
    return {"ok": True, "actualizadas": actualizadas}
```

A diferencia de `editar_venta` (PATCH en `ventas_router.py:121`) y `editar_movimiento`, este endpoint NO invalida el cache de alertas. Hoy el detector de alertas en `kpis/alertas.py` no consume `pago_v1/pago_v2/helper_v` directamente, así que el cache de 30s de TTL no devuelve datos visibles "incorrectos" — pero:

1. El contrato de la sesión declara "`@invalida_alertas` aplicado en TODAS las mutaciones que pueden invalidar el cache". Este es el único endpoint mutador detectado que rompe esa invariante. Si mañana se agrega una alerta tipo "% de cobros sin verificar" o "monto pendiente de verificar" (ya está sugerido como KPI candidato en las reglas de negocio), la alerta se queda fría 30s después de cada bulk-verify.
2. Los endpoints siblings (`crear_movimiento`, `editar_movimiento`, `eliminar_movimiento`, `editar_venta`) sí decoran. La inconsistencia es la fuente más probable de futuros olvidos.

**Fix sugerido**: agregar `@invalida_alertas` en la línea 375 (decorando entre `@router.post` y la función). Sin más cambios.

---

## Important

### I1. `backend/app/importers/detalle_ventas.py:122-130` — dedupe O(n × m) por fila, regresa lineal con tamaño de venta

```python
ya_existe = False
for n in range(0, pos_actual.get(id_venta, 0)):
    h_existente = hash_row(
        id_venta, n, producto, lista_precios,
        cantidad_norm, subtotal_norm,
    )
    if h_existente in hashes_existentes:
        ya_existe = True
        break
```

Para detectar si una línea ya está, se reconstruyen hasta `pos_actual[id_venta]` hashes (uno por cada `linea_num` posible) y se chequea contra el set. Para una venta con 50 líneas y un re-import full, son 50² = 2.500 ops de hashing. Para CSVs de 100k líneas con ventas grandes, esto vuelve la importación cuadrática en el peor caso.

**Fix sugerido**: indexar por `(id_venta, producto, lista_precios, cantidad_norm, subtotal_norm)` directamente, no por `linea_num`. La línea de detalle es naturalmente identificable por sus atributos, no por su posición. Si dos líneas tienen exactamente los mismos 5 atributos son intercambiables a efectos de KPIs (y el orden interno es irrelevante).

```python
clave_logica = (id_venta, producto, lista_precios or "", cantidad_norm, subtotal_norm)
# precarga: dict[clave_logica, linea_num]
existentes = {}
for r in db.query(...).all():
    k = (r.id_venta, r.producto, r.lista_precios or "", _norm_dec(r.cantidad), _norm_dec(r.subtotal))
    existentes[k] = r.linea_num

# en el loop:
if (id_venta, producto, lista_precios or "", cantidad_norm, subtotal_norm) in existentes:
    result.ya_existian += 1
    continue
```

Esto reduce dedupe a O(1) por fila y elimina la necesidad de `hash_row` para detalle_ventas (el hash queda solo como impl detail interno si se quisiera persistir).

### I2. `backend/app/importers/movimientos_caja.py:80-87` — cajas y categorías se persisten antes del check de hash

```python
origen_obj = (
    get_or_create_caja(db, origen_disp, cache_cajas, result.cajas_creadas)
    if origen_disp else None
)
...
db.flush()
...
h = hash_row(...)
if h in hashes_existentes:
    result.ya_existian += 1
    continue
```

Si la fila se descarta por colisión de hash, las cajas/categorías recién creadas ya quedaron `add+flush` en la sesión. El `db.commit()` final del importer las persiste. Resultado: `cajas_creadas` puede contener cajas que no se usan en ningún movimiento aceptado de este batch (porque la única fila que las referenciaba era duplicada). En `movimientos_caja.py:99-100` el `result.ya_existian` se suma sin "deshacer" la creación.

**Impacto**: el panel de configuración muestra cajas vacías. No es corrupción, pero ensucia el catálogo. Si el usuario nombra mal una caja en una sola fila duplicada, queda registrada para siempre.

**Fix sugerido**: postergar la creación de cajas hasta confirmar que la fila se acepta (mover el `get_or_create_caja` después del hash check), o filtrar `result.cajas_creadas` al final removiendo las que no figuran en `Venta.caja1/caja2` ni `MovimientoCaja.caja_origen/destino` recién insertados.

### I3. `backend/app/importers/movimientos_caja.py:120-123` — el comentario sobre rollback es correcto pero el except siguiente podría dejar la sesión envenenada

```python
except Exception as e:
    # NO hacer db.rollback() aquí: revertiría todas las filas
    # ya aceptadas en este batch. Solo registramos el rechazo.
    _rechazar(db, result, int(idx), fila_dict, "excepcion", repr(e))
```

El comentario es correcto: no se debe rollbackear. Pero si la excepción fue `OperationalError`, `IntegrityError` no capturada por el `try/except` interno, o cualquier error a nivel SQL, la sesión queda en estado `PendingRollbackError` y el siguiente `db.add` (dentro de `_rechazar`, que hace `db.add(CasoRevisar(...))`) explota silenciosamente o la siguiente fila falla en cascada. Y al final `db.commit()` (línea 125) termina haciendo rollback implícito de todo.

El test `test_movimientos_fila_rota_no_revierte_aceptadas` cubre el caso de fecha inválida (que se detecta antes y se rechaza con código `fecha_invalida`, sin tocar la sesión SQL), pero no cubre el caso de excepción **a nivel SQL** (ej. caja con nombre que viola constraint, IntegrityError no capturada).

**Fix sugerido**: dentro del `except Exception`, si la sesión está en estado inconsistente, hacer un savepoint (`with db.begin_nested():`) por fila para que el rollback de una no afecte a las anteriores. Patrón:

```python
for idx, row in df.iterrows():
    try:
        with db.begin_nested():  # SAVEPOINT
            # toda la lógica de procesar la fila
            db.add(mov)
    except Exception as e:
        # el SAVEPOINT ya rollbackeó solo esta fila
        _rechazar(db, result, int(idx), fila_dict, "excepcion", repr(e))
```

Esto resuelve el problema de raíz y permite remover el `try/except IntegrityError` interno duplicado. Aplicar también a `detalle_ventas.py` y `ventas.py`.

### I4. `backend/app/routers/dashboard.py:54` — duplica la lógica de `_filtro_fecha` en lugar de reusarla

```python
.filter(Venta.vendedor.isnot(None), Venta.fecha >= desde, Venta.fecha <= datetime.combine(hasta, datetime.max.time()))
```

`comerciales._filtro_fecha` y `caja._filtro_fecha` ya implementan exactamente esta lógica con `_hasta_fin_dia`. Aquí se duplica inline, lo cual:

- viola DRY (si mañana se cambia la convención de inclusión, este sitio queda atrás);
- usa `datetime.max.time()` en lugar de `time.max` — funcionalmente equivalente pero distinto del helper, lo cual oscurece la lectura.

**Fix sugerido**: importar `_filtro_fecha` y reescribir:

```python
q = db.query(func.count(distinct(Venta.vendedor))).filter(Venta.vendedor.isnot(None))
q = _filtro_fecha(q, Venta.fecha, desde, hasta)
vendedores_activos = q.scalar() or 0
```

Bonus: extraer `_hasta_fin_dia` y `_filtro_fecha` a un módulo común (`app/kpis/_helpers.py` o `app/utils/fechas.py`) — actualmente está duplicado entre `kpis/comerciales.py:15-29` y `kpis/caja.py:16-31` con las mismas líneas idénticas.

---

## Minor

### M1. `backend/app/importers/parsing.py:52-71` — `parse_datetime_es` no maneja zonas horarias

`datetime.strptime` siempre devuelve un `datetime` naive. Si en el futuro se cargan exports con offset (`+03:00`, `Z`) o se cambia la BD a `TIMESTAMP WITH TIME ZONE`, los filtros `Venta.fecha <= datetime.combine(hasta, time.max)` dejarán de comparar correctamente. Hoy todo es naive y funciona, pero conviene documentar la suposición (o agregar `parse_datetime_es_tz`).

### M2. `backend/app/importers/ventas.py:91-96` — tolerancia `$0,50` para `discrepancia_pago` está hardcodeada

```python
suma_pagos = (monto1 or Decimal(0)) + (monto2 or Decimal(0))
tiene_discrepancia = (
    not es_cta_corriente
    and suma_pagos > Decimal(0)
    and abs(suma_pagos - total) > Decimal("0.50")
)
```

Mismo número repetido en `ventas_router.py:179`. Extraer a constante (`TOLERANCIA_DISCREPANCIA_ARS = Decimal("0.50")`) en un módulo compartido para que un cambio de política se aplique en ambos sitios sin riesgo.

### M3. `backend/app/routers/cuentas_corrientes_router.py:49` — BOM hardcoded como caracter literal

`buf.write("﻿")` es más robusto que escribir el BOM directamente en el source — evita dependencia del encoding del archivo .py. Funciona igual, pero es mejor práctica.

### M4. `backend/app/routers/_cache_helpers.py:7-32` — el decorador invalida cache solo si la función NO levanta excepción

Comportamiento correcto pero implícito. Documentar en el docstring: "Si la función levanta una excepción HTTP (ej. 409, 404), el cache NO se invalida". Eso es lo deseado (los rollbacks no cambian estado), pero alguien podría intentar levantar una HTTPException después de modificar y commitear estado parcial — en ese caso el cache no se invalida y se desync. Es un footgun documentar+evitar.

### M5. `backend/app/kpis/cuentas_corrientes.py:166-169` — sort por slice de string en lugar de date

```python
eventos.sort(key=lambda e: (e["fecha"][:10], 0 if e["tipo"] == "venta" else 1))
```

Funciona porque ISO 8601 es lex-sortable, pero si alguna vez una fecha entra con formato distinto (ej. el frontend envía `"02/05/2026"` por error), el orden se rompe silenciosamente. Más seguro normalizar a `date` o `datetime` antes del sort.

---

## Pendientes diferibles

- **Migración de `_filtro_fecha` a un único módulo común** (mencionado en I4). No bloqueante, pero la duplicación entre `comerciales.py` y `caja.py` es un riesgo mediano.
- **Test que cubra excepción SQL en el medio del loop de import** (asociado a I3) — ej. fila que crea una caja con nombre que rompe constraint. Hoy `test_movimientos_fila_rota_no_revierte_aceptadas` solo cubre el camino "fila rechazada por validación pre-flight".
- **Test para `parse_monto` con inputs en-US** (asociado a C1) — agregar casos que verifiquen el comportamiento esperado (sea rechazo o detección correcta). Hoy nada los cubre.
- **Auditoría periódica de `cajas` con saldo nulo y sin movimientos referenciados** (asociado a I2) — UI o script CLI para limpiar el catálogo.
- **Mover el cache de alertas a Redis o algo persistente** si el sistema crece a multi-worker uvicorn — el cache in-process de `alertas_router.py` se duplica por worker y `invalidar_cache()` solo afecta al worker que recibió la mutación. Hoy con 1 worker no es problema.
- **Considerar `helperV` como insumo de alguna alerta futura** ("X% de cobros sin verificar en últimos 7 días") — refuerza la decisión de aplicar `@invalida_alertas` en `verificar-bulk` (C2) preventivamente.
