# UX Productivo (Sesión 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Reemplazar diálogos nativos del browser, agregar feedback consistente, hacer la app responsive y accesible para uso diario.

**Architecture:** Componentes React reutilizables + context providers globales para Toast y Confirm. Cambios mínimos en pages existentes — solo reemplazar `alert/confirm` por hooks. CSS con media queries para responsive.

**Tech Stack:** React + Vite (existente).

**Notas:**
- Frontend Vite con HMR — los cambios se ven al instante.
- Sin git: skip commits.
- Tests no aplican a la mayoría (UI). Smoke test manual en cada pantalla afectada.

---

## Task 1: Toast component + Provider global

**Files:**
- Create: `frontend/src/components/Toast.jsx`
- Modify: `frontend/src/App.jsx` (envolver con `<ToastProvider>`)
- Modify: `frontend/src/index.css` (estilos del toast)

Reemplaza `alert()` para feedback de éxito/error post-acción. Stack vertical en esquina inferior-derecha, auto-dismiss en 3s.

- [ ] **Step 1: Crear el componente + provider + hook**

`frontend/src/components/Toast.jsx`:
```jsx
import { createContext, useCallback, useContext, useState } from "react";

const ToastContext = createContext({ push: () => {} });

let counter = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const push = useCallback((mensaje, tipo = "info", duracion = 3000) => {
    const id = ++counter;
    setToasts((prev) => [...prev, { id, mensaje, tipo }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, duracion);
  }, []);

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="toast-stack">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.tipo}`} role="status">
            {t.mensaje}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
