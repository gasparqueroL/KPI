import { useEffect, useState } from "react";
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import api, { fmtMoney, fmtNum, urlBackend } from "../api/client";
import ObjetivoCell from "../components/ObjetivoCell";
import { useToast } from "../components/Toast";

/** Formatea valor según unidad detectada. */
function formatValor(valor, unidad) {
  if (valor == null) return "—";
  if (unidad === "ARS" || unidad === "ARS/empleado") return fmtMoney(valor);
  if (unidad === "%") return `${Number(valor).toFixed(1)}%`;
  if (unidad === "ratio") return Number(valor).toFixed(2);
  if (unidad === "score") return Number(valor).toFixed(1);
  if (unidad === "‰") return `${Number(valor).toFixed(2)}‰`;
  return fmtNum(valor);
}

const STATUS_BADGES = {
  ok: { label: "OK", color: "#34d399", bg: "#064e3b" },
  parcial: { label: "Parcial", color: "#fbbf24", bg: "#78350f" },
  faltan: { label: "Faltan datos", color: "#94a3b8", bg: "#1e293b" },
};

/** Mes actual en YYYY-MM. */
function mesActual() {
  const hoy = new Date();
  return `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, "0")}`;
}

/** Genera lista de últimos 12 meses como ["YYYY-MM", "Mes Año"]. */
function ultimosMeses(n = 12) {
  const out = [];
  const hoy = new Date();
  for (let i = 0; i < n; i++) {
    const d = new Date(hoy.getFullYear(), hoy.getMonth() - i, 1);
    const ym = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const label = d.toLocaleDateString("es-AR", { month: "long", year: "numeric" });
    out.push([ym, label.charAt(0).toUpperCase() + label.slice(1)]);
  }
  return out;
}

