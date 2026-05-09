import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

// Mock de useAlertas — Layout consume el contexto, lo controlamos por test.
vi.mock("./AlertasContext", () => ({
  useAlertas: vi.fn(),
}));
import { useAlertas } from "./AlertasContext";
import Layout from "./Layout";

function renderConRouter(initialPath = "/direccion", alertas = []) {
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
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="*" element={<div data-testid="contenido-pagina">Página actual</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("Layout — render base", () => {
  afterEach(() => vi.clearAllMocks());

  it("renderiza el título y la nav", () => {
    renderConRouter();
    expect(screen.queryByText("KPI Dashboard")).not.toBeNull();
    expect(screen.queryByRole("navigation")).not.toBeNull();
  });

  it("renderiza el Outlet con la página activa", () => {
    renderConRouter("/direccion");
    expect(screen.queryByTestId("contenido-pagina")).not.toBeNull();
  });

  it("muestra los 3 grupos de navegación", () => {
    renderConRouter();
    expect(screen.queryByText("Análisis")).not.toBeNull();
    expect(screen.queryByText("Operación")).not.toBeNull();
    expect(screen.queryByText("Admin")).not.toBeNull();
  });

  it("renderiza los links principales", () => {
    renderConRouter();
    expect(screen.queryByRole("link", { name: /Dirección/i })).not.toBeNull();
    expect(screen.queryByRole("link", { name: /Comercial$/i })).not.toBeNull();
    expect(screen.queryByRole("link", { name: /Caja diaria/i })).not.toBeNull();
    expect(screen.queryByRole("link", { name: /Casos a revisar/i })).not.toBeNull();
    expect(screen.queryByRole("link", { name: /Importar CSV/i })).not.toBeNull();
  });

  it("a11y: el link activo tiene aria-current='page' (NavLink lo aplica auto)", () => {
    renderConRouter("/comercial");
    const linkActivo = screen.getByRole("link", { name: /Comercial$/i });
    expect(linkActivo.getAttribute("aria-current")).toBe("page");
    // Otros links NO tienen aria-current.
    const linkOtro = screen.getByRole("link", { name: /Dirección/i });
    expect(linkOtro.getAttribute("aria-current")).not.toBe("page");
  });
});

describe("Layout — badges según alertas", () => {
  afterEach(() => vi.clearAllMocks());

  it("sin alertas → ningún badge visible", () => {
    renderConRouter("/direccion", []);
    // Los badges renderean span con números; chequeamos que no aparezca
    // ningún número adyacente al link Dirección.
    const linkDireccion = screen.getByRole("link", { name: /Dirección/i });
    // El text content del link es "Dirección" (sin badge).
    expect(linkDireccion.textContent.trim()).toBe("Dirección");
  });

  it("alertas críticas y atención muestran badges en Dirección", () => {
    renderConRouter("/direccion", [
      { severidad: "critica", codigo: "x", titulo: "T", link: "/x" },
      { severidad: "critica", codigo: "y", titulo: "T", link: "/x" },
      { severidad: "atencion", codigo: "z", titulo: "T", link: "/x" },
    ]);
    const linkDireccion = screen.getByRole("link", { name: /Dirección/i });
    // Badges con count: 2 críticas, 1 atención.
    expect(linkDireccion.textContent).toContain("2");
    expect(linkDireccion.textContent).toContain("1");
  });

  it("alerta casos_pendientes muestra badge en 'Casos a revisar'", () => {
    renderConRouter("/casos", [
      { severidad: "atencion", codigo: "casos_pendientes", titulo: "T", link: "/casos", valor: 7 },
    ]);
    const linkCasos = screen.getByRole("link", { name: /Casos a revisar/i });
    expect(linkCasos.textContent).toContain("7");
  });

  it("alerta caja_saldo_negativo muestra badge en 'Caja / Finanzas'", () => {
    renderConRouter("/caja", [
      { severidad: "critica", codigo: "caja_saldo_negativo", titulo: "T", link: "/caja", valor: 1 },
    ]);
    const linkCaja = screen.getByRole("link", { name: /Caja \/ Finanzas/i });
    expect(linkCaja.textContent).toContain("1");
  });

  it("alerta categorias_sin_familia muestra badge en 'Configuración'", () => {
    renderConRouter("/config", [
      { severidad: "info", codigo: "categorias_sin_familia", titulo: "T", link: "/config", valor: 3 },
    ]);
    const linkConfig = screen.getByRole("link", { name: /Configuración/i });
    expect(linkConfig.textContent).toContain("3");
  });

  it("alerta sin valor (= 0 o null) NO muestra badge", () => {
    renderConRouter("/casos", [
      { severidad: "atencion", codigo: "casos_pendientes", titulo: "T", link: "/casos", valor: 0 },
    ]);
    const linkCasos = screen.getByRole("link", { name: /Casos a revisar/i });
    // Solo el texto del link, sin badge numérico.
    expect(linkCasos.textContent.trim()).toBe("Casos a revisar");
  });
});

describe("Layout — sidebar mobile toggle", () => {
  afterEach(() => vi.clearAllMocks());

  it("toggle button alterna aria-expanded entre true/false", () => {
    renderConRouter();
    const toggle = screen.getByRole("button", { name: /Abrir menú/i });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(toggle);
    // Después del click el label cambia y aria también.
    const toggleAbierto = screen.getByRole("button", { name: /Cerrar menú/i });
    expect(toggleAbierto.getAttribute("aria-expanded")).toBe("true");
  });

  it("sidebar tiene clase 'abierto' cuando se abre", () => {
    const { container } = renderConRouter();
    const aside = container.querySelector("aside.sidebar");
    expect(aside.className).not.toContain("abierto");

    fireEvent.click(screen.getByRole("button", { name: /Abrir menú/i }));
    expect(aside.className).toContain("abierto");
  });

  it("click en un link cierra la sidebar (cerrarSidebar handler en nav)", () => {
    const { container } = renderConRouter();
    fireEvent.click(screen.getByRole("button", { name: /Abrir menú/i }));
    expect(container.querySelector("aside.sidebar").className).toContain("abierto");

    // Click en cualquier link debería cerrar.
    fireEvent.click(screen.getByRole("link", { name: /Comercial$/i }));
    expect(container.querySelector("aside.sidebar").className).not.toContain("abierto");
  });

  it("overlay aparece solo cuando sidebar está abierto", () => {
    const { container } = renderConRouter();
    expect(container.querySelector(".sidebar-overlay")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Abrir menú/i }));
    expect(container.querySelector(".sidebar-overlay")).not.toBeNull();
  });

  it("click en overlay cierra la sidebar", () => {
    const { container } = renderConRouter();
    fireEvent.click(screen.getByRole("button", { name: /Abrir menú/i }));
    const overlay = container.querySelector(".sidebar-overlay");
    expect(overlay).not.toBeNull();

    fireEvent.mouseDown(overlay, { target: overlay, currentTarget: overlay });
    fireEvent.mouseUp(overlay, { target: overlay, currentTarget: overlay });
    expect(container.querySelector("aside.sidebar").className).not.toContain("abierto");
  });

  it("drag-to-close prevention: mouseDown fuera del overlay + mouseUp en overlay → NO cierra", () => {
    // Caso bug clásico: usuario inicia drag en otro elemento, suelta sobre
    // el overlay accidentalmente. NO debe cerrar la sidebar.
    const { container } = renderConRouter();
    fireEvent.click(screen.getByRole("button", { name: /Abrir menú/i }));
    const overlay = container.querySelector(".sidebar-overlay");

    // Simular drag iniciado afuera del overlay.
    const otroElemento = document.body;
    fireEvent.mouseDown(otroElemento);
    fireEvent.mouseUp(overlay, { target: overlay, currentTarget: overlay });

    // Sidebar sigue abierto.
    expect(container.querySelector("aside.sidebar").className).toContain("abierto");
  });
});

