# Review — Mejoras estratégicas

## Resumen ejecutivo

El codebase está en un estado de **MVP maduro** sorprendentemente coherente para haberse construido en una sesión: separación clara back/front, capa de KPIs pura (sin Pydantic mezclado), Alembic ya configurado desde temprano, modelo de cajas como entidad central que paga muy bien. La velocidad de iteración de la próxima vuelta va a depender de **dos movidas estructurales**: (1) introducir la tabla `pago_aplicado(venta_id, movimiento_id, monto)` que ya recomendó el review previo — sin eso, el ledger del cliente sigue siendo *inferido* y no se puede modelar pago parcial, sobrepago ni cobranza que aplica a varias ventas; (2) extraer una capa de schemas Pydantic + tipar la API contractualmente para destrabar tanto TS en el frontend como tests E2E. Todo lo demás es consolidación.

---

## Strengths arquitectónicas

Antes de las críticas, lo que hay que **conservar**:

1. **Separación KPIs / Routers**. `app/kpis/*.py` son funciones puras `(db, params) → dict` sin acoplarse a HTTP. Esto permite que `dashboard.py` reuse `comerciales.resumen()` y `caja.saldos_por_caja()` sin duplicar SQL. Patrón a imitar.
2. **Cajas como entidad con `nombre_normalizado` PK + `nombre_display`** — decisión muy fuerte. Tolera tipeo del usuario y permite el feature de merge de cajas en una sola UPDATE. Replicar para clientes/productos cuando llegue el momento.
3. **`CasoRevisar` como bandeja de entrada**. La política "solo entra al sistema lo válido" + reintento desde UI con misma función importer (`crear_casos=False`) es exactamente el patrón correcto. Reutilización limpia.
4. **Alembic configurado desde el día 1** con migraciones reales (3 ya en `versions/`). Casi nadie hace esto en sesión inicial — paga el resto del proyecto.
5. **Hash de dedupe + `IntegrityError` rollback** (`movimientos_caja.py:112-118`) es robusto: dedupe en memoria + safety net en BD.
6. **Backups automáticos al startup** + listing UI. Pequeño y muy alto leverage para confianza del usuario.
7. **Cache TTL de alertas** (`alertas_router.py`) con invalidación explícita en cada mutación. Solución pragmática y correcta para algo que se polea cada 60s.
8. **Tests con SQLite en memoria + fixtures por test**. Setup mínimo, ejecución rápida.

---

## Mejoras priorizadas

### High leverage (mucho ROI)

#### H1. Tabla `pago_aplicado(venta_id, movimiento_id, monto)` — pendiente del review previo

Es **la** decisión estructural. El modelo actual (`MovimientoCaja.id_cliente_relacionado`) asume implícitamente "1 cobranza = N ventas del cliente, FIFO o sin orden". Imposible:
- Modelar **pago parcial** (cobro $5000 a una venta de $8000).
- Modelar **sobrepago** que queda como crédito.
- Saber **qué venta específica** quedó cancelada vs cuál sigue abierta.
- Hacer extracto **antigüedad de saldos** (aging report).
- Soportar la regla "marcar venta como cancelada cuando esté pagada" sin imputación explícita.

Impacto cascada: el guard de C3 en `cuentas_corrientes_router.py:140` ("hay cobranzas asignadas, no se puede desmarcar") es un parche que existe **porque no hay tabla puente**. Con `pago_aplicado`, simplemente las imputaciones quedan huérfanas y el sistema lo sabe.

Migración: NO romper compatibilidad — al crear la tabla, hacer un seed que para cada `MovimientoCaja` con `id_cliente_relacionado` cree filas `pago_aplicado` aplicando FIFO contra ventas abiertas del cliente. Después borrar la columna en una migración separada.

#### H2. Capa Pydantic schemas + tipado del contrato API

`app/schemas/__init__.py` está **vacío**. Cada router devuelve dicts construidos a mano, lo que significa:
- El frontend adivina la forma de los payloads (e.g. `EditarVentaFila.jsx` accede a `venta.cliente || venta.venta_cliente` porque viene en dos shapes según el origen).
- No hay generación de OpenAPI rica → no se puede generar cliente TypeScript.
- Cambiar un campo en el backend rompe silenciosamente el front.

