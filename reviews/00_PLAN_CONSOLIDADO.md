# Plan consolidado de cambios — Multi-review

Síntesis de 5 reviews paralelas (diseño, seguridad, funcionalidad, bugs, mejoras estratégicas). Las **señales fuertes** (donde múltiples lentes coinciden) están priorizadas primero.

---

## Hallazgo más importante (cruza 3 reviews)

**Cache de alertas no se invalida en 6+ endpoints + helpers `_filtro_fecha` duplicados + flag `es_ingreso_operativo` se apaga al guardar categoría.** Esto significa que la app puede mostrar cobertura % "correcta" un día y al día siguiente cobertura cae 30% sin que cambien los datos — solo porque el usuario tocó una categoría. **Es el riesgo más serio de credibilidad del sistema**.

---

## Sesión 1 — CRÍTICA (datos correctos) ⏱ ~1.5h

Sin esto los números mienten silenciosamente. Todo lo de acá es bug real, no feature.

### Bugs de corrupción silenciosa
1. **`Configuracion.jsx:138-144`** — PUT categorías omite `es_ingreso_operativo` → cada save desde UI lo apaga → conciliación queda mal. **5 minutos de fix**.
2. **`categorias_seed.py:97-107`** — re-seed sobrescribe ediciones manuales en cada restart. Hay que detectar "tocado por usuario" y respetarlo. **15 min**.
3. **`parsing.py parse_monto`** — `"1.5"` se convierte en `15` (aplica thousands a un solo punto). Frontend manda `Number().toString()` que puede generar este formato. **10 min**.
4. **`detalle_ventas.py` dedupe por posición runtime** — re-import con orden distinto duplica todo. Persistir `linea_num` en el modelo. **20 min** + migration Alembic.
5. **`kpis/caja.py _filtro_fecha`** — no extiende `hasta` a fin de día para `Venta.fecha` (DateTime). Las ventas del día tope desaparecen del flujo. **5 min**.
6. **`movimientos_caja.py:120-122`** — `db.rollback()` dentro del loop revierte filas pendientes. **5 min**.
7. **`clientes_con_cuenta`** — agrupa por `(id_cliente, cliente)` → cliente con typo aparece 2 veces y se cuenta ×2. Agrupar solo por id. **5 min**.
8. **`caja_diaria_router.py:179-183`** — re-cómputo de hash en editar puede tirar 500 por colisión. Atrapar IntegrityError. **5 min**.

### Cache invalidation centralizada
- Crear decorator `@invalida_alertas` que envuelva mutaciones. Aplicarlo a: `asignar_movimiento`, `desasignar_movimiento`, `marcar_venta_cta_cte`, `import`, `descartar_caso`, `merge_cajas`, `editar_venta`, `actualizar_categoria`. **30 min**.

### Tests para cada uno
- Test que reproduzca cada bug + asserta el fix. **30 min**.

**Total estimado: 2h.** Después de esto, los números son confiables.

---

## Sesión 2 — UX que importa (productividad diaria) ⏱ ~2h

El usuario va a usarlo todo el día. Estos detalles definen si lo abandona o no.

1. **Reemplazar `alert()` y `confirm()` por componentes propios**:
   - `<ConfirmDialog>` — modal con botones consistentes en lugar del confirm del browser (~8 lugares)
   - `<Toast>` — notificaciones de éxito post-acción (hoy solo el form de movimiento las muestra)
2. **Modal accesible**: cierre con Escape, click-outside, focus-trap básico.
3. **Layout responsive básico**: sidebar colapsable < 900px, tablas con `overflow-x: auto`.
4. **Feedback de carga consistente**: skeleton o overlay en lugar de "datos viejos + spinner mini".
5. **Componentes reutilizables**: `<PageHeader>` y `<FilterBar>` para no duplicar toolbars.
6. **`:focus-visible` global** + tabs semánticos (`role="tablist"`).
7. **Iconos SVG** en lugar de `✏✕` plano.

**Total estimado: 2h.**

---

## Sesión 3 — Funcionalidad para REEMPLAZAR la planilla ⏱ ~3-4h

Hoy la app cubre ~45-55% de lo que hace la planilla. Le faltan 3 bloques estructurales:

### A. Cierre de caja con bloqueo (~1h)
- Modelo: nueva tabla `cierre_caja(fecha, caja, saldo_cierre, usuario, cerrado_at)`
- Endpoint: cerrar caja → calcular saldo final, snapshotearlo, marcar movimientos como "cerrados"
- Movimientos de fecha cerrada: no se pueden editar/borrar sin "abrir cierre"
- UI: botón en Caja Diaria "Cerrar día" + visualización de cierres históricos
- Habilita: arqueos, diferencias entre teórico vs real

