import Icon from "./Icon";

// Constantes exportadas para que los tests assertenten contra ellas en vez
// de hardcodear valores hex. Si en el futuro se cambia la paleta, se cambia
// acá y los tests siguen verdes (mientras la semántica positivo/negativo/
// neutro se mantenga).
export const COLORES_DELTA = {
  positivo: "#34d399",  // verde — mejora vs período anterior
  negativo: "#f87171",  // rojo — caída vs período anterior
  neutro: "#94a3b8",    // gris — sin cambio o sin comparativa
};

/** KpiCard con comparativa vs período anterior. */
export default function KpiCardComp({ label, value, prevValue, formatter, sub, tone }) {
  let delta = null;
  if (prevValue != null && prevValue !== 0) {
    const pct = ((value - prevValue) / Math.abs(prevValue)) * 100;
    delta = pct;
  }
  const iconName = delta == null ? null : delta > 0 ? "trend-up" : delta < 0 ? "trend-down" : "dot";
  const color = delta == null
    ? COLORES_DELTA.neutro
    : delta > 0
      ? COLORES_DELTA.positivo
      : delta < 0
        ? COLORES_DELTA.negativo
        : COLORES_DELTA.neutro;

  return (
    <div className={`kpi-card ${tone || ""}`}>
      <div className="label">{label}</div>
      <div className="value">{formatter ? formatter(value) : value}</div>
      <div className="sub" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <span>{sub}</span>
        {delta != null && (
          <span style={{ color, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 4 }}>
            <Icon name={iconName} size={12} />
            {Math.abs(delta).toFixed(1)}%
          </span>
        )}
      </div>
    </div>
  );
}
