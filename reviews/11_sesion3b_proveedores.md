# Review Sesión 3B — Proveedores + Cuentas a Pagar

Fecha review: 2026-05-02
Alcance: catálogo de proveedores, facturas con vencimiento, vinculación de pagos (egresos) a facturas, ledger por proveedor.

Archivos revisados:
- `C:\Users\HP ENVY\Desktop\KPI\backend\app\models\proveedor.py`
- `C:\Users\HP ENVY\Desktop\KPI\backend\app\kpis\proveedores.py`
- `C:\Users\HP ENVY\Desktop\KPI\backend\app\routers\proveedores_router.py`
- `C:\Users\HP ENVY\Desktop\KPI\backend\tests\test_proveedores.py`
- `C:\Users\HP ENVY\Desktop\KPI\frontend\src\pages\Proveedores.jsx`
- `C:\Users\HP ENVY\Desktop\KPI\backend\app\models\movimiento_caja.py` (referencia FK)

Nota: NO se reabre el hallazgo I2 (transferencias contadas como pagos), ya marcado y arreglado post-sesión 5. Se confirma que `proveedores_con_saldo`, `vencimientos_proximos` y `ledger_proveedor` filtran correctamente con `caja_destino.is_(None)`.

---

## Strengths

1. **Modelado limpio y simétrico con clientes**: `Proveedor` + `FacturaProveedor` con `cascade="all, delete-orphan"` + relación inversa `back_populates`. Sigue el mismo patrón usado para clientes/ventas, lo que facilita razonar.
2. **Filtro de "egreso puro" consistente** en los tres lugares que importan (`proveedores_con_saldo`, `ledger_proveedor`, `vencimientos_proximos`): `caja_origen IS NOT NULL AND caja_destino IS NULL`. La regla está aplicada uniformemente.
3. **Uso correcto de Decimal** para sumas de saldo: las funciones de KPI usan `Decimal(str(...))` para evitar precisión float, y solo convierten a `float` en el borde de salida (JSON).
4. **`eliminar_factura` defensivo**: bloquea borrado si hay pagos vinculados, con mensaje claro indicando la acción correctiva (desvincular primero). Devuelve 409, no 500.
5. **`vincular_movimiento` valida tipo de movimiento**: rechaza intentos de vincular transferencias o ingresos con HTTPException 400 y mensaje explicativo. Esa fue exactamente la corrección de I2 trasladada al endpoint de vinculación.
6. **Ledger ordena correctamente**: `eventos.sort(key=lambda e: (e["fecha"][:10], 0 if e["tipo"] == "factura" else 1))` — facturas antes que pagos en mismo día. Saldo corrido bien calculado.
7. **Validación `total > 0` en backend**: `crear_factura` rechaza `total <= 0` antes de tocar la DB. El frontend (`AltaFactura.guardar`) también valida en el cliente, así que hay defensa en profundidad.
8. **Tests cubren los tres caminos críticos**: proveedor sin facturas (saldo cero), factura genera saldo, pago vinculado reduce saldo + vencimientos filtra pagadas. La aserción `len(out) == 1, "la factura pagada no debe aparecer"` es explícita.
9. **UX del frontend**: KPIs claros (`Total a pagar`, `Vencen en 30 días`), badges color-coded por urgencia (`vencida` rojo, `<=7d` warn, resto muted), y panel de "egresos sin vincular" con búsqueda en detalle pre-llenada con el nombre del proveedor.

---

## Critical

### C1. Cascade de Proveedor deja FKs huérfanas en MovimientoCaja

`Proveedor.facturas` tiene `cascade="all, delete-orphan"`, así que borrar un proveedor borra sus facturas. Pero la FK en `MovimientoCaja.id_factura_proveedor`:

```python
# app/models/movimiento_caja.py:49-51
id_factura_proveedor = Column(
    Integer, ForeignKey("facturas_proveedor.id"), nullable=True, index=True
)
```

No tiene `ondelete=...`, no hay relationship inversa con cascade, y SQLite por defecto NO enforce FKs salvo que se haga `PRAGMA foreign_keys=ON` en cada conexión. Resultado:

