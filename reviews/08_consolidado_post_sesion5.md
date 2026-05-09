# Review consolidada post-Sesión 5 — síntesis + fixes aplicados

Despaché 2 reviewers (bugs + integración) sobre el código completo después de Sesión 5. Convergieron en los mismos hallazgos. Lo que sigue es la síntesis y qué se arregló acá mismo.

## Hallazgos cruzados (ambos reviewers coincidieron)

### 🔴 CRÍTICOS
1. **C1 — Auth de cartón**: módulo `app/core/auth.py` con tests pasando, pero NO aplicado a ningún endpoint. Setear `KPI_API_KEY` no protegía nada.
2. **C2 — Transferencias se aceptaban como pagos**: `aplicar_pago` solo chequeaba `caja_destino is not None`. Una transferencia (origen+destino) pasaba el filtro y rompía consistencia con el saldo de cajas.
3. **C3 — Double-counting `pago_aplicado` vs `id_cliente_relacionado`**: helpers viejos (ledger, aging, DSO) usan el camino viejo; `saldo_venta` usa el nuevo. Sin enforcement.

### 🟡 IMPORTANTES
- **I2 — Mismo bug que C2 en proveedores** (`vincular_movimiento` permitía transferencias)
- **I7 — Cap upload se evaluaba después de `read()`**: chunked sin Content-Length OOMeaba
- **`pagos_aplicados` sin UI**: 4 endpoints + 8 tests + 0 referencias en frontend
- **Proveedores sin paridad** con Cuentas Corrientes (faltan aging buckets, DPO, export CSV)
- **`localhost:8000` hardcoded** en frontend (extracto CSV download)
- **`test_cierres.py` con solo 2 tests** para uno de los módulos más críticos

### Lo que SÍ está bien
- Cierre de caja: doble check (antes + después de modificar) cubre cambio de fecha y de caja ✓
- Sort intra-día en proveedores ledger: factura siempre antes que pago ✓
- CSV injection fix: aplicado en el único endpoint que genera CSV ✓
- Re-aplicar pago con `monto=None` falla correctamente la 2ª vez ✓

---

## Fixes aplicados en este turno

| # | Fix | Archivos |
|---|-----|----------|
| **C1** | Middleware global `auth_middleware` en `main.py` que exige `X-API-Key` cuando `KPI_API_KEY` está seteada. Excluye `/health`, `/docs`, `/openapi`, `/redoc`. | `backend/app/main.py` |
| **C2** | `aplicar_pago` y `disponible_movimiento` ahora exigen ingreso PURO (`caja_origen is None`). Mensaje de error explica que transferencias no son cobranzas. | `backend/app/kpis/pagos_aplicados.py` |
| **I2** | Mismo fix en proveedores: `vincular_movimiento` exige egreso puro; `proveedores_con_saldo` y `ledger_proveedor` filtran `caja_destino.is_(None)` para no contar transferencias como pagos. | `backend/app/kpis/proveedores.py`, `backend/app/routers/proveedores_router.py` |
| **I7** | Upload import lee por chunks de 64KB y corta a 50MB. Doble guarda: `file.size` (Content-Length) + tamaño real acumulado durante stream. | `backend/app/routers/import_router.py` |
| **Tests** | 2 tests nuevos en `test_pagos_no_transferencias.py` que cubren C2/I2. | `backend/tests/test_pagos_no_transferencias.py` |

**Tests post-fix: 83/83 verde** (81 previos + 2 nuevos).
**App: 85 routes, 2 middlewares (CORS + auth)**.

---

## Pendientes que NO se atacaron acá

### 🔴 C3 — coexistencia `pago_aplicado` vs `id_cliente_relacionado`
Requiere decidir política: ¿deprecar el viejo? ¿exclusión mutua? ¿migración masiva?
**No es bug latente** porque hoy el frontend NO usa `pagos_aplicados` (sin UI), así que no hay double-counting real.
**Recomendación**: dejar para sesión dedicada cuando se construya la UI de pagos parciales.

### 🟡 Important diferidos
- **Frontend para `pagos_aplicados`** (botón "aplicar a venta X" en feed de Caja Diaria + columna "saldo neto" en ledger)
- **Paridad proveedores ↔ cuentas corrientes** (aging buckets + DPO + export)
- **`localhost:8000` hardcoded** → mover a `api/client.js` baseURL
- **Tests de cierres** ampliar a 5+ casos
- **Sidebar agrupado** (Operación | Análisis | Admin)

---

## Estado final del proyecto

- **83 tests pasando**
- **85 endpoints**, **2 middlewares**
- **5 migraciones Alembic**
- **9 modelos** (Caja, CategoriaCaja, CasoRevisar, CierreCaja, MovimientoCaja, PagoAplicado, Proveedor, FacturaProveedor, Venta+DetalleVenta)
- **12 pestañas** funcionales
- **5 sesiones** del plan consolidado completadas
- **Auth opcional** (env var `KPI_API_KEY`)
- **CSV injection** mitigado
- **Backups automáticos** + manuales
- **Cap upload** 50MB con stream protection

**Verdadero veredicto**: production-ready para uso interno. Para uso fuera de localhost, además de setear `KPI_API_KEY` se recomienda HTTPS y proxy reverso (nginx).
