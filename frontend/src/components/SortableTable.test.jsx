import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import SortableTable from "./SortableTable";

// Mock del helper de CSV: solo nos interesa observar que se llama con los
// argumentos correctos cuando la dueña aprieta el botón. La lógica del CSV
// ya está testeada en csvExport.test.js.
vi.mock("../api/csvExport", () => ({
  descargarComoCSV: vi.fn(),
}));
import { descargarComoCSV } from "../api/csvExport";

const FILAS = [
  { id: 1, producto: "Detergente", monto: 100, vendedor: "Ana" },
  { id: 2, producto: "Bolsa basura", monto: 50, vendedor: "Beto" },
  { id: 3, producto: "Lavandina", monto: 200, vendedor: "Ana" },
];

const COLS_BASIC = [
  { key: "producto", label: "Producto" },
  { key: "monto", label: "Monto", num: true },
  { key: "vendedor", label: "Vendedor" },
];

describe("SortableTable — render básico", () => {
  it("renderiza headers y filas", () => {
    render(
      <SortableTable
        columns={COLS_BASIC}
        rows={FILAS}
        rowKey={(r) => r.id}
      />,
    );
    expect(screen.queryByText("Producto")).not.toBeNull();
    expect(screen.queryByText("Monto")).not.toBeNull();
    expect(screen.queryByText("Detergente")).not.toBeNull();
    expect(screen.queryByText("Bolsa basura")).not.toBeNull();
    expect(screen.queryByText("Lavandina")).not.toBeNull();
  });

  it("usa render(row) cuando está definido (toma prioridad sobre row[key])", () => {
    render(
      <SortableTable
        columns={[
          { key: "producto", label: "Producto", render: (r) => `[${r.producto.toUpperCase()}]` },
        ]}
        rows={FILAS}
        rowKey={(r) => r.id}
      />,
    );
    expect(screen.queryByText("[DETERGENTE]")).not.toBeNull();
    // El valor crudo NO está visible (lo reemplazó render).
    expect(screen.queryByText("Detergente")).toBeNull();
  });
});

describe("SortableTable — sort dir defaults por click en header", () => {
  it("primer click en columna string ordena ASC", () => {
    render(<SortableTable columns={COLS_BASIC} rows={FILAS} rowKey={(r) => r.id} />);
    fireEvent.click(screen.getByText("Producto"));
    const filas = screen.getAllByRole("row").slice(1); // saltar header
    // ASC alfabético: Bolsa, Detergente, Lavandina
    expect(within(filas[0]).queryByText("Bolsa basura")).not.toBeNull();
    expect(within(filas[2]).queryByText("Lavandina")).not.toBeNull();
  });

  it("primer click en columna num=true ordena DESC (default razonable: ver montos altos primero)", () => {
    render(<SortableTable columns={COLS_BASIC} rows={FILAS} rowKey={(r) => r.id} />);
    fireEvent.click(screen.getByText("Monto"));
    const filas = screen.getAllByRole("row").slice(1);
    // DESC: 200, 100, 50
    expect(within(filas[0]).queryByText("200")).not.toBeNull();
    expect(within(filas[2]).queryByText("50")).not.toBeNull();
  });

  it("segundo click en misma columna toggle de dirección", () => {
    render(<SortableTable columns={COLS_BASIC} rows={FILAS} rowKey={(r) => r.id} />);
    const headerMonto = screen.getByText("Monto");
    fireEvent.click(headerMonto); // DESC
    fireEvent.click(headerMonto); // ASC
    const filas = screen.getAllByRole("row").slice(1);
    expect(within(filas[0]).queryByText("50")).not.toBeNull();
    expect(within(filas[2]).queryByText("200")).not.toBeNull();
  });

  it("click en columna distinta resetea dir según defaultSort de la columna", () => {
    render(<SortableTable columns={COLS_BASIC} rows={FILAS} rowKey={(r) => r.id} />);
    fireEvent.click(screen.getByText("Producto")); // string ASC
    fireEvent.click(screen.getByText("Monto")); // num default DESC
    const filas = screen.getAllByRole("row").slice(1);
    expect(within(filas[0]).queryByText("200")).not.toBeNull();
  });
});