Pasos:
1. Crear `app/schemas/` con `VentaOut`, `MovimientoOut`, `LedgerEvento`, `KpisResumen`, etc.
2. Reemplazar el `dict` constructor en endpoints por `MovimientoOut.model_validate(m)`.
3. Activar `response_model=` en cada `@router.get`.
4. Generar cliente TS desde `/openapi.json` con `openapi-typescript` u `orval`.

Esto **destraba** la migración a TypeScript del frontend (ver T1).

#### H3. Index compuestos en el modelo

Los queries más calientes (saldos por caja, conciliación) hacen:
- `SUM(monto) FROM movimientos_caja GROUP BY caja_destino WHERE caja_destino IS NOT NULL`
- `SUM(monto_pago1) FROM ventas WHERE caja1 = ? AND fecha BETWEEN ?`

Hoy hay índices simples sobre `fecha` y `tipo_operacion`, pero no compuestos que cubran `(caja_destino, fecha)` ni `(caja1, fecha)`. Con 119k detalles ya está cómodo, pero a 1M filas (1-2 años más de operación) los `GROUP BY` van a empezar a sentirse. Agregar:

```python
__table_args__ = (
    Index("ix_mov_destino_fecha", "caja_destino", "fecha"),
    Index("ix_mov_origen_fecha", "caja_origen", "fecha"),
    Index("ix_venta_caja1_fecha", "caja1", "fecha"),
    Index("ix_venta_caja2_fecha", "caja2", "fecha"),
    Index("ix_detalle_categoria_fecha", "categoria_linea", "fecha"),
)
```

Migración Alembic auto-generada.

#### H4. Eliminar el patrón "10 queries para armar 1 endpoint" (saldos_por_caja, configuracion/cajas, configuracion/categorias)

`saldos_por_caja()` hace 5 queries separadas + JOIN en Python. `configuracion.listar_cajas()` hace 4. Con SQL hoy se hace en 1 query con sub-CTEs. Estos endpoints se pollean cada vez que se entra a Caja diaria → es la pantalla más usada operativamente. Refactor:

```python
# Algo así, 1 query:
SELECT
  c.nombre_display, c.tipo,
  COALESCE((SELECT SUM(monto_pago1) FROM ventas WHERE caja1 = c.nombre_normalizado), 0)
  + COALESCE((SELECT SUM(monto_pago2) FROM ventas WHERE caja2 = c.nombre_normalizado), 0) AS ing_ventas,
  COALESCE((SELECT SUM(monto) FROM movimientos_caja WHERE caja_destino = c.nombre_normalizado), 0) AS ing_mov,
  COALESCE((SELECT SUM(monto) FROM movimientos_caja WHERE caja_origen = c.nombre_normalizado), 0) AS egr_mov
FROM cajas c
ORDER BY (ing_ventas + ing_mov - egr_mov) DESC
```

Mejor aún: vista materializada en SQLite (no existe nativa) o **cache TTL de 30s con invalidación al crear movimiento** (mismo patrón que alertas).

#### H5. Cliente API frontend con factory por dominio + abstracción de fetcher

`api.get(...)` se llama 50+ veces a lo largo de páginas. No hay deduplicación, no hay reintento, no hay loading global, no hay invalidación tras mutación. Todo `useEffect(() => { cargar(); }, [])` a mano.

Solución: **adoptar TanStack Query (React Query) o SWR** y crear un módulo por dominio:

```js
// api/comerciales.js
export const useResumen = (params) => useQuery({
  queryKey: ['comerciales/resumen', params],
  queryFn: () => api.get('/api/kpis/comerciales/resumen', { params }).then(r => r.data),
});
```

Beneficios concretos: cache compartida entre páginas (saldos en Caja Diaria + Direccion no se piden 2 veces), refetch on window focus, mutation invalidation explícita. El polling de alertas se simplifica radicalmente.

#### H6. Modelo `Cliente` y `Producto` como entidades de primer orden

Hoy el cliente es `(id_cliente, cliente)` denormalizado en la tabla `ventas`. Esto causa:
- En `clientes_con_cuenta()` (`cuentas_corrientes.py:87`) hay que hacer `db.query(Venta.cliente).filter(...).limit(1).scalar()` para resolver el nombre.
- En `caja_diaria_router.movimientos_recientes()` (línea 215) lo mismo.
- Si el mismo `id_cliente` aparece con dos nombres distintos en el CSV (typo, espacios), el sistema no lo unifica.
- No se puede agregar metadata por cliente (teléfono, condición fiscal, vendedor habitual, etc.).

