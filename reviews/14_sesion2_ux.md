# Review — Sesión 2 UX productivo

## Resumen
3 críticos / 6 importantes / 7 menores

## Strengths

- **Arquitectura de providers limpia y bien anidada en `App.jsx`** (`ToastProvider` → `ConfirmProvider` → `AlertasProvider`). El orden permite que `ConfirmProvider` use el `Modal` y, si quisiera, también el toast.
- **`useConfirm` retorna directamente la función `confirm`** (no el contexto entero) — API ergonómica: `const ok = await confirmar({...})`.
- **`confirm` acepta string u object** (`typeof opciones === "string" ? { mensaje } : opciones`) — buen detalle DX.
- **Defaults sensatos** en confirm: títulos, labels, peligroso=false. Cero boilerplate cuando no hace falta.
- **Toast con `pointer-events: none` en el stack y `auto` en cada toast**: clicks atraviesan el contenedor. Detalle pulcro.
- **Animación CSS de entrada (`@keyframes toast-in`)** muy ligera, sin librerías.
- **`role="status"` en cada toast** y `role="dialog" aria-modal="true" aria-labelledby` en Modal — accesibilidad básica correcta.
- **`focus-visible` global**: outline sólo cuando el usuario navega con teclado, no con click. Bien hecho.
- **CSS responsive `@media (max-width: 900px)`**: sidebar fija con `transform`/`left` animado y overlay. Solución estándar y compacta.
- **Migración consistente del 90 % de pantallas críticas a `useConfirm` + `useToast`** (CajaDiaria, CasosRevisar, Configuracion, CuentasCorrientes, Proveedores).
- **Consistencia de tipo de toast**: `success` para creación, `info` para borrado/desvinculado, `error` para fallos. Patrón claro.
- **SVG icons inline en los botones de la fila de movimientos** sin emoji-fallback issues.

## Critical

### C1. `frontend/src/components/Toast.jsx:13` — leak de timer cuando el provider se desmonta
```js
setTimeout(() => {
  setToasts((prev) => prev.filter((t) => t.id !== id));
}, duracion);
```
No hay cleanup. Cuando el `ToastProvider` se desmonta (rara vez en producción, pero **siempre en HMR / tests / Strict Mode dev**) los timers quedan vivos y disparan `setToasts` sobre un componente desmontado → warning *"Can't perform a state update on an unmounted component"* y memory leak del closure.
- **Manifestación**: al recargar en dev con hot-reload mientras hay toasts activos; en tests con `@testing-library/react` (`render`/`unmount`).
- **Fix**: guardar timers en `useRef(new Map())` y limpiarlos en `useEffect(() => () => timers.current.forEach(clearTimeout), [])`. O bien chequear con un flag `mounted`.

### C2. `frontend/src/components/ConfirmDialog.jsx:23` — promise nunca se resuelve si el provider se desmonta
```js
function responder(ok) {
  if (estado) estado.resolve(ok);
  setEstado(null);
}
```
Si el provider se desmonta con un confirm pendiente, `responder` nunca se llama y el `await confirmar(...)` del caller queda colgado para siempre. El caller probablemente tiene `setBusy(true)` antes y nunca llega al `finally` → spinner eterno + handler bloqueado.
- **Manifestación**: navegación brusca durante un confirm abierto (poco común con un provider top-level), pero **garantizado en HMR / test teardown**.
- **Fix**: en un `useEffect(() => () => { if (estado) estado.resolve(false); }, [])` resolver con `false` al desmontar.

### C3. `frontend/src/components/EditarVentaFila.jsx:65` — quedó un `confirm()` nativo sin migrar
```js
if (confirm(e.response.data.detail + "\n\n¿Forzar igualmente?")) {
  return guardar(true);
}
```
Bloquea el navegador, rompe el patrón visual, y este componente se usa desde `CuentasCorrientes.jsx:260` y otros lugares. Inconsistente con el resto de la sesión.
- **Manifestación**: al editar una venta y cambiar el flag de cuenta corriente, si el backend devuelve 409, aparece un `window.confirm()` nativo del navegador en lugar del `ConfirmDialog`.
- **Fix**: convertir la función en hook usando `useConfirm()` (igual que `CuentasCorrientes.toggleCtaCte` que ya lo hace bien en `CuentasCorrientes.jsx:174`).

## Important

### I1. `frontend/src/components/Modal.jsx:6-19` — focus trap incompleto + restauración de foco ausente
El efecto sólo hace `focus()` inicial. **No atrapa Tab/Shift+Tab**: con varios tabs el foco escapa al fondo (a la sidebar, a botones de la página) mientras el usuario lo percibe como modal-bloqueante. Tampoco restaura el foco al elemento que abrió el modal cuando se cierra → el usuario teclado pierde su sitio.
- **Gravedad**: media-alta para usuarios de teclado / lectores de pantalla; baja para usuarios de mouse. WCAG 2.1.2 (focus order) y 2.4.3 (focus order) lo exigen para `aria-modal="true"`.
- **Fix**: handler `Tab` que cycle focus dentro del modal, y al abrir guardar `document.activeElement` y devolverle el foco al cerrar.