describe("SortableTable — initialSort", () => {
  it("respeta initialSort en el primer render", () => {
    render(
      <SortableTable
        columns={COLS_BASIC}
        rows={FILAS}
        rowKey={(r) => r.id}
        initialSort={{ key: "monto", dir: "asc" }}
      />,
    );
    const filas = screen.getAllByRole("row").slice(1);
    // Monto ASC: 50, 100, 200
    expect(within(filas[0]).queryByText("50")).not.toBeNull();
    expect(within(filas[2]).queryByText("200")).not.toBeNull();
  });
});

describe("SortableTable — comparación numérica vs string", () => {
  it("número compara con resta directa (no string-compare → '10' antes de '9')", () => {
    const rows = [
      { id: 1, n: 10 },
      { id: 2, n: 9 },
      { id: 3, n: 100 },
    ];
    render(
      <SortableTable
        columns={[{ key: "n", label: "N", num: true }]}
        rows={rows}
        rowKey={(r) => r.id}
        initialSort={{ key: "n", dir: "asc" }}
      />,
    );
    const filas = screen.getAllByRole("row").slice(1);
    // Numérico: 9, 10, 100. Si fuese string-compare daría 10, 100, 9.
    expect(filas[0].textContent).toContain("9");
    expect(filas[1].textContent).toContain("10");
    expect(filas[2].textContent).toContain("100");
  });

  it("string usa localeCompare es con numeric: true (acentos + dígitos en strings)", () => {
    const rows = [
      { id: 1, s: "ítem 10" },
      { id: 2, s: "ítem 2" },
      { id: 3, s: "ítem 1" },
    ];
    render(
      <SortableTable
        columns={[{ key: "s", label: "S" }]}
        rows={rows}
        rowKey={(r) => r.id}
        initialSort={{ key: "s", dir: "asc" }}
      />,
    );
    const filas = screen.getAllByRole("row").slice(1);
    // localeCompare con numeric: ítem 1, ítem 2, ítem 10 (no string-compare).
    expect(filas[0].textContent).toContain("ítem 1");
    expect(filas[1].textContent).toContain("ítem 2");
    expect(filas[2].textContent).toContain("ítem 10");
  });
});

describe("SortableTable — null handling", () => {
  it("nulls van AL FINAL en sort asc (semántica: 'desconocido = mayor')", () => {
    const rows = [
      { id: 1, m: null },
      { id: 2, m: 50 },
      { id: 3, m: 100 },
    ];
    render(
      <SortableTable
        columns={[{ key: "m", label: "M", num: true }]}
        rows={rows}
        rowKey={(r) => r.id}
        initialSort={{ key: "m", dir: "asc" }}
      />,
    );
    const filas = screen.getAllByRole("row").slice(1);
    expect(filas[0].textContent).toContain("50");
    expect(filas[2].textContent.trim()).toBe(""); // null renderea vacío
  });

  it("nulls van AL FINAL también en sort desc (null-always-last)", () => {
    // Comportamiento corregido (review ronda 4): el `.reverse()` ciego del
    // array entero hacía que en DESC los nulls quedaran AL PRINCIPIO. Era
    // bug latente: usuario que ordena DESC para ver los más grandes NO
    // quiere nulls al tope. Ahora null-always-last regardless of dir.
    const rows = [
      { id: 1, m: null },
      { id: 2, m: 50 },
      { id: 3, m: 100 },
    ];
    render(
      <SortableTable
        columns={[{ key: "m", label: "M", num: true }]}
        rows={rows}
        rowKey={(r) => r.id}
        initialSort={{ key: "m", dir: "desc" }}
      />,
    );
    const filas = screen.getAllByRole("row").slice(1);
    // DESC: 100, 50, null (null sigue al final)
    expect(filas[0].textContent).toContain("100");
    expect(filas[1].textContent).toContain("50");
    expect(filas[2].textContent.trim()).toBe("");
  });

  it("ambos nulls retornan 0 en comparator (orden estable preservado)", () => {
    const rows = [
      { id: 1, m: null },
      { id: 2, m: null },
      { id: 3, m: 50 },
    ];
    render(
      <SortableTable
        columns={[{ key: "m", label: "M", num: true }]}
        rows={rows}
        rowKey={(r) => r.id}
        initialSort={{ key: "m", dir: "asc" }}
      />,
    );
    const filas = screen.getAllByRole("row").slice(1);
    // 50 primero (no null), luego los dos nulls. Sin crashear.
    expect(filas[0].textContent).toContain("50");
  });
});

