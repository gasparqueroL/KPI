# Review — Bugs / Defectos

## Resumen ejecutivo

- **Críticos (datos incorrectos / corrupción silenciosa / crash)**: 8
- **Importantes (funcionalidad rota en edge cases)**: 14
- **Menores (pulido / hardening)**: 12

El sistema tiene varias vías de **corrupción silenciosa de datos** (categorias_seed sobrescribe ediciones del usuario, `Configuracion` UI omite un campo en el PUT, parser de montos aplica thousands-separator incorrectamente para algunos formatos), **timezone bugs** que desplazan fechas un día en Argentina (UTC-3), un **endpoint que puede tirar 500** por colisión de hash al editar movimientos, y varios sitios donde el cache de alertas y los KPIs derivados quedan stale tras mutaciones.

---

## Bugs por severidad

### Critical (datos incorrectos o crash)

#### C1. `Configuracion.jsx:138-144` — PUT `/api/config/categorias/{tipo}` omite `es_ingreso_operativo`, lo apaga en cada save

```js
await api.put(`/api/config/categorias/${encodeURIComponent(tipo)}`, {
  familia: merged.familia,
  excluir_flujo: merged.excluir_flujo,
  es_transferencia: merged.es_transferencia,
  es_retiro: merged.es_retiro,
  descripcion: merged.descripcion,
});
```

El backend `configuracion.py:81-97 (actualizar_categoria)` define `CategoriaUpdate` con `es_ingreso_operativo: bool = False` y aplica `cat.es_ingreso_operativo = data.es_ingreso_operativo` incondicional. Como el frontend no manda el campo, **cada save desde la UI silenciosamente apaga `es_ingreso_operativo`** para esa categoría.

Esto rompe directamente:
- `kpis/conciliacion.py:48` → "cobranzas_cta_cte" da $0 para esa categoría.
- `kpis/cuentas_corrientes.py:194-200` (movimientos sin asignar) → la categoría desaparece de la lista.
- `routers/cuentas_corrientes_router.py:90` → ya no se pueden asignar nuevos movimientos a clientes.

**Reproducción**: Configuración → Categorías → editar familia/check de "Ingreso" → Guardar → recargar Conciliación → "Cobranzas cta cte" cae a $0 → Cobertura % se desploma → alerta crítica falsa.

**Fix**: enviar `es_ingreso_operativo: merged.es_ingreso_operativo` en el payload, y exponer el checkbox en la UI. Y/o cambiar el backend a `PATCH` semántico que solo actualice campos enviados (`exclude_unset=True`).

---

#### C2. `categorias_seed.py:97-107` — Re-seed sobrescribe ediciones manuales en cada arranque

```python
cats_op = db.query(CategoriaCaja).filter(
    CategoriaCaja.tipo_operacion.in_(operativas),
    CategoriaCaja.es_ingreso_operativo == False,
).all()
for cat in cats_op:
    cat.es_ingreso_operativo = True
```

Si el usuario explícitamente desmarca `es_ingreso_operativo` en una categoría que está en `DEFAULTS` con ese flag (`Ingreso`, `paga cuenta corriente`), **al próximo restart del server queda re-activada**. No hay forma de desactivarla persistentemente. Combinado con C1, los flags oscilan entre lo que pone el usuario y lo que reaplica el seed.

**Fix**: agregar columna `seed_aplicado` o `flag_user_override` para que el seed solo toque categorías que nunca fueron tocadas por el usuario (idéntico patrón al check `familia IS NULL` ya usado en el bloque de arriba).

---

#### C3. `parsing.py:7-28` — `parse_monto` malinterpreta números con un solo punto decimal

```python
elif has_dot:
    s = s.replace(".", "")  # asume thousands-separator
```

Un valor como `"1.5"` (un kilo y medio, decimal estilo en-US, o costo `1.5` en USD que llegue por copy-paste) se convierte en `Decimal("15")`. Casos reales:
- CST exportado en formato en-US con `.` decimal → todos los costos quedan ×10.
- Cantidades fraccionarias `0.5` → `5` → margen y top productos rotos.
- Montos chicos `12.50` (sin separador de miles) → `1250`.

El código asume formato es-AR exclusivo, pero el comentario del docstring lo confirma sin protección. **No es teórico**: cualquier import de un CSV exportado desde Excel en-US o desde cualquier sistema con locale distinto va a corromper datos sin error.

