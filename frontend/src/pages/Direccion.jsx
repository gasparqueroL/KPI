import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import api, { fmtMoney, fmtNum, fmtPct, urlBackend } from "../api/client";
import DateRange from "../components/DateRange";
import Icon from "../components/Icon";
import KpiCardComp from "../components/KpiCardComp";
import Modal from "../components/Modal";
import PanelAlertas from "../components/PanelAlertas";
import PeriodPresets from "../components/PeriodPresets";
import Skeleton, { SkeletonKpiGrid, SkeletonPanel } from "../components/Skeleton";
import { useStoredState } from "../hooks/useStoredState";

/** Genera lista de los últimos 12 meses como ["YYYY-MM", "Mes Año"]. */
function ultimosMeses(n = 12) {
  const out = [];
  const hoy = new Date();
  for (let i = 1; i <= n; i++) {
    const d = new Date(hoy.getFullYear(), hoy.getMonth() - i, 1);
    const ym = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const label = d.toLocaleDateString("es-AR", { month: "long", year: "numeric" });
    out.push([ym, label.charAt(0).toUpperCase() + label.slice(1)]);
  }
  return out;
}

const COLORS = ["#60a5fa", "#34d399", "#fbbf24", "#f87171", "#a78bfa", "#fb923c", "#22d3ee", "#f472b6", "#94a3b8", "#84cc16"];

/** Color escalado para %s de concentración: verde si bajo, ámbar si medio,
 * rojo si alto. Los umbrales son por métrica (top1 vs top3 vs top5).
 * Centralizados en backend (`kpis/comerciales._umbrales_concentracion`)
 * para que la card y la alerta nunca se desincronicen. */
function tonoConc(pct, umbralAtencion, umbralCritico) {
  if (pct >= umbralCritico) return "#f87171";
  if (pct >= umbralAtencion) return "#fbbf24";
  return "#34d399";
}

