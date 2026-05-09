import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import KpiCardComp, { COLORES_DELTA } from "./KpiCardComp";

// Helper: encuentra el span con `style.color` que matchea el color esperado.
// JSDOM convierte hex a rgb() automáticamente en .style.color y en el atributo
// HTML. Convertimos el hex esperado a rgb() para hacer comparación robusta.
function hexToRgb(hex) {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgb(${r}, ${g}, ${b})`;
}

function spanConColor(container, hex) {
  const rgb = hexToRgb(hex);
  return Array.from(container.querySelectorAll("span[style*='color']"))
    .find((s) => s.style.color === rgb);
}

describe("KpiCardComp — render base", () => {
  it("renderiza label y value crudo cuando no hay formatter", () => {
    render(<KpiCardComp label="Ventas" value={1500} />);
    expect(screen.queryByText("Ventas")).not.toBeNull();
    expect(screen.queryByText("1500")).not.toBeNull();
  });

  it("aplica formatter al value", () => {
    render(<KpiCardComp label="Ventas" value={1500} formatter={(v) => `$${v}`} />);
    expect(screen.queryByText("$1500")).not.toBeNull();
  });

  it("renderiza sub si está", () => {
    render(<KpiCardComp label="X" value={100} sub="extra info" />);
    expect(screen.queryByText("extra info")).not.toBeNull();
  });

  it("aplica clase tone como modificador", () => {
    const { container } = render(<KpiCardComp label="X" value={100} tone="green" />);
    expect(container.querySelector(".kpi-card.green")).not.toBeNull();
  });
});

describe("KpiCardComp — delta sin prevValue (no comparativa)", () => {
  it("sin prevValue NO muestra badge de delta", () => {
    const { container } = render(<KpiCardComp label="X" value={100} />);
    // No hay span con %
    expect(container.textContent).not.toMatch(/\d+\.\d+%/);
  });

  it("prevValue === 0 NO muestra delta (evita div/0)", () => {
    // Caso típico: comparando un período con período anterior sin actividad.
    const { container } = render(<KpiCardComp label="X" value={100} prevValue={0} />);
    expect(container.textContent).not.toMatch(/\d+\.\d+%/);
  });

  it("prevValue undefined NO muestra delta", () => {
    const { container } = render(<KpiCardComp label="X" value={100} prevValue={undefined} />);
    expect(container.textContent).not.toMatch(/\d+\.\d+%/);
  });
});

describe("KpiCardComp — delta positivo (mejora)", () => {
  it("value > prevValue → muestra delta positivo", () => {
    render(<KpiCardComp label="X" value={150} prevValue={100} />);
    // (150 - 100) / 100 * 100 = 50% (positive)
    expect(screen.queryByText(/50\.0%/)).not.toBeNull();
  });

  it("delta positivo usa color verde (COLORES_DELTA.positivo)", () => {
    const { container } = render(<KpiCardComp label="X" value={150} prevValue={100} />);
    expect(spanConColor(container, COLORES_DELTA.positivo)).not.toBeUndefined();
  });

  it("decimal entero (33) → 33.0%", () => {
    // (133 - 100) / 100 * 100 = 33% → toFixed(1) → "33.0%"
    render(<KpiCardComp label="X" value={133} prevValue={100} />);
    expect(screen.queryByText(/33\.0%/)).not.toBeNull();
  });

  it("decimal con fracción (33.5) → 33.5%", () => {
    // (133.5 - 100) / 100 * 100 = 33.5% → toFixed(1) → "33.5%"
    // Tests separados (no rerender) para evitar ambigüedad — antes se hacía
    // en un solo it con dos render() lo que matcheaba en cualquiera.
    render(<KpiCardComp label="X" value={133.5} prevValue={100} />);
    expect(screen.queryByText(/33\.5%/)).not.toBeNull();
  });
});

describe("KpiCardComp — delta negativo (caída)", () => {
  it("value < prevValue → muestra delta absoluto sin signo (color comunica)", () => {
    render(<KpiCardComp label="X" value={50} prevValue={100} />);
    // (50 - 100) / 100 * 100 = -50%; renderiza como Math.abs → 50.0%
    // El color rojo + icon trend-down comunica que es caída.
    expect(screen.queryByText(/50\.0%/)).not.toBeNull();
  });

  it("delta negativo usa color rojo (COLORES_DELTA.negativo)", () => {
    const { container } = render(<KpiCardComp label="X" value={50} prevValue={100} />);
    expect(spanConColor(container, COLORES_DELTA.negativo)).not.toBeUndefined();
  });
});

describe("KpiCardComp — delta cero", () => {
  it("value === prevValue → muestra 0.0% en gris (COLORES_DELTA.neutro)", () => {
    const { container } = render(<KpiCardComp label="X" value={100} prevValue={100} />);
    expect(screen.queryByText(/0\.0%/)).not.toBeNull();
    expect(spanConColor(container, COLORES_DELTA.neutro)).not.toBeUndefined();
  });
});

describe("KpiCardComp — edge: prevValue negativo", () => {
  // Caso real: una métrica que puede ser negativa (e.g., margen bruto cuando
  // hubo pérdida). La fórmula usa Math.abs(prevValue) en el denominador.
  it("prev=-100, value=-50 (mejoró acercándose a 0): delta positivo", () => {
    render(<KpiCardComp label="X" value={-50} prevValue={-100} />);
    // (-50 - -100) / |-100| * 100 = 50 / 100 * 100 = 50% positivo
    // Pasa de -100 a -50: mejora (perdió menos) → delta positivo, verde.
    expect(screen.queryByText(/50\.0%/)).not.toBeNull();
  });

  it("prev=-100, value=-200 (empeoró): delta negativo", () => {
    render(<KpiCardComp label="X" value={-200} prevValue={-100} />);
    // (-200 - -100) / |-100| * 100 = -100 / 100 * 100 = -100%
    // Pasa de -100 a -200: empeoró → delta negativo, rojo.
    expect(screen.queryByText(/100\.0%/)).not.toBeNull();
  });
});

describe("KpiCardComp — formatter + delta combinados", () => {
  it("formatter aplica al value pero NO al delta (delta siempre %)", () => {
    render(
      <KpiCardComp
        label="Ventas"
        value={150000}
        prevValue={100000}
        formatter={(v) => `$${v.toLocaleString()}`}
      />,
    );
    // El valor formateado con el formatter del caller.
    expect(screen.queryByText("$150,000")).not.toBeNull();
    // El delta sigue siendo %.
    expect(screen.queryByText(/50\.0%/)).not.toBeNull();
  });
});
