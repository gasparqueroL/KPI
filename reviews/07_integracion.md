# Review final — Integración

Foco: cómo encajan los módulos de la sesión 5 (proveedores, cierres, pagos_aplicados, auth, CSV) con lo que ya estaba. No re-reviso diseño interno: solo gaps de costura y consistencia.

---

## Tests reales

```
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-9.0.3, pluggy-1.6.0
rootdir: C:\Users\HP ENVY\Desktop\KPI\backend
configfile: pytest.ini
collected 81 items

tests\test_caja_diaria.py ....                                           [  4%]
tests\test_caja_normalizacion.py .....                                   [ 11%]
tests\test_categorias_seed.py ..                                         [ 13%]
tests\test_cierres.py ..                                                 [ 16%]
tests\test_clasificar_linea.py .......                                   [ 24%]
tests\test_conciliacion.py .....                                         [ 30%]
tests\test_cuentas_corrientes.py .........                               [ 41%]
tests\test_importer_idempotencia.py ....                                 [ 46%]
tests\test_kpis_caja.py .                                                [ 48%]
tests\test_pagos_aplicados.py ........                                   [ 58%]
tests\test_parsing.py .......................                            [ 86%]
tests\test_periodo_anterior.py ....                                      [ 91%]
tests\test_proveedores.py ....                                           [ 96%]
tests\test_seguridad.py ...                                              [100%]

============================= 81 passed in 2.49s ==============================
```

81/81 verde, 0 skipped, 0 xfail. Tiempo total 2.49s. La cifra del enunciado es real.

