import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useStoredState } from "./useStoredState";

describe("useStoredState — load inicial", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("usa initial cuando no hay nada guardado", () => {
    const { result } = renderHook(() => useStoredState("test:k", "default"));
    expect(result.current[0]).toBe("default");
  });

  it("recupera valor previamente guardado", () => {
    sessionStorage.setItem("test:k", JSON.stringify("guardado"));
    const { result } = renderHook(() => useStoredState("test:k", "default"));
    expect(result.current[0]).toBe("guardado");
  });

  it("recupera objetos y arrays serializados", () => {
    const obj = { a: 1, b: [2, 3] };
    sessionStorage.setItem("test:k", JSON.stringify(obj));
    const { result } = renderHook(() => useStoredState("test:k", null));
    expect(result.current[0]).toEqual(obj);
  });

  it("fallback a initial si el JSON guardado está corrupto", () => {
    sessionStorage.setItem("test:k", "{esto-no-es-json}");
    // Silenciamos el warn que el hook emite intencionalmente al parser-fail.
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = renderHook(() => useStoredState("test:k", "default"));
    expect(result.current[0]).toBe("default");
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("string vacío como valor guardado se parsea correctamente (no fallback)", () => {
    sessionStorage.setItem("test:k", JSON.stringify(""));
    const { result } = renderHook(() => useStoredState("test:k", "default"));
    expect(result.current[0]).toBe("");
  });
});

describe("useStoredState — persistencia", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("guarda el valor inicial en sessionStorage al mount", () => {
    renderHook(() => useStoredState("test:k", "inicial"));
    expect(sessionStorage.getItem("test:k")).toBe(JSON.stringify("inicial"));
  });

  it("actualiza sessionStorage cuando cambia el state via setter", () => {
    const { result } = renderHook(() => useStoredState("test:k", "v1"));
    act(() => {
      result.current[1]("v2");
    });
    expect(result.current[0]).toBe("v2");
    expect(sessionStorage.getItem("test:k")).toBe(JSON.stringify("v2"));
  });

  it("guarda objetos complejos correctamente", () => {
    const { result } = renderHook(() =>
      useStoredState("test:k", { fuente: "", motivo: "" }),
    );
    act(() => {
      result.current[1]({ fuente: "ventas", motivo: "fecha-invalida" });
    });
    expect(JSON.parse(sessionStorage.getItem("test:k"))).toEqual({
      fuente: "ventas",
      motivo: "fecha-invalida",
    });
  });

  it("acepta functional updater (setX(prev => prev + 1)) y persiste el resultado", () => {
    // Pattern estándar de React. El hook devuelve el setter de useState
    // crudo, así que esta forma DEBE funcionar. Test que lo fija.
    const { result } = renderHook(() => useStoredState("test:counter", 0));
    expect(result.current[0]).toBe(0);

    act(() => {
      result.current[1]((prev) => prev + 1);
    });
    expect(result.current[0]).toBe(1);
    expect(JSON.parse(sessionStorage.getItem("test:counter"))).toBe(1);

    act(() => {
      result.current[1]((prev) => prev + 10);
    });
    expect(result.current[0]).toBe(11);
    expect(JSON.parse(sessionStorage.getItem("test:counter"))).toBe(11);
  });
});

describe("useStoredState — múltiples instancias", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("dos instancias con misma key NO se sincronizan automáticamente entre sí", () => {
    // Importante documentar: useStoredState NO escucha el evento `storage`.
    // Si dos componentes en la misma pestaña usan la misma key y uno actualiza,
    // el otro no se entera hasta su próximo re-render. Patrón actual del
    // proyecto: una sola instancia por key, así que no es bug, pero el test
    // asegura que el comportamiento sea predecible y conocido.
    const a = renderHook(() => useStoredState("test:shared", "init"));
    const b = renderHook(() => useStoredState("test:shared", "init"));

    act(() => {
      a.result.current[1]("cambio-en-a");
    });

    expect(a.result.current[0]).toBe("cambio-en-a");
    // b sigue con su valor local — sessionStorage tiene "cambio-en-a" pero
    // b no se re-renderiza ni hace polling.
    expect(b.result.current[0]).toBe("init");
    expect(sessionStorage.getItem("test:shared")).toBe(JSON.stringify("cambio-en-a"));
  });

  it("instancias con keys distintas son independientes", () => {
    const a = renderHook(() => useStoredState("test:a", "v-a"));
    const b = renderHook(() => useStoredState("test:b", "v-b"));

    act(() => {
      a.result.current[1]("nuevo-a");
    });

    expect(a.result.current[0]).toBe("nuevo-a");
    expect(b.result.current[0]).toBe("v-b");
    expect(sessionStorage.getItem("test:a")).toBe(JSON.stringify("nuevo-a"));
    expect(sessionStorage.getItem("test:b")).toBe(JSON.stringify("v-b"));
  });
});

describe("useStoredState — error handling", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("captura QuotaExceededError en setItem y emite warn (no crashea)", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const setItemMock = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new DOMException("Quota", "QuotaExceededError");
      });

    const { result } = renderHook(() => useStoredState("test:k", "init"));

    // El setter funciona en memoria aunque storage falle.
    act(() => {
      result.current[1]("nuevo");
    });
    expect(result.current[0]).toBe("nuevo");
    expect(warn).toHaveBeenCalled();

    setItemMock.mockRestore();
  });

  it("captura SecurityError en getItem (modo incógnito) y usa initial", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const getItemMock = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new DOMException("Denied", "SecurityError");
      });

    const { result } = renderHook(() => useStoredState("test:k", "default"));
    expect(result.current[0]).toBe("default");
    expect(warn).toHaveBeenCalled();

    getItemMock.mockRestore();
  });
});

describe("useStoredState — contracto de key estable", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("cambiar key en runtime NO re-lee storage (initializer corre solo en mount)", () => {
    // Documentado en el comentario del hook. Test asegura que el
    // comportamiento sea EL DOCUMENTADO, no el deseado: cambiar `key` no
    // re-lee. Si futuros mantenedores intentan parametrizar la key, este
    // test los avisa de la trampa.
    sessionStorage.setItem("test:a", JSON.stringify("valor-a"));
    sessionStorage.setItem("test:b", JSON.stringify("valor-b"));

    const { result, rerender } = renderHook(
      ({ k }) => useStoredState(k, "default"),
      { initialProps: { k: "test:a" } },
    );
    expect(result.current[0]).toBe("valor-a");

    // Cambiar key — el state NO se actualiza al valor de la nueva key.
    rerender({ k: "test:b" });
    expect(result.current[0]).toBe("valor-a");

    // Peor: el effect sobreescribe sessionStorage["test:b"] con "valor-a".
    expect(sessionStorage.getItem("test:b")).toBe(JSON.stringify("valor-a"));
  });
});
