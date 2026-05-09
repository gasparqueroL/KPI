import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../api/client", () => ({
  default: { post: vi.fn(), get: vi.fn() },
  fmtNum: (n) => String(n),
}));
vi.mock("../components/Toast", () => ({
  useToast: () => ({ push: vi.fn() }),
}));

import api from "../api/client";
import Importar from "./Importar";

afterEach(() => {
  vi.mocked(api.post).mockReset();
});

describe("Importar (página /importar)", () => {
  it("renderiza dropzone y mensaje inicial", () => {
    render(<Importar />);
    expect(screen.getByText(/Importar CSV/i)).toBeTruthy();
    expect(screen.getByText(/Arrastrá tus CSV/i)).toBeTruthy();
  });

  it("muestra resumen de archivos seleccionados antes de importar", () => {
    render(<Importar />);
    const file = new File(["periodo,codigo\n2026-04,nps"], "test.csv", { type: "text/csv" });
    const input = document.querySelector('input[type="file"]');
    fireEvent.change(input, { target: { files: [file] } });
    expect(screen.getByText(/Archivos a importar/i)).toBeTruthy();
    expect(screen.getByText(/test\.csv/i)).toBeTruthy();
  });

  it("import exitoso muestra resultado con tipo detectado", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      data: {
        tipo_detectado: "movimientos_caja",
        aceptados: 10, ya_existian: 0, rechazados_count: 0,
        cajas_creadas: [], categorias_creadas: [],
      },
    });
    render(<Importar />);
    const file = new File(["periodo,codigo\n2026-04,nps"], "ok.csv", { type: "text/csv" });
    const input = document.querySelector('input[type="file"]');
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByText("Importar"));
    await waitFor(() => {
      expect(screen.getByText(/movimientos_caja/i)).toBeTruthy();
    });
  });

  it("import con error muestra mensaje", async () => {
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Encoding inválido" } },
    });
    render(<Importar />);
    const file = new File(["bad"], "fail.csv", { type: "text/csv" });
    const input = document.querySelector('input[type="file"]');
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByText("Importar"));
    await waitFor(() => {
      expect(screen.getByText(/Encoding inválido/i)).toBeTruthy();
    });
  });
});
