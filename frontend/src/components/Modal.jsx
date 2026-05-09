import { useEffect, useLayoutEffect, useRef, useState } from "react";

// Stack global de modales abiertos: el handler de Escape solo dispara
// para el modal "top". Sin esto, abrir un confirm sobre otro modal y
// apretar Escape cerraría el de abajo.
const modalStack = [];

const FOCUSABLE = "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])";

export default function Modal({ open, onClose, title, children, width = 800, hideClose = false }) {
  const ref = useRef(null);
  const previousFocus = useRef(null);
  // Ref de onClose para que la effect principal NO dependa de su referencia
  // — sino, callers que pasan `onClose={() => ...}` inline crean fn nueva
  // en cada render, disparan re-ejecución de la effect, y la nueva ejecución
  // captura `previousOverflow="hidden"` en vez del original (porque la
  // ejecución previa ya lo había seteado). Resultado: al desmontar el último
  // modal, body.overflow queda "hidden" en vez de restaurarse.
  //
  // Asignación directa durante render (no useEffect) — pattern recomendado
  // por React docs para refs que tracean valores mutables. useEffect corre
  // post-commit, dejando una ventana donde un event handler externo podría
  // leer la ref vieja. La asignación directa es síncrona con el render.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  // mouseDownTarget evita que un drag iniciado dentro del modal y
  // soltado sobre el overlay cierre el modal sin querer (drag-to-close bug).
  const [mouseDownOnOverlay, setMouseDownOnOverlay] = useState(false);

  // Foco inicial al primer focusable. useLayoutEffect en vez de
  // setTimeout(..., 0): mismo resultado pero con intención explícita.
  //
  // **Override deliberado de `autoFocus` de descendientes**: este focus()
  // corre DESPUÉS del autoFocus de React, así que pisa cualquier `autoFocus`
  // declarado en hijos. Decisión de jurado adversarial: para acciones
  // destructivas (mayoría de los confirms del sistema), focar al primer
  // focusable del DOM (típicamente Cancelar) es más defensivo que dejar
  // Aceptar focado — minimiza Enter reflejo en borrados. Si en el futuro
  // un caller necesita autoFocus respetado, considerar agregar prop
  // `Modal initialFocus="..."` opt-in en vez de cambiar este default.
  useLayoutEffect(() => {
    if (!open) return;
    previousFocus.current = document.activeElement;
    const focusable = ref.current?.querySelector(FOCUSABLE);
    if (focusable) {
      focusable.focus();
    } else if (ref.current) {
      // Fallback: si los children no tienen ningún elemento focusable
      // (caso raro: hideClose=true + contenido puramente informativo), el
      // foco quedaría afuera del modal y el Tab trap se rompería. Focamos
      // el wrapper del modal con tabindex=-1 para mantener el foco dentro.
      ref.current.focus();
    }
    return () => {
      // Restaurar foco al elemento que abrió el modal.
      if (previousFocus.current && previousFocus.current.focus) {
        previousFocus.current.focus();
      }
    };
  }, [open]);

  // Stack de modales + Escape + Tab trap + body overflow.
  // Solo depende de [open] — onClose se lee via ref (ver arriba).
  useEffect(() => {
    if (!open) return;

    const token = Symbol("modal");
    modalStack.push(token);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function handleKey(e) {
      if (modalStack[modalStack.length - 1] !== token) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current?.();
        return;
      }
      if (e.key === "Tab" && ref.current) {
        const focusables = ref.current.querySelectorAll(FOCUSABLE);
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      const idx = modalStack.indexOf(token);
      if (idx >= 0) modalStack.splice(idx, 1);
      if (modalStack.length === 0) {
        document.body.style.overflow = previousOverflow;
      }
    };
  }, [open]);

  if (!open) return null;

  function handleOverlayMouseDown(e) {
    setMouseDownOnOverlay(e.target === e.currentTarget);
  }
  function handleOverlayMouseUp(e) {
    if (mouseDownOnOverlay && e.target === e.currentTarget) {
      onClose?.();
    }
    setMouseDownOnOverlay(false);
  }

  return (
    <div
      onMouseDown={handleOverlayMouseDown}
      onMouseUp={handleOverlayMouseUp}
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
        // tabIndex=-1: focusable programáticamente como fallback cuando
        // children no tienen focusables (ver useLayoutEffect arriba). No
        // aparece en el orden de Tab natural, solo recibe foco vía .focus().
        tabIndex={-1}
        onMouseDown={(e) => e.stopPropagation()}
        onMouseUp={(e) => e.stopPropagation()}
        style={{
          background: "#1e293b", border: "1px solid #334155", borderRadius: 12,
          padding: 24, width, maxWidth: "92vw", maxHeight: "88vh", overflow: "auto",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 id="modal-title" style={{ margin: 0, fontSize: 18, color: "#f1f5f9" }}>{title}</h3>
          {!hideClose && (
            <button className="btn-ghost btn" onClick={onClose} aria-label="Cerrar">Cerrar</button>
          )}
        </div>
        {children}
      </div>
    </div>
  );
}
