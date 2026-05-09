# Review — Diseño / UX-UI

## Resumen ejecutivo

La app tiene una base visual coherente (paleta dark slate/azul + verde/ámbar/rojo semánticos, sistema de KPIs y paneles uniforme) y es funcionalmente densa, lo cual encaja con un usuario "power" que la usa todo el día. Pero está claramente diseñada para una sola pantalla de escritorio: rompe en mobile, no respeta accesibilidad básica (focus, contraste de algunos badges, semántica), tiene inconsistencias notorias entre páginas (toolbars duplicadas, diálogos `confirm()` nativos, tipografía/espaciados ad-hoc) y carece de microinteracciones que ayuden al usuario a confiar en el sistema (toasts, undo, skeletons, indicadores de "guardado"). Para reemplazar una planilla de cálculo estos detalles importan: hoy se siente más prototipo que producto.

## Strengths

- **Sistema de tokens implícito coherente**: paleta consistente (`#0f172a`/`#1e293b`/`#334155` para superficies, `#34d399`/`#f87171`/`#fbbf24` para semántica) usada en todas las páginas. El usuario aprende los colores rápido.
- **KPI cards uniformes**: `.kpi-card` + `.kpi-grid` con `auto-fit, minmax(200px, 1fr)` (`index.css:91-95`) escala bien y se ve profesional.
- **`KpiCardComp` con delta y flechas** (`KpiCardComp.jsx:10-22`): excelente affordance — el usuario ve de un vistazo "vendí más/menos que el período anterior", con color y signo. Muy bien hecho.
- **`SortableTable`** con indicadores `▲▼⇅` (`SortableTable.jsx:46`) y default-sort distinto para columnas numéricas (`desc`) vs. texto (`asc`) — muestra atención al detalle.
- **`PeriodPresets`** (Este mes, Mes pasado, YTD, etc.) (`PeriodPresets.jsx:5-57`): una de las mejores decisiones UX de la app. Reduce drásticamente clicks vs. seleccionar fechas a mano.
- **Empty states con tono empático** ("Nada para mostrar 🎉", `Conciliacion.jsx:130`; "No hay cobros pendientes 🎉", `CajaDiaria.jsx:179`): pequeño detalle, gran impacto.
- **CajaDiaria como "todo en una pantalla"** (`CajaDiaria.jsx:71-75`) con form de alta + saldos en vivo + recientes + pendientes: la decisión de densidad es correcta para el power-user.
- **PanelAlertas + Badges en sidebar** (`Layout.jsx:30-52`, `PanelAlertas.jsx`): el dueño ve "qué necesita su atención" sin pensar.
- **Cohorte heatmap** (`Analisis.jsx:65-86`) con leyenda de colores explícita: un tipo de visualización difícil hecho legible.

## Issues por severidad

### Critical (impide uso productivo)

1. **No hay layout responsive — la sidebar es fija 240px** (`index.css:15-21`): en cualquier pantalla < 900px (laptop chica, tablet, vista partida) la app simplemente se desborda con `overflow-x: auto` (`index.css:43`). Si el dueño abre la app en su celular o tablet (cosa esperable mientras camina por el depósito), no puede usarla. No hay menú hamburguesa, no hay collapse, no hay breakpoint <1100px (el único media query que existe es `index.css:141` y solo afecta `panel-grid`).

2. **`window.confirm()` y `alert()` para acciones destructivas e importantes** (`CajaDiaria.jsx:118`, `CasosRevisar.jsx:65`, `CuentasCorrientes.jsx:130, 149`, `Configuracion.jsx:60, 240`, `EditarVentaFila.jsx:65`): son diálogos nativos del browser, rompen el dark theme, no son traducibles, no permiten ver contexto (qué fila, qué monto). Para un usuario que va a borrar/forzar/mergear decenas de veces por día esto es agotador y propenso a errores. Necesita un Modal de confirmación in-app reusable.

