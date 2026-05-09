import { Fragment, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api, { fmtMoney, fmtNum, urlBackend } from "../api/client";
import { descargarComoCSV } from "../api/csvExport";
import AplicarPagoModal from "../components/AplicarPagoModal";
import { useConfirm } from "../components/ConfirmDialog";
import EditarVentaFila from "../components/EditarVentaFila";
import Icon from "../components/Icon";
import KpiCard from "../components/KpiCard";
import { SkeletonPanel } from "../components/Skeleton";
import SortableTable from "../components/SortableTable";
import { useToast } from "../components/Toast";

export default function CuentasCorrientes() {
  const [clientes, setClientes] = useState([]);
  const [filtro, setFiltro] = useState("");
  const [seleccionado, setSeleccionado] = useState(null);
  const [loading, setLoading] = useState(false);
  const [aging, setAging] = useState(null);
  const [dsoData, setDsoData] = useState(null);
  const [dsoDias, setDsoDias] = useState(90);
  // Soporta deep link desde la búsqueda global: `?cliente=42` abre el
  // detalle del cliente directamente. Limpia el param tras abrir para
  // que un refresh no quede en bucle si el usuario navega y vuelve.
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const cid = searchParams.get("cliente");
    if (!cid) return;
    // Validar que sea un número positivo: alguien podría manipular la URL
    // a `?cliente=abc` y `Number("abc") = NaN` rompería el detalle dejando
    // "Cargando..." perpetuo. Limpiamos el param igual para no quedarnos
    // en bucle.
    const n = Number(cid);
    if (Number.isFinite(n) && n > 0) {
      setSeleccionado(n);
    }
    // Patrón funcional: NO mutar la referencia del hook, construir nueva
    // URLSearchParams. El anti-patrón anterior (mutar y setear la misma
    // referencia) funciona en RR v6 pero genera comportamiento raro si
    // alguien la reusa.
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("cliente");
      return next;
    }, { replace: true });
  }, [searchParams, setSearchParams]);

  async function cargarClientes(signal) {
    setLoading(true);
    try {
      const { data } = await api.get("/api/cuentas-corrientes/clientes", { signal });
      setClientes(data);
      const [agData, dsoRes] = await Promise.all([
        api.get("/api/cuentas-corrientes/aging", { signal }),
        api.get("/api/cuentas-corrientes/dso", { params: { dias: dsoDias }, signal }),
      ]);
      setAging(agData.data);
      setDsoData(dsoRes.data);
    } catch (e) {
      if (e.name !== "CanceledError" && e.code !== "ERR_CANCELED") throw e;
    } finally { setLoading(false); }
  }

  useEffect(() => {
    const ctrl = new AbortController();
    cargarClientes(ctrl.signal);
    return () => ctrl.abort();
  }, [dsoDias]);

  const filtrados = clientes.filter((c) => {
    const nombre = (c.cliente || "").toLowerCase();
    const f = filtro.toLowerCase();
    return nombre.includes(f) || String(c.id_cliente || "").includes(filtro);
  });

  const totalSaldo = clientes.reduce((s, c) => s + c.saldo, 0);
  const conSaldo = clientes.filter((c) => c.saldo > 0).length;

  return (
    <>
      <h2>Cuentas corrientes {loading && <span className="spinner" />}</h2>
      <p style={{ color: "#94a3b8", marginTop: -10 }}>
        Clientes con saldo pendiente. Incluye ventas <b>marcadas como cta cte</b> y ventas <b>sin cobro registrado</b>
        (probable cta cte mal etiquetada). Click en un cliente para ver su extracto y asignarle pagos.
      </p>

      <div className="kpi-grid">
        <KpiCard label="Clientes con saldo" value={fmtNum(conSaldo)} sub={`de ${clientes.length} con actividad`} />
        <KpiCard label="Saldo total a cobrar" value={fmtMoney(totalSaldo)} tone="amber" />
        <KpiCard
          label={(
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              DSO
              <select
                value={dsoDias}
                onChange={(e) => setDsoDias(Number(e.target.value))}
                onClick={(e) => e.stopPropagation()}
                style={{ fontSize: 11, padding: "2px 6px", height: "auto" }}
                title="Ventana de cálculo: a más días, suaviza picos puntuales"
              >
                <option value={30}>30d</option>
                <option value={60}>60d</option>
                <option value={90}>90d</option>
                <option value={180}>180d</option>
                <option value={365}>365d</option>
              </select>
            </span>
          )}
          value={dsoData?.dso_aprox_dias != null ? `${dsoData.dso_aprox_dias} días` : "-"}
          sub="días promedio cobro (aprox)"
        />
        <KpiCard label="Top deudor" value={clientes[0]?.cliente || "-"} sub={fmtMoney(clientes[0]?.saldo || 0)} />
      </div>

      {/* Espejo del aging proveedores: si no hay items, escondemos el
          panel entero — sino quedaría con KPI cards en cero sin tabla,
          UX confusa. La condición de KPIs y tabla queda atada a la
          existencia de items para coherencia visual. */}
      {aging && !seleccionado && aging.items.length > 0 && (
        <div className="panel">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h3 style={{ margin: 0 }}>Aging de saldos pendientes</h3>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                className="btn-ghost btn"
                onClick={() => descargarComoCSV(
                  `aging-clientes-${new Date().toISOString().slice(0, 10)}.csv`,
                  [
                    { key: "cliente", label: "Cliente" },
                    { key: "bucket_0_30", label: "0-30 días" },
                    { key: "bucket_31_60", label: "31-60" },
                    { key: "bucket_61_90", label: "61-90" },
                    { key: "bucket_90_mas", label: "90+" },
                    { key: "total", label: "Total" },
                  ],
                  aging.items,
                )}
                title="Descargar aging por cliente en CSV"
                style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12 }}
              >
                <Icon name="download" size={12} /> CSV
              </button>
              <a
                className="btn-ghost btn"
                href={urlBackend("/api/cuentas-corrientes/aging.pdf")}
                download
                title="Imprimir el aging completo (PDF para revisar con contador)"
                style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
              >
                <Icon name="download" size={14} /> Imprimir aging
              </a>
            </div>
          </div>
          <div className="kpi-grid" style={{ marginBottom: 14 }}>
            <KpiCard label="0-30 días" value={fmtMoney(aging.totales.bucket_0_30)} tone="green" />
            <KpiCard label="31-60 días" value={fmtMoney(aging.totales.bucket_31_60)} tone="amber" />
            <KpiCard label="61-90 días" value={fmtMoney(aging.totales.bucket_61_90)} tone="amber" />
            <KpiCard label="+90 días" value={fmtMoney(aging.totales.bucket_90_mas)} tone="red" sub="morosidad" />
          </div>
          <table>
            <thead>
              <tr>
                <th>Cliente</th>
                <th className="num">0-30 días</th>
                <th className="num">31-60</th>
                <th className="num">61-90</th>
                <th className="num">90+</th>
                <th className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {aging.items.map((it) => (
                <tr key={it.id_cliente}>
                  <td>
                    <a href="#" onClick={(e) => { e.preventDefault(); setSeleccionado(it.id_cliente); }}>
                      {it.cliente || `(ID ${it.id_cliente})`}
                    </a>
                  </td>
                  <td className="num" style={{ color: it.bucket_0_30 > 0 ? "#cbd5e1" : "#475569" }}>
                    {it.bucket_0_30 > 0 ? fmtMoney(it.bucket_0_30) : "-"}
                  </td>
                  <td className="num" style={{ color: it.bucket_31_60 > 0 ? "#fbbf24" : "#475569" }}>
                    {it.bucket_31_60 > 0 ? fmtMoney(it.bucket_31_60) : "-"}
                  </td>
                  <td className="num" style={{ color: it.bucket_61_90 > 0 ? "#fb923c" : "#475569" }}>
                    {it.bucket_61_90 > 0 ? fmtMoney(it.bucket_61_90) : "-"}
                  </td>
                  <td className="num" style={{ color: it.bucket_90_mas > 0 ? "#f87171" : "#475569", fontWeight: it.bucket_90_mas > 0 ? 600 : 400 }}>
                    {it.bucket_90_mas > 0 ? fmtMoney(it.bucket_90_mas) : "-"}
                  </td>
                  <td className="num" style={{ fontWeight: 600 }}>{fmtMoney(it.total)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr style={{ borderTop: "2px solid #334155", fontWeight: 600 }}>
                <td>Totales</td>
                <td className="num">{fmtMoney(aging.totales.bucket_0_30)}</td>
                <td className="num">{fmtMoney(aging.totales.bucket_31_60)}</td>
                <td className="num">{fmtMoney(aging.totales.bucket_61_90)}</td>
                <td className="num">{fmtMoney(aging.totales.bucket_90_mas)}</td>
                <td className="num">{fmtMoney(aging.totales.total)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {/* Clientes con saldo a favor — sobrepagos / anticipos. Útil para
          la dueña que ve "le debo a este cliente" antes de cobrarle más. */}
      {aging && !seleccionado && aging.con_credito && aging.con_credito.length > 0 && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>
            Clientes con saldo a favor
            <span style={{ fontSize: 12, color: "#94a3b8", fontWeight: 400, marginLeft: 8 }}>
              (sobrepagos / anticipos — descontar antes del próximo cobro)
            </span>
          </h3>
          <table>
            <thead>
              <tr>
                <th>Cliente</th>
                <th className="num">Crédito a favor</th>
              </tr>
            </thead>
            <tbody>
              {aging.con_credito.map((c) => (
                <tr key={c.id_cliente}>
                  <td>
                    <a href="#" onClick={(e) => { e.preventDefault(); setSeleccionado(c.id_cliente); }}>
                      {c.cliente || `(ID ${c.id_cliente})`}
                    </a>
                  </td>
                  <td className="num" style={{ color: "#34d399", fontWeight: 600 }}>
                    {fmtMoney(c.credito_a_favor)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {seleccionado ? (
        <DetalleCliente
          idCliente={seleccionado}
          onClose={() => { setSeleccionado(null); cargarClientes(); }}
        />
      ) : (
        <div className="panel">
          <h3>Clientes con cuenta corriente</h3>
          <input
            placeholder="Buscar por nombre o ID..."
            value={filtro}
            onChange={(e) => setFiltro(e.target.value)}
            style={{ marginBottom: 12, width: 280 }}
          />
          <SortableTable
            rowKey={(c) => c.id_cliente}
            rows={filtrados}
            initialSort={{ key: "saldo", dir: "desc" }}
            exportCSV={{ filename: `cuentas-corrientes-${new Date().toISOString().slice(0, 10)}.csv` }}
            columns={[
              { key: "id_cliente", label: "ID", num: true },
              { key: "cliente", label: "Cliente", render: (c) => (
                <a href="#" onClick={(e) => { e.preventDefault(); setSeleccionado(c.id_cliente); }}>{c.cliente}</a>
              ), csvFormat: (c) => c.cliente },
              { key: "ventas_pendientes", label: "Ventas pend.", num: true, render: (c) => fmtNum(c.ventas_pendientes) },
              { key: "monto_cargado", label: "Cargado", num: true, render: (c) => fmtMoney(c.monto_cargado) },
              { key: "monto_pagado", label: "Pagado", num: true, render: (c) => fmtMoney(c.monto_pagado) },
              { key: "saldo", label: "Saldo", num: true, render: (c) => (
                <span style={{ color: c.saldo > 0 ? "#fbbf24" : c.saldo < 0 ? "#34d399" : "#94a3b8", fontWeight: 600 }}>
                  {fmtMoney(c.saldo)}
                </span>
              ), csvFormat: (c) => c.saldo },
            ]}
          />
        </div>
      )}
    </>
  );
}

function DetalleCliente({ idCliente, onClose }) {
  const confirmar = useConfirm();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [sinAsignar, setSinAsignar] = useState([]);
  const [busqueda, setBusqueda] = useState("");
  const [editandoVenta, setEditandoVenta] = useState(null);
  const [cajasList, setCajasList] = useState([]);
  const [movAplicando, setMovAplicando] = useState(null);

  async function cargarLedger(signal) {
    try {
      const { data } = await api.get(`/api/cuentas-corrientes/${idCliente}/ledger`, { signal });
      setData(data);
    } catch (e) {
      if (e.name === "CanceledError" || e.code === "ERR_CANCELED") return;
      // Si el cliente no existe o el id es inválido, en lugar de quedar
      // colgado en "Cargando..." indefinido cerramos el detalle y avisamos.
      // Caso típico: deep link con id de un cliente borrado entre el search
      // y el click, o id manipulado por URL.
      console.error("Error cargando ledger", e);
      const detalle = e.response?.data?.detail || "No se pudo cargar el cliente";
      toast.push(detalle, "error");
      onClose();
    }
  }

  async function cargarSinAsignar(b, signal) {
    try {
      const { data } = await api.get("/api/cuentas-corrientes/movimientos-sin-asignar", {
        params: b ? { busqueda: b, limite: 50 } : { limite: 30 },
        signal,
      });
      setSinAsignar(data);
    } catch (e) {
      if (e.name === "CanceledError" || e.code === "ERR_CANCELED") return;
      console.error("Error cargando movimientos sin asignar", e);
    }
  }

  // Ledger: solo cuando cambia el cliente
  useEffect(() => {
    const ctrl = new AbortController();
    cargarLedger(ctrl.signal);
    return () => ctrl.abort();
  }, [idCliente]);
  useEffect(() => {
    api.get("/api/caja-diaria/sugerencias").then((r) => setCajasList(r.data.cajas || []));
  }, []);

  // Movimientos sin asignar: debounce 300ms cuando cambia la búsqueda
  useEffect(() => {
    const ctrl = new AbortController();
    const t = setTimeout(() => cargarSinAsignar(busqueda, ctrl.signal), 300);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [busqueda, idCliente]);

  async function asignar(movId) {
    try {
      await api.post(`/api/cuentas-corrientes/movimiento/${movId}/asignar`, { id_cliente: idCliente });
      cargarLedger();
      cargarSinAsignar(busqueda);
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error asignando movimiento", "error");
    }
  }

  async function desasignarMov(movId) {
    await api.post(`/api/cuentas-corrientes/movimiento/${movId}/desasignar`);
    cargarLedger();
    cargarSinAsignar(busqueda);
  }

  async function toggleCtaCte(idPedido, esCtaCteActual, forzar = false) {
    try {
      await api.post(`/api/cuentas-corrientes/venta/${encodeURIComponent(idPedido)}/marcar-cta-cte`, {
        es_cuenta_corriente: !esCtaCteActual,
        forzar,
      });
      cargarLedger();
    } catch (e) {
      if (e.response?.status === 409) {
        const ok = await confirmar({
          titulo: "Confirmar desmarcado",
          mensaje: e.response.data.detail + "\n\n¿Forzar el desmarcado igualmente?",
          labelOk: "Forzar",
          peligroso: true,
        });
        if (ok) toggleCtaCte(idPedido, esCtaCteActual, true);
      } else {
        toast.push(e.response?.data?.detail || "Error", "error");
      }
    }
  }

  // Ventas con saldo pendiente del cliente, derivadas del ledger en frontend.
  // El backend ya descuenta pagos vinculados via ledger_cliente; lo que queda
  // como "saldo neto" de cada venta lo calculamos con FIFO simple sobre el
  // saldo total del cliente. Para la UI alcanza con: cualquier venta cuyo
  // total supere lo cobrado al cliente, con saldo proporcional desde la
  // venta más antigua. Más simple: ofrecemos todas las ventas y dejamos que
  // el backend valide saldo_venta real al aplicar.
  const ventasPendientes = useMemo(() => {
    if (!data) return [];
    return data.eventos
      .filter((e) => e.ref_tipo === "venta")
      .map((e) => ({
        id_pedido: e.ref_id,
        descripcion: e.descripcion,
        fecha: e.fecha,
        // Saldo "estimado" para ordenar: el backend valida el real al aplicar.
        saldo: e.debe,
      }))
      .sort((a, b) => (a.fecha < b.fecha ? -1 : 1));
  }, [data]);

  if (!data) {
    // Skeleton del drilldown: mantenemos botón Volver funcional para que
    // la dueña pueda cancelar si la carga del ledger se demora (ej: cliente
    // con miles de movimientos). El resto se aproxima con SkeletonPanel.
    return (
      <>
        <div className="toolbar">
          <button className="btn-ghost btn" onClick={onClose}>← Volver al listado</button>
        </div>
        <SkeletonPanel rows={6} />
      </>
    );
  }

  return (
    <>
      <div className="toolbar">
        <button className="btn-ghost btn" onClick={onClose}>← Volver al listado</button>
        <span style={{ fontSize: 16, color: "#f1f5f9", marginLeft: 16, flex: 1 }}>
          <b>{data.cliente}</b> (ID {data.id_cliente})
        </span>
        <a
          className="btn"
          href={urlBackend(`/api/cuentas-corrientes/${idCliente}/extracto.pdf`)}
          download
          title="Descargar extracto en PDF (mandar por mail/WhatsApp)"
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <Icon name="download" size={14} /> Descargar PDF
        </a>
        <a
          className="btn-ghost btn"
          href={urlBackend(`/api/cuentas-corrientes/${idCliente}/extracto.csv`)}
          download
          title="Descargar extracto en CSV (Excel-compatible)"
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <Icon name="download" size={14} /> CSV
        </a>
      </div>

      <div className="kpi-grid">
        <KpiCard label="Saldo actual" value={fmtMoney(data.saldo_actual)} tone={data.saldo_actual > 0 ? "amber" : "green"} />
        <KpiCard label="Total cargado (DEBE)" value={fmtMoney(data.total_debe)} />
        <KpiCard label="Total pagado (HABER)" value={fmtMoney(data.total_haber)} />
        <KpiCard label="Eventos" value={fmtNum(data.eventos.length)} />
      </div>

      <div className="panel">
        <h3>Extracto cronológico</h3>
        {data.eventos.length === 0 && <div className="empty">Sin eventos.</div>}
        {data.eventos.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Tipo</th>
                <th>Descripción</th>
                <th className="num">Debe</th>
                <th className="num">Haber</th>
                <th className="num">Saldo</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.eventos.map((e, i) => (
                <Fragment key={`${e.ref_tipo}-${e.ref_id}`}>
                  <tr>
                    <td>{e.fecha.slice(0, 10)}</td>
                    <td><span className={`badge ${e.tipo === "venta" ? "warn" : "ok"}`}>{e.tipo}</span></td>
                    <td>{e.descripcion}</td>
                    <td className="num" style={{ color: e.debe > 0 ? "#fbbf24" : "#475569" }}>
                      {e.debe > 0 ? fmtMoney(e.debe) : "-"}
                    </td>
                    <td className="num" style={{ color: e.haber > 0 ? "#34d399" : "#475569" }}>
                      {e.haber > 0 ? fmtMoney(e.haber) : "-"}
                    </td>
                    <td className="num" style={{ fontWeight: 600 }}>{fmtMoney(e.saldo)}</td>
                    <td>
                      {e.ref_tipo === "movimiento" && (
                        <>
                          <button
                            className="btn"
                            style={{ marginRight: 6 }}
                            onClick={() => setMovAplicando({
                              id: e.ref_id,
                              monto: e.haber,
                              fecha: e.fecha,
                              descripcion: e.descripcion,
                            })}
                            title="Aplicar este pago a una venta específica del cliente"
                          >
                            Aplicar a venta
                          </button>
                          <button className="btn-ghost btn" onClick={() => desasignarMov(e.ref_id)}>Desvincular</button>
                        </>
                      )}
                      {e.ref_tipo === "venta" && (
                        <button
                          className="btn-ghost btn"
                          onClick={() => setEditandoVenta(editandoVenta === e.ref_id ? null : e.ref_id)}
                        >
                          {editandoVenta === e.ref_id ? "Cerrar" : "Editar"}
                        </button>
                      )}
                    </td>
                  </tr>
                  {editandoVenta === e.ref_id && e.ref_tipo === "venta" && (
                    <tr>
                      <td colSpan={7} style={{ background: "#0f172a", padding: 0 }}>
                        <EditarVentaFila
                          venta={{ id_pedido: e.ref_id, ...e }}
                          cajasDisponibles={cajasList}
                          onCancel={() => setEditandoVenta(null)}
                          onSaved={() => { setEditandoVenta(null); cargarLedger(); }}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {movAplicando && (
        <AplicarPagoModal
          movimiento={movAplicando}
          ventasPendientes={ventasPendientes}
          onClose={() => setMovAplicando(null)}
          onAplicado={() => { setMovAplicando(null); cargarLedger(); }}
        />
      )}

      <div className="panel">
        <h3>Movimientos sin asignar — vincular a {data.cliente}</h3>
        <div style={{ marginBottom: 12, fontSize: 13, color: "#94a3b8" }}>
          Estos son cobranzas (categorías Ingreso / paga cuenta corriente) que todavía no fueron vinculadas a ningún cliente.
          Buscá por palabra del detalle (ej. apellido del cliente) y asigná las que correspondan.
        </div>
        <input
          placeholder={`Buscar en detalle... (ej. "${data.cliente.split(' ')[0]}")`}
          value={busqueda}
          onChange={(e) => setBusqueda(e.target.value)}
          style={{ marginBottom: 12, width: 360 }}
        />
        {sinAsignar.length === 0 && <div className="empty">No hay movimientos sin asignar con esa búsqueda.</div>}
        {sinAsignar.length > 0 && (
          <table>
            <thead>
              <tr><th>Fecha</th><th>Tipo</th><th>Detalle</th><th>Caja</th><th className="num">Monto</th><th></th></tr>
            </thead>
            <tbody>
              {sinAsignar.map((m) => (
                <tr key={m.id}>
                  <td>{m.fecha}</td>
                  <td><span className="badge muted">{m.tipo_operacion}</span></td>
                  <td>{m.detalle}</td>
                  <td>{m.caja_destino}</td>
                  <td className="num">{fmtMoney(m.monto)}</td>
                  <td>
                    <button className="btn" onClick={() => asignar(m.id)}>Asignar →</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