### I2. `frontend/src/components/Modal.jsx:24-25` — `onClick={onClose}` sin distinguir mousedown/mouseup (drag bug)
Si el usuario empieza a seleccionar texto **dentro** del modal, arrastra el mouse y suelta **fuera**, el `mouseup` cae sobre el overlay y cierra el modal sin querer. Es un patrón clásico de modales mal hechos y muy frustrante en confirms con mensajes largos (`whiteSpace: pre-wrap` en `ConfirmDialog.jsx:34` invita a copiar texto).
- **Fix**: detectar `onMouseDown` sobre el overlay y sólo cerrar si el `mouseup` también es sobre el overlay (state local `mouseDownTarget`).

### I3. `frontend/src/components/Layout.jsx:66` — el overlay tiene el mismo bug de "drag-to-close"
Mismo patrón que I2: si el usuario inicia un drag sobre la sidebar y suelta sobre el overlay, se cierra. Menos crítico (sólo es la sidebar), pero el comportamiento se siente mal.

### I4. `frontend/src/components/Modal.jsx:6-19` — sin restablecer overflow del body
El modal no setea `body.style.overflow = "hidden"`. Si el contenido detrás puede scrollear, el usuario puede scrollearlo con la rueda mientras el modal está abierto. Estética/UX media.

### I5. `frontend/src/components/Toast.jsx:5` — `let counter = 0` a nivel módulo
Funciona porque es un módulo singleton, pero:
- Múltiples instancias del provider en el mismo árbol (rara vez intencional, frecuente en tests con `render(<ToastProvider>...)` por test) **comparten el counter**. Si la prueba A crea toast id=3 y la prueba B también, no colisionan porque `++counter` es secuencial — pero no hay isolation entre tests.
- En SSR / Vitest concurrente puede generar duplicados teóricos.
- **Fix**: mover `counter` adentro del provider con `useRef(0)`. Cero costo, infinitamente más correcto.

### I6. `frontend/src/components/Modal.jsx:9` — Escape cierra **siempre** el modal del fondo si hay dos abiertos
El handler está en `document` y no chequea si este modal es el "top". Si abrís un confirm desde dentro de otro modal (`Configuracion` → `Mergear` confirm sobre el modal de cierre, por ejemplo), Escape cerraría el de abajo. Hoy no se da en la app pero es trampa abierta.
- **Fix**: no setear handler si hay otro modal arriba (stack global) o usar `e.target` para confirmar.

## Minor

### M1. `frontend/src/components/Modal.jsx:12` — `setTimeout(..., 0)` para foco
Funciona pero es smelly. Mejor usar `useLayoutEffect` o `requestAnimationFrame`. Resultado idéntico, intención más clara.

### M2. `frontend/src/components/Modal.jsx:18` — el cleanup no es exhaustivo
El `return () => document.removeEventListener(...)` está bien para `keydown`, pero si se agrega el focus-trap (I1) hay que limpiar también ese listener.

### M3. `frontend/src/components/Toast.jsx:23` — `role="status"` siempre
`status` (= `aria-live="polite"`) está bien para info/success, pero **errores deberían ser `role="alert"`** (= `assertive`) para que lectores de pantalla los anuncien sin esperar. Variar según `tipo`.

