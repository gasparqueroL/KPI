import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { ConfirmProvider, useConfirm } from "./ConfirmDialog";

// Componente de prueba que usa el hook y guarda el resultado del confirm
// para que el test lo pueda inspeccionar.
function Disparador({ opciones, onResultado }) {
  const confirm = useConfirm();
  return (
    <button
      onClick={async () => {
        const r = await confirm(opciones);
        onResultado(r);
      }}
    >
      Disparar
    </button>
  );
}

function renderConProvider(props) {
  return render(
    <ConfirmProvider>
      <Disparador {...props} />
    </ConfirmProvider>,
  );
}

describe("ConfirmDialog — flow básico", () => {
  afterEach(() => {
    document.body.style.overflow = "";
  });

  it("click en Aceptar resuelve con true", async () => {
    const onResultado = vi.fn();
    renderConProvider({
      opciones: { mensaje: "¿Borrar?" },
      onResultado,
    });

    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    // El modal se abre con default labels.
    expect(screen.queryByText("¿Borrar?")).not.toBeNull();
    expect(screen.queryByRole("button", { name: /Aceptar/i })).not.toBeNull();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Aceptar/i }));
    });
    expect(onResultado).toHaveBeenCalledWith(true);
  });

  it("click en Cancelar resuelve con false", async () => {
    const onResultado = vi.fn();
    renderConProvider({
      opciones: { mensaje: "¿Seguir?" },
      onResultado,
    });

    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Cancelar/i }));
    });
    expect(onResultado).toHaveBeenCalledWith(false);
  });

  it("Esc cierra y resuelve con false (heredado de Modal)", async () => {
    const onResultado = vi.fn();
    renderConProvider({
      opciones: { mensaje: "x" },
      onResultado,
    });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));

    await act(async () => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(onResultado).toHaveBeenCalledWith(false);
  });

  it("opciones como string usa el string como mensaje (atajo)", async () => {
    renderConProvider({
      opciones: "¿Estás seguro?",
      onResultado: vi.fn(),
    });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    expect(screen.queryByText("¿Estás seguro?")).not.toBeNull();
  });
});

describe("ConfirmDialog — defaults", () => {
  afterEach(() => {
    document.body.style.overflow = "";
  });

  it("titulo default es 'Confirmar'", () => {
    renderConProvider({
      opciones: { mensaje: "x" },
      onResultado: vi.fn(),
    });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    expect(screen.queryByText("Confirmar")).not.toBeNull();
  });

  it("labels default Aceptar / Cancelar", () => {
    renderConProvider({
      opciones: { mensaje: "x" },
      onResultado: vi.fn(),
    });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    expect(screen.queryByRole("button", { name: /^Aceptar$/i })).not.toBeNull();
    expect(screen.queryByRole("button", { name: /^Cancelar$/i })).not.toBeNull();
  });

  it("labels custom override defaults", () => {
    renderConProvider({
      opciones: { mensaje: "x", labelOk: "Borrar", labelCancel: "Volver" },
      onResultado: vi.fn(),
    });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    expect(screen.queryByRole("button", { name: /^Borrar$/i })).not.toBeNull();
    expect(screen.queryByRole("button", { name: /^Volver$/i })).not.toBeNull();
  });

  it("titulo custom override default", () => {
    renderConProvider({
      opciones: { mensaje: "x", titulo: "Eliminar registro" },
      onResultado: vi.fn(),
    });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    expect(screen.queryByText("Eliminar registro")).not.toBeNull();
    expect(screen.queryByText("Confirmar")).toBeNull(); // no aparece el default
  });
});

describe("ConfirmDialog — peligroso", () => {
  afterEach(() => {
    document.body.style.overflow = "";
  });

  it("peligroso=true aplica clase btn-danger al botón OK", () => {
    renderConProvider({
      opciones: { mensaje: "x", peligroso: true, labelOk: "Borrar" },
      onResultado: vi.fn(),
    });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    const btnOk = screen.getByRole("button", { name: /^Borrar$/i });
    expect(btnOk.className).toContain("btn-danger");
  });

  it("peligroso=false (default) NO aplica btn-danger", () => {
    renderConProvider({
      opciones: { mensaje: "x" },
      onResultado: vi.fn(),
    });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    const btnOk = screen.getByRole("button", { name: /^Aceptar$/i });
    expect(btnOk.className).not.toContain("btn-danger");
  });
});

