import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import api, { fmtMoney, fmtNum, fmtPct } from "../api/client";
import DateRange from "../components/DateRange";
import Icon from "../components/Icon";
import KpiCard from "../components/KpiCard";
import KpiCardComp from "../components/KpiCardComp";
import Modal from "../components/Modal";
import PeriodPresets, { periodoAnterior } from "../components/PeriodPresets";
import Skeleton, { SkeletonKpiGrid } from "../components/Skeleton";
import SortableTable from "../components/SortableTable";
import { useStoredState } from "../hooks/useStoredState";

export default function Comercial() {
  const [desde, setDesde] = useStoredState("comercial:desde", "");
  const [hasta, setHasta] = useStoredState("comercial:hasta", "");
  const [vendedor, setVendedor] = useStoredState("comercial:vendedor", "");
  const [vendedoresList, setVendedoresList] = useState([]);
  const [resumen, setResumen] = useState(null);
  const [resumenPrev, setResumenPrev] = useState(null);
  const [serie, setSerie] = useState([]);
  const [topProductos, setTopProductos] = useState([]);
  const [topClientes, setTopClientes] = useState([]);
  const [topVendedores, setTopVendedores] = useState([]);
  const [recompra, setRecompra] = useState(null);
  const [perdida, setPerdida] = useState([]);
  const [abc, setAbc] = useState(null);
  const [loading, setLoading] = useState(false);
  const [modalVendedor, setModalVendedor] = useState(null);
  const [modalProducto, setModalProducto] = useState(null);
  const navigate = useNavigate();

  // Ref para abortar fetches en vuelo cuando se dispara una nueva.
  const abortRef = useRef(null);

  async function cargar(desdeOverride, hastaOverride) {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    // Overrides explícitos para PeriodPresets — sino el closure de state
    // queda viejo y los KPIs no actualizan al click del preset.
    const d = desdeOverride !== undefined ? desdeOverride : desde;
    const h = hastaOverride !== undefined ? hastaOverride : hasta;
    const params = {};
    if (d) params.desde = d;
    if (h) params.hasta = h;
    if (vendedor) params.vendedor = vendedor;
    try {
      // allSettled: defensa contra backend desactualizado o endpoint con
      // error puntual. Cada panel se degrada por su cuenta — la página
      // sigue funcionando aunque uno o dos endpoints fallen.
      const results = await Promise.allSettled([
        api.get("/api/kpis/comerciales/resumen", { params, signal: ctrl.signal }),
        api.get("/api/kpis/comerciales/serie-temporal", { params: { ...params, periodo: "mes" }, signal: ctrl.signal }),
        api.get("/api/kpis/comerciales/top-productos", { params: { ...params, por: "margen", limite: 10 }, signal: ctrl.signal }),
        api.get("/api/kpis/comerciales/top-clientes", { params: { ...params, limite: 10 }, signal: ctrl.signal }),
        api.get("/api/kpis/comerciales/top-vendedores", { params: { ...params, limite: 15 }, signal: ctrl.signal }),
        api.get("/api/kpis/comerciales/recompra", { params, signal: ctrl.signal }),
        api.get("/api/kpis/comerciales/productos-a-perdida", { params: { ...params, limite: 20 }, signal: ctrl.signal }),
        api.get("/api/kpis/comerciales/analisis-abc-productos", { params, signal: ctrl.signal }),
      ]);
      if (abortRef.current !== ctrl) return;  // pisó otra fetch
      const nombres = ["resumen", "serie-temporal", "top-productos", "top-clientes",
                       "top-vendedores", "recompra", "productos-perdida", "abc"];
      results.forEach((r, i) => {
        if (r.status === "rejected") {
          console.warn(`[comercial] /${nombres[i]} falló:`, r.reason);
        }
      });
      const [r, s, tp, tc, tv, rc, pp, ab] = results;
      const valOrNull = (x) => x.status === "fulfilled" ? x.value.data : null;
      setResumen(valOrNull(r));
      setSerie(valOrNull(s) || []);
      setTopProductos(valOrNull(tp) || []);
      setTopClientes(valOrNull(tc) || []);
      setTopVendedores(valOrNull(tv) || []);
      setRecompra(valOrNull(rc));
      setPerdida(valOrNull(pp) || []);
      setAbc(valOrNull(ab));

      // Comparativa vs período anterior si hay rango definido. Si falla,
      // limpiamos `resumenPrev` para no mostrar deltas calculados contra
      // un período viejo (engañoso). El interceptor ya muestra toast.
      if (desde && hasta) {
        try {
          const prev = periodoAnterior(desde, hasta);
          const prevParams = { desde: prev.desde, hasta: prev.hasta };
          if (vendedor) prevParams.vendedor = vendedor;
          const rp = await api.get("/api/kpis/comerciales/resumen", { params: prevParams, signal: ctrl.signal });
          setResumenPrev(rp.data);
        } catch (e) {
          if (e.name !== "CanceledError" && e.code !== "ERR_CANCELED") {
            console.warn("[comercial] resumenPrev falló:", e);
            setResumenPrev(null);
          }
        }
      } else {
        setResumenPrev(null);
      }
    } catch (e) {
      if (e.name !== "CanceledError" && e.code !== "ERR_CANCELED") throw e;
    } finally {
      if (abortRef.current === ctrl) setLoading(false);
    }
  }

  async function cargarVendedores(signal) {
    try {
      const { data } = await api.get("/api/ventas/vendedores", { signal });
      setVendedoresList(data);
    } catch (e) {
      if (e.name !== "CanceledError" && e.code !== "ERR_CANCELED") throw e;
    }
  }

  useEffect(() => {
    cargar();
    const ctrlV = new AbortController();
    cargarVendedores(ctrlV.signal);
    return () => { abortRef.current?.abort(); ctrlV.abort(); };
  }, []);

  return (
    <>
      <h2>Comercial / Ventas {loading && <span className="spinner" />}</h2>
      <DateRange desde={desde} hasta={hasta} setDesde={setDesde} setHasta={setHasta}>
        <label>Vendedor</label>
        <select value={vendedor} onChange={(e) => setVendedor(e.target.value)}>
          <option value="">Todos</option>
          {vendedoresList.map((v) => (
            <option key={v.vendedor} value={v.vendedor}>{v.vendedor} ({v.pedidos})</option>
          ))}
        </select>
        <button className="btn" onClick={cargar}>Aplicar</button>
      </DateRange>
      <div className="toolbar">
        <span style={{ fontSize: 12, color: "#94a3b8" }}>Atajos:</span>
        <PeriodPresets setDesde={setDesde} setHasta={setHasta} onApply={cargar} />
      </div>
      {(desde && !hasta) || (!desde && hasta) ? (
        <div style={{ fontSize: 12, color: "#fbbf24", marginTop: -10, marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
          <Icon name="warn" size={14} />
          Para ver comparativa vs período anterior, definí <b>desde</b> y <b>hasta</b>.
        </div>
      ) : null}

      {resumen ? (
        <div className="kpi-grid">
          <KpiCardComp label="Ventas totales" value={resumen.ventas_totales} prevValue={resumenPrev?.ventas_totales} formatter={fmtMoney} sub={`${fmtNum(resumen.pedidos)} pedidos`} />
          <KpiCardComp label="Ticket promedio" value={resumen.ticket_promedio} prevValue={resumenPrev?.ticket_promedio} formatter={fmtMoney} />
          <KpiCardComp label="Clientes únicos" value={resumen.clientes_unicos} prevValue={resumenPrev?.clientes_unicos} formatter={fmtNum} sub={`${fmtNum(resumen.clientes_nuevos)} nuevos`} />
          <KpiCardComp label="Margen bruto" value={resumen.margen_bruto} prevValue={resumenPrev?.margen_bruto} formatter={fmtMoney} tone="green" sub={fmtPct(resumen.margen_pct)} />
          <KpiCard label="Ingresos mercadería" value={fmtMoney(resumen.ingresos_mercaderia)} />
          <KpiCard label="Costo (CST)" value={fmtMoney(resumen.costo_mercaderia)} />
          {recompra && <KpiCard label="Tasa recompra" value={fmtPct(recompra.tasa_recompra_pct)} sub={`${fmtNum(recompra.clientes_recurrentes)} de ${fmtNum(recompra.clientes_total)}`} />}
          {recompra && <KpiCard label="Frecuencia" value={recompra.frecuencia_promedio_pedidos.toFixed(2)} sub="pedidos/cliente" />}
          {resumen.ventas_con_discrepancia > 0 && <KpiCard label="Ventas con discrepancia" value={fmtNum(resumen.ventas_con_discrepancia)} tone="amber" sub="pago ≠ total" />}
        </div>
      ) : (
        // Skeleton siempre que no hay resumen: en first mount loading=false
        // por un tick antes que arranque cargar(). Mostrar `null` ahí
        // produce un flash visual de pantalla vacía → skeleton.
        <SkeletonKpiGrid cards={6} />
      )}

      <div className="panel">
        <h3>Evolución mensual de ventas</h3>
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={serie}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="periodo" stroke="#94a3b8" fontSize={11} />
            <YAxis stroke="#94a3b8" fontSize={11} tickFormatter={(v) => "$" + (v / 1e6).toFixed(0) + "M"} />
            <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155" }} formatter={fmtMoney} />
            <Legend />
            <Line type="monotone" dataKey="ventas" stroke="#60a5fa" strokeWidth={2} name="Ventas" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="panel-grid">
        <div className="panel">
          <h3>Top productos por margen <span style={{ fontSize: 11, color: "#94a3b8", fontWeight: 400 }}>(click columna para ordenar)</span></h3>
          <SortableTable
            rowKey={(r) => r.producto}
            rows={topProductos}
            initialSort={{ key: "margen", dir: "desc" }}
            exportCSV={{ filename: "top-productos.csv" }}
            columns={[
              { key: "producto", label: "Producto", render: (r) => (
                <a href="#" onClick={(e) => { e.preventDefault(); setModalProducto(r.producto); }}>{r.producto}</a>
              ), csvFormat: (r) => r.producto },
              { key: "ingresos", label: "Ingresos", num: true, render: (r) => fmtMoney(r.ingresos) },
              { key: "margen", label: "Margen", num: true, render: (r) => fmtMoney(r.margen) },
              { key: "margen_pct", label: "%", num: true, render: (r) => fmtPct(r.margen_pct) },
              { key: "ventas", label: "Ventas", num: true, render: (r) => fmtNum(r.ventas) },
            ]}
          />
        </div>

        <div className="panel">
          <h3>Top clientes por ventas</h3>
          <SortableTable
            rowKey={(r) => r.id_cliente}
            rows={topClientes}
            initialSort={{ key: "ventas", dir: "desc" }}
            exportCSV={{ filename: "top-clientes.csv" }}
            columns={[
              { key: "cliente", label: "Cliente", render: (r) => (
                <a
                  href="#"
                  onClick={(e) => { e.preventDefault(); navigate(`/cuentas-corrientes?cliente=${r.id_cliente}`); }}
                  title="Ver extracto del cliente"
                >{r.cliente}</a>
              ), csvFormat: (r) => r.cliente },
              { key: "ventas", label: "Ventas", num: true, render: (r) => fmtMoney(r.ventas) },
              { key: "pedidos", label: "Pedidos", num: true, render: (r) => fmtNum(r.pedidos) },
              { key: "ticket_promedio", label: "Ticket", num: true, render: (r) => fmtMoney(r.ticket_promedio) },
            ]}
          />
        </div>
      </div>

      <div className="panel">
        <h3>Vendedores: ventas y margen <span style={{ fontSize: 12, color: "#94a3b8", fontWeight: 400 }}>(click para ver detalle)</span></h3>
        <ResponsiveContainer width="100%" height={Math.max(260, topVendedores.length * 28)}>
          <BarChart data={topVendedores} layout="vertical" margin={{ left: 100 }} onClick={(d) => d?.activeLabel && setModalVendedor(d.activeLabel)}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis type="number" stroke="#94a3b8" fontSize={11} tickFormatter={(v) => "$" + (v / 1e6).toFixed(0) + "M"} />
            <YAxis type="category" dataKey="vendedor" stroke="#94a3b8" fontSize={11} width={130} />
            <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155" }} formatter={fmtMoney} />
            <Legend />
            <Bar dataKey="ventas" fill="#60a5fa" name="Ventas" cursor="pointer" />
            <Bar dataKey="margen" fill="#34d399" name="Margen" cursor="pointer" />
          </BarChart>
        </ResponsiveContainer>
        <div style={{ marginTop: 8 }}>
          <SortableTable
            rowKey={(r) => r.vendedor}
            rows={topVendedores}
            initialSort={{ key: "ventas", dir: "desc" }}
            exportCSV={{ filename: "top-vendedores.csv" }}
            columns={[
              { key: "vendedor", label: "Vendedor", render: (r) => (
                <a href="#" onClick={(e) => { e.preventDefault(); setModalVendedor(r.vendedor); }}>{r.vendedor}</a>
              ), csvFormat: (r) => r.vendedor },
              { key: "pedidos", label: "Pedidos", num: true, render: (r) => fmtNum(r.pedidos) },
              { key: "clientes", label: "Clientes", num: true, render: (r) => fmtNum(r.clientes) },
              { key: "ticket_promedio", label: "Ticket", num: true, render: (r) => fmtMoney(r.ticket_promedio) },
              { key: "ventas", label: "Ventas", num: true, render: (r) => fmtMoney(r.ventas) },
              { key: "margen", label: "Margen", num: true, render: (r) => <span style={{ color: "#34d399" }}>{fmtMoney(r.margen)}</span> },
            ]}
          />
        </div>
      </div>

      {abc && abc.totales.productos > 0 && (
        <div className="panel">
          <h3>Análisis ABC de productos (Pareto)</h3>
          <div style={{ color: "#94a3b8", fontSize: 12, marginTop: -6, marginBottom: 12 }}>
            Clasificación por contribución acumulada al margen.
            <b> A</b>: top que genera 80% — foco comercial.
            <b> B</b>: 80-95% — secundarios.
            <b> C</b>: cola larga 5%.
          </div>
          <div className="kpi-grid">
            <div className="kpi-card green">
              <div className="label">Categoría A</div>
              <div className="value">{fmtNum(abc.totales.a)}</div>
              <div className="sub">de {fmtNum(abc.totales.productos)} productos · 80% del margen</div>
            </div>
            <div className="kpi-card amber">
              <div className="label">Categoría B</div>
              <div className="value">{fmtNum(abc.totales.b)}</div>
              <div className="sub">15% del margen</div>
            </div>
            <div className="kpi-card muted">
              <div className="label">Categoría C</div>
              <div className="value">{fmtNum(abc.totales.c)}</div>
              <div className="sub">5% del margen — cola larga</div>
            </div>
            <div className="kpi-card">
              <div className="label">Margen total</div>
              <div className="value">{fmtMoney(abc.totales.margen_total)}</div>
              <div className="sub">acumulado en período</div>
            </div>
          </div>
          <details style={{ marginTop: 12 }}>
            <summary style={{ cursor: "pointer", color: "#94a3b8", fontSize: 12 }}>
              Ver lista completa de productos clasificados
            </summary>
            <table style={{ marginTop: 8, fontSize: 12 }}>
              <thead>
                <tr>
                  <th>ABC</th><th>Producto</th>
                  <th className="num">Margen</th>
                  <th className="num">% del total</th>
                  <th className="num">Acum %</th>
                </tr>
              </thead>
              <tbody>
                {abc.productos.map((p) => (
                  <tr key={p.producto}>
                    <td>
                      <span className={`badge ${p.categoria_abc === "A" ? "ok" : p.categoria_abc === "B" ? "warn" : "muted"}`}>
                        {p.categoria_abc}
                      </span>
                    </td>
                    <td>{p.producto}</td>
                    <td className="num">{fmtMoney(p.margen)}</td>
                    <td className="num">{fmtPct(p.margen_pct)}</td>
                    <td className="num" style={{ color: "#94a3b8" }}>{fmtPct(p.margen_acumulado_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>
      )}

      {perdida.length > 0 && (
        <div className="panel">
          <h3>Productos con margen negativo (a pérdida real)</h3>
          <table>
            <thead><tr><th>Producto</th><th className="num">Ingresos</th><th className="num">Costo</th><th className="num">Pérdida</th></tr></thead>
            <tbody>
              {perdida.map((p) => (
                <tr key={p.producto}>
                  <td>{p.producto}</td>
                  <td className="num">{fmtMoney(p.ingresos)}</td>
                  <td className="num">{fmtMoney(p.costo)}</td>
                  <td className="num" style={{ color: "#f87171" }}>{fmtMoney(p.margen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={!!modalVendedor}
        onClose={() => setModalVendedor(null)}
        title={`Detalle: ${modalVendedor || ""}`}
        width={900}
      >
        {modalVendedor && <DetalleVendedor vendedor={modalVendedor} desde={desde} hasta={hasta} />}
      </Modal>

      <Modal
        open={!!modalProducto}
        onClose={() => setModalProducto(null)}
        title={`Clientes que compraron: ${modalProducto || ""}`}
        width={780}
      >
        {modalProducto && (
          <ClientesDeProducto
            producto={modalProducto}
            desde={desde}
            hasta={hasta}
            onCerrar={() => setModalProducto(null)}
          />
        )}
      </Modal>
    </>
  );
}

function ClientesDeProducto({ producto, desde, hasta, onCerrar }) {
  const navigate = useNavigate();
  const [clientes, setClientes] = useState(null);

  useEffect(() => {
    const params = { producto };
    if (desde) params.desde = desde;
    if (hasta) params.hasta = hasta;
    api.get("/api/kpis/comerciales/clientes-de-producto", { params })
      .then((r) => setClientes(r.data));
  }, [producto, desde, hasta]);

  if (clientes === null) {
    // ClientesDeProducto vive dentro de Modal — skeleton liviano sin
    // panel wrapper (mismo pattern que DetalleFamilia en Direccion).
    return (
      <>
        <Skeleton width="60%" height={12} style={{ marginBottom: 12 }} />
        <Skeleton width="100%" height={14} style={{ marginBottom: 6 }} />
        <Skeleton width="100%" height={14} style={{ marginBottom: 6 }} />
        <Skeleton width="80%" height={14} />
      </>
    );
  }
  if (clientes.length === 0) return <div className="empty">Sin compras de este producto en el período.</div>;

  const totalMonto = clientes.reduce((s, c) => s + c.monto_total, 0);

  return (
    <>
      <div style={{ color: "#94a3b8", fontSize: 12, marginBottom: 12 }}>
        {clientes.length} clientes · {fmtMoney(totalMonto)} total · ordenados por monto
      </div>
      <table>
        <thead>
          <tr>
            <th>Cliente</th>
            <th className="num">Cantidad</th>
            <th className="num">Monto</th>
            <th className="num">Pedidos</th>
            <th>Última compra</th>
          </tr>
        </thead>
        <tbody>
          {clientes.map((c) => (
            <tr key={c.id_cliente}>
              <td>
                <a
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    onCerrar();
                    navigate(`/cuentas-corrientes?cliente=${c.id_cliente}`);
                  }}
                  title="Ver extracto del cliente"
                >{c.cliente || `(ID ${c.id_cliente})`}</a>
              </td>
              <td className="num">{fmtNum(c.cantidad_total)}</td>
              <td className="num" style={{ fontWeight: 600 }}>{fmtMoney(c.monto_total)}</td>
              <td className="num">{fmtNum(c.pedidos)}</td>
              <td style={{ color: "#94a3b8", fontSize: 12 }}>{c.ultima_compra?.slice(0, 10) || "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function DetalleVendedor({ vendedor, desde, hasta }) {
  const [resumen, setResumen] = useState(null);
  const [productos, setProductos] = useState([]);
  const [clientes, setClientes] = useState([]);
  const [ventas, setVentas] = useState([]);

  useEffect(() => {
    const params = { vendedor };
    if (desde) params.desde = desde;
    if (hasta) params.hasta = hasta;
    Promise.all([
      api.get("/api/kpis/comerciales/resumen", { params }),
      api.get("/api/kpis/comerciales/top-productos", { params: { ...params, limite: 10 } }),
      api.get("/api/kpis/comerciales/top-clientes", { params: { ...params, limite: 10 } }),
      api.get("/api/ventas/buscar", { params: { ...params, limite: 15 } }),
    ]).then(([r, p, c, v]) => {
      setResumen(r.data);
      setProductos(p.data);
      setClientes(c.data);
      setVentas(v.data.items);
    });
  }, [vendedor, desde, hasta]);

  if (!resumen) {
    // Sub-componente "vendedor detail" dentro de Modal — kpi grid de 4 +
    // skeleton lines para los tops. Liviano, sin panel wrapper.
    return (
      <>
        <SkeletonKpiGrid cards={4} />
        <Skeleton width="40%" height={14} style={{ margin: "16px 0 8px" }} />
        <Skeleton width="100%" height={14} style={{ marginBottom: 6 }} />
        <Skeleton width="100%" height={14} style={{ marginBottom: 6 }} />
        <Skeleton width="80%" height={14} />
      </>
    );
  }

  return (
    <>
      <div className="kpi-grid">
        <KpiCard label="Ventas" value={fmtMoney(resumen.ventas_totales)} sub={`${fmtNum(resumen.pedidos)} pedidos`} />
        <KpiCard label="Ticket promedio" value={fmtMoney(resumen.ticket_promedio)} />
        <KpiCard label="Clientes" value={fmtNum(resumen.clientes_unicos)} sub={`${fmtNum(resumen.clientes_nuevos)} nuevos`} />
        <KpiCard label="Margen bruto" value={fmtMoney(resumen.margen_bruto)} tone="green" sub={fmtPct(resumen.margen_pct)} />
      </div>

      <div className="panel-grid" style={{ margin: 0 }}>
        <div>
          <h3>Top productos</h3>
          <table>
            <thead><tr><th>Producto</th><th className="num">Margen</th></tr></thead>
            <tbody>{productos.map((p) => <tr key={p.producto}><td>{p.producto}</td><td className="num">{fmtMoney(p.margen)}</td></tr>)}</tbody>
          </table>
        </div>
        <div>
          <h3>Top clientes</h3>
          <table>
            <thead><tr><th>Cliente</th><th className="num">Ventas</th></tr></thead>
            <tbody>{clientes.map((c) => <tr key={c.id_cliente}><td>{c.cliente}</td><td className="num">{fmtMoney(c.ventas)}</td></tr>)}</tbody>
          </table>
        </div>
      </div>

      <h3 style={{ marginTop: 20 }}>Últimas 15 ventas</h3>
      <table>
        <thead><tr><th>Fecha</th><th>Cliente</th><th className="num">Total</th></tr></thead>
        <tbody>
          {ventas.map((v) => (
            <tr key={v.id_pedido}>
              <td>{v.fecha?.slice(0, 16).replace("T", " ")}</td>
              <td>{v.cliente}</td>
              <td className="num">{fmtMoney(v.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