**Fix**: si es ambiguo (un punto y dos decimales después o número total < 1000) tratar como decimal. Mejor aún: detectar locale al principio del CSV (mirá la columna entera) y normalizar consistentemente.

---

#### C4. `caja_diaria_router.py:179-183` — Re-cómputo del `hash_dedupe` en editar puede tirar 500 por UNIQUE violation

```python
m.hash_dedupe = hash_row(
    m.fecha.isoformat(), m.tipo_operacion, m.detalle or "",
    str(m.monto), m.caja_origen or "", m.caja_destino or "",
)
db.commit()
```

`MovimientoCaja.hash_dedupe` es `unique=True`. Si el usuario edita un movimiento y los nuevos valores coinciden con otro movimiento ya existente, el commit lanza `IntegrityError` no atajado → 500 al usuario, transacción abortada.

**Reproducción**: dos movimientos de hoy con mismo tipo/origen/destino/detalle pero monto distinto. Editar uno y poner el monto del otro → 500.

**Fix**: try/except IntegrityError con mensaje 409 ("colisiona con movimiento existente"); o validar antes del commit con un select de control.

---

#### C5. `kpis/caja.py:16-21` — `_filtro_fecha` no extiende `hasta` a fin de día para columnas DateTime

```python
def _filtro_fecha(query, columna, desde, hasta):
    if desde:
        query = query.filter(columna >= desde)
    if hasta:
        query = query.filter(columna <= hasta)
    return query
```

Mientras que `comerciales.py:_filtro_fecha + _hasta_fin_dia` correctamente convierte el `date` a `datetime(..., time.max)` para columnas DateTime (`Venta.fecha`), `caja.py:_filtro_fecha` filtra `Venta.fecha <= '2026-05-02'`. SQLite compara como string → todas las ventas con timestamp posterior a `'2026-05-02 00:00:00'` (o sea, todas las del día) **se excluyen** del flujo y resúmenes de caja cuando el rango incluye el día actual. Esto se manifiesta en:
- `flujo_caja` → la columna `ingresos_ventas` para el día tope queda en 0.
- `composicion_gastos` → con `MovimientoCaja.fecha` (Date) está OK, pero si llega a usarse con Venta queda mal.

**Fix**: usar el mismo helper `_hasta_fin_dia` que `comerciales.py`. Mejor todavía: mover el helper a un módulo común y reutilizarlo en ambos.

---

#### C6. `kpis/cuentas_corrientes.py:36-101` — `clientes_con_cuenta` no maneja clientes con NULL `cliente`

En `cargos_q` agrupa por `(Venta.id_cliente, Venta.cliente)`. Si para un mismo `id_cliente` hay ventas con distintos valores en `cliente` (typo, cambio de nombre, NULL), el cliente aparece **duplicado** en la lista, cada fila con sus propias `ventas_pendientes` y `monto_cargado`, y el saldo total NETO del cliente queda **mal calculado** porque los `pagos` del diccionario `pagos_dict[c.id_cliente]` se suman al primer match y NO al segundo (ambas filas reportan el mismo `monto_pagado`).

**Reproducción**: insertar dos ventas para id_cliente=42 con cliente "Pedro Pérez" y "Pedro Perez" (sin tilde). Listado muestra dos filas con saldo separado pero ambas con el mismo `pagos_recibidos` y `monto_pagado` → la suma es ×2.

**Fix**: agrupar solo por `Venta.id_cliente` y elegir el nombre con `func.max(Venta.cliente)` o un MIN, o cargar el nombre en una segunda query.

---

#### C7. `importers/detalle_ventas.py:54-119` — Hash dedupe basado en posición es frágil

El esquema de dedupe agrega un contador "posición de línea por id_venta", pero la posición de las filas YA cargadas se calcula iterando `db.query(...).order_by(DetalleVenta.id).all()`. Esto solo coincide con la posición original del CSV si:

1. Las filas de detalle del mismo `id_venta` se importaron consecutivamente, en orden CSV.
2. No hubo edits/deletes intermedios (no hay endpoints que los hagan ahora, pero podría haber).

Si el CSV original mezcla líneas de distintos `id_venta` y se reordena en una re-importación, el hash difiere y el sistema **importa duplicados sin detectarlos**, contaminando margen, top productos y conciliación.

**Reproducción**: importar `detalle.csv` con orden mezclado por `id_venta`. Re-importar el mismo CSV ordenado por `id_venta` → todas las filas pasan dedupe y se duplican.

