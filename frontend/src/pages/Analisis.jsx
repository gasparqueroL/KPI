import { useEffect, useState } from "react";
import api, { fmtNum } from "../api/client";

export default function Analisis() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [meses, setMeses] = useState(11);
  const [minimoCohorte, setMinimoCohorte] = useState(10);

  async function cargar() {
    setLoading(true);
    try {
      const { data } = await api.get("/api/kpis/comerciales/cohortes", {
        params: { meses_max: meses, minimo_cohorte: minimoCohorte },
      });
      setData(data);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { cargar(); }, []);

  return (
    <>
      <h2>Análisis de cohortes {loading && <span className="spinner" />}</h2>
      <p style={{ color: "#94a3b8", marginTop: -10 }}>
        Cada fila es un grupo de clientes que hicieron su <b>primera compra</b> en ese mes.
        Cada columna muestra qué % de ellos volvió a comprar N meses después.
        Útil para detectar calidad/lealtad de adquisición por época y caída en retención.
      </p>

      <div className="toolbar">
        <label>Meses a mostrar</label>
        <input type="number" min={1} max={24} value={meses} onChange={(e) => setMeses(Number(e.target.value))} style={{ width: 70 }} />
        <label>Mín. clientes por cohorte</label>
        <input type="number" min={1} max={100} value={minimoCohorte} onChange={(e) => setMinimoCohorte(Number(e.target.value))} style={{ width: 70 }} />
        <button className="btn" onClick={cargar}>Aplicar</button>
      </div>

      {data && data.cohortes.length === 0 && (
        <div className="empty">No hay cohortes que cumplan el mínimo configurado.</div>
      )}

      {data && data.cohortes.length > 0 && (
        <div className="panel">
          <h3>Retención por cohorte (% de clientes que volvieron)</h3>
          <div style={{ overflowX: "auto" }}>
            <table className="cohorte-tabla">
              <thead>
                <tr>
                  <th>Mes alta</th>
                  <th className="num">Tamaño</th>
                  {Array.from({ length: meses + 1 }, (_, i) => (
                    <th key={i} className="num" style={{ width: 50 }}>M{i}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.cohortes.map((c) => (
                  <tr key={c.mes_alta}>
                    <td>{c.mes_alta}</td>
                    <td className="num">{fmtNum(c.tamano)}</td>
                    {c.retencion.map((r, i) => (
                      <td key={i} className="num" style={{
                        background: r == null ? "transparent" : colorRetencion(r),
                        color: r == null ? "#475569" : (r > 50 ? "#0f172a" : "#e2e8f0"),
                        fontVariantNumeric: "tabular-nums",
                        fontWeight: r != null && r > 0 ? 600 : 400,
                      }}>
                        {r == null ? "" : (r === 0 ? "0" : `${r.toFixed(0)}%`)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: 12, fontSize: 11, color: "#64748b" }}>
            Escala de color: <span style={{ background: colorRetencion(5), padding: "2px 8px", borderRadius: 3 }}>5%</span>
            {" "}<span style={{ background: colorRetencion(20), padding: "2px 8px", borderRadius: 3 }}>20%</span>
            {" "}<span style={{ background: colorRetencion(40), padding: "2px 8px", borderRadius: 3 }}>40%</span>
            {" "}<span style={{ background: colorRetencion(70), padding: "2px 8px", borderRadius: 3, color: "#0f172a", fontWeight: 600 }}>70%</span>
            {" "}<span style={{ background: colorRetencion(100), padding: "2px 8px", borderRadius: 3, color: "#0f172a", fontWeight: 600 }}>100%</span>
            {" — celdas vacías = mes futuro (todavía no ocurrió)"}
          </div>
        </div>
      )}
    </>
  );
}

/** Escala dark-blue → green según porcentaje de retención. */
function colorRetencion(pct) {
  if (pct == null || pct < 0) return "transparent";
  if (pct === 0) return "#1e293b";
  // 0-100 → opacidad sobre verde
  const intensidad = Math.min(pct / 100, 1);
  // Color base: verde teal
  const r = Math.round(30 + (52 - 30) * intensidad);
  const g = Math.round(50 + (211 - 50) * intensidad);
  const b = Math.round(80 + (153 - 80) * intensidad);
  return `rgb(${r}, ${g}, ${b})`;
}