- En SQLite (entorno actual): borrar un proveedor con facturas pagadas deja `MovimientoCaja.id_factura_proveedor` apuntando a IDs inexistentes. `proveedores_con_saldo` y `ledger_proveedor` los ignoran (porque hacen JOIN con FacturaProveedor), pero el dinero "desaparece" del lado del proveedor sin trazabilidad. No hay log, no hay error, simplemente FK rota silenciosa.
- En Postgres (futuro): el `db.delete(proveedor)` haría que SQLAlchemy intente borrar la factura, y el RDBMS rechaza con `ForeignKeyViolation` por la referencia desde `movimientos_caja`. El usuario ve un 500 críptico.

Además, no hay endpoint `DELETE /api/proveedores/{id}`, así que esto solo se dispara si alguien borra desde shell/migración, pero la trampa queda sembrada. **Recomendaciones (cualquiera de las dos)**:

a) Agregar `ondelete="SET NULL"` en la FK + un guard en futuro endpoint de delete (rechazar si tiene movimientos vinculados, igual que `eliminar_factura`).
b) Cambiar el cascade del proveedor a `cascade="all"` (sin `delete-orphan`) y no permitir borrar proveedor con facturas/movimientos; usar `activo=False` para "baja lógica".

Mi recomendación: (b), que es coherente con el campo `activo` ya existente en el modelo (que actualmente no se usa para filtrar nada — ver M2).

### C2. `vincular_movimiento` no valida que la factura sea del proveedor "actual"

`POST /api/proveedores/movimiento/{id}/vincular` solo verifica:
1. Movimiento existe.
2. Es egreso puro.
3. Factura existe.

NO valida que el proveedor de la factura sea el que el usuario "está mirando". El frontend desde `DetalleProveedor` solo ofrece facturas del proveedor activo (lo arma de `data.eventos`), pero la API es pública: cualquier cliente HTTP puede pasar `id_factura` de OTRO proveedor y el sistema lo acepta sin chistar. Resultado: el pago aparece en el ledger del proveedor "dueño" de esa factura, no del que el usuario quería. Ningún test cubre esto.

Tampoco hay validación de que el monto del movimiento `<=` pendiente de la factura, ni que la fecha del pago sea posterior a la emisión. Estos dos últimos son discutibles (puede haber adelantos), pero el primero (consistencia proveedor-factura-movimiento) sí es un bug.

**Fix sugerido**: el endpoint debería recibir también `id_proveedor` (o derivarlo y validarlo):

```python
factura = db.get(FacturaProveedor, data.id_factura)
if factura is None: raise HTTPException(404, "Factura no encontrada")
# si el frontend manda id_proveedor en el body o la URL:
# if factura.id_proveedor != id_proveedor_url: raise HTTPException(400, "...")
```

Como mínimo, devolver el `id_proveedor` resultante para que el caller pueda verificar. Idealmente cambiar la URL a `POST /api/proveedores/{id_proveedor}/movimiento/{id}/vincular` y validar que `factura.id_proveedor == id_proveedor`.

---

## Important

### I1. Edge case de `pendiente <= 0` con redondeo Decimal

Pregunta del foco: `pendiente = Decimal(str(f.total)) - pagado`. ¿Hay edge case con redondeo?

**Análisis**:
- `FacturaProveedor.total` es `Numeric(14, 2)` → SQLAlchemy devuelve Decimal con escala 2.
- `MovimientoCaja.monto` también es `Numeric(14, 2)` (verificado en modelo). El `func.sum(...)` en SQLite devuelve un Decimal que puede tener más precisión interna pero los operandos están a 2 decimales.
- En la práctica, `pendiente` siempre tendrá ≤ 2 decimales reales y el `<= 0` funciona bien.

**Pero**: si en el futuro se permite `monto` con 4 decimales (ej. ajustes de cambio en multimoneda) o si Postgres devuelve `func.sum` como `Numeric(14+escala, 4)`, podría ocurrir `pendiente = Decimal("0.0000")` que `<= 0` sigue siendo True (correcto), o `Decimal("-0.005")` que sería False y mostraría una factura "casi pagada" como pendiente con monto residual de medio centavo.

**Recomendación**: usar tolerancia explícita y ser más conservador:

```python
if pendiente <= Decimal("0.01"):  # menos de un centavo, considerar pagada
    continue
```

Y exponer `pendiente` redondeado: `_to_float(pendiente.quantize(Decimal("0.01")))`. Mismo principio aplicaría en `proveedores_con_saldo.saldo`. Hoy no es un bug observable pero es una bomba de tiempo si entran movimientos importados con escalas distintas (ya hubo un episodio con `Decimal` en sesiones previas según los reviews acumulados).