**Fix**: persistir explícitamente el `linea_orden` (entero por id_venta) en `DetalleVenta` y dedupe por hash que incluya esa columna real, no la calculada por orden de inserción.

---

#### C8. Pérdida de datos al rollback de movimientos durante import — `importers/movimientos_caja.py:120-122`

```python
except Exception as e:
    db.rollback()
    _rechazar(...)
```

`db.rollback()` dentro del loop revierte **todas las filas pendientes** (no solo la actual). Como el commit es al final (`db.commit()` línea 124), una sola excepción a mitad del CSV revierte TODOS los movimientos previos del archivo (no se han comiteado todavía). El log muestra "aceptados: N" pero la BD no tiene esos N. **El conteo `result.aceptados` mentirá** y el caso a revisar tampoco se persiste (porque el `_rechazar` también se rollback-ea junto con todo lo anterior).

**Reproducción**: CSV con 100 filas válidas + fila #50 que rompe en una assertion no controlada → al final aceptados=99, ya_existian=0, rechazados=1, pero la BD termina con **0 filas** porque el rollback tiró abajo todo.

**Fix**: usar SAVEPOINTs por fila, o procesar en bulk con upsert; al menos NO llamar rollback sobre la sesión global.

---

### Important (funcionalidad rota en edge cases)

#### I1. `PeriodPresets.jsx:1-3` y `CajaDiaria.jsx:352` — Timezone bug en presets de fecha

`new Date(...).toISOString().slice(0,10)` devuelve fecha UTC. En Argentina (UTC-3), entre 21:00 y 23:59 local **todas las fechas se desplazan un día al futuro**. Ejemplo: a las 22:00 del 30/4 local, "Hoy" en CajaDiaria muestra "2026-05-01"; los presets "Este mes" calculan a partir del 1 de mayo en vez del 1 de abril.

**Fix**: helper local `fmtIsoLocal(d) = ${y}-${m}-${d}` con `getFullYear/getMonth/getDate`.

#### I2. `cuentas_corrientes_router.py:asignar/desasignar/marcar_cta_cte` — No invalidan cache de alertas

Al asignar una cobranza a un cliente, los KPIs de cobertura/saldo cambian, pero el cache de `/api/alertas` (TTL 30s) sigue mostrando datos viejos. Sidebar y panel de alertas quedan stale hasta 30s o un refresh manual. No es catastrófico pero rompe UX prometida ("invalidar_cache después de mutaciones").

**Fix**: agregar `alertas_router.invalidar_cache()` después del commit en cada endpoint de mutación.

#### I3. `import_router.py:21-30` — Tras importar no se invalida cache de alertas ni se notifica al frontend

Después de un import grande, el sidebar puede tardar hasta 60s (poll del AlertasContext) en mostrar nuevas alertas (cobertura, productos a pérdida, etc.) y los KPIs cacheados están desactualizados. El componente `Importar.jsx` tampoco llama a `recargar()` del context.

**Fix**: backend invalida cache al final del import; frontend llama `recargar()` después del POST.

#### I4. `casos_revisar.py:reintentar` — No invalida cache de alertas

Aceptar un caso suma una venta/movimiento → cambia conciliación, posiblemente alertas. El endpoint no invalida cache.

#### I5. `configuracion.py:merge_cajas` — No invalida cache de alertas y mezcla puede dejar tipos inconsistentes

Tras merge, el cache de saldos sigue mostrando ambas cajas. Adicionalmente, si `src.tipo == "fc_empleado"` y `dst.tipo == "operativa"`, el merge mete las ventas/movimientos de FC en una caja operativa sin advertir al usuario, mezclando saldos de adelantos con caja operativa.

#### I6. `ventas_router.py:editar_venta` — No recalcula `es_cuenta_corriente` cuando se cambia caja1

Si el usuario cambia caja1 de "FALTA PAGAR" a "EFECTIVO" pero no toca el flag `es_cuenta_corriente`, la venta queda marcada como cta cte aunque ya no tenga forma de pago de cta cte. Inconsistente con el cómputo del importer (`ventas.py:81-84`). Ledger del cliente sigue cargando esa venta.

**Fix**: recalcular `es_cuenta_corriente` con la misma lógica del importer si no llega explícito en el PATCH.

#### I7. `ventas_router.py:153,169` — `monto_pago > 0` silenciosamente convierte `0` a `null`

