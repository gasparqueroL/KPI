import { useRef, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAlertas } from "./AlertasContext";

/** Atajo de búsqueda según OS — Mac usa ⌘, Windows/Linux usa Ctrl.
 * `userAgent` es más confiable que `navigator.platform` (deprecado). */
function shortcutBuscar() {
  if (typeof navigator === "undefined") return "Ctrl+K";
  return /Mac|iPhone|iPad/i.test(navigator.userAgent) ? "⌘K" : "Ctrl+K";
}

function Badge({ count, kind }) {
  if (!count) return null;
  const colors = {
    critica: { bg: "#dc2626", color: "#fff" },
    atencion: { bg: "#f59e0b", color: "#0f172a" },
  };
  const c = colors[kind] || { bg: "#475569", color: "#fff" };
  return (
    <span style={{
      background: c.bg, color: c.color, fontSize: 10, fontWeight: 700,
      padding: "1px 6px", borderRadius: 999, marginLeft: 6,
    }}>{count}</span>
  );
}

export default function Layout() {
  const { criticas, atencion, alertas } = useAlertas();
  const [abierto, setAbierto] = useState(false);
  const overlayMouseDownRef = useRef(false);
  const casosCnt = alertas.find((a) => a.codigo === "casos_pendientes")?.valor || 0;
  const cajaCnt = alertas.find((a) => a.codigo === "caja_saldo_negativo")?.valor || 0;
  const configCnt = alertas.find((a) => a.codigo === "categorias_sin_familia")?.valor || 0;

  // Cerrar la sidebar al cambiar de ruta (más confiable que onClick global
  // sobre el <nav>, que se puede romper si se agregan botones sin link).
  function cerrarSidebar() {
    setAbierto(false);
  }

  return (
    <div className="app">
      <button
        className="sidebar-toggle"
        aria-label={abierto ? "Cerrar menú" : "Abrir menú"}
        aria-expanded={abierto}
        onClick={() => setAbierto(!abierto)}
      >
        {abierto ? (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        ) : (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        )}
      </button>
      <aside className={`sidebar ${abierto ? "abierto" : ""}`}>
        <h1>KPI Dashboard</h1>
        <div style={{
          margin: "0 20px 16px",
          padding: "8px 10px",
          background: "#0f172a",
          border: "1px solid #334155",
          borderRadius: 6,
          fontSize: 11,
          color: "#94a3b8",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}>
          <span>Buscar</span>
          <kbd style={{
            fontFamily: "monospace",
            fontSize: 10,
            padding: "2px 6px",
            background: "#1e293b",
            border: "1px solid #475569",
            borderRadius: 3,
            color: "#cbd5e1",
          }}>{shortcutBuscar()}</kbd>
        </div>
        <nav onClick={(e) => { if (e.target.closest("a")) cerrarSidebar(); }}>
          {/* Análisis: vistas de lectura primarias. Cuentas Corrientes y
              Proveedores entran acá: el dueño las consulta a diario para
              ver saldos y aging — las escrituras (aplicar pago, anular
              factura) son secundarias al uso principal. */}
          <div className="nav-group">Análisis</div>
          <NavLink to="/direccion">
            Dirección
            <Badge count={criticas} kind="critica" />
            <Badge count={atencion} kind="atencion" />
          </NavLink>
          <NavLink to="/comercial">Comercial</NavLink>
          <NavLink to="/caja">
            Caja / Finanzas
            <Badge count={cajaCnt} kind="critica" />
          </NavLink>
          <NavLink to="/cuentas-corrientes">Cuentas corrientes</NavLink>
          <NavLink to="/proveedores">Proveedores</NavLink>
          <NavLink to="/analisis">Análisis (cohortes)</NavLink>

          {/* Operación: captura diaria — formularios que el dueño completa. */}
          <div className="nav-group">Operación</div>
          <NavLink to="/caja-diaria">Caja diaria</NavLink>
          <NavLink to="/conciliacion">Conciliación</NavLink>
          <NavLink to="/casos">
            Casos a revisar
            <Badge count={casosCnt} kind="atencion" />
          </NavLink>

          {/* Admin: cargas masivas y configuración del sistema. */}
          <div className="nav-group">Admin</div>
          <NavLink to="/importar">Importar CSV</NavLink>
          <NavLink to="/config">
            Configuración
            <Badge count={configCnt} />
          </NavLink>
          <NavLink to="/indice">Índice de KPIs</NavLink>
          <NavLink to="/kpis-manuales">Carga manual mensual</NavLink>
        </nav>
      </aside>
      {abierto && (
        <div
          className="sidebar-overlay"
          onMouseDown={(e) => { overlayMouseDownRef.current = e.target === e.currentTarget; }}
          onMouseUp={(e) => {
            if (overlayMouseDownRef.current && e.target === e.currentTarget) {
              cerrarSidebar();
            }
            overlayMouseDownRef.current = false;
          }}
        />
      )}
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
