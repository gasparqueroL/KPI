import { useEffect, useState } from "react";
import api, { fmtMoney, fmtNum, urlBackend } from "../api/client";
import { useConfirm } from "../components/ConfirmDialog";
import Icon from "../components/Icon";
import Skeleton, { SkeletonKpiGrid } from "../components/Skeleton";
import { useToast } from "../components/Toast";

export default function Configuracion() {
  const [tab, setTab] = useState("categorias");
  return (
    <>
      <h2>Configuración</h2>
      <div className="toolbar">
        <button
          className={tab === "categorias" ? "btn" : "btn-ghost btn"}
          onClick={() => setTab("categorias")}
        >
          Categorías de caja
        </button>
        <button
          className={tab === "cajas" ? "btn" : "btn-ghost btn"}
          onClick={() => setTab("cajas")}
        >
          Cajas / Formas de pago
        </button>
        <button
          className={tab === "backups" ? "btn" : "btn-ghost btn"}
          onClick={() => setTab("backups")}
        >
          Backups
        </button>
        <button
          className={tab === "sistema" ? "btn" : "btn-ghost btn"}
          onClick={() => setTab("sistema")}
        >
          Sistema
        </button>
      </div>
      {tab === "categorias" && <Categorias />}
      {tab === "cajas" && <Cajas />}
      {tab === "backups" && <Backups />}
      {tab === "sistema" && <Sistema />}
    </>
  );
}

