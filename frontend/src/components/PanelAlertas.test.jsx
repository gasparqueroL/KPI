import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mock del context: cada test setea el valor de retorno de `useAlertas`
// para controlar el shape que ve el componente sin levantar el provider.
vi.mock("./AlertasContext", () => ({
  useAlertas: vi.fn(),
}));
import { useAlertas } from "./AlertasContext";
import PanelAlertas from "./PanelAlertas";

// Helper: render con MemoryRouter (PanelAlertas usa <Link>) y stub de useAlertas.
function renderConAlertas(alertas) {
  vi.mocked(useAlertas).mockReturnValue({
    alertas,
    total: alertas.length,
    criticas: alertas.filter((a) => a.severidad === "critica").length,
    atencion: alertas.filter((a) => a.severidad === "atencion").length,
    info: alertas.filter((a) => a.severidad === "info").length,
    error: null,
    recargar: vi.fn(),
  });
  return render(
    <MemoryRouter>
      <PanelAlertas />
    </MemoryRouter>,
  );
}

describe("PanelAlertas — render base", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("no renderiza nada si total es 0", () => {
    const { container } = renderConAlertas([]);
    expect(container.firstChild).toBeNull();
  });

  it("renderiza header con cantidad total entre paréntesis", () => {
    renderConAlertas([
      { codigo: "x", titulo: "Test", severidad: "info", dominio: "datos", link: "/x" },
      { codigo: "y", titulo: "Test 2", severidad: "info", dominio: "datos", link: "/y" },
    ]);
    // Match estricto: el `(\d+)` exige paréntesis literales y dígitos —
    // resistente a títulos de alertas que mencionen "Alertas activas".
    expect(screen.queryByText(/^Alertas activas \(2\)$/)).not.toBeNull();
  });

  it("muestra título y detalle de cada alerta", () => {
    renderConAlertas([
      {
        codigo: "morosos",
        titulo: "5 clientes con saldo +90 días",
        detalle: "Total moroso: $200.000 — Cliente A, B",
        severidad: "atencion",
        dominio: "cobranza",
        link: "/cuentas-corrientes",
      },
    ]);
    expect(screen.queryByText(/5 clientes con saldo \+90 días/)).not.toBeNull();
    expect(screen.queryByText(/Total moroso: \$200\.000/)).not.toBeNull();
  });
});

describe("PanelAlertas — agrupación por dominio", () => {
  afterEach(() => vi.clearAllMocks());

  it("agrupa alertas en headers por dominio con conteo", () => {
    renderConAlertas([
      { codigo: "a", titulo: "Vta caída", severidad: "atencion", dominio: "comercial", link: "/c" },
      { codigo: "b", titulo: "Margen bajo", severidad: "atencion", dominio: "comercial", link: "/c" },
      { codigo: "c", titulo: "Cobertura baja", severidad: "atencion", dominio: "cobranza", link: "/co" },
    ]);
    // Match estricto al header de dominio: `^Label (N)$`. El `^...$` evita
    // matchear contenido dentro de títulos/detalles que mencionen "Comercial".
    expect(screen.queryByText(/^Comercial \(2\)$/)).not.toBeNull();
    expect(screen.queryByText(/^Cobranza \(1\)$/)).not.toBeNull();
  });

  it("alerta sin dominio se asigna a 'datos' por default (compat con backend viejo)", () => {
    renderConAlertas([
      { codigo: "x", titulo: "Sin dominio", severidad: "info", link: "/x" },
    ]);
    expect(screen.queryByText(/^Datos \/ Sistema \(1\)$/)).not.toBeNull();
  });

  it("dominio desconocido cae al bucket 'otros' con console.warn", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    renderConAlertas([
      { codigo: "rrhh", titulo: "Algo de RRHH", severidad: "info", dominio: "rrhh", link: "/r" },
    ]);
    expect(screen.queryByText(/^Otros \(1\)$/)).not.toBeNull();
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining('dominio desconocido "rrhh"'),
    );
    warn.mockRestore();
  });
});

