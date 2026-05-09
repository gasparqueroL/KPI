# Review final — Bugs

## Resumen
**3 críticos / 7 importantes / 5 menores**

Lo nuevo de sesión 5 está bastante sólido, pero hay 3 bugs reales que pueden causar corrupción contable o "feature de seguridad que no protege nada". El más grave es que `requiere_api_key` no se aplica a NINGÚN endpoint — el módulo existe pero el sistema sigue 100% abierto. Los otros dos críticos son double-counting potencial entre `pago_aplicado` y el ledger basado en `id_cliente_relacionado`, y la posibilidad de aplicar pagos desde transferencias (que no son cobranzas).

---

## Critical (bug real, riesgo de corrupción / crash)

### C1 — `requiere_api_key` NO se aplica a ningún endpoint (auth de cartón)
**Archivo:** `backend/app/main.py:53-67` (uso) + `backend/app/core/auth.py` (definición)

**Repro:**
```bash
grep -r "requiere_api_key" backend/app/routers/   # → 0 matches
grep -r "Depends(requiere_api_key)" backend/      # → 0 matches
```
El dependency está definido y testeado en aislamiento (`test_seguridad.py`), pero no se incluye en `app.dependencies=[...]`, ni en `APIRouter(dependencies=...)`, ni como `Depends(...)` en handlers. Setear `KPI_API_KEY=secreto` no protege nada; el header `X-API-Key` se ignora porque nadie lo pide.

**Fix:** Aplicarlo globalmente en `main.py` o por router. Ejemplo global:
```python
from app.core.auth import requiere_api_key
app = FastAPI(..., dependencies=[Depends(requiere_api_key)])
```
o por router en cada `include_router(..., dependencies=[Depends(requiere_api_key)])`. Recordá excluir `/health`. Y agregar un test e2e con TestClient que verifique 401 cuando la env var está seteada y no llega el header.

---

### C2 — `aplicar_pago` acepta movimientos que son TRANSFERENCIAS (caja_origen + caja_destino)
**Archivo:** `backend/app/kpis/pagos_aplicados.py:49-50` y `disponible_movimiento` 25-33

**Repro:** Un movimiento "Balance" entre cajas tiene `caja_origen='c1'` y `caja_destino='c2'`. La validación de `aplicar_pago` solo chequea `if m.caja_destino is None`. Una transferencia pasa el filtro y se puede aplicar a una venta como si fuera cobranza, inflando `total_haber` del cliente y desincronizando saldo de cajas.

**Fix:** Agregar
```python
if m.caja_origen is not None:
    raise ValueError("El movimiento debe ser un ingreso PURO (sin caja_origen)")
```
en `aplicar_pago` (línea 50) **y** en `disponible_movimiento` (línea 28) hacer `if m is None or m.caja_destino is None or m.caja_origen is not None:`. Idealmente también validar contra `CategoriaCaja.es_ingreso_operativo` igual que hace `cuentas_corrientes_router.asignar_movimiento`.

---

### C3 — Double-counting potencial entre `pago_aplicado` (nuevo) y `id_cliente_relacionado` (viejo)
**Archivo:** `backend/app/kpis/cuentas_corrientes.py:58-66` (clientes_con_cuenta) + `127-131` (ledger_cliente) + `227-235` (aging_cobros) + `pagos_aplicados.py:14-22` (saldo_venta)

**Repro:**
1. Crear venta `p1` total=10000 marcada cta cte, cliente=10.
2. Crear movimiento `m1` ingreso=3000 caja_destino="cl", `id_cliente_relacionado=10`.
3. Llamar `POST /api/pagos-aplicados` para aplicar 3000 de m1 a p1.
4. `GET /api/cuentas-corrientes/10/ledger` → muestra venta 10000 (debe) y pago 3000 (haber) → saldo 7000 (correcto vía vía vieja).
5. `GET /api/pagos-aplicados/venta/p1` → `saldo_venta = 7000` (correcto vía nueva).
6. Pero NUNCA se chequea consistencia. Si el usuario aplica m1 a p1 vía API nueva pero también lo asigna a otro cliente vía vieja (o lo desasigna del cliente 10), los dos sistemas divergen sin alarma.

Caso peor: aplicar 3000 a p1, después desaplicar (`DELETE /api/pagos-aplicados/{id}`). El ledger del cliente sigue mostrando el pago de 3000 vía `id_cliente_relacionado` (porque el movimiento sigue asignado al cliente 10), pero `saldo_venta(p1)` vuelve a 10000. Doble verdad sobre el mismo pago.