Crear:
```
clientes (id PK, nombre, ...metadata) -- PK = id_cliente del sistema externo
productos (id PK, nombre, lista_precios_default, ...)
```
Y ventas/detalle apuntando por FK. Migración: poblar desde MAX(fecha) por cliente.

---

### Medium leverage

#### M1. Eliminar la duplicación `_filtro_fecha` / `_to_float` en cada módulo de KPIs

`comerciales.py:23`, `caja.py:16`, `conciliacion.py` hacen import desde `comerciales._filtro_fecha`. Y `cuentas_corrientes.py` no lo usa para nada porque "es distinto". Crear `app/kpis/_helpers.py` con:
- `filtrar_por_fecha(query, columna, desde, hasta)`
- `decimal_to_float(v)`
- `bucket_periodo(periodo, columna)` (resuelve `dia/semana/mes/anio`, hoy duplicado en 2 lugares)
- `combine_fin_dia(hasta)`

#### M2. `_PERIODOS_FMT` está duplicado entre `comerciales.serie_temporal` y `caja.flujo_caja`

Ambos definen el mismo dict `{"dia": "%Y-%m-%d", ...}`. Y ambos usan `func.strftime` de SQLite — esto **rompe cuando se migre a Postgres** (Postgres usa `to_char` o `date_trunc`). Abstraer en helper que conozca el dialect.

#### M3. Excepciones genéricas en importers

`except Exception as e: _rechazar(...)` (en los 3 importers) atrapa TODO. Si hay un bug en el modelo, queda silenciado en `CasoRevisar` con motivo "excepcion". Mejor: catch específicos (`ValueError`, `IntegrityError`, `InvalidOperation`) y dejar burbujear el resto. Lo que entra a "excepcion" hoy es una mezcla de "fila mala" y "bug nuestro".

#### M4. Reemplazar `print` / `console.error` por logging estructurado

El frontend tiene `console.error` regados (AlertasContext, CuentasCorrientes). El backend tiene un logger pero solo lo usa `main.py`. Para una app financiera, querés:
- Backend: `structlog` o `loguru` con JSON estructurado, log de cada mutación con `user/ts/payload/result`.
- Frontend: si va a producción, integrar Sentry o similar.

#### M5. Dependency injection del config

`DATABASE_URL`, `BACKUPS_DIR`, `CORS_ORIGINS` viven en constantes globales. Pasar a `pydantic-settings`:
```python
class Settings(BaseSettings):
    database_url: str = "sqlite:///data/kpi.db"
    cors_origins: list[str] = ["http://localhost:5173"]
    backup_dir: Path = ...
```
Habilita ambientes (dev/staging/prod) sin tocar código y permite override por env var.

#### M6. Validación en Pydantic, no en handler

`crear_movimiento` en `caja_diaria_router.py:43-46` valida `tipo_operacion.strip()` y "al menos una caja" en el handler. Esa lógica va en validators de `NuevoMovimiento` (Pydantic v2 `@model_validator`). Más declarativo, testeable sin levantar la app.

#### M7. Capas estilo `service`

Hoy los routers tienen lógica de negocio mezclada (e.g. `merge_cajas` en `configuracion.py:158` hace los UPDATE directamente, `crear_movimiento` calcula hash, normaliza, etc). Para que sea testeable sin FastAPI, extraer a `app/services/cajas_service.py`, `app/services/movimientos_service.py`. Los routers quedan finos: parsing del request → llamar service → serializar.

#### M8. Soft-delete + audit trail

Una webapp financiera **no debería borrar nada**. Hoy `DELETE /movimiento/{id}` borra físico, igual `DELETE /backups/{archivo}`. Cambiar a `deleted_at`/`deleted_by` columns + filtros en queries. Y agregar tabla `audit_log(entidad, entidad_id, accion, usuario, payload_antes, payload_despues, ts)` populada por SQLAlchemy events. Cuando entre el primer usuario "real", esto es lo que va a pedir.

#### M9. CORS_ORIGINS hardcoded a localhost

`core/config.py:10`. En el momento que se quiera deployar a un host real (incluso un servidor en LAN), hay que tocar código. Llevarlo a env var con default sano.