### B. Módulo Proveedores + Cuentas a Pagar (~1.5h)
Espejo del módulo de Cuentas Corrientes pero del lado proveedor:
- Modelo: `proveedor`, `factura_proveedor`, `pago_proveedor`
- Pantalla con saldo por proveedor, vencimientos, aging
- Vincular movimientos de egreso a facturas/proveedores
- Habilita: DPO (días promedio pago), priorizar a quién pagar primero

### C. Aging de cobros + DSO + alertas de morosidad (~30 min)
- Aging buckets: 0-30, 31-60, 61-90, 90+ días
- Alerta automática: clientes con saldo > X que pasan a bucket morosidad
- DSO (días promedio cobro)

**Después**: con A, B, C podés calcular **margen operativo real**, **EBITDA aproximado real**, **rentabilidad neta**, **punto de equilibrio**, **liquidez corriente** — todos KPIs del PDF original que hoy faltan.

---

## Sesión 4 — Refactor estructural ⏱ ~2-3h

### A. Tabla `pago_aplicado(venta_id, movimiento_id, monto)` (~1.5h)
**Pendiente del review #1 + #5**. Reemplaza el flat `id_cliente_relacionado` con una tabla puente real.

Beneficios:
- Pagos parciales (cobranza cubre N facturas)
- Sobrepagos (cobranza > venta = anticipo)
- Aging real por venta
- Mata C2 y C3 del review previo de raíz
- Habilita auditoría: "¿qué cobranzas pagaron qué venta?"

### B. Helpers compartidos (~30 min)
- Mover `_filtro_fecha` y `_PERIODOS_FMT` a `app/kpis/_shared.py`
- Reemplazar `func.strftime` con función agnóstica al motor (cuando se migre a Postgres no rompe en 5 lugares)

### C. Pydantic schemas + tipos compartidos (~30 min)
- Llenar `app/schemas/` con response models
- Frontend deja de adivinar shapes (ver `EditarVentaFila.jsx` con `venta.cliente || venta.venta_cliente`)

### D. SQLite PRAGMA foreign_keys=ON (~5 min)
- Hoy borrados directos por SQL pueden dejar huérfanos.

---

## Sesión 5 — Hardening + Polish ⏱ ~1.5h

### Seguridad (si se expone fuera de localhost, hoy NO está listo)
1. **Bindear uvicorn a 127.0.0.1** explícito (1 línea, defense in depth).
2. **Cap 50MB** en upload CSV (`import_router.py:21`).
3. **Auth con API key** estática en env var — 30 líneas con dependency compartida.
4. **CSV injection** en extracto: prefijar fórmulas (`=cmd|...`) con `'` en exports.
5. Sacar path absoluto de `/api/admin/info`.
6. Mover `data/` a `%LOCALAPPDATA%/KPI/` con ACLs.

### Tests faltantes
- Tests de routers con `TestClient` (cero hoy).
- Tests de endpoints destructivos.
- Test de migrations desde clean.

---

## Sesión 6 — Bonus / Largo plazo (opcional)

### Decisiones tecnológicas (cuando crezca)
- **Postgres**: solo cuando haya multi-usuario o queries lentas. Hoy SQLite es óptimo.
- **TypeScript**: sí, pero después de schemas Pydantic (genera tipos automáticos).
- **TanStack Query**: ROI inmediato — elimina los `useEffect → cargar()` manuales en todas las pantallas.
- **react-hook-form + zod**: para reemplazar los `useState × 12` en forms (CajaDiaria, EditarVentaFila).
- **Sacar pandas**: 50MB de dependencia para `df.iterrows()` en imports. Reemplazar con `csv` stdlib.

### Funcionalidad avanzada
- Conciliación bancaria con import de extracto bancario
- IVA + clasificación fijos/variables → desbloquea Rentabilidad neta, Margen operativo, Punto de equilibrio, EBITDA y subdiario IVA
- Stock / inventario
- Liquidación de tarjetas

---

## Resumen ejecutivo

| Sesión | Foco | Tiempo | Resultado |
|--------|------|-------:|-----------|
| 1 | Datos correctos | ~2h | Números confiables |
| 2 | UX productivo | ~2h | Usable todo el día sin frustración |
| 3 | Reemplaza planilla | ~3-4h | Cierre + Proveedores + Aging |
| 4 | Refactor estructural | ~2-3h | Modelo de datos sólido a futuro |
| 5 | Hardening | ~1.5h | Listo para LAN/multi-usuario |
| 6 | Largo plazo | abierto | TypeScript, Postgres, etc. |

**Mi recomendación**: hacer Sesión 1 sí o sí (es deuda técnica real), y después decidir entre Sesión 2 (UX) o Sesión 3 (funcionalidad para reemplazar planilla) según qué te urgue más.

---

## Reviews originales

- `01_diseno.md` — UX/UI
- `02_seguridad.md` — Seguridad
- `03_funcionalidad.md` — Cobertura funcional
- `04_bugs.md` — Bugs detectados
- `05_mejoras.md` — Mejoras estratégicas