**Fix mínimo:** Decidir cuál es la fuente de verdad y enforzarlo.
- Opción A (preferida): hacer que `ledger_cliente` y `aging_cobros` calculen cobranzas a partir de `pago_aplicado` cuando exista, y caigan a `id_cliente_relacionado` solo si no hay aplicaciones para esa venta. Documentar que no se puede tener ambas.
- Opción B: en `aplicar_pago`, si el movimiento ya tiene `id_cliente_relacionado` ≠ del cliente de la venta, raisear error. Y al desaplicar, advertir.
- Como mínimo: tests que demuestren el escenario y comentario explícito en `pago_aplicado.py:9` ("NO reemplaza...") explicando QUÉ se cuenta dónde y QUIÉN gana cuando hay conflicto.

---

## Important

### I1 — `aplicar_pago(monto=None)` después de aplicación parcial: comportamiento sutil pero correcto
**Archivo:** `backend/app/kpis/pagos_aplicados.py:60, 67-77`

**Análisis:** Llamar 2 veces con `monto=None` SÍ funciona correctamente:
- 1ª llamada: `min(saldo, disp) = min(10000, 3000) = 3000`. Crea registro con monto=3000.
- 2ª llamada: `saldo_venta = 10000 - 3000 = 7000`, `disponible = 3000 - 3000 = 0`. La función falla con `"El movimiento no tiene saldo disponible"` ANTES de llegar al merge. Bien.

Pero si `monto=None` y la venta YA está totalmente cobrada por OTRO movimiento, falla con "La venta ya está totalmente cobrada" — eso es correcto.

El bug real está en otro escenario: si **se borra el `existente` por desaplicación entre las dos llamadas**, no hay race protection. Como no hay `with_for_update()` ni transacción única, dos requests concurrentes pueden ambas leer "no existente" y crear DOS PagoAplicado con el mismo (id_venta, id_movimiento). El UniqueConstraint los protege a nivel DB (ok), pero la 2ª transacción tira IntegrityError no atajado → 500. Si dos requests son `monto=1000` cada uno con disp=3000, ambas leen disp=3000, ambas insertan 1000 → solo una sobrevive.

**Fix:** Capturar `IntegrityError` y reintentar o devolver 409 amigable. O envolver en transacción serializable. Para single-user no es crítico, pero el TODO debería estar.

---

### I2 — `ledger_proveedor` cuenta transferencias como pagos al proveedor
**Archivo:** `backend/app/kpis/proveedores.py:75-80`, `proveedores_con_saldo` 27-35, `vencimientos_proximos` 139-147

**Repro:** Movimiento de tipo "Balance" con `caja_origen="c1"`, `caja_destino="c2"`, y `id_factura_proveedor=5` (alguien lo vinculó por error o mal flujo). El filtro es solo `MovimientoCaja.caja_origen.isnot(None)` — la transferencia pasa, y aparece como pago al proveedor reduciendo el saldo y filtrando la factura de "vencimientos próximos". Plata fantasma pagada.

**Fix:** Agregar filtro `MovimientoCaja.caja_destino.is_(None)` en los tres lugares (proveedores.py 33, 79, 144) para asegurar que solo egresos puros cuenten como pagos. Y/o validar en `proveedores_router.vincular_movimiento` (línea 173) que `m.caja_destino is None`.

---

### I3 — `caja_esta_bloqueada`: lógica `>=` puede ser incorrecta vs el modelo "bloqueado HASTA fecha"
**Archivo:** `backend/app/kpis/cierres.py:42-45`

**Análisis del código:** `return ult is not None and ult >= fecha`. Entonces si último cierre es 2026-04-30:
- fecha=2026-04-30 → bloqueado (correcto)
- fecha=2026-04-15 → bloqueado (correcto, está antes del cierre)
- fecha=2026-05-01 → NO bloqueado (correcto)

Mirado así está bien. **Pero** `fecha_ultimo_cierre` devuelve `MAX(fecha)` para esa caja. Considerá: hay cierres en 2026-04-30 y 2026-03-31. El 2026-03-31 ya queda implícitamente cubierto por el 2026-04-30, OK. Pero si alguien REABRE el cierre de 2026-04-30 (vía DELETE) sin reabrir el de 2026-03-31, ahora `MAX = 2026-03-31` y un movimiento del 2026-04-10 vuelve a ser editable — aunque conceptualmente "el cierre de marzo lo cubre" porque es un mes ya cerrado.

