import { Fragment, useEffect, useState } from "react";
import api, { fmtNum } from "../api/client";
import { descargarComoCSV } from "../api/csvExport";
import { useConfirm } from "../components/ConfirmDialog";
import Icon from "../components/Icon";
import { useToast } from "../components/Toast";
import { useStoredState } from "../hooks/useStoredState";

// Columnas relevantes por tipo de fuente — solo lo que se necesita editar.
const COLUMNAS = {
  movimientos_caja: [
    { key: "FECHA", label: "Fecha", width: 95 },
    { key: "Tipo de Operación", label: "Tipo Op.", width: 130 },
    { key: "DETALLE DEL GASTO", label: "Detalle", width: 280, full: true },
    { key: "MONTO", label: "Monto", width: 110, num: true },
    { key: "SALIDAS", label: "Origen", width: 120 },
    { key: "ENTRADAS", label: "Destino", width: 120 },
  ],
  ventas: [
    { key: "Fecha", label: "Fecha", width: 130 },
    { key: "cliente", label: "Cliente", width: 180 },
    { key: "vendedor", label: "Vendedor", width: 130 },
    { key: "total", label: "Total", width: 110, num: true },
    { key: "formaDePago1", label: "Caja 1", width: 110 },
    { key: "montoPago1", label: "Monto 1", width: 100, num: true },
    { key: "formaDePago2", label: "Caja 2", width: 110 },
    { key: "montoPago2", label: "Monto 2", width: 100, num: true },
  ],
  detalle_ventas: [
    { key: "fecha", label: "Fecha", width: 130 },
    { key: "idVenta", label: "ID Venta", width: 80 },
    { key: "producto", label: "Producto", width: 220, full: true },
    { key: "listaDePrecios", label: "Lista", width: 70 },
    { key: "cantidad", label: "Cant.", width: 70, num: true },
    { key: "precioUnitario", label: "P.Unit", width: 90, num: true },
    { key: "subTotal", label: "Subtotal", width: 100, num: true },
  ],
};

