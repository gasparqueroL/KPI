import axios from "axios";

// baseURL toma la env VITE_API_URL si está seteada (deploy detrás de proxy
// o en otra origin); por defecto usa el dev server local del backend.
// Para deploys con front+back en el mismo origen, dejar VITE_API_URL="".
const baseURL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

const api = axios.create({
  baseURL,
  timeout: 600000,
});

// Interceptor de request: si VITE_API_KEY está configurada en build, agrega
// el header X-API-Key automáticamente. El backend lo exige cuando KPI_API_KEY
// está seteada (deploy fuera de localhost). Sin VITE_API_KEY no toca nada
// (modo localhost sin auth).
//
// ⚠️ TRADEOFF DE SEGURIDAD A ENTENDER:
// La key queda hardcoded en el bundle JS público. Cualquiera con DevTools
// (F12 → Sources, o "view source") puede leerla. Esto es OBFUSCACIÓN, no
// seguridad real. Aceptable solo si:
//   1. La URL del frontend es privada (deploy interno, IP no listada,
//      detrás de VPN/Tailscale/Cloudflare Access).
//   2. El modelo de amenaza es "evitar scrapers casuales", no "atacante
//      motivado".
// Para frontend con URL pública, la solución correcta es auth con sesión
// (login + cookie con HttpOnly) o un proxy inverso con auth real.
const apiKey = import.meta.env.VITE_API_KEY;
if (apiKey) {
  api.interceptors.request.use((config) => {
    config.headers["X-API-Key"] = apiKey;
    return config;
  });
}

// Bridge a Toast: el interceptor no puede usar el hook useToast directamente
// (no es un componente). En su lugar, dispara un CustomEvent que el
// <ApiErrorBridge> en App.jsx escucha para mostrar el toast. Así cualquier
// loader que no tenga su propio try/catch deja de fallar en silencio.
//
// `silent: true` en la config saltea el toast (útil cuando la página ya
// muestra el error inline o cuando 404 es esperado, p. ej. /pagos-aplicados).
export const API_ERROR_EVENT = "api-error";

api.interceptors.response.use(
  (r) => r,
  (error) => {
    // `silent: true` opt-in para casos donde 404/error es esperado (p.ej.
    // GET de pagos-aplicados en movimientos no-ingreso). NO silenciamos
    // 404 GET globalmente: un typo en una URL del front debe gritar, no
    // morir en silencio.
    if (error.config?.silent) return Promise.reject(error);
    const status = error.response?.status;
    const detail = error.response?.data?.detail;
    let mensaje;
    if (!error.response) {
      mensaje = "Error de red: el backend no responde";
    } else if (status >= 500) {
      mensaje = `Error del servidor (${status})${detail ? `: ${detail}` : ""}`;
    } else {
      mensaje = detail || `Error ${status || ""}`.trim();
    }
    window.dispatchEvent(new CustomEvent(API_ERROR_EVENT, {
      detail: { mensaje, status: status ?? "network" },
    }));
    return Promise.reject(error);
  },
);

/** Resuelve `valor` (display o normalizado) al `nombre_normalizado` real
 * de la caja, buscando en `cajas` (lista de {nombre_display, nombre_normalizado}).
 * Si no encuentra, devuelve `valor` tal cual. */
export function cajaToNormalizado(cajas, valor) {
  if (!valor || !cajas?.length) return valor;
  const found = cajas.find(
    (c) => c.nombre_display === valor || c.nombre_normalizado === valor,
  );
  return found?.nombre_normalizado || valor;
}

/** URL absoluta para descargar archivos del backend (download links).
 * Usa la baseURL del cliente para no hardcodear localhost. */
export function urlBackend(path) {
  return `${baseURL}${path.startsWith("/") ? path : `/${path}`}`;
}

export const fmtMoney = (v) => {
  if (v == null || isNaN(v)) return "-";
  return "$" + Number(v).toLocaleString("es-AR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
};

export const fmtNum = (v) => {
  if (v == null || isNaN(v)) return "-";
  return Number(v).toLocaleString("es-AR");
};

export const fmtPct = (v) => {
  if (v == null || isNaN(v)) return "-";
  return Number(v).toFixed(1) + "%";
};

export default api;