```

- [ ] **Step 2: Estilos en `index.css`**

Agregar al final de `frontend/src/index.css`:
```css
.toast-stack {
  position: fixed;
  right: 20px;
  bottom: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 1000;
  pointer-events: none;
}
.toast {
  background: #1e293b;
  border: 1px solid #334155;
  border-left-width: 4px;
  color: #e2e8f0;
  padding: 12px 16px;
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
  min-width: 240px;
  max-width: 380px;
  font-size: 13px;
  pointer-events: auto;
  animation: toast-in 0.2s ease-out;
}
.toast-success { border-left-color: #34d399; }
.toast-error { border-left-color: #f87171; }
.toast-info { border-left-color: #60a5fa; }
.toast-warn { border-left-color: #fbbf24; }
@keyframes toast-in {
  from { transform: translateX(20px); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}
```

- [ ] **Step 3: Envolver App con `ToastProvider`**

En `frontend/src/App.jsx`, envolver el `<AlertasProvider>` con `<ToastProvider>`:
```jsx
import { ToastProvider } from "./components/Toast";

// dentro del App:
<BrowserRouter>
  <ToastProvider>
    <AlertasProvider>
      ... resto igual ...
    </AlertasProvider>
  </ToastProvider>
</BrowserRouter>
```

Agregar `import { ToastProvider } from "./components/Toast";` arriba.

- [ ] **Step 4: Verificación rápida**

Reiniciar Vite si HMR no agarra. Abrir consola del navegador (F12), ejecutar:
```js
// Ningún error de compilación esperado
```

NO modificar páginas todavía — eso viene en Task 2 cuando reemplacemos los `alert()`.

---

## Task 2: ConfirmDialog component + reemplazar confirms nativos

**Files:**
- Create: `frontend/src/components/ConfirmDialog.jsx`
- Modify: `frontend/src/App.jsx`
- Modify páginas que usan `confirm()`:
  - `frontend/src/pages/CajaDiaria.jsx` (borrar movimiento)
  - `frontend/src/pages/CasosRevisar.jsx` (descartar caso)
  - `frontend/src/pages/Configuracion.jsx` (mergear cajas, borrar backup)
  - `frontend/src/pages/CuentasCorrientes.jsx` (toggleCtaCte con forzar)

- [ ] **Step 1: Componente + provider + hook `useConfirm`**

`frontend/src/components/ConfirmDialog.jsx`:
```jsx
import { createContext, useCallback, useContext, useState } from "react";
import Modal from "./Modal";

const ConfirmContext = createContext({ confirm: () => Promise.resolve(false) });

export function ConfirmProvider({ children }) {
  const [estado, setEstado] = useState(null);

  const confirm = useCallback((opciones) => {
    return new Promise((resolve) => {
      const opts = typeof opciones === "string" ? { mensaje: opciones } : opciones;
      setEstado({
        titulo: opts.titulo || "Confirmar",
        mensaje: opts.mensaje || "",
        labelOk: opts.labelOk || "Aceptar",
        labelCancel: opts.labelCancel || "Cancelar",
        peligroso: !!opts.peligroso,
        resolve,
      });
    });
  }, []);

  function responder(ok) {
    if (estado) estado.resolve(ok);
    setEstado(null);
  }

  return (
    <ConfirmContext.Provider value={{ confirm }}>
      {children}
      <Modal open={!!estado} onClose={() => responder(false)} title={estado?.titulo} width={460}>
        {estado && (
          <>
            <div style={{ whiteSpace: "pre-wrap", color: "#cbd5e1", marginBottom: 18 }}>
              {estado.mensaje}
            </div>
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button className="btn-ghost btn" onClick={() => responder(false)}>
                {estado.labelCancel}
              </button>
              <button
                className={`btn ${estado.peligroso ? "btn-danger" : ""}`}
                onClick={() => responder(true)}
                autoFocus
              >
                {estado.labelOk}
              </button>
            </div>
          </>
        )}
      </Modal>
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  return useContext(ConfirmContext).confirm;
}
```

- [ ] **Step 2: Envolver App con `ConfirmProvider`** (dentro del Toast):

```jsx
<ToastProvider>
  <ConfirmProvider>
    <AlertasProvider>
      ...
```

- [ ] **Step 3: Reemplazar `confirm()` en `CajaDiaria.jsx`**

Buscar el botón ✕ que tiene:
```jsx
onClick={async () => {
  if (!confirm(`¿Borrar movimiento #${m.id}?\n\n${m.tipo_operacion}: ${m.detalle || "(sin detalle)"}\n${fmtMoney(m.monto)}`)) return;
  await api.delete(`/api/caja-diaria/movimiento/${m.id}`);
  cargarTodo();
}}
```

Reemplazar por (necesita `useConfirm` y `useToast` importados arriba del componente):
```jsx
onClick={async () => {
  const ok = await confirmar({
    titulo: `Borrar movimiento #${m.id}`,
    mensaje: `${m.tipo_operacion}: ${m.detalle || "(sin detalle)"}\n${fmtMoney(m.monto)}`,
    labelOk: "Borrar",
    peligroso: true,
  });
  if (!ok) return;
  await api.delete(`/api/caja-diaria/movimiento/${m.id}`);
  toast.push("Movimiento borrado", "success");
  cargarTodo();
}}
```

Y al inicio del componente `CajaDiaria` agregar:
```jsx
import { useConfirm } from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";
// ...
const confirmar = useConfirm();
const toast = useToast();
```

- [ ] **Step 4: Reemplazar `confirm()` en `CasosRevisar.jsx`**

Buscar la función `descartar`:
```jsx
async function descartar(id) {
  if (!confirm("¿Descartar este caso?")) return;
  await api.post(`/api/casos-revisar/${id}/descartar`);
  cargar();
}
```

Reemplazar (con `useConfirm`/`useToast` agregados al componente):
```jsx
async function descartar(id) {
  const ok = await confirmar({
    titulo: "Descartar caso",
    mensaje: "El caso quedará marcado como descartado y no se podrá editar más.",
    labelOk: "Descartar",
    peligroso: true,
  });
  if (!ok) return;
  await api.post(`/api/casos-revisar/${id}/descartar`);
  toast.push("Caso descartado", "info");
  cargar();
}
```

- [ ] **Step 5: Reemplazar `confirm()` en `Configuracion.jsx`** (mergear + borrar backup)

Buscar `borrar(archivo)` en `Backups`:
```jsx
async function borrar(archivo) {
  if (!confirm(`¿Borrar ${archivo}?`)) return;
  ...
}
```

Reemplazar:
```jsx
async function borrar(archivo) {
  const ok = await confirmar({
    titulo: "Borrar backup",
    mensaje: `Se eliminará el archivo ${archivo} permanentemente.`,
    labelOk: "Borrar",
    peligroso: true,
  });
  if (!ok) return;
  await api.delete(`/api/admin/backups/${archivo}`);
  toast.push("Backup borrado", "info");
  cargar();
}
```

Buscar `ejecutarMerge` en `Cajas`:
```jsx
if (!confirm(`Mergear "${dispCfg(merge.desde)}" → "${dispCfg(merge.hacia)}"?...`)) return;
```

Reemplazar:
```jsx
const ok = await confirmar({
  titulo: "Mergear cajas",
  mensaje: `"${dispCfg(merge.desde)}" → "${dispCfg(merge.hacia)}"\n\nLa primera caja se eliminará y todas sus referencias pasarán a la segunda.`,
  labelOk: "Mergear",
  peligroso: true,
});
if (!ok) return;
```

Y al inicio de `Backups()` y `Cajas()`:
```jsx
const confirmar = useConfirm();
const toast = useToast();
```

- [ ] **Step 6: Reemplazar `confirm()` en `CuentasCorrientes.jsx`**

Buscar `toggleCtaCte` con `confirm(e.response.data.detail + ...)`:
```jsx
if (e.response?.status === 409) {
  if (confirm(e.response.data.detail + "\n\n¿Forzar el desmarcado igualmente?")) {
    toggleCtaCte(idPedido, esCtaCteActual, true);
  }
}
```

Reemplazar por (función debe ser `async`, ya lo es):
```jsx
if (e.response?.status === 409) {
  const ok = await confirmar({
    titulo: "Confirmar desmarcado",
    mensaje: e.response.data.detail + "\n\n¿Forzar el desmarcado igualmente?",
    labelOk: "Forzar",
    peligroso: true,
  });
  if (ok) toggleCtaCte(idPedido, esCtaCteActual, true);
}
```

Y al inicio del componente `DetalleCliente`:
```jsx
const confirmar = useConfirm();
```

- [ ] **Step 7: Verificar manualmente cada acción**

Recargar el navegador y probar:
1. Caja Diaria → ✕ en un movimiento → modal con título + texto + botón rojo "Borrar"
2. Casos a revisar → Descartar → modal explicativo
3. Configuración → Backups → Borrar → modal
4. Configuración → Cajas → Ejecutar merge → modal con info
5. Cuentas corrientes → Marcar/desmarcar cta cte que tenga conflicto → modal en 409

NO debe quedar NINGÚN `confirm()` ni `alert()` nativo (excepto los `alert()` puros de error que vienen del catch — esos los cambiamos en Task 3).

---

## Task 3: Reemplazar `alert()` errors por toast

**Files:**
- Modify: `frontend/src/components/EditarVentaFila.jsx`
- Modify: `frontend/src/pages/CuentasCorrientes.jsx`
- Modify: `frontend/src/pages/CajaDiaria.jsx` (si quedó alguno)

Hay varios `alert(e.response?.data?.detail || ...)` en handlers de error. Reemplazar por `toast.push(..., "error")`.

- [ ] **Step 1: `EditarVentaFila.jsx`**

Buscar `alert(e.response?.data?.detail || "Error")` (línea ~92 aprox). Reemplazar todo el bloque del catch por:
```jsx
} catch (e) {
  setError(e.response?.data?.detail || e.message);
}
```

(Nota: ya hay `setError` y se muestra abajo. No hace falta agregar toast.)

- [ ] **Step 2: `CuentasCorrientes.jsx`**

Buscar `alert(e.response?.data?.detail || "Error asignando movimiento")` y `alert(e.response?.data?.detail || "Error")`.

Agregar al inicio del componente `DetalleCliente`:
```jsx
const toast = useToast();
```

Reemplazar los `alert(...)` por:
```jsx
toast.push(e.response?.data?.detail || "Error", "error");
```

(Asegurar que `useToast` esté importado.)

- [ ] **Step 3: `CajaDiaria.jsx`**

Verificar que ya no haya `alert(...)`. Si queda alguno, mismo patrón.

- [ ] **Step 4: Smoke test**

Provocar un error (ej. asignar un movimiento sin permiso) y verificar que aparece toast rojo en la esquina, no `alert` nativo del browser.

---

## Task 4: Modal accesible (Escape + click outside + focus trap básico)

**Files:**
- Modify: `frontend/src/components/Modal.jsx`

El Modal actual no cierra con Escape ni atrapa foco. Hacerlo accesible.

- [ ] **Step 1: Reemplazar `Modal.jsx` por versión accesible**

```jsx
import { useEffect, useRef } from "react";

export default function Modal({ open, onClose, title, children, width = 800 }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    function handleKey(e) {
      if (e.key === "Escape") onClose?.();
    }
    document.addEventListener("keydown", handleKey);
    // Focus inicial
    setTimeout(() => {
      const focusable = ref.current?.querySelector(
        "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"
      );
      focusable?.focus();
    }, 0);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? "modal-title" : undefined}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
      }}
    >
      <div
        ref={ref}
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#1e293b", border: "1px solid #334155", borderRadius: 12,
          padding: 24, width, maxWidth: "92vw", maxHeight: "88vh", overflow: "auto",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 id="modal-title" style={{ margin: 0, fontSize: 18, color: "#f1f5f9" }}>{title}</h3>
          <button className="btn-ghost btn" onClick={onClose} aria-label="Cerrar">Cerrar</button>
        </div>
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Smoke test**

1. Abrir un modal cualquiera (ej. drill-down vendedor en Comercial)
2. Apretar Escape → cierra
3. Click afuera → cierra
4. Tab → navega elementos del modal

---

## Task 5: Layout responsive básico

**Files:**
- Modify: `frontend/src/components/Layout.jsx`
- Modify: `frontend/src/index.css`

Sidebar fija de 240px hace que la app sea inutilizable < 900px. Sidebar colapsable + tabla con `overflow-x: auto`.

- [ ] **Step 1: Modificar Layout para sidebar colapsable**

En `frontend/src/components/Layout.jsx`, agregar estado de colapso y botón hamburguesa:

```jsx
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAlertas } from "./AlertasContext";

function Badge({ count, kind }) {
  // ... igual que está
}

export default function Layout() {
  const { criticas, atencion, alertas } = useAlertas();
  const [abierto, setAbierto] = useState(false);
  const casosCnt = alertas.find((a) => a.codigo === "casos_pendientes")?.valor || 0;
  const cajaCnt = alertas.find((a) => a.codigo === "caja_saldo_negativo")?.valor || 0;
  const configCnt = alertas.find((a) => a.codigo === "categorias_sin_familia")?.valor || 0;

  return (
    <div className="app">
      <button
        className="sidebar-toggle"
        aria-label="Abrir menú"
        onClick={() => setAbierto(!abierto)}
      >
        ☰
      </button>
      <aside className={`sidebar ${abierto ? "abierto" : ""}`}>
        <h1>KPI Dashboard</h1>
        <nav onClick={() => setAbierto(false)}>
          {/* ... NavLinks iguales que están ... */}
        </nav>
      </aside>
      {abierto && (
        <div className="sidebar-overlay" onClick={() => setAbierto(false)} />
      )}
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 2: CSS responsive en `index.css`**

Agregar al final:
```css
.sidebar-toggle {
  display: none;
  position: fixed;
  top: 12px;
  left: 12px;
  z-index: 50;
  background: #1e293b;
  color: #e2e8f0;
  border: 1px solid #334155;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 18px;
  cursor: pointer;
}
.sidebar-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 30;
}
table {
  /* asegurar que tablas largas tengan scroll horizontal en mobile */
}
.panel {
  overflow-x: auto;
}

@media (max-width: 900px) {
  .sidebar-toggle { display: block; }
  .sidebar {
    position: fixed;
    left: -260px;
    top: 0;
    height: 100vh;
    z-index: 40;
    transition: left 0.2s;
    overflow-y: auto;
  }
  .sidebar.abierto { left: 0; }
  .main { padding: 60px 16px 16px; }
  .panel-grid { grid-template-columns: 1fr; }
  .kpi-grid { grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
  .kpi-card .value { font-size: 18px; }
}
```

- [ ] **Step 3: Smoke test**

1. Achicar la ventana del navegador a < 900px de ancho
2. Aparece el botón ☰ arriba-izquierda
3. Click → sidebar se desliza desde la izquierda
4. Click en un link o en el overlay → sidebar se cierra
5. Las tablas anchas hacen scroll horizontal

---

## Task 6: Pulido final (focus-visible + iconos SVG)

**Files:**
- Modify: `frontend/src/index.css` (focus-visible global)
- Modify: `frontend/src/pages/CajaDiaria.jsx` (iconos ✏ ✕ → SVG inline)

- [ ] **Step 1: `:focus-visible` global**

Agregar al final de `frontend/src/index.css`:
```css
button:focus-visible,
input:focus-visible,
select:focus-visible,
textarea:focus-visible,
a:focus-visible {
  outline: 2px solid #60a5fa;
  outline-offset: 2px;
}
```

- [ ] **Step 2: Iconos SVG en feed de Caja Diaria**

En `CajaDiaria.jsx`, reemplazar los botones que tienen `✏` y `✕` por SVGs inline. Reemplazar el bloque:

```jsx
<button
  className="btn-ghost btn"
  title="Editar"
  style={{ padding: "4px 8px", marginRight: 4 }}
  onClick={() => setEditandoId(editandoId === m.id ? null : m.id)}
>
  ✏
</button>
<button
  className="btn-ghost btn"
  title="Borrar"
  style={{ padding: "4px 8px" }}
  onClick={async () => {
    // ... lógica
  }}
>
  ✕
</button>
```

Por:
```jsx
<button
  className="btn-ghost btn"
  title="Editar"
  aria-label="Editar movimiento"
  style={{ padding: "4px 8px", marginRight: 4 }}
  onClick={() => setEditandoId(editandoId === m.id ? null : m.id)}
>
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M12 20h9" />
    <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
  </svg>
</button>
<button
  className="btn-ghost btn"
  title="Borrar"
  aria-label="Borrar movimiento"
  style={{ padding: "4px 8px" }}
  onClick={async () => {
    // ... misma lógica con confirmar/toast
  }}
>
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M3 6h18" />
    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
    <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
  </svg>
</button>
```

- [ ] **Step 3: Smoke test**

1. Tab por la app → outline azul visible en cada elemento focuseado
2. Caja Diaria feed → iconos lápiz/basura en lugar de unicode

---

## Resumen

| Task | Componente | Archivos |
|------|-----------|----------|
| 1 | Toast component | nuevo + App + CSS |
| 2 | ConfirmDialog | nuevo + App + 4 páginas |
| 3 | alert() → toast errors | 3 archivos |
| 4 | Modal accesible | 1 archivo |
| 5 | Responsive | Layout + CSS |
| 6 | Pulido (focus + SVG) | CSS + CajaDiaria |

Total estimado: ~2 horas. Sin migraciones ni backend, todo frontend.
