import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import Modal from "./Modal";

const ConfirmContext = createContext({ confirm: () => Promise.resolve(false) });

export function ConfirmProvider({ children }) {
  const [estado, setEstado] = useState(null);
  const estadoRef = useRef(null);
  estadoRef.current = estado;

  // Cleanup: si el provider se desmonta con un confirm pendiente,
  // resolver false para que el caller no quede esperando para siempre.
  useEffect(() => {
    return () => {
      if (estadoRef.current) {
        try { estadoRef.current.resolve(false); } catch {}
      }
    };
  }, []);

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
      <Modal open={!!estado} onClose={() => responder(false)} title={estado?.titulo} width={460} hideClose>
        {estado && (
          <>
            <div style={{ whiteSpace: "pre-wrap", color: "#cbd5e1", marginBottom: 18 }}>
              {estado.mensaje}
            </div>
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button className="btn-ghost btn" onClick={() => responder(false)}>
                {estado.labelCancel}
              </button>
              {/* Sin autoFocus deliberadamente: el Modal padre foca al
                  primer focusable del DOM (Cancelar en este layout) — es
                  defensa para acciones destructivas (peligroso=true), que
                  son la mayoría de los confirms del sistema. La dueña tiene
                  que Tab+Enter para confirmar — minimiza Enter reflejo en
                  borrados. Decisión de jurado adversarial. */}
              <button
                className={`btn ${estado.peligroso ? "btn-danger" : ""}`}
                onClick={() => responder(true)}
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
