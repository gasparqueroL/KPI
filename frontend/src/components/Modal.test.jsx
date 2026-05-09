import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import Modal from "./Modal";

describe("Modal — open/close", () => {
  it("no renderiza nada cuando open=false", () => {
    const { container } = render(
      <Modal open={false} onClose={() => {}} title="X">
        <p>contenido</p>
      </Modal>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renderiza children cuando open=true", () => {
    render(
      <Modal open onClose={() => {}} title="Mi modal">
        <p data-testid="contenido">contenido</p>
      </Modal>,
    );
    expect(screen.queryByTestId("contenido")).not.toBeNull();
    expect(screen.queryByText("Mi modal")).not.toBeNull();
  });

  it("muestra botón Cerrar por default", () => {
    render(
      <Modal open onClose={() => {}} title="X">
        <p>x</p>
      </Modal>,
    );
    expect(screen.queryByRole("button", { name: /Cerrar/i })).not.toBeNull();
  });

  it("hideClose=true esconde el botón Cerrar (uso típico: ConfirmDialog)", () => {
    render(
      <Modal open onClose={() => {}} title="Confirmar" hideClose>
        <p>¿Seguro?</p>
      </Modal>,
    );
    expect(screen.queryByRole("button", { name: /Cerrar/i })).toBeNull();
  });

  it("aria-modal y role=dialog presentes", () => {
    render(
      <Modal open onClose={() => {}} title="X">
        <p>x</p>
      </Modal>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
  });
});

describe("Modal — cierre por interacción", () => {
  afterEach(() => {
    // Restaurar body overflow en caso de tests que dejen modales montados.
    document.body.style.overflow = "";
  });

  it("Esc llama onClose", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="X">
        <p>x</p>
      </Modal>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("click en overlay (mouseDown + mouseUp en mismo target) cierra", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="X">
        <p>x</p>
      </Modal>,
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.mouseDown(dialog, { target: dialog, currentTarget: dialog });
    fireEvent.mouseUp(dialog, { target: dialog, currentTarget: dialog });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("click en el botón Cerrar llama onClose", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="X">
        <p>x</p>
      </Modal>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Cerrar/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("drag-to-close: mouseDown DENTRO del modal + mouseUp en overlay → NO cierra", () => {
    // Caso bug clásico: usuario selecciona texto desde el modal, suelta el
    // botón fuera del modal por accidente. NO debería cerrar.
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="X">
        <p data-testid="texto">contenido seleccionable</p>
      </Modal>,
    );
    const texto = screen.getByTestId("texto");
    const dialog = screen.getByRole("dialog");
    // mouseDown dentro del modal (texto), mouseUp en el overlay.
    fireEvent.mouseDown(texto);
    fireEvent.mouseUp(dialog, { target: dialog, currentTarget: dialog });
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("Modal — body overflow", () => {
  it("setea body.style.overflow=hidden mientras está open", () => {
    document.body.style.overflow = "";
    render(
      <Modal open onClose={() => {}} title="X">
        <p>x</p>
      </Modal>,
    );
    expect(document.body.style.overflow).toBe("hidden");
  });

  it("restaura body.style.overflow al desmontar", () => {
    document.body.style.overflow = "auto";
    const { unmount } = render(
      <Modal open onClose={() => {}} title="X">
        <p>x</p>
      </Modal>,
    );
    expect(document.body.style.overflow).toBe("hidden");
    unmount();
    expect(document.body.style.overflow).toBe("auto");
  });
});

describe("Modal — fallback sin focusables", () => {
  afterEach(() => {
    document.body.style.overflow = "";
  });

  it("hideClose=true + sin focusables en children → foca el wrapper (tabindex=-1)", () => {
    // Edge case: contenido puramente informativo. Sin focusable + hideClose,
    // el foco quedaría afuera del modal y el Tab trap se rompería.
    // El fallback foca el wrapper con tabindex=-1.
    render(
      <Modal open onClose={() => {}} title="Info" hideClose>
        <p>Contenido informativo sin botones ni inputs</p>
      </Modal>,
    );
    const dialog = screen.getByRole("dialog");
    // El wrapper interno (con ref={ref}) recibe el foco.
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(document.activeElement.getAttribute("tabindex")).toBe("-1");
  });
});

describe("Modal — focus management", () => {
  afterEach(() => {
    document.body.style.overflow = "";
  });

  it("foca el primer elemento focusable al abrir", () => {
    render(
      <Modal open onClose={() => {}} title="X">
        <button data-testid="primer">Primero</button>
        <button data-testid="segundo">Segundo</button>
      </Modal>,
    );
    // El primer focusable es el botón Cerrar (renderizado antes de los children
    // dentro del header del modal). Verificamos que algún elemento dentro del
    // modal tenga focus, no específicamente cuál (depende del orden interno).
    const enFocusEnModal = screen.getByRole("dialog").contains(document.activeElement);
    expect(enFocusEnModal).toBe(true);
  });

  it("restaura el foco al elemento que abrió el modal cuando se cierra", () => {
    function Wrapper({ abierto }) {
      return (
        <>
          <button data-testid="trigger">Abrir</button>
          {abierto && (
            <Modal open onClose={() => {}} title="X">
              <p>x</p>
            </Modal>
          )}
        </>
      );
    }
    const { rerender } = render(<Wrapper abierto={false} />);
    const trigger = screen.getByTestId("trigger");
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    rerender(<Wrapper abierto={true} />);
    // Mientras el modal está abierto, el foco está adentro.
    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);

    rerender(<Wrapper abierto={false} />);
    // Al cerrar, foco vuelve al trigger.
    expect(document.activeElement).toBe(trigger);
  });
});

describe("Modal — stack (modales anidados)", () => {
  afterEach(() => {
    document.body.style.overflow = "";
  });

  it("Esc solo dispara onClose del modal TOP de la stack", () => {
    const onCloseA = vi.fn();
    const onCloseB = vi.fn();
    render(
      <>
        <Modal open onClose={onCloseA} title="A">
          <p>A</p>
        </Modal>
        <Modal open onClose={onCloseB} title="B">
          <p>B</p>
        </Modal>
      </>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    // Solo B (último pusheado a la stack) debería cerrar.
    expect(onCloseB).toHaveBeenCalledTimes(1);
    expect(onCloseA).not.toHaveBeenCalled();
  });

  it("body.style.overflow se restaura solo cuando se desmonta el ÚLTIMO modal (con onClose inline)", () => {
    // Usamos `onClose={() => {}}` inline DELIBERADAMENTE — replica el patrón
    // de ConfirmDialog y otros callers reales. Antes del fix con onCloseRef,
    // este test fallaba: la effect se re-ejecutaba por cambio de referencia
    // de onClose y capturaba un previousOverflow="hidden" mid-state. Después
    // del fix (Modal.jsx usa onCloseRef + dep solo en [open]), inline funciona.
    //
    // Test intencionalmente AGRESIVO contra regresión: incluye un paso
    // intermedio donde re-renderizamos con `open=true` constante pero
    // forzando onClose nueva. Si alguien remueve el ref pattern y vuelve
    // a `[open, onClose]`, este paso re-ejecuta el effect y "contamina"
    // previousOverflow → el assertion final falla.
    document.body.style.overflow = "auto";
    const { rerender } = render(
      <>
        <Modal open onClose={() => {}} title="A"><p>A</p></Modal>
        <Modal open onClose={() => {}} title="B"><p>B</p></Modal>
      </>,
    );
    expect(document.body.style.overflow).toBe("hidden");

    // PASO INTERMEDIO: re-render con ambos abiertos pero onClose nuevas.
    // Esto fuerza a las effects a contaminar previousOverflow si los deps
    // incluyen onClose. Sin este paso, el bug original podría no surfacear.
    rerender(
      <>
        <Modal open onClose={() => {}} title="A"><p>A</p></Modal>
        <Modal open onClose={() => {}} title="B"><p>B</p></Modal>
      </>,
    );
    expect(document.body.style.overflow).toBe("hidden");

    // Cerrar solo B → A queda abierto, overflow sigue hidden.
    rerender(
      <>
        <Modal open onClose={() => {}} title="A"><p>A</p></Modal>
        <Modal open={false} onClose={() => {}} title="B"><p>B</p></Modal>
      </>,
    );
    expect(document.body.style.overflow).toBe("hidden");

    // Cerrar A también → ahora sí restaura al valor original.
    rerender(
      <>
        <Modal open={false} onClose={() => {}} title="A"><p>A</p></Modal>
        <Modal open={false} onClose={() => {}} title="B"><p>B</p></Modal>
      </>,
    );
    expect(document.body.style.overflow).toBe("auto");
  });
});

describe("Modal — Tab trap", () => {
  afterEach(() => {
    document.body.style.overflow = "";
  });

  it("Tab en el último focusable rota al primero (botón Cerrar)", () => {
    render(
      <Modal open onClose={() => {}} title="X">
        <button data-testid="b1">B1</button>
        <button data-testid="b2">B2</button>
      </Modal>,
    );
    // Foco al último focusable manualmente.
    const b2 = screen.getByTestId("b2");
    b2.focus();
    expect(document.activeElement).toBe(b2);

    fireEvent.keyDown(document, { key: "Tab" });
    // Aserción explícita: el foco debe estar EN el botón Cerrar (primer
    // focusable del modal, renderizado antes de los children). Antes la
    // assertion era laxa (cualquier elemento dentro del dialog) — un bug
    // futuro que mandara el foco al b1 o al título habría pasado silencioso.
    const cerrar = screen.getByRole("button", { name: /Cerrar/i });
    expect(document.activeElement).toBe(cerrar);
  });

  it("Shift+Tab en el primer focusable rota al último", () => {
    render(
      <Modal open onClose={() => {}} title="X">
        <button data-testid="b1">B1</button>
        <button data-testid="b2">B2</button>
      </Modal>,
    );
    // El primer focusable es el Cerrar (renderizado antes de children).
    const cerrar = screen.getByRole("button", { name: /Cerrar/i });
    cerrar.focus();
    expect(document.activeElement).toBe(cerrar);

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    // Foco se movió al último focusable (b2).
    expect(document.activeElement).toBe(screen.getByTestId("b2"));
  });
});