---

### Low leverage / opcional

#### L1. `__init__.py` vacíos

Tests pasan, pero falta `app/__init__.py` con `__version__`. Convención.

#### L2. `_crear_casos = crear_casos` como atributo dinámico del dataclass

`importers/ventas.py:36` hace `result._crear_casos = crear_casos`. Anti-pattern: el dataclass `ImportResult` no declara ese campo. Mejor pasar `crear_casos` como argumento separado a `_rechazar()`.

#### L3. `Optional` en relaciones inversas

`Venta.detalle` tiene `cascade="all, delete-orphan"` pero no hay constraint que impida que un detalle quede huérfano cuando se borra una venta vía SQL directo. SQLite no enforce FK por default — habilitar `PRAGMA foreign_keys=ON` en el `connect_args`.

#### L4. Inline styles en React

Cada componente lleva `style={{ ... }}` hardcoded. Funciona, pero a medida que crece duele. Pasar a CSS modules o a una librería liviana (Tailwind, vanilla-extract). Mientras tanto, al menos sacar los colores repetidos (`#94a3b8`, `#1e293b`, `#34d399`...) a CSS custom properties:
```css
:root {
  --text-muted: #94a3b8;
  --panel-bg: #1e293b;
  --color-positive: #34d399;
  ...
}
```

#### L5. `Modal.jsx` usa `position: fixed; inset: 0` con `onClick={onClose}` pero no tiene escape key handler ni focus trap

Funcional, pero accessibility básica falta.

#### L6. `confirm()` y `alert()` nativos

`CajaDiaria.jsx:118`, `CuentasCorrientes.jsx:130`, etc. Bloqueantes y feos. Crear un `<ConfirmDialog>` reutilizable.

#### L7. `useEffect(() => { cargar(); }, [])` sin cleanup

Si el usuario navega rápido, los `setData` corren después de unmount → React warning. Agregar pattern abort controller o usar Query (ver H5).

#### L8. Hash de dedupe SHA-1

`base.py:53`. Para esto está bien (no es seguridad), pero `xxhash` o incluso `hashlib.blake2b(digest_size=16)` son 5x más rápidos. No urgente con 119k filas, sí cuando crezca.

#### L9. `categorias_seed.py` tiene **`"Ingreso"` declarado dos veces** en el dict

Líneas 70 y 76 ambas tienen `"Ingreso"`. La segunda sobrescribe a la primera silenciosamente (Python dict literal semantics). Es accidental — la intención era *hacer ambas operativas*.

#### L10. Tests de KPIs faltan

Solo hay tests de conciliación, cuentas corrientes, parsing, idempotencia, normalización (~44 que dice el prompt). NO hay tests de:
- `comerciales.resumen()` ni `serie_temporal()` ni `cohortes_retencion()`
- `caja.saldos_por_caja()` (¡el cálculo financiero más crítico!)
- `caja.flujo_caja()`
- `alertas.evaluar_alertas()`
- Ningún router (no hay TestClient).

Con 14k ventas reales y un usuario que toma decisiones por estos números, **agregar al menos un test de invariante por KPI** es alto valor. Ej.: "la suma de saldos_por_caja debe igualar la suma de ingresos − egresos del flujo". Si rompe alguna vez, lo querés saber.

---

## Refactors específicos sugeridos

### Top 5

#### 1. Tabla `pago_aplicado` (cubierto en H1)
**Cambia**: agrega tabla puente, reemplaza `MovimientoCaja.id_cliente_relacionado` con esta tabla, reescribe `cuentas_corrientes.ledger_cliente()`.
**Destraba**: pago parcial, sobrepagos, antigüedad de saldos, eliminar el guard 409 de "tiene cobranzas asignadas", reportes por antigüedad, multipagos.

#### 2. Capa schemas + cliente TypeScript generado (cubierto en H2)
**Cambia**: `app/schemas/` con todos los DTOs. `response_model=` en cada endpoint. Workflow `npm run gen-types` que pega `/openapi.json` y genera `frontend/src/api/types.ts`.
**Destraba**: migración completa a TypeScript del frontend, autocomplete real, refactors seguros, deprecación documentada de endpoints.

