import { Link } from "react-router-dom";
import { useAlertas } from "./AlertasContext";
import Icon from "./Icon";

const COLORES = {
  critica: { bg: "#7f1d1d", border: "#dc2626", icon: "🔴" },
  atencion: { bg: "#7c2d12", border: "#f59e0b", icon: "🟡" },
  info: { bg: "#1e3a5f", border: "#60a5fa", icon: "🔵" },
};

// Orden canónico de dominios — usado como tiebreaker cuando dos grupos
// tienen la misma severidad máxima. "comercial" primero porque es donde
// la dueña actúa (clientes, productos), después cobranza (cash pendiente),
// caja (operativo) y al final datos (mantenimiento).
const ORDEN_DOMINIOS = ["comercial", "cobranza", "caja", "datos", "otros"];

const PESO_SEVERIDAD = { critica: 3, atencion: 2, info: 1 };

const LABELS_DOMINIO = {
  comercial: "Comercial",
  cobranza: "Cobranza",
  caja: "Caja",
  datos: "Datos / Sistema",
  otros: "Otros",
};

export default function PanelAlertas() {
  const { alertas, total } = useAlertas();
  if (total === 0) return null;

  // Agrupar por dominio. Default "datos" si una alerta del backend viejo
  // no incluye el campo (defensa contra mismatch de versión). Si llega un
  // dominio fuera del orden conocido (backend agregó "rrhh" sin tocar
  // frontend), va al bucket "otros" + warn — sin desaparecer silenciosamente.
  const grupos = {};
  for (const a of alertas) {
    let dom = a.dominio || "datos";
    if (!ORDEN_DOMINIOS.includes(dom)) {
      console.warn(`[alertas] dominio desconocido "${dom}" en alerta ${a.codigo}`);
      dom = "otros";
    }
    if (!grupos[dom]) grupos[dom] = [];
    grupos[dom].push(a);
  }

  // Reordenar por máxima severidad del grupo (decisión de jurado adversarial:
  // si una crítica cae en un dominio "tarde" del orden canónico, NO la
  // ocultamos abajo del panel — sube al tope). Tiebreaker: orden canónico.
  // Esto preserva la jerarquía de severidad sin perder el contexto de dominio.
  const dominiosVisibles = ORDEN_DOMINIOS
    .filter((d) => grupos[d]?.length > 0)
    .sort((a, b) => {
      const sevA = Math.max(...grupos[a].map((x) => PESO_SEVERIDAD[x.severidad] || 0));
      const sevB = Math.max(...grupos[b].map((x) => PESO_SEVERIDAD[x.severidad] || 0));
      if (sevA !== sevB) return sevB - sevA;
      // Empate: respetar orden canónico (índice más chico primero).
      return ORDEN_DOMINIOS.indexOf(a) - ORDEN_DOMINIOS.indexOf(b);
    });

  return (
    <div className="panel" style={{ borderColor: "#7f1d1d" }}>
      <h3 style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Icon name="warn" size={18} style={{ color: "#f87171" }} label="Atención" />
        Alertas activas ({total})
      </h3>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {dominiosVisibles.map((dom) => (
          <div key={dom}>
            <div style={{
              fontSize: 11, color: "#94a3b8", textTransform: "uppercase",
              letterSpacing: "0.05em", marginBottom: 6, fontWeight: 600,
            }}>
              {LABELS_DOMINIO[dom]} ({grupos[dom].length})
            </div>
            <div style={{ display: "grid", gap: 6 }}>
              {grupos[dom].map((a) => {
                const col = COLORES[a.severidad] || COLORES.info;
                return (
                  <Link
                    key={a.codigo + a.titulo}
                    to={a.link}
                    style={{
                      background: col.bg,
                      borderLeft: `3px solid ${col.border}`,
                      padding: "10px 14px",
                      borderRadius: 6,
                      color: "#f1f5f9",
                      textDecoration: "none",
                      display: "block",
                    }}
                  >
                    <div style={{ fontWeight: 600, fontSize: 14 }}>
                      {col.icon} {a.titulo}
                    </div>
                    {a.detalle && (
                      <div style={{ fontSize: 12, color: "#cbd5e1", marginTop: 4 }}>{a.detalle}</div>
                    )}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