3. **No hay feedback de éxito visible y persistente** después de la mayoría de las acciones: editar una venta (`EditarVentaFila.jsx`) no muestra "guardado", solo cierra; asignar un movimiento (`CuentasCorrientes.jsx:124-132`) recarga sin confirmar; descartar un caso (`CasosRevisar.jsx:64-68`) silenciosamente. El único toast existe en `FormNuevoMovimiento` (`CajaDiaria.jsx:500`) y dura 2s. El usuario no sabe si lo que hizo "tomó" — va a hacer doble-click defensivo y va a tener miedo de la app.

4. **Estados de carga inconsistentes y a veces engañosos**: `Direccion.jsx:36` muestra "Cargando..." la primera vez, pero las recargas posteriores solo muestran un spinner pequeño al lado del título. `Comercial.jsx`, `Caja.jsx` no tienen empty/loading state distinguibles — se ven los datos viejos con un spinner chiquito casi invisible al lado del título. El usuario no sabe si los KPIs son del período nuevo o aún del viejo. Necesita un overlay/skeleton o al menos opacar la zona en recarga.

### Important (frustra al usuario)

5. **Toolbar de filtros duplicada y desconectada** en `Direccion.jsx:48-54`, `Comercial.jsx:79-92`, `Conciliacion.jsx:59-65`: hay dos `.toolbar` consecutivos, el primero con DateRange + botón "Aplicar", el segundo con "Atajos:" + presets. Visualmente son dos cajas pegadas haciendo lo mismo. Debería ser una sola fila integrada con los presets como chips dentro del DateRange, o con los presets reemplazando el "Aplicar" cuando se cliquean (que ya hacen). El "Aplicar" tampoco se dispara automáticamente al cambiar fechas, lo cual obliga a un click extra siempre.

6. **Iconos de acción ambiguos** en `CajaDiaria.jsx:111, 123`: "✏" y "✕" como botones de Editar/Borrar son íconos texto crudos. No son SVG, no escalan, no tienen `aria-label` y dependen de `title` para descubribilidad. Use Lucide/Phosphor icons o al menos `aria-label`.

7. **Inputs de form sin estilos consistentes**: `EditarVentaFila.jsx:107-119` y `CajaDiaria.jsx:281-310` usan `<input>` directos sin las clases del theme; los inputs en `.toolbar` sí están estilados (`index.css:62-69`) pero los inputs sueltos heredan estilos browser-default y se ven con bordes blancos/celestes en focus, rompiendo el tema dark. Necesita una clase global `input` o estilo para `input:not([type=checkbox]):not([type=file])`.

8. **Foco de teclado invisible en todo lugar**: no hay `:focus-visible` definido en ningún lado. Para un usuario que va a tabular por un form de "nuevo movimiento" 50 veces al día, no saber dónde está el cursor es tortura. Es además un fail de accesibilidad básico.

9. **Contraste de algunos badges**: `.badge.warn` (`index.css:182`: `#7c2d12` bg / `#fdba74` color) y `.badge.err` (`#7f1d1d` / `#fca5a5`) están en el filo del WCAG AA (calculado ~4.0:1). En texto pequeño (11px) no pasa AA. La palabra "fc_empleado" (`Caja.jsx:91`) en badge.warn es difícil de leer rápido.

10. **Tabs con button + clases distintas**: `Conciliacion.jsx:117-125` y `Configuracion.jsx:10-28` no son `tab` semánticos (no hay `role="tablist"`/`role="tab"`/`aria-selected`), son botones que cambian color. El usuario con teclado/screen reader no entiende que está navegando entre vistas. Para un usuario vidente sí funcionan, pero la experiencia keyboard es pobre.

11. **Anchors `<a href="#">` con onClick para acciones no-navegacionales** (`CuentasCorrientes.jsx:67`, `Comercial.jsx:180`, `CajaDiaria.jsx:165`): semánticamente deberían ser `<button>` con estilo de link. Hoy el browser muestra "#" en la statusbar al hover, y el comportamiento de back-button puede romperse.

12. **`EditarVentaFila` y `EditarMovimientoFila` se renderizan inline en una `<td colSpan>`** (`CajaDiaria.jsx:127-139`, `Conciliacion.jsx:151-162`, `CuentasCorrientes.jsx:228-239`): el form ocupa todo el ancho de la tabla, empuja todas las filas y desorienta visualmente. Funciona, pero a partir de la 3ra-4ta edición el usuario pierde el contexto de qué estaba editando. Considerar Modal o panel lateral fijo.

