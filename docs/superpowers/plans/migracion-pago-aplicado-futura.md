# Plan B (futuro): migración masiva `id_cliente_relacionado` → `pago_aplicado`

> **Estado**: NO ejecutado. Esta es la documentación del plan que se aplicará
> cuando se cumplan los disparadores definidos abajo. Hoy (2026-05) se aplicó
> la **Opción C — UI-driven freeze**: la UI de creación/edición de movimientos
> esconde el campo legacy bajo `<details>` y dirige al flujo nuevo
> (`Cuentas Corrientes → Aplicar a venta`). El backend sigue aceptando
> `id_cliente_relacionado` para compatibilidad con importers históricos.

## Contexto

Hay dos formas de vincular un movimiento de cobranza a deuda del cliente:

1. **Legacy `MovimientoCaja.id_cliente_relacionado`**: aging hace FIFO clásico
   contra las ventas pendientes del cliente.
2. **Nuevo `pago_aplicado`** (tabla separada): vinculación granular
   movimiento↔venta específica con monto.

`aging_cobros` respeta `pago_aplicado` como **override** cuando existe; sino
cae al FIFO de `id_cliente_relacionado`. Hay un delta explícito en el aging
para evitar double-count (`aplicado_cliente_nivel`). Ese delta es deuda
latente que conviene eliminar eventualmente.

## Decisión y rationale (jurado adversarial 2026-05)

- **Pragmático** votó C (UI-driven freeze): hoy no hay dolor real, ~250 movs.
  Migrar con FIFO sintético tiene riesgo de mover plata sin que nadie note.
- **Conservador** votó B (migración masiva con disciplina): el delta corrector
  es deuda latente. 250 movs es el momento ideal — el costo crece linealmente.

**Síntesis aplicada**: C ahora + B planeada documentada.

## Disparadores para ejecutar B

Cualquiera de estos:
- **Migración a Postgres** (planeada en 1-2 años): aprovechar el cambio de stack
  para limpiar el modelo en el mismo movimiento.
- **>500 movimientos legacy** sin `pago_aplicado`: cuando el sistema crezca
  significativamente, la deuda del delta corrector pesa más.
- **Bug en aging atribuido al delta corrector**: si alguien tropieza con un
  caso donde el cliente-nivel + venta-nivel dan resultados raros, no patchear
  — migrar.
- **Nueva feature de aging que requiera consistencia**: si hay que agregar
  reportes contables con auditoría línea-por-línea, el FIFO implícito no sirve.

## Plan de migración (B con disciplina)

### Pre-migración

1. **Snapshot de DB**:
   ```bash
   cp kpi.db kpi.db.pre_migration_$(date +%Y%m%d)
   sqlite3 kpi.db .dump > kpi.db.pre_migration_$(date +%Y%m%d).sql
   ```
2. **Versionar el script y hash del DB de partida**:
   ```bash
   sha256sum kpi.db > pre_migration_hash.txt
   git tag pre-migracion-pago-aplicado
   ```
3. **Marcar las filas migradas**: agregar columna `origen` a `pago_aplicado`:
   ```sql
   ALTER TABLE pagos_aplicados ADD COLUMN origen TEXT
       DEFAULT 'manual' CHECK (origen IN ('manual', 'migracion_fifo'));
   ```
   Esto permite revertir selectivamente:
   `DELETE FROM pagos_aplicados WHERE origen = 'migracion_fifo'`.

### Script de migración

`backend/app/scripts/migrar_pago_aplicado.py`:

```python
"""Migración FIFO: id_cliente_relacionado → pago_aplicado.

Idempotente: si la fila ya existe con origen='migracion_fifo', no la
duplica. NO toca id_cliente_relacionado (no borra el campo legacy).
"""
def migrar_movimiento(db, mov):
    # 1. Si ya tiene pago_aplicado, saltear (cobertura granular ya hecha).
    ya = db.query(PagoAplicado).filter(PagoAplicado.id_movimiento == mov.id).first()
    if ya is not None:
        return "skipped_ya_aplicado"

    # 2. Buscar ventas pendientes del cliente al momento del pago.
    ventas = db.query(Venta).filter(
        Venta.id_cliente == mov.id_cliente_relacionado,
        Venta.fecha <= mov.fecha,  # solo ventas previas al pago
    ).order_by(Venta.fecha).all()

    # 3. FIFO: imputar el monto a la deuda más vieja primero.
    pendiente = Decimal(str(mov.monto))
    aplicaciones = []
    for v in ventas:
        saldo_v = saldo_de_venta_al(db, v, mov.fecha)  # neto de pagos previos
        if saldo_v <= 0:
            continue
        a_aplicar = min(pendiente, saldo_v)
        aplicaciones.append((v.id_pedido, a_aplicar))
        pendiente -= a_aplicar
        if pendiente <= 0:
            break

    # 4. Caso ambiguo: pago > deuda total. NO inventar.
    if pendiente > 0:
        crear_caso_revisar(db, mov, motivo="cobro_excede_deuda_FIFO")
        return "ambiguo_caso_revisar"

    # 5. Persistir aplicaciones con origen='migracion_fifo'.
    with db.begin_nested():  # savepoint por movimiento
        for id_pedido, monto in aplicaciones:
            db.add(PagoAplicado(
                id_movimiento=mov.id,
                id_venta=id_pedido,
                monto=monto,
                origen="migracion_fifo",
            ))
    return "ok"
```