**Repro:** crear cierre marzo 31, crear cierre abril 30, hacer DELETE del de abril, ahora un movimiento del 5 de abril es editable de nuevo. ¿Es eso lo querido? Si "reabrir" significa solo abrir abril, no debería desbloquear marzo. Si significa abrir todo, semánticamente confuso.

**Fix:** Documentar muy explícito qué hace el reabrir, o cambiar `caja_esta_bloqueada` para que use `EXISTS` en vez de MAX:
```python
return db.query(CierreCaja.id).filter(
    CierreCaja.caja == caja, CierreCaja.fecha >= fecha
).first() is not None
```
Así DELETE de abril deja marzo intacto y el 5 de abril sigue bloqueado.

---

### I4 — Aging y DSO ignoran completamente `pago_aplicado` (siempre miran movimiento total)
**Archivo:** `backend/app/kpis/cuentas_corrientes.py:227-275` (aging) y `302-336` (dso)

**Repro:** Venta p1 de 10000 cta cte. Movimiento m1 de 5000 con `id_cliente_relacionado=cliente`. Pero el usuario aplica solo 3000 vía `pago_aplicado` (los otros 2000 son sobrante para anticipo).

- `aging_cobros` lee `sum(MovimientoCaja.monto)` filtrando por `id_cliente_relacionado` → cuenta 5000 pagado, no 3000 aplicado.
- `dso` directamente no mira pagos en absoluto, solo "venta marcada cta cte vs total ventas".

Resultado: aging dice saldo 5000 (cuando son 7000 reales), DSO da artificialmente bajo, y el aging puede llegar a `pagado_total > facturado_total` si hubo sobrepago/anticipo (info["total"] negativo, después se filtra con `if info["total"] <= 0: continue` → desaparece del listado, lo cual es otro bug: cliente con anticipo a favor desaparece del aging).

**Fix:** Aging y DSO deberían usar `saldo_venta(p1)` (de pagos_aplicados) cuando exista al menos una aplicación; si no, fallback al método actual. O al menos clampear: `max(0, info["total"] - pagado)` no resta de buckets si no hay nada.

---

### I5 — Ledger orden mismo día: tiebreaker es solo (fecha, factura/pago) — no usa hora
**Archivo:** `backend/app/kpis/cuentas_corrientes.py:169` y `proveedores.py:107`

**Análisis:** El sort hace `(e["fecha"][:10], 0 if venta/factura else 1)`. Esto truca el orden a "ventas/facturas siempre ANTES que pagos del mismo día", lo cual es la convención contable habitual. Hay test que lo cubre (`test_ledger_orden_mismo_dia_venta_antes_que_pago`). Bien.

**Pero:** el saldo running se calcula sobre ese orden. Si en realidad el cliente PAGÓ en la mañana y la venta nueva fue en la tarde, el ledger lo muestra como "primero compré, después pagué" — saldo intermedio incorrecto, aunque el final coincide. No es un bug de corrupción, es un display issue. Tests no validan que dos ventas el mismo día se ordenen entre sí (resultado actual: orden indeterminado dentro del mismo (fecha, tipo)).

**Fix sugerido:** Para `cuentas_corrientes`, usar `(fecha[:10], 0 if venta else 1, fecha)` para que dos ventas del mismo día se ordenen por hora completa (`Venta.fecha` es DateTime). Para `proveedores`, las facturas son `Date`, no hay hora — agregar tiebreak por `id` para que sea estable.

---

### I6 — `proveedores_router.eliminar_factura` permite borrar factura sin chequear pagos parciales
**Archivo:** `backend/app/routers/proveedores_router.py:143-160`

**Análisis:** Bloquea el delete si hay movimientos vinculados (línea 152: `n_pagos > 0` → 409). Bueno. Pero la `cascade="all, delete-orphan"` está en `Proveedor.facturas`. Si el usuario elimina el PROVEEDOR (no implementado, OK), las facturas se borran en cascada y los movimientos vinculados quedan con FK rota (NULL? no, `id_factura_proveedor` no tiene `ondelete`). SQLAlchemy no impone ON DELETE a nivel DB; el ORM solo borra `Proveedor.facturas`, no toca los movimientos. Si SQLite tuviera FK enforcement, fallaría. **No hay endpoint DELETE de proveedor**, así que es teórico — pero `cascade="all, delete-orphan"` deja la puerta abierta a una catástrofe futura.

