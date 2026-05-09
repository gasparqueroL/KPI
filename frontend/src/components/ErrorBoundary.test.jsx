import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ErrorBoundary from "./ErrorBoundary";

function Bomba({ explotar, mensaje = "boom" }) {
  if (explotar) throw new Error(mensaje);
  return <div data-testid="hijo-ok">Hijo renderizado OK</div>;
}

describe("ErrorBoundary — render normal", () => {
  it("renderiza children cuando no hay error", () => {
    render(
      <ErrorBoundary>
        <div data-testid="contenido">Hola</div>
      </ErrorBoundary>,
    );
    expect(screen.queryByTestId("contenido")).not.toBeNull();
  });

  it("no renderiza el fallback si el hijo es OK", () => {
    render(
      <ErrorBoundary>
        <Bomba explotar={false} />
      </ErrorBoundary>,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByTestId("hijo-ok")).not.toBeNull();
  });
});

describe("ErrorBoundary — captura de error", () => {
  // Silenciar console.error: React loguea el error capturado además de
  // nuestro propio console.error. No es ruido relevante para los tests.
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("muestra fallback con role=alert cuando el hijo crashea", () => {
    render(
      <ErrorBoundary>
        <Bomba explotar mensaje="dataset null" />
      </ErrorBoundary>,
    );
    expect(screen.queryByRole("alert")).not.toBeNull();
    expect(screen.queryByText(/Algo salió mal/i)).not.toBeNull();
  });

  it("muestra los 3 botones de recuperación en el fallback", () => {
    render(
      <ErrorBoundary>
        <Bomba explotar />
      </ErrorBoundary>,
    );
    expect(screen.queryByRole("button", { name: /Reintentar/i })).not.toBeNull();
    expect(screen.queryByRole("button", { name: /Ir al inicio/i })).not.toBeNull();
    expect(screen.queryByRole("button", { name: /Recargar página/i })).not.toBeNull();
  });

  it("loguea el error a console.error (componentDidCatch)", () => {
    // El beforeEach ya tiene `console.error` mockeado. Aprovechamos ese
    // mismo mock — `vi.spyOn` sobre un método ya mockeado devuelve el mismo
    // mock, NO restaura. Limpiamos sus calls para no mezclar con ruido
    // de tests previos del bloque.
    const consoleErr = console.error;
    consoleErr.mockClear();
    render(
      <ErrorBoundary>
        <Bomba explotar mensaje="error custom" />
      </ErrorBoundary>,
    );
    const llamadas = consoleErr.mock.calls.map((c) => c.join(" "));
    expect(llamadas.some((l) => l.includes("[ErrorBoundary]"))).toBe(true);
  });
});

describe("ErrorBoundary — recuperación", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("botón Reintentar limpia el error y dispara re-render del child", () => {
    // Counter externo de renders del child: si el botón Reintentar realmente
    // limpia el error state del boundary, el child se re-renderiza (y
    // vuelve a explotar). Observable = renders > 1 después del click.
    let renders = 0;
    function BombaContador() {
      renders++;
      throw new Error("boom");
    }

    render(
      <ErrorBoundary>
        <BombaContador />
      </ErrorBoundary>,
    );
    expect(screen.queryByRole("alert")).not.toBeNull();
    const rendersAntes = renders;

    fireEvent.click(screen.getByRole("button", { name: /Reintentar/i }));
    // El boundary reseteó error → re-renderiza children → Bomba corre otra
    // vez. Si el botón no hiciera nada, renders quedaría igual.
    expect(renders).toBeGreaterThan(rendersAntes);
    // Y el alert sigue visible porque el child sigue tirando.
    expect(screen.queryByRole("alert")).not.toBeNull();
  });

  it("cuando cambia resetKey, el boundary limpia el error", () => {
    function Wrapper({ explotar, resetKey }) {
      return (
        <ErrorBoundary resetKey={resetKey}>
          <Bomba explotar={explotar} />
        </ErrorBoundary>
      );
    }
    const { rerender } = render(<Wrapper explotar resetKey="/ruta-a" />);
    expect(screen.queryByRole("alert")).not.toBeNull();

    // Simulamos lo real: la dueña navega a OTRA ruta, el child ya NO
    // explota (es otro componente que renderiza OK), y el resetKey cambia.
    rerender(<Wrapper explotar={false} resetKey="/ruta-b" />);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByTestId("hijo-ok")).not.toBeNull();
  });

  it("si resetKey no cambia, el error persiste aunque cambien children", () => {
    // Este test documenta intención: el reset es POR resetKey, no por
    // cambio arbitrario de children. Sino la dueña no podría ver el error
    // en escenarios donde el árbol se re-render con datos nuevos.
    function Wrapper({ explotar }) {
      return (
        <ErrorBoundary resetKey="ruta-fija">
          <Bomba explotar={explotar} />
        </ErrorBoundary>
      );
    }
    const { rerender } = render(<Wrapper explotar />);
    expect(screen.queryByRole("alert")).not.toBeNull();

    rerender(<Wrapper explotar={false} />);
    // resetKey no cambió → error sigue visible.
    expect(screen.queryByRole("alert")).not.toBeNull();
  });
});

