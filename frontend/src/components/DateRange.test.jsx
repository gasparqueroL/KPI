import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import DateRange from "./DateRange";

describe("DateRange — render", () => {
  it("renderiza dos inputs date asociados con sus labels (a11y)", () => {
    render(<DateRange desde="" hasta="" setDesde={vi.fn()} setHasta={vi.fn()} />);
    // getByLabelText valida la asociación label-input via htmlFor/id.
    // Más robusto que `inputs[0]/[1]` por orden DOM.
    expect(screen.getByLabelText("Desde")).not.toBeNull();
    expect(screen.getByLabelText("Hasta")).not.toBeNull();
    // Los inputs son tipo date.
    expect(screen.getByLabelText("Desde").getAttribute("type")).toBe("date");
    expect(screen.getByLabelText("Hasta").getAttribute("type")).toBe("date");
  });

  it("inputs muestran los valores prop", () => {
    render(
      <DateRange
        desde="2026-04-01"
        hasta="2026-04-30"
        setDesde={vi.fn()}
        setHasta={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Desde").value).toBe("2026-04-01");
    expect(screen.getByLabelText("Hasta").value).toBe("2026-04-30");
  });

  it("desde/hasta vacíos NO disparan warning controlled→uncontrolled", () => {
    // React tira warning si `value` cambia entre defined y undefined.
    // El componente pasa siempre el prop directo — con `desde=""` debe
    // dar input controlado con value vacío.
    const { container } = render(
      <DateRange desde="" hasta="" setDesde={vi.fn()} setHasta={vi.fn()} />,
    );
    expect(screen.getByLabelText("Desde").value).toBe("");
    expect(screen.getByLabelText("Hasta").value).toBe("");
  });

  it("renderiza botón 'Todo'", () => {
    render(<DateRange desde="" hasta="" setDesde={vi.fn()} setHasta={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /^Todo$/i })).not.toBeNull();
  });

  it("renderiza children en el slot final", () => {
    render(
      <DateRange desde="" hasta="" setDesde={vi.fn()} setHasta={vi.fn()}>
        <button>Aplicar</button>
      </DateRange>,
    );
    expect(screen.queryByRole("button", { name: /^Aplicar$/i })).not.toBeNull();
  });
});

describe("DateRange — interacciones", () => {
  it("cambiar input 'Desde' llama setDesde con el nuevo valor", () => {
    const setDesde = vi.fn();
    render(<DateRange desde="" hasta="" setDesde={setDesde} setHasta={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Desde"), { target: { value: "2026-05-15" } });
    expect(setDesde).toHaveBeenCalledWith("2026-05-15");
  });

  it("cambiar input 'Hasta' llama setHasta con el nuevo valor", () => {
    const setHasta = vi.fn();
    render(<DateRange desde="" hasta="" setDesde={vi.fn()} setHasta={setHasta} />);
    fireEvent.change(screen.getByLabelText("Hasta"), { target: { value: "2026-05-20" } });
    expect(setHasta).toHaveBeenCalledWith("2026-05-20");
  });

  it("click en 'Todo' limpia AMBOS inputs", () => {
    const setDesde = vi.fn();
    const setHasta = vi.fn();
    render(
      <DateRange
        desde="2026-04-01"
        hasta="2026-04-30"
        setDesde={setDesde}
        setHasta={setHasta}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Todo$/i }));
    expect(setDesde).toHaveBeenCalledWith("");
    expect(setHasta).toHaveBeenCalledWith("");
  });
});