`v.monto_pago1 = Decimal(str(data.monto_pago1)) if data.monto_pago1 > 0 else None`. Cualquier valor 0 o negativo se convierte en NULL sin error. Combinado con `EditarVentaFila.jsx:46` que envía `monto_pago1: monto1 ? Number(monto1) : 0`, un input vacío se traduce a 0 → backend lo convierte a NULL → la caja1 queda asignada sin monto. Esto rompe luego "ventas sin cobro" (la lista filtra por suma de pagos == 0, así que la venta vuelve a aparecer, aunque caja1 no es null) y discrepancia.

#### I8. `EditarVentaFila.jsx:23-27` — useEffect con deps faltantes y race con cajas

```js
useEffect(() => {
  if (!cajasDisponibles || cajasDisponibles.length === 0) {
    api.get("/api/caja-diaria/sugerencias").then((r) => setCajas(r.data.cajas || []));
  }
}, []);
```

Closure stale sobre `cajasDisponibles`. Si el padre carga cajas asíncronamente y las pasa después, el useEffect no re-corre. Mientras `cajas` está vacío, `displayDe(caja1)` devuelve el nombre normalizado, el `<select>` no encuentra match y muestra placeholder ("— elegí —"). Si el usuario guarda sin tocar el select, el state local de `caja1` sigue siendo el normalizado original — eso se manda al backend que lo re-normaliza. OK por casualidad. Pero si el usuario abre el select **antes** de que carguen las cajas y ve "— elegí —", puede pensar que no hay caja y la cambia.

#### I9. `EditarVentaFila.jsx:54-70` — Inconsistencia parcial entre PATCH y marcar-cta-cte

Si el PATCH de venta succeed pero el endpoint `marcar-cta-cte` devuelve un 500 (no 409), el catch hace `throw e`, el modal muestra error, **pero la venta YA fue editada** (cliente, vendedor, montos cambiados) sin que el usuario sepa. La cta cte queda en el estado anterior. El usuario reintenta y posiblemente confunde el estado.

**Fix**: invertir el orden o hacer ambas mutaciones atómicas en backend (un solo endpoint).

#### I10. `ventas_router.py:editar_venta` — Edición no valida que `id_cliente` exista en la BD

```python
if data.id_cliente is not None:
    v.id_cliente = data.id_cliente
```

Permite asignar id_cliente arbitrario que no existe en ninguna venta. Luego el ledger/búsqueda por ese cliente da resultados vacíos o con nombre `Cliente #999999`. No FK.

#### I11. `caja_diaria_router.py:343-345` — `helper_v` recomputado sin la cláusula de cajas presentes

```python
v1_ok = (not v.caja1) or v.pago_v1
v2_ok = (not v.caja2) or v.pago_v2
v.helper_v = v1_ok and v2_ok
```

Si una venta no tiene caja1 ni caja2 (caso raro), `v1_ok=v2_ok=True`, `helper_v=True`. Pero `ventas_router.py:182` requiere ADEMÁS `(v.caja1 or v.caja2)`. Inconsistencia: una venta sin cajas marca `helper_v=True` por verificar-bulk, `helper_v=False` por editar. Causa flips dependiendo del path.

#### I12. `caja_diaria_router.py:DELETE /movimiento/{id}` — Borra cobranza sin verificar ledger

Si el movimiento estaba asignado a un cliente, borrarlo deja al cliente con ese pago "perdido": el ledger se recalcula sin ese haber, el saldo aumenta sin contraparte y el usuario no se entera. Análogo al guard de `marcar-cta-cte` (que sí avisa con 409); falta el mismo guard en delete.

#### I13. `kpis/comerciales.py:135-156` (`serie_temporal`) — Buckets de semana mal ordenados a fin de año

`func.strftime("%Y-W%W", Venta.fecha)` produce strings como `"2024-W52"`, `"2025-W00"`, `"2025-W01"`. El sort lexicográfico funciona, pero `%W` en SQLite pone semana 00 a las primeras filas del año si caen antes del primer lunes — **dos semanas distintas pueden mapear a la misma key (W00 y W53 del año previo si Sunday-Monday)**. Combinando con buckets para `caja.py:103` también. Edge case raro pero real.

#### I14. `kpis/comerciales.py:cohortes_retencion` — `meses_max` mayor que historia disponible no se valida en backend

Si la BD solo tiene 3 meses de datos y el usuario pide `meses_max=12`, las celdas devuelven `None` para meses futuros (lógica `target > hoy_ym`), pero también pueden devolver `0%` para meses pasados sin actividad — el frontend pinta esos como verde pálido (en lugar de "transparente"), confundiendo al usuario sobre datos faltantes vs cohortes muertos.

