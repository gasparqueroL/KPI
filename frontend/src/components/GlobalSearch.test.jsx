import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";

// Mock api: cada test setea el comportamiento de api.get.
vi.mock("../api/client", () => ({
  default: { get: vi.fn() },
}));
import api from "../api/client";
import GlobalSearch from "./GlobalSearch";

// Helper: render con router. Si querés observar la URL post-navigate,
// pasá un setter al spy `onLocationChange`.
function renderConRouter(onLocationChange = null) {
  function Spy() {
    const loc = useLocation();
    if (onLocationChange) onLocationChange(loc);
    return null;
  }
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <GlobalSearch />
      <Routes>
        <Route path="*" element={<Spy />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("GlobalSearch — open/close con Cmd+K", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it("Ctrl+K (sin foco en input) abre el modal", () => {
    renderConRouter();
    expect(screen.queryByPlaceholderText(/Buscá clientes/i)).toBeNull();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.queryByPlaceholderText(/Buscá clientes/i)).not.toBeNull();
  });

  it("Cmd+K (Mac) también abre", () => {
    renderConRouter();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.queryByPlaceholderText(/Buscá clientes/i)).not.toBeNull();
  });

  it("Ctrl+K con modal abierto lo CIERRA (toggle)", () => {
    renderConRouter();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.queryByPlaceholderText(/Buscá clientes/i)).not.toBeNull();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.queryByPlaceholderText(/Buscá clientes/i)).toBeNull();
  });

  it("Ctrl+K mientras escribís en otro input NO secuestra (excepto si el modal ya está abierto)", () => {
    function App() {
      return (
        <MemoryRouter>
          <input data-testid="afuera" />
          <GlobalSearch />
        </MemoryRouter>
      );
    }
    render(<App />);
    const afuera = screen.getByTestId("afuera");
    afuera.focus();

    // Cmd+K con foco en input externo y modal cerrado → no abre.
    fireEvent.keyDown(afuera, { key: "k", ctrlKey: true });
    expect(screen.queryByPlaceholderText(/Buscá clientes/i)).toBeNull();
  });
});

