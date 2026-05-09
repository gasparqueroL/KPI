import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { ToastProvider, useToast } from "./Toast";

// Componente de prueba: dispara push() con la config que cada test pase.
function Disparador({ mensaje, tipo, duracion }) {
  const { push } = useToast();
  return (
    <button
      onClick={() => {
        if (duracion !== undefined) push(mensaje, tipo, duracion);
        else if (tipo !== undefined) push(mensaje, tipo);
        else push(mensaje);
      }}
    >
      Disparar
    </button>
  );
}

function renderConProvider(props) {
  return render(
    <ToastProvider>
      <Disparador {...props} />
    </ToastProvider>,
  );
}

describe("Toast — push básico", () => {
  it("push muestra el toast con el mensaje", () => {
    renderConProvider({ mensaje: "Guardado OK" });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    expect(screen.queryByText("Guardado OK")).not.toBeNull();
  });

  it("default tipo es 'info' (sin parámetro tipo)", () => {
    renderConProvider({ mensaje: "neutral" });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    const toast = screen.getByText("neutral").closest(".toast");
    expect(toast.className).toContain("toast-info");
  });

  it("tipo custom aplica className correspondiente", () => {
    renderConProvider({ mensaje: "ok", tipo: "success" });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    const toast = screen.getByText("ok").closest(".toast");
    expect(toast.className).toContain("toast-success");
  });
});

describe("Toast — accesibilidad", () => {
  it("error usa role='alert' (anuncia inmediato a screen readers)", () => {
    renderConProvider({ mensaje: "Falló", tipo: "error" });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    // role=alert → screen reader interrumpe lo que esté leyendo y anuncia.
    expect(screen.getByRole("alert").textContent).toBe("Falló");
  });

  it("info / success / warn usan role='status' (anuncio educado)", () => {
    renderConProvider({ mensaje: "ok", tipo: "success" });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    // role=status no interrumpe — el SR lo lee cuando termina lo actual.
    expect(screen.getByRole("status").textContent).toBe("ok");
  });
});

describe("Toast — auto-dismiss", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("se auto-elimina después de 3000ms (default)", () => {
    renderConProvider({ mensaje: "temporal" });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    expect(screen.queryByText("temporal")).not.toBeNull();

    // Justo antes del cierre — sigue visible.
    act(() => {
      vi.advanceTimersByTime(2999);
    });
    expect(screen.queryByText("temporal")).not.toBeNull();

    // Pasa el tiempo total → se elimina.
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByText("temporal")).toBeNull();
  });

  it("respeta duracion custom (5000ms)", () => {
    renderConProvider({ mensaje: "largo", tipo: "info", duracion: 5000 });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));

    act(() => vi.advanceTimersByTime(3000));
    expect(screen.queryByText("largo")).not.toBeNull(); // sigue, default no aplica

    act(() => vi.advanceTimersByTime(2000));
    expect(screen.queryByText("largo")).toBeNull();
  });
});

describe("Toast — stacking", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("múltiples toasts coexisten en stack", () => {
    function Multi() {
      const { push } = useToast();
      return (
        <>
          <button onClick={() => push("Primero")}>P1</button>
          <button onClick={() => push("Segundo", "error")}>P2</button>
          <button onClick={() => push("Tercero", "success")}>P3</button>
        </>
      );
    }
    render(<ToastProvider><Multi /></ToastProvider>);

    fireEvent.click(screen.getByRole("button", { name: /^P1$/ }));
    fireEvent.click(screen.getByRole("button", { name: /^P2$/ }));
    fireEvent.click(screen.getByRole("button", { name: /^P3$/ }));

    expect(screen.queryByText("Primero")).not.toBeNull();
    expect(screen.queryByText("Segundo")).not.toBeNull();
    expect(screen.queryByText("Tercero")).not.toBeNull();
  });

  it("cada toast se elimina independiente según su propio timer", () => {
    function Multi() {
      const { push } = useToast();
      return (
        <>
          <button onClick={() => push("Corto", "info", 1000)}>C</button>
          <button onClick={() => push("Largo", "info", 5000)}>L</button>
        </>
      );
    }
    render(<ToastProvider><Multi /></ToastProvider>);

    fireEvent.click(screen.getByRole("button", { name: /^C$/ }));
    fireEvent.click(screen.getByRole("button", { name: /^L$/ }));

    // Ambos visibles inicialmente.
    expect(screen.queryByText("Corto")).not.toBeNull();
    expect(screen.queryByText("Largo")).not.toBeNull();

    // 1s → se va Corto, queda Largo.
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.queryByText("Corto")).toBeNull();
    expect(screen.queryByText("Largo")).not.toBeNull();

    // 4s más → se va Largo.
    act(() => vi.advanceTimersByTime(4000));
    expect(screen.queryByText("Largo")).toBeNull();
  });
});

describe("Toast — cleanup en unmount", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("unmount cancela timers pendientes (no setState post-unmount)", () => {
    // Si el provider se desmonta antes de que los timers disparen, el
    // mountedRef + clearTimeout previenen el setState — sino React
    // tiraría warning "Can't perform setState on unmounted component".
    const consoleErr = vi.spyOn(console, "error").mockImplementation(() => {});

    const { unmount } = render(
      <ToastProvider>
        <Disparador mensaje="x" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));

    // Desmontar inmediatamente.
    unmount();

    // Avanzar timers — no debería setear state ni warn.
    act(() => vi.advanceTimersByTime(10_000));

    // No warnings sobre setState en unmounted.
    const llamadas = consoleErr.mock.calls.map((c) => c.join(" "));
    const warnsSetState = llamadas.filter((l) =>
      l.includes("unmounted") || l.includes("memory leak"),
    );
    expect(warnsSetState).toHaveLength(0);
    consoleErr.mockRestore();
  });
});

describe("Toast — useToast sin provider", () => {
  it("retorna default context con push noop (no crashea)", () => {
    // Defensa: si alguien usa useToast sin ToastProvider, no debe crashear.
    // El default tiene `push: () => {}` — el toast no aparece pero el
    // caller (que probablemente está testeando algo distinto) sigue.
    const { container } = render(<Disparador mensaje="x" />);
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    // No hay toast renderizado.
    expect(container.querySelector(".toast")).toBeNull();
    // Sin crash es la garantía.
  });
});
