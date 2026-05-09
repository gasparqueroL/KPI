import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, renderHook, waitFor } from "@testing-library/react";
import { AlertasProvider, useAlertas } from "./AlertasContext";

// Mock del cliente API. Cada test setea el comportamiento de api.get
// (resolve con data o reject con error) para controlar el flow.
vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
  },
}));
import api from "../api/client";

const respuestaOK = {
  alertas: [
    { codigo: "x", titulo: "Test", severidad: "info", dominio: "datos", link: "/x" },
  ],
  total: 1,
  criticas: 0,
  atencion: 0,
  info: 1,
};

function wrapper({ children }) {
  return <AlertasProvider>{children}</AlertasProvider>;
}

describe("AlertasContext — fetch inicial", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it("dispara fetch a /api/alertas en mount", async () => {
    api.get.mockResolvedValue({ data: respuestaOK });
    renderHook(() => useAlertas(), { wrapper });

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/api/alertas");
    });
  });

  it("popula state con la respuesta del backend", async () => {
    api.get.mockResolvedValue({ data: respuestaOK });
    const { result } = renderHook(() => useAlertas(), { wrapper });

    await waitFor(() => {
      expect(result.current.total).toBe(1);
    });
    expect(result.current.alertas).toEqual(respuestaOK.alertas);
    expect(result.current.error).toBeNull();
  });

  it("default state antes del primer resolve: alertas vacío, total 0", () => {
    api.get.mockReturnValue(new Promise(() => {})); // pendiente
    const { result } = renderHook(() => useAlertas(), { wrapper });
    expect(result.current.alertas).toEqual([]);
    expect(result.current.total).toBe(0);
  });
});

describe("AlertasContext — error handling", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("captura error y setea error state (no crashea)", async () => {
    const consoleErr = vi.spyOn(console, "error").mockImplementation(() => {});
    api.get.mockRejectedValue(new Error("Network down"));
    const { result } = renderHook(() => useAlertas(), { wrapper });

    await waitFor(() => {
      expect(result.current.error).toBe("Network down");
    });
    // El state queda en el default — no se rompe el render del consumer.
    expect(result.current.total).toBe(0);
    expect(consoleErr).toHaveBeenCalled();
    consoleErr.mockRestore();
  });

  it("error string del API se usa con fallback genérico si el error no tiene .message", async () => {
    const consoleErr = vi.spyOn(console, "error").mockImplementation(() => {});
    // Error sin mensaje (caso raro pero defensivo).
    api.get.mockRejectedValue({ status: 500 });
    const { result } = renderHook(() => useAlertas(), { wrapper });

    await waitFor(() => {
      expect(result.current.error).toBeTruthy();
    });
    expect(result.current.error).toBe("Error de conexión");
    consoleErr.mockRestore();
  });
});

describe("AlertasContext — polling cada 60s", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(api.get).mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("re-fetchea cada 60 segundos via setInterval", async () => {
    api.get.mockResolvedValue({ data: respuestaOK });
    renderHook(() => useAlertas(), { wrapper });

    // Mount → 1 fetch.
    await vi.waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));

    // Avanzar 60s → segundo fetch.
    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    expect(api.get).toHaveBeenCalledTimes(2);

    // Avanzar otros 60s → tercer fetch.
    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    expect(api.get).toHaveBeenCalledTimes(3);
  });

  it("limpia el interval en unmount (no fetchea después)", async () => {
    api.get.mockResolvedValue({ data: respuestaOK });
    const { unmount } = renderHook(() => useAlertas(), { wrapper });

    await vi.waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    unmount();

    // Avanzar mucho — no debería haber más fetches.
    await act(async () => {
      vi.advanceTimersByTime(120_000);
    });
    expect(api.get).toHaveBeenCalledTimes(1);
  });
});

describe("AlertasContext — recargar manual", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it("recargar() fuerza un fetch sin esperar al polling", async () => {
    api.get.mockResolvedValue({ data: respuestaOK });
    const { result } = renderHook(() => useAlertas(), { wrapper });

    await vi.waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));

    // Llamar recargar manualmente — debe disparar otro fetch inmediato.
    await act(async () => {
      await result.current.recargar();
    });
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("recargar() exitoso después de un error limpia el error state", async () => {
    const consoleErr = vi.spyOn(console, "error").mockImplementation(() => {});
    // Primer fetch falla.
    api.get.mockRejectedValueOnce(new Error("temp fail"));
    const { result } = renderHook(() => useAlertas(), { wrapper });

    await vi.waitFor(() => expect(result.current.error).toBe("temp fail"));

    // Segundo fetch (vía recargar) success.
    api.get.mockResolvedValueOnce({ data: respuestaOK });
    await act(async () => {
      await result.current.recargar();
    });
    expect(result.current.error).toBeNull();
    expect(result.current.total).toBe(1);
    consoleErr.mockRestore();
  });
});

describe("AlertasContext — fuera del provider", () => {
  it("useAlertas sin provider devuelve el default context (no crashea)", () => {
    // Defensa: si alguien usa el hook sin envolver con AlertasProvider
    // (típico en tests aislados), debe devolver shape estable.
    const { result } = renderHook(() => useAlertas());
    expect(result.current.alertas).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(typeof result.current.recargar).toBe("function");
  });
});
