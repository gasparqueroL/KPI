// "en-CA" devuelve YYYY-MM-DD interpretado en zona local (no UTC). Esto
// importa para Argentina (UTC-3): un Date construido con (year, month, day)
// es local, y `toISOString()` lo convertía a UTC, restando 1 día si la hora
// local era ≥ 21:00. Acá nos importa la fecha local del usuario, no UTC.
function fmtIso(d) {
  return d.toLocaleDateString("en-CA");
}

// Parser local de YYYY-MM-DD. `new Date("2026-04-08")` parsea como UTC
// midnight (spec ES6) — combinado con fmtIso (local) genera off-by-one
// en TZ negativas: en Argentina UTC-3, UTC midnight April 8 = local April 7
// 21:00, y fmtIso devuelve "2026-04-07". Bug real: las comparaciones del
// dashboard quedaban desplazadas 1 día. Fix: parsing local consistente.
//
// Validación defensiva: si el caller pasa un string en formato inesperado
// (ISO con time, otra delimitación, etc.), devolvemos null en vez de
// `Invalid Date`. Sin esto, un `"2026-04-08T10:00"` produciría
// `Number("08T10:00") === NaN` → `Date(2026, 3, NaN)` → "Invalid Date" en
// params del request al backend. Fail-fast vía null > silent corruption.
function parseIsoLocal(iso) {
  if (!iso || typeof iso !== "string") return null;
  const partes = iso.split("-");
  if (partes.length !== 3) return null;
  const [y, m, d] = partes.map(Number);
  if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) return null;
  return new Date(y, m - 1, d);
}

export const PRESETS = [
  {
    label: "Este mes",
    calc: () => {
      const n = new Date();
      const desde = new Date(n.getFullYear(), n.getMonth(), 1);
      return { desde: fmtIso(desde), hasta: fmtIso(n) };
    },
  },
  {
    label: "Mes pasado",
    calc: () => {
      const n = new Date();
      const desde = new Date(n.getFullYear(), n.getMonth() - 1, 1);
      const hasta = new Date(n.getFullYear(), n.getMonth(), 0);
      return { desde: fmtIso(desde), hasta: fmtIso(hasta) };
    },
  },
  {
    label: "Últimos 3 meses",
    calc: () => {
      const n = new Date();
      const desde = new Date(n.getFullYear(), n.getMonth() - 3, n.getDate());
      return { desde: fmtIso(desde), hasta: fmtIso(n) };
    },
  },
  {
    label: "YTD",
    calc: () => {
      const n = new Date();
      const desde = new Date(n.getFullYear(), 0, 1);
      return { desde: fmtIso(desde), hasta: fmtIso(n) };
    },
  },
  {
    label: "Año pasado",
    calc: () => {
      const n = new Date();
      return {
        desde: `${n.getFullYear() - 1}-01-01`,
        hasta: `${n.getFullYear() - 1}-12-31`,
      };
    },
  },
  {
    label: "Últimos 12m",
    calc: () => {
      const n = new Date();
      const desde = new Date(n.getFullYear() - 1, n.getMonth(), n.getDate());
      return { desde: fmtIso(desde), hasta: fmtIso(n) };
    },
  },
];

/** Calcula el período inmediatamente anterior de igual largo. */
export function periodoAnterior(desde, hasta) {
  if (!desde || !hasta) return { desde: "", hasta: "" };
  const d = parseIsoLocal(desde);
  const h = parseIsoLocal(hasta);
  // parseIsoLocal devuelve null si el input no es YYYY-MM-DD canónico.
  if (!d || !h) return { desde: "", hasta: "" };
  const dias = Math.round((h - d) / 86400000) + 1;
  const hastaPrev = new Date(d.getTime() - 86400000);
  const desdePrev = new Date(hastaPrev.getTime() - (dias - 1) * 86400000);
  return { desde: fmtIso(desdePrev), hasta: fmtIso(hastaPrev) };
}

export default function PeriodPresets({ setDesde, setHasta, onApply }) {
  return (
    <>
      {PRESETS.map((p) => (
        <button
          key={p.label}
          className="btn-ghost btn"
          onClick={() => {
            const { desde, hasta } = p.calc();
            setDesde(desde);
            setHasta(hasta);
            // Pasamos los valores NUEVOS directo a onApply — sino el caller
            // recibe el closure viejo de cargar() con desde/hasta previos
            // (React no flushea el state antes que setTimeout dispare).
            // Era bug real: dueña apretaba "Mes pasado", cargar() corría
            // con el rango anterior y los KPIs no actualizaban.
            if (onApply) onApply(desde, hasta);
          }}
        >
          {p.label}
        </button>
      ))}
    </>
  );
}
