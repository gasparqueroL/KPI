import { useEffect, useRef } from "react";
import { API_ERROR_EVENT } from "../api/client";
import { useToast } from "./Toast";

/**
 * Convierte errores de axios (vía CustomEvent disparado por el interceptor)
 * en toasts de error. Coalesce dentro de 1.5s por **código de status**
 * (no por texto exacto): si 8 endpoints devuelven 404 cada uno con un path
 * distinto en `detail`, solo vemos UN toast 404 representativo en vez de 8.
 */
export default function ApiErrorBridge() {
  const toast = useToast();
  const ultimo = useRef({ status: null, ts: 0 });

  useEffect(() => {
    function onError(e) {
      // Soporta tanto el formato nuevo `{mensaje, status}` como el viejo
      // `string` directo (defensivo por si quedó algún caller anterior).
      const payload = e.detail;
      if (!payload) return;
      const mensaje = typeof payload === "string" ? payload : payload.mensaje;
      const status = typeof payload === "string" ? null : payload.status;
      if (!mensaje) return;

      const ahora = Date.now();
      // Coalescer por status: el caso típico es "backend caído" → N
      // requests fallan con la misma categoría. Mostrar 1 toast representa
      // bien el problema sin spam.
      if (status === ultimo.current.status && ahora - ultimo.current.ts < 1500) {
        return;
      }
      ultimo.current = { status, ts: ahora };
      toast.push(mensaje, "error");
    }
    window.addEventListener(API_ERROR_EVENT, onError);
    return () => window.removeEventListener(API_ERROR_EVENT, onError);
  }, [toast]);

  return null;
}