### I2. `vencimientos_proximos` con `dias=0` — comportamiento del Query

El endpoint declara `dias: int = Query(30, ge=1, le=365)`. Con `ge=1`, FastAPI rechaza `dias=0` con 422 antes de llegar a la función. **No es bug**, es por diseño.

Pero el límite inferior `ge=1` impide consultar "qué vence HOY exactamente", que es un caso de uso legítimo. Con `dias=1` se incluyen facturas con `fecha_vencimiento <= hoy + 1 día`, o sea HOY + MAÑANA. Si el usuario quiere solo HOY, no puede.

**Recomendación**: bajar a `ge=0` y documentar que `dias=0` significa "vencen hoy o ya vencidas". El código ya lo soporta: `limite = hoy + timedelta(days=0) = hoy`, y el filtro `fecha_vencimiento <= hoy` es correcto. Importante: aún con `dias=0` se devuelven las **vencidas pasadas**, no solo las de hoy, porque no hay límite inferior en la query — esto está bien (uno quiere ver las vencidas), pero el nombre `vencimientos_proximos` es engañoso. Considerar agregar una nota en el docstring o renombrar a `facturas_pendientes_o_vencidas`.

### I3. No hay path de "anular factura sin borrar"

`eliminar_factura` rechaza correctamente si hay pagos vinculados. Pero no hay forma de anular una factura cargada por error que YA tiene pagos vinculados (ej. carga duplicada que el usuario cobró parcialmente). El usuario tendría que:
1. Desvincular cada pago manualmente.
2. Borrar factura.
3. Volver a vincular pagos.

No hay endpoint `PATCH /api/proveedores/factura/{id}` para editar `total` o `observaciones`, ni un campo `anulada: bool` o `estado: str`. **Falta** un mecanismo de "soft-delete" o "anulación" que:
- Mantenga la factura en histórico (auditoría).
- La excluya de cálculos de saldo y vencimientos.
- Permita agregar nota de anulación en `observaciones`.

**Recomendación**: agregar `anulada = Column(Boolean, default=False)` en el modelo, filtrar en las tres KPIs (`proveedores_con_saldo`, `ledger_proveedor`, `vencimientos_proximos`), y endpoint `POST /api/proveedores/factura/{id}/anular` que requiera motivo (lo guarda en observaciones) y desvincule los pagos asociados (poniéndolos como "sin asignar"). El campo `observaciones` ya existe en el modelo (línea 36) pero NO se expone en el ledger ni se devuelve en ningún endpoint — ver M3.

### I4. `DetalleProveedor` muestra TODAS las facturas en el select de vinculación, incluso pagadas

```jsx
const facturasParaVincular = data.eventos.filter((e) => e.ref_tipo === "factura");
```

No hay filtro por "pendiente > 0". Si una factura está completamente pagada (3 pagos sumando el total), igual aparece en el dropdown como opción. El usuario podría sobre-pagar accidentalmente. El backend no rechaza esto (no valida monto pago vs pendiente), así que el ledger mostraría saldo NEGATIVO en ese proveedor.

**Fix sugerido**: el ledger del backend debería incluir `pendiente_por_factura` por evento factura, y el frontend filtrar:

```jsx
const facturasParaVincular = data.eventos.filter(
  (e) => e.ref_tipo === "factura" && e.pendiente > 0
);
```

Hoy esto requiere recalcular en frontend (sumar `haber` de pagos vinculados a cada factura, lo cual no es trivial porque el ledger no expone `id_factura` por movimiento). Mejor: agregar `pendiente` al evento factura desde el backend en `ledger_proveedor`.

### I5. Falta paridad de aging para proveedores

Confirmado: NO existe `aging_pagos` ni `aging_proveedores` equivalente al `aging_cobros` que existe para clientes. La review post-sesión 5 lo marcó como "paridad faltante" — **es feature deferred, no bug**, pero amerita ticket explícito porque para una herramienta de cuentas a pagar el aging (qué tan vieja es la deuda) es información de primera necesidad, mucho más útil que el simple "vence en N días".

`vencimientos_proximos` da una vista forward-looking de 30 días, pero no responde "cuánto le debo a cada proveedor en buckets 0-30 / 31-60 / 61-90 / 90+ días desde fecha_emision o fecha_vencimiento". Sin esto, no se pueden priorizar pagos por antigüedad de deuda ni detectar proveedores con deuda crónica.

