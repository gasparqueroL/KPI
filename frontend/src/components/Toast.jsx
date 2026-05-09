import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

const ToastContext = createContext({ push: () => {} });

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timersRef = useRef(new Map());
  const mountedRef = useRef(true);
  // Counter por instancia (no a nivel módulo): aísla tests que renderizan
  // múltiples providers y evita teóricos duplicados en SSR concurrente.
  const counterRef = useRef(0);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      for (const tid of timersRef.current.values()) clearTimeout(tid);
      timersRef.current.clear();
    };
  }, []);

  const push = useCallback((mensaje, tipo = "info", duracion = 3000) => {
    const id = ++counterRef.current;
    setToasts((prev) => [...prev, { id, mensaje, tipo }]);
    const tid = setTimeout(() => {
      if (!mountedRef.current) return;
      setToasts((prev) => prev.filter((t) => t.id !== id));
      timersRef.current.delete(id);
    }, duracion);
    timersRef.current.set(id, tid);
  }, []);

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="toast-stack">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`toast toast-${t.tipo}`}
            role={t.tipo === "error" ? "alert" : "status"}
          >
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