**Fix:** Cambiar a `cascade="save-update, merge"` (sin delete-orphan) en `proveedor.py:21`, o agregar `ondelete="SET NULL"` en `movimiento_caja.py:50` para que MovimientoCaja sobreviva al delete de la factura.

---

### I7 — `import_router` no protege con auth + cap puede superarse vía streaming chunked sin Content-Length
**Archivo:** `backend/app/routers/import_router.py:27-35`

**Análisis técnico:** `file.size` viene de `Content-Length` del MULTIPART part. Para uploads chunked sin length declarado, `file.size` es `None` (el `is not None` lo cubre). El safety net `len(contenido) > MAX_UPLOAD_BYTES` después del `await file.read()` es lo que protege en ese caso. **Pero `file.read()` ya leyó todo a memoria** — un atacante que stream un archivo de 1GB ya OOMeó el proceso ANTES de llegar al chequeo. El cap no protege contra eso.

**Fix:** Leer en chunks con `file.read(8192)` en bucle y abortar al pasar el cap. Algo como:
```python
contenido = bytearray()
while chunk := await file.read(64 * 1024):
    contenido.extend(chunk)
    if len(contenido) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Archivo demasiado grande.")
```
Para single-user trusted local, importa poco; para LAN o deploy es real.

---

## Minor

### m1 — `_safe_csv_field` no protege contra newlines embebidas
**Archivo:** `backend/app/routers/cuentas_corrientes_router.py:31-39`

Maneja prefijos peligrosos (`= + - @ \t \r`) pero no `\n`. Un detalle de venta con `"foo\n=cmd|calc"` se escribe en CSV como dos líneas, la segunda interpretada por Excel como fórmula. Para Excel-AR concretamente el riesgo es bajo porque las celdas multilínea van entre comillas (csv.writer las cita), pero confirmá que csv.writer está siempre quoteando los campos con `\n`. Si querés ser estricto, sanitizar `\n` también.

### m2 — `proveedores_con_saldo` no soporta proveedores sin facturas en aging/vencimientos
Solo lo lista en `proveedores_con_saldo` con saldo 0 — ok. Pero el `out.sort(key=lambda r: r["saldo"], reverse=True)` pone proveedores con saldo 0 al final mezclados con proveedores con saldo NEGATIVO (anticipos). Debería separar visualmente o filtrar inactivos. No es bug, es UX.

### m3 — `cierres_router.cerrar` no valida que `data.fecha <= today`
**Archivo:** `backend/app/routers/cierres_router.py:51-82`

Permite crear un cierre con fecha futura (ej. 2099-01-01), bloqueando todo movimiento de la caja para siempre. Solo se puede deshacer con DELETE. Worth a guard:
```python
if data.fecha > date.today():
    raise HTTPException(400, "No se puede cerrar caja con fecha futura.")
```

### m4 — `ledger_proveedor` usa `m.caja_origen` como "caja" del pago, pero eventos de factura no tienen caja
Mostrar como columna en UI puede dejar gaps confusos. Cosmético.

### m5 — `dso` redondea a 1 decimal con `round(float(...), 1)` perdiendo precisión Decimal
**Archivo:** `backend/app/kpis/cuentas_corrientes.py:335`

Si `dso_val` es Decimal exacto, convertirlo a float y redondear introduce el sesgo binario habitual. Para un KPI que se muestra en pantalla redondeado a 1 decimal el impacto es nulo, pero por consistencia con el resto del módulo (que usa Decimal), `round(dso_val, 1)` directo funciona y es más limpio.

---

## Top 5 a arreglar

1. **C1**: aplicar `requiere_api_key` a los routers (o globalmente). Sin esto el módulo de auth es teatro. **Fix de 5 líneas en `main.py`** + 1 test e2e.
2. **C2**: validar `caja_origen is None` en `aplicar_pago` y `disponible_movimiento` para no aceptar transferencias como cobranzas. **Fix de 2 líneas + 1 test**.
3. **C3**: definir y documentar la regla de coexistencia `pago_aplicado` ↔ `id_cliente_relacionado`. Mínimo: comentario en `pago_aplicado.py` + test que cubra el escenario de divergencia + regla en aging/dso para preferir pagos aplicados.
4. **I2**: agregar `caja_destino.is_(None)` en los 3 queries de proveedores para no contar transferencias como pagos. **Fix de 3 líneas + 1 test**.
5. **I7**: leer `file` en chunks en `import_router` o usar Starlette `Request.stream()` para abortar antes de OOMear. Solo crítico cuando el sistema se exponga.