13. **Tablas sin scroll horizontal explícito en mobile/laptop chica**: `Caja.jsx:114-129`, `CajaDiaria.jsx:80-144`, etc. tienen muchas columnas; en pantallas de 13" con la sidebar abierta se cortan o aprietan. Solo `CasosRevisar.jsx:113` y `Analisis.jsx:48` envuelven en `overflow-x: auto`.

14. **Diferencia rara en `Importar.jsx`**: el dropzone es enorme (`padding: 60px 20px`, `index.css:162`) y luego los resultados no tienen affordance de "qué hago ahora" — sí dicen "los rechazos quedaron en Casos a revisar" (`Importar.jsx:97`) pero no hay link directo al filtro. Debería ser un botón "Ir a casos a revisar (3)".

15. **`CuentasCorrientes.jsx:43` "Top deudor"** muestra `clientes[0]?.cliente` asumiendo que `clientes` viene ordenado por saldo desc. Si se cambia el orden o si el primer cliente es el que más ventas tiene pero saldo 0, miente. Debería calcular `Math.max` o asumir el orden explícitamente arriba con un comentario.

16. **`Conciliacion.jsx:165` "× quitar filtro"**: usa `<a href="#">`. Si me distraigo y le doy con click-medio se abre nueva tab a la home.

17. **No hay shortcut/keyboard nav entre páginas**: para un usuario "todo el día" debería poder hacer `g d` (go direccion), `g c` (caja), o al menos los `Tab`/`Arrow` funcionar bien. No es bloqueante pero suma fricción.

18. **`CuentasCorrientes.jsx:169` link directo a `http://localhost:8000/...`**: hardcoded localhost en producción no funciona y rompe accesibilidad/portabilidad. Es código no-UX pero el botón es visible.

19. **Modal solo se cierra con click fuera o "Cerrar"** (`Modal.jsx:5, 20`): no escucha `Escape`, no devuelve foco al elemento que lo abrió, no atrapa el foco dentro. Estándar fallido.

### Minor (pulido)

20. **Emojis hardcodeados en strings**: "🎉", "⚠", "🔴", "🟡", "🔵" (`Importar.jsx`, `Conciliacion.jsx`, `PanelAlertas.jsx:4-8`). Funcionan pero rompen consistencia visual con el resto. Mejor: SVG icons del mismo set.

21. **`fmtPct` se importa sin usar** en `KpiCardComp.jsx:1`: sin impacto pero ensucia.

22. **Texto descriptivo bajo los `<h2>`** se repite con `marginTop: -10` en muchas páginas (`Direccion.jsx:44`, `Importar.jsx:37`, `CajaDiaria.jsx:67`, `Analisis.jsx:27`). Debería ser un componente `PageHeader title="..." description="..." `.

23. **Los KPI cards con `tone="amber"` para "Ventas con discrepancia"** (`Comercial.jsx:109`) son condicionales — solo aparecen si hay valor. Ese aparece-y-desaparece deja huecos visuales en el grid.

24. **Inconsistencia en cómo se muestran fechas**: `CajaDiaria.jsx:202` (`v.fecha?.slice(0, 10)`), `Comercial.jsx:280` (`v.fecha?.slice(0, 16).replace("T", " ")`), `Caja.jsx:121` (`g.fecha` directo). Cada página formatea distinto.

25. **`Configuracion.jsx:98` `tamaño_kb`** con `ñ` en una key — no es un bug, pero contrasta con el resto del código que usa keys ASCII.

26. **`Modal.jsx` con todos los estilos inline**: imposible de tematizar, duplicado de la paleta. Lo mismo con `Layout.jsx:11-17` (badges) y muchos `style={{}}` en páginas. El `index.css` debería absorberlos.

27. **Loaders `<span className="spinner" />` de 12×12px** (`index.css:194`): muy chiquitos, se confunden con caracteres. Bueno tener uno mediano (24-32px) para zonas vacías.