**Recomendación**: crear `aging_proveedores(db, base="vencimiento" | "emision")` siguiendo el shape del `aging_cobros` para reutilizar el componente frontend.

---

## Minor

### M1. `proveedores_con_saldo` hace 3 queries y ensambla en Python

```python
facturado = dict(...)         # query 1: sum por proveedor
pagado_por_factura = dict(...)# query 2: sum por factura
facturas_a_proveedor = dict(...) # query 3: factura -> proveedor
```

Esto es O(N) en filas + ensamblado en Python que puede simplificarse a una sola query con dos LEFT JOINs y subqueries:

```sql
SELECT p.id, p.nombre, p.cuit, ...,
       COALESCE(f.facturado, 0) - COALESCE(pg.pagado, 0) AS saldo
FROM proveedores p
LEFT JOIN (SELECT id_proveedor, SUM(total) AS facturado FROM facturas_proveedor GROUP BY id_proveedor) f ON f.id_proveedor = p.id
LEFT JOIN (SELECT fp.id_proveedor, SUM(mc.monto) AS pagado
           FROM movimientos_caja mc JOIN facturas_proveedor fp ON fp.id = mc.id_factura_proveedor
           WHERE mc.caja_origen IS NOT NULL AND mc.caja_destino IS NULL
           GROUP BY fp.id_proveedor) pg ON pg.id_proveedor = p.id
ORDER BY saldo DESC NULLS LAST
```

No es crítico hoy (proveedores son pocos), pero a partir de ~1000 facturas el costo del round-trip se nota. Defer hasta tener número.

### M2. El campo `activo` no se usa en filtros

`Proveedor.activo` existe (default `True`) y se puede editar via `PATCH /api/proveedores/{id}`, pero **ningún endpoint filtra por `activo`**:
- `proveedores_con_saldo` lista TODOS, activos e inactivos por igual.
- El frontend muestra `activo` en el saldo pero no permite ocultar inactivos.

Si la idea es "dar de baja sin borrar", hoy no tiene efecto visible. **Recomendación**: agregar query param `incluir_inactivos: bool = False` en `GET /api/proveedores`, default ocultarlos, y un toggle en frontend.

### M3. Campo `observaciones` no se expone

`FacturaProveedor.observaciones` existe en el modelo y es seteado por `crear_factura`, pero `ledger_proveedor` no lo devuelve en los eventos de tipo factura. El usuario lo carga y nunca lo vuelve a ver. Tampoco hay endpoint para editarlo. Agregar `"observaciones": f.observaciones` al dict de evento factura.

### M4. `_to_float` es defensivo pero los Decimal no son None

`_to_float(v) -> float: return float(v) if v is not None else 0.0`. En todos los call sites el valor proviene de `Decimal(0)` o de `Decimal(str(x))`, nunca de `None`. La defensa no aporta y oculta el origen del dato. Aceptable como "belt and suspenders" pero también un olor a "no estoy seguro de dónde viene esto".

### M5. Frontend `AltaProveedor`: import `useToast` duplicado

En `Proveedores()` (línea 9) y dentro de `AltaProveedor` (línea 120) se llama `useToast()` por separado. No es bug (cada componente puede tener su propio hook), pero `AltaProveedor` recibe `onClose`/`onSaved` y no necesitaría toast propio; podría delegarlo al padre. Cosmético.

### M6. `cascade="all, delete-orphan"` con `Proveedor.facturas` — inconsistencia con `eliminar_factura`

El cascade dice "si remuevo una factura del array `proveedor.facturas`, se borra". Pero `eliminar_factura` valida n_pagos primero. Si alguien hace `proveedor.facturas.remove(factura)` desde código (no via endpoint), se salta esa validación. Improbable con la API actual, pero la regla "no borrar facturas con pagos" no está en el modelo, solo en el endpoint — un test futuro o script podría romper invariante silenciosamente.

**Recomendación**: mover validación a un evento SQLAlchemy `before_delete` en `FacturaProveedor` o agregar un constraint a nivel DB (`ON DELETE RESTRICT` desde `MovimientoCaja.id_factura_proveedor`).

### M7. `crear_factura` acepta `total: float`

```python
class NuevaFactura(BaseModel):
    total: float
```