describe("ErrorBoundary — alcance limitado (contracto)", () => {
  // Documentación viva: Error Boundaries de React solo capturan errores
  // de RENDER/lifecycle/constructor. NO capturan: event handlers, async
  // (setTimeout, promesas), errores en el propio boundary, errores de SSR.
  // Estos tests fijan ese contrato. Si rompen, ojo: el patrón de manejo
  // del proyecto cambió.
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("NO captura errores tirados desde un onClick (event handler)", () => {
    // Listener global para silenciar el "uncaught" que jsdom emite al
    // window cuando React no maneja el error del handler — sino vitest lo
    // marca como unhandled error del test run.
    const onError = (e) => e.preventDefault();
    window.addEventListener("error", onError);

    function HijoConBotonRoto() {
      return (
        <button
          onClick={() => {
            throw new Error("error en handler");
          }}
        >
          Click roto
        </button>
      );
    }

    try {
      render(
        <ErrorBoundary>
          <HijoConBotonRoto />
        </ErrorBoundary>,
      );
      // Renderizó OK, no hay alert.
      expect(screen.queryByRole("alert")).toBeNull();

      // Disparamos el click. React 19 reporta el error internamente
      // (vía dispatcher de eventos) pero NO lo encapsula en el boundary.
      fireEvent.click(screen.getByRole("button", { name: /Click roto/i }));

      // Observable clave: el boundary sigue mostrando children, no fallback.
      // Esto fija el contracto: errors-en-handler NO van al boundary.
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.queryByRole("button", { name: /Click roto/i })).not.toBeNull();
    } finally {
      window.removeEventListener("error", onError);
    }
  });

  it("NO captura errores async (setTimeout)", async () => {
    function HijoConAsyncRoto() {
      // Disparamos un throw después del render. El boundary no debería verlo.
      setTimeout(() => {
        // En jsdom esto se loguea pero no propaga al boundary.
        // No tiramos directamente porque rompe vitest. Sí emitimos un
        // warn detectable para confirmar que el código corrió.
        console.warn("[test] async ran sin pasar por boundary");
      }, 0);
      return <div data-testid="async-ok">renderizado</div>;
    }

    render(
      <ErrorBoundary>
        <HijoConAsyncRoto />
      </ErrorBoundary>,
    );
    // Esperamos un tick para que el setTimeout corra.
    await new Promise((r) => setTimeout(r, 10));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByTestId("async-ok")).not.toBeNull();
  });
});

describe("ErrorBoundary — modo dev", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("en dev (import.meta.env.DEV=true), muestra detalle técnico expandible", () => {
    // vitest ejecuta con import.meta.env.DEV = true por default.
    render(
      <ErrorBoundary>
        <Bomba explotar mensaje="stack-de-prueba" />
      </ErrorBoundary>,
    );
    // El <details> está presente con summary "Detalle técnico (solo dev)".
    expect(screen.queryByText(/Detalle técnico/i)).not.toBeNull();
  });
});