describe("GlobalSearch — input + debounce + fetch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(api.get).mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("escribir query dispara fetch DESPUÉS del debounce 200ms", async () => {
    api.get.mockResolvedValue({ data: { resultados: [] } });
    renderConRouter();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });

    const input = screen.getByPlaceholderText(/Buscá clientes/i);
    fireEvent.change(input, { target: { value: "Acme" } });

    // Antes del debounce: ningún fetch.
    expect(api.get).not.toHaveBeenCalled();

    // Avanzar 199ms → todavía no.
    await act(async () => vi.advanceTimersByTime(199));
    expect(api.get).not.toHaveBeenCalled();

    // 1ms más → 200ms total → dispara.
    await act(async () => vi.advanceTimersByTime(1));
    expect(api.get).toHaveBeenCalledWith("/api/search", expect.objectContaining({
      params: { q: "Acme" },
    }));
  });

  it("guard de stale-response: si fetch viejo resuelve después del nuevo, NO pisa resultados", async () => {
    // Bug latente capturado por review ronda 8: dos fetches in-flight y
    // el más viejo resuelve último. Sin guard, los resultados antiguos
    // pisaban a los nuevos. Con `requestIdRef` el response stale se descarta.
    let resolveA, resolveAcme;
    const promesaA = new Promise((r) => { resolveA = r; });
    const promesaAcme = new Promise((r) => { resolveAcme = r; });
    api.get
      .mockReturnValueOnce(promesaA)
      .mockReturnValueOnce(promesaAcme);

    renderConRouter();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = screen.getByPlaceholderText(/Buscá clientes/i);

    // Tipear "A" y dejar el fetch in-flight.
    fireEvent.change(input, { target: { value: "A" } });
    await act(async () => vi.advanceTimersByTime(200));
    expect(api.get).toHaveBeenCalledTimes(1);

    // Tipear "Acme" — segundo fetch.
    fireEvent.change(input, { target: { value: "Acme" } });
    await act(async () => vi.advanceTimersByTime(200));
    expect(api.get).toHaveBeenCalledTimes(2);

    // El segundo fetch resuelve PRIMERO con resultados de "Acme".
    await act(async () => {
      resolveAcme({ data: { resultados: [{ tipo: "cliente", id: 1, label: "Acme SA", link: "/x" }] } });
    });
    expect(screen.queryByText("Acme SA")).not.toBeNull();

    // Ahora el primer fetch (stale, "A") resuelve último con resultados
    // genéricos. Sin guard pisaría "Acme SA". Con guard, descarta.
    await act(async () => {
      resolveA({ data: { resultados: [{ tipo: "cliente", id: 99, label: "Otro genérico", link: "/y" }] } });
    });
    // "Acme SA" sigue visible — el response stale fue ignorado.
    expect(screen.queryByText("Acme SA")).not.toBeNull();
    expect(screen.queryByText("Otro genérico")).toBeNull();
  });

  it("teclas rápidas cancelan el debounce previo (solo último query se fetchea)", async () => {
    api.get.mockResolvedValue({ data: { resultados: [] } });
    renderConRouter();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = screen.getByPlaceholderText(/Buscá clientes/i);

    fireEvent.change(input, { target: { value: "A" } });
    await act(async () => vi.advanceTimersByTime(100));
    fireEvent.change(input, { target: { value: "Acme" } });
    await act(async () => vi.advanceTimersByTime(100));
    fireEvent.change(input, { target: { value: "Acme SA" } });

    // 200ms tras el último cambio.
    await act(async () => vi.advanceTimersByTime(200));

    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledWith("/api/search", expect.objectContaining({
      params: { q: "Acme SA" },
    }));
  });

  it("query vacía limpia resultados y NO hace fetch", async () => {
    api.get.mockResolvedValue({ data: { resultados: [{ tipo: "cliente", id: 1, label: "X", link: "/x" }] } });
    renderConRouter();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = screen.getByPlaceholderText(/Buscá clientes/i);

    // Escribir y dejar resultados.
    fireEvent.change(input, { target: { value: "X" } });
    await act(async () => vi.advanceTimersByTime(200));
    expect(api.get).toHaveBeenCalledTimes(1);

    // Borrar todo el input → query vacía.
    fireEvent.change(input, { target: { value: "" } });
    await act(async () => vi.advanceTimersByTime(300));

    // No hubo segundo fetch.
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Escribí al menos 1 caracter/i)).not.toBeNull();
  });
});