describe("SortableTable — exportCSV", () => {
  beforeEach(() => {
    vi.mocked(descargarComoCSV).mockClear();
  });

  it("NO muestra botón si exportCSV es undefined", () => {
    render(<SortableTable columns={COLS_BASIC} rows={FILAS} rowKey={(r) => r.id} />);
    expect(screen.queryByRole("button", { name: /CSV/i })).toBeNull();
  });

  it("NO muestra botón si rows.length === 0 (aunque exportCSV esté)", () => {
    render(
      <SortableTable
        columns={COLS_BASIC}
        rows={[]}
        rowKey={(r) => r.id}
        exportCSV={{ filename: "test.csv" }}
      />,
    );
    expect(screen.queryByRole("button", { name: /CSV/i })).toBeNull();
  });

  it("muestra botón cuando hay rows + exportCSV", () => {
    render(
      <SortableTable
        columns={COLS_BASIC}
        rows={FILAS}
        rowKey={(r) => r.id}
        exportCSV={{ filename: "test.csv" }}
      />,
    );
    expect(screen.queryByRole("button", { name: /CSV/i })).not.toBeNull();
  });

  it("click en CSV llama a descargarComoCSV con filename + cols mapeadas + sortedRows", () => {
    render(
      <SortableTable
        columns={COLS_BASIC}
        rows={FILAS}
        rowKey={(r) => r.id}
        exportCSV={{ filename: "comercial.csv" }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /CSV/i }));
    expect(descargarComoCSV).toHaveBeenCalledTimes(1);
    const [filename, cols, rowsExportados] = descargarComoCSV.mock.calls[0];
    expect(filename).toBe("comercial.csv");
    // Cols se mapean a {key, label, format}
    expect(cols.map((c) => c.key)).toEqual(["producto", "monto", "vendedor"]);
    // Sin csvFormat → format es undefined
    expect(cols[0].format).toBeUndefined();
    // Sin sort, mantiene orden original.
    expect(rowsExportados.map((r) => r.id)).toEqual([1, 2, 3]);
  });

  it("CSV usa el orden ACTUAL (post-sort), no el original", () => {
    render(
      <SortableTable
        columns={COLS_BASIC}
        rows={FILAS}
        rowKey={(r) => r.id}
        exportCSV={{ filename: "test.csv" }}
        initialSort={{ key: "monto", dir: "asc" }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /CSV/i }));
    const [, , rowsExportados] = descargarComoCSV.mock.calls[0];
    // Orden ASC por monto: 50, 100, 200 → ids 2, 1, 3
    expect(rowsExportados.map((r) => r.id)).toEqual([2, 1, 3]);
  });

  it("csvFormat se pasa como `format` a descargarComoCSV (prioridad sobre row[key])", () => {
    render(
      <SortableTable
        columns={[
          {
            key: "producto",
            label: "Producto",
            render: (r) => `[${r.producto}]`,
            csvFormat: (r) => `csv:${r.producto}`,
          },
        ]}
        rows={FILAS}
        rowKey={(r) => r.id}
        exportCSV={{ filename: "test.csv" }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /CSV/i }));
    const [, cols] = descargarComoCSV.mock.calls[0];
    expect(cols[0].format).toBeTypeOf("function");
    expect(cols[0].format(FILAS[0])).toBe("csv:Detergente");
  });
});
