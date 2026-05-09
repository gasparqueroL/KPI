import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import PeriodPresets, { PRESETS, periodoAnterior } from "./PeriodPresets";

describe("periodoAnterior — cálculo de período anterior de igual largo", () => {
  it("mes completo: abril 1-30 → marzo 1-31", () => {
    expect(periodoAnterior("2026-04-01", "2026-04-30")).toEqual({
      desde: "2026-03-02",
      hasta: "2026-03-31",
    });
    // 30 días: período previo de 30 días, terminando el día anterior al desde.
  });

  it("rango de 1 día: 2026-04-15 → día anterior", () => {
    expect(periodoAnterior("2026-04-15", "2026-04-15")).toEqual({
      desde: "2026-04-14",
      hasta: "2026-04-14",
    });
  });

  it("rango cruzando año: enero 1-15 2026 → dic 17-31 2025", () => {
    // 15 días → previos 15 días terminando el 31 dic.
    expect(periodoAnterior("2026-01-01", "2026-01-15")).toEqual({
      desde: "2025-12-17",
      hasta: "2025-12-31",
    });
  });

  it("rango de 7 días: período previo de 7 días", () => {
    expect(periodoAnterior("2026-04-08", "2026-04-14")).toEqual({
      desde: "2026-04-01",
      hasta: "2026-04-07",
    });
  });

  it("desde vacío → fallback {desde:'', hasta:''}", () => {
    expect(periodoAnterior("", "2026-04-30")).toEqual({ desde: "", hasta: "" });
  });

  it("hasta vacío → fallback", () => {
    expect(periodoAnterior("2026-04-01", "")).toEqual({ desde: "", hasta: "" });
  });

  it("ambos vacíos → fallback", () => {
    expect(periodoAnterior("", "")).toEqual({ desde: "", hasta: "" });
  });

  it("formato no canónico (ISO con time) → fallback en vez de Invalid Date", () => {
    // Defensivo: parseIsoLocal solo acepta YYYY-MM-DD. Sin esto, un input
    // con time component produciría NaN → Invalid Date en params del request.
    expect(periodoAnterior("2026-04-08T10:00", "2026-04-15")).toEqual({
      desde: "",
      hasta: "",
    });
    expect(periodoAnterior("2026/04/08", "2026/04/15")).toEqual({
      desde: "",
      hasta: "",
    });
    expect(periodoAnterior("hola", "mundo")).toEqual({
      desde: "",
      hasta: "",
    });
  });
});

describe("PRESETS — calculadores con fecha controlada", () => {
  // Fijo "hoy" en 2026-05-15 para todos los tests del bloque. setSystemTime
  // mockea `new Date()` que es lo que usan los presets.
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-15T10:00:00"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  function preset(label) {
    return PRESETS.find((p) => p.label === label).calc();
  }

  it("'Este mes': desde 1ro del mes actual hasta hoy", () => {
    expect(preset("Este mes")).toEqual({
      desde: "2026-05-01",
      hasta: "2026-05-15",
    });
  });

  it("'Mes pasado': desde 1 abril hasta 30 abril (inclusive último día)", () => {
    expect(preset("Mes pasado")).toEqual({
      desde: "2026-04-01",
      hasta: "2026-04-30",
    });
  });

  it("'Mes pasado' edge: último día calcula con day=0 del mes actual", () => {
    // Si hoy es 1 marzo, "Mes pasado" debe ser feb 1 - feb 28/29.
    vi.setSystemTime(new Date("2026-03-01T10:00:00"));
    expect(preset("Mes pasado")).toEqual({
      desde: "2026-02-01",
      hasta: "2026-02-28", // 2026 no es bisiesto
    });
  });

  it("'Mes pasado' bisiesto: feb 2024 termina en 29", () => {
    vi.setSystemTime(new Date("2024-03-15T10:00:00"));
    expect(preset("Mes pasado")).toEqual({
      desde: "2024-02-01",
      hasta: "2024-02-29",
    });
  });

  it("'Últimos 3 meses': desde 3 meses atrás hasta hoy", () => {
    // Hoy = 15 mayo. Hace 3 meses = 15 febrero.
    expect(preset("Últimos 3 meses")).toEqual({
      desde: "2026-02-15",
      hasta: "2026-05-15",
    });
  });

  it("'YTD': desde 1 enero del año actual", () => {
    expect(preset("YTD")).toEqual({
      desde: "2026-01-01",
      hasta: "2026-05-15",
    });
  });

  it("'Año pasado': todo el año anterior completo", () => {
    expect(preset("Año pasado")).toEqual({
      desde: "2025-01-01",
      hasta: "2025-12-31",
    });
  });

  it("'Últimos 12m': hace 1 año desde hoy", () => {
    expect(preset("Últimos 12m")).toEqual({
      desde: "2025-05-15",
      hasta: "2026-05-15",
    });
  });
});

describe("PeriodPresets — componente", () => {
  it("renderiza 6 botones (uno por preset)", () => {
    render(<PeriodPresets setDesde={vi.fn()} setHasta={vi.fn()} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(6);
    expect(buttons.map((b) => b.textContent)).toEqual([
      "Este mes",
      "Mes pasado",
      "Últimos 3 meses",
      "YTD",
      "Año pasado",
      "Últimos 12m",
    ]);
  });

  it("click en preset llama setDesde y setHasta con los valores calculados", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-15T10:00:00"));

    const setDesde = vi.fn();
    const setHasta = vi.fn();
    render(<PeriodPresets setDesde={setDesde} setHasta={setHasta} />);

    fireEvent.click(screen.getByRole("button", { name: "Este mes" }));
    expect(setDesde).toHaveBeenCalledWith("2026-05-01");
    expect(setHasta).toHaveBeenCalledWith("2026-05-15");

    vi.useRealTimers();
  });

  it("onApply se llama SÍNCRONAMENTE con (desde, hasta) nuevos como args", () => {
    // Antes el componente hacía `setTimeout(onApply, 0)` con la idea de
    // esperar al state flush. PERO el `onApply` capturado tiene closure
    // viejo (state previos) — bug real: la dueña hace click en "Mes pasado"
    // y los KPIs no actualizan. Fix: pasar los valores DIRECTO a onApply.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-15T10:00:00"));

    const onApply = vi.fn();
    render(
      <PeriodPresets
        setDesde={vi.fn()}
        setHasta={vi.fn()}
        onApply={onApply}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Este mes" }));
    // Llamada SÍNCRONA con los valores del preset.
    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply).toHaveBeenCalledWith("2026-05-01", "2026-05-15");

    vi.useRealTimers();
  });

  it("sin onApply: click no rompe (callback opcional)", () => {
    const setDesde = vi.fn();
    const setHasta = vi.fn();
    render(<PeriodPresets setDesde={setDesde} setHasta={setHasta} />);
    expect(() => {
      fireEvent.click(screen.getByRole("button", { name: "YTD" }));
    }).not.toThrow();
    expect(setDesde).toHaveBeenCalled();
  });
});
