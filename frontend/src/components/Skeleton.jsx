/**
 * Placeholder visual mientras carga el contenido. La meta es mimicar el
 * layout final lo más posible para reducir layout shift al llegar los datos.
 *
 * Uso típico:
 *   <Skeleton width="100%" height={20} />
 *   <Skeleton width={120} height={32} style={{ marginRight: 8 }} />
 */
export default function Skeleton({ width = "100%", height = 16, style }) {
  return (
    <div
      className="skeleton"
      style={{ width, height, ...style }}
      aria-hidden="true"
    />
  );
}

/**
 * Helper: imita una `kpi-card` mientras carga. Usado en Direccion/Comercial
 * cuando todavía no hay datos pero ya queremos pintar la grilla con el
 * número correcto de cards.
 *
 * NO incluye `aria-busy` por sí mismo — el wrapper natural es
 * `SkeletonKpiGrid` que lo lleva en el padre. Si en el futuro alguien usa
 * `SkeletonKpiCard` standalone (fuera del Grid), envolverlo con un div
 * con `aria-busy="true"` o usar un wrapper apropiado.
 */
export function SkeletonKpiCard() {
  return (
    <div className="kpi-card" style={{ minHeight: 90 }}>
      <Skeleton width="55%" height={11} style={{ marginBottom: 12 }} />
      <Skeleton width="75%" height={22} style={{ marginBottom: 8 }} />
      <Skeleton width="40%" height={10} />
    </div>
  );
}

/**
 * Helper: grid de N skeleton kpi-cards.
 */
export function SkeletonKpiGrid({ cards = 6 }) {
  return (
    <div className="kpi-grid" aria-busy="true">
      {Array.from({ length: cards }).map((_, i) => <SkeletonKpiCard key={i} />)}
    </div>
  );
}

/**
 * Helper: panel con título + N filas skeleton (para tablas que cargan).
 */
export function SkeletonPanel({ rows = 4 }) {
  return (
    <div className="panel" aria-busy="true">
      <Skeleton width={180} height={18} style={{ marginBottom: 14 }} />
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} width="100%" height={14} style={{ marginBottom: 8 }} />
      ))}
    </div>
  );
}