Distribución por nuevos módulos sesión 5:
- `test_pagos_aplicados.py` — 8 tests (refactor solo backend, sin UI)
- `test_proveedores.py` — 4 tests (la mitad de cuentas_corrientes que tiene 9)
- `test_cierres.py` — 2 tests (escaso, ver issue Important #4)
- `test_seguridad.py` — 3 tests (auth + csv injection)

Aclaración para reproducir: pytest no estaba instalado en el venv del entorno; corrí `pip install -r requirements.txt` antes de la suite.

---

## Strengths

1. **Decorator `@invalida_alertas` aplicado consistentemente**: todos los routers nuevos lo usan en mutaciones (`proveedores_router.py:71,94,122,144,168,186`, `cierres_router.py:50,86`, `pagos_aplicados_router.py:23,34`). El bug crítico cross-review de la sesión 1 está resuelto y los módulos nuevos respetan la convención.
2. **Cierre por `(caja, fecha)`**: la lógica backend está bien aislada — `_verificar_no_bloqueado` (caja_diaria_router.py:30) chequea TANTO el estado actual como el nuevo del movimiento (línea 188), evitando que un edit "saque" un movimiento de una caja cerrada. El mensaje 403 nombra explícitamente la caja y la fecha, lo cual ayuda al usuario a entender el bloqueo.
3. **CSV injection patch correcto**: `_safe_csv_field` (cuentas_corrientes_router.py:31-39) cubre los 5 caracteres peligrosos (`= + - @ \t \r`). El test (`test_seguridad.py:28-37`) cubre los 4 principales y casos negativos.
4. **Hardening de proveedor**: `eliminar_factura` chequea pagos vinculados antes de borrar (proveedores_router.py:152) y `vincular_movimiento` rechaza no-egresos (línea 173). Tienen el mismo nivel de defensa que las protecciones de cuentas-corrientes.
5. **`marcar-cta-cte` con flag `forzar`**: patrón bonito — tira 409 con explicación, el frontend escucha el código y muestra `useConfirm` con `peligroso: true` (CuentasCorrientes.jsx:173-184). Es el único flujo "force" del sistema y está bien resuelto.

---

## Issues por severidad

### Critical

**C1. `requiere_api_key` está definido pero NO está enchufado en NINGÚN router.**
- `app/core/auth.py:20` define la dependency.
- `app/main.py` no la usa en `app = FastAPI(...)` ni como `dependencies=[...]` en ningún `include_router`.
- `Grep "Depends(requiere_api_key)"` → 0 matches en todo el backend (solo aparece en el test).
- Resultado: setear `KPI_API_KEY=xxx` en producción **no protege nada**. La API queda completamente abierta y el usuario va a creer lo contrario.
- El test `test_seguridad.py:16-25` pasa porque verifica la función aislada, no que esté wired. Es un falso positivo.
- Frontend tampoco manda `X-API-Key` (axios `client.js:3-6` no agrega headers). Si se enchufara la auth, todo el frontend rompería con 401 — pero ni siquiera llegamos a eso porque la auth no está activa.
- **Fix mínimo**: agregar `dependencies=[Depends(requiere_api_key)]` a `FastAPI(...)` en `main.py` excluyendo `/health` y `/api/admin/auth-status`. Y en `client.js` leer `import.meta.env.VITE_KPI_API_KEY` y meterlo como header default.

### Important

**I1. Sidebar tiene asimetría: "Caja / Finanzas" antes de "Caja diaria" pero ambas son del mismo dominio.**
- `Layout.jsx:45-54` orden actual: Dirección → Comercial → Caja/Finanzas → Caja diaria → Conciliación → Cuentas corrientes → Proveedores → Análisis → Importar → Casos → Configuración.
- "Caja / Finanzas" (Caja.jsx, 5.5KB) es la vista KPI agregada y "Caja diaria" (30KB) es donde se opera. Tenerlas separadas por el orden está bien, pero **falta cualquier indicador visual de que el cierre de caja vive DENTRO de Caja diaria**, no es un menú propio. Un usuario nuevo va a buscar "Cierre" en el sidebar y no lo va a encontrar.
- El item "Importar CSV" está al final junto con "Casos a revisar". Para un usuario que recién importó datos, "Importar" debería estar más visible. Pero si la app ya está en uso, está bien escondida.
- Sugerencia mínima: agrupar visualmente con un divider CSS o subtítulo: *Operación* (Caja diaria, Conciliación, Cuentas corrientes, Proveedores) vs *Análisis* (Dirección, Comercial, Análisis) vs *Setup* (Importar, Casos, Configuración).

**I2. Pantalla Proveedores le faltan features paralelas a Cuentas corrientes**:

| Feature | Cuentas corrientes | Proveedores |
|---|---|---|
| KPI Aging buckets | sí (0-30/31-60/61-90/+90) | **no** (solo "vencen en 30 días" plano) |
| KPI DSO/DPO | sí (DSO 90 días) | **no** |
| Export CSV extracto | sí (botón en detalle) | **no** |
| Detalle: editar venta inline | sí (`EditarVentaFila`) | **no** (no hay edit de factura inline) |
| Listado: top deudor en KPI | sí | **no** |
| Asignar movimiento | "Asignar →" simple (es por cliente) | "Vincular →" con select de factura (es por factura específica) — esto está bien, no es asimetría |

El backend tiene todo para resolver aging+DPO de proveedores: `aging_cobros` (cuentas_corrientes.py:219) podría replicarse como `aging_pagos` reusando `vencimientos_proximos`. Hoy `kpis/proveedores.py` no tiene `aging` ni `dpo` (greppeado, 0 matches).

Si el plan de la sesión 3 prometía paridad con cuentas a cobrar, falta cumplir eso.

**I3. `pagos_aplicados` está sin UI, el endpoint existe pero ningún frontend lo invoca.**
- `Grep "pagos-aplicados"` en `frontend/src` → 0 matches.
- El módulo backend está completo (`pagos_aplicados.py`, 8 tests, modelo `PagoAplicado`, router con 4 endpoints).
- Sin UI, los pagos parciales **siguen siendo invisibles para el usuario**. Hoy una venta de $10k cobrada en 3 plazos de $3.3k no muestra "saldo $0.1k" en el ledger — porque el ledger de cuentas-corrientes (`ledger_cliente`) no llama a `saldo_venta` de pagos_aplicados.
- Decisión: o se construye la UI (tabla de aplicación parcial debajo de cada venta en el detalle del cliente), o se borra/marca como "interno/futuro". Endpoint vivo sin frontend en producción es deuda peligrosa: alguien puede llamarlo desde Postman, crear filas en `pago_aplicado`, y los KPIs del frontend van a quedar inconsistentes con la BD.
- Mínimo aceptable hoy: agregar una nota en el `ledger_cliente.py` que diga "TODO: si hay pagos_aplicados para esta venta, restar del DEBE" y crear un test de regresión que falle si llegan filas a `pago_aplicado`. O incluir las aplicaciones en el extracto cronológico.

**I4. `test_cierres.py` solo tiene 2 tests para uno de los módulos más sensibles** (bloquea/desbloquea ediciones).
- Casos faltantes: cierre de caja A no bloquea movimientos en caja B (cross-caja); reabrir cierre re-habilita ediciones; cerrar caja con saldo manual distinto al calculado; tirar 409 si ya hay cierre del día; transferencia (caja_origen + caja_destino) bloqueada si CUALQUIERA de las dos cajas tiene cierre que cubre la fecha.
- Si bien los tests `test_caja_diaria.py` (4) podrían cubrir parcialmente el bloqueo, no hay tests cruzados en el subset que vi.

### Suggestions

**S1. Hardcoded `http://localhost:8000` en CuentasCorrientes.jsx:198** para el download del CSV. Como el resto de la app usa `api.baseURL`, bajar el archivo así rompe en producción si el backend cambia de host. Reemplazar con `${api.defaults.baseURL}/api/cuentas-corrientes/...` o usar `<a href={api.getUri({url: ...})}>`.

**S2. `vincularA` en Proveedores.jsx:186 usa un `<select>` con `onBlur={() => setVinculando(null)}`** que cierra el dropdown si el usuario hace click en el scrollbar del select, perdiendo la selección. UX muy frágil. En cuentas-corrientes el flujo es más simple (un botón "Asignar"), acá sería mejor abrir un Modal con búsqueda.

**S3. `Proveedores.jsx:32` calcula `totalSaldo` con `.reduce((s, p) => s + p.saldo, 0)`** sin validar que `p.saldo` sea número. Si la API devuelve `null` (proveedor sin facturas), el total se vuelve `NaN`. Defensivo: `s + (Number(p.saldo) || 0)`.

**S4. `ToastProvider` y `useToast` se importan pero `toast` queda definido y no usado en `Proveedores.jsx:9`** (línea 9: `const toast = useToast();` y nunca se llama en el componente raíz, solo en sub-componentes). Limpieza.

**S5. CajaDiaria.jsx:590 mensaje del cierre dice "movimientos de ese día y anteriores en esta caja NO se podrán editar"** — claro respecto a "esta caja", pero el formato del confirm sigue siendo texto plano con `\n\n`. Comparado con el mensaje de `marcar-cta-cte` que es server-side, este queda más caseroSimplemente decir "Solo se bloquea la caja seleccionada — las otras cajas siguen editables" reforzaría el mental model.

**S6. El BOM al inicio del CSV** (`buf.write("﻿")` en cuentas_corrientes_router.py:49) está OK, pero no hay test de que la respuesta empiece con BOM. Si alguien refactoriza eso, se rompe Excel y nadie se entera.

**S7. `auth_status` en admin_router.py:83** devuelve si auth está activa. Si la fix de C1 se hace, este endpoint debería dejar de requerir auth (es lo único razonable que se podría llamar sin key, para que el frontend sepa si necesita pedirle la key al usuario).

---

## UX gaps post-sesión 5

1. **No hay manera de aplicar un pago parcial desde la UI** (issue I3): la única forma de asignar cobro a venta sigue siendo asignar el movimiento entero al cliente (no a la venta). Todos los KPIs de aging asumen "saldo de cliente = total - cobrado total", lo cual funciona si los montos calzan, pero no si hay sobrepago/parcial.
2. **Paridad visual proveedor vs cliente** (I2): el usuario que aprende el flujo en cuentas-corrientes va a buscar "aging" y "DSO" en proveedores y no los va a encontrar. Inconsistencia confunde.
3. **Cierre de caja descubrible solo por scroll**: vive al final de Caja Diaria. Un atajo desde el sidebar o un badge "X días sin cerrar" ayudaría.
4. **CSV solo desde detalle de cliente**: no hay export de listado de proveedores con saldo, ni de aging completo, ni de movimientos de un día. El usuario que quiere llevarse data a Excel solo puede hacer 1 cliente a la vez.
5. **Frontend no soporta auth API key**: si en algún momento se enchufa C1, hay que tocar `client.js` y cargar la key de env o de localStorage. Hoy no hay ningún hook para eso.

---

## Plan de cierre (top 5)

Ordenado por riesgo / esfuerzo:

1. **[Critical, 30 min]** Resolver C1: enchufar `Depends(requiere_api_key)` en el `FastAPI(...)` con whitelist para `/health` y `/api/admin/auth-status`, y agregar header `X-API-Key` en `client.js` leyendo `VITE_KPI_API_KEY` (o equivalente). Sin esto, el feature de seguridad es decorativo y mentiroso.

2. **[Important, 45 min]** Decidir destino de `pagos_aplicados` (I3): o construir la UI mínima (sub-tabla en detalle de cliente con "Aplicar parcialmente $X de este movimiento a esta venta"), o feature-flag el router behind config para no exponerlo. Tener endpoints públicos sin frontend es invitación a inconsistencia.

3. **[Important, 1h]** Cerrar gap de paridad proveedores (I2): agregar `aging_pagos` + `dpo` en `kpis/proveedores.py` siguiendo el mismo shape que `aging_cobros`/`dso`, exponer en `proveedores_router.py`, y mostrar las 4 KPI cards en la cabecera de `Proveedores.jsx`. Reusar `KpiCard`. Esto le da al usuario las herramientas equivalentes para decidir "a quién pagar primero" igual que ya tiene "a quién cobrar primero".

4. **[Important, 30 min]** Sumar 4-5 tests más en `test_cierres.py` (I4): cross-caja, transferencia bloqueada, reabrir habilita edits, doble cierre rechaza. Es el módulo con más blast radius (un cierre incorrecto bloquea todo el operativo) y solo tiene 2 tests.

5. **[Suggestion, 15 min]** Limpieza y consistencia chica (S1, S3, S4): hardcoded localhost en download CSV, NaN defensivo, imports no usados. Triviales pero ensucian el código y el localhost rompe el deploy.

Total estimado: ~3 horas. Después de esto, los módulos nuevos quedan integrados con el mismo nivel de pulido que los viejos.
