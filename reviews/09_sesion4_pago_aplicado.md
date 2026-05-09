# Review — Sesión 4 pago_aplicado

Alcance: tabla `pagos_aplicados`, helpers en `app/kpis/pagos_aplicados.py`, router `pagos_aplicados_router.py`, tests `test_pagos_aplicados.py` y migración `d2cde3f7eaa0_pagos_aplicados.py`. Se excluyen ítems ya tratados en reviews previas (C2 transferencias, C3 double-counting con `id_cliente_relacionado`).

## Resumen ejecutivo

**3 críticos / 4 importantes / 5 menores** específicos a Sesión 4.

Los críticos son: (1) la migración Alembic está vacía — la tabla NO se crea en deploy real; (2) el endpoint `DELETE` no tiene autorización ni filtro por cliente; (3) la combinación `UNIQUE(id_venta, id_movimiento)` + `re-aplicar suma al existente` introduce una race condition que permite sobrepasar el monto del movimiento bajo concurrencia.

El refactor está bien pensado a nivel de modelo (aditivo, FK correctas, índices, comentarios honestos sobre la deuda con `id_cliente_relacionado`), pero la capa de validación, persistencia y endpoints tienen agujeros que conviene cerrar antes de exponerlo a producción.

## Strengths

- **Modelo bien diseñado** (`pago_aplicado.py:28-42`): índices en ambas FK, `UniqueConstraint` nombrado, `Numeric(14,2)` para monto, `created_at` para auditoría. La docstring del módulo (`pago_aplicado.py:1-11`) es honesta sobre la convivencia con `id_cliente_relacionado`.
- **Separación limpia kpi/router**: la lógica vive en `app/kpis/pagos_aplicados.py` y el router solo orquesta y traduce errores a HTTP. Buen patrón.
- **`disponible_movimiento` valida que sea ingreso puro** (`pagos_aplicados.py:29`): `caja_destino is not None and caja_origen is None`. Coherente con el fix de C2 y aplicado de forma consistente también en `aplicar_pago` (`pagos_aplicados.py:50`).
- **Test `test_re_aplicar_suma_al_existente`** (`test_pagos_aplicados.py:68-76`) verifica explícitamente que el `UniqueConstraint` no se rompe y la fila se actualiza en lugar de duplicarse. Excelente intención de cobertura.
- **`aplicar_pago` con `monto=None`** (`pagos_aplicados.py:65`) usa `min(saldo, disp)` — UX agradable para el caso común de "aplicá lo que cubra".
- **Conversión `Decimal(str(...))` consistente** evita los típicos bugs de `Decimal(float)` con representación binaria. Buena disciplina (`pagos_aplicados.py:22, 34, 65, 77, 78`).
- **Invalidación de cache de alertas** (`pagos_aplicados_router.py:23, 34`) en POST y DELETE — recordá hacerlo, fácil de olvidar.

## Critical

### C1. La migración Alembic está vacía — la tabla NO se crea en producción

`alembic/versions/d2cde3f7eaa0_pagos_aplicados.py:21-32`: tanto `upgrade()` como `downgrade()` contienen únicamente `pass` y el comentario autogenerado "please adjust!". El archivo fue creado con `alembic revision` pero nunca se llenó con `op.create_table(...)`.

Los tests pasan porque `conftest.py:14` hace `Base.metadata.create_all(bind=e)` que crea la tabla por reflexión de los modelos, no por la migración. En cuanto se haga `alembic upgrade head` en un ambiente real, la tabla `pagos_aplicados` no existirá, los endpoints van a fallar con `OperationalError: no such table`.

**Fix**: poblar `upgrade()` con `op.create_table('pagos_aplicados', sa.Column('id', sa.Integer(), nullable=False, primary_key=True), sa.Column('id_venta', sa.String(), sa.ForeignKey('ventas.id_pedido'), nullable=False), sa.Column('id_movimiento', sa.Integer(), sa.ForeignKey('movimientos_caja.id'), nullable=False), sa.Column('monto', sa.Numeric(14,2), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=True), sa.UniqueConstraint('id_venta','id_movimiento', name='uq_pago_aplicado'))` y los `op.create_index` correspondientes; en `downgrade()` el `op.drop_table` simétrico.