---

### Minor (pulido / hardening)

#### M1. `categorias_seed.py:70 vs 76` — Clave `"Ingreso"` duplicada en el dict `DEFAULTS`

Python silenciosamente queda con la segunda definición; afortunadamente la segunda incluye `es_ingreso_operativo: True` que es lo deseado, pero el code smell es señal de que el seed creció sin revisión. La línea 70 queda dead code.

#### M2. `kpis/comerciales.py:cohortes_retencion:392-393` — Cálculo de offset de mes off-by-one ambiguo

```python
year = mes_alta[0] + (mes_alta[1] - 1 + offset) // 12
month = (mes_alta[1] - 1 + offset) % 12 + 1
```
La fórmula es correcta pero no obvia. Edge: para `mes_alta = (2024, 12)`, `offset=1` → `year=2025, month=1`. OK. Pero la legibilidad es nula. Recomendado usar `dateutil.relativedelta` o helper.

#### M3. `alertas_router.py:13-17` — Cache módulo-level no es safe con múltiples workers

`uvicorn --workers 4` haría que cada worker tenga su propio `_cache`. Mutaciones invalidan solo el cache del worker que recibió la mutación. Con un solo worker (configuración actual presumida) no es problema, pero documentar la limitación.

#### M4. `SortableTable.jsx:28` — `.reverse()` mutando — sort no es estable

`sorted.reverse()` reversa todo, no preserva orden relativo de elementos iguales. Recomendado: invertir el comparator (`(a,b) => -base(a,b)`).

#### M5. `Conciliacion.jsx:46` — useEffect dispara `cargarItems` en cada cambio de tab/desde/hasta sin cancelar request previa

Si el usuario tipea fechas o cambia tab rápido, hay race entre las respuestas. La última en llegar gana, pero no necesariamente es la más reciente. Recomendado AbortController.

#### M6. `Comercial.jsx:cargar` — Misma race que arriba al disparar 7 requests en paralelo

Si el usuario aprieta "Aplicar" varias veces, hay races entre lotes. El `loading` es booleano global, no por request.

#### M7. `Importar.jsx:30` — `setArchivos([])` no notifica al `AlertasContext`

Tras import el badge del sidebar tarda hasta 60s. Llamar `useAlertas().recargar()` después de cada import.

#### M8. `CasosRevisar.jsx:67` — `descartar` no recarga sidebar de alertas

El conteo "casos_pendientes" baja, pero el badge sigue mostrando el viejo hasta 60s.

#### M9. `dashboard.py:35-37` — `dias` puede ser 0 o negativo si `desde > hasta`

No hay validación. Resulta en `desde_prev = hasta_prev + timedelta(...)` con valores raros pero no crash. Mejor 400.

#### M10. `cuentas_corrientes.py:107-109` — `cliente_nombre` solo busca el primer match

```python
db.query(Venta.cliente).filter(Venta.id_cliente == id_cliente).limit(1).scalar()
```
Si hay multiple Venta para ese id_cliente con nombres distintos (ej. "Pérez", "Perez"), elige uno arbitrario, no necesariamente el más reciente o el correcto.

#### M11. `casos_revisar.py:151` — `import_detalle_ventas(db, df, crear_casos=False)` con `df` de 1 fila

Llama al importer completo que carga todos los hashes existentes en RAM. Para detalle_ventas con 119k filas ya cargadas, cada reintento hace ese load. Lento pero funcional.

#### M12. `ventas_router.py:editar_venta` — `helper_v` recalculado pero `pago_v1/pago_v2` puede saltearse silenciosamente

En el patch, si `pago_v1 is None` (no enviado) y la caja1 cambió, el flag puede quedar inconsistente con la nueva caja. Por ejemplo: caja1 era "EFECTIVO" verificada (`pago_v1=True`), usuario cambia caja1 a "MERCADOPAGO" → `pago_v1` no se resetea → la nueva caja queda como "verificada" sin que el usuario lo confirme.

---

## Patrones repetidos

### P1. Cache de alertas no invalidado tras mutaciones

Solo `ventas_router.editar_venta` y `caja_diaria_router.{crear,editar,eliminar}_movimiento` llaman `alertas_router.invalidar_cache()`. El resto NO:
- `import_router.importar_csv`
- `cuentas_corrientes_router.{asignar_movimiento, desasignar_movimiento, marcar_venta_cta_cte}`
- `casos_revisar.{descartar, reintentar, marcar_pendiente}`
- `configuracion.{actualizar_categoria, actualizar_caja, merge_cajas}`

