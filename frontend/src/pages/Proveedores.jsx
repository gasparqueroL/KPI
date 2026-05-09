import { Fragment, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api, { fmtMoney, fmtNum, urlBackend } from "../api/client";
import { descargarComoCSV } from "../api/csvExport";
import AnularFacturaModal from "../components/AnularFacturaModal";
import EditarFacturaModal from "../components/EditarFacturaModal";
import Icon from "../components/Icon";
import { useConfirm } from "../components/ConfirmDialog";
import KpiCard from "../components/KpiCard";
import { SkeletonPanel } from "../components/Skeleton";
import SortableTable from "../components/SortableTable";
import { useToast } from "../components/Toast";

export default function Proveedores() {
  const toast = useToast();
  const [proveedores, setProveedores] = useState([]);
  const [vencimientos, setVencimientos] = useState([]);
  const [aging, setAging] = useState(null);
  const [agingBase, setAgingBase] = useState("vencimiento");
  const [filtro, setFiltro] = useState("");
  const [seleccionado, setSeleccionado] = useState(null);
  // Si vino con `?factura=ID` desde la búsqueda global, guardamos ese id
  // para pasárselo al DetalleProveedor y que haga scroll/highlight en la
  // fila correspondiente del ledger.
  const [facturaInicial, setFacturaInicial] = useState(null);
  const [showAlta, setShowAlta] = useState(false);
  // Soporta deep link desde la búsqueda global: `?proveedor=12` abre el
  // detalle del proveedor (también se usa cuando se busca una factura,
  // que linkea al proveedor de la factura). `?factura=99` opcional, marca
  // la fila para resaltar.
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const pid = searchParams.get("proveedor");
    if (!pid) return;
    // URL manipulada con `?proveedor=abc` daría NaN → "Cargando..." perpetuo.
    const n = Number(pid);
    if (Number.isFinite(n) && n > 0) {
      setSeleccionado(n);
      // Reset explícito: si llega un nuevo deep link sin `?factura=`,
      // no queremos arrastrar el id de la búsqueda anterior (sería scroll
      // fantasma si por casualidad el proveedor nuevo tiene factura con
      // ese mismo id).
      const fid = searchParams.get("factura");
      const fn = Number(fid);
      setFacturaInicial(Number.isFinite(fn) && fn > 0 ? fn : null);
    }
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("proveedor");
      next.delete("factura");
      return next;
    }, { replace: true });
  }, [searchParams, setSearchParams]);

  // Ref-based abort: cargar() se invoca desde useEffect Y desde handlers
  // post-acción (cierre de modal, alta, vincular). Centralizar el aborto
  // evita que un cargar() viejo pise state después de un action reciente.
  const cargarAbortRef = useRef(null);

  const [dpo, setDpo] = useState(null);
  const [dependencia, setDependencia] = useState(null);

  async function cargar() {
    cargarAbortRef.current?.abort();
    const ctrl = new AbortController();
    cargarAbortRef.current = ctrl;
    try {
      const [p, v, a, dp, dep] = await Promise.all([
        api.get("/api/proveedores", { signal: ctrl.signal }),
        api.get("/api/proveedores/vencimientos-proximos", { params: { dias: 30 }, signal: ctrl.signal }),
        api.get("/api/proveedores/aging", { params: { base: agingBase }, signal: ctrl.signal }),
        api.get("/api/kpis/financieros/dpo", { signal: ctrl.signal }),
        api.get("/api/kpis/financieros/dependencia-proveedores", { params: { top: 5 }, signal: ctrl.signal }),
      ]);
      if (cargarAbortRef.current !== ctrl) return;
      setProveedores(p.data);
      setVencimientos(v.data);
      setAging(a.data);
      setDpo(dp.data);
      setDependencia(dep.data);
    } catch (e) {
      if (e.name !== "CanceledError" && e.code !== "ERR_CANCELED") throw e;
    }
  }

  useEffect(() => {
    cargar();
    return () => cargarAbortRef.current?.abort();
  }, [agingBase]);

  const filtrados = proveedores.filter((p) =>
    (p.nombre || "").toLowerCase().includes(filtro.toLowerCase()) ||
    (p.cuit || "").includes(filtro)
  );

  const totalSaldo = proveedores.reduce((s, p) => s + p.saldo, 0);
  const conSaldo = proveedores.filter((p) => p.saldo > 0).length;
  const vencidas = vencimientos.filter((v) => v.vencida).length;

  return (
    <>
      <h2>Proveedores / Cuentas a pagar</h2>
      <p style={{ color: "#94a3b8", marginTop: -10 }}>
        Catálogo de proveedores con saldos pendientes y vencimientos próximos. Vinculá pagos (egresos de caja) a facturas para llevar la cta cte por proveedor.
      </p>

      <div className="kpi-grid">
        <KpiCard label="Proveedores con saldo" value={fmtNum(conSaldo)} sub={`de ${proveedores.length} totales`} />
        <KpiCard label="Total a pagar" value={fmtMoney(totalSaldo)} tone="amber" />
        <KpiCard label="Vencen en 30 días" value={fmtNum(vencimientos.length)} sub={vencidas > 0 ? `${vencidas} ya vencidas` : "ninguna vencida"} tone={vencidas > 0 ? "red" : undefined} />
        <KpiCard
          label="DPO (días promedio de pago)"
          value={dpo?.dpo_dias != null ? `${dpo.dpo_dias.toFixed(1)} días` : "—"}
          sub={dpo?.facturas_consideradas ? `${dpo.facturas_consideradas} facturas saldadas` : "sin datos suficientes"}
        />
        <KpiCard
          label="Concentración top 1 proveedor"
          value={dependencia?.concentracion?.top_1_pct != null ? `${dependencia.concentracion.top_1_pct.toFixed(1)}%` : "—"}
          sub={dependencia?.top?.[0]?.nombre ? `top: ${dependencia.top[0].nombre}` : "sin facturas"}
          tone={(() => {
            const u = dependencia?.concentracion?.umbrales || dependencia?.umbrales || { top1_atencion: 30, top1_critica: 50 };
            const p = dependencia?.concentracion?.top_1_pct;
            if (p == null) return undefined;
            if (p >= u.top1_critica) return "red";
            if (p >= u.top1_atencion) return "amber";
            return undefined;
          })()}
        />
      </div>

      {dependencia?.top?.length > 0 && !seleccionado && (
        <div className="panel">
          <h3>Dependencia de proveedores</h3>
          <p style={{ color: "#94a3b8", fontSize: 12, marginTop: -6 }}>
            % del costo total de compras concentrado por proveedor.
            Top {dependencia.top.length} = {dependencia.concentracion.top_n_pct.toFixed(1)}% del total
            ({fmtMoney(dependencia.total_compras)}).
          </p>
          <table>
            <thead>
              <tr>
                <th>Proveedor</th>
                <th className="num">Compras</th>
                <th className="num">Facturas</th>
                <th className="num">% del total</th>
              </tr>
            </thead>
            <tbody>
              {dependencia.top.map((d) => (
                <tr key={d.id_proveedor}>
                  <td>
                    <a href="#" onClick={(e) => { e.preventDefault(); setSeleccionado(d.id_proveedor); }}>
                      {d.nombre}
                    </a>
                  </td>
                  <td className="num">{fmtMoney(d.monto)}</td>
                  <td className="num">{fmtNum(d.facturas)}</td>
                  <td className="num" style={{ color: d.pct >= 30 ? "#fbbf24" : undefined }}>
                    {d.pct.toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {seleccionado ? (
        <DetalleProveedor
          idProveedor={seleccionado}
          facturaInicial={facturaInicial}
          onClose={() => { setSeleccionado(null); setFacturaInicial(null); cargar(); }}
        />
      ) : (
        <>
          {vencimientos.length > 0 && (
            <div className="panel">
              <h3>Vencimientos próximos (30 días)</h3>
              <table>
                <thead><tr><th>Vence</th><th>Proveedor</th><th>Factura</th><th className="num">Pendiente</th><th>Estado</th></tr></thead>
                <tbody>
                  {vencimientos.map((v) => (
                    <tr key={v.id_factura}>
                      <td>{v.fecha_vencimiento}</td>
                      <td><a href="#" onClick={(e) => { e.preventDefault(); setSeleccionado(v.id_proveedor); }}>{v.proveedor}</a></td>
                      <td>{v.numero || "(sin nro)"}</td>
                      <td className="num" style={{ fontWeight: 600 }}>{fmtMoney(v.pendiente)}</td>
                      <td>
                        {v.vencida
                          ? <span className="badge err">vencida {Math.abs(v.dias_para_vencer)}d</span>
                          : v.dias_para_vencer <= 7
                            ? <span className="badge warn">{v.dias_para_vencer}d</span>
                            : <span className="badge muted">{v.dias_para_vencer}d</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="panel">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <h3 style={{ margin: 0 }}>Proveedores</h3>
              <button className="btn" onClick={() => setShowAlta(true)}>+ Nuevo proveedor</button>
            </div>
            <input
              placeholder="Buscar por nombre o CUIT..."
              value={filtro}
              onChange={(e) => setFiltro(e.target.value)}
              style={{ marginBottom: 12, width: 280 }}
            />
            <SortableTable
              rowKey={(p) => p.id}
              rows={filtrados}
              initialSort={{ key: "saldo", dir: "desc" }}
              exportCSV={{ filename: `proveedores-${new Date().toISOString().slice(0, 10)}.csv` }}
              columns={[
                { key: "nombre", label: "Nombre", render: (p) => (
                  <a href="#" onClick={(e) => { e.preventDefault(); setSeleccionado(p.id); }}>{p.nombre}</a>
                ), csvFormat: (p) => p.nombre },
                { key: "cuit", label: "CUIT" },
                { key: "facturado_total", label: "Facturado", num: true, render: (p) => fmtMoney(p.facturado_total) },
                { key: "pagado_total", label: "Pagado", num: true, render: (p) => fmtMoney(p.pagado_total) },
                { key: "saldo", label: "Saldo", num: true, render: (p) => (
                  <span style={{ color: p.saldo > 0 ? "#fbbf24" : "#94a3b8", fontWeight: 600 }}>{fmtMoney(p.saldo)}</span>
                ), csvFormat: (p) => p.saldo },
              ]}
            />
            {filtrados.length === 0 && <div className="empty">No hay proveedores que coincidan.</div>}
          </div>

          {aging && aging.items.length > 0 && (
            <div className="panel">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <h3 style={{ margin: 0 }}>Aging de deuda por proveedor</h3>
                <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <span style={{ fontSize: 12, color: "#94a3b8" }}>Días desde:</span>
                    <select value={agingBase} onChange={(e) => setAgingBase(e.target.value)}>
                      <option value="vencimiento">vencimiento</option>
                      <option value="emision">emisión</option>
                    </select>
                  </div>
                  <button
                    className="btn-ghost btn"
                    onClick={() => descargarComoCSV(
                      `aging-proveedores-${agingBase}-${new Date().toISOString().slice(0, 10)}.csv`,
                      [
                        { key: "proveedor", label: "Proveedor" },
                        { key: "bucket_0_30", label: "0-30 días" },
                        { key: "bucket_31_60", label: "31-60" },
                        { key: "bucket_61_90", label: "61-90" },
                        { key: "bucket_90_mas", label: "90+" },
                        { key: "total", label: "Total" },
                      ],
                      aging.items,
                    )}
                    title="Descargar aging en CSV (Excel-compatible)"
                    style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12 }}
                  >
                    <Icon name="download" size={12} /> CSV
                  </button>
                  <a
                    className="btn-ghost btn"
                    href={urlBackend(`/api/proveedores/aging.pdf?base=${agingBase}`)}
                    download
                    title="Imprimir aging completo en PDF"
                    style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
                  >
                    <Icon name="download" size={14} /> Imprimir aging
                  </a>
                </div>
              </div>
              <table>
                <thead>
                  <tr>
                    <th>Proveedor</th>
                    <th className="num">0-30 días</th>
                    <th className="num">31-60</th>
                    <th className="num">61-90</th>
                    <th className="num">90+</th>
                    <th className="num">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {aging.items.map((it) => (
                    <tr key={it.id_proveedor}>
                      <td>
                        <a href="#" onClick={(e) => { e.preventDefault(); setSeleccionado(it.id_proveedor); }}>
                          {it.proveedor}
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

          {showAlta && <AltaProveedor onClose={() => setShowAlta(false)} onSaved={() => { setShowAlta(false); cargar(); }} />}
        </>
      )}
    </>
  );
}

function AltaProveedor({ onClose, onSaved }) {
  const toast = useToast();
  const [nombre, setNombre] = useState("");
  const [cuit, setCuit] = useState("");
  const [contacto, setContacto] = useState("");
  const [busy, setBusy] = useState(false);

  async function guardar() {
    if (!nombre.trim()) { toast.push("Nombre es obligatorio", "error"); return; }
    setBusy(true);
    try {
      await api.post("/api/proveedores", { nombre, cuit: cuit || null, contacto: contacto || null });
      toast.push("Proveedor creado", "success");
      onSaved();
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error", "error");
    } finally { setBusy(false); }
  }

  return (
    <div className="panel" style={{ marginTop: 12 }}>
      <h3>Nuevo proveedor</h3>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 2fr auto auto", gap: 10, alignItems: "end" }}>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Nombre *</label>
          <input value={nombre} onChange={(e) => setNombre(e.target.value)} style={{ width: "100%" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>CUIT</label>
          <input value={cuit} onChange={(e) => setCuit(e.target.value)} style={{ width: "100%" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Contacto</label>
          <input value={contacto} onChange={(e) => setContacto(e.target.value)} placeholder="tel/email/quien atiende" style={{ width: "100%" }} />
        </div>
        <button className="btn" disabled={busy} onClick={guardar}>{busy ? <span className="spinner" /> : "Guardar"}</button>
        <button className="btn-ghost btn" onClick={onClose}>Cancelar</button>
      </div>
    </div>
  );
}

function DetalleProveedor({ idProveedor, facturaInicial, onClose }) {
  const confirmar = useConfirm();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [showAltaFact, setShowAltaFact] = useState(false);
  const [sinAsignar, setSinAsignar] = useState([]);
  const [busqueda, setBusqueda] = useState("");
  const [vinculando, setVinculando] = useState(null);
  const [anulando, setAnulando] = useState(null);
  const [editando, setEditando] = useState(null);
  // Highlight temporal de la fila de factura cuando viene desde la búsqueda
  // global. Se setea una vez cargado el ledger, no antes (la fila aún no
  // existe en el DOM). 2.5s coincide con el patrón usado en CajaDiaria.
  const [facturaHighlight, setFacturaHighlight] = useState(null);
  // Recordamos qué `facturaInicial` ya scrolleamos para que un reload
  // del ledger (editar/anular factura) NO redispare el highlight. Solo
  // queremos resaltar una vez por valor entrante de `facturaInicial`.
  const facturaInicialProcesada = useRef(null);

  async function cargar(signal) {
    try {
      const { data } = await api.get(`/api/proveedores/${idProveedor}/ledger`, { signal });
      setData(data);
    } catch (e) {
      if (e.name === "CanceledError" || e.code === "ERR_CANCELED") return;
      // Mismo patrón que CuentasCorrientes: si el proveedor no existe
      // (id manipulado, proveedor borrado entre search y click), cerramos
      // en lugar de quedar en "Cargando..." perpetuo.
      console.error("Error cargando ledger proveedor", e);
      const detalle = e.response?.data?.detail || "No se pudo cargar el proveedor";
      toast.push(detalle, "error");
      onClose();
    }
  }
  async function cargarSinAsignar(b, signal) {
    try {
      const { data } = await api.get("/api/proveedores/movimientos-sin-asignar", {
        params: b ? { busqueda: b, limite: 50 } : { limite: 30 },
        signal,
      });
      setSinAsignar(data);
    } catch (e) {
      if (e.name !== "CanceledError" && e.code !== "ERR_CANCELED") throw e;
    }
  }
  useEffect(() => {
    const ctrl = new AbortController();
    cargar(ctrl.signal);
    return () => ctrl.abort();
  }, [idProveedor]);
  useEffect(() => {
    const ctrl = new AbortController();
    const t = setTimeout(() => cargarSinAsignar(busqueda, ctrl.signal), 300);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [busqueda, idProveedor]);

  // Cuando llega `facturaInicial` y el ledger ya cargó, scroll + highlight.
  // Solo dispara una vez por valor entrante: el ref `facturaInicialProcesada`
  // recuerda el último id que ya scrolleamos. Sin esto, un reload del ledger
  // (editar/anular una factura cualquiera) re-disparaba el scroll/highlight
  // de la factura del deep link original, lo cual era UX rara.
  useEffect(() => {
    if (!facturaInicial || !data) return;
    if (facturaInicialProcesada.current === facturaInicial) return;
    facturaInicialProcesada.current = facturaInicial;
    setFacturaHighlight(facturaInicial);
    const el = document.getElementById(`fila-factura-${facturaInicial}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    const t = setTimeout(() => setFacturaHighlight(null), 2500);
    return () => clearTimeout(t);
  }, [facturaInicial, data]);

  async function vincularA(movId, idFactura) {
    await api.post(`/api/proveedores/movimiento/${movId}/vincular`, {
      id_factura: idFactura,
      id_proveedor: idProveedor,
    });
    toast.push("Pago vinculado", "success");
    cargar(); cargarSinAsignar(busqueda); setVinculando(null);
  }
  async function desvincular(movId) {
    await api.post(`/api/proveedores/movimiento/${movId}/desvincular`);
    cargar(); cargarSinAsignar(busqueda);
  }

  if (!data) {
    // Skeleton del drilldown: mantenemos botón Volver funcional. Pattern
    // espejo del DetalleCliente — drilldowns frecuentes que no deben
    // bloquear la navegación.
    return (
      <>
        <div className="toolbar">
          <button className="btn-ghost btn" onClick={onClose}>← Volver</button>
        </div>
        <SkeletonPanel rows={6} />
      </>
    );
  }

  // Solo facturas vivas (no anuladas) y con saldo pendiente son candidatas
  // a recibir un pago — evita ofrecer facturas saldadas o muertas en el select.
  const facturasParaVincular = data.eventos.filter(
    (e) => e.ref_tipo === "factura" && !e.anulada && (e.pendiente == null || e.pendiente > 0)
  );

  return (
    <>
      <div className="toolbar">
        <button className="btn-ghost btn" onClick={onClose}>← Volver</button>
        <span style={{ fontSize: 16, color: "#f1f5f9", marginLeft: 16, flex: 1 }}>
          <b>{data.nombre}</b>
          {data.cuit && <span style={{ color: "#94a3b8", marginLeft: 8 }}>CUIT {data.cuit}</span>}
          {data.contacto && <span style={{ color: "#94a3b8", marginLeft: 12 }}>· {data.contacto}</span>}
        </span>
        <a
          className="btn"
          href={urlBackend(`/api/proveedores/${idProveedor}/extracto.pdf`)}
          download
          title="Descargar extracto en PDF"
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <Icon name="download" size={14} /> Descargar PDF
        </a>
      </div>

      <div className="kpi-grid">
        <KpiCard label="Saldo actual" value={fmtMoney(data.saldo_actual)} tone={data.saldo_actual > 0 ? "amber" : "green"} />
        <KpiCard label="Total facturado" value={fmtMoney(data.total_debe)} />
        <KpiCard label="Total pagado" value={fmtMoney(data.total_haber)} />
        <KpiCard label="Eventos" value={fmtNum(data.eventos.length)} />
      </div>

      <div className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>Extracto cronológico</h3>
          <button className="btn" onClick={() => setShowAltaFact(true)}>+ Nueva factura</button>
        </div>
        {showAltaFact && (
          <AltaFactura
            idProveedor={idProveedor}
            onClose={() => setShowAltaFact(false)}
            onSaved={() => { setShowAltaFact(false); cargar(); }}
          />
        )}
        {data.eventos.length === 0 && <div className="empty">Sin eventos.</div>}
        {data.eventos.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Tipo</th>
                <th>Descripción</th>
                <th>Vence</th>
                <th className="num">Debe</th>
                <th className="num">Haber</th>
                <th className="num">Saldo</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.eventos.map((e) => {
                const anulada = e.ref_tipo === "factura" && e.anulada;
                const styleAnulada = anulada
                  ? { opacity: 0.55, textDecoration: "line-through" }
                  : undefined;
                const esHighlighted = e.ref_tipo === "factura" && e.ref_id === facturaHighlight;
                const trStyle = esHighlighted
                  ? { background: "#422006", transition: "background 0.4s ease-out" }
                  : undefined;
                // Solo facturas tienen id DOM-targeteable (las usamos para
                // scroll desde la búsqueda global). No le ponemos id a los
                // pagos para evitar conflicto si IDs coinciden entre tablas.
                const trId = e.ref_tipo === "factura" ? `fila-factura-${e.ref_id}` : undefined;
                return (
                  <tr key={`${e.ref_tipo}-${e.ref_id}`} id={trId} style={trStyle}>
                    <td style={styleAnulada}>{e.fecha?.slice(0, 10)}</td>
                    <td>
                      <span className={`badge ${anulada ? "muted" : e.tipo === "factura" ? "warn" : "ok"}`}>
                        {anulada ? "anulada" : e.tipo}
                      </span>
                    </td>
                    <td style={styleAnulada}>{e.descripcion}</td>
                    <td style={{ color: "#94a3b8", fontSize: 12, ...styleAnulada }}>{e.vencimiento || "-"}</td>
                    <td className="num" style={{ color: e.debe > 0 ? "#fbbf24" : "#475569", ...styleAnulada }}>
                      {e.debe > 0 ? fmtMoney(e.debe) : "-"}
                    </td>
                    <td className="num" style={{ color: e.haber > 0 ? "#34d399" : "#475569", ...styleAnulada }}>
                      {e.haber > 0 ? fmtMoney(e.haber) : "-"}
                    </td>
                    <td className="num" style={{ fontWeight: 600, ...styleAnulada }}>{fmtMoney(e.saldo)}</td>
                    <td>
                      {e.ref_tipo === "movimiento" && (
                        <button className="btn-ghost btn" onClick={() => desvincular(e.ref_id)}>Desvincular</button>
                      )}
                      {e.ref_tipo === "factura" && !anulada && (
                        <>
                          <button
                            className="btn-ghost btn"
                            onClick={() => setEditando(e)}
                            title="Editar nro/fechas/descripción (total solo si no tiene pagos)"
                          >
                            Editar
                          </button>
                          <button
                            className="btn-ghost btn"
                            style={{ color: "#f87171" }}
                            onClick={() => setAnulando(e)}
                            title="Marcar como anulada (soft-delete)"
                          >
                            Anular
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h3>Egresos sin vincular — asignar a este proveedor</h3>
        <input
          placeholder={`Buscar en detalle... (ej. "${data.nombre.split(" ")[0]}")`}
          value={busqueda}
          onChange={(e) => setBusqueda(e.target.value)}
          style={{ marginBottom: 12, width: 360 }}
        />
        {sinAsignar.length === 0 && <div className="empty">No hay egresos sin vincular.</div>}
        {sinAsignar.length > 0 && (
          <table>
            <thead><tr><th>Fecha</th><th>Categoría</th><th>Detalle</th><th>Caja</th><th className="num">Monto</th><th></th></tr></thead>
            <tbody>
              {sinAsignar.map((m) => (
                <tr key={m.id}>
                  <td>{m.fecha}</td>
                  <td><span className="badge muted">{m.tipo_operacion}</span></td>
                  <td>{m.detalle}</td>
                  <td>{m.caja_origen}</td>
                  <td className="num">{fmtMoney(m.monto)}</td>
                  <td>
                    {vinculando === m.id ? (
                      <select
                        autoFocus
                        onChange={(e) => e.target.value && vincularA(m.id, Number(e.target.value))}
                        onBlur={() => setVinculando(null)}
                      >
                        <option value="">— elegir factura —</option>
                        {facturasParaVincular.map((f) => (
                          <option key={f.ref_id} value={f.ref_id}>
                            {f.descripcion} — {fmtMoney(f.debe)}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <button className="btn" disabled={facturasParaVincular.length === 0} onClick={() => setVinculando(m.id)}>
                        Vincular →
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {anulando && (
        <AnularFacturaModal
          factura={anulando}
          onClose={() => setAnulando(null)}
          onAnulada={() => { setAnulando(null); cargar(); cargarSinAsignar(busqueda); }}
        />
      )}

      {editando && (
        <EditarFacturaModal
          factura={editando}
          onClose={() => setEditando(null)}
          onGuardado={() => { setEditando(null); cargar(); }}
        />
      )}
    </>
  );
}

function AltaFactura({ idProveedor, onClose, onSaved }) {
  const toast = useToast();
  const [numero, setNumero] = useState("");
  const [fechaEmision, setFechaEmision] = useState(new Date().toLocaleDateString("en-CA"));
  const [fechaVencimiento, setFechaVencimiento] = useState("");
  const [total, setTotal] = useState("");
  const [descripcion, setDescripcion] = useState("");
  const [busy, setBusy] = useState(false);

  async function guardar() {
    if (!total || Number(total) <= 0) { toast.push("Total inválido", "error"); return; }
    setBusy(true);
    try {
      await api.post("/api/proveedores/factura", {
        id_proveedor: idProveedor,
        numero: numero || null,
        fecha_emision: fechaEmision,
        fecha_vencimiento: fechaVencimiento || null,
        total: Number(total),
        descripcion: descripcion || null,
      });
      toast.push("Factura creada", "success");
      onSaved();
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error", "error");
    } finally { setBusy(false); }
  }

  return (
    <div style={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, padding: 14, marginBottom: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr 2fr auto auto", gap: 10, alignItems: "end" }}>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Nº factura</label>
          <input value={numero} onChange={(e) => setNumero(e.target.value)} style={{ width: "100%" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Emisión *</label>
          <input type="date" value={fechaEmision} onChange={(e) => setFechaEmision(e.target.value)} style={{ width: "100%" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Vencimiento</label>
          <input type="date" value={fechaVencimiento} onChange={(e) => setFechaVencimiento(e.target.value)} style={{ width: "100%" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Total *</label>
          <input type="number" step="0.01" value={total} onChange={(e) => setTotal(e.target.value)} style={{ width: "100%", textAlign: "right" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Descripción</label>
          <input value={descripcion} onChange={(e) => setDescripcion(e.target.value)} style={{ width: "100%" }} />
        </div>
        <button className="btn" disabled={busy} onClick={guardar}>{busy ? <span className="spinner" /> : "Crear"}</button>
        <button className="btn-ghost btn" onClick={onClose}>Cancelar</button>
      </div>
    </div>
  );
}