### C2. `DELETE /api/pagos-aplicados/{id}` sin autenticación ni autorización

`pagos_aplicados_router.py:33-40`: `desaplicar` recibe un `id_pago_aplicado` entero y lo borra sin validar:
- Quién es el usuario que llama (no hay `Depends(current_user)` ni similar).
- Si ese pago aplicado pertenece al cliente/tenant del usuario.
- Si la venta o el movimiento siguen vigentes (¿borrar aplicaciones de un período cerrado?).

`kpi_pa.desaplicar_pago` (`pagos_aplicados.py:91-96`) tampoco hace controles. Cualquiera con conocimiento del esquema puede iterar IDs y reventar la conciliación con `for i in range(1,1000): DELETE /api/pagos-aplicados/i`.

Esto encaja con la pregunta del prompt ("¿alguien con ID podría borrar aplicaciones de cualquier cliente?"): **sí, hoy mismo**.

**Fix**: agregar dependencia de auth, y en `desaplicar_pago` validar (a) que la venta pertenezca al cliente del usuario, (b) opcionalmente, que la fecha del movimiento no esté dentro de un período cerrado.

### C3. Race condition en `aplicar_pago` con re-aplicación / movimientos compartidos

`pagos_aplicados.py:57-88`: el flujo es leer-validar-escribir SIN lock de fila ni constraint defensivo a nivel DB:

1. `disp = disponible_movimiento(...)` — SELECT.
2. Validación `monto_a_aplicar > disp`.
3. Buscar `existente`, sumar a `monto`, `commit`.

Dos requests concurrentes pidiendo aplicar todo el saldo del mismo movimiento (a ventas distintas, o a la misma venta vía re-aplicación) pueden ambos pasar el chequeo de `disp` con la misma foto (3000 disponibles) y ambos commitear (resultado: 6000 aplicados sobre 3000). Para ventas distintas el `UniqueConstraint(id_venta,id_movimiento)` no las protege porque las claves difieren. Para la misma venta + mismo movimiento concurrente, dos `INSERT` chocan con el unique (gana uno, el otro lanza `IntegrityError` 500), pero dos `UPDATE` al mismo `existente` pueden serializarse y sumar de más.

Adicionalmente: la respuesta a la pregunta del prompt sobre "re-aplicar OTROS $5000 cuando disponible es $1500" — la lógica está bien EN UN SOLO HILO porque (a) `disponible_movimiento` resta lo ya aplicado, así que `disp == 1500`, (b) la guard `monto_a_aplicar > disp` falla. **No hay bug en serie**, sí hay bug en concurrencia.

**Fix**:
- Agregar `CHECK (monto > 0)` y, si SQLite/Postgres lo permite limpio, un trigger o constraint diferida que valide la suma. Lo simple: `with_for_update()` sobre el `MovimientoCaja` al inicio de `aplicar_pago` para serializar accesos al mismo movimiento.
- Capturar `IntegrityError` en el endpoint y devolver 409.

## Important

### I1. Falta `CHECK (monto > 0)` y validación de signo en helper

`pago_aplicado.py:41` declara `monto = Column(Numeric(14, 2), nullable=False)` sin CHECK. `aplicar_pago` (`pagos_aplicados.py:66`) sí valida `monto_a_aplicar <= 0`, pero `desaplicar_pago` no impide que un INSERT directo en DB (o un futuro endpoint admin) inserte negativos. Conviene defensa en profundidad: agregar `sa.CheckConstraint('monto > 0', name='ck_pago_aplicado_monto_pos')` en `__table_args__`.

El test `test_aplicar_pago(monto=Decimal("-100"))` no existe — dado que la validación está en `aplicar_pago`, hace falta confirmarla.

### I2. Sin `ON DELETE CASCADE` → riesgo de PagoAplicado huérfano

`pago_aplicado.py:35-40`: las FK a `ventas.id_pedido` y `movimientos_caja.id` no especifican `ondelete`. Si se ejecuta un `DELETE FROM ventas WHERE id_pedido=X` (re-importación, limpieza, fix manual) y la DB no tiene FK enforcement (SQLite por default no las aplica), quedan filas en `pagos_aplicados` apuntando a ventas o movimientos inexistentes — y `aplicaciones_de_venta`/`aplicaciones_de_movimiento` hacen INNER JOIN, así que esos pagos huérfanos *desaparecen* de la UI pero siguen restando saldo en `saldo_venta`/`disponible_movimiento`, que sí los cuenta.