#### 3. Helpers compartidos en KPIs
**Cambia**: crear `app/kpis/_helpers.py` con `filtrar_fecha`, `bucket_periodo`, `decimal_to_float`. Migrar los 5 módulos de KPIs.
**Destraba**: cuando se cambie a Postgres (`strftime` → `date_trunc`), un solo lugar. Cuando se quiera testear SQL helper, una función pura.

#### 4. Capa de servicios
**Cambia**: `app/services/cajas.py`, `app/services/movimientos.py`, `app/services/ventas.py`. Routers solo orquestan.
**Destraba**: tests sin TestClient, reuso entre CLI y HTTP, lógica de negocio versionable separadamente.

#### 5. React Query + módulos API por dominio
**Cambia**: agregar `@tanstack/react-query`, mover cada `api.get` a `useXxxQuery`/`useXxxMutation`. Provider en `App.jsx`.
**Destraba**: cache automática, refetch on focus, eliminar `cargarTodo()` mano a mano, mutaciones que invalidan queries automáticamente. Reduce el peso de cada `pages/*.jsx` significativamente.

---

## Decisiones tecnológicas a evaluar

### T1. ¿Postgres ahora o esperar?

**Esperar** hasta que (a) haya 2+ usuarios concurrentes editando, (b) se quiera deployar a un servidor compartido, o (c) las queries sean lentas (>500ms en SQLite). Hoy SQLite es ideal: 1 archivo, backup trivial, transacciones serializables sin tuning. El día que se migre, los puntos de fricción serán: `func.strftime` (resolver con M2), `Boolean` defaults, índices a recrear. Con Alembic ya activo, la migración es un `alembic revision` + cambiar `DATABASE_URL`.

### T2. ¿TypeScript en el frontend?

**Sí, pero condicionado a H2 primero**. Migrar JS a TS sin tener un cliente API tipado es trabajo desperdiciado. Orden: (1) schemas Pydantic completos, (2) generar `types.ts`, (3) renombrar `.jsx → .tsx` archivo por archivo. Recharts tiene tipos. React Query tiene tipos. Vite soporta TS sin config extra. El esfuerzo grande es **componentes con muchos props** — `EditarVentaFila` por ejemplo, que hoy hace `venta.cliente || venta.venta_cliente` sin saber qué es.

### T3. ¿Bibliotecas a sumar?

- **TanStack Query** (H5) — ROI inmediato.
- **react-hook-form + zod** — los forms actuales son `useState` × 12. RHF + zod elimina ~40% del código de páginas como `CajaDiaria` o `Configuracion` y valida client-side con el mismo schema.
- **shadcn/ui + Tailwind** — si vas a iterar UI mucho. Si no, mantenete con CSS custom.
- **`structlog`** backend.
- **`pydantic-settings`** (M5).

### T4. ¿Bibliotecas a sacar?

- **pandas** — solo se usa en importers para leer CSV. Es ~50MB de dependencia. `csv` stdlib + `dictreader` hace lo mismo en este caso (no se usa nada de DataFrame realmente — `df.iterrows()` es lo único). Cambio chico, descarga el deploy.
- **axios** vs `fetch` nativo — `fetch` ya alcanza para esta API. Axios pesa ~30KB. Pero si se adopta React Query, axios pierde la mitad de su utilidad de todos modos.

### T5. ¿Auth?

No hay. Para uso single-user local está bien. **El día que se publique a una IP** (incluso LAN), agregar auth básica:
- HTTP Basic + un usuario en `.env` (nivel mínimo).
- O FastAPI Users + JWT si va a haber roles (vendedor vs gerencia).

### T6. ¿Deploy?

Vale la pena tener un `docker-compose.yml` con back + front + volumen para `data/`. Hoy levantar el sistema requiere 2 terminales y conocer venv. Un `docker compose up` baja la fricción para mostrarlo a otros.

---

## Documentación faltante

Para que un colaborador externo pueda entrar:

1. **`docs/MODELO_DOMINIO.md`**: explicar el negocio. ¿Qué es una "caja"? ¿Por qué hay `caja1`/`caja2` en una venta? ¿Qué es `helper_v`? ¿Cuándo `discrepancia_pago` es esperable? ¿Por qué la suma de detalles ≠ total de la venta? Hoy esto vive en `~/.claude/projects/.../project_reglas_negocio.md` (referenciado desde CLAUDE.md) y nadie más lo ve.