### Casos ambiguos (NO inventar)

Van todos a "Casos a revisar" para que la dueña los resuelva manualmente:

- Cobro **>** deuda total del cliente al momento del pago (anticipos/saldos a favor).
- Cliente sin ventas previas al movimiento (cobranza sin deuda registrada).
- Cliente borrado/inactivo (`id_cliente` no encontrado en `clientes`).
- Movimiento con saldo restante después del FIFO (significa que la lógica de
  cobertura cliente-nivel sumaba más que las ventas — bug de datos).

### Dual-read de validación (2 semanas)

> **Nota sobre redistribución intra-bucket**: el script de migración hace
> FIFO por `Venta.fecha` (la deuda más vieja se cobra primero). El aging
> actual (`aging_cobros`) imputa por **buckets**: primero `bucket_90_mas`,
> después `bucket_61_90`, etc. Para deudas dentro del mismo bucket el orden
> entre sí no está garantizado. Resultado: el dual-read puede mostrar
> deltas a nivel `id_pedido` aunque los **buckets totales por cliente**
> sean iguales. El criterio de "0 deltas" se aplica al nivel bucket, no
> al nivel venta individual. Si los buckets coinciden con tolerancia
> $0.01, la migración se considera consistente.

Antes de deprecar el FIFO en `aging_cobros`, modificar la función para que
**calcule por ambas vías** y loggee diferencias:

```python
def aging_cobros(db):
    nuevo = aging_cobros_solo_pago_aplicado(db)
    viejo = aging_cobros_con_fifo_legacy(db)
    deltas = comparar(nuevo, viejo)
    if deltas:
        logger.warning("AGING_DELTA: %s", deltas)
    return viejo  # mientras tanto, devolver el viejo
```

Después de **2 semanas con 0 deltas**, recién entonces:
1. Cambiar `aging_cobros` para devolver `nuevo`.
2. Borrar el código FIFO legacy y el delta corrector.
3. Dejar `id_cliente_relacionado` como columna legacy (no borrar — los importers la usan).

### Rollback

Si en cualquier momento las cosas no cuadran:

```bash
# Opción 1: revertir solo la migración (deja el resto intacto)
python -m app.scripts.revertir_migracion_pago_aplicado
# Equivale a: DELETE FROM pagos_aplicados WHERE origen = 'migracion_fifo';

# Opción 2: rollback total al snapshot pre-migración
mv kpi.db kpi.db.post_migration_failed_$(date +%Y%m%d)
cp kpi.db.pre_migration_<fecha> kpi.db
```

## Tests requeridos antes de ejecutar B

- `test_migracion_pago_aplicado_fifo_basico`: 1 cliente con 3 ventas viejas y 1 cobro
  del monto exacto → 3 aplicaciones que cubren las 3 ventas.
- `test_migracion_pago_aplicado_idempotente`: correr el script 2 veces no duplica filas.
- `test_migracion_pago_aplicado_caso_ambiguo`: cobro > deuda → caso a revisar, sin
  filas en `pago_aplicado`.
- `test_migracion_aging_dual_read_zero_delta`: dataset realista, ambas paths dan
  números iguales con tolerancia $0.01.
- `test_migracion_revertir_borra_solo_migracion_fifo`: revertir no toca aplicaciones
  manuales.

## Métricas de éxito

- 100% de movimientos con `id_cliente_relacionado` quedan en uno de:
  (a) migrados a `pago_aplicado` con `origen='migracion_fifo'`,
  (b) en "Casos a revisar".
- 0 deltas en aging después de 2 semanas de dual-read.
- Tests de aging pasan tanto contra el path nuevo como el viejo.
