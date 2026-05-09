# Review Sesión 3C — Aging de cobros + DSO

Fecha review: 2026-05-02
Alcance: `aging_cobros()` (buckets 0-30 / 31-60 / 61-90 / +90) y `dso()` (Days Sales Outstanding) sobre `cuentas_corrientes`, con dos endpoints nuevos y tres tests.

Archivos revisados:
- `C:\Users\HP ENVY\Desktop\KPI\backend\app\kpis\cuentas_corrientes.py` (funciones `aging_cobros` y `dso`, líneas 219-336)
- `C:\Users\HP ENVY\Desktop\KPI\backend\app\routers\cuentas_corrientes_router.py` (endpoints `/aging` y `/dso`, líneas 74-84)
- `C:\Users\HP ENVY\Desktop\KPI\backend\tests\test_cuentas_corrientes.py` (tres tests al final, líneas 176-266)
- `C:\Users\HP ENVY\Desktop\KPI\frontend\src\pages\CuentasCorrientes.jsx` (cards de aging + KPI DSO)
- `C:\Users\HP ENVY\Desktop\KPI\backend\app\kpis\pagos_aplicados.py` (referencia: el camino "nuevo")

---

## Strengths

1. **Uso correcto de `Decimal` para sumas y aplicación de pagos**: `por_cliente[v.id_cliente]["buckets"][bucket] += Decimal(str(v.total))` y `Decimal(str(pagado_por_cliente.get(cli_id, 0)))`. Evita el típico drift float que arruina aging por centavos.
2. **Filtro de "ingreso puro"... parcial pero presente**: la query de pagos en `aging_cobros` filtra `caja_destino.isnot(None)`, consistente con `clientes_con_cuenta`. (Ver Important #2 sobre que falta `caja_origen.is_(None)` para excluir transferencias a cliente).
3. **Mismo predicado de "venta pendiente" que `clientes_con_cuenta`**: ambos usan el mismo `or_(es_cuenta_corriente == True, suma_pagos == 0 AND total > 0)`. Eso garantiza que el aging y el listado coinciden en universo de ventas, evitando que un cliente aparezca con saldo en una vista y no en la otra.
4. **Endpoint `/dso` valida rango**: `Query(90, ge=7, le=365)` evita `dias_ventana=0` (división por cero) y valores absurdos como -1 o 100000. Defensa simple pero efectiva.
5. **Sort estable de items por `bucket_90_mas` desc**: la UI ve primero los clientes con más morosidad, que es justamente la pregunta que el usuario quiere responder ("¿a quién perseguir?"). Buena decisión de presentación.
6. **`dso()` retorna estructura útil para auditoría**: incluye `ventas_periodo` y `saldo_pendiente_periodo` en la respuesta, no solo `dso_dias`. El usuario puede verificar el cálculo en pantalla.
7. **Tests cubren el camino feliz del aging**: distribución a buckets correctos, aplicación FIFO inverso (test del pago $2500 que limpia $2000 del bucket viejo y deja $500), y cálculo del DSO con un ratio simple (1000/2000 * 90 = 45).

---

## Critical

### C1. Aging ignora `pagos_aplicados` — el camino "nuevo" introducido en Sesión 4

`aging_cobros()` calcula `pagado_por_cliente` sumando `MovimientoCaja.monto` agrupado por `id_cliente_relacionado`. Pero en Sesión 4 se introdujo `PagoAplicado` (cobertura granular de movimiento → venta específica), y la convención es que un movimiento puede tener pagos aplicados parciales, sobrepagos, o estar aplicado a varias ventas. El docstring de `pago_aplicado.py` dice:

```python
# app/models/pago_aplicado.py:9-11
NO reemplaza `MovimientoCaja.id_cliente_relacionado` por compatibilidad.
El campo viejo sigue funcionando para vínculos cliente-nivel.
```

Esa convención es razonable, pero el aging hereda dos bugs latentes:

1. **Si el usuario empieza a usar `aplicar_pago` por venta** sin asignar `id_cliente_relacionado` en el movimiento (porque la app ya tiene `pagos_aplicados`), esos pagos NO entran al `pagado_por_cliente`. El aging muestra deudas infladas para ese cliente.
2. **Si el movimiento tiene AMBOS** (`id_cliente_relacionado` Y `pagos_aplicados`), se contabiliza dos veces — una en el sum del campo viejo y otra implícitamente porque la venta sigue marcada como `es_cuenta_corriente=True`. (Aging no usa `saldo_venta` de `pagos_aplicados.py`, pero el problema simétrico existe: la venta queda en aging con su total lleno aunque ya esté parcialmente cobrada por `PagoAplicado`).

Ambos casos producen aging silenciosamente erróneo. Recomendaciones:

- **Decidir explícitamente la fuente de verdad**: o bien (a) `aging_cobros` usa SOLO `pagos_aplicados` (y entonces el camino viejo `id_cliente_relacionado` necesita migrar a aplicaciones), o (b) usa los dos sumando: `pagado = sum(MovimientoCaja con id_cliente_relacionado pero SIN pagos_aplicados) + sum(PagoAplicado del cliente)`. La opción (b) es más segura para datos legacy. Documentar la decisión.
- **Mientras tanto, agregar nota en el docstring** de `aging_cobros` advirtiendo que ignora `pagos_aplicados` y que por ahora solo refleja vinculaciones cliente-nivel.
- **Test de regresión**: una venta con `pagos_aplicados` que cubre 70% del total debería aparecer con el 30% restante en el aging. Hoy aparecería con el 100%.

### C2. Ventas con fecha futura caen al bucket "0-30" silenciosamente

```python
# cuentas_corrientes.py:251-257
dias = (hoy - v_fecha).days
bucket = (
    "bucket_0_30" if dias <= 30
    else "bucket_31_60" if dias <= 60
    ...
)
```

Si `v_fecha > hoy` (fecha futura por tipeo o sync de un sistema con clock skew), `dias` es negativo y satisface `dias <= 30`, entrando al bucket "vigente". El usuario no se entera que la fila tiene fecha mal puesta y la venta se reporta como "al día". Pasa silencio: ni warning, ni log, ni bucket "futuro/inválido".

Punteo el riesgo real: ventas pre-cargadas con fechas planeadas (presupuestos), exports con timezone que rotan días, y errores de tipeo (2027 en lugar de 2026). En todos esos casos un aging que mete deuda futura en "0-30" desinforma al usuario.

Recomendación:
- O bien `dias = max(0, (hoy - v_fecha).days)` y registrar las ventas futuras en una métrica aparte del response (ej. `ventas_fecha_futura: 3`).
- O bien dejarlas fuera del aging por completo (`if v_fecha > hoy: continue` con contador de excluidas).
- Test: venta con `fecha = hoy + 5` debe ser flaggeada.

---

## Important

### I1. La fórmula DSO es "Sales-Weighted DSO" simplificado, NO el DSO clásico

```python
# cuentas_corrientes.py:326-329
if ventas_total > 0:
    dso_val = (pendiente / ventas_total) * dias_ventana
else:
    dso_val = Decimal(0)
```

Esto NO es el DSO clásico (`AR / ventas_diarias_promedio`). Es una proxy: "qué fracción del periodo está aún pendiente, escalado a días". Ejemplos para mostrar la diferencia:

- Si en los últimos 90 días vendiste $9000 y todavía quedan $3000 sin cobrar, esta fórmula da `3000/9000 * 90 = 30 días`. Eso da una intuición correcta: en promedio te están tardando ~30 días.
- Pero si las ventas se concentraron en el día 89 y el resto del periodo no vendiste nada, el "verdadero DSO" (cuándo se cobra cada venta) es muy distinto al que da esta fórmula.

Además, `pendiente` filtra por `Venta.fecha >= desde_dt` (ventas DEL periodo) pero no le resta los pagos aplicados o los cobros recibidos en ese rango — solo restringe a ventas que todavía cumplen el predicado de cuenta-corriente-pendiente. Funciona como aproximación, pero no es exacta.

Recomendación:
- **Renombrar el campo** a `dso_aprox_dias` o documentar muy claramente en el docstring qué fórmula es. Hoy el cliente lo lee como "DSO" estándar y puede usarlo en reportes financieros formales donde la fórmula es otra.
- Considerar exponer también el cálculo "countback" (DSO clásico): tomar saldo pendiente actual y restarle ventas hasta agotar, días sumados = DSO. Es más caro pero más exacto, y el usuario puede comparar.

### I2. Pagos en aging incluyen movimientos con `caja_origen` (transferencias mal asignadas)

```python
# cuentas_corrientes.py:227-235
pagado_por_cliente = dict(
    db.query(...).filter(
        MovimientoCaja.id_cliente_relacionado.isnot(None),
        MovimientoCaja.caja_destino.isnot(None),
    ).group_by(...).all()
)
```

Falta `MovimientoCaja.caja_origen.is_(None)`, que sí está en `ledger_cliente` (cuentas_corrientes.py:130). Una transferencia entre cajas mal-asignada al cliente (`caja_origen` y `caja_destino` ambas seteadas) sumaría al `pagado_por_cliente` pero el ledger del mismo cliente NO la vería. Resultado: aging y ledger discrepan para ese cliente.

Es exactamente el mismo bug que I2 del review post-Sesión 5 que ya se arregló en otros lugares, pero acá quedó replicado. Recomendación: agregar `MovimientoCaja.caja_origen.is_(None)` al filtro. Test sugerido: crear movimiento con `caja_origen="A", caja_destino="B", id_cliente_relacionado=X` y verificar que NO aparece en `pagado_por_cliente`.

### I3. `dso()` con `ventas_periodo == 0` retorna 0, lo que es engañoso

Si en los últimos 90 días no hubo ninguna venta, devolver `dso_dias = 0` sugiere "los clientes pagan instantáneamente", cuando en realidad la métrica no es calculable. El frontend muestra "0 días" en la KpiCard sin distinción.

Recomendaciones (cualquiera):
- Retornar `dso_dias: None` y que el frontend muestre `-` en ese caso. La KpiCard ya tiene `dsoData ? dsoData.dso_dias : "-"`, así que extender a null es trivial.
- Retornar un campo `valido: false` con mensaje "sin ventas en el periodo".

Sin esto, la métrica miente cuando más debería gritar "no hay datos".

### I4. Caso pago > deuda: contabilizado pero NO documentado, e ítem desaparece del aging

```python
# cuentas_corrientes.py:264-275
for cli_id, info in por_cliente.items():
    pagado = Decimal(str(pagado_por_cliente.get(cli_id, 0)))
    restante = pagado
    for b in orden_buckets:
        ...
    info["total"] -= pagado
```

Si el cliente pagó $5000 y solo tenía $3000 de deuda (sobrepago, anticipo, o pago duplicado), `info["total"]` queda en `-2000`. Después:

```python
# cuentas_corrientes.py:281
if info["total"] <= 0:
    continue
```

El cliente desaparece del aging. **Eso es lo que pediste y es correcto contablemente** (si pagó de más, no tiene deuda). PERO es información valiosa: el cliente tiene $2000 de saldo a favor que el negocio le debe (o que se contabilizó erróneamente). Hoy se pierde silenciosamente.

Recomendación: separar `items` en `pendientes` (saldo > 0) y `con_credito` (saldo < 0) en el response. La UI ya tiene precedente: en `clientes_con_cuenta` el saldo negativo se muestra en verde. Coherente con eso, el aging debería exponer al menos un contador `clientes_con_credito_a_favor: N` para alertar.

### I5. Performance: `aging_cobros` carga TODAS las ventas pendientes en memoria

```python
# cuentas_corrientes.py:237-245
ventas = db.query(Venta).filter(...).order_by(Venta.fecha).all()
```

Con 10k ventas pendientes (escenario realista en algunos meses) eso es 10k objetos ORM hidratados, cada uno con todas sus columnas, solo para leer `fecha`, `total`, `id_cliente`, `cliente`. Hay overhead de:

- ORM hydration: ~10x más lento que un raw query con columnas selectivas.
- Memoria: con 30+ columnas en `Venta`, son varios MB por cada llamada.
- Cada hit del endpoint `/aging` paga ese costo.

Recomendaciones progresivas:
- **Mínimo**: `db.query(Venta.id_cliente, Venta.cliente, Venta.fecha, Venta.total).filter(...)` (tuplas, no objetos). Reduce 5x la memoria y 2-3x la latencia sin más cambio.
- **Si hace falta más**: bucketizar en SQL con `CASE WHEN`. Para SQLite es escribible pero feo; para Postgres futuro queda elegante. Devuelve agregados ya hechos. La aplicación FIFO inversa de pagos debe quedar en Python igual (es difícil en SQL puro), pero los buckets brutos pre-pago se calculan server-side.
- **Cachear** la respuesta: ya hay `_cache_helpers.py` en el codebase y `invalida_alertas` se usa en endpoints que mutan; aplicar el mismo patrón a `/aging` (TTL 5min) elimina el problema casi por completo en uso normal.

### I6. La heurística FIFO no está documentada y "FIFO inverso" es un nombre confuso

El docstring de `aging_cobros` dice "Aging de saldos pendientes por cliente, agrupado en buckets temporales." y nada más. La decisión "los pagos aplican primero al bucket más viejo" es un supuesto contable importante que merece estar explícito.

Realidad contable:
- En cuentas comerciales argentinas la convención común es **FIFO** (la deuda más vieja se cancela primero), salvo que el pago indique factura específica.
- Hay otros modelos: LIFO, prorrateo, asignación específica vía `pago_aplicado` (¡ya existe!).
- Lo que hace el código es FIFO clásico (no "inverso"): aplica al bucket más viejo primero, que es exactamente FIFO. El nombre del comentario `# FIFO inverso` es engañoso — se entiende como "primero pagás lo más nuevo", que sería LIFO. Renombrar el comentario a `# FIFO clásico (deuda más antigua primero)`.

Recomendación:
- Docstring actualizado con la convención: "Asume FIFO: los pagos no específicos se imputan a la deuda más antigua primero. Para imputación explícita, usar `pagos_aplicados`."
- Cuando se resuelva C1 (integración con `pagos_aplicados`), distinguir: aplicaciones explícitas → restan del bucket de la venta a la que se aplicaron; saldo del movimiento sin aplicar → FIFO.

---

## Suggestions

### S1. Tests faltantes (importantes para confianza en el aging)

Los tres tests cubren el camino feliz. Faltan:

1. **Pago > deuda total** (sobrepago): cliente con $1000 deuda y pago $1500. Debe quedar fuera de `items` y opcionalmente en una nueva sección `con_credito` (ver I4).
2. **Múltiples clientes mezclados**: el sort por `bucket_90_mas desc` no se ejercita con un solo cliente. Crear cliente X con $500 en +90, cliente Y con $1000 en +90 y verificar orden.
3. **DSO sin ventas en el periodo**: actualmente cubierto por defecto solo si pasa por el `else` (`ventas_total == 0`). Test explícito: DB vacía, llamar `dso(db, 30)`, ver qué retorna. Necesario antes de aplicar fix de I3.
4. **DSO con ventas todas cobradas**: `ventas_total = 10000, pendiente = 0`, debería dar `dso_dias = 0` (correcto en este caso). Test confirma.
5. **Aging con fecha futura**: ver C2.
6. **Aging cuando solo existe `id_cliente_relacionado` viejo Y también hay `pagos_aplicados`**: ver C1. Crítico antes de que la app empiece a usar el camino nuevo en producción.
7. **Filtro `caja_origen.is_(None)` en pagos**: ver I2.

### S2. Imports redundantes dentro de funciones

```python
# cuentas_corrientes.py:221-222 (dentro de aging_cobros)
from collections import defaultdict
from datetime import date, timedelta

# cuentas_corrientes.py:304 (dentro de dso)
from datetime import date, datetime, time, timedelta
```

`date` y `datetime` ya están importados arriba (línea 9). `defaultdict`, `timedelta`, `time` se pueden subir al top-level. Pequeño, pero hace el código más uniforme con el resto del archivo.

### S3. Magic strings de buckets duplicados

`"bucket_0_30"`, `"bucket_31_60"`, etc. aparecen en `cortes`, en el if/elif, en `orden_buckets`, en el output. Si mañana se cambia a 5 buckets (0-15, 16-30, ...) hay que tocar 4 lugares y los tests. Sugerencia:

```python
BUCKETS = [
    ("bucket_0_30", 30),
    ("bucket_31_60", 60),
    ("bucket_61_90", 90),
    ("bucket_90_mas", None),  # None = catch-all
]
```

Y derivar `cortes`, el if-cascade y `orden_buckets` (reversed) de esa lista. Refactor opcional, pero útil cuando cambian umbrales.

### S4. El frontend muestra "DSO (90 días)" sin permitir cambiar el periodo

El backend acepta `dias` como query param (`Query(90, ge=7, le=365)`) pero el frontend solo llama con `90` hardcoded:

```jsx
// CuentasCorrientes.jsx:24
api.get("/api/cuentas-corrientes/dso", { params: { dias: 90 } }),
```

Considerar un selector (30 / 60 / 90 / 180 / 365) cerca de la KpiCard. UX típica de dashboards financieros. Sin urgencia.

### S5. KpiCard "Top deudor" usa `clientes[0]` asumiendo orden por saldo

```jsx
// CuentasCorrientes.jsx:54
<KpiCard label="Top deudor" value={clientes[0]?.cliente || "-"} sub={fmtMoney(clientes[0]?.saldo || 0)} />
```

Esto depende de que el backend devuelva ya ordenado por `saldo desc`, que `clientes_con_cuenta` sí hace (línea 102). Pero si alguien refactorea el sort de backend, la KpiCard pasa a mostrar un cliente al azar. Defensivo: `[...clientes].sort((a,b) => b.saldo - a.saldo)[0]` o un comentario explícito.

### S6. La aplicación de pagos a buckets muta `info["buckets"]` en el mismo dict

```python
# cuentas_corrientes.py:270-273
si = info["buckets"][b]
if si > 0:
    aplicado = min(si, restante)
    info["buckets"][b] -= aplicado
    restante -= aplicado
```

Funciona, pero `defaultdict(Decimal)` significa que acceder `info["buckets"][b]` para un bucket sin ventas crea una entrada `Decimal(0)` por side-effect. No rompe nada, pero ensucia el dict (y lo verás en el output como ceros explícitos). Sugerencia: `si = info["buckets"].get(b, Decimal(0))`. O dropear el `defaultdict` y inicializar buckets explícitamente.

### S7. Variable `si` es un mal nombre

`si = info["buckets"][b]` — `si` colisiona con la palabra "if" en español y no dice qué representa. Renombrar a `saldo_bucket` o `pendiente_bucket`. Trivial pero mejora legibilidad.

---

## Plan deviations

No detecté deviations significativas respecto al alcance descrito de Sesión 3C: se agregaron `aging_cobros()` + `dso()` + dos endpoints + tres tests + cards en el frontend. Todo dentro del scope.

La interacción con `pagos_aplicados` (Sesión 4) NO fue parte del scope de 3C, pero es la deuda técnica más importante que queda viva (C1). Es razonable diferirla siempre que se documente y se schedule explícitamente.

---

## Resumen y recomendaciones de seguimiento

**Bloqueantes (resolver antes de exponer aging a usuarios para decisiones contables)**:
- C1: definir relación entre aging y `pagos_aplicados`. Hoy son inconsistentes apenas se use el camino nuevo.
- C2: manejar fechas futuras para no desinformar.

**Importantes (resolver pronto, no bloquean uso interno)**:
- I1: documentar/renombrar `dso_dias` para no confundir con DSO contable estándar.
- I2: agregar `caja_origen.is_(None)` para coherencia con `ledger_cliente`.
- I3: `dso` con `ventas_periodo=0` debería ser `null`, no `0`.
- I4: exponer clientes con saldo a favor en lugar de descartar silenciosamente.
- I5: optimizar query (al menos: select columnas específicas, ojalá: cache).
- I6: documentar la convención FIFO; el comentario `# FIFO inverso` es confuso.

**Sugerencias (baja prioridad)**:
- S1: ampliar tests (sobrepago, multi-cliente, DSO=0, aging con `pagos_aplicados`).
- S2-S7: limpieza de código, refactor de magic strings, mejoras menores de UI.

Lo que está bien hecho: uso consistente de `Decimal`, validación de rango en endpoint, sort por morosidad, estructura del response útil para auditoría, tests del camino feliz cubren la lógica central. Es una primera versión funcional sólida, pero conviene cerrar C1, C2 e I1 antes de promocionar la métrica como confiable para decisiones de negocio.
