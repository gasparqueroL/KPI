/**
 * Iconos SVG reutilizables. Reemplazan caracteres unicode (▲▼⇅↑↓⚠⬇✓✗←→)
 * que renderizan inconsistente entre OS / fuentes y a veces caen al fallback
 * "tofu" en Windows con fuentes monospaceas.
 *
 * Uso: <Icon name="check" size={14} />
 * Toman currentColor por default, así heredan color del padre.
 */

const PATHS = {
  // Direcciones / sort
  "arrow-up":   "M12 19V5M5 12l7-7 7 7",
  "arrow-down": "M12 5v14M5 12l7 7 7-7",
  "arrow-left":  "M19 12H5M12 19l-7-7 7-7",
  "arrow-right": "M5 12h14M12 5l7 7-7 7",
  "sort":     "M8 9l4-5 4 5M8 15l4 5 4-5", // doble flecha (sin sort activo)

  // Estado
  "check":  "M5 12l5 5L20 7",
  "x":      "M6 6l12 12M18 6L6 18",
  "warn":   "M12 2L1 22h22L12 2zM12 9v6M12 18h.01", // triángulo + !

  // Trend
  "trend-up":   "M3 17l6-6 4 4 8-8M21 7h-5M21 7v5",
  "trend-down": "M3 7l6 6 4-4 8 8M21 17h-5M21 17v-5",
  "dot":        "M12 12h.01",

  // Misc
  "download":   "M12 3v12M7 10l5 5 5-5M5 21h14",
};

export default function Icon({ name, size = 14, strokeWidth = 2, style, label }) {
  const d = PATHS[name];
  if (!d) return null;
  // Cuando el icono es la **única** señal de estado (✓/✗ de un resultado,
  // ⚠ de error en una fila), pasar `label` lo hace accesible: el screen
  // reader lee el <title> en lugar de saltarlo. Sin label, queda como
  // decorativo (aria-hidden), que es lo correcto para sort/trend/chevrons.
  const accessible = !!label;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ display: "inline-block", verticalAlign: "-2px", ...style }}
      role={accessible ? "img" : undefined}
      aria-hidden={accessible ? undefined : "true"}
      aria-label={accessible ? label : undefined}
    >
      {accessible && <title>{label}</title>}
      <path d={d} />
    </svg>
  );
}