describe("Layout — shortcut por OS", () => {
  const originalUserAgent = navigator.userAgent;

  afterEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(navigator, "userAgent", {
      value: originalUserAgent,
      configurable: true,
    });
  });

  it("muestra Ctrl+K en Windows/Linux", () => {
    Object.defineProperty(navigator, "userAgent", {
      value: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",
      configurable: true,
    });
    renderConRouter();
    // El kbd con la sigla.
    const kbds = screen.getAllByText(/Ctrl\+K|⌘K/);
    expect(kbds[0].textContent).toBe("Ctrl+K");
  });

  it("muestra ⌘K en Mac", () => {
    Object.defineProperty(navigator, "userAgent", {
      value: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...",
      configurable: true,
    });
    renderConRouter();
    const kbds = screen.getAllByText(/Ctrl\+K|⌘K/);
    expect(kbds[0].textContent).toBe("⌘K");
  });

  it("muestra ⌘K en iPad/iPhone", () => {
    Object.defineProperty(navigator, "userAgent", {
      value: "Mozilla/5.0 (iPad; CPU OS 14_4 like Mac OS X) ...",
      configurable: true,
    });
    renderConRouter();
    const kbds = screen.getAllByText(/Ctrl\+K|⌘K/);
    expect(kbds[0].textContent).toBe("⌘K");
  });
});