### M4. `frontend/src/index.css:298-305` — `:focus-visible` global aplica también a inputs dentro de Modal
No hay over-styling porque el outline azul (#60a5fa) combina con el fondo del modal (#1e293b), pero el `outline-offset: 2px` puede chocar con el padding interno de inputs muy pegados al borde del modal. Verificar visualmente en `EditarMovimientoFila` (modal de edición), aunque no es modal — es expandible inline, así que no aplica de hecho.

### M5. `frontend/src/components/Layout.jsx:38` — `onClick` en `<nav>` para cerrar sidebar
Funciona aún si el click cae sobre un `<Badge>` (la propagación lo lleva al `<nav>`). PERO: si en el futuro alguien pone un `<button>` dentro del nav (p. ej. logout), también cerraría la sidebar al clickearlo en mobile. Mejor: ponerlo en cada `<NavLink>` (`onClick`) o usar `useNavigate`/`location` para cerrar al cambiar de ruta. Actual es frágil.

### M6. `frontend/src/components/Layout.jsx:34` — botón de toggle dice `☰` (unicode) y depende de la fuente
Inconsistente con la decisión de la sesión (SVG icons). Reemplazar por SVG burger/X según `abierto`.

### M7. `frontend/src/components/ConfirmDialog.jsx:31` — el confirm dialog tiene el botón "Cerrar" del Modal **además** de Cancelar
Modal renderiza siempre un botón "Cerrar" en el header. En un confirm se ve raro tener tres salidas: Cerrar (header), Cancelar (footer), backdrop click. Los tres hacen `onClose=responder(false)` así que es funcionalmente correcto, pero visualmente sobrecargado para un confirm de 1 línea.
- Posible mejora: prop `Modal({ hideClose })` para confirms.

### M8. Mensajes de éxito en CajaDiaria duplican feedback
`CajaDiaria.jsx:420` setea `success` local y a la vez en otros endpoints usa `toast.push`. Mezcla de patrones — el `<span>✓ {success}</span>` de `FormNuevoMovimiento` y `EditarMovimientoFila` (`:364`, `:525`) podrían migrar a toast también para consistencia.

## Inconsistencias detectadas

### Pantallas / componentes con código viejo que escapó a la migración

1. **`frontend/src/components/EditarVentaFila.jsx:65`** — usa `confirm()` nativo. Componente no listado en los archivos de la sesión pero es invocado desde `CuentasCorrientes` (que sí está) — quedó fuera del barrido. **Crítico (C3)**.
2. **`frontend/src/pages/Configuracion.jsx:255`** — `alert("Origen y destino deben ser distintos")` quedó sin migrar dentro de `Cajas.ejecutarMerge`. La función ya tiene `useToast()` arriba (`:240`), así que el cambio es una línea: `toast.push("Origen y destino deben ser distintos", "error")`.
3. **`frontend/src/pages/CuentasCorrientes.jsx:121`, `:133`** — `console.error("Error cargando ledger", e)` y similares en `cargarSinAsignar`. Errores silenciosos: el usuario no ve nada, sólo queda en consola. Inconsistente con el resto del archivo que usa toast.
4. **`frontend/src/pages/CajaDiaria.jsx:53-66`** — `verificarSeleccionadas` no muestra error si `api.post` falla (sólo `setVerificando(false)` en `finally`). Misma inconsistencia.
5. **`frontend/src/pages/CajaDiaria.jsx:38`, `:34`, `:117`** — `cargarTodo`, `cargarPendientes` y otros loaders no manejan errores. Si el endpoint falla la pantalla queda en blanco sin feedback.

### Unicode icons que NO se migraron a SVG

La sesión sólo migró 2 botones (editar/borrar en `CajaDiaria.jsx:121-148`). Quedan los siguientes (todos los listados se ven legítimamente como icono en un botón o título, no como texto narrativo):

- **`frontend/src/components/Layout.jsx:34`**: `☰` (botón hamburguesa).
- **`frontend/src/components/SortableTable.jsx:46`**: `▲ ▼ ⇅` (indicadores de orden).
- **`frontend/src/components/PanelAlertas.jsx:16`**: `⚠ Alertas activas`.
- **`frontend/src/components/KpiCardComp.jsx:10`**: `↑ ↓ •` (delta indicator).
- **`frontend/src/pages/CuentasCorrientes.jsx:202`**: `⬇ Descargar extracto CSV`.
- **`frontend/src/pages/CuentasCorrientes.jsx:303`**, **`Proveedores.jsx:303`**: `Asignar →` / `Vincular →`.
- **`frontend/src/pages/CajaDiaria.jsx:364`, `:525`, `:526`**, **`CasosRevisar.jsx:258`**, **`EditarVentaFila.jsx:101`**: `✓ ✗` para success/error inline.
- **`frontend/src/pages/CasosRevisar.jsx:179, 181`**: `← Anterior` / `Siguiente →`.
- **`frontend/src/pages/Comercial.jsx:95`**: `⚠ Para ver comparativa...`.

Decidir: **¿migrar todo a SVG por consistencia o aceptar unicode salvo en botones de acción?** Hoy quedó a mitad de camino.

## Recomendaciones top 5

1. **Arreglar el leak de timers en Toast (C1) y la promise leak en ConfirmDialog (C2)** — ambos son one-liners y previenen warnings/bugs en HMR y tests. Es plomería que paga sola.
2. **Migrar `EditarVentaFila.jsx:65` a `useConfirm` y `Configuracion.jsx:255` a `toast.push`** — son los dos huérfanos de la migración. Sin esto el patrón "no hay alerts/confirms nativos" se rompe.
3. **Mejorar Modal**: focus trap real + restaurar foco al cerrar + fix mousedown/mouseup en backdrop (I1, I2) + `body.style.overflow` (I4). El Modal es el cimiento de ConfirmDialog y de cualquier modal futuro; vale invertir media hora ahora.
4. **Decidir política de iconografía** y aplicarla parejo: o todo SVG (al menos en botones de acción y en el toggle de sidebar) o aceptar unicode con regla clara. Hoy quedó híbrido sin criterio explícito.
5. **Estandarizar manejo de errores en loaders**: hoy `cargarTodo`, `cargarLedger`, `cargarSinAsignar` etc. tienen patrones distintos (algunos `console.error`, otros nada, otros toast). Crear un wrapper `useApiCall` o convención: **todo `catch` en un loader hace `toast.push(..., "error")`**. Sin eso, la promesa de "el usuario siempre ve qué pasó" no se cumple.
