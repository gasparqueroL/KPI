export default function DateRange({ desde, hasta, setDesde, setHasta, children }) {
  // `htmlFor` + `id` asocia label con input — clave para a11y (screen
  // readers anuncian "Desde" al focar el input) y para testing-library
  // que usa getByLabelText() para selectores estables (no por orden DOM).
  return (
    <div className="toolbar">
      <label htmlFor="date-range-desde">Desde</label>
      <input
        id="date-range-desde"
        type="date"
        value={desde}
        onChange={(e) => setDesde(e.target.value)}
      />
      <label htmlFor="date-range-hasta">Hasta</label>
      <input
        id="date-range-hasta"
        type="date"
        value={hasta}
        onChange={(e) => setHasta(e.target.value)}
      />
      <button className="btn-ghost btn" onClick={() => { setDesde(""); setHasta(""); }}>
        Todo
      </button>
      {children}
    </div>
  );
}
