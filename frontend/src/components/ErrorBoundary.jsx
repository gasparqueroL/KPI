import { Component } from "react";

/**
 * Captura errores de render de los hijos para que un crash de UI
 * (ej: null inesperado en un chart, dataset raro) no deje a la dueña
 * con pantalla blanca sin recuperación.
 *
 * - En dev: muestra stack + mensaje crudo (útil para diagnosticar).
 * - En prod: mensaje amable + botón "Recargar" / "Ir al inicio".
 * - Reset automático con prop `resetKey` (típicamente `location.pathname`):
 *   al cambiar de ruta, se descarta el error y se intenta renderizar
 *   los nuevos hijos. Sin esto, la dueña quedaría atrapada en el error
 *   incluso al hacer click en otro link del menú.
 *
 * No reemplaza al toast del interceptor de axios — esto es para errores
 * de RENDER (sincrónicos), no de fetch.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary] crash de render:", error, info);
  }

  componentDidUpdate(prevProps) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;
    return <ErrorFallback error={this.state.error} onRetry={() => this.setState({ error: null })} />;
  }
}

function ErrorFallback({ error, onRetry }) {
  const enDev = import.meta.env?.DEV;
  return (
    <div
      role="alert"
      style={{
        padding: 32,
        margin: "40px auto",
        maxWidth: 720,
        background: "#1e293b",
        border: "1px solid #475569",
        borderRadius: 12,
        textAlign: "center",
      }}
    >
      <div style={{ fontSize: 36, marginBottom: 8 }}>⚠️</div>
      <h2 style={{ marginTop: 0, color: "#f1f5f9" }}>Algo salió mal en esta vista</h2>
      <p style={{ color: "#cbd5e1" }}>
        El error fue capturado y no afectó tus datos. Probá recargar la página o
        volver al inicio. Si vuelve a pasar, avisanos.
      </p>
      {enDev && (
        <details style={{ textAlign: "left", marginTop: 16, color: "#fbbf24", fontSize: 12 }}>
          <summary style={{ cursor: "pointer" }}>Detalle técnico (solo dev)</summary>
          <pre style={{
            marginTop: 8, padding: 12, background: "#0f172a", borderRadius: 6,
            overflow: "auto", fontFamily: "monospace", fontSize: 11,
          }}>
            {error?.message}
            {"\n\n"}
            {error?.stack}
          </pre>
        </details>
      )}
      <div style={{ display: "flex", gap: 12, justifyContent: "center", marginTop: 20 }}>
        <button className="btn" onClick={onRetry}>Reintentar</button>
        <button
          className="btn-ghost btn"
          onClick={() => { window.location.href = "/"; }}
        >
          Ir al inicio
        </button>
        <button
          className="btn-ghost btn"
          onClick={() => window.location.reload()}
        >
          Recargar página
        </button>
      </div>
    </div>
  );
}