export default function CasosRevisar() {
  const confirmar = useConfirm();
  const toast = useToast();
  const [resumen, setResumen] = useState(null);
  const [casos, setCasos] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [filtros, setFiltros] = useStoredState(
    "casos:filtros",
    { fuente: "", motivo_codigo: "", estado: "pendiente" },
  );
  // Toggle "ver archivados". Default false (vista activa). Cuando true,
  // se piden SOLO los archivados al backend.
  const [verArchivados, setVerArchivados] = useStoredState("casos:verArchivados", false);
  const [editando, setEditando] = useState(null);  // id del caso en modo edit
  const [pagina, setPagina] = useState(0);
  // Búsqueda libre: input controlado vs query enviada al backend (debounced).
  // Persistimos el input — `busqueda` arranca sincronizada para evitar
  // doble fetch en el primer mount con valor recuperado.
  const [busquedaInput, setBusquedaInput] = useStoredState("casos:busqueda", "");
  const [busqueda, setBusqueda] = useState(busquedaInput);
  // Selección múltiple para bulk descartar.
  const [seleccionados, setSeleccionados] = useState(new Set());
  const limite = 25;

  // Debounce de la búsqueda para no spamear el backend con cada tecla.
  useEffect(() => {
    const t = setTimeout(() => {
      setBusqueda(busquedaInput);
      setPagina(0);
    }, 300);
    return () => clearTimeout(t);
  }, [busquedaInput]);

  async function cargar(signal) {
    setLoading(true);
    try {
      const params = { ...filtros, limite, offset: pagina * limite };
      if (busqueda.trim()) params.q = busqueda.trim();
      if (verArchivados) params.solo_archivados = true;
      const [r, l] = await Promise.all([
        api.get("/api/casos-revisar/resumen", { signal }),
        api.get("/api/casos-revisar", { params, signal }),
      ]);
      setResumen(r.data);
      setCasos(l.data.items);
      setTotal(l.data.total);
    } catch (e) {
      // Aborts se ignoran silenciosamente: son cancelaciones esperadas
      // cuando el usuario cambia filtro/página rápido (la próxima llamada
      // pisa la vieja).
      if (e.name !== "CanceledError" && e.code !== "ERR_CANCELED") throw e;
      return;
    } finally {
      setLoading(false);
    }
  }

  // AbortController por efecto: cuando cambian los deps (filtro, página,
  // etc.), cancelamos la fetch anterior. Sin esto, dos cargas pueden
  // resolver fuera de orden y mostrar datos viejos sobre nuevos.
  useEffect(() => {
    const ctrl = new AbortController();
    cargar(ctrl.signal);
    return () => ctrl.abort();
  }, [pagina, filtros, busqueda, verArchivados]);
  // Limpiar selección al cambiar página/filtro: la operación bulk solo
  // tiene sentido sobre lo que se ve actualmente, no sobre la "intención"
  // arrastrada de otra vista.
  useEffect(() => { setSeleccionados(new Set()); }, [pagina, filtros, busqueda, verArchivados]);

  function toggleSel(id) {
    const next = new Set(seleccionados);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSeleccionados(next);
  }

  function toggleSelTodos() {
    const idsVisibles = casos
      .filter((c) => c.estado === "pendiente")
      .map((c) => c.id);
    if (idsVisibles.every((id) => seleccionados.has(id))) {
      // Si TODOS los visibles ya están seleccionados, deseleccionar todos.
      setSeleccionados(new Set());
    } else {
      setSeleccionados(new Set(idsVisibles));
    }
  }

  async function descartarBulk() {
    const ids = [...seleccionados];
    if (ids.length === 0) return;
    const ok = await confirmar({
      titulo: "Descartar en bulk",
      mensaje: `Vas a marcar ${ids.length} casos como descartados. Acción reversible solo desde "Marcar pendiente" caso por caso.`,
      labelOk: `Descartar ${ids.length}`,
      peligroso: true,
    });
    if (!ok) return;
    const { data } = await api.post("/api/casos-revisar/descartar-bulk", { ids });
    toast.push(`${data.descartados} casos descartados`, "info");
    setSeleccionados(new Set());
    cargar();
  }

  async function descartar(id) {
    const ok = await confirmar({
      titulo: "Descartar caso",
      mensaje: "El caso quedará marcado como descartado y no se podrá editar más.",
      labelOk: "Descartar",
      peligroso: true,
    });
    if (!ok) return;
    await api.post(`/api/casos-revisar/${id}/descartar`);
    toast.push("Caso descartado", "info");
    cargar();
  }

  async function archivar(id) {
    await api.post(`/api/casos-revisar/${id}/archivar`);
    toast.push("Caso archivado", "info");
    cargar();
  }

  async function desarchivar(id) {
    await api.post(`/api/casos-revisar/${id}/desarchivar`);
    toast.push("Caso desarchivado", "info");
    cargar();
  }

  async function archivarResueltos() {
    const cantidad = (resumen?.por_estado?.descartado || 0) + (resumen?.por_estado?.corregido || 0);
    if (cantidad === 0) {
      toast.push("No hay casos resueltos para archivar", "info");
      return;
    }
    const ok = await confirmar({
      titulo: "Archivar resueltos",
      mensaje: `Vas a archivar ${cantidad} casos (descartados + corregidos). Quedan accesibles desde "Ver archivados".`,
      labelOk: `Archivar ${cantidad}`,
    });
    if (!ok) return;
    const { data } = await api.post("/api/casos-revisar/archivar-resueltos");
    toast.push(`${data.archivados} casos archivados`, "info");
    cargar();
  }

  const motivos = [...new Set((resumen?.agrupado || []).map((a) => a.motivo_codigo))];
  const fuentes = ["ventas", "detalle_ventas", "movimientos_caja"];
  const [exportando, setExportando] = useState(false);

  // Exporta TODOS los casos que matchean los filtros actuales (no solo la
  // página visible) — el caso de uso es "revisar offline en planilla", lo
  // contrario sería arbitrario. Cap defensivo: 5000 filas para no congelar
  // el browser si por alguna razón el filtro está vacío y hay decenas de
  // miles de casos descartados históricos.
  async function exportarCSV() {
    if (exportando) return;
    setExportando(true);
    try {
      const params = { ...filtros, limite: Math.min(total, 5000), offset: 0 };
      if (busqueda.trim()) params.q = busqueda.trim();
      const { data } = await api.get("/api/casos-revisar", { params });
      const filas = data.items.map((c) => ({
        id: c.id,
        fuente: c.fuente,
        estado: c.estado,
        motivo_codigo: c.motivo_codigo,
        motivo_descripcion: c.motivo_descripcion,
        // datos_originales serializado para que viaje en una sola celda.
        datos: JSON.stringify(c.datos_originales),
      }));
      descargarComoCSV(
        `casos-revisar-${filtros.estado || "todos"}-${new Date().toISOString().slice(0, 10)}.csv`,
        [
          { key: "id", label: "ID" },
          { key: "fuente", label: "Fuente" },
          { key: "estado", label: "Estado" },
          { key: "motivo_codigo", label: "Motivo" },
          { key: "motivo_descripcion", label: "Descripción" },
          { key: "datos", label: "Datos originales (JSON)" },
        ],
        filas,
      );
      if (total > 5000) {
        toast.push(`Exporté los primeros 5000 casos de ${total}. Filtrá más para acotar.`, "info");
      }
    } catch (e) {
      toast.push(e.response?.data?.detail || "Error exportando CSV", "error");
    } finally {
      setExportando(false);
    }
  }

  return (
    <>
      <h2>Casos a revisar {loading && <span className="spinner" />}</h2>
      <p style={{ color: "#94a3b8", marginTop: -10 }}>
        Filas que no pasaron validación durante import. Click en <b>Editar</b> y corregís los campos en línea — al guardar, el sistema re-importa la fila.
      </p>

      {resumen && (
        <div className="kpi-grid">
          <div className="kpi-card amber"><div className="label">Pendientes</div><div className="value">{fmtNum(resumen.por_estado?.pendiente || 0)}</div></div>
          <div className="kpi-card green"><div className="label">Corregidos</div><div className="value">{fmtNum(resumen.por_estado?.corregido || 0)}</div></div>
          <div className="kpi-card muted"><div className="label">Descartados</div><div className="value">{fmtNum(resumen.por_estado?.descartado || 0)}</div></div>
          <div className="kpi-card"><div className="label">Archivados</div><div className="value">{fmtNum(resumen.archivados || 0)}</div></div>
        </div>
      )}

      <div className="toolbar">
        <label>Fuente</label>
        <select value={filtros.fuente} onChange={(e) => { setPagina(0); setFiltros({ ...filtros, fuente: e.target.value }); }}>
          <option value="">Todas</option>
          {fuentes.map((f) => <option key={f}>{f}</option>)}
        </select>
        <label>Motivo</label>
        <select value={filtros.motivo_codigo} onChange={(e) => { setPagina(0); setFiltros({ ...filtros, motivo_codigo: e.target.value }); }}>
          <option value="">Todos</option>
          {motivos.map((m) => <option key={m}>{m}</option>)}
        </select>
        <label>Estado</label>
        <select value={filtros.estado} onChange={(e) => { setPagina(0); setFiltros({ ...filtros, estado: e.target.value }); }}>
          <option value="pendiente">Pendiente</option>
          <option value="corregido">Corregido</option>
          <option value="descartado">Descartado</option>
          <option value="">Todos</option>
        </select>
        <input
          type="search"
          value={busquedaInput}
          onChange={(e) => setBusquedaInput(e.target.value)}
          placeholder="Buscar en motivo o datos..."
          style={{ flex: 1, minWidth: 200 }}
        />
        {seleccionados.size > 0 && (
          <button className="btn btn-danger" onClick={descartarBulk}>
            Descartar {seleccionados.size} seleccionado{seleccionados.size === 1 ? "" : "s"}
          </button>
        )}
        <label style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "#94a3b8" }}>
          <input
            type="checkbox"
            checked={verArchivados}
            onChange={(e) => { setPagina(0); setVerArchivados(e.target.checked); }}
          />
          Ver archivados ({fmtNum(resumen?.archivados || 0)})
        </label>
        {!verArchivados && ((resumen?.por_estado?.descartado || 0) + (resumen?.por_estado?.corregido || 0)) > 0 && (
          <button className="btn-ghost btn" onClick={archivarResueltos} title="Archiva todos los descartados y corregidos">
            Archivar resueltos
          </button>
        )}
      </div>

      <div className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>{fmtNum(total)} casos {filtros.estado || "totales"}</h3>
          {total > 0 && (
            <button
              className="btn-ghost btn"
              onClick={exportarCSV}
              disabled={exportando}
              title={`Descargar todos los ${total} casos del filtro actual en CSV`}
              style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12 }}
            >
              {exportando ? <span className="spinner" /> : <Icon name="download" size={12} />}
              CSV {total > limite && `(${fmtNum(Math.min(total, 5000))})`}
            </button>
          )}
        </div>
        {casos.length === 0 && <div className="empty">No hay casos con esos filtros 🎉</div>}
        {casos.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: 30 }}>
                    {!verArchivados && (
                      <input
                        type="checkbox"
                        checked={
                          casos.filter((c) => c.estado === "pendiente").length > 0 &&
                          casos.filter((c) => c.estado === "pendiente").every((c) => seleccionados.has(c.id))
                        }
                        onChange={toggleSelTodos}
                        title="Seleccionar todos los pendientes visibles"
                      />
                    )}
                  </th>
                  <th style={{ width: 50 }}>ID</th>
                  <th style={{ width: 110 }}>Fuente</th>
                  <th style={{ width: 130 }}>Motivo</th>
                  <th>Detalle</th>
                  <th style={{ width: 200 }}>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {casos.map((c) => (
                  <Fragment key={c.id}>
                    <tr>
                      <td>
                        {!verArchivados && c.estado === "pendiente" && (
                          <input
                            type="checkbox"
                            checked={seleccionados.has(c.id)}
                            onChange={() => toggleSel(c.id)}
                          />
                        )}
                      </td>
                      <td>{c.id}</td>
                      <td><span className="badge muted">{c.fuente}</span></td>
                      <td><span className={`badge ${c.estado === "corregido" ? "ok" : "warn"}`}>{c.motivo_codigo}</span></td>
                      <td style={{ color: "#cbd5e1", fontSize: 12 }}>{c.motivo_descripcion}</td>
                      <td>
                        {verArchivados ? (
                          <>
                            <span style={{ color: "#94a3b8", fontSize: 12, marginRight: 8 }}>{c.estado}</span>
                            <button className="btn-ghost btn" onClick={() => desarchivar(c.id)}>Desarchivar</button>
                          </>
                        ) : c.estado === "pendiente" ? (
                          <>
                            <button
                              className="btn"
                              style={{ marginRight: 6 }}
                              onClick={() => setEditando(editando === c.id ? null : c.id)}
                            >
                              {editando === c.id ? "Cerrar" : "Editar"}
                            </button>
                            <button className="btn btn-danger" style={{ marginRight: 6 }} onClick={() => descartar(c.id)}>Descartar</button>
                            <button className="btn-ghost btn" onClick={() => archivar(c.id)} title="Sacar de la vista (reversible)">Archivar</button>
                          </>
                        ) : (
                          <>
                            <span style={{ color: "#94a3b8", fontSize: 12, marginRight: 8 }}>{c.estado}</span>
                            <button className="btn-ghost btn" onClick={() => archivar(c.id)} title="Sacar de la vista (reversible)">Archivar</button>
                          </>
                        )}
                      </td>
                    </tr>
                    {editando === c.id && (
                      <tr>
                        <td colSpan={6} style={{ background: "#0f172a", padding: 0 }}>
                          <FilaEditable
                            caso={c}
                            onCancel={() => setEditando(null)}
                            onDone={() => { setEditando(null); cargar(); }}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div style={{ marginTop: 16, display: "flex", gap: 10, alignItems: "center" }}>
          <button className="btn-ghost btn" disabled={pagina === 0} onClick={() => setPagina(pagina - 1)}>← Anterior</button>
          <span>Página {pagina + 1} de {Math.ceil(total / limite) || 1}</span>
          <button className="btn-ghost btn" disabled={(pagina + 1) * limite >= total} onClick={() => setPagina(pagina + 1)}>Siguiente →</button>
        </div>
      </div>
    </>
  );
}

function FilaEditable({ caso, onCancel, onDone }) {
  const [campos, setCampos] = useState(() => ({ ...caso.datos_originales }));
  const [busy, setBusy] = useState(false);
  const [resultado, setResultado] = useState(null);
  const [sugerencias, setSugerencias] = useState(null);

  const cols = COLUMNAS[caso.fuente] || [];
  // Cualquier campo del original que NO esté en COLUMNAS, mantenerlo intacto pero ocultarlo.
  const camposOcultos = Object.keys(caso.datos_originales).filter(
    (k) => !cols.find((c) => c.key === k)
  );

  // Sugerencias de caja: solo aplica al motivo sin_caja (movimientos_caja).
  const aplicaSugerencias = caso.motivo_codigo === "sin_caja"
    && caso.fuente === "movimientos_caja";

  useEffect(() => {
    if (!aplicaSugerencias) return;
    const ctrl = new AbortController();
    api.get(`/api/casos-revisar/${caso.id}/sugerencias-caja`, { signal: ctrl.signal })
      .then((r) => setSugerencias(r.data))
      .catch((e) => {
        if (e.name === "CanceledError" || e.code === "ERR_CANCELED") return;
        setSugerencias({ sugerencias: [] });
      });
    return () => ctrl.abort();
  }, [caso.id, aplicaSugerencias]);

  function setField(k, v) {
    setCampos({ ...campos, [k]: v });
  }

  function aplicarSugerencia(s) {
    // Pre-llena SALIDAS o ENTRADAS según la dirección sugerida.
    // Si la dirección es "ambas" (transferencia), pone en ENTRADAS por
    // default — la dueña edita si fue al revés.
    const next = { ...campos };
    if (s.direccion === "salida") next.SALIDAS = s.nombre_display;
    else next.ENTRADAS = s.nombre_display;
    setCampos(next);
  }

  async function reintentar() {
    setBusy(true);
    setResultado(null);
    try {
      const { data } = await api.post(`/api/casos-revisar/${caso.id}/reintentar`, campos);
      setResultado(data);
      if (data.ok) {
        setTimeout(onDone, 1500);
      }
    } catch (e) {
      setResultado({ ok: false, mensaje: e.response?.data?.detail || e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ padding: 14 }}>
      {aplicaSugerencias && sugerencias && sugerencias.sugerencias.length > 0 && (
        <div style={{
          marginBottom: 14, padding: 10,
          background: "#1e293b", border: "1px solid #334155", borderRadius: 6,
        }}>
          <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 8 }}>
            Cajas usadas históricamente para <b>"{sugerencias.tipo_operacion}"</b>:
            {' '}clickeá una para pre-llenar SALIDAS o ENTRADAS.
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {sugerencias.sugerencias.map((s) => (
              <button
                key={s.nombre_normalizado}
                className="btn-ghost btn"
                style={{ fontSize: 12, padding: "4px 10px" }}
                onClick={() => aplicarSugerencia(s)}
                title={`${s.usos_origen} usos como salida, ${s.usos_destino} como entrada`}
              >
                {s.nombre_display}
                <span style={{
                  color: s.direccion === "salida" ? "#fca5a5" : s.direccion === "entrada" ? "#86efac" : "#94a3b8",
                  marginLeft: 6, fontSize: 10,
                }}>
                  {s.direccion === "salida" ? "↑ salida" : s.direccion === "entrada" ? "↓ entrada" : "↕ ambas"}
                </span>
                <span style={{ color: "#64748b", marginLeft: 6, fontSize: 10 }}>
                  {s.total_usos} usos
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 14 }}>
        {cols.map((c) => (
          <div key={c.key} style={{ width: c.width, flex: c.full ? "1 1 200px" : `0 0 ${c.width}px` }}>
            <label style={{ fontSize: 11, color: "#94a3b8", display: "block", marginBottom: 2 }}>{c.label}</label>
            <input
              value={campos[c.key] == null ? "" : String(campos[c.key])}
              onChange={(e) => setField(c.key, e.target.value)}
              style={{
                width: "100%",
                textAlign: c.num ? "right" : "left",
                fontVariantNumeric: c.num ? "tabular-nums" : "normal",
              }}
            />
          </div>
        ))}
      </div>

      {camposOcultos.length > 0 && (
        <details style={{ marginBottom: 12, color: "#64748b", fontSize: 11 }}>
          <summary style={{ cursor: "pointer" }}>+ ver {camposOcultos.length} campos técnicos no editables</summary>
          <pre className="json" style={{ marginTop: 6 }}>
            {JSON.stringify(Object.fromEntries(camposOcultos.map((k) => [k, caso.datos_originales[k]])), null, 2)}
          </pre>
        </details>
      )}

      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <button className="btn" disabled={busy} onClick={reintentar}>
          {busy ? <span className="spinner" /> : "Guardar y re-importar"}
        </button>
        <button className="btn-ghost btn" onClick={onCancel}>Cancelar</button>
        {resultado && (
          <span style={{
            color: resultado.ok ? "#34d399" : "#f87171",
            fontSize: 13,
            marginLeft: 10,
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
          }}>
            <Icon name={resultado.ok ? "check" : "x"} size={14} label={resultado.ok ? "OK" : "Error"} />
            {resultado.mensaje}
            {resultado.nuevo_motivo_codigo && (
              <span style={{ color: "#94a3b8", marginLeft: 6 }}>({resultado.nuevo_motivo_codigo})</span>
            )}
          </span>
        )}
      </div>
    </div>
  );
}
