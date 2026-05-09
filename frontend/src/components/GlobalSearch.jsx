import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client";
import Modal from "./Modal";

/**
 * Modal de búsqueda global activado con Cmd-K (Mac) / Ctrl-K (Win/Linux).
 *
 * - Listener global: ESC adentro del modal lo cierra (manejado por Modal).
 *   Ctrl/Cmd+K en cualquier parte de la app abre/cierra.
 * - Debounce 200ms en el input para no spamear el backend.
 * - Keyboard nav: ↑ ↓ para mover el highlight, Enter para abrir.
 * - Click en resultado → navega + cierra.
 */

const TIPO_LABELS = {
  cliente: "Cliente",
  proveedor: "Proveedor",
  factura: "Factura",
  movimiento: "Movimiento",
};

const TIPO_COLORS = {
  cliente: "#60a5fa",
  proveedor: "#a78bfa",
  factura: "#fbbf24",
  movimiento: "#34d399",
};

export default function GlobalSearch() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [resultados, setResultados] = useState([]);
  const [loading, setLoading] = useState(false);
  const [highlight, setHighlight] = useState(0);

  // Listener global Cmd-K / Ctrl-K.
  // - `e.key?.toLowerCase()`: dead keys / IME pueden devolver `e.key=undefined`.
  // - Saltea inputs activos: si la dueña está tipeando un detalle de movimiento
  //   y aprieta Cmd-K por accidente, NO secuestramos el contexto del form.
  //   El modal se abre sólo si el target NO es un editor de texto.
  useEffect(() => {
    function onKey(e) {
      const k = e.key?.toLowerCase();
      if (!(e.metaKey || e.ctrlKey) || k !== "k") return;
      const t = e.target;
      const enInput = t && (
        t.tagName === "INPUT" ||
        t.tagName === "TEXTAREA" ||
        t.tagName === "SELECT" ||
        t.isContentEditable
      );
      // Excepción: si el modal YA está abierto, permitir cerrarlo aún
      // estando el foco dentro del input del propio modal.
      if (enInput && !open) return;
      e.preventDefault();
      setOpen((prev) => !prev);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Limpiar al cerrar.
  useEffect(() => {
    if (!open) {
      setQ("");
      setResultados([]);
      setHighlight(0);
    }
  }, [open]);

  // Debounce de la query.
  // Stale-response guard: si la dueña tipea "A" → Acme rápido y el fetch
  // de "A" (lento, matchea más rows) resuelve DESPUÉS del de "Acme",
  // pisaría los resultados correctos con los obsoletos. Cada efecto trackea
  // su `requestId` y antes de llamar setResultados verifica que sigue siendo
  // el último — sino, descarta el response. Patrón clásico para search-as-
  // you-type.
  const requestIdRef = useRef(0);
  useEffect(() => {
    if (!open) return;
    const term = q.trim();
    if (!term) {
      setResultados([]);
      return;
    }
    const myRequestId = ++requestIdRef.current;
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const { data } = await api.get("/api/search", {
          params: { q: term },
          // silent: la búsqueda es continua mientras el usuario tipea —
          // un 4xx por query muy corta no debe disparar toast.
          silent: true,
        });
        // Guard: si llegó otro request más nuevo mientras este estaba
        // in-flight, descartamos el response stale.
        if (requestIdRef.current !== myRequestId) return;
        setResultados(data.resultados);
        setHighlight(0);
      } catch {
        if (requestIdRef.current !== myRequestId) return;
        setResultados([]);
      } finally {
        if (requestIdRef.current === myRequestId) {
          setLoading(false);
        }
      }
    }, 200);
    return () => clearTimeout(t);
  }, [q, open]);

  function abrir(r) {
    navigate(r.link);
    setOpen(false);
  }

  function onInputKey(e) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, Math.max(0, resultados.length - 1)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter" && resultados[highlight]) {
      abrir(resultados[highlight]);
    }
  }

  return (
    <Modal
      open={open}
      onClose={() => setOpen(false)}
      title="Buscar"
      width={640}
      hideClose
    >
      <input
        autoFocus
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={onInputKey}
        // maxLength alineado con `Query(max_length=100)` del backend —
        // si la dueña pega 500 chars, no llega un 422 silencioso al server.
        maxLength={100}
        placeholder="Buscá clientes, proveedores, facturas, movimientos..."
        style={{ width: "100%", fontSize: 16, padding: "10px 12px" }}
      />
      <div style={{ marginTop: 12, fontSize: 12, color: "#94a3b8" }}>
        {loading && <span>Buscando...</span>}
        {!loading && q && resultados.length === 0 && <span>Sin resultados.</span>}
        {!loading && !q && <span>Escribí al menos 1 caracter para buscar.</span>}
      </div>

      {resultados.length > 0 && (
        <div style={{ marginTop: 8, maxHeight: 420, overflowY: "auto" }}>
          {resultados.map((r, i) => (
            <ResultadoFila
              key={`${r.tipo}-${r.id}`}
              resultado={r}
              activo={i === highlight}
              onClick={() => abrir(r)}
              onMouseEnter={() => setHighlight(i)}
            />
          ))}
        </div>
      )}

      {/* Footer fijo con shortcuts — siempre visible para que la dueña
          sepa cómo navegar/cerrar el modal aunque haya tipeado y el
          mensaje de "Esc para cerrar" del bloque de arriba haya
          desaparecido al iniciar la búsqueda. */}
      <div style={{
        marginTop: 12, paddingTop: 10, borderTop: "1px solid #334155",
        display: "flex", gap: 14, fontSize: 11, color: "#64748b",
      }}>
        <span><Tecla>↑</Tecla><Tecla>↓</Tecla> moverte</span>
        <span><Tecla>Enter</Tecla> abrir</span>
        <span><Tecla>Esc</Tecla> cerrar</span>
      </div>
    </Modal>
  );
}

function Tecla({ children }) {
  return (
    <kbd style={{
      fontFamily: "monospace",
      padding: "1px 5px",
      background: "#1e293b",
      border: "1px solid #475569",
      borderRadius: 3,
      color: "#cbd5e1",
      fontSize: 10,
      marginRight: 4,
    }}>{children}</kbd>
  );
}

function ResultadoFila({ resultado, activo, onClick, onMouseEnter }) {
  return (
    <div
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      style={{
        padding: "8px 12px",
        borderRadius: 6,
        cursor: "pointer",
        background: activo ? "#334155" : "transparent",
        display: "flex",
        gap: 12,
        alignItems: "center",
      }}
    >
      <span style={{
        fontSize: 10,
        textTransform: "uppercase",
        background: TIPO_COLORS[resultado.tipo] + "22",
        color: TIPO_COLORS[resultado.tipo],
        padding: "2px 6px",
        borderRadius: 4,
        fontWeight: 600,
        minWidth: 70,
        textAlign: "center",
      }}>
        {TIPO_LABELS[resultado.tipo]}
      </span>
      <div style={{ flex: 1, overflow: "hidden" }}>
        <div style={{ color: "#f1f5f9", fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {resultado.label}
        </div>
        {resultado.sub && (
          <div style={{ color: "#94a3b8", fontSize: 11 }}>{resultado.sub}</div>
        )}
      </div>
    </div>
  );
}