→ Refactor: decorator `@invalida_alertas` o un middleware que limpie el cache después de cualquier 2xx en un POST/PATCH/PUT/DELETE.

### P2. `Decimal` ⇄ `float` ida y vuelta sin razón clara

Casi todos los kpis hacen `Decimal(str(row.x or 0))` para sumar y luego `_to_float(...)` al final. Funciona pero introduce overhead y complica leer el código. Tampoco evita los problemas reales de precisión: el float del JSON ya redondea. Recomendado: o todo Decimal hasta serializar en el último momento, o trabajar con float desde el principio (los montos son moneda con 2 decimales, los floats sirven).

### P3. Helpers de fecha duplicados

`comerciales.py:_filtro_fecha + _hasta_fin_dia` y `caja.py:_filtro_fecha` divergen (este último no maneja end-of-day para columnas DateTime). Mover a un módulo común.

### P4. UI: `Number(input)` sin validación → NaN se manda al backend

Varios lugares: `EditarVentaFila.jsx:44`, `CajaDiaria.jsx:259`. Si el input está vacío o tiene texto, `Number("")=0` o `Number("abc")=NaN`. El backend recibe `null` (porque JSON no permite NaN) o `0` y silenciosamente toma decisiones erradas (ver I7).

### P5. Eventos sin clave única en eventos del ledger

`CuentasCorrientes.jsx:202` usa `\`${e.ref_tipo}-${e.ref_id}\`` como key — si hay dos movimientos con mismo `id` (no debería, pero...) o futuros eventos sin ref_id, React quejará en consola y puede romper rendering al editar.

---

## Test coverage gaps

Bugs que tests automáticos hubieran detectado:

1. **C1**: test de integración `Configuracion → POST → GET` que verifique que `es_ingreso_operativo` sobrevive un round-trip de save.
2. **C2**: test del seed que verifique idempotencia bidireccional (un valor false explícito no se sobreescribe).
3. **C3**: tests parametrizados de `parse_monto` con casos `"1.5"`, `"1.234"`, `"1,234.56"`, `"1.234,56"`, `"$0,50"`, `"-100,00"`, `""`, `"NaN"`.
4. **C4**: test de `editar_movimiento` con valores que colisionen con otro existente.
5. **C5**: test de `flujo_caja` con desde=hasta=hoy y una venta a las 14:00 → debe contarla.
6. **C6**: test de `clientes_con_cuenta` con un mismo `id_cliente` y dos `cliente` distintos en BD.
7. **C7**: test de re-importar un CSV de detalle_ventas con orden distinto al original — debe detectar duplicados.
8. **C8**: test de `import_movimientos_caja` con una fila que tira excepción no controlada — verificar conteos consistentes con BD post-rollback.
9. **I1**: test del helper `fmtIso` con fecha local cerca de medianoche en TZ negativa (mockear `Date`).
10. **I7**: test de `editar_venta` con `monto_pago1=0` — definir explícitamente la semántica.

---

## Plan de fixes (top 5 por impacto)

1. **C1 + Frontend `Configuracion.jsx`** — agregar `es_ingreso_operativo` al payload del PUT y exponerlo como checkbox. Es **el bug más dañino** porque corrompe silenciosamente la conciliación cada vez que el usuario "limpia" categorías.
2. **C3 `parse_monto`** — refactor para detectar formato por contexto y al menos no aplicar thousands-separator a strings con menos de 4 dígitos. Cualquier import futuro de un CSV con formato distinto rompe los KPIs sin ruido.
3. **C2 `categorias_seed`** — bandera `seed_lock` o `user_modified_at` para que las ediciones no se reviertan en restart. Sin esto, el fix de C1 se ve revertido al primer restart.
4. **C7 `detalle_ventas` dedupe** — persistir `linea_orden` real para que la idempotencia funcione independiente del orden de filas en el CSV de re-import.
5. **C5 `caja.py:_filtro_fecha`** — unificar con el helper de `comerciales.py`. Las ventas del día actual desaparecen del flujo de caja, distorsionando todo el dashboard de Caja en el rango "hoy".

Después de estos cinco, encarar el patrón P1 (invalidación de cache) en una sola pasada (decorator) limpia ~6 issues adicionales.
