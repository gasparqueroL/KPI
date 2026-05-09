import { useEffect, useRef, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import api, { fmtMoney, fmtNum, fmtPct } from "../api/client";
import DateRange from "../components/DateRange";
import KpiCard from "../components/KpiCard";
import { useStoredState } from "../hooks/useStoredState";

const COLORS = ["#60a5fa", "#34d399", "#fbbf24", "#f87171", "#a78bfa", "#fb923c", "#22d3ee", "#f472b6", "#94a3b8", "#84cc16"];

export default function Caja() {
  const [desde, setDesde] = useStoredState("caja:desde", "");
  const [hasta, setHasta] = useStoredState("caja:hasta", "");
  const [resumen, setResumen] = useState(null);
  const [saldos, setSaldos] = useState([]);
  const [flujo, setFlujo] = useState([]);
  const [composicion, setComposicion] = useState([]);
  const [topGastos, setTopGastos] = useState([]);
  const [loading, setLoading] = useState(false);

  // Ref-based abort: cargar() invocado desde useEffect Y desde botón
  // "Aplicar". Centraliza la cancelación de fetches viejos.
  const abortRef = useRef(null);

  async function cargar() {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    const params = {};
    if (desde) params.desde = desde;
    if (hasta) params.hasta = hasta;
    try {
      // allSettled: si un endpoint falla los demás igual se renderizan.
      const [r, s, f, c, g] = await Promise.allSettled([
        api.get("/api/kpis/caja/resumen", { params, signal: ctrl.signal }),
        api.get("/api/kpis/caja/saldos", { signal: ctrl.signal }),
        api.get("/api/kpis/caja/flujo", { params: { ...params, periodo: "mes" }, signal: ctrl.signal }),
        api.get("/api/kpis/caja/composicion-gastos", { params, signal: ctrl.signal }),
        api.get("/api/kpis/caja/top-gastos", { params: { ...params, limite: 10 }, signal: ctrl.signal }),
      ]);
      if (abortRef.current !== ctrl) return;  // descartar si pisó otra fetch
      if (r.status === "fulfilled") setResumen(r.value.data);
      if (s.status === "fulfilled") setSaldos(s.value.data);
      if (f.status === "fulfilled") setFlujo(f.value.data);
      if (c.status === "fulfilled") setComposicion(c.value.data.slice(0, 10));
      if (g.status === "fulfilled") setTopGastos(g.value.data);
    } finally {
      if (abortRef.current === ctrl) setLoading(false);
    }
  }

  useEffect(() => {
    cargar();
    return () => abortRef.current?.abort();
  }, []);

  return (
    <>
      <h2>Caja / Finanzas {loading && <span className="spinner" />}</h2>
      <DateRange desde={desde} hasta={hasta} setDesde={setDesde} setHasta={setHasta}>
        <button className="btn" onClick={() => cargar()}>Aplicar</button>
      </DateRange>

      {resumen && (
        <div className="kpi-grid">
          <KpiCard label="Saldo total" value={fmtMoney(resumen.saldo_total_actual)} tone="green" sub="suma de todas las cajas" />
          <KpiCard label="Cajas operativas" value={fmtMoney(resumen.saldo_cajas_operativas)} />
          <KpiCard label="Cajas FC empleados" value={fmtMoney(resumen.saldo_cajas_fc)} sub="adelantos pendientes" />
          <KpiCard label="Ingresos (mov)" value={fmtMoney(resumen.ingresos_movimientos)} />
          <KpiCard label="Egresos (mov)" value={fmtMoney(resumen.egresos_movimientos)} tone="red" />
          <KpiCard label="Transferencias internas" value={fmtMoney(resumen.transferencias_internas)} sub="entre cajas" />
        </div>
      )}

      <div className="panel">
        <h3>Flujo de caja mensual (solo movimientos, sin contar ventas a caja)</h3>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={flujo}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="periodo" stroke="#94a3b8" fontSize={11} />
            <YAxis stroke="#94a3b8" fontSize={11} tickFormatter={(v) => "$" + (v / 1e6).toFixed(0) + "M"} />
            <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155" }} formatter={fmtMoney} />
            <Legend />
            <Bar dataKey="ingresos" fill="#34d399" name="Ingresos" />
            <Bar dataKey="egresos" fill="#f87171" name="Egresos" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="panel-grid">
        <div className="panel">
          <h3>Saldos por caja (top 15)</h3>
          <table>
            <thead>
              <tr><th>Caja</th><th>Tipo</th><th className="num">Saldo</th></tr>
            </thead>
            <tbody>
              {saldos.slice(0, 15).map((c) => (
                <tr key={c.caja}>
                  <td>{c.caja}</td>
                  <td><span className={`badge ${c.tipo === "fc_empleado" ? "warn" : "muted"}`}>{c.tipo}</span></td>
                  <td className="num" style={{ color: c.saldo < 0 ? "#f87171" : "#34d399" }}>{fmtMoney(c.saldo)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <h3>Composición de gastos (top 10)</h3>
          <ResponsiveContainer width="100%" height={350}>
            <PieChart>
              <Pie data={composicion} dataKey="monto" nameKey="categoria" outerRadius={120} label={(e) => `${e.categoria} ${e.pct.toFixed(0)}%`}>
                {composicion.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
              <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155" }} formatter={fmtMoney} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="panel">
        <h3>Top gastos individuales</h3>
        <table>
          <thead>
            <tr><th>Fecha</th><th>Tipo</th><th>Detalle</th><th>Caja</th><th className="num">Monto</th></tr>
          </thead>
          <tbody>
            {topGastos.map((g, i) => (
              <tr key={i}>
                <td>{g.fecha}</td>
                <td><span className="badge muted">{g.tipo_operacion}</span></td>
                <td style={{ maxWidth: 400 }}>{g.detalle}</td>
                <td>{g.caja_origen}</td>
                <td className="num">{fmtMoney(g.monto)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
