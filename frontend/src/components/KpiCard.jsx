export default function KpiCard({ label, value, sub, tone }) {
  // Bug histórico: `{sub && <div>}` con `sub=0` (falsy) retorna `0` y
  // React lo renderiza como TEXTO sin el wrapper `.sub` — asimétrico
  // con string vacío (no renderiza) y `"0"` (renderiza con div).
  // Fix: chequear null/undefined/"" explícitamente. `sub=0` ahora
  // renderiza como `<div className="sub">0</div>` (mismo path que cualquier
  // valor).
  const tieneSub = sub != null && sub !== "";
  return (
    <div className={`kpi-card ${tone || ""}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {tieneSub && <div className="sub">{sub}</div>}
    </div>
  );
}
