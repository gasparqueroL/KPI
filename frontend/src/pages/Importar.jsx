import { useRef, useState } from "react";
import api, { fmtNum } from "../api/client";
import { useToast } from "../components/Toast";

export default function Importar() {
  const toast = useToast();
  const [archivos, setArchivos] = useState([]);
  const [resultados, setResultados] = useState([]);
  const [loading, setLoading] = useState(false);
  const [actual, setActual] = useState(null);  // archivo en curso
  const [dragOver, setDragOver] = useState(false);
  const cancelRef = useRef(false);
  const inputRef = useRef();

  function onFiles(files) {
    setArchivos(Array.from(files));
  }

  // Ref para abortar el upload en vuelo si la dueña cancela. Sin esto,
  // un upload de 50MB sigue ocupando server tras click en cancelar.
  const uploadAbortRef = useRef(null);
  // Lock síncrono contra doble click rápido en "Importar" antes de que
  // `setLoading(true)` flushee. Sin esto, dos flujos paralelos pisan
  // `uploadAbortRef`, `setActual` y `setResultados`.
  const runningRef = useRef(false);

  function cancelar() {
    cancelRef.current = true;
    uploadAbortRef.current?.abort();
    toast.push("Cancelando — abortando archivo en curso + omitiendo siguientes", "info");
  }

  async function importarTodos() {
    if (runningRef.current) return;  // doble click rápido — no entrar 2 veces
    runningRef.current = true;
    setLoading(true);
    setResultados([]);
    cancelRef.current = false;
    const res = [];
    let abortados = 0;
    let saltados = 0;
    try {
      for (const f of archivos) {
        if (cancelRef.current) {
          saltados++;
          continue;
        }
        setActual(f.name);
        const ctrl = new AbortController();
        uploadAbortRef.current = ctrl;
        try {
          const fd = new FormData();
          fd.append("file", f);
          const { data } = await api.post("/api/import", fd, { signal: ctrl.signal });
          res.push({ ok: true, archivo: f.name, ...data });
        } catch (e) {
          if (e.name === "CanceledError" || e.code === "ERR_CANCELED") {
            res.push({ ok: false, archivo: f.name, error: "cancelado por el usuario" });
            abortados++;
          } else {
            const msg = e.response?.data?.detail || e.message;
            res.push({ ok: false, archivo: f.name, error: msg });
            toast.push(`${f.name}: ${msg}`, "error");
          }
        }
        setResultados([...res]);
      }
    } finally {
      // Reset garantizado: si cualquier paso explota inesperadamente,
      // el lock no queda colgado bloqueando el siguiente click.
      setActual(null);
      setArchivos([]);
      setLoading(false);
      cancelRef.current = false;
      uploadAbortRef.current = null;
      runningRef.current = false;
    }
    if (abortados > 0 || saltados > 0) {
      const partes = [];
      if (abortados > 0) partes.push(`${abortados} abortado${abortados === 1 ? "" : "s"}`);
      if (saltados > 0) partes.push(`${saltados} omitido${saltados === 1 ? "" : "s"}`);
      toast.push(partes.join(" · "), "info");
    } else if (res.every((r) => r.ok)) {
      toast.push(`${res.length} archivos importados`, "success");
    }
  }

  return (
    <>
      <h2>Importar CSV</h2>
      <p style={{ color: "#94a3b8", marginTop: -10 }}>
        Subí los CSV de <b>ventas</b>, <b>detalle de ventas</b> o <b>movimientos de caja</b>.
        El sistema detecta el tipo automáticamente.
      </p>

      <div
        className={`dropzone ${dragOver ? "drag-over" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          onFiles(e.dataTransfer.files);
        }}
      >
        <div style={{ fontSize: 18, marginBottom: 8 }}>
          Arrastrá tus CSV acá o hacé click para elegirlos
        </div>
        <div style={{ color: "#64748b", fontSize: 13 }}>
          Acepta varios archivos CSV o XLSX a la vez (ventas, detalle_ventas, movimientos_caja).
          El sistema detecta el formato automáticamente por contenido.
        </div>
        <input
          type="file"
          ref={inputRef}
          multiple
          accept=".csv,.xlsx"
          onChange={(e) => onFiles(e.target.files)}
        />
      </div>

      {archivos.length > 0 && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h3>Archivos a importar ({archivos.length})</h3>
          <ul>{archivos.map((f) => <li key={f.name}>{f.name} — {(f.size / 1024).toFixed(0)} KB</li>)}</ul>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <button className="btn" disabled={loading} onClick={importarTodos}>
              {loading ? <><span className="spinner" /> Importando{actual ? ` ${actual}...` : "..."}</> : "Importar"}
            </button>
            {loading && (
              <button className="btn-ghost btn" onClick={cancelar}>
                Cancelar siguientes
              </button>
            )}
          </div>
        </div>
      )}

      {resultados.map((r, i) => (
        <div key={i} className="panel">
          <h3>
            {r.archivo} {r.ok
              ? <span className={`badge ok`} style={{ marginLeft: 8 }}>{r.tipo_detectado}</span>
              : <span className="badge err" style={{ marginLeft: 8 }}>error</span>}
          </h3>
          {!r.ok && <div style={{ color: "#fca5a5" }}>{r.error}</div>}
          {r.ok && (
            <>
              <div className="kpi-grid">
                <div className="kpi-card green"><div className="label">Aceptados</div><div className="value">{fmtNum(r.aceptados)}</div></div>
                <div className="kpi-card muted"><div className="label">Ya existían</div><div className="value">{fmtNum(r.ya_existian)}</div></div>
                <div className="kpi-card amber"><div className="label">Rechazados</div><div className="value">{fmtNum(r.rechazados_count)}</div></div>
                <div className="kpi-card"><div className="label">Cajas creadas</div><div className="value">{fmtNum(r.cajas_creadas?.length || 0)}</div></div>
                <div className="kpi-card"><div className="label">Categorías nuevas</div><div className="value">{fmtNum(r.categorias_creadas?.length || 0)}</div></div>
              </div>
              {r.rechazados_count > 0 && (
                <div style={{ color: "#94a3b8", fontSize: 13 }}>
                  Los rechazos quedaron registrados en <b>Casos a revisar</b>.
                </div>
              )}
            </>
          )}
        </div>
      ))}
    </>
  );
}