export default function KpisManuales() {
  const toast = useToast();
  const [periodo, setPeriodo] = useState(mesActual());
  const [catalogo, setCatalogo] = useState({});
  const [valores, setValores] = useState({});  // {codigo: {valor, nota}}
  // Dirty tracking: solo mandamos al backend los códigos modificados en
  // esta sesión. Sin esto, un toggle accidental en un input vacío podría
  // borrar un valor cargado previamente.
  const [dirty, setDirty] = useState(new Set());
  const [derivados, setDerivados] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [trendCodigo, setTrendCodigo] = useState("rotacion");
  const [trend, setTrend] = useState(null);
  // Bump tras guardar exitoso → re-fetch del trend. Evita disparar 12
  // meses de cómputo cuando solo cambió el dropdown del período.
  const [trendVersion, setTrendVersion] = useState(0);
  const [heatmap, setHeatmap] = useState(null);
  const meses = ultimosMeses(18);

  // Cargar catálogo (estático) una sola vez.
  useEffect(() => {
    api.get("/api/kpis-manuales/catalogo").then((r) => setCatalogo(r.data.areas));
  }, []);

  async function cargar(signal) {
    setLoading(true);
    try {
      const [valRes, derRes] = await Promise.all([
        api.get(`/api/kpis-manuales/${periodo}`, { signal }),
        api.get(`/api/kpis-manuales/${periodo}/derivados`, { signal }),
      ]);
      const map = {};
      for (const v of valRes.data.valores) {
        map[v.codigo] = { valor: v.valor, nota: v.nota };
      }
      setValores(map);
      setDirty(new Set());  // resetear dirty al cambiar período
      setDerivados(derRes.data);
    } catch (e) {
      if (e.name !== "CanceledError" && e.code !== "ERR_CANCELED") throw e;
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const ctrl = new AbortController();
    cargar(ctrl.signal);
    return () => ctrl.abort();
  }, [periodo]);

  // Cargar trend del KPI seleccionado (12 meses). NO depende de `periodo`:
  // el trend es panorámico (12 meses) y no cambia al elegir otro mes en
  // el selector. Se refresca SOLO cuando cambia el código o tras guardar
  // exitosamente (incremento de trendVersion).
  useEffect(() => {
    if (!trendCodigo) return;
    const ctrl = new AbortController();
    api.get(`/api/kpis-manuales/derivados/historico/${trendCodigo}`, {
      params: { meses: 12 }, signal: ctrl.signal,
    })
      .then((r) => setTrend(r.data))
      .catch((e) => {
        if (e.name === "CanceledError" || e.code === "ERR_CANCELED") return;
        setTrend(null);
      });
    return () => ctrl.abort();
  }, [trendCodigo, trendVersion]);

  // Heatmap de cumplimiento — refresca tras guardar/import.
  useEffect(() => {
    const ctrl = new AbortController();
    api.get("/api/kpis-objetivos/heatmap", {
      params: { meses: 6 }, signal: ctrl.signal,
    })
      .then((r) => setHeatmap(r.data))
      .catch((e) => {
        if (e.name === "CanceledError" || e.code === "ERR_CANCELED") return;
        setHeatmap(null);
      });
    return () => ctrl.abort();
  }, [trendVersion]);

  function setValor(codigo, valor, nota) {
    setValores((prev) => ({
      ...prev,
      [codigo]: {
        valor: valor === "" ? null : Number(valor),
        nota: nota !== undefined ? nota : prev[codigo]?.nota,
      },
    }));
    setDirty((prev) => {
      const next = new Set(prev);
      next.add(codigo);
      return next;
    });
  }

  async function actualizarObjetivo(codigo, valor) {
    try {
      if (valor === null || valor === undefined) {
        // Si no había objetivo previo, no llamamos DELETE — evita 404
        // espurio que dispara toast de error sin razón.
        const tieneObjetivo = derivados?.kpis?.find(
          (k) => k.codigo === codigo,
        )?.objetivo != null;
        if (!tieneObjetivo) return;
        await api.delete(`/api/kpis-objetivos/${codigo}`);
      } else {
        await api.put(`/api/kpis-objetivos/${codigo}`, {
          valor_objetivo: valor,
        });
      }
      setTrendVersion((v) => v + 1);  // refresca heatmap
      cargar();  // refresca derivados con el nuevo objetivo
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error al guardar objetivo", "error");
    }
  }

  async function importarCsv(file) {
    const fd = new FormData();
    fd.append("file", file);
    setSaving(true);
    try {
      const { data } = await api.post("/api/kpis-manuales/import-csv", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const msg = `${data.insertados} insertados, ${data.actualizados} actualizados`;
      const tipo = data.errores?.length > 0 ? "info" : "success";
      toast.push(msg + (data.errores?.length ? ` · ${data.errores.length} errores` : ""), tipo);
      if (data.errores?.length > 0) {
        // Loguear errores para que la dueña los vea en la consola si quiere
        console.warn("Errores en import CSV:", data.errores);
      }
      setTrendVersion((v) => v + 1);
      cargar();
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error en import CSV", "error");
    } finally {
      setSaving(false);
    }
  }

  async function importarObjetivosCsv(file) {
    const fd = new FormData();
    fd.append("file", file);
    setSaving(true);
    try {
      const { data } = await api.post("/api/kpis-objetivos/import-csv", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const msg = `${data.insertados} insertados, ${data.actualizados} actualizados`;
      const tipo = data.errores?.length > 0 ? "info" : "success";
      toast.push("Objetivos: " + msg + (data.errores?.length ? ` · ${data.errores.length} errores` : ""), tipo);
      if (data.errores?.length > 0) console.warn("Errores en import objetivos:", data.errores);
      setTrendVersion((v) => v + 1);  // refresca heatmap
      cargar();
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error en import de objetivos", "error");
    } finally {
      setSaving(false);
    }
  }

  async function guardar() {
    if (dirty.size === 0) {
      toast.push("Nada que guardar", "info");
      return;
    }
    setSaving(true);
    try {
      // Solo enviar los códigos modificados en esta sesión. Si un input
      // se vació explícitamente (valor=null), el backend lo borra.
      const entries = [...dirty].map((codigo) => {
        const v = valores[codigo] || { valor: null, nota: null };
        return { codigo, valor: v.valor, nota: v.nota || null };
      });
      const { data } = await api.put(`/api/kpis-manuales/${periodo}`, {
        valores: entries,
      });
      toast.push(`Guardado: ${data.upserted} valores (${data.deleted} borrados)`, "success");
      setDirty(new Set());
      setTrendVersion((v) => v + 1);  // refrescar trend chart con datos nuevos
      cargar();  // refrescar derivados del mes actual
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error al guardar", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <h2>KPIs manuales {loading && <span className="spinner" />}</h2>
      <p style={{ color: "#94a3b8", marginTop: -10 }}>
        Cargá mensualmente los datos que no vienen en los CSVs (balance contable,
        empleados, marketing, encuestas, IT). Los KPIs derivados (ROI, ROA, liquidez,
        rotación, CAC, etc.) se computan automáticamente al guardar.
      </p>

      <div className="toolbar">
        <label>Período</label>
        <select value={periodo} onChange={(e) => setPeriodo(e.target.value)}>
          {meses.map(([ym, label]) => (
            <option key={ym} value={ym}>{label}</option>
          ))}
        </select>
        <button className="btn" disabled={saving || dirty.size === 0} onClick={guardar}>
          {saving ? <span className="spinner" /> : `Guardar${dirty.size > 0 ? ` (${dirty.size})` : ""}`}
        </button>
        {dirty.size > 0 && (
          <span style={{ color: "#fbbf24", fontSize: 12 }}>
            {dirty.size} valor{dirty.size === 1 ? "" : "es"} modificado{dirty.size === 1 ? "" : "s"} sin guardar
          </span>
        )}
        <span style={{ flex: 1 }} />
        <label
          className="btn-ghost btn"
          style={{ cursor: "pointer", fontSize: 12 }}
          title="Subir CSV con varios meses/códigos a la vez"
        >
          Importar CSV
          <input
            type="file"
            accept=".csv,text/csv"
            style={{ display: "none" }}
            disabled={saving}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) importarCsv(f);
              e.target.value = "";  // permite re-subir el mismo archivo
            }}
          />
        </label>
        <a
          className="btn-ghost btn"
          href={urlBackend("/api/kpis-manuales/template-csv")}
          download
          title="Descargar template CSV con todos los códigos válidos"
          style={{ fontSize: 12 }}
        >
          Template
        </a>
        <span style={{ width: 1, height: 20, background: "#334155", marginLeft: 8 }} />
        <label
          className="btn-ghost btn"
          style={{ cursor: "pointer", fontSize: 12 }}
          title="Subir CSV con objetivos de KPIs (codigo,valor_objetivo)"
        >
          Importar objetivos
          <input
            type="file"
            accept=".csv,text/csv"
            style={{ display: "none" }}
            disabled={saving}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) importarObjetivosCsv(f);
              e.target.value = "";
            }}
          />
        </label>
        <a
          className="btn-ghost btn"
          href={urlBackend("/api/kpis-objetivos/template-csv")}
          download
          title="Template CSV de objetivos"
          style={{ fontSize: 12 }}
        >
          Template obj.
        </a>
      </div>

      {derivados && (
        <div className="kpi-grid">
          <div className="kpi-card green">
            <div className="label">KPIs OK</div>
            <div className="value">{derivados.resumen.ok}</div>
          </div>
          <div className="kpi-card amber">
            <div className="label">Parciales</div>
            <div className="value">{derivados.resumen.parcial}</div>
          </div>
          <div className="kpi-card muted">
            <div className="label">Faltan datos</div>
            <div className="value">{derivados.resumen.faltan}</div>
            <div className="sub">Cargá los inputs abajo</div>
          </div>
          <div className="kpi-card">
            <div className="label">Total derivados</div>
            <div className="value">{derivados.resumen.total}</div>
          </div>
        </div>
      )}

      {/* Forms de carga por área */}
      <div className="panel">
        <h3>Datos del período {periodo}</h3>
        <p style={{ color: "#94a3b8", fontSize: 12, marginTop: -6 }}>
          Los campos vacíos no afectan KPIs (siguen como "faltan datos").
          Para borrar un valor cargado, vaciá el input y guardá.
        </p>
        {Object.entries(catalogo).map(([area, items]) => (
          <details key={area} open style={{ marginBottom: 16 }}>
            <summary style={{
              cursor: "pointer", padding: "8px 12px",
              background: "#1e293b", borderRadius: 4,
              fontWeight: 600,
            }}>
              {area} <span style={{ color: "#94a3b8", fontWeight: 400 }}>
                ({items.length} datos)
              </span>
            </summary>
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
              gap: 12, marginTop: 12,
            }}>
              {items.map((c) => {
                const v = valores[c.codigo];
                const cargado = v && v.valor != null;
                return (
                  <div key={c.codigo} style={{
                    padding: 10,
                    background: cargado ? "#0f172a" : "#0f172aaa",
                    border: `1px solid ${cargado ? "#334155" : "#1e293b"}`,
                    borderRadius: 6,
                  }}>
                    <label style={{ fontSize: 12, color: "#94a3b8", display: "block", marginBottom: 4 }}>
                      {c.label}
                      <span style={{ color: "#475569", marginLeft: 6, fontSize: 11 }}>
                        ({c.unidad})
                      </span>
                    </label>
                    <input
                      type="number"
                      step="any"
                      value={v?.valor ?? ""}
                      onChange={(e) => setValor(c.codigo, e.target.value)}
                      placeholder="—"
                      style={{ width: "100%", textAlign: "right" }}
                    />
                    {c.descripcion && (
                      <div style={{ fontSize: 10, color: "#64748b", marginTop: 4 }}>
                        {c.descripcion}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </details>
        ))}
      </div>

      {/* Heatmap de cumplimiento de objetivos */}
      {heatmap && heatmap.kpis.length > 0 && (
        <div className="panel">
          <h3>Cumplimiento de objetivos (últimos 6 meses)</h3>
          <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 8 }}>
            Verde = cumple objetivo · Rojo = no cumple · Gris = sin valor cargado.
            Click en celda para detalles.
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ tableLayout: "fixed", width: "100%" }}>
              <thead>
                <tr>
                  <th style={{ width: 220, textAlign: "left" }}>KPI</th>
                  {heatmap.periodos.map((p) => (
                    <th key={p} style={{ fontSize: 10, fontWeight: 400, color: "#94a3b8" }}>
                      {p.slice(5)}/{p.slice(2, 4)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {heatmap.kpis.map((k) => (
                  <tr key={k.codigo}>
                    <td style={{ fontSize: 12, padding: "4px 8px" }}>
                      {k.label}
                      {k.huerfano && (
                        <span style={{ color: "#fbbf24", marginLeft: 6, fontSize: 10 }}>
                          (huérfano)
                        </span>
                      )}
                    </td>
                    {k.celdas.map((c) => {
                      const bg = c.cumple === true ? "#064e3b"
                        : c.cumple === false ? "#7f1d1d"
                        : "#1e293b";
                      const text = c.cumple === true ? "#34d399"
                        : c.cumple === false ? "#fca5a5"
                        : "#475569";
                      const op = k.mejor_si === "bajar" ? "≤" : "≥";
                      const titulo = c.valor != null
                        ? `${c.periodo}: ${formatValor(c.valor, k.unidad)} (objetivo ${op} ${c.objetivo})`
                        : `${c.periodo}: sin valor`;
                      return (
                        <td
                          key={c.periodo}
                          style={{
                            background: bg, color: text, textAlign: "center",
                            fontSize: 10, padding: "6px 4px",
                            border: "1px solid #0f172a",
                          }}
                          title={titulo}
                        >
                          {c.valor != null ? formatValor(c.valor, k.unidad) : "—"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Trend chart de un KPI a elección */}
      {derivados && (
        <div className="panel">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <h3 style={{ margin: 0 }}>Evolución (últimos 12 meses)</h3>
            <select value={trendCodigo} onChange={(e) => setTrendCodigo(e.target.value)}>
              {derivados.kpis.map((k) => (
                <option key={k.codigo} value={k.codigo}>{k.label}</option>
              ))}
            </select>
          </div>
          {trend && trend.puntos.length > 0 && (() => {
            // Objetivo del KPI seleccionado: línea de referencia horizontal.
            // Mostramos solo si el KPI tiene objetivo cargado en el mes
            // actual (lo leemos de `derivados` que está en sync).
            const kpiActual = derivados?.kpis?.find((k) => k.codigo === trendCodigo);
            const objetivoLinea = kpiActual?.objetivo ?? null;
            return (
              <>
                <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 8 }}>
                  Puntos sin valor (status="faltan") aparecen como huecos en la línea.
                  {objetivoLinea != null && (
                    <span style={{ marginLeft: 8, color: "#fbbf24" }}>
                      · Línea ámbar punteada = objetivo ({kpiActual.mejor_si === "bajar" ? "≤" : "≥"} {objetivoLinea})
                    </span>
                  )}
                </div>
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={trend.puntos} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="periodo" stroke="#94a3b8" fontSize={11} />
                    <YAxis stroke="#94a3b8" fontSize={11} />
                    <Tooltip
                      contentStyle={{ background: "#0f172a", border: "1px solid #334155" }}
                      formatter={(v) => formatValor(v, trend.unidad)}
                    />
                    {objetivoLinea != null && (
                      <ReferenceLine
                        y={objetivoLinea}
                        stroke="#fbbf24"
                        strokeDasharray="4 2"
                        strokeWidth={1.5}
                        label={{ value: "obj", position: "right", fill: "#fbbf24", fontSize: 11 }}
                      />
                    )}
                    <Line
                      type="monotone"
                      dataKey="valor"
                      stroke="#60a5fa"
                      strokeWidth={2}
                      dot={{ r: 3, fill: "#60a5fa" }}
                      connectNulls={false}
                      name={trend.label}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </>
            );
          })()}
        </div>
      )}

      {/* KPIs derivados */}
      {derivados && (
        <div className="panel">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <h3 style={{ margin: 0 }}>KPIs derivados de {derivados.periodo}</h3>
            <a
              className="btn-ghost btn"
              href={urlBackend(`/api/kpis-manuales/${derivados.periodo}/derivados.csv`)}
              download
              title="Descargar CSV con todos los KPIs derivados de este mes (incluye objetivos y comparativa)"
              style={{ fontSize: 12 }}
            >
              Descargar CSV
            </a>
          </div>
          {derivados.comparativa_disponible === false && (
            <div style={{ color: "#fbbf24", fontSize: 12, marginTop: -6, marginBottom: 8 }}>
              Sin datos del año anterior cargados — la columna "Δ %" aparece vacía.
              {' '}Cargá valores en {(() => {
                const [y, m] = derivados.periodo.split("-");
                return `${parseInt(y) - 1}-${m}`;
              })()} para ver comparativa interanual.
            </div>
          )}
          <table>
            <thead>
              <tr>
                <th style={{ width: 130 }}>Área</th>
                <th>KPI</th>
                <th className="num" style={{ width: 140 }}>Valor</th>
                <th className="num" style={{ width: 130 }}>Hace 1 año</th>
                <th className="num" style={{ width: 90 }}>Δ %</th>
                <th className="num" style={{ width: 130 }}>Objetivo</th>
                <th style={{ width: 100 }}>Estado</th>
                <th>Fórmula / nota</th>
              </tr>
            </thead>
            <tbody>
              {derivados.kpis.map((k) => {
                const b = STATUS_BADGES[k.status];
                // Color del delta: verde si mejora. `mejor_si` viene del
                // backend (single source of truth) — si dice "bajar",
                // entonces delta negativo = verde.
                const esMenosEsMejor = k.mejor_si === "bajar";
                const subir = esMenosEsMejor ? "#fca5a5" : "#86efac";
                const bajar = esMenosEsMejor ? "#86efac" : "#fca5a5";
                const colorDelta = k.delta_pct == null
                  ? "#64748b"
                  : k.delta_pct > 0 ? subir
                  : k.delta_pct < 0 ? bajar
                  : "#94a3b8";
                return (
                  <tr key={k.codigo}>
                    <td style={{ color: "#94a3b8", fontSize: 12 }}>{k.area}</td>
                    <td>{k.label}</td>
                    <td className="num">{formatValor(k.valor, k.unidad)}</td>
                    <td className="num" style={{ color: "#94a3b8", fontSize: 12 }}>
                      {k.valor_anterior != null ? formatValor(k.valor_anterior, k.unidad) : "—"}
                    </td>
                    <td className="num" style={{ color: colorDelta, fontSize: 12, fontWeight: 500 }}>
                      {k.delta_pct == null
                        ? "—"
                        : `${k.delta_pct >= 0 ? "+" : ""}${k.delta_pct.toFixed(1)}%`}
                    </td>
                    <td className="num" style={{ fontSize: 12 }}>
                      <ObjetivoCell
                        kpi={k}
                        onChange={(nuevoObj) => actualizarObjetivo(k.codigo, nuevoObj)}
                      />
                    </td>
                    <td>
                      <span className="badge" style={{
                        background: b.bg, color: b.color,
                        border: `1px solid ${b.color}40`,
                      }}>{b.label}</span>
                    </td>
                    <td style={{ fontSize: 11, color: "#94a3b8" }}>
                      {k.formula}
                      {k.falta && (
                        <div style={{ color: "#fbbf24", marginTop: 2 }}>
                          Falta: <code>{k.falta}</code>
                        </div>
                      )}
                      {k.nota && (
                        <div style={{ color: "#64748b", marginTop: 2 }}>
                          {k.nota}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}


