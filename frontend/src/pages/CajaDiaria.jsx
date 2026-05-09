import { Fragment, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import api, { fmtMoney, fmtNum, urlBackend } from "../api/client";
import { descargarComoCSV } from "../api/csvExport";
import { useConfirm } from "../components/ConfirmDialog";
import Icon from "../components/Icon";
import { useToast } from "../components/Toast";

export default function CajaDiaria() {
  const confirmar = useConfirm();
  const toast = useToast();
  const [editandoId, setEditandoId] = useState(null);
  const [sugerencias, setSugerencias] = useState({ cajas: [], categorias: [], categorias_top: [] });
  const [saldos, setSaldos] = useState([]);
  const [recientes, setRecientes] = useState([]);
  const [resumenPendientes, setResumenPendientes] = useState([]);
  const [pendientes, setPendientes] = useState([]);
  const [filtroCajaPend, setFiltroCajaPend] = useState("");
  const [seleccionadas, setSeleccionadas] = useState(new Set());
  const [verificando, setVerificando] = useState(false);
  // Resumen rápido de la actividad del día (qué pasó hoy en el negocio).
  // Carga en paralelo con el resto pero su panel se renderiza al tope.
  const [actividad, setActividad] = useState(null);

  async function cargarTodo() {
    // allSettled: si falla el endpoint de actividad (más nuevo, podría no
    // estar en backend desactualizado), el resto de la página igual carga.
    const [s, sa, r, rp, ad] = await Promise.allSettled([
      api.get("/api/caja-diaria/sugerencias"),
      api.get("/api/kpis/caja/saldos"),
      api.get("/api/caja-diaria/movimientos-recientes", { params: { limite: 30 } }),
      api.get("/api/caja-diaria/cobros-pendientes-resumen"),
      api.get("/api/kpis/caja/actividad-dia"),
    ]);
    // Defaults defensivos: si el contrato del endpoint cambia y `data.items`
    // viene undefined, no queremos que .map/.length crasheen toda la página.
    if (s.status === "fulfilled") setSugerencias(s.value.data || { cajas: [], categorias: [], categorias_top: [] });
    if (sa.status === "fulfilled") setSaldos(sa.value.data || []);
    if (r.status === "fulfilled") setRecientes(r.value.data?.items || []);
    if (rp.status === "fulfilled") setResumenPendientes(rp.value.data || []);
    if (ad.status === "fulfilled") setActividad(ad.value.data);
    else { console.warn("[caja-diaria] /actividad-dia falló:", ad.reason); setActividad(null); }
    cargarPendientes();
  }

  async function cargarPendientes(signal) {
    const params = { limite: 30 };
    if (filtroCajaPend) params.caja = filtroCajaPend;
    try {
      const { data } = await api.get("/api/caja-diaria/cobros-pendientes", { params, signal });
      setPendientes(data?.items || []);
      setSeleccionadas(new Set());
    } catch (e) {
      if (e.name !== "CanceledError" && e.code !== "ERR_CANCELED") throw e;
    }
  }

  useEffect(() => { cargarTodo(); }, []);
  useEffect(() => {
    const ctrl = new AbortController();
    cargarPendientes(ctrl.signal);
    return () => ctrl.abort();
  }, [filtroCajaPend]);

  function toggleSelect(idPedido, cajaIdx) {
    const key = `${idPedido}|${cajaIdx}`;
    const next = new Set(seleccionadas);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSeleccionadas(next);
  }

  async function verificarSeleccionadas() {
    if (seleccionadas.size === 0) return;
    setVerificando(true);
    try {
      const items = [...seleccionadas].map((k) => {
        const [id_pedido, caja_idx] = k.split("|");
        return { id_pedido, caja_idx: Number(caja_idx) };
      });
      await api.post("/api/caja-diaria/verificar-bulk", { items });
      cargarTodo();
    } finally {
      setVerificando(false);
    }
  }

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0 }}>Caja diaria</h2>
        <a
          className="btn-ghost btn"
          href={urlBackend(`/api/caja-diaria/resumen-diario.pdf?fecha=${new Date().toLocaleDateString("en-CA")}`)}
          download
          title="Imprimir resumen del día (saldos al cierre + movimientos del día)"
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <Icon name="download" size={14} /> Imprimir resumen del día
        </a>
      </div>
      <p style={{ color: "#94a3b8", marginTop: 4 }}>
        Alta de movimientos, saldos en vivo y verificación de cobros pendientes — todo en una pantalla.
      </p>

      {actividad && (
        <div className="panel" style={{ borderColor: "#3b82f6", marginBottom: 16 }}>
          <h3 style={{ margin: 0, marginBottom: 12 }}>Actividad de hoy</h3>
          <div className="kpi-grid" style={{ marginBottom: 12 }}>
            <div className="kpi-card">
              <div className="label">Ventas del día</div>
              <div className="value">{fmtMoney(actividad.ventas_monto)}</div>
              <div className="sub">{fmtNum(actividad.ventas_pedidos)} pedidos</div>
            </div>
            <div className="kpi-card green">
              <div className="label">Ingresos a caja</div>
              <div className="value">{fmtMoney(actividad.ingresos_operativos)}</div>
              <div className="sub">cobranzas operativas</div>
            </div>
            <div className="kpi-card amber">
              <div className="label">Egresos de caja</div>
              <div className="value">{fmtMoney(actividad.egresos_operativos)}</div>
              <div className="sub">gastos puros</div>
            </div>
            <div className={`kpi-card ${
              actividad.neto_operativo > 0 ? "green" :
              actividad.neto_operativo < 0 ? "red" :
              ""
            }`}>
              <div className="label">Neto del día</div>
              <div className="value">
                {actividad.neto_operativo > 0 ? "+" : ""}{fmtMoney(actividad.neto_operativo)}
              </div>
              <div className="sub">ingresos − egresos</div>
            </div>
          </div>
          {actividad.top_familias_gasto.length > 0 && (
            <div style={{ display: "flex", gap: 12, fontSize: 12, color: "#cbd5e1", flexWrap: "wrap" }}>
              <b style={{ color: "#94a3b8" }}>Top gastos del día:</b>
              {actividad.top_familias_gasto.map((f, i) => (
                <span
                  key={i}
                  title={`${f.familia}: ${fmtMoney(f.monto)}`}
                  style={{
                    maxWidth: 220,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >{f.familia}: <b>{fmtMoney(f.monto)}</b></span>
              ))}
            </div>
          )}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 20, marginBottom: 20 }}>
        <FormNuevoMovimiento sugerencias={sugerencias} onSaved={cargarTodo} />
        <SaldosVivos saldos={saldos} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 20, marginBottom: 20 }}>
        <CerrarDiaPanel cajas={sugerencias.cajas} onCerrado={cargarTodo} />
        <CierresHistorial recargar={recientes.length} />
      </div>

      <div className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>Movimientos recientes</h3>
          {recientes.length > 0 && (
            <button
              className="btn-ghost btn"
              onClick={() => descargarComoCSV(
                `movimientos-recientes-${new Date().toISOString().slice(0, 10)}.csv`,
                [
                  { key: "fecha", label: "Fecha" },
                  { key: "tipo_operacion", label: "Tipo operación" },
                  { key: "detalle", label: "Detalle" },
                  { key: "caja_origen", label: "Origen" },
                  { key: "caja_destino", label: "Destino" },
                  { key: "monto", label: "Monto" },
                  { key: "cliente_nombre", label: "Cliente" },
                  { key: "tipo", label: "Flow" },
                ],
                recientes,
              )}
              title="Descargar movimientos en CSV"
              style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12 }}
            >
              <Icon name="download" size={12} /> CSV
            </button>
          )}
        </div>
        {recientes.length === 0 && <div className="empty">No hay movimientos hoy.</div>}
        {recientes.length > 0 && (
          <table>
            <thead>
              <tr><th>Fecha</th><th>Tipo</th><th>Detalle</th><th>Origen</th><th>Destino</th><th className="num">Monto</th><th>Cliente</th><th>Flow</th><th style={{ width: 90 }}></th></tr>
            </thead>
            <tbody>
              {recientes.map((m) => (
                <Fragment key={m.id}>
                  <tr>
                    <td>{m.fecha}</td>
                    <td><span className="badge muted">{m.tipo_operacion}</span></td>
                    <td style={{ maxWidth: 400, color: "#cbd5e1" }}>{m.detalle}</td>
                    <td style={{ color: m.caja_origen ? "#f87171" : "#475569" }}>{m.caja_origen || "-"}</td>
                    <td style={{ color: m.caja_destino ? "#34d399" : "#475569" }}>{m.caja_destino || "-"}</td>
                    <td className="num" style={{ fontWeight: 600 }}>{fmtMoney(m.monto)}</td>
                    <td>
                      {m.cliente_nombre ? (
                        <Link to="/cuentas-corrientes" style={{ color: "#60a5fa" }} title={`Ver cuenta corriente de ${m.cliente_nombre}`}>
                          {m.cliente_nombre}
                        </Link>
                      ) : (
                        <span style={{ color: "#475569" }}>-</span>
                      )}
                    </td>
                    <td><span className={`badge ${m.tipo === "ingreso" ? "ok" : m.tipo === "egreso" ? "err" : "muted"}`}>{m.tipo}</span></td>
                    <td>
                      <button
                        className="btn-ghost btn"
                        title="Editar"
                        aria-label="Editar movimiento"
                        style={{ padding: "4px 8px", marginRight: 4 }}
                        onClick={() => setEditandoId(editandoId === m.id ? null : m.id)}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M12 20h9" />
                          <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                        </svg>
                      </button>
                      <button
                        className="btn-ghost btn"
                        title="Borrar"
                        aria-label="Borrar movimiento"
                        style={{ padding: "4px 8px" }}
                        onClick={async () => {
                          const ok = await confirmar({
                            titulo: `Borrar movimiento #${m.id}`,
                            mensaje: `${m.tipo_operacion}: ${m.detalle || "(sin detalle)"}\n${fmtMoney(m.monto)}`,
                            labelOk: "Borrar",
                            peligroso: true,
                          });
                          if (!ok) return;
                          await api.delete(`/api/caja-diaria/movimiento/${m.id}`);
                          toast.push("Movimiento borrado", "success");
                          cargarTodo();
                        }}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M3 6h18" />
                          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                          <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                  {editandoId === m.id && (
                    <tr>
                      <td colSpan={9} style={{ background: "#0f172a", padding: 0 }}>
                        <EditarMovimientoFila
                          mov={m}
                          cajas={sugerencias.cajas}
                          categorias={sugerencias.categorias}
                          onCancel={() => setEditandoId(null)}
                          onSaved={() => { setEditandoId(null); cargarTodo(); }}
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

      <div className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>Cobros pendientes de verificación</h3>
          {pendientes.length > 0 && (
            <button
              className="btn-ghost btn"
              onClick={() => {
                // Flatten: una fila por (venta, caja) — mismo orden visible.
                // id_pedido va primero: clave para identificar la venta al
                // revisar offline (sino la dueña no puede correlacionar con
                // el sistema).
                const filas = pendientes.flatMap((v) =>
                  v.pendientes.map((p) => ({
                    id_pedido: v.id_pedido,
                    fecha: v.fecha?.slice(0, 10) || "",
                    cliente: v.cliente,
                    vendedor: v.vendedor,
                    caja: p.caja,
                    monto: p.monto,
                    total_venta: v.total,
                  }))
                );
                descargarComoCSV(
                  `cobros-pendientes-${new Date().toISOString().slice(0, 10)}.csv`,
                  [
                    { key: "id_pedido", label: "ID pedido" },
                    { key: "fecha", label: "Fecha" },
                    { key: "cliente", label: "Cliente" },
                    { key: "vendedor", label: "Vendedor" },
                    { key: "caja", label: "Caja" },
                    { key: "monto", label: "Monto" },
                    { key: "total_venta", label: "Total venta" },
                  ],
                  filas,
                );
              }}
              title="Descargar cobros pendientes en CSV"
              style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12 }}
            >
              <Icon name="download" size={12} /> CSV
            </button>
          )}
        </div>
        <div style={{ marginBottom: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
          {resumenPendientes.map((r) => (
            <button
              key={r.caja}
              className={filtroCajaPend === r.caja ? "btn" : "btn-ghost btn"}
              onClick={() => setFiltroCajaPend(filtroCajaPend === r.caja ? "" : r.caja)}
              style={{ textAlign: "left", padding: "10px 12px" }}
            >
              <div style={{ fontWeight: 600 }}>{r.caja}</div>
              <div style={{ fontSize: 11, color: "#94a3b8" }}>{r.pendientes} cobros · {fmtMoney(r.monto_total)}</div>
            </button>
          ))}
        </div>

        {filtroCajaPend && (
          <div style={{ marginBottom: 10, fontSize: 12, color: "#94a3b8" }}>
            Filtrando por caja <b>{filtroCajaPend}</b> · <a href="#" onClick={(e) => { e.preventDefault(); setFiltroCajaPend(""); }}>quitar filtro</a>
          </div>
        )}

        {seleccionadas.size > 0 && (
          <div style={{ marginBottom: 12, padding: 10, background: "#1e3a5f", borderRadius: 6, display: "flex", alignItems: "center", gap: 12 }}>
            <span>{seleccionadas.size} seleccionados</span>
            <button className="btn" disabled={verificando} onClick={verificarSeleccionadas}>
              {verificando ? <span className="spinner" /> : `Marcar ${seleccionadas.size} como verificados`}
            </button>
            <button className="btn-ghost btn" onClick={() => setSeleccionadas(new Set())}>Limpiar</button>
          </div>
        )}

        {pendientes.length === 0 && <div className="empty">No hay cobros pendientes con esos filtros 🎉</div>}
        {pendientes.length > 0 && (
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Fecha</th>
                <th>Cliente</th>
                <th>Vendedor</th>
                <th>Caja</th>
                <th className="num">Monto</th>
                <th className="num">Total venta</th>
              </tr>
            </thead>
            <tbody>
              {pendientes.flatMap((v) =>
                v.pendientes.map((p) => {
                  const key = `${v.id_pedido}|${p.caja_idx}`;
                  const sel = seleccionadas.has(key);
                  return (
                    <tr key={key} style={{ background: sel ? "#1e3a5f" : "transparent", cursor: "pointer" }}
                        onClick={() => toggleSelect(v.id_pedido, p.caja_idx)}>
                      <td><input type="checkbox" checked={sel} readOnly /></td>
                      <td>{v.fecha?.slice(0, 10)}</td>
                      <td>{v.cliente}</td>
                      <td>{v.vendedor}</td>
                      <td><span className="badge muted">{p.caja}</span></td>
                      <td className="num">{fmtMoney(p.monto)}</td>
                      <td className="num" style={{ color: "#94a3b8" }}>{fmtMoney(v.total)}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function EditarMovimientoFila({ mov, cajas, categorias, onCancel, onSaved }) {
  const [fecha, setFecha] = useState(mov.fecha);
  const [tipoOp, setTipoOp] = useState(mov.tipo_operacion);
  const [detalle, setDetalle] = useState(mov.detalle || "");
  const [monto, setMonto] = useState(String(mov.monto));
  const [origen, setOrigen] = useState(mov.caja_origen || "");
  const [destino, setDestino] = useState(mov.caja_destino || "");
  const [idCliente, setIdCliente] = useState(mov.id_cliente_relacionado || "");
  const [clienteNombre, setClienteNombre] = useState(mov.cliente_nombre || "");
  const [clienteSugs, setClienteSugs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Categoría seleccionada — saber si es ingreso operativo (para mostrar el campo cliente)
  const catSel = categorias.find((c) => c.tipo_operacion === tipoOp);
  const esCobranza = !!catSel && catSel.familia === "Operaciones especiales" && (
    tipoOp === "Ingreso" || tipoOp === "paga cuenta corriente"
  );

  const cajasOrdenadas = useMemo(() => [...cajas].sort((a, b) => a.nombre_display.localeCompare(b.nombre_display)), [cajas]);

  // Para el select usamos display, pero el backend guarda normalizado.
  // Encontrar display a partir del normalizado actual.
  const displayDe = (norm) => cajas.find((c) => c.nombre_normalizado === norm)?.nombre_display || norm || "";

  async function buscarClientes(q) {
    if (!q || q.length < 2) { setClienteSugs([]); return []; }
    const { data } = await api.get("/api/ventas/clientes-buscar", { params: { q, limite: 8 } });
    setClienteSugs(data);
    return data;  // Devuelve para que el caller pueda matchear sin esperar al re-render
  }

  async function guardar() {
    setBusy(true);
    setError(null);
    try {
      const payload = {
        fecha,
        tipo_operacion: tipoOp,
        detalle: detalle || null,
        monto: Number(monto),
        caja_origen: origen || null,
        caja_destino: destino || null,
        limpiar_caja_origen: origen === "",
        limpiar_caja_destino: destino === "",
        id_cliente_relacionado: idCliente ? Number(idCliente) : null,
        limpiar_cliente: !idCliente,
      };
      await api.patch(`/api/caja-diaria/movimiento/${mov.id}`, payload);
      onSaved();
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ padding: 14 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        <div style={{ width: 130 }}>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Fecha</label>
          <input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} style={{ width: "100%" }} />
        </div>
        <div style={{ width: 160 }}>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Tipo de Operación</label>
          <input list="cats-edit" value={tipoOp} onChange={(e) => setTipoOp(e.target.value)} style={{ width: "100%" }} />
          <datalist id="cats-edit">
            {categorias.map((c) => <option key={c.tipo_operacion} value={c.tipo_operacion} />)}
          </datalist>
        </div>
        <div style={{ flex: "2 1 280px" }}>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Detalle</label>
          <input value={detalle} onChange={(e) => setDetalle(e.target.value)} style={{ width: "100%" }} />
        </div>
        <div style={{ width: 110 }}>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Monto</label>
          <input type="number" step="0.01" value={monto} onChange={(e) => setMonto(e.target.value)} style={{ width: "100%", textAlign: "right" }} />
        </div>
        <div style={{ width: 160 }}>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Caja origen</label>
          <select value={displayDe(origen)} onChange={(e) => setOrigen(e.target.value)} style={{ width: "100%" }}>
            <option value="">— sin origen —</option>
            {cajasOrdenadas.map((c) => <option key={c.nombre_normalizado} value={c.nombre_display}>{c.nombre_display}</option>)}
          </select>
        </div>
        <div style={{ width: 160 }}>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Caja destino</label>
          <select value={displayDe(destino)} onChange={(e) => setDestino(e.target.value)} style={{ width: "100%" }}>
            <option value="">— sin destino —</option>
            {cajasOrdenadas.map((c) => <option key={c.nombre_normalizado} value={c.nombre_display}>{c.nombre_display}</option>)}
          </select>
        </div>
        {esCobranza && (
          <div style={{ flex: "1 1 240px" }}>
            <details {...(idCliente ? { open: true } : {})}>
              <summary style={{ cursor: "pointer", fontSize: 11, color: "#94a3b8" }}>
                Cliente vinculado (legacy — FIFO automático)
              </summary>
              <input
                list={`cli-edit-${mov.id}`}
                value={clienteNombre}
                placeholder="buscá nombre o id..."
                onChange={async (e) => {
                  const valor = e.target.value;
                  setClienteNombre(valor);
                  // Match contra resultados FRESCOS (no `clienteSugs` viejo
                  // del state — eso era stale closure, daba idCliente
                  // incorrecto cuando el datalist autocompletaba con un
                  // pedido nuevo).
                  const sugsFrescas = await buscarClientes(valor);
                  const match = sugsFrescas?.find((c) => c.cliente === valor);
                  if (match) setIdCliente(match.id_cliente);
                }}
                style={{ width: "100%" }}
              />
              <datalist id={`cli-edit-${mov.id}`}>
                {clienteSugs.map((c) => <option key={c.id_cliente} value={c.cliente}>id {c.id_cliente} · {c.pedidos} pedidos</option>)}
              </datalist>
              {idCliente && <span style={{ fontSize: 10, color: "#94a3b8" }}>id={idCliente}</span>}
              <div style={{ fontSize: 10, color: "#64748b", marginTop: 4 }}>
                Para nuevos cobros, preferí <b>Cuentas Corrientes → Aplicar a venta</b>.
              </div>
            </details>
          </div>
        )}
      </div>
      <div style={{ marginTop: 12, display: "flex", gap: 10, alignItems: "center" }}>
        <button className="btn" disabled={busy} onClick={guardar}>
          {busy ? <span className="spinner" /> : "Guardar cambios"}
        </button>
        <button className="btn-ghost btn" onClick={onCancel}>Cancelar</button>
        {error && (
          <span style={{ color: "#f87171", fontSize: 13, display: "inline-flex", alignItems: "center", gap: 4 }}>
            <Icon name="x" size={14} label="Error" /> {error}
          </span>
        )}
      </div>
    </div>
  );
}

function FormNuevoMovimiento({ sugerencias, onSaved }) {
  const [tipo, setTipo] = useState("egreso");  // egreso | ingreso | transferencia
  const [tipoOperacion, setTipoOperacion] = useState("");
  const [detalle, setDetalle] = useState("");
  const [monto, setMonto] = useState("");
  const [cajaOrigen, setCajaOrigen] = useState("");
  const [cajaDestino, setCajaDestino] = useState("");
  const [fecha, setFecha] = useState(new Date().toLocaleDateString("en-CA"));
  const [idCliente, setIdCliente] = useState("");
  const [clienteNombre, setClienteNombre] = useState("");
  const [clienteSugs, setClienteSugs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Mostrar campo cliente cuando es cobranza típica de cta cte
  const esCobranza = tipoOperacion === "Ingreso" || tipoOperacion === "paga cuenta corriente";

  async function buscarClientes(q) {
    if (!q || q.length < 2) { setClienteSugs([]); return []; }
    const { data } = await api.get("/api/ventas/clientes-buscar", { params: { q, limite: 8 } });
    setClienteSugs(data);
    return data;
  }

  const cajasOrdenadas = useMemo(() => {
    return [...sugerencias.cajas].sort((a, b) => a.nombre_display.localeCompare(b.nombre_display));
  }, [sugerencias.cajas]);

  function setearTipo(t) {
    setTipo(t);
    if (t === "ingreso") setCajaOrigen("");
    else if (t === "egreso") setCajaDestino("");
  }

  async function guardar(e) {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    setBusy(true);
    try {
      const payload = {
        fecha,
        tipo_operacion: tipoOperacion,
        detalle: detalle || null,
        monto: Number(monto),
        caja_origen: cajaOrigen || null,
        caja_destino: cajaDestino || null,
        id_cliente_relacionado: esCobranza && idCliente ? Number(idCliente) : null,
      };
      const { data } = await api.post("/api/caja-diaria/movimiento", payload);
      setSuccess(`Movimiento #${data.id} guardado${payload.id_cliente_relacionado ? " (vinculado a cliente)" : ""}`);
      setTipoOperacion("");
      setDetalle("");
      setMonto("");
      setIdCliente("");
      setClienteNombre("");
      onSaved();
      setTimeout(() => setSuccess(null), 2000);
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h3>Nuevo movimiento</h3>
      <div className="toolbar" style={{ marginBottom: 12 }}>
        {["egreso", "ingreso", "transferencia"].map((t) => (
          <button key={t} className={tipo === t ? "btn" : "btn-ghost btn"} onClick={() => setearTipo(t)}>
            {t === "egreso" ? "Egreso (sale de caja)" : t === "ingreso" ? "Ingreso (entra a caja)" : "Transferencia"}
          </button>
        ))}
      </div>

      <form onSubmit={guardar} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div>
          <label style={{ fontSize: 12, color: "#94a3b8" }}>Fecha</label>
          <input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} style={{ width: "100%" }} />
        </div>
        <div>
          <label style={{ fontSize: 12, color: "#94a3b8" }}>Monto *</label>
          <input type="number" step="0.01" required value={monto} onChange={(e) => setMonto(e.target.value)} placeholder="0.00" style={{ width: "100%" }} />
        </div>

        <div style={{ gridColumn: "span 2" }}>
          <label style={{ fontSize: 12, color: "#94a3b8" }}>Categoría / Tipo de Operación *</label>
          <input
            list="cats-list"
            required
            value={tipoOperacion}
            onChange={(e) => setTipoOperacion(e.target.value)}
            placeholder="Materia Prima, Sueldo, Envios..."
            style={{ width: "100%" }}
          />
          <datalist id="cats-list">
            {sugerencias.categorias_top.map((c) => <option key={c.tipo_operacion} value={c.tipo_operacion} />)}
            {sugerencias.categorias.map((c) => <option key={c.tipo_operacion} value={c.tipo_operacion} />)}
          </datalist>
        </div>

        {(tipo === "egreso" || tipo === "transferencia") && (
          <div>
            <label style={{ fontSize: 12, color: "#94a3b8" }}>Caja origen (sale de) *</label>
            <select required value={cajaOrigen} onChange={(e) => setCajaOrigen(e.target.value)} style={{ width: "100%" }}>
              <option value="">— elegí —</option>
              {cajasOrdenadas.map((c) => <option key={c.nombre_normalizado} value={c.nombre_display}>{c.nombre_display}</option>)}
            </select>
          </div>
        )}

        {(tipo === "ingreso" || tipo === "transferencia") && (
          <div>
            <label style={{ fontSize: 12, color: "#94a3b8" }}>Caja destino (entra a) *</label>
            <select required value={cajaDestino} onChange={(e) => setCajaDestino(e.target.value)} style={{ width: "100%" }}>
              <option value="">— elegí —</option>
              {cajasOrdenadas.map((c) => <option key={c.nombre_normalizado} value={c.nombre_display}>{c.nombre_display}</option>)}
            </select>
          </div>
        )}

        <div style={{ gridColumn: "span 2" }}>
          <label style={{ fontSize: 12, color: "#94a3b8" }}>Detalle</label>
          <input value={detalle} onChange={(e) => setDetalle(e.target.value)} placeholder="opcional..." style={{ width: "100%" }} />
        </div>

        {esCobranza && (
          <div style={{ gridColumn: "span 2" }}>
            <div style={{ background: "#1e3a8a", border: "1px solid #3b82f6", padding: 10, borderRadius: 6, fontSize: 12, color: "#bfdbfe", marginBottom: 8 }}>
              <b>Cobranza de cuenta corriente</b>: guardá el movimiento sin vincular,
              y aplicá el cobro a una venta puntual desde <b>Cuentas Corrientes →
              Aplicar a venta</b>. Ese flujo permite cobertura granular (un pago a
              varias ventas) y deja traza explícita en lugar del FIFO automático.
            </div>
            <details>
              <summary style={{ cursor: "pointer", fontSize: 12, color: "#94a3b8", marginBottom: 4 }}>
                Vincular a cliente (legacy — FIFO automático)
              </summary>
              <input
                list="cli-form-list"
                value={clienteNombre}
                placeholder="buscá nombre o id..."
                onChange={async (e) => {
                  const valor = e.target.value;
                  setClienteNombre(valor);
                  // Match contra resultados frescos (no clienteSugs viejo).
                  const sugsFrescas = await buscarClientes(valor);
                  const match = sugsFrescas?.find((c) => c.cliente === valor);
                  if (match) setIdCliente(match.id_cliente);
                }}
                style={{ width: "100%" }}
              />
              <datalist id="cli-form-list">
                {clienteSugs.map((c) => <option key={c.id_cliente} value={c.cliente}>id {c.id_cliente} · {c.pedidos} pedidos</option>)}
              </datalist>
              {idCliente && <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 2 }}>id seleccionado: {idCliente}</div>}
            </details>
          </div>
        )}

        <div style={{ gridColumn: "span 2", display: "flex", gap: 10, alignItems: "center" }}>
          <button className="btn" type="submit" disabled={busy}>
            {busy ? <span className="spinner" /> : "Guardar"}
          </button>
          {success && (
            <span style={{ color: "#34d399", fontSize: 13, display: "inline-flex", alignItems: "center", gap: 4 }}>
              <Icon name="check" size={14} label="OK" /> {success}
            </span>
          )}
          {error && (
            <span style={{ color: "#f87171", fontSize: 13, display: "inline-flex", alignItems: "center", gap: 4 }}>
              <Icon name="x" size={14} label="Error" /> {error}
            </span>
          )}
        </div>
      </form>
    </div>
  );
}

function SaldosVivos({ saldos }) {
  const [filtro, setFiltro] = useState("");
  const total = saldos.reduce((s, c) => s + c.saldo, 0);
  const filtrados = saldos.filter((c) => c.caja.toLowerCase().includes(filtro.toLowerCase()));

  return (
    <div className="panel" style={{ maxHeight: 460, overflow: "auto" }}>
      <h3>Saldos en vivo <span style={{ fontSize: 12, color: "#94a3b8", fontWeight: 400 }}>({fmtNum(saldos.length)} cajas · total {fmtMoney(total)})</span></h3>
      <input
        placeholder="Filtrar caja..."
        value={filtro}
        onChange={(e) => setFiltro(e.target.value)}
        style={{ width: "100%", marginBottom: 10 }}
      />
      <table>
        <thead><tr><th>Caja</th><th className="num">Saldo</th></tr></thead>
        <tbody>
          {filtrados.slice(0, 30).map((c) => (
            <tr key={c.caja}>
              <td>
                {c.caja}
                {c.tipo === "fc_empleado" && <span className="badge warn" style={{ marginLeft: 6, fontSize: 10 }}>FC</span>}
              </td>
              <td className="num" style={{ color: c.saldo < 0 ? "#f87171" : c.saldo > 0 ? "#34d399" : "#94a3b8", fontWeight: 600 }}>
                {fmtMoney(c.saldo)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CerrarDiaPanel({ cajas, onCerrado }) {
  const confirmar = useConfirm();
  const toast = useToast();
  const [caja, setCaja] = useState("");
  const [fecha, setFecha] = useState(new Date().toLocaleDateString("en-CA"));
  const [saldoCalc, setSaldoCalc] = useState(null);
  const [observaciones, setObservaciones] = useState("");
  const [busy, setBusy] = useState(false);

  async function calcularSaldo() {
    if (!caja || !fecha) return;
    const cajaNorm = cajas.find((c) => c.nombre_display === caja || c.nombre_normalizado === caja)?.nombre_normalizado || caja;
    const { data } = await api.get("/api/cierres/saldo-actual", { params: { caja: cajaNorm, fecha } });
    setSaldoCalc(data.saldo_calculado);
  }

  async function cerrar() {
    if (!caja || !fecha) {
      toast.push("Elegí caja y fecha", "error");
      return;
    }
    const ok = await confirmar({
      titulo: "Cerrar día",
      mensaje: `Vas a cerrar la caja "${caja}" al ${fecha} con saldo ${saldoCalc != null ? "$" + saldoCalc.toLocaleString("es-AR") : "(calculado)"}.\n\nDespués del cierre los movimientos de ese día y anteriores en esta caja NO se podrán editar ni borrar.`,
      labelOk: "Cerrar día",
    });
    if (!ok) return;
    setBusy(true);
    try {
      const cajaNorm = cajas.find((c) => c.nombre_display === caja)?.nombre_normalizado || caja;
      await api.post("/api/cierres", {
        fecha, caja: cajaNorm,
        saldo_cierre: saldoCalc,
        observaciones: observaciones || null,
      });
      toast.push("Día cerrado correctamente", "success");
      setObservaciones("");
      setSaldoCalc(null);
      onCerrado?.();
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error al cerrar", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h3>Cerrar día</h3>
      <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 12 }}>
        Snapshotea el saldo del día y bloquea ediciones de ese día (y anteriores) en la caja seleccionada.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 10, alignItems: "end" }}>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Caja</label>
          <select value={caja} onChange={(e) => { setCaja(e.target.value); setSaldoCalc(null); }} style={{ width: "100%" }}>
            <option value="">— elegí —</option>
            {cajas.map((c) => <option key={c.nombre_normalizado} value={c.nombre_display}>{c.nombre_display}</option>)}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Fecha</label>
          <input type="date" value={fecha} onChange={(e) => { setFecha(e.target.value); setSaldoCalc(null); }} style={{ width: "100%" }} />
        </div>
        <div>
          <label style={{ fontSize: 11, color: "#94a3b8" }}>Saldo calculado</label>
          <div style={{ padding: "6px 10px", background: "#0f172a", border: "1px solid #334155", borderRadius: 6, color: saldoCalc != null ? "#34d399" : "#64748b" }}>
            {saldoCalc != null ? `$${saldoCalc.toLocaleString("es-AR")}` : "—"}
          </div>
        </div>
        <button className="btn-ghost btn" onClick={calcularSaldo} disabled={!caja || !fecha}>Calcular</button>
      </div>
      <div style={{ marginTop: 10 }}>
        <label style={{ fontSize: 11, color: "#94a3b8" }}>Observaciones</label>
        <input value={observaciones} onChange={(e) => setObservaciones(e.target.value)} placeholder="opcional..." style={{ width: "100%" }} />
      </div>
      <div style={{ marginTop: 12 }}>
        <button className="btn" disabled={busy || !caja || !fecha} onClick={cerrar}>
          {busy ? <span className="spinner" /> : "Cerrar día"}
        </button>
      </div>
    </div>
  );
}

function CierresHistorial({ recargar }) {
  const confirmar = useConfirm();
  const toast = useToast();
  const [cierres, setCierres] = useState([]);
  const [auditoria, setAuditoria] = useState([]);
  // ID del cierre highlighted al hacer click desde el panel de auditoría.
  // Se limpia tras 2.5s — feedback visual sin acción permanente.
  const [highlightId, setHighlightId] = useState(null);

  async function cargar(signal) {
    try {
      const [r1, r2] = await Promise.all([
        api.get("/api/cierres", { params: { limite: 30 }, signal }),
        api.get("/api/cierres/auditoria", { signal }),
      ]);
      setCierres(r1.data);
      setAuditoria(r2.data);
    } catch (e) {
      if (e.name !== "CanceledError" && e.code !== "ERR_CANCELED") throw e;
    }
  }
  useEffect(() => {
    const ctrl = new AbortController();
    cargar(ctrl.signal);
    return () => ctrl.abort();
  }, [recargar]);

  function irAlCierre(id) {
    setHighlightId(id);
    // scrollIntoView con behavior:smooth — la tabla principal está justo
    // debajo del panel de auditoría, así que el scroll es corto pero útil
    // si la lista creció mucho.
    const el = document.getElementById(`cierre-row-${id}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => setHighlightId(null), 2500);
  }

  async function reabrir(c) {
    const ok = await confirmar({
      titulo: "Reabrir cierre",
      mensaje: `Caja "${c.caja}" del ${c.fecha}.\n\nSe eliminará el cierre y los movimientos de ese día y anteriores volverán a ser editables.`,
      labelOk: "Reabrir",
      peligroso: true,
    });
    if (!ok) return;
    await api.delete(`/api/cierres/${c.id}`);
    toast.push("Cierre reabierto", "info");
    cargar();
  }

  return (
    <div className="panel">
      <h3>Cierres recientes</h3>
      {auditoria.length > 0 && (
        <div style={{ background: "#422006", border: "1px solid #92400e", padding: 10, borderRadius: 6, marginBottom: 12 }}>
          <div style={{ color: "#fde68a", fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
            <Icon name="warn" size={14} label="Atención" /> {auditoria.length} cierre{auditoria.length === 1 ? "" : "s"} con discrepancia detectada
          </div>
          <table style={{ fontSize: 12 }}>
            <thead><tr><th>Fecha</th><th>Caja</th><th className="num">Declarado</th><th className="num">Calculado</th><th className="num">Diff</th><th></th></tr></thead>
            <tbody>
              {auditoria.map((a) => (
                <tr
                  key={a.id}
                  onClick={() => irAlCierre(a.id)}
                  style={{ cursor: "pointer" }}
                  title="Click para ir al cierre"
                >
                  <td>{a.fecha}</td>
                  <td>{a.caja}</td>
                  <td className="num">{fmtMoney(a.saldo_declarado)}</td>
                  <td className="num">{fmtMoney(a.saldo_calculado)}</td>
                  <td className="num" style={{ color: a.diff > 0 ? "#34d399" : "#f87171", fontWeight: 600 }}>
                    {a.diff > 0 ? "+" : ""}{fmtMoney(a.diff)}
                  </td>
                  <td style={{ color: "#94a3b8", fontSize: 10 }}>↓</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {cierres.length === 0 && <div className="empty">No hay cierres todavía.</div>}
      {cierres.length > 0 && (
        <table>
          <thead><tr><th>Fecha</th><th>Caja</th><th className="num">Saldo cierre</th><th>Observaciones</th><th></th></tr></thead>
          <tbody>
            {cierres.map((c) => (
              <tr
                key={c.id}
                id={`cierre-row-${c.id}`}
                style={highlightId === c.id ? {
                  background: "#422006",
                  transition: "background 0.4s ease-out",
                } : undefined}
              >
                <td>{c.fecha}</td>
                <td>{c.caja}</td>
                <td className="num">{fmtMoney(c.saldo_cierre)}</td>
                <td style={{ color: "#94a3b8", fontSize: 12 }}>{c.observaciones || "-"}</td>
                <td><button className="btn-ghost btn btn-danger" onClick={() => reabrir(c)}>Reabrir</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
