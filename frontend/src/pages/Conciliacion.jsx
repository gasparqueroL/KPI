import { Fragment, useEffect, useRef, useState } from "react";
import api, { fmtMoney, fmtNum, fmtPct } from "../api/client";
import { descargarComoCSV } from "../api/csvExport";
import DateRange from "../components/DateRange";
import EditarVentaFila from "../components/EditarVentaFila";
import Icon from "../components/Icon";
import KpiCard from "../components/KpiCard";
import PeriodPresets from "../components/PeriodPresets";
import { useStoredState } from "../hooks/useStoredState";

// Definición de columnas por tab — el botón CSV dispatcha según tab activo.
// El nombre del archivo trae fecha + tab para que la dueña no pise descargas
// previas si baja varios sin cerrar la pestaña.
const COLS_CSV = {
  "sin-cobro": [
    { key: "fecha", label: "Fecha", format: (v) => v.fecha?.slice(0, 10) || "" },
    { key: "cliente", label: "Cliente" },
    { key: "vendedor", label: "Vendedor" },
    { key: "total", label: "Total" },
  ],
  "discrepancias": [
    { key: "fecha", label: "Fecha", format: (v) => v.fecha?.slice(0, 10) || "" },
    { key: "cliente", label: "Cliente" },
    { key: "total", label: "Total" },
    { key: "monto_pago1", label: "Pago 1" },
    { key: "monto_pago2", label: "Pago 2" },
    { key: "suma_pagos", label: "Suma" },
    { key: "diferencia", label: "Diferencia" },
  ],
  "cta-cte": [
    { key: "fecha", label: "Fecha", format: (v) => v.fecha?.slice(0, 10) || "" },
    { key: "cliente", label: "Cliente" },
    { key: "vendedor", label: "Vendedor" },
    { key: "total", label: "Total" },
  ],
};