function Sistema() {
  const [freezeStatus, setFreezeStatus] = useState(null);
  const [actividad, setActividad] = useState(null);
  const [duplicados, setDuplicados] = useState(null);
  const [movDuplicados, setMovDuplicados] = useState(null);
  // health: null=cargando, {status:"ok",...}=ok, {status:"down"}=caído.
  // Usamos un objeto con status para distinguir "todavía cargando" vs
  // "respondió pero falló" — con allSettled no es lo mismo.
  const [health, setHealth] = useState(null);

  useEffect(() => {
    // allSettled en lugar de all: si el endpoint /health falla con 503
    // (justo el caso que motiva el endpoint), los otros paneles deben
    // seguir mostrando datos en vez de quedarse en "Cargando..." para siempre.
    Promise.allSettled([
      api.get("/api/admin/freeze-status", { silent: true }),
      api.get("/api/admin/ultima-actividad", { silent: true }),
      api.get("/api/health", { silent: true }),
      api.get("/api/admin/clientes-duplicados-sospechosos", { silent: true }),
      api.get("/api/admin/movimientos-duplicados-sospechosos", { silent: true }),
    ]).then(([f, a, h, d, md]) => {
      setFreezeStatus(f.status === "fulfilled" ? f.value.data : { error: true });
      setActividad(a.status === "fulfilled" ? a.value.data : { error: true });
      setHealth(h.status === "fulfilled" ? h.value.data : { status: "down" });
      setDuplicados(d.status === "fulfilled" ? d.value.data : { error: true });
      setMovDuplicados(md.status === "fulfilled" ? md.value.data : { error: true });
    });
  }, []);

  return (
    <>
      <div className="panel">
        <h3>Estado del sistema</h3>
        {health == null ? (
          <Skeleton width="50%" height={18} />
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14 }}>
            <span style={{
              width: 12, height: 12, borderRadius: "50%",
              background: health.status === "ok" ? "#34d399" : "#f87171",
              boxShadow: health.status === "ok" ? "0 0 6px #34d399" : "0 0 6px #f87171",
            }} />
            <b style={{ textTransform: "uppercase" }}>{health.status}</b>
            {health.status === "ok" ? (
              <span style={{ color: "#94a3b8" }}>· uptime {fmtUptime(health.uptime_segundos)}</span>
            ) : (
              <span style={{ color: "#f87171" }}>· backend no responde</span>
            )}
          </div>
        )}
      </div>

      <div className="panel">
        <h3>Última actividad</h3>
        <p style={{ color: "#94a3b8", fontSize: 12, marginTop: -6 }}>
          Cuándo se cargó por última vez cada tabla principal. Útil para verificar
          si un import quedó con error o si hace mucho que no se actualizan los datos.
        </p>
        {actividad == null ? (
          <>
            <Skeleton width="100%" height={14} style={{ marginBottom: 8 }} />
            <Skeleton width="100%" height={14} style={{ marginBottom: 8 }} />
            <Skeleton width="100%" height={14} />
          </>
        ) : actividad.error ? (
          <div className="empty" style={{ color: "#f87171" }}>No se pudo cargar la actividad.</div>
        ) : (
          <table>
            <thead>
              <tr><th>Tabla</th><th className="num">Filas</th><th>Última carga</th></tr>
            </thead>
            <tbody>
              <tr><td>Ventas</td><td className="num">{fmtNum(actividad.ventas.total_filas)}</td><td>{fmtFecha(actividad.ventas.ultima_carga)}</td></tr>
              <tr><td>Movimientos de caja</td><td className="num">{fmtNum(actividad.movimientos_caja.total_filas)}</td><td>{fmtFecha(actividad.movimientos_caja.ultima_carga)}</td></tr>
              <tr><td>Facturas de proveedor</td><td className="num">{fmtNum(actividad.facturas_proveedor.total_filas)}</td><td>{fmtFecha(actividad.facturas_proveedor.ultima_carga)}</td></tr>
            </tbody>
          </table>
        )}
      </div>

      <PanelDuplicados duplicados={duplicados} />

      <PanelMovDuplicados movDuplicados={movDuplicados} />

      <div className="panel">
        <h3>Estado de la migración legacy → pago_aplicado</h3>
        <p style={{ color: "#94a3b8", fontSize: 13, marginTop: -6 }}>
          El sistema usa <b>pago_aplicado</b> (vinculación granular movimiento↔venta) como flujo recomendado.
          Los movimientos viejos siguen usando <b>id_cliente_relacionado</b> (FIFO automático). Cuando este contador llegue a 0,
          se puede ejecutar la migración B documentada en <code>docs/superpowers/plans/migracion-pago-aplicado-futura.md</code>.
        </p>
        {freezeStatus == null ? (
          <SkeletonKpiGrid cards={3} />
        ) : freezeStatus.error ? (
          <div className="empty" style={{ color: "#f87171" }}>No se pudo cargar el estado de migración.</div>
        ) : (
          <div className="kpi-grid" style={{ marginTop: 12 }}>
            <div className="kpi-card">
              <div className="label">Total con id_cliente_relacionado</div>
              <div className="value">{fmtNum(freezeStatus.legacy_total)}</div>
              <div className="sub">movimientos legacy en sistema</div>
            </div>
            <div className="kpi-card amber">
              <div className="label">Sin pago_aplicado</div>
              <div className="value">{fmtNum(freezeStatus.legacy_sin_pago_aplicado)}</div>
              <div className="sub">deuda pendiente de migrar</div>
            </div>
            <div className="kpi-card green">
              <div className="label">Con cobertura granular</div>
              <div className="value">{fmtNum(freezeStatus.legacy_con_pago_aplicado)}</div>
              <div className="sub">tienen pago_aplicado además del legacy</div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function PanelDuplicados({ duplicados }) {
  const [verTodos, setVerTodos] = useState(false);

  const grupos = duplicados?.grupos || [];
  const visibles = verTodos ? grupos : grupos.slice(0, 10);

  return (
    <div className="panel">
      <h3>Clientes con nombres similares (posibles duplicados)</h3>
      <p style={{ color: "#94a3b8", fontSize: 13, marginTop: -6 }}>
        IDs de cliente distintos cuyos nombres normalizan al mismo string
        (ej. "Acme SA" vs "Acme S.A."). Heurística: ignora tildes, puntuación
        y sufijos S.A./SRL/SL al final del nombre. Para fusionar, editá
        manualmente las ventas del id menos usado para apuntar al id correcto.
      </p>
      <div style={{
        background: "#1e3a8a22", border: "1px solid #1e3a8a", padding: 8,
        borderRadius: 6, fontSize: 12, color: "#bfdbfe", marginBottom: 12,
      }}>
        <b>Atención:</b> los sufijos societarios (S.A., SRL, etc.) se ignoran.
        Esto puede agrupar empresas legalmente distintas con la misma raíz
        ("Acme SA" y "Acme SRL"). Verificá manualmente antes de tratarlas como
        duplicado.
      </div>
      {duplicados == null ? (
        <>
          <Skeleton width="40%" height={14} style={{ marginBottom: 10 }} />
          <Skeleton width="100%" height={14} style={{ marginBottom: 6 }} />
          <Skeleton width="100%" height={14} style={{ marginBottom: 6 }} />
          <Skeleton width="80%" height={14} />
        </>
      ) : duplicados.error ? (
        <div className="empty" style={{ color: "#f87171" }}>No se pudo cargar.</div>
      ) : duplicados.total_grupos === 0 ? (
        <div className="empty" style={{ color: "#34d399" }}>Sin duplicados detectados.</div>
      ) : (
        <>
          <div style={{ color: "#fbbf24", fontSize: 13, marginBottom: 12 }}>
            {duplicados.total_grupos} grupo{duplicados.total_grupos === 1 ? "" : "s"} sospechoso{duplicados.total_grupos === 1 ? "" : "s"}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {visibles.map((g) => (
              <div key={g.nombre_normalizado} style={{
                background: "#0f172a", border: "1px solid #334155",
                borderRadius: 6, padding: 10,
              }}>
                <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 6 }}>
                  Normalizado: <code style={{ color: "#cbd5e1" }}>{g.nombre_normalizado}</code>
                </div>
                <table style={{ fontSize: 13 }}>
                  <thead>
                    <tr><th>ID</th><th>Cliente</th><th className="num">Pedidos</th><th className="num">Ventas</th><th>Última</th></tr>
                  </thead>
                  <tbody>
                    {g.clientes.map((c) => (
                      <tr key={c.id_cliente}>
                        <td>{c.id_cliente}</td>
                        <td>{c.cliente}</td>
                        <td className="num">{fmtNum(c.pedidos)}</td>
                        <td className="num">{fmtMoney(c.total_ventas)}</td>
                        <td style={{ color: "#94a3b8", fontSize: 11 }}>
                          {c.ultima_venta?.slice(0, 10) || "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
            {grupos.length > 10 && (
              <button
                className="btn-ghost btn"
                onClick={() => setVerTodos((v) => !v)}
                style={{ alignSelf: "flex-start" }}
              >
                {verTodos
                  ? `Mostrar solo top 10`
                  : `Mostrar todos (${grupos.length} grupos)`}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function PanelMovDuplicados({ movDuplicados }) {
  const [verTodos, setVerTodos] = useState(false);
  const grupos = movDuplicados?.grupos || [];
  const visibles = verTodos ? grupos : grupos.slice(0, 10);

  return (
    <div className="panel">
      <h3>Movimientos de caja con datos repetidos</h3>
      <p style={{ color: "#94a3b8", fontSize: 13, marginTop: -6 }}>
        Movimientos con misma fecha + monto + cajas + tipo de operación.
        El dedupe del import ya bloquea duplicados exactos por hash, pero
        si dos cargas tienen detalle ligeramente distinto ("Pago fact 123"
        vs "Pago factura 123") pueden colarse igual. Verificá manualmente:
        no todo grupo es error (puede ser un pago real repetido el mismo día).
      </p>
      {movDuplicados == null ? (
        <>
          <Skeleton width="100%" height={14} style={{ marginBottom: 6 }} />
          <Skeleton width="100%" height={14} style={{ marginBottom: 6 }} />
          <Skeleton width="80%" height={14} />
        </>
      ) : movDuplicados.error ? (
        <div className="empty" style={{ color: "#f87171" }}>No se pudo cargar.</div>
      ) : movDuplicados.total_grupos === 0 ? (
        <div className="empty" style={{ color: "#34d399" }}>Sin movimientos repetidos detectados.</div>
      ) : (
        <>
          <div style={{ color: "#fbbf24", fontSize: 13, marginBottom: 12 }}>
            {movDuplicados.total_grupos} grupo{movDuplicados.total_grupos === 1 ? "" : "s"} sospechoso{movDuplicados.total_grupos === 1 ? "" : "s"}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {visibles.map((g, idx) => (
              <div key={idx} style={{
                background: "#0f172a", border: "1px solid #334155",
                borderRadius: 6, padding: 10,
              }}>
                <div style={{ fontSize: 12, color: "#cbd5e1", marginBottom: 6 }}>
                  <b>{g.fecha}</b> · {fmtMoney(g.monto)} · {g.tipo_operacion}
                  {g.caja_origen && <> · origen <code>{g.caja_origen}</code></>}
                  {g.caja_destino && <> · destino <code>{g.caja_destino}</code></>}
                  · <span style={{ color: "#fbbf24" }}>{g.cantidad} repetidos</span>
                </div>
                <table style={{ fontSize: 12 }}>
                  <thead>
                    <tr><th>ID</th><th>Detalle</th><th>Cliente</th><th>Factura</th></tr>
                  </thead>
                  <tbody>
                    {g.movimientos.map((m) => (
                      <tr key={m.id}>
                        <td>{m.id}</td>
                        <td>{m.detalle || "(sin detalle)"}</td>
                        <td>{m.id_cliente_relacionado ?? "-"}</td>
                        <td>{m.id_factura_proveedor ?? "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
            {grupos.length > 10 && (
              <button
                className="btn-ghost btn"
                onClick={() => setVerTodos((v) => !v)}
                style={{ alignSelf: "flex-start" }}
              >
                {verTodos
                  ? `Mostrar solo top 10`
                  : `Mostrar todos (${grupos.length} grupos)`}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function fmtFecha(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("es-AR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function fmtUptime(segs) {
  if (segs == null) return "—";
  const d = Math.floor(segs / 86400);
  const h = Math.floor((segs % 86400) / 3600);
  const m = Math.floor((segs % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${Math.round(segs)}s`;
}

function Backups() {
  const confirmar = useConfirm();
  const toast = useToast();
  const [info, setInfo] = useState(null);
  const [backups, setBackups] = useState([]);
  const [busy, setBusy] = useState(false);

  async function cargar(signal) {
    try {
      const [i, b] = await Promise.allSettled([
        api.get("/api/admin/info", { signal }),
        api.get("/api/admin/backups", { signal }),
      ]);
      if (i.status === "fulfilled") setInfo(i.value.data);
      if (b.status === "fulfilled") setBackups(b.value.data);
    } catch (e) {
      if (e.name !== "CanceledError" && e.code !== "ERR_CANCELED") {
        toast.push("Error cargando admin", "error");
      }
    }
  }
  useEffect(() => {
    const ctrl = new AbortController();
    cargar(ctrl.signal);
    return () => ctrl.abort();
  }, []);

  async function crearBackup() {
    setBusy(true);
    try {
      await api.post("/api/admin/backup");
      cargar();
    } finally { setBusy(false); }
  }

  async function borrar(archivo) {
    const ok = await confirmar({
      titulo: "Borrar backup",
      mensaje: `Se eliminará el archivo ${archivo} permanentemente.`,
      labelOk: "Borrar",
      peligroso: true,
    });
    if (!ok) return;
    await api.delete(`/api/admin/backups/${archivo}`);
    toast.push("Backup borrado", "info");
    cargar();
  }

  return (
    <>
      {info ? (
        <div className="kpi-grid">
          <div className="kpi-card"><div className="label">Tamaño BD</div><div className="value">{info.db_tamano_kb.toLocaleString("es-AR")} KB</div></div>
          <div className="kpi-card"><div className="label">Backups</div><div className="value">{fmtNum(info.backups_count)}</div><div className="sub">{info.backups_tamano_kb.toLocaleString("es-AR")} KB total</div></div>
          <div className="kpi-card green">
            <div className="label">Último backup</div>
            <div className="value" style={{ fontSize: 14 }}>
              {info.ultimo_backup ? new Date(info.ultimo_backup * 1000).toLocaleString("es-AR") : "(ninguno)"}
            </div>
          </div>
        </div>
      ) : (
        <SkeletonKpiGrid cards={3} />
      )}

      <div className="panel">
        <h3>Backups disponibles</h3>
        <div style={{ marginBottom: 12, color: "#94a3b8", fontSize: 13 }}>
          La BD se respalda <b>automáticamente al arrancar el servidor</b> si ese día todavía no hay un backup.
          Podés además crear uno manual cuando quieras (recomendado antes de operaciones grandes).
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn" disabled={busy} onClick={crearBackup}>
            {busy ? <span className="spinner" /> : "Crear backup ahora"}
          </button>
          <a
            className="btn-ghost btn"
            href={urlBackend("/api/admin/export.json")}
            download
            title="Descarga un JSON con todos los datos (clientes, ventas, movimientos, proveedores). Útil para llevarse una copia o auditar en herramientas externas."
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            <Icon name="download" size={14} /> Exportar todo a JSON
          </a>
        </div>

        {backups.length === 0 && <div className="empty" style={{ marginTop: 16 }}>No hay backups todavía.</div>}
        {backups.length > 0 && (
          <table style={{ marginTop: 16 }}>
            <thead><tr><th>Archivo</th><th className="num">Tamaño</th><th>Creado</th><th></th></tr></thead>
            <tbody>
              {backups.map((b) => (
                <tr key={b.archivo}>
                  <td style={{ fontFamily: "monospace" }}>{b.archivo}</td>
                  <td className="num">{b.tamaño_kb.toLocaleString("es-AR")} KB</td>
                  <td>{new Date(b.creado).toLocaleString("es-AR")}</td>
                  <td><button className="btn-ghost btn btn-danger" onClick={() => borrar(b.archivo)}>Borrar</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function Categorias() {
  const [cats, setCats] = useState([]);
  const [familias, setFamilias] = useState([]);
  const [edits, setEdits] = useState({});
  const [saving, setSaving] = useState(null);

  async function cargar(signal) {
    try {
      const [c, f] = await Promise.allSettled([
        api.get("/api/config/categorias", { signal }),
        api.get("/api/config/familias", { signal }),
      ]);
      if (c.status === "fulfilled") setCats(c.value.data);
      if (f.status === "fulfilled") setFamilias(f.value.data);
    } catch (e) {
      if (e.name === "CanceledError" || e.code === "ERR_CANCELED") return;
      throw e;
    }
  }
  useEffect(() => {
    const ctrl = new AbortController();
    cargar(ctrl.signal);
    return () => ctrl.abort();
  }, []);

  function setField(tipo, field, value) {
    setEdits({
      ...edits,
      [tipo]: { ...(edits[tipo] || cats.find((c) => c.tipo_operacion === tipo)), [field]: value },
    });
  }

  async function guardar(tipo) {
    setSaving(tipo);
    const original = cats.find((c) => c.tipo_operacion === tipo);
    const merged = { ...original, ...(edits[tipo] || {}) };
    await api.put(`/api/config/categorias/${encodeURIComponent(tipo)}`, {
      familia: merged.familia,
      excluir_flujo: !!merged.excluir_flujo,
      es_transferencia: !!merged.es_transferencia,
      es_retiro: !!merged.es_retiro,
      es_ingreso_operativo: !!merged.es_ingreso_operativo,
      es_costo_fijo: !!merged.es_costo_fijo,
      descripcion: merged.descripcion,
    });
    const ne = { ...edits };
    delete ne[tipo];
    setEdits(ne);
    setSaving(null);
    cargar();
  }

  return (
    <div className="panel">
      <h3>Categorías ({cats.length})</h3>
      <div style={{ color: "#94a3b8", fontSize: 13, marginBottom: 12 }}>
        <b>Familia:</b> agrupación visual en gráficos. <b>Transferencia:</b> movimiento entre cajas internas, NO es gasto. <b>Retiro:</b> retiro del dueño, NO es gasto operativo. <b>Excluir flujo:</b> NO computar en flujo de caja. <b>Costo fijo:</b> sueldos/alquileres/servicios — habilita el cálculo de punto de equilibrio.
      </div>
      <table>
        <thead>
          <tr>
            <th>Categoría</th>
            <th>Familia</th>
            <th>Transferencia</th>
            <th>Retiro</th>
            <th>Excluir</th>
            <th>Operativo</th>
            <th>Costo fijo</th>
            <th className="num">Movimientos</th>
            <th className="num">Monto total</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {cats.map((c) => {
            const cur = edits[c.tipo_operacion]
              ? { ...c, ...edits[c.tipo_operacion] }
              : c;
            const dirty = !!edits[c.tipo_operacion];
            return (
              <tr key={c.tipo_operacion}>
                <td>{c.tipo_operacion}</td>
                <td>
                  <select
                    value={cur.familia || ""}
                    onChange={(e) => setField(c.tipo_operacion, "familia", e.target.value || null)}
                  >
                    <option value="">(ninguna)</option>
                    {familias.map((f) => <option key={f} value={f}>{f}</option>)}
                  </select>
                </td>
                <td>
                  <input type="checkbox" checked={!!cur.es_transferencia}
                    onChange={(e) => setField(c.tipo_operacion, "es_transferencia", e.target.checked)} />
                </td>
                <td>
                  <input type="checkbox" checked={!!cur.es_retiro}
                    onChange={(e) => setField(c.tipo_operacion, "es_retiro", e.target.checked)} />
                </td>
                <td>
                  <input type="checkbox" checked={!!cur.excluir_flujo}
                    onChange={(e) => setField(c.tipo_operacion, "excluir_flujo", e.target.checked)} />
                </td>
                <td>
                  <input type="checkbox" checked={!!cur.es_ingreso_operativo}
                    onChange={(e) => setField(c.tipo_operacion, "es_ingreso_operativo", e.target.checked)} />
                </td>
                <td>
                  <input type="checkbox" checked={!!cur.es_costo_fijo}
                    onChange={(e) => setField(c.tipo_operacion, "es_costo_fijo", e.target.checked)} />
                </td>
                <td className="num">{fmtNum(c.movimientos)}</td>
                <td className="num">{fmtMoney(c.monto_total)}</td>
                <td>
                  <button
                    className="btn"
                    disabled={!dirty || saving === c.tipo_operacion}
                    onClick={() => guardar(c.tipo_operacion)}
                  >
                    {saving === c.tipo_operacion ? <span className="spinner" /> : "Guardar"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Cajas() {
  const confirmar = useConfirm();
  const toast = useToast();
  const [cajas, setCajas] = useState([]);
  const [merge, setMerge] = useState({ desde: "", hacia: "" });
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [filtro, setFiltro] = useState("");
  const [verArchivadas, setVerArchivadas] = useState(false);

  async function cargar(signal) {
    setLoading(true);
    try {
      const params = verArchivadas ? { incluir_archivadas: true } : {};
      const { data } = await api.get("/api/config/cajas", { params, signal });
      setCajas(data);
    } catch (e) {
      if (e.name !== "CanceledError" && e.code !== "ERR_CANCELED") throw e;
      return;
    } finally {
      setLoading(false);
    }
  }

  // AbortController por efecto: toggles rápidos no dejan datos viejos.
  useEffect(() => {
    const ctrl = new AbortController();
    cargar(ctrl.signal);
    return () => ctrl.abort();
  }, [verArchivadas]);

  async function archivar(c) {
    await api.post(`/api/config/cajas/${encodeURIComponent(c.nombre_normalizado)}/archivar`);
    toast.push(`Caja "${c.nombre_display}" archivada`, "info");
    cargar();
  }

  async function desarchivar(c) {
    await api.post(`/api/config/cajas/${encodeURIComponent(c.nombre_normalizado)}/desarchivar`);
    toast.push(`Caja "${c.nombre_display}" desarchivada`, "info");
    cargar();
  }

  async function archivarInactivas() {
    const candidatas = cajas.filter(
      (c) => !c.archivado_at && c.uso_total === 0,
    );
    if (candidatas.length === 0) {
      toast.push("No hay cajas sin uso para archivar", "info");
      return;
    }
    const ok = await confirmar({
      titulo: "Archivar cajas sin uso",
      mensaje: `Vas a archivar ${candidatas.length} cajas que NO tienen movimientos ni ventas. Reversible (clic en "Desarchivar" desde "Ver archivadas").`,
      labelOk: `Archivar ${candidatas.length}`,
    });
    if (!ok) return;
    setBusy(true);
    try {
      const { data } = await api.post("/api/config/cajas/archivar-inactivas");
      toast.push(`${data.archivadas} cajas archivadas`, "info");
      cargar();
    } finally {
      setBusy(false);
    }
  }

  async function ejecutarMerge() {
    if (!merge.desde || !merge.hacia) return;
    if (merge.desde === merge.hacia) {
      toast.push("Origen y destino deben ser distintos", "error");
      return;
    }
    const dispCfg = (n) => cajas.find((c) => c.nombre_normalizado === n)?.nombre_display || n;
    const ok = await confirmar({
      titulo: "Mergear cajas",
      mensaje: `"${dispCfg(merge.desde)}" → "${dispCfg(merge.hacia)}"\n\nLa primera caja se eliminará y todas sus referencias pasarán a la segunda.`,
      labelOk: "Mergear",
      peligroso: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await api.post("/api/config/cajas/merge", merge);
      setMerge({ desde: "", hacia: "" });
      cargar();
    } finally {
      setBusy(false);
    }
  }

  const filtradas = cajas.filter((c) =>
    c.nombre_display.toLowerCase().includes(filtro.toLowerCase())
  );

  return (
    <>
      <div className="panel">
        <h3>Mergear cajas (unificar variantes mal escritas)</h3>
        <div style={{ color: "#94a3b8", fontSize: 13, marginBottom: 12 }}>
          Elegí la caja a eliminar y la caja que la absorbe. Todas las ventas y movimientos de la primera pasan a la segunda.
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <select value={merge.desde} onChange={(e) => setMerge({ ...merge, desde: e.target.value })}>
            <option value="">— Caja a eliminar —</option>
            {cajas.map((c) => <option key={c.nombre_normalizado} value={c.nombre_normalizado}>{c.nombre_display} ({c.uso_total} usos)</option>)}
          </select>
          <span>→</span>
          <select value={merge.hacia} onChange={(e) => setMerge({ ...merge, hacia: e.target.value })}>
            <option value="">— Caja destino —</option>
            {cajas.map((c) => <option key={c.nombre_normalizado} value={c.nombre_normalizado}>{c.nombre_display} ({c.uso_total} usos)</option>)}
          </select>
          <button className="btn btn-danger" disabled={busy || !merge.desde || !merge.hacia} onClick={ejecutarMerge}>
            {busy ? "Mergeando..." : "Ejecutar merge"}
          </button>
        </div>
      </div>

      <div className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12, marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>
            {verArchivadas ? "Cajas archivadas" : "Cajas existentes"} ({cajas.length})
            {loading && <span className="spinner" style={{ marginLeft: 8 }} />}
          </h3>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "#94a3b8" }}>
              <input
                type="checkbox"
                checked={verArchivadas}
                onChange={(e) => setVerArchivadas(e.target.checked)}
              />
              Ver archivadas
            </label>
            {!verArchivadas && (
              <button
                className="btn-ghost btn"
                onClick={archivarInactivas}
                disabled={busy}
                title="Archiva todas las cajas sin movimientos ni ventas"
              >
                Archivar inactivas
              </button>
            )}
          </div>
        </div>
        <input
          placeholder="Filtrar..."
          value={filtro}
          onChange={(e) => setFiltro(e.target.value)}
          style={{ marginBottom: 12, width: 240 }}
        />
        <table>
          <thead>
            <tr>
              <th>Nombre</th>
              <th>Tipo</th>
              <th className="num">Uso total</th>
              <th className="num">Ventas (caja1)</th>
              <th className="num">Ventas (caja2)</th>
              <th className="num">Mov origen</th>
              <th className="num">Mov destino</th>
              <th style={{ width: 130 }}>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {filtradas.map((c) => (
              <tr key={c.nombre_normalizado}>
                <td>{c.nombre_display}</td>
                <td><span className={`badge ${c.tipo === "fc_empleado" ? "warn" : "muted"}`}>{c.tipo}</span></td>
                <td className="num">{fmtNum(c.uso_total)}</td>
                <td className="num">{fmtNum(c.ventas_como_caja1)}</td>
                <td className="num">{fmtNum(c.ventas_como_caja2)}</td>
                <td className="num">{fmtNum(c.movimientos_origen)}</td>
                <td className="num">{fmtNum(c.movimientos_destino)}</td>
                <td>
                  {c.archivado_at ? (
                    <button className="btn-ghost btn" onClick={() => desarchivar(c)} title="Volver a mostrar en el listado">Desarchivar</button>
                  ) : (
                    <button className="btn-ghost btn" onClick={() => archivar(c)} title="Sacar del listado (reversible)">Archivar</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
