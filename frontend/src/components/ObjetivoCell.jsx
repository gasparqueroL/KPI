import { useEffect, useRef, useState } from "react";

/** Celda editable inline para fijar el objetivo de un KPI.
 * - Sin objetivo cargado: muestra link "fijar"
 * - Con objetivo: muestra valor + ✓/✗ según cumple, click para editar
 * - Borrar: dejar vacío y guardar
 *
 * Race con re-fetch del padre: useEffect sincroniza `valor` cuando
 * la prop `kpi.objetivo` cambia y NO se está editando. Si el usuario
 * está tipeando, NO pisa.
 *
 * Doble guardado: Enter dispara `guardar` que pone editando=false; el
 * blur subsiguiente dispararía otro guardar. `guardandoRef` es un lock
 * por instancia que se libera en el próximo tick. */
export default function ObjetivoCell({ kpi, onChange }) {
  const [editando, setEditando] = useState(false);
  const [valor, setValor] = useState(kpi.objetivo ?? "");
  const guardandoRef = useRef(false);

  useEffect(() => {
    if (!editando) setValor(kpi.objetivo ?? "");
  }, [kpi.objetivo, editando]);

  function guardar() {
    if (guardandoRef.current) return;
    guardandoRef.current = true;
    const v = valor === "" ? null : Number(valor);
    if (v !== null && !Number.isFinite(v)) {
      guardandoRef.current = false;
      return;
    }
    onChange(v);
    setEditando(false);
    setTimeout(() => { guardandoRef.current = false; }, 0);
  }

  function cancelar() {
    guardandoRef.current = true;
    setValor(kpi.objetivo ?? "");
    setEditando(false);
    setTimeout(() => { guardandoRef.current = false; }, 0);
  }

  if (editando) {
    return (
      <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
        <input
          type="number"
          step="any"
          value={valor}
          onChange={(e) => setValor(e.target.value)}
          onBlur={guardar}
          onKeyDown={(e) => {
            if (e.key === "Enter") guardar();
            if (e.key === "Escape") cancelar();
          }}
          autoFocus
          placeholder="—"
          style={{ width: 80, textAlign: "right", fontSize: 12 }}
          aria-label={`Objetivo de ${kpi.label}`}
        />
      </div>
    );
  }

  if (kpi.objetivo == null) {
    return (
      <button
        className="btn-ghost btn"
        onClick={() => { setValor(""); setEditando(true); }}
        style={{ fontSize: 11, padding: "2px 8px", color: "#94a3b8" }}
      >
        fijar
      </button>
    );
  }

  const cumple = kpi.cumple_objetivo;
  const colorBadge = cumple === true ? "#34d399" : cumple === false ? "#f87171" : "#94a3b8";
  const icono = cumple === true ? "✓" : cumple === false ? "✗" : "·";
  return (
    <button
      className="btn-ghost btn"
      onClick={() => { setValor(kpi.objetivo); setEditando(true); }}
      style={{
        fontSize: 12, padding: "2px 8px",
        textAlign: "right", fontFamily: "inherit",
      }}
      title={`Click para editar — objetivo: ${kpi.mejor_si === "bajar" ? "≤" : "≥"} ${kpi.objetivo}`}
    >
      <span style={{ color: colorBadge, fontWeight: 700, marginRight: 4 }}>{icono}</span>
      {kpi.objetivo}
    </button>
  );
}
