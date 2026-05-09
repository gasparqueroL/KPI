import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ObjetivoCell from "./ObjetivoCell";

const kpiBase = {
  codigo: "nps",
  label: "NPS (clientes)",
  unidad: "score",
  mejor_si: "subir",
  valor: 60,
  objetivo: 50,
  cumple_objetivo: true,
};

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("ObjetivoCell", () => {
  it("muestra ✓ verde si cumple", () => {
    render(<ObjetivoCell kpi={kpiBase} onChange={vi.fn()} />);
    expect(screen.getByText("✓")).toBeTruthy();
    expect(screen.getByText("50")).toBeTruthy();
  });

  it("muestra ✗ si no cumple", () => {
    render(<ObjetivoCell kpi={{ ...kpiBase, cumple_objetivo: false }} onChange={vi.fn()} />);
    expect(screen.getByText("✗")).toBeTruthy();
  });

  it("muestra 'fijar' cuando no hay objetivo", () => {
    render(<ObjetivoCell kpi={{ ...kpiBase, objetivo: null }} onChange={vi.fn()} />);
    expect(screen.getByText("fijar")).toBeTruthy();
  });

  it("click abre el input editable", () => {
    render(<ObjetivoCell kpi={kpiBase} onChange={vi.fn()} />);
    fireEvent.click(screen.getByText("50"));
    expect(screen.getByRole("spinbutton")).toBeTruthy();
  });

  it("Enter guarda y llama onChange con el nuevo valor", () => {
    const onChange = vi.fn();
    render(<ObjetivoCell kpi={kpiBase} onChange={onChange} />);
    fireEvent.click(screen.getByText("50"));
    const input = screen.getByRole("spinbutton");
    fireEvent.change(input, { target: { value: "75" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith(75);
  });

  it("Escape cancela sin llamar onChange", () => {
    const onChange = vi.fn();
    render(<ObjetivoCell kpi={kpiBase} onChange={onChange} />);
    fireEvent.click(screen.getByText("50"));
    const input = screen.getByRole("spinbutton");
    fireEvent.change(input, { target: { value: "75" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("input vacío + Enter llama onChange con null (borrar)", () => {
    const onChange = vi.fn();
    render(<ObjetivoCell kpi={kpiBase} onChange={onChange} />);
    fireEvent.click(screen.getByText("50"));
    const input = screen.getByRole("spinbutton");
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("Enter + blur posterior NO dispara doble onChange", () => {
    const onChange = vi.fn();
    render(<ObjetivoCell kpi={kpiBase} onChange={onChange} />);
    fireEvent.click(screen.getByText("50"));
    const input = screen.getByRole("spinbutton");
    fireEvent.change(input, { target: { value: "75" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("Escape + blur posterior NO dispara onChange", () => {
    const onChange = vi.fn();
    render(<ObjetivoCell kpi={kpiBase} onChange={onChange} />);
    fireEvent.click(screen.getByText("50"));
    const input = screen.getByRole("spinbutton");
    fireEvent.change(input, { target: { value: "999" } });
    fireEvent.keyDown(input, { key: "Escape" });
    fireEvent.blur(input);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("re-fetch del padre cambia kpi.objetivo y la celda se actualiza si NO está editando", () => {
    const { rerender } = render(<ObjetivoCell kpi={kpiBase} onChange={vi.fn()} />);
    expect(screen.getByText("50")).toBeTruthy();
    rerender(<ObjetivoCell kpi={{ ...kpiBase, objetivo: 80 }} onChange={vi.fn()} />);
    expect(screen.getByText("80")).toBeTruthy();
  });

  it("operador en title cambia según mejor_si", () => {
    const { rerender } = render(<ObjetivoCell kpi={kpiBase} onChange={vi.fn()} />);
    expect(screen.getByTitle(/≥ 50/)).toBeTruthy();
    rerender(<ObjetivoCell kpi={{ ...kpiBase, mejor_si: "bajar" }} onChange={vi.fn()} />);
    expect(screen.getByTitle(/≤ 50/)).toBeTruthy();
  });
});