Y luego `Decimal(str(data.total))`. Mejor recibir `total: Decimal` o `condecimal(gt=0, max_digits=14, decimal_places=2)` y dejar que Pydantic v2 valide tipo + precisión + signo en una sola línea, eliminando la conversión manual y el guard `if data.total <= 0`. Mismo patrón en `MovimientoCaja` (asumo) — defer si es estilo de codebase.

### M8. `vencimientos_proximos` filtra por `<= limite` pero no por `>= alguna_fecha`

Esto incluye facturas vencidas hace 5 años. Funcionalmente puede ser deseado ("mostrarme TODA la deuda no pagada con vencimiento"), pero el nombre `proximos` sugiere lo contrario. Frontend muestra `vencida {N}d` con badge rojo, así que funciona como "deuda pendiente o por vencer". Aclarar nombre o agregar parámetro `incluir_vencidas: bool = True` (con default actual) para hacer el contrato explícito.

---

## Tests faltantes

1. **C2 cubierto**: test que `vincular_movimiento` con factura de otro proveedor falle (hoy NO falla, hay que arreglar primero, luego testear).
2. **Cascade C1**: test que borrar proveedor (cuando se agregue endpoint) no rompa FK; o que rechace si hay facturas con pagos vinculados.
3. **`eliminar_factura` con pagos vinculados** devuelve 409: no hay test explícito de la rama `n_pagos > 0`.
4. **`crear_factura` con `total <= 0`** retorna 400: hay validación, no hay test.
5. **`crear_factura` con `id_proveedor` inexistente** retorna 404: hay validación, no hay test.
6. **`vincular_movimiento` con transferencia** (caja_origen + caja_destino) retorna 400: validación clave de I2 sin cobertura de regresión.
7. **`vincular_movimiento` con ingreso** (caja_origen=None) retorna 400: idem.
8. **`vencimientos_proximos` con factura vencida** (`fecha_vencimiento < hoy`) la incluye con `dias_para_vencer < 0` y `vencida=True`: no testeado, es la rama UI más visible (badge rojo).
9. **`vencimientos_proximos` con `dias_ventana=1`** discrimina correctamente entre "vence mañana" (incluida) vs "vence pasado mañana" (excluida).
10. **Ledger ordenamiento mismo día**: dos eventos misma fecha (factura + pago) con orden correcto factura→pago. El test actual usa fechas distintas.
11. **`desvincular_movimiento`**: no hay test. Caso particularmente importante: tras desvincular, `proveedores_con_saldo` debe re-incluir el monto en pendiente.
12. **Saldo negativo / sobre-pago**: vincular pagos por más del total de una factura — qué pasa con `saldo_actual` del ledger (debería ir negativo) y con `pendiente` en `vencimientos_proximos` (hoy quedaría < 0 y se excluye, ver I4).

---

## Recomendaciones priorizadas

1. **C2** (validar coherencia factura-proveedor en `vincular_movimiento`) — fix simple, alto impacto en correctitud. **Hacer ya.**
2. **C1** (cascade FK rota) — definir política de baja de proveedor antes de tener un endpoint DELETE. Recomiendo soft-delete via `activo=False` (M2).
3. **I3** (anulación de facturas) — necesario para uso real; agregar `anulada: bool` y endpoint `anular` con motivo en `observaciones`.
4. **I4** (filtrar facturas pagadas del select de vinculación) — UX crítica para evitar sobre-pagos. Requiere exponer `pendiente` por factura en `ledger_proveedor`.
5. **I5** (aging para proveedores) — paridad con clientes; impacta priorización de pagos.
6. **I2** (`dias=0` y nombre engañoso) — bajar `ge=1` a `ge=0` y/o mejorar docstring.
7. **I1** (tolerancia Decimal) — agregar `quantize(Decimal("0.01"))` y comparar con `Decimal("0.01")`.
8. **Tests faltantes 1, 2, 3, 6, 11, 12** — cubrir antes de la próxima sesión que toque proveedores.
9. **M2, M3** (campo `activo` y `observaciones` ignorados) — exponerlos para que dejen de ser data muerta.

Conclusión: la sesión 3B entregó funcionalidad sólida y simétrica con clientes, con buen filtrado del bug I2 (transferencias). Los dos hallazgos críticos (C1 cascade, C2 cross-tenant en vinculación) son del tipo "no se ven hoy pero te muerden mañana"; recomiendo arreglarlos antes de la próxima ronda de features de proveedores. La paridad de aging (I5) es la única "feature gap" estructural pendiente.