describe("GlobalSearch — resultados y navegación", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(api.get).mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  const RESULTADOS = [
    { tipo: "cliente", id: 1, label: "Acme SA", sub: "ID 1", link: "/cuentas-corrientes?cliente=1" },
    { tipo: "factura", id: 99, label: "Factura 99", sub: "$1.000", link: "/proveedores?factura=99" },
    { tipo: "movimiento", id: 5, label: "Pago efectivo", sub: "$500", link: "/caja-diaria" },
  ];

  async function renderConResultados() {
    api.get.mockResolvedValue({ data: { resultados: RESULTADOS } });
    let url = null;
    renderConRouter((loc) => { url = loc.pathname + loc.search; });
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = screen.getByPlaceholderText(/Buscá clientes/i);
    fireEvent.change(input, { target: { value: "Acme" } });
    await act(async () => vi.advanceTimersByTime(200));
    return { input, getUrl: () => url };
  }

  it("renderiza los resultados con label y sub", async () => {
    await renderConResultados();
    expect(screen.queryByText("Acme SA")).not.toBeNull();
    expect(screen.queryByText("Factura 99")).not.toBeNull();
    expect(screen.queryByText("Pago efectivo")).not.toBeNull();
    // sub aparece como secundario.
    expect(screen.queryByText("$1.000")).not.toBeNull();
  });

  it("ArrowDown × 2 + ArrowUp lleva highlight al índice 1 (Factura 99)", async () => {
    const { input, getUrl } = await renderConResultados();
    // highlight=0 inicial. Down→1, Down→2, Up→1.
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.keyDown(input, { key: "Enter" });
    // Enter abre el resultado del medio (Factura 99). Antes este test
    // no tenía expect — silent pass detectado por code review.
    expect(getUrl()).toBe("/proveedores?factura=99");
  });

  it("Enter abre el resultado actualmente highlighted (default 0)", async () => {
    const { input, getUrl } = await renderConResultados();
    fireEvent.keyDown(input, { key: "Enter" });
    // Default highlight=0 → primer resultado (Acme SA).
    expect(getUrl()).toBe("/cuentas-corrientes?cliente=1");
  });

  it("Enter después de ArrowDown abre el segundo resultado", async () => {
    const { input, getUrl } = await renderConResultados();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(getUrl()).toBe("/proveedores?factura=99");
  });

  it("ArrowDown no pasa el último (clamping)", async () => {
    const { input, getUrl } = await renderConResultados();
    // 3 resultados: índices 0,1,2. Si highlight ya está en 2, Down no avanza.
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" }); // intenta ir al 3 (clamped a 2)
    fireEvent.keyDown(input, { key: "ArrowDown" }); // idem
    fireEvent.keyDown(input, { key: "Enter" });
    // Sigue en 2 (movimiento).
    expect(getUrl()).toBe("/caja-diaria");
  });

  it("ArrowUp no pasa el primero (clamping a 0)", async () => {
    const { input, getUrl } = await renderConResultados();
    fireEvent.keyDown(input, { key: "ArrowUp" }); // ya está en 0
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(getUrl()).toBe("/cuentas-corrientes?cliente=1");
  });

  it("Enter sin resultados no rompe (no navigate)", async () => {
    api.get.mockResolvedValue({ data: { resultados: [] } });
    let urlBefore = null;
    renderConRouter((loc) => { urlBefore = loc.pathname; });
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = screen.getByPlaceholderText(/Buscá clientes/i);
    fireEvent.change(input, { target: { value: "nada" } });
    await act(async () => vi.advanceTimersByTime(200));

    fireEvent.keyDown(input, { key: "Enter" });
    // URL no cambia (sigue en /).
    expect(urlBefore).toBe("/");
  });
});

describe("GlobalSearch — UX states", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(api.get).mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("input vacío al abrir: muestra hint 'Escribí al menos 1 caracter'", () => {
    renderConRouter();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.queryByText(/Escribí al menos 1 caracter/i)).not.toBeNull();
  });

  it("query con resultados vacíos muestra 'Sin resultados'", async () => {
    api.get.mockResolvedValue({ data: { resultados: [] } });
    renderConRouter();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = screen.getByPlaceholderText(/Buscá clientes/i);
    fireEvent.change(input, { target: { value: "asdf" } });
    await act(async () => vi.advanceTimersByTime(200));
    expect(screen.queryByText(/Sin resultados/i)).not.toBeNull();
  });

  it("input maxLength=100 (alineado con backend Query max_length)", () => {
    renderConRouter();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = screen.getByPlaceholderText(/Buscá clientes/i);
    expect(input.getAttribute("maxlength")).toBe("100");
  });

  it("error en api.get NO crashea, deja resultados vacíos (silent)", async () => {
    api.get.mockRejectedValue(new Error("network"));
    renderConRouter();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = screen.getByPlaceholderText(/Buscá clientes/i);
    fireEvent.change(input, { target: { value: "x" } });

    await act(async () => vi.advanceTimersByTime(200));
    // Tras el reject, debe mostrar "Sin resultados" (no romper UI).
    // Esto requiere que React procese el .catch — esperamos un microtask.
    await act(async () => { await Promise.resolve(); });

    expect(screen.queryByText(/Sin resultados/i)).not.toBeNull();
  });
});