Recomendado: `ForeignKey("ventas.id_pedido", ondelete="CASCADE")` y lo mismo en `id_movimiento`. Y declararlo también en la migración.

### I3. `saldo_venta` y `disponible_movimiento` devuelven `Decimal(0)` silenciosamente cuando la entidad no existe

`pagos_aplicados.py:17-18` y `27-30`: si la venta o el movimiento no existen, retorna `Decimal(0)`. Esto se propaga a los endpoints `GET /venta/{id_pedido}` y `GET /movimiento/{id_movimiento}` (`pagos_aplicados_router.py:43-56`) que devuelven `200 OK` con `{"saldo_venta": 0.0, "aplicaciones": []}`.

Es UX confusa: el front no distingue "venta cobrada" de "venta inexistente". Y el caso de `disponible_movimiento` es peor: también devuelve 0 si el movimiento existe pero es una transferencia o un egreso, mezclando "no aplicable" con "no existe" con "ya aplicado todo".

Mejor: el helper retorna `Decimal | None` o lanza, y el endpoint distingue 404 (no existe) de 200 con `disponible=0`. Como mínimo, agregar logs `WARN` cuando se llama con id inexistente — hoy es silencioso.

### I4. Inconsistencia: `monto` en API es `float`, internamente `Decimal`

`pagos_aplicados_router.py:19` define `monto: float | None`. Para entradas de usuario está OK (Pydantic lo convierte), pero el response devuelve `float(p.monto)` (`pagos_aplicados_router.py:30`, `pagos_aplicados.py:112-113, 131`). Cuando el front re-envíe ese float para una nueva aplicación, va a haber casos de borde por representación binaria (`5.1 - 3.0 == 2.0999999999999996` etc.). Mejor: tipar como `Decimal` en el modelo Pydantic con `model_config = ConfigDict(json_encoders={Decimal: str})` y devolver strings. Si el front no lo soporta, al menos `round(float(p.monto), 2)`.

## Minor

### M1. UNIQUE(id_venta, id_movimiento) — discusión

Pregunta del prompt: ¿hay caso donde el usuario querría 2 aplicaciones de la misma combinación venta+movimiento? Respuesta: no, no se me ocurre uno legítimo. Si quiere "registrar dos aplicaciones por separado", es ruido — la representación correcta es UNA fila con la suma. El constraint está bien.

Lo que sí complica: hace que la lógica de `aplicar_pago` tenga que manejar el upsert manualmente (`pagos_aplicados.py:71-82`). Si en algún momento se quiere preservar historial de aplicaciones individuales (ej: "el 15/4 aplicó 1000, el 20/4 aplicó otros 500"), va a haber que romper este UNIQUE y agregar un `aplicado_at` o similar. Por ahora, OK.

### M2. `id=1` hardcodeado en tests

`test_pagos_aplicados.py:35` fija `id=1` en `MovimientoCaja(...)`. Funciona porque cada test arranca con `:memory:` limpio (ver `conftest.py:11-15`), así que no colisiona ENTRE tests. Pero dentro de un test, si agregás un segundo movimiento sin `id` explícito, SQLite asigna autoincrement y la lectura `id=1` queda válida — todo bien por accidente, hasta que alguien refactoree. Mejor: capturar `m.id` después del commit en una helper `_setup`.

### M3. `kpi_pa.desaplicar_pago` no devuelve nada útil

`pagos_aplicados.py:91-96` retorna `None` y el endpoint responde `{"ok": True}`. Sería más útil devolver el `id_venta`/`id_movimiento` afectados para que el front pueda invalidar las queries correctas sin un round-trip extra.

### M4. `aplicaciones_de_movimiento` hace INNER JOIN sobre Venta

`pagos_aplicados.py:121-123`: si la venta fue borrada (ver I2), las aplicaciones a esa venta no aparecen, pero el `disponible` sí descuenta su monto. Inconsistencia silenciosa hasta que se aplique CASCADE o se cambie a LEFT JOIN.

### M5. Nombres mezclados ES/EN y typing inconsistente