28. **`CajaDiaria` panel "Cobros pendientes"**: los chips de cajas son grids de botones que con muchas cajas (>10) ocupan media pantalla. Considerar un select/scroll-x.

29. **Tipografía con un solo nivel**: 14px base en body, 22px en h2, 16-18px en h3 — pero falta una jerarquía intermedia para sub-secciones. Hoy todo se ve "plano".

30. **`Cohorte`**: las celdas muestran `0` o `0%` indistintamente (`Analisis.jsx:71`). Confuso.

## Recomendaciones de mejora

- **Sistema de toasts in-app**: un componente `<Toaster />` montado en `App.jsx` con un hook `useToast()` que cualquier acción pueda llamar (`toast.success('Movimiento #123 guardado')`, `toast.error(...)`). Reemplaza `confirm`/`alert` y los success-strings ad-hoc.
- **Componente `<ConfirmDialog>` con tema**: cualquier acción destructiva debería pasar por él, mostrando contexto rico (qué se va a borrar, montos, link a deshacer si aplica).
- **`PageHeader` componente**: title + description + acciones a la derecha (botón "Aplicar", export, etc.), reemplaza el patrón h2 + p disperso.
- **`FilterBar` componente**: unifica DateRange + Presets + filtros adicionales en una sola fila con estado interno; auto-aplica al cambiar (con debounce de 300ms) en lugar de exigir click "Aplicar".
- **Layout responsive con sidebar collapsible**: hamburger en <900px, slide-in. Las tablas pasan a cards apiladas con label/value (data-list).
- **`:focus-visible` global** con outline `2px solid #60a5fa offset 2px`. Tres líneas de CSS, gigantesco impacto a11y.
- **Skeleton loaders** en KPI grids y tablas durante recarga, en lugar de "datos viejos + spinner mini".
- **Iconos consistentes**: adoptar `lucide-react` (compatible con la paleta, SVG, ARIA-friendly) y reemplazar todos los `✏ ✕ ⬇ ← →` y emojis decorativos.
- **Modal con `Escape`, focus-trap y `aria-modal`**: usar un wrapper sobre Radix Dialog o Headless UI Dialog en lugar del DIY actual.
- **Edición inline en panel lateral en lugar de fila expandida**: cuando se clickea "Editar" abre un panel a la derecha (slide-in 480px) con el form, dejando la tabla intacta. Mucho menos desorientador.
- **Tabs accesibles**: usar `role="tablist"` o componente Radix Tabs; navegación con flechas izq/der.
- **Atajos de teclado**: `g+letra` para ir a páginas, `n` para nuevo movimiento en CajaDiaria, `/` para foco en filtro. Documentar con un panel `?`.
- **Botones de acción en tablas con consistencia**: actualmente conviven "Editar"/"Cerrar"/"Asignar →"/"✏"/"Desvincular" — definir un set fijo de verbos y tamaños.
- **Indicador de "última actualización"**: cada panel debería tener un timestamp pequeño "actualizado hace 12s" y botón refresh, sobre todo dado que las alertas se refrescan cada 60s pero los datos no.

## Plan priorizado

1. **Reemplazar `confirm`/`alert` por `ConfirmDialog` y `Toaster` in-app** — alto impacto en sensación de calidad y reduce ansiedad del usuario en cada operación destructiva. Toca ~8 archivos.
2. **Resolver feedback de éxito y estado de carga**: Toasts post-acción + skeleton/overlay durante recarga + opacar zona stale. Sin esto el usuario nunca confía en lo que hace.
3. **Layout responsive con sidebar collapsible y tablas adaptables** — abre el uso fuera del escritorio. Hoy el usuario *no puede* usar la app en mobile.
4. **`:focus-visible` global + Modal con `Escape`/focus-trap + tabs accesibles** — costo bajo, ganancia enorme en ergonomía teclado y accesibilidad. Imprescindible para uso intensivo.
5. **Componentizar `PageHeader` + `FilterBar` (con auto-apply) + iconos SVG consistentes** — elimina los dos toolbars duplicados, los `marginTop: -10`, los emojis crudos, y deja la app sintiéndose "diseñada" en lugar de "armada".