describe("ConfirmDialog — focus al abrir (jurado adversarial)", () => {
  afterEach(() => {
    document.body.style.overflow = "";
  });

  // Decisión de jurado adversarial (ronda autoFocus): la mayoría de los
  // confirms del sistema son destructivos (`peligroso: true`). Para esos,
  // foco en Cancelar es defensivo — la dueña tiene que Tab+Enter para
  // confirmar, minimiza Enter reflejo. ConfirmDialog NO usa autoFocus en
  // Aceptar intencionalmente; el Modal padre hace el focus management.
  //
  // La decisión es UNIFORME — no condicional según peligroso. Tests cubren
  // ambos casos para congelar el comportamiento.

  it("peligroso=false: foco va al primer focusable (Cancelar)", () => {
    renderConProvider({
      opciones: { mensaje: "x" },
      onResultado: vi.fn(),
    });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: /^Cancelar$/i }),
    );
  });

  it("peligroso=true: foco SIGUE en Cancelar (decisión uniforme)", () => {
    renderConProvider({
      opciones: { mensaje: "Borrar?", peligroso: true, labelOk: "Borrar" },
      onResultado: vi.fn(),
    });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: /^Cancelar$/i }),
    );
    // Sanity check: el botón Borrar EXISTE pero NO tiene foco.
    const btnBorrar = screen.getByRole("button", { name: /^Borrar$/i });
    expect(document.activeElement).not.toBe(btnBorrar);
  });

  it("E2E: Enter inmediato post-apertura CANCELA, no acepta (Enter reflejo seguro)", async () => {
    // Test que congela el resultado end-to-end del jurado: la dueña abre
    // un confirm peligroso, presiona Enter por reflejo (sin Tab), y el
    // confirm se RESUELVE CON FALSE — no acepta accidentalmente.
    const onResultado = vi.fn();
    renderConProvider({
      opciones: { mensaje: "Borrar 47 casos?", peligroso: true, labelOk: "Borrar" },
      onResultado,
    });
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));

    // Enter en el botón con foco (Cancelar) → click → responder(false).
    const btnFocado = document.activeElement;
    await act(async () => {
      fireEvent.keyDown(btnFocado, { key: "Enter" });
      // Browsers reales convierten Enter en click en buttons. JSDOM no lo
      // hace automático — disparamos el click explícito que es el efecto
      // observable: si el botón focado fuera Borrar, esto resolvería true.
      fireEvent.click(btnFocado);
    });

    expect(onResultado).toHaveBeenCalledWith(false);
  });
});

describe("ConfirmDialog — cleanup", () => {
  afterEach(() => {
    document.body.style.overflow = "";
  });

  it("provider unmount con confirm pendiente resuelve con false (no leak)", async () => {
    const onResultado = vi.fn();
    const { unmount } = render(
      <ConfirmProvider>
        <Disparador opciones={{ mensaje: "x" }} onResultado={onResultado} />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Disparar/i }));
    // Confirm está pendiente — promise no resolvió todavía.
    expect(onResultado).not.toHaveBeenCalled();

    // Desmontar el provider mientras hay confirm vivo.
    await act(async () => {
      unmount();
    });
    // El cleanup del provider debe resolver el confirm pendiente con false
    // para que el caller (que está awaiting) no quede colgado para siempre.
    expect(onResultado).toHaveBeenCalledWith(false);
  });
});

describe("ConfirmDialog — multiple confirms secuenciales", () => {
  afterEach(() => {
    document.body.style.overflow = "";
  });

  it("dos confirms en secuencia: cada uno resuelve independiente", async () => {
    const resultados = [];
    function Doble() {
      const confirm = useConfirm();
      return (
        <>
          <button
            onClick={async () => resultados.push(await confirm("Primero?"))}
          >
            P1
          </button>
          <button
            onClick={async () => resultados.push(await confirm("Segundo?"))}
          >
            P2
          </button>
        </>
      );
    }
    render(<ConfirmProvider><Doble /></ConfirmProvider>);

    // Primer confirm: aceptar.
    fireEvent.click(screen.getByRole("button", { name: /^P1$/ }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Aceptar$/i }));
    });

    // Segundo confirm: cancelar.
    fireEvent.click(screen.getByRole("button", { name: /^P2$/ }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Cancelar$/i }));
    });

    expect(resultados).toEqual([true, false]);
  });
});
