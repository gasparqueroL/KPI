import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState as reactUseState } from "react";

vi.mock("../api/client", () => ({
  default: { get: vi.fn(), post: vi.fn() },
  fmtNum: (n) => String(n),
}));
vi.mock("../api/csvExport", () => ({
  descargarComoCSV: vi.fn(),
}));
vi.mock("../components/ConfirmDialog", () => ({
  useConfirm: () => async () => true,
}));
vi.mock("../components/Toast", () => ({
  useToast: () => ({ push: vi.fn() }),
}));
vi.mock("../components/Icon", () => ({
  default: () => null,
}));
vi.mock("../hooks/useStoredState", () => ({
  // useStoredState con import estático (no `require` que rompe ESM/Vitest).
  useStoredState: (key, defaultValue) => reactUseState(defaultValue),
}));

import api from "../api/client";
import CasosRevisar from "./CasosRevisar";

afterEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
});

describe("CasosRevisar (página /casos)", () => {
  it("renderiza título y carga resumen + casos al mount", async () => {
    vi.mocked(api.get).mockImplementation((url) => {
      if (url.includes("/resumen")) {
        return Promise.resolve({
          data: {
            total: 5, archivados: 0,
            por_estado: { pendiente: 5, descartado: 0, corregido: 0 },
            agrupado: [],
          },
        });
      }
      return Promise.resolve({ data: { total: 5, items: [] } });
    });
    render(<CasosRevisar />);
    expect(screen.getByText(/Casos a revisar/i)).toBeTruthy();
    await waitFor(() => {
      // Card de pendientes con valor 5
      expect(screen.getByText(/Pendientes/i)).toBeTruthy();
    });
  });

  it("toggle 'Ver archivados' cambia los params del fetch", async () => {
    let llamadasGetCasos = [];
    vi.mocked(api.get).mockImplementation((url, opts) => {
      if (url === "/api/casos-revisar") {
        llamadasGetCasos.push(opts?.params || {});
      }
      if (url.includes("/resumen")) {
        return Promise.resolve({
          data: { total: 0, archivados: 3, por_estado: {}, agrupado: [] },
        });
      }
      return Promise.resolve({ data: { total: 0, items: [] } });
    });
    render(<CasosRevisar />);
    await waitFor(() => screen.getByText(/Ver archivados/i));

    // Click el toggle. El input checkbox es sibling del label de texto.
    const checkboxes = document.querySelectorAll('input[type="checkbox"]');
    const toggleArchivados = [...checkboxes].find(
      (cb) => cb.parentElement?.textContent?.includes("Ver archivados"),
    );
    expect(toggleArchivados).toBeTruthy();

    // Pre-toggle: solo_archivados NO está en params.
    const llamadasPre = llamadasGetCasos.length;
    fireEvent.click(toggleArchivados);

    // Post-toggle: el último fetch incluye solo_archivados=true.
    await waitFor(() => {
      expect(llamadasGetCasos.length).toBeGreaterThan(llamadasPre);
      const ultima = llamadasGetCasos[llamadasGetCasos.length - 1];
      expect(ultima.solo_archivados).toBe(true);
    });
  });
});