export default function Direccion() {
  const [desde, setDesde] = useStoredState("direccion:desde", "");
  const [hasta, setHasta] = useStoredState("direccion:hasta", "");
  const [data, setData] = useState(null);
  const [conc, setConc] = useState(null);
  const [proy, setProy] = useState(null);
  const [margenOp, setMargenOp] = useState(null);
  const [margenSerie, setMargenSerie] = useState(null);
  const [objResumen, setObjResumen] = useState(null);
  const [puntoEquilibrio, setPuntoEquilibrio] = useState(null);
  const [crecimiento, setCrecimiento] = useState(null);
  const [loading, setLoading] = useState(false);
  const meses = ultimosMeses(12);
  const [mesReporte, setMesReporte] = useState(meses[0][0]);
  // Drill-down del pie de gastos: cuando la dueña clickea un sector,
  // abrimos modal con los movs de esa familia en el rango actual.
  const [familiaDrill, setFamiliaDrill] = useState(null);
  // Modal del sector "Otros": muestra las familias agrupadas en lugar de
  // hacer drill-down directo (que sumaría movimientos de N categorías
  // distintas, sin sentido). Cada fila del modal sí dispara drilldown.
  const [otrosOpen, setOtrosOpen] = useState(false);

  // Ref a la AbortController vigente: como cargar() se invoca tanto desde
  // useEffect (mount) como desde PeriodPresets (clicks rápidos), necesitamos
  // un punto único donde abortar la fetch previa cuando llega una nueva.
  const abortRef = useRef(null);

  async function cargar(desdeOverride, hastaOverride) {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    // Acepta overrides explícitos para casos donde el caller (ej: PeriodPresets)
    // ya conoce los valores nuevos y no quiere depender del closure de state
    // que React aún no flusheó. Sino fallback al state.
    const d = desdeOverride !== undefined ? desdeOverride : desde;
    const h = hastaOverride !== undefined ? hastaOverride : hasta;
    const params = {};
    if (d) params.desde = d;
    if (h) params.hasta = h;
    try {
      // allSettled: si un endpoint falla (backend desactualizado, error puntual)
      // los otros paneles igual se renderizan en lugar de quedar colgados en
      // "Cargando..." para siempre. La dueña ve toast del interceptor con el
      // detalle del error.
      const [r1, r2, r3, r4, r5, r6, r7, r8] = await Promise.allSettled([
        api.get("/api/dashboard/direccion", { params, signal: ctrl.signal }),
        api.get("/api/kpis/comerciales/concentracion-clientes", { params, signal: ctrl.signal }),
        api.get("/api/kpis/comerciales/proyeccion-mes", { signal: ctrl.signal }),
        api.get("/api/kpis/financieros/margen-operativo", { params, signal: ctrl.signal }),
        // Serie SIN filtro de fecha → 12 meses panorámicos. Permite ver
        // tendencia aunque la dueña filtró un rango chico arriba.
        api.get("/api/kpis/financieros/margen-operativo-serie", { signal: ctrl.signal }),
        api.get("/api/kpis-objetivos/resumen", { signal: ctrl.signal }),
        api.get("/api/kpis/financieros/punto-equilibrio", { params, signal: ctrl.signal }),
        api.get("/api/kpis/financieros/crecimiento-sostenido", { signal: ctrl.signal }),
      ]);
      // Si la AbortController ya fue reemplazada por una llamada posterior,
      // descartamos esta respuesta (evita pisar el render con datos viejos).
      if (abortRef.current !== ctrl) return;
      if (r1.status === "fulfilled") setData(r1.value.data);
      else console.warn("[direccion] /dashboard/direccion falló:", r1.reason);
      if (r2.status === "fulfilled") setConc(r2.value.data);
      else { console.warn("[direccion] /concentracion-clientes falló:", r2.reason); setConc(null); }
      if (r3.status === "fulfilled") setProy(r3.value.data);
      else { console.warn("[direccion] /proyeccion-mes falló:", r3.reason); setProy(null); }
      if (r4.status === "fulfilled") setMargenOp(r4.value.data);
      else { console.warn("[direccion] /margen-operativo falló:", r4.reason); setMargenOp(null); }
      if (r5.status === "fulfilled") setMargenSerie(r5.value.data);
      else { console.warn("[direccion] /margen-operativo-serie falló:", r5.reason); setMargenSerie(null); }
      if (r6.status === "fulfilled") setObjResumen(r6.value.data);
      else { console.warn("[direccion] /kpis-objetivos/resumen falló:", r6.reason); setObjResumen(null); }
      if (r7.status === "fulfilled") setPuntoEquilibrio(r7.value.data);
      else { console.warn("[direccion] /punto-equilibrio falló:", r7.reason); setPuntoEquilibrio(null); }
      if (r8.status === "fulfilled") setCrecimiento(r8.value.data);
      else { console.warn("[direccion] /crecimiento-sostenido falló:", r8.reason); setCrecimiento(null); }
    } finally {
      if (abortRef.current === ctrl) setLoading(false);
    }
  }

  useEffect(() => {
    cargar();
    return () => abortRef.current?.abort();
  }, []);

  if (!data) {
    return (
      <>
        <h2>Dirección / Gerencia {loading && <span className="spinner" />}</h2>
        {loading ? (
          <>
            {/* Skeleton mimica el layout real (KPI grid + alertas) para
                que la dueña vea estructura familiar mientras carga, sin
                layout shift cuando llega el data. */}
            <SkeletonKpiGrid cards={6} />
            <div style={{ marginTop: 14 }}>
              <SkeletonPanel rows={3} />
            </div>
          </>
        ) : (
          <div className="empty" style={{ color: "#f87171" }}>
            No se pudo cargar el dashboard. Verificá que el backend esté
            actualizado y reintentá. <button className="btn-ghost btn" onClick={() => cargar()}>Reintentar</button>
          </div>
        )}
      </>
    );
  }

  const k = data.kpis;

  return (
    <>
      <h2>Dirección / Gerencia {loading && <span className="spinner" />}</h2>
      <div style={{ color: "#94a3b8", marginTop: -12, marginBottom: 14, fontSize: 13 }}>
        Período <b>{data.rango.desde}</b> a <b>{data.rango.hasta}</b> ({data.rango.dias} días) — comparado contra <b>{data.rango_anterior.desde}</b> a <b>{data.rango_anterior.hasta}</b>
      </div>

      <DateRange desde={desde} hasta={hasta} setDesde={setDesde} setHasta={setHasta}>
        <button className="btn" onClick={() => cargar()}>Aplicar</button>
      </DateRange>
      <div className="toolbar">
        <span style={{ fontSize: 12, color: "#94a3b8" }}>Atajos:</span>
        <PeriodPresets setDesde={setDesde} setHasta={setHasta} onApply={cargar} />
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: "#94a3b8" }}>Reporte mensual:</span>
        <select value={mesReporte} onChange={(e) => setMesReporte(e.target.value)}>
          {meses.map(([ym, label]) => <option key={ym} value={ym}>{label}</option>)}
        </select>
        <a
          className="btn"
          href={urlBackend(`/api/dashboard/reporte-mensual.pdf?mes=${mesReporte}`)}
          download
          title="Descargar PDF de 1 página con KPIs, top productos/clientes/vendedores y alertas del mes"
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <Icon name="download" size={14} /> Descargar PDF
        </a>
      </div>

      <PanelAlertas />

      <div className="kpi-grid">
        <KpiCardComp label="Ventas" value={k.ventas.actual} prevValue={k.ventas.anterior} formatter={fmtMoney} sub={`${fmtNum(k.pedidos.actual)} pedidos`} />
        <KpiCardComp label="Margen bruto" value={k.margen_bruto.actual} prevValue={k.margen_bruto.anterior} formatter={fmtMoney} tone="green" sub={fmtPct(k.margen_bruto.margen_pct_actual)} />
        <KpiCardComp label="Ticket promedio" value={k.ticket_promedio.actual} prevValue={k.ticket_promedio.anterior} formatter={fmtMoney} />
        <KpiCardComp label="Clientes únicos" value={k.clientes_unicos.actual} prevValue={k.clientes_unicos.anterior} formatter={fmtNum} sub={`${fmtNum(k.clientes_nuevos.actual)} nuevos`} />
        <div className="kpi-card"><div className="label">Vendedores activos</div><div className="value">{fmtNum(k.vendedores_activos)}</div></div>
        <div className="kpi-card green"><div className="label">Saldo total caja</div><div className="value">{fmtMoney(k.saldo_total_caja)}</div></div>
        {margenOp && (
          <>
            <div className={`kpi-card ${margenOp.margen_operativo >= 0 ? "green" : "red"}`}>
              <div className="label">Margen operativo</div>
              <div className="value">{fmtMoney(margenOp.margen_operativo)}</div>
              <div className="sub">
                {margenOp.margen_operativo_pct != null
                  ? `${margenOp.margen_operativo_pct.toFixed(1)}% sobre ingresos`
                  : "—"}
              </div>
            </div>
            <div className="kpi-card">
              <div className="label">Egresos operativos</div>
              <div className="value">{fmtMoney(margenOp.egresos_operativos)}</div>
              <div className="sub">excluye transferencias y retiros</div>
            </div>
          </>
        )}
        {puntoEquilibrio?.cobertura_pct != null && (() => {
          // Tono: rojo si cobertura < 100% (no llega), ámbar 100-120%
          // (justa), verde si > 120% (cómoda).
          const c = puntoEquilibrio.cobertura_pct;
          const tono = c < 100 ? "red" : c < 120 ? "amber" : "green";
          return (
            <div className={`kpi-card ${tono}`}>
              <div className="label">Punto de equilibrio</div>
              <div className="value">{c.toFixed(0)}%</div>
              <div className="sub">
                {c < 100 ? "ingresos < PE — perdiendo" : "cobertura sobre PE"}
                {puntoEquilibrio.margen_contribucion_pct != null && (
                  <> · margen contrib {puntoEquilibrio.margen_contribucion_pct.toFixed(1)}%</>
                )}
              </div>
            </div>
          );
        })()}
        {/* Fallback mutuamente exclusivo: cobertura_pct null = sin PE
             computable. La nota explica la causa (sin config / sin
             ingresos / negocio en rojo). */}
        {puntoEquilibrio?.cobertura_pct == null && puntoEquilibrio?.nota && (
          <div className="kpi-card muted">
            <div className="label">Punto de equilibrio</div>
            <div className="value">—</div>
            <div
              className="sub"
              style={{
                fontSize: 11,
                display: "-webkit-box",
                WebkitLineClamp: 3,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              }}
              title={puntoEquilibrio.nota}
            >
              {puntoEquilibrio.nota}
            </div>
          </div>
        )}
        {crecimiento && crecimiento.tasa_mensual_pct != null && (
          <div
            className={`kpi-card ${crecimiento.tasa_mensual_pct >= 0 ? "green" : "red"}`}
            title={
              crecimiento.tasa_mensual_promedio_pct != null
                ? `Mediana: ${crecimiento.tasa_mensual_pct.toFixed(2)}% · `
                  + `Promedio simple: ${crecimiento.tasa_mensual_promedio_pct.toFixed(2)}% `
                  + `(sensible a outliers, contraste con la mediana).`
                : ""
            }
          >
            <div className="label">Crecimiento sostenido</div>
            <div className="value">
              {crecimiento.tasa_mensual_pct >= 0 ? "+" : ""}{crecimiento.tasa_mensual_pct.toFixed(1)}% mes
            </div>
            <div className="sub">
              {crecimiento.tasa_anualizada_pct != null && (
                <>≈ {crecimiento.tasa_anualizada_pct >= 0 ? "+" : ""}{crecimiento.tasa_anualizada_pct.toFixed(0)}% anual</>
              )}
              <> · {crecimiento.periodos_analizados} meses (mediana)</>
            </div>
          </div>
        )}
        {objResumen && objResumen.total > 0 && (() => {
          const tono = objResumen.no_cumplen > 0
            ? "amber"
            : objResumen.cumplen === objResumen.total ? "green" : "";
          return (
            <Link
              className={`kpi-card ${tono}`}
              to="/kpis-manuales"
              style={{ textDecoration: "none", color: "inherit", display: "block" }}
              title="Ir a /kpis-manuales para gestionar objetivos"
            >
              <div className="label">Objetivos cumpliendo</div>
              <div className="value">{objResumen.cumplen} / {objResumen.total}</div>
              <div className="sub">
                {objResumen.no_cumplen > 0 && `${objResumen.no_cumplen} no cumple · `}
                {objResumen.sin_valor > 0 && `${objResumen.sin_valor} sin valor · `}
                {objResumen.huerfanos > 0 && `${objResumen.huerfanos} huérfano${objResumen.huerfanos === 1 ? "" : "s"} · `}
                {objResumen.periodo_evaluado}
              </div>
            </Link>
          );
        })()}
      </div>

      {proy && proy.proyectado_cierre != null && (() => {
        // Tono de la card "Proyección" según comparativa con año anterior:
        // verde si supera, ámbar si retrocede levemente, rojo si cae fuerte.
        // Sin comparativa (dataset frío) cae a neutro.
        const delta = proy.delta_pct_vs_anio_anterior;
        const tonoProy =
          delta == null ? "" :
          delta >= 0 ? "green" :
          delta >= -10 ? "amber" :
          "red";
        return (
          <div className="panel" style={{ borderColor: "#3b82f6" }}>
            <h3>Proyección del mes en curso</h3>
            <div style={{ color: "#94a3b8", fontSize: 12, marginTop: -6, marginBottom: 12 }}>
              Extrapolación lineal a partir de los <b>{proy.dias_transcurridos} de {proy.dias_totales} días</b> transcurridos.
              No modela estacionalidad intra-mes (semana fuerte / floja al cierre).
            </div>
            <div className="kpi-grid">
              <div className="kpi-card">
                <div className="label">Ventas a la fecha</div>
                <div className="value">{fmtMoney(proy.ventas_a_la_fecha)}</div>
                <div className="sub">{fmtNum(proy.pedidos_a_la_fecha)} pedidos</div>
              </div>
              <div className={`kpi-card ${tonoProy}`}>
                <div className="label">Proyección al cierre</div>
                <div className="value">{fmtMoney(proy.proyectado_cierre)}</div>
                <div className="sub">si se mantiene la tasa diaria</div>
              </div>
              {delta != null && (
                <div className={`kpi-card ${delta >= 0 ? "green" : "red"}`}>
                  <div className="label">vs mismo mes 1 año atrás</div>
                  <div className="value">
                    {delta >= 0 ? "+" : ""}{fmtPct(delta)}
                  </div>
                  <div className="sub">{fmtMoney(proy.anio_anterior_mismo_mes)} en {proy.mes.replace(proy.mes.slice(0,4), String(Number(proy.mes.slice(0,4))-1))}</div>
                </div>
              )}
            </div>
          </div>
        );
      })()}

      <div className="panel">
        <h3 style={{ marginBottom: 4 }}>
          Evolución
          {data.periodo_serie === "dia" && " diaria"}
          {data.periodo_serie === "semana" && " semanal"}
          {data.periodo_serie === "mes" && " mensual"}
        </h3>
        {/* Subtítulo con rango REAL del chart. En cold-open, el chart cubre
            12 meses mientras los KPIs muestran 30 días — sin esto, la dueña
            ve "Período 30 días" arriba y un chart de 14 meses sin entender
            por qué. `rango_serie` viene del backend; fallback al rango de
            los KPIs si endpoint viejo no lo trae. */}
        <div style={{ color: "#94a3b8", fontSize: 12, marginBottom: 8 }}>
          {(data.rango_serie || data.rango).desde} a {(data.rango_serie || data.rango).hasta}
          {data.rango_serie && data.rango_serie.desde !== data.rango.desde && (
            <span style={{ marginLeft: 8, color: "#fbbf24" }}>
              · contexto histórico (los KPIs arriba son del período {data.rango.dias} días)
            </span>
          )}
        </div>
        <ResponsiveContainer width="100%" height={240}>
          {/* `evolucion` (antes `evolucion_mensual`): granularidad adaptive
              al rango filtrado — dia/semana/mes. El título refleja qué
              recibió. */}
          <LineChart data={data.evolucion || data.evolucion_mensual}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="periodo" stroke="#94a3b8" fontSize={11} />
            <YAxis stroke="#94a3b8" fontSize={11} tickFormatter={(v) => "$" + (v / 1e6).toFixed(0) + "M"} />
            <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155" }} formatter={fmtMoney} />
            <Legend />
            <Line type="monotone" dataKey="ventas" stroke="#60a5fa" strokeWidth={2} name="Ventas" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {margenSerie && margenSerie.length > 0 && (
        <div className="panel">
          <h3>Margen operativo mensual (últimos 12 meses)</h3>
          <div style={{ color: "#94a3b8", fontSize: 12, marginBottom: 8 }}>
            Ingresos del período - egresos operativos (excluye transferencias y retiros). Línea ámbar es % sobre ingresos.
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={margenSerie}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="periodo" stroke="#94a3b8" fontSize={11} />
              <YAxis yAxisId="left" stroke="#94a3b8" fontSize={11} tickFormatter={(v) => "$" + (v / 1e6).toFixed(0) + "M"} />
              <YAxis yAxisId="right" orientation="right" stroke="#fbbf24" fontSize={11} tickFormatter={(v) => `${v.toFixed(0)}%`} />
              <Tooltip
                contentStyle={{ background: "#1e293b", border: "1px solid #334155" }}
                // Ocultamos % cuando es null (mes sin ingresos): formatter
                // que retorna null evita que recharts pinte la fila.
                formatter={(v, name) => {
                  if (name === "Margen %") {
                    return v != null ? [`${v.toFixed(1)}%`, name] : null;
                  }
                  return [fmtMoney(v), name];
                }}
              />
              <Legend />
              <Line yAxisId="left" type="monotone" dataKey="margen" stroke="#34d399" strokeWidth={2} name="Margen $" />
              <Line yAxisId="right" type="monotone" dataKey="margen_pct" stroke="#fbbf24" strokeWidth={1.5} strokeDasharray="4 2" name="Margen %" connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {conc && conc.cantidad_clientes > 0 && (() => {
        // Umbrales para top1 vienen del backend (env vars) — single source
        // of truth con la regla de alerta. top3/top5/top10 no tienen severidad
        // crítica propia, así que escalamos sus colores manualmente: el de top3
        // sí coincide con el umbral de alerta atención.
        const u = conc.umbrales || { top1_atencion: 30, top1_critica: 50, top3_atencion: 60 };
        const u_top3_critica = Math.min(100, u.top3_atencion + 20);
        const u_top5_atencion = Math.min(100, u.top3_atencion + 15);
        const u_top5_critica = Math.min(100, u.top3_atencion + 30);
        const colorBarra = (pct) =>
          pct >= u.top1_critica ? "#f87171" : pct >= u.top1_atencion ? "#fbbf24" : "#60a5fa";
        return (
          <div className="panel">
            <h3>Concentración de clientes</h3>
            <div style={{ color: "#94a3b8", fontSize: 12, marginTop: -6, marginBottom: 12 }}>
              % que representa cada grupo sobre las ventas totales del período. Concentración alta = riesgo si se pierde un cliente.
            </div>
            <div className="kpi-grid" style={{ marginBottom: 12 }}>
              <div className="kpi-card">
                <div className="label">Top 1</div>
                <div className="value" style={{ color: tonoConc(conc.top_1_pct, u.top1_atencion, u.top1_critica) }}>{fmtPct(conc.top_1_pct)}</div>
                <div className="sub">cliente principal</div>
              </div>
              <div className="kpi-card">
                <div className="label">Top 3</div>
                <div className="value" style={{ color: tonoConc(conc.top_3_pct, u.top3_atencion, u_top3_critica) }}>{fmtPct(conc.top_3_pct)}</div>
                <div className="sub">acumulado top 3</div>
              </div>
              <div className="kpi-card">
                <div className="label">Top 5</div>
                <div className="value" style={{ color: tonoConc(conc.top_5_pct, u_top5_atencion, u_top5_critica) }}>{fmtPct(conc.top_5_pct)}</div>
                <div className="sub">acumulado top 5</div>
              </div>
              <div className="kpi-card">
                <div className="label">Top 10</div>
                <div className="value">{fmtPct(conc.top_10_pct)}</div>
                <div className="sub">{fmtNum(conc.cantidad_clientes)} clientes en total</div>
              </div>
            </div>
            <table>
              <thead>
                <tr><th style={{ width: 30 }}>#</th><th>Cliente</th><th className="num">Ventas</th><th className="num">%</th><th></th></tr>
              </thead>
              <tbody>
                {conc.top_clientes.slice(0, 5).map((c, i) => (
                  <tr key={c.id_cliente}>
                    <td style={{ color: "#94a3b8" }}>{i + 1}</td>
                    <td>{c.cliente || `(ID ${c.id_cliente})`}</td>
                    <td className="num">{fmtMoney(c.ventas)}</td>
                    <td className="num" style={{ fontWeight: 600 }}>{fmtPct(c.pct)}</td>
                    <td style={{ width: 140 }}>
                      <div style={{ background: "#334155", height: 8, borderRadius: 4, overflow: "hidden" }}>
                        <div style={{
                          width: `${Math.min(100, c.pct)}%`,
                          height: "100%",
                          background: colorBarra(c.pct),
                        }} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })()}

      <div className="panel-grid">
        <div className="panel">
          <h3>Top 5 productos por margen</h3>
          <table>
            <thead><tr><th>Producto</th><th className="num">Margen</th><th className="num">%</th></tr></thead>
            <tbody>
              {data.top_productos.map((p) => (
                <tr key={p.producto}><td>{p.producto}</td><td className="num">{fmtMoney(p.margen)}</td><td className="num">{fmtPct(p.margen_pct)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="panel">
          <h3>Top 5 vendedores</h3>
          <table>
            <thead><tr><th>Vendedor</th><th className="num">Ventas</th><th className="num">Margen</th></tr></thead>
            <tbody>
              {data.top_vendedores.map((v) => (
                <tr key={v.vendedor}><td>{v.vendedor}</td><td className="num">{fmtMoney(v.ventas)}</td><td className="num" style={{ color: "#34d399" }}>{fmtMoney(v.margen)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel-grid">
        <div className="panel">
          <h3>Top 5 cajas por saldo</h3>
          <table>
            <thead><tr><th>Caja</th><th>Tipo</th><th className="num">Saldo</th></tr></thead>
            <tbody>
              {data.top_cajas.map((c) => (
                <tr key={c.caja}>
                  <td>{c.caja}</td>
                  <td><span className={`badge ${c.tipo === "fc_empleado" ? "warn" : "muted"}`}>{c.tipo}</span></td>
                  <td className="num" style={{ color: "#34d399" }}>{fmtMoney(c.saldo)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="panel">
          <h3>Composición de gastos del período <span style={{ fontSize: 11, color: "#94a3b8", fontWeight: 400 }}>(click en sector para ver detalle)</span></h3>
          {(() => {
            // Si hay más de 8 familias, las posiciones 9+ se agrupan en
            // un sector "Otros" — antes desaparecían silenciosamente del
            // pie. El sector es clickeable y abre un modal con la lista.
            const all = data.composicion_gastos;
            const top = all.slice(0, 8);
            const resto = all.slice(8);
            const dataConOtros = resto.length > 0
              ? [
                  ...top,
                  {
                    categoria: "__otros__",
                    label: `Otros (${resto.length})`,
                    monto: resto.reduce((s, r) => s + r.monto, 0),
                    pct: resto.reduce((s, r) => s + (r.pct || 0), 0),
                    _esOtros: true,
                    _items: resto,
                  },
                ]
              : top;
            return (
              <ResponsiveContainer width="100%" height={280}>
                <PieChart>
                  <Pie
                    data={dataConOtros}
                    dataKey="monto"
                    nameKey="categoria"
                    outerRadius={100}
                    cursor="pointer"
                    onClick={(e) => {
                      if (!e) return;
                      if (e._esOtros) setOtrosOpen(true);
                      else if (e.categoria) setFamiliaDrill(e.categoria);
                    }}
                    label={(e) => {
                      if (e.pct < 5) return "";
                      const nombre = e._esOtros ? e.label : e.categoria;
                      return `${nombre} ${e.pct.toFixed(0)}%`;
                    }}
                  >
                    {dataConOtros.map((d, i) => (
                      <Cell
                        key={i}
                        fill={d._esOtros ? "#475569" : COLORS[i % COLORS.length]}
                      />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155" }} formatter={fmtMoney} />
                </PieChart>
              </ResponsiveContainer>
            );
          })()}
        </div>
      </div>

      <Modal
        open={!!familiaDrill}
        onClose={() => setFamiliaDrill(null)}
        title={`Movimientos: ${familiaDrill || ""}`}
        width={920}
      >
        {familiaDrill && (
          <DetalleFamilia
            familia={familiaDrill}
            desde={data.rango.desde}
            hasta={data.rango.hasta}
          />
        )}
      </Modal>

      <Modal
        open={otrosOpen}
        onClose={() => setOtrosOpen(false)}
        title="Otras familias de gastos"
        width={680}
      >
        {(() => {
          const resto = data.composicion_gastos.slice(8);
          if (resto.length === 0) return <div className="empty">No hay otras familias.</div>;
          return (
            <>
              <div style={{ color: "#94a3b8", fontSize: 12, marginBottom: 12 }}>
                {resto.length} familias agrupadas (las que están fuera del top 8 visible en el pie).
                Click en una fila para ver el detalle de movimientos.
              </div>
              <table>
                <thead>
                  <tr><th>Familia</th><th className="num">Monto</th><th className="num">%</th><th className="num">Movs</th></tr>
                </thead>
                <tbody>
                  {resto.map((r) => (
                    <tr
                      key={r.categoria}
                      style={{ cursor: "pointer" }}
                      onClick={() => {
                        setOtrosOpen(false);
                        setFamiliaDrill(r.categoria);
                      }}
                      title="Ver movimientos de esta familia"
                    >
                      <td>{r.categoria}</td>
                      <td className="num">{fmtMoney(r.monto)}</td>
                      <td className="num">{fmtPct(r.pct)}</td>
                      <td className="num">{fmtNum(r.operaciones)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          );
        })()}
      </Modal>
    </>
  );
}

function DetalleFamilia({ familia, desde, hasta }) {
  const [movs, setMovs] = useState(null);

  useEffect(() => {
    api.get("/api/kpis/caja/movimientos-por-familia", {
      params: { familia, desde, hasta, limite: 200 },
    }).then((r) => setMovs(r.data));
  }, [familia, desde, hasta]);

  if (movs === null) {
    // DetalleFamilia se muestra dentro de un Modal — skeleton liviano
    // (3 líneas + tabla minimal) en vez de SkeletonPanel que tiene su
    // propio wrapper panel y queda redundante.
    return (
      <>
        <Skeleton width="60%" height={12} style={{ marginBottom: 12 }} />
        <Skeleton width="100%" height={14} style={{ marginBottom: 6 }} />
        <Skeleton width="100%" height={14} style={{ marginBottom: 6 }} />
        <Skeleton width="80%" height={14} />
      </>
    );
  }
  if (movs.length === 0) return <div className="empty">Sin movimientos en esta familia y período.</div>;

  const total = movs.reduce((s, m) => s + m.monto, 0);

  return (
    <>
      <div style={{ color: "#94a3b8", fontSize: 12, marginBottom: 12 }}>
        {movs.length} movimientos · total {fmtMoney(total)} · período {desde} a {hasta}
      </div>
      <table>
        <thead>
          <tr>
            <th>Fecha</th>
            <th>Tipo</th>
            <th>Detalle</th>
            <th>Caja</th>
            <th className="num">Monto</th>
          </tr>
        </thead>
        <tbody>
          {movs.map((m) => (
            <tr key={m.id}>
              <td>{m.fecha}</td>
              <td><span className="badge muted">{m.tipo_operacion}</span></td>
              <td>{m.detalle || "(sin detalle)"}</td>
              <td style={{ color: "#94a3b8", fontSize: 12 }}>{m.caja_origen}</td>
              <td className="num" style={{ fontWeight: 600 }}>{fmtMoney(m.monto)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