export default function Conciliacion() {
  const [desde, setDesde] = useStoredState("conciliacion:desde", "");
  const [hasta, setHasta] = useStoredState("conciliacion:hasta", "");
  const [resumen, setResumen] = useState(null);
  const [tab, setTab] = useStoredState("conciliacion:tab", "sin-cobro");
  const [items, setItems] = useState([]);
  const [itemsTotal, setItemsTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [editando, setEditando] = useState(null);
  const [cajasList, setCajasList] = useState([]);

  // Ref a la AbortController vigente: cargarResumen se llama desde mount,
  // PeriodPresets, "Aplicar" y after-save. Single point de aborto evita
  // que llamadas viejas pisen state nuevo.
  const resumenAbortRef = useRef(null);

  async function cargarResumen(desdeOverride, hastaOverride) {
    resumenAbortRef.current?.abort();
    const ctrl = new AbortController();
    resumenAbortRef.current = ctrl;
    setLoading(true);
    // Overrides para PeriodPresets — sino closure viejo (cargarItems sí
    // tiene useEffect en [desde,hasta] así que actualiza solo).
    const d = desdeOverride !== undefined ? desdeOverride : desde;
    const h = hastaOverride !== undefined ? hastaOverride : hasta;
    const params = {};
    if (d) params.desde = d;
    if (h) params.hasta = h;
    try {
      const { data } = await api.get("/api/conciliacion/resumen", { params, signal: ctrl.signal });
      if (resumenAbortRef.current === ctrl) setResumen(data);
    } catch (e) {
      if (e.name !== "CanceledError" && e.code !== "ERR_CANCELED") throw e;
    } finally {
      if (resumenAbortRef.current === ctrl) setLoading(false);
    }
  }

  async function cargarItems(signal) {
    const params = { limite: 100 };
    if (desde) params.desde = desde;
    if (hasta) params.hasta = hasta;
    let url;
    if (tab === "sin-cobro") url = "/api/conciliacion/sin-cobro";
    else if (tab === "discrepancias") url = "/api/conciliacion/discrepancias";
    else url = "/api/conciliacion/cta-cte-emitidas";
    try {
      const { data } = await api.get(url, { params, signal });
      setItems(data.items || []);
      setItemsTotal(data.total ?? data.total_cantidad ?? data.items?.length ?? 0);
    } catch (e) {
      if (e.name !== "CanceledError" && e.code !== "ERR_CANCELED") throw e;
    }
  }

  useEffect(() => {
    cargarResumen();
    return () => resumenAbortRef.current?.abort();
  }, []);
  useEffect(() => {
    const ctrl = new AbortController();
    cargarItems(ctrl.signal);
    return () => ctrl.abort();
  }, [tab, desde, hasta]);
  useEffect(() => {
    api.get("/api/caja-diaria/sugerencias").then((r) => setCajasList(r.data.cajas || []));
  }, []);

  return (
    <>
      <h2>Conciliación financiera {loading && <span className="spinner" />}</h2>
      <p style={{ color: "#94a3b8", marginTop: -10 }}>
        Compara <b>lo facturado</b> con <b>lo que efectivamente entró a las cajas</b>.
        Identifica los gaps para que puedas corregir los datos sucios y llevar finanzas precisas.
      </p>

      <DateRange desde={desde} hasta={hasta} setDesde={setDesde} setHasta={setHasta}>
        <button className="btn" onClick={() => { cargarResumen(); cargarItems(); }}>Aplicar</button>
      </DateRange>
      <div className="toolbar">
        <span style={{ fontSize: 12, color: "#94a3b8" }}>Atajos:</span>
        <PeriodPresets
          setDesde={setDesde} setHasta={setHasta}
          onApply={(d, h) => cargarResumen(d, h)}
        />
        {/* cargarItems tiene useEffect en [desde,hasta] → actualiza solo
            cuando el state se flushe — no necesita override directo. */}
      </div>

      {resumen && (
        <>
          <div className="kpi-grid">
            <KpiCard label="Facturado" value={fmtMoney(resumen.facturado)} sub="suma de Venta.total" />
            <KpiCard label="Ingreso operativo" value={fmtMoney(resumen.ingreso_operativo)} tone="green" sub="cobrado en cajas + cobranzas cta cte" />
            <KpiCard
              label="Cobertura"
              value={fmtPct(resumen.cobertura_pct)}
              tone={resumen.cobertura_pct >= 95 ? "green" : resumen.cobertura_pct >= 85 ? "amber" : "red"}
              sub="ingreso operativo / facturado"
            />
            <KpiCard label="Diferencia (gap)" value={fmtMoney(resumen.diferencia_facturado_vs_operativo)} tone="red" sub="facturado - ingreso operativo" />
          </div>

          <div className="panel">
            <h3>Desglose del ingreso</h3>
            <div className="kpi-grid" style={{ marginBottom: 0 }}>
              <KpiCard label="Cobrado en cajas" value={fmtMoney(resumen.cobrado_en_caja)} sub="al hacer la venta (montoPago1+2)" />
              <KpiCard label="Cobranzas cta cte" value={fmtMoney(resumen.cobranzas_cta_cte)} sub="movimientos: Ingreso / paga cta cte" />
              <KpiCard label="Otros ingresos" value={fmtMoney(resumen.otros_ingresos_movimientos)} sub="movimientos NO operativos (FC, etc.)" />
              <KpiCard label="Ingreso real total" value={fmtMoney(resumen.ingreso_real_total)} sub="incluye otros (no comercial)" />
            </div>
          </div>

          <div className="panel">
            <h3>Causas del gap</h3>
            <div className="kpi-grid" style={{ marginBottom: 0 }}>
              <KpiCard
                label="Ventas SIN cobro"
                value={fmtNum(resumen.ventas_sin_cobro.cantidad)}
                tone="red"
                sub={`${fmtMoney(resumen.ventas_sin_cobro.monto_total)} - falta forma de pago`}
              />
              <KpiCard
                label="Ventas en cta cte"
                value={fmtNum(resumen.ventas_cta_cte.cantidad)}
                tone="amber"
                sub={`${fmtMoney(resumen.ventas_cta_cte.monto_total)} - facturado, sin cobrar todavía`}
              />
              <KpiCard
                label="Discrepancias chicas"
                value={fmtNum(resumen.ventas_con_discrepancia.cantidad)}
                sub={`${fmtMoney(resumen.ventas_con_discrepancia.diferencia_total)} (vuelto/descuento al momento)`}
              />
            </div>
          </div>
        </>
      )}

      <div className="toolbar" style={{ marginTop: 20 }}>
        <button className={tab === "sin-cobro" ? "btn" : "btn-ghost btn"} onClick={() => setTab("sin-cobro")}>
          Ventas sin cobro
        </button>
        <button className={tab === "discrepancias" ? "btn" : "btn-ghost btn"} onClick={() => setTab("discrepancias")}>
          Discrepancias (pago ≠ total)
        </button>
        <button className={tab === "cta-cte" ? "btn" : "btn-ghost btn"} onClick={() => setTab("cta-cte")}>
          Cta cte emitidas
        </button>
      </div>

      <div className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>{itemsTotal} {tab === "sin-cobro" ? "ventas sin cobro" : tab === "discrepancias" ? "ventas con discrepancia" : "cuentas corrientes"}</h3>
          {items.length > 0 && (
            <button
              className="btn-ghost btn"
              onClick={() => descargarComoCSV(
                `conciliacion-${tab}-${new Date().toISOString().slice(0, 10)}.csv`,
                COLS_CSV[tab],
                items,
              )}
              title="Descargar la tabla en CSV"
              style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12 }}
            >
              <Icon name="download" size={12} /> CSV
            </button>
          )}
        </div>
        {items.length === 0 && <div className="empty">Nada para mostrar 🎉</div>}
        {items.length > 0 && tab === "sin-cobro" && (
          <table>
            <thead><tr><th>Fecha</th><th>Cliente</th><th>Vendedor</th><th className="num">Total</th><th></th></tr></thead>
            <tbody>
              {items.map((v) => (
                <Fragment key={v.id_pedido}>
                  <tr>
                    <td>{v.fecha?.slice(0, 10)}</td>
                    <td>{v.cliente}</td>
                    <td>{v.vendedor}</td>
                    <td className="num">{fmtMoney(v.total)}</td>
                    <td>
                      <button
                        className="btn-ghost btn"
                        onClick={() => setEditando(editando === v.id_pedido ? null : v.id_pedido)}
                      >
                        {editando === v.id_pedido ? "Cerrar" : "Editar"}
                      </button>
                    </td>
                  </tr>
                  {editando === v.id_pedido && (
                    <tr>
                      <td colSpan={5} style={{ background: "#0f172a", padding: 0 }}>
                        <EditarVentaFila
                          venta={v}
                          cajasDisponibles={cajasList}
                          onCancel={() => setEditando(null)}
                          onSaved={() => { setEditando(null); cargarItems(); cargarResumen(); }}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
        {items.length > 0 && tab === "discrepancias" && (
          <table>
            <thead><tr><th>Fecha</th><th>Cliente</th><th className="num">Total</th><th className="num">Pago 1</th><th className="num">Pago 2</th><th className="num">Suma</th><th className="num">Diferencia</th></tr></thead>
            <tbody>
              {items.map((v) => (
                <tr key={v.id_pedido}>
                  <td>{v.fecha?.slice(0, 10)}</td>
                  <td>{v.cliente}</td>
                  <td className="num">{fmtMoney(v.total)}</td>
                  <td className="num">{v.monto_pago1 ? fmtMoney(v.monto_pago1) : "-"}</td>
                  <td className="num">{v.monto_pago2 ? fmtMoney(v.monto_pago2) : "-"}</td>
                  <td className="num">{fmtMoney(v.suma_pagos)}</td>
                  <td className="num" style={{ color: v.diferencia > 0 ? "#fbbf24" : "#34d399" }}>{fmtMoney(v.diferencia)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {items.length > 0 && tab === "cta-cte" && (
          <>
            <div style={{ marginBottom: 12, fontSize: 12, color: "#94a3b8" }}>
              ⓘ Estas son ventas <b>emitidas</b> como cta cte en el período. Para ver saldos NETOS por cliente
              (descontando cobranzas vinculadas), andá a <b>Cuentas corrientes</b>.
            </div>
            <table>
              <thead><tr><th>Fecha</th><th>Cliente</th><th>Vendedor</th><th className="num">Total</th></tr></thead>
              <tbody>
                {items.map((v) => (
                  <tr key={v.id_pedido}>
                    <td>{v.fecha?.slice(0, 10)}</td>
                    <td>{v.cliente}</td>
                    <td>{v.vendedor}</td>
                    <td className="num">{fmtMoney(v.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </>
  );
}
