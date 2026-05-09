import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import KpiCard from "./KpiCard";

describe("KpiCard — render", () => {
  it("renderiza label y value", () => {
    render(<KpiCard label="Ventas" value="$1.500" />);
    expect(screen.queryByText("Ventas")).not.toBeNull();
    expect(screen.queryByText("$1.500")).not.toBeNull();
  });

  it("renderiza sub si está provisto", () => {
    render(<KpiCard label="Ventas" value="$100" sub="3 pedidos" />);
    expect(screen.queryByText("3 pedidos")).not.toBeNull();
  });

  it("NO renderiza sub si es null/undefined", () => {
    const { container } = render(<KpiCard label="X" value="100" />);
    expect(container.querySelector(".sub")).toBeNull();
  });

  it("NO renderiza sub si es string vacío (falsy)", () => {
    const { container } = render(<KpiCard label="X" value="100" sub="" />);
    expect(container.querySelector(".sub")).toBeNull();
  });

  it("renderiza sub=0 con wrapper .sub (bug histórico fixeado)", () => {
    // Antes: `{sub && <div>}` con sub=0 → React renderizaba `0` como
    // texto SIN el wrapper .sub (asimétrico con sub="0" que sí lo tenía).
    // Ahora: chequeo explícito null/"" → 0 entra al path normal.
    const { container } = render(<KpiCard label="X" value="100" sub={0} />);
    const subDiv = container.querySelector(".sub");
    expect(subDiv).not.toBeNull();
    expect(subDiv.textContent).toBe("0");
  });

  it("renderiza sub='0' (string truthy) con wrapper", () => {
    // Sanity check: el path original ya funcionaba para strings, lo
    // mantenemos para asegurar que el fix no rompió este caso.
    const { container } = render(<KpiCard label="X" value="100" sub="0" />);
    expect(container.querySelector(".sub")).not.toBeNull();
  });
});

describe("KpiCard — tone class", () => {
  it("sin tone aplica solo 'kpi-card'", () => {
    const { container } = render(<KpiCard label="X" value="1" />);
    const card = container.querySelector(".kpi-card");
    expect(card).not.toBeNull();
    // className es "kpi-card " (con trailing space del template literal),
    // no debe contener tones específicos.
    expect(card.className.trim()).toBe("kpi-card");
  });

  it("tone='green' aplica clase verde", () => {
    const { container } = render(<KpiCard label="X" value="1" tone="green" />);
    expect(container.querySelector(".kpi-card.green")).not.toBeNull();
  });

  it("tone='red' aplica clase roja", () => {
    const { container } = render(<KpiCard label="X" value="1" tone="red" />);
    expect(container.querySelector(".kpi-card.red")).not.toBeNull();
  });

  it("tone='amber' aplica clase ámbar", () => {
    const { container } = render(<KpiCard label="X" value="1" tone="amber" />);
    expect(container.querySelector(".kpi-card.amber")).not.toBeNull();
  });
});

describe("KpiCard — value puede ser cualquier renderable", () => {
  it("acepta string", () => {
    render(<KpiCard label="X" value="texto" />);
    expect(screen.queryByText("texto")).not.toBeNull();
  });

  it("acepta número (renderiza directo)", () => {
    render(<KpiCard label="X" value={42} />);
    expect(screen.queryByText("42")).not.toBeNull();
  });

  it("acepta JSX (e.g., spans con estilos custom)", () => {
    render(
      <KpiCard
        label="X"
        value={<span data-testid="valor-jsx">complejo</span>}
      />,
    );
    expect(screen.queryByTestId("valor-jsx")).not.toBeNull();
  });
});
