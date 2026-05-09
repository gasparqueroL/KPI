import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render } from "@testing-library/react";
import ApiErrorBridge from "./ApiErrorBridge";
import { ToastProvider } from "./Toast";
import { API_ERROR_EVENT } from "../api/client";

// Helper: dispara el CustomEvent que normalmente emite el interceptor de axios.
function emitirError(payload) {
  window.dispatchEvent(new CustomEvent(API_ERROR_EVENT, { detail: payload }));
}

// Renderiza ApiErrorBridge dentro de ToastProvider real (testeamos integración).
// `pushSpy` se inyecta vía mock de useToast — pero como ApiErrorBridge llama
// `toast.push`, la forma más simple es contar las DOM appearances de toasts.
function renderConToast() {
  return render(
    <ToastProvider>
      <ApiErrorBridge />
    </ToastProvider>,
  );
}

describe("ApiErrorBridge — push básico", () => {
  it("evento con payload válido dispara toast de tipo error", () => {
    const { container } = renderConToast();
    act(() => {
      emitirError({ mensaje: "Backend caído", status: 503 });
    });
    // Hay un toast en el stack con la clase toast-error.
    const toast = container.querySelector(".toast-error");
    expect(toast).not.toBeNull();
    expect(toast.textContent).toBe("Backend caído");
  });

  it("payload SIN mensaje no dispara toast (defensivo)", () => {
    const { container } = renderConToast();
    act(() => {
      emitirError({ status: 500 }); // sin mensaje
    });
    expect(container.querySelector(".toast")).toBeNull();
  });

  it("payload null/undefined no dispara toast", () => {
    const { container } = renderConToast();
    act(() => {
      emitirError(null);
    });
    expect(container.querySelector(".toast")).toBeNull();
  });

  it("payload formato VIEJO (string directo) sigue funcionando — backward compat", () => {
    const { container } = renderConToast();
    act(() => {
      emitirError("Mensaje legacy"); // string suelto, no objeto
    });
    const toast = container.querySelector(".toast-error");
    expect(toast).not.toBeNull();
    expect(toast.textContent).toBe("Mensaje legacy");
  });
});

describe("ApiErrorBridge — coalescing por status (1.5s)", () => {
  // ApiErrorBridge usa `Date.now()` para comparar timestamps. `vi.advanceTimersByTime`
  // adelanta timers internos pero NO mueve `Date.now()` por default en todas
  // las configuraciones. Usamos `vi.setSystemTime(date)` explícito que SÍ
  // lo mockea — los tests son determinísticos independiente del config de
  // fakeTimers del proyecto.
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-08T10:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("dos errores con MISMO status dentro de 1.5s → solo UN toast", () => {
    const { container } = renderConToast();
    act(() => {
      emitirError({ mensaje: "404 endpoint A", status: 404 });
    });
    // 500ms después.
    vi.setSystemTime(new Date("2026-05-08T10:00:00.500Z"));
    act(() => {
      emitirError({ mensaje: "404 endpoint B", status: 404 });
    });

    // Solo el primero (mensaje del A) está renderizado.
    const toasts = container.querySelectorAll(".toast-error");
    expect(toasts).toHaveLength(1);
    expect(toasts[0].textContent).toBe("404 endpoint A");
  });

  it("mismo status DESPUÉS de 1.5s → segundo toast SÍ aparece", () => {
    const { container } = renderConToast();
    act(() => {
      emitirError({ mensaje: "Primer 503", status: 503 });
    });
    // 1600ms después.
    vi.setSystemTime(new Date("2026-05-08T10:00:01.600Z"));
    act(() => {
      emitirError({ mensaje: "Segundo 503", status: 503 });
    });

    const toasts = container.querySelectorAll(".toast-error");
    expect(toasts).toHaveLength(2);
    expect(toasts[0].textContent).toBe("Primer 503");
    expect(toasts[1].textContent).toBe("Segundo 503");
  });

  it("DIFERENTE status dentro de 1.5s → segundo toast aparece (no se coalesca)", () => {
    const { container } = renderConToast();
    act(() => emitirError({ mensaje: "Error 404", status: 404 }));
    vi.setSystemTime(new Date("2026-05-08T10:00:00.200Z"));
    act(() => emitirError({ mensaje: "Error 500", status: 500 }));

    // Ambos toasts visibles (status distintos no se coalescan).
    const toasts = container.querySelectorAll(".toast-error");
    expect(toasts).toHaveLength(2);
  });

  it("formato viejo (string) coalesca como status=null entre sí", () => {
    const { container } = renderConToast();
    act(() => emitirError("error 1"));
    vi.setSystemTime(new Date("2026-05-08T10:00:00.200Z"));
    act(() => emitirError("error 2"));

    const toasts = container.querySelectorAll(".toast-error");
    expect(toasts).toHaveLength(1);
    expect(toasts[0].textContent).toBe("error 1");
  });

  it("formato viejo (status=null) NO coalesce con formato nuevo de status concreto", () => {
    const { container } = renderConToast();
    act(() => emitirError("error legacy"));
    vi.setSystemTime(new Date("2026-05-08T10:00:00.200Z"));
    act(() => emitirError({ mensaje: "error 503", status: 503 }));

    // Status distintos (null vs 503) → ambos pasan.
    const toasts = container.querySelectorAll(".toast-error");
    expect(toasts).toHaveLength(2);
  });
});

describe("ApiErrorBridge — cleanup", () => {
  it("unmount remueve el listener (no dispara toast después)", () => {
    const { container, unmount } = renderConToast();
    unmount();

    // Tras unmount, el evento no debe causar nada (listener removido).
    // Renderizamos un nuevo provider para tener un container donde inspeccionar.
    const { container: container2 } = render(<ToastProvider />);
    act(() => {
      emitirError({ mensaje: "post-unmount", status: 500 });
    });

    // No hay toast en el container original (desmontado) ni en el nuevo
    // (que no tiene ApiErrorBridge).
    expect(container.querySelector(".toast")).toBeNull();
    expect(container2.querySelector(".toast")).toBeNull();
  });
});