2. **`docs/KPIS.md`**: cada KPI con su fórmula exacta. "Margen bruto" = `SUM(detalle.subtotal - detalle.cst) WHERE categoria_linea IN ('mercaderia','bonificacion')`. Hoy hay que leer el código.

3. **`docs/ARQUITECTURA.md`**: diagrama de capas (model → kpi → router → frontend). Convenciones (rutas en español, código en inglés/español mixto, nombres de columnas snake_case).

4. **`docs/ADRs/`**: Architecture Decision Records para las decisiones grandes ya tomadas:
   - "ADR-001: Cajas como entidad central con nombre_normalizado"
   - "ADR-002: Casos a revisar como bandeja de entrada (rechazo amable)"
   - "ADR-003: Idempotencia por hash en movimientos, por id_pedido en ventas"
   - "ADR-004: SQLite para v1, plan de migración a Postgres"
   - (futuro) "ADR-005: tabla pago_aplicado"

5. **`README.md` en `tests/`**: cómo correr un solo test, cómo ver coverage, cómo agregar fixture nueva.

6. **OpenAPI con descripciones**: hoy los endpoints tienen `description=` mínimos en algunos params. Cuando se complete H2, los `response_model` + `description` de cada handler hacen del `/docs` la documentación viva.

7. **Cambio de cero a "tengo dashboard funcionando con mis datos"**: README dice cómo correr dev, pero no documenta el flujo de **importar** los 3 CSV iniciales ni qué configurar en `Configuración` antes de mirar KPIs.

8. **`CLAUDE.md` → `CONTRIBUTING.md`**. La política de "jurado adversarial" es interna a Claude. Para humanos colaboradores hace falta otro documento (cómo agregar un KPI, cómo agregar una página, cómo escribir un test).

---

## Plan de evolución (próximas 2-3 sesiones)

### Sesión 1 — "Datos sólidos" (1 día)

- Implementar tabla `pago_aplicado` con migración + seed FIFO desde el dato actual (H1).
- Reescribir `cuentas_corrientes.ledger_cliente()` y `clientes_con_cuenta()` usando la nueva tabla.
- Eliminar el guard 409 ("tiene cobranzas asignadas").
- Agregar UI mínima para imputar un pago a venta(s) específicas (formulario en `CuentasCorrientes` que muestre las ventas abiertas y permita asignar montos).
- Tests: aging, pago parcial, sobrepago, cobranza multi-venta.

### Sesión 2 — "API contractual + DevEx" (1 día)

- Crear `app/schemas/` completo. Migrar todos los endpoints a `response_model=`.
- Agregar workflow `npm run gen-types` con `openapi-typescript`.
- Adoptar TanStack Query en `frontend/`. Migrar mínimo 3 páginas (Dirección, Caja Diaria, Cuentas Corrientes).
- Crear `app/kpis/_helpers.py` y deduplicar.
- Agregar índices compuestos faltantes (H3) con migración Alembic.

### Sesión 3 — "Testing + cliente como entidad" (1 día)

- Crear modelo `Cliente` (H6). Migración que lo popula desde `ventas.cliente`. Refactor de queries para join.
- Tests de KPIs faltantes: `saldos_por_caja`, `flujo_caja`, `cohortes_retencion`, una invariante de "saldo agregado = ingresos - egresos" (L10).
- Capa de servicios (M7) — al menos extraer `services/movimientos.py` y `services/ventas.py`.
- Documentación: 4 ADRs + `MODELO_DOMINIO.md` + `KPIS.md`.

### Sesión 4+ (opcional, según prioridades del usuario)

- Migración a TypeScript del frontend (T2).
- Soft-delete + audit log (M8).
- Auth básica + Docker compose (T5/T6).
- Eliminar pandas (T4).
- Productos como entidad (parte de H6).

---

## Cierre

Si entregás esto a un equipo nuevo, lo primero que pediría que limpien es:
1. **`pago_aplicado`** — porque sin eso cada feature de cuentas corrientes es un parche.
2. **Schemas Pydantic + tipado** — porque sin contrato cada cambio rompe algo en el front silenciosamente.
3. **Helpers compartidos** — porque el día que se migre a Postgres se duplica el dolor 5 veces.

Lo que ya está bien y NO hace falta tocar: el modelo de cajas, los importers, Alembic, la separación KPIs/Routers, el patrón "casos a revisar", los backups automáticos. Todo eso paga.
