import { useMemo, useState } from "react";
import { descargarComoCSV } from "../api/csvExport";
import Icon from "./Icon";

/**
 * Tabla con sort por columna haciendo click en el header.
 *
 * Props:
 * - columns: [{ key, label, render?(row), num?, defaultSort? "asc"|"desc",
 *              csvFormat?(row) → valor crudo para CSV (sin formato visual) }]
 * - rows: array de objetos
 * - rowKey: (row) => string|number
 * - initialSort: { key, dir }
 * - exportCSV: { filename } — si está, muestra botón "Descargar CSV"
 *
 * `csvFormat` permite separar el render visual (que puede tener JSX, links,
 * iconos) del valor que se exporta. Si no se pasa, se usa `row[key]` crudo.
 */
export default function SortableTable({ columns, rows, rowKey, initialSort, className, exportCSV }) {
  const [sort, setSort] = useState(initialSort || null);

  const sortedRows = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col) return rows;
    // Comparator: nulls SIEMPRE al final independiente de la dir
    // (semántica: "valor desconocido" → no debería competir con valores
    // reales por el top de la lista). Los valores definidos se comparan
    // según tipo y se invierte el resultado para desc — sin .reverse()
    // ciego del array, que mandaba los nulls al principio en desc.
    const sorted = [...rows].sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;   // null va después
      if (bv == null) return -1;
      const cmp =
        typeof av === "number" && typeof bv === "number"
          ? av - bv
          : String(av).localeCompare(String(bv), "es", { numeric: true });
      return sort.dir === "desc" ? -cmp : cmp;
    });
    return sorted;
  }, [rows, sort, columns]);

  function clickHeader(key) {
    if (sort?.key === key) {
      setSort({ key, dir: sort.dir === "asc" ? "desc" : "asc" });
    } else {
      const col = columns.find((c) => c.key === key);
      setSort({ key, dir: col?.num ? "desc" : "asc" });
    }
  }

  function exportar() {
    // Para CSV usamos el orden actual de la tabla (sortedRows), no el
    // original — la dueña ve un orden, exporta con ese orden.
    const cols = columns.map((c) => ({
      key: c.key,
      label: c.label,
      // csvFormat tiene prioridad. Sino fallback al valor crudo (sin render JSX).
      format: c.csvFormat,
    }));
    descargarComoCSV(exportCSV.filename, cols, sortedRows);
  }

  return (
    <>
      {exportCSV && rows.length > 0 && (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}>
          <button
            className="btn-ghost btn"
            onClick={exportar}
            title="Descargar la tabla en CSV (Excel-compatible) con el orden actual"
            style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12 }}
          >
            <Icon name="download" size={12} /> CSV
          </button>
        </div>
      )}
      <table className={className}>
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key;
              const iconName = active
                ? (sort.dir === "asc" ? "arrow-up" : "arrow-down")
                : "sort";
              return (
                <th
                  key={c.key}
                  className={c.num ? "num" : ""}
                  style={{ cursor: "pointer", userSelect: "none" }}
                  onClick={() => clickHeader(c.key)}
                >
                  {c.label}
                  <span style={{ opacity: active ? 1 : 0.4, marginLeft: 4 }}>
                    <Icon name={iconName} size={12} />
                  </span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((r) => (
            <tr key={rowKey(r)}>
              {columns.map((c) => (
                <td key={c.key} className={c.num ? "num" : ""}>
                  {c.render ? c.render(r) : r[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