describe("PanelAlertas — orden por severidad y tiebreaker canónico", () => {
  afterEach(() => vi.clearAllMocks());

  it("dominio con severidad CRÍTICA aparece primero aunque sea 'tarde' en el orden canónico", () => {
    // Caso real: una alerta crítica en "datos" (que es last en el canon)
    // debería subir al tope del panel — sino la dueña la pierde.
    renderConAlertas([
      { codigo: "a", titulo: "Alta comercial", severidad: "info", dominio: "comercial", link: "/c" },
      { codigo: "b", titulo: "Crítica datos", severidad: "critica", dominio: "datos", link: "/d" },
    ]);
    // Match estricto a los headers (label + paréntesis con count) — evita
    // false positives si un título de alerta arranca con la palabra dominio.
    const headers = screen.getAllByText(/^(Comercial|Cobranza|Caja|Datos \/ Sistema|Otros) \(\d+\)$/);
    // El primero debe ser "Datos / Sistema" (sev crítica), no "Comercial".
    expect(headers[0].textContent).toMatch(/^Datos \/ Sistema/);
  });

  it("empate de severidad → respeta orden canónico (comercial, cobranza, caja, datos, otros)", () => {
    renderConAlertas([
      { codigo: "a", titulo: "A1", severidad: "atencion", dominio: "datos", link: "/d" },
      { codigo: "b", titulo: "A2", severidad: "atencion", dominio: "comercial", link: "/c" },
      { codigo: "c", titulo: "A3", severidad: "atencion", dominio: "caja", link: "/cj" },
    ]);
    const headers = screen.getAllByText(/^(Comercial|Cobranza|Caja|Datos \/ Sistema|Otros) \(\d+\)$/);
    // Las 3 con misma severidad → orden canónico: Comercial, Caja, Datos.
    expect(headers[0].textContent).toMatch(/^Comercial/);
    expect(headers[1].textContent).toMatch(/^Caja/);
    expect(headers[2].textContent).toMatch(/^Datos \/ Sistema/);
  });

  it("dentro de un dominio mantiene el orden recibido del backend", () => {
    // El backend ya viene con prioridad pre-calculada; no tocamos el orden
    // intra-dominio.
    renderConAlertas([
      { codigo: "a", titulo: "Primera", severidad: "atencion", dominio: "comercial", link: "/c1" },
      { codigo: "b", titulo: "Segunda", severidad: "atencion", dominio: "comercial", link: "/c2" },
    ]);
    const links = screen.getAllByRole("link");
    expect(links[0].textContent).toContain("Primera");
    expect(links[1].textContent).toContain("Segunda");
  });
});

describe("PanelAlertas — deep linking", () => {
  afterEach(() => vi.clearAllMocks());

  it("preserva query params del link (deep link a entidad específica)", () => {
    // Pattern usado por clientes_morosos / facturas_vencidas: link incluye
    // ?cliente=42 o ?proveedor=7 para abrir el detalle al click.
    renderConAlertas([
      {
        codigo: "morosos",
        titulo: "Cliente moroso",
        severidad: "atencion",
        dominio: "cobranza",
        link: "/cuentas-corrientes?cliente=42",
      },
    ]);
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("/cuentas-corrientes?cliente=42");
  });

  it("link sin query params (alerta no-deep-linkable) sigue funcionando", () => {
    renderConAlertas([
      { codigo: "info", titulo: "Info general", severidad: "info", dominio: "datos", link: "/config" },
    ]);
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("/config");
  });

  it("cada alerta es un Link separado con su propio href", () => {
    renderConAlertas([
      { codigo: "a", titulo: "A", severidad: "atencion", dominio: "comercial", link: "/comercial" },
      { codigo: "b", titulo: "B", severidad: "critica", dominio: "cobranza", link: "/proveedores?proveedor=5" },
    ]);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    const hrefs = links.map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/comercial");
    expect(hrefs).toContain("/proveedores?proveedor=5");
  });
});

describe("PanelAlertas — severidad colores", () => {
  afterEach(() => vi.clearAllMocks());

  it("usa color de fallback para severidad desconocida (info)", () => {
    // Defensa: si el backend introduce una severidad nueva sin update
    // del frontend, no debería crashear — usa el color de info.
    renderConAlertas([
      { codigo: "x", titulo: "Severidad rara", severidad: "extreme", dominio: "datos", link: "/x" },
    ]);
    // El componente igual renderiza el alert (no crash).
    expect(screen.queryByText(/Severidad rara/)).not.toBeNull();
  });
});