`aplicaciones_de_venta` retorna `list[dict[str, Any]]` (`pagos_aplicados.py:99`) — sin Pydantic schema. Para un módulo nuevo conviene definir `PagoAplicadoOut(BaseModel)` y tiparlo en el router para tener docs OpenAPI decentes. Hoy `/docs` muestra `dict` y nada más.

## Tests faltantes

1. **Monto negativo o cero**: `aplicar_pago(db, "p1", 1, Decimal("-100"))` y `Decimal("0")` — esperado: `ValueError`.
2. **Venta inexistente**: `aplicar_pago(db, "no-existe", 1, Decimal("100"))` — esperado: `ValueError`. Hay rama (`pagos_aplicados.py:45-46`) pero no hay test.
3. **Movimiento inexistente**: idem (`pagos_aplicados.py:48-49`).
4. **Aplicar a venta ya saldada**: aplicá 10000 a "p1", después intentá aplicar otros 100 — esperado: "ya está totalmente cobrada".
5. **Re-aplicar excediendo el movimiento**: aplicar 1500 + intento de 2000 cuando disp era 3000 → testea la rama `nuevo_total > m.monto` (`pagos_aplicados.py:78-79`).
6. **Aplicar sobre transferencia**: crear movimiento con `caja_origen` Y `caja_destino`, intentar `aplicar_pago` → `ValueError` (cubre `pagos_aplicados.py:50-55` y refuerza el fix C2).
7. **Aplicar sobre egreso puro**: solo `caja_origen` → `ValueError`.
8. **`disponible_movimiento` sobre id inexistente**: hoy devuelve `Decimal(0)` silencioso. Test que documente el comportamiento (o, mejor, que falle hasta que se decida raisear — ver I3).
9. **`saldo_venta` con múltiples aplicaciones de movimientos distintos**: hoy el único test multi-aplicación es `test_un_movimiento_cubre_dos_ventas` (1 mov → 2 ventas). Falta el dual: 2 movs → 1 venta.
10. **Endpoint `DELETE` con id inexistente**: el helper raisea, el endpoint devuelve 404. Test directo del router.
11. **Race / concurrencia**: difícil de cubrir en SQLite, pero al menos un test que serialize dos `aplicar_pago` en transacciones separadas con commit intercalado sobre el mismo movimiento.

## Recomendaciones para que esta tabla destrabe valor sin romper nada

1. **Llenar la migración Alembic ya** (C1). Sin esto, el feature es ficción en cualquier deploy real.
2. **Cerrar el endpoint DELETE con auth + scoping por cliente** (C2). Es trivial agregar y el costo de exponerlo abierto es alto (corrupción silenciosa de conciliación).
3. **Agregar `CHECK (monto > 0)` y `ON DELETE CASCADE`** (I1, I2) en la próxima migración correctiva. Defensa en profundidad: la app valida, la DB también.
4. **Pydantic schema de salida** (`PagoAplicadoOut`) para que el front no consuma `dict[str,Any]` sin contrato y las docs OpenAPI sean utilizables.
5. **Decidir contrato de errores en getters**: o `404` cuando la venta/movimiento no existe (I3), o documentar explícitamente que `0` significa "no aplicable o no existe". Hoy es ambiguo.
6. **Agregar serialización para concurrencia** (C3): un `with_for_update()` sobre el `MovimientoCaja` al inicio de `aplicar_pago`. Simple, suficiente para Postgres en producción.
7. **Cubrir las ramas no testeadas listadas arriba** — la mayoría son tests de 3 líneas que evitan regresiones cuando alguien refactoree validaciones.
8. **Considerar deprecar gradualmente `id_cliente_relacionado`**: ahora que existe el vínculo explícito, el campo viejo sigue siendo fuente de double-counting potencial (C3 del review previo). Una vez que el flujo de UI use `aplicar_pago`, se puede empezar a ignorar `id_cliente_relacionado` en los KPIs (ya marcado como deuda en `pago_aplicado.py:9-10`).
9. **Evaluar mover el "upsert manual"** (`pagos_aplicados.py:71-82`) a un INSERT...ON CONFLICT a nivel SQL — más atómico y libra de la race condition C3 sin necesidad de lock explícito (Postgres lo soporta limpio; SQLite también desde 3.24).
