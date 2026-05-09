import { describe, expect, it } from "vitest";
import { cajaToNormalizado, fmtMoney, fmtNum, fmtPct, urlBackend } from "./client";

describe("fmtMoney — formato AR", () => {
  it("número entero: prefix $ + miles con punto", () => {
    expect(fmtMoney(1234567)).toBe("$1.234.567");
  });

  it("número chico (< 1000) sin separador", () => {
    expect(fmtMoney(123)).toBe("$123");
  });

  it("redondea a 0 decimales (importes operativos sin centavos)", () => {
    expect(fmtMoney(1234.78)).toBe("$1.235");
    expect(fmtMoney(1234.49)).toBe("$1.234");
  });

  it("0 se serializa como $0 (no como string vacío)", () => {
    // Diferencia con fmt_money_ar del backend: el frontend siempre muestra
    // monto. Las celdas vacías son responsabilidad del caller.
    expect(fmtMoney(0)).toBe("$0");
  });

  it("negativo conserva signo (Intl.NumberFormat decide la posición)", () => {
    // Intl es-AR pone el signo `-` ANTES del número: "-1.000"; con prefix
    // del template literal queda "$-1.000". NO es la convención AR Excel
    // ("-$1.000") — discrepancia consciente con el backend, ver fmt_money_ar.
    expect(fmtMoney(-1000)).toBe("$-1.000");
  });

  it("null devuelve '-'", () => {
    expect(fmtMoney(null)).toBe("-");
  });

  it("undefined devuelve '-'", () => {
    expect(fmtMoney(undefined)).toBe("-");
  });

  it("NaN devuelve '-'", () => {
    expect(fmtMoney(NaN)).toBe("-");
  });

  it("string parseable se convierte (defensivo, axios a veces devuelve strings)", () => {
    expect(fmtMoney("1500")).toBe("$1.500");
  });
});

describe("fmtNum — formato AR sin símbolo", () => {
  it("formato AR con miles", () => {
    expect(fmtNum(1234567)).toBe("1.234.567");
  });

  it("0 visible (no vacío)", () => {
    expect(fmtNum(0)).toBe("0");
  });

  it("null/undefined/NaN → '-'", () => {
    expect(fmtNum(null)).toBe("-");
    expect(fmtNum(undefined)).toBe("-");
    expect(fmtNum(NaN)).toBe("-");
  });

  it("decimales se preservan", () => {
    expect(fmtNum(1234.5)).toBe("1.234,5");
  });
});

describe("fmtPct — porcentaje con 1 decimal", () => {
  it("número entero formatea con .0", () => {
    expect(fmtPct(50)).toBe("50.0%");
  });

  it("decimal redondea a 1", () => {
    expect(fmtPct(33.456)).toBe("33.5%");
  });

  it("negativo conserva signo", () => {
    expect(fmtPct(-12.3)).toBe("-12.3%");
  });

  it("0 → 0.0%", () => {
    expect(fmtPct(0)).toBe("0.0%");
  });

  it("null/undefined/NaN → '-'", () => {
    expect(fmtPct(null)).toBe("-");
    expect(fmtPct(undefined)).toBe("-");
    expect(fmtPct(NaN)).toBe("-");
  });
});

describe("cajaToNormalizado", () => {
  const cajas = [
    { nombre_display: "Caja Local", nombre_normalizado: "cl" },
    { nombre_display: "Banco Patagonia", nombre_normalizado: "banco_pat" },
  ];

  it("matchea por nombre_display y devuelve normalizado", () => {
    expect(cajaToNormalizado(cajas, "Caja Local")).toBe("cl");
  });

  it("matchea por nombre_normalizado (idempotente — ya normalizado)", () => {
    expect(cajaToNormalizado(cajas, "cl")).toBe("cl");
  });

  it("no encontrado devuelve el valor crudo (passthrough)", () => {
    // Defensivo: si la dueña agrega caja nueva en otra sesión y el frontend
    // no la conoce todavía, el valor debe pasar tal cual al backend.
    expect(cajaToNormalizado(cajas, "Caja Nueva")).toBe("Caja Nueva");
  });

  it("valor vacío/null/undefined devuelve tal cual (no busca)", () => {
    expect(cajaToNormalizado(cajas, "")).toBe("");
    expect(cajaToNormalizado(cajas, null)).toBe(null);
    expect(cajaToNormalizado(cajas, undefined)).toBe(undefined);
  });

  it("cajas vacío/undefined devuelve valor tal cual (no rompe)", () => {
    expect(cajaToNormalizado([], "Caja Local")).toBe("Caja Local");
    expect(cajaToNormalizado(null, "Caja Local")).toBe("Caja Local");
    expect(cajaToNormalizado(undefined, "Caja Local")).toBe("Caja Local");
  });
});

describe("urlBackend — URL absoluta para downloads", () => {
  // baseURL viene de `import.meta.env.VITE_API_URL ?? "http://localhost:8000"`.
  // En CI o ambientes con VITE_API_URL custom, los tests deben seguir verdes.
  // No mockeamos import.meta.env directamente (es complicado en vitest);
  // las asserts son robustas a cualquier baseURL no-vacía.

  it("path con slash inicial concatena directo (sin doble slash)", () => {
    const url = urlBackend("/api/test.pdf");
    expect(url).toMatch(/\/api\/test\.pdf$/);
    // No hay doble slash entre baseURL y path.
    expect(url).not.toMatch(/\/\/api\/test\.pdf$/);
  });

  it("path sin slash inicial agrega slash (evita concat sin separador)", () => {
    expect(urlBackend("api/test.pdf")).toMatch(/\/api\/test\.pdf$/);
  });

  it("preserva el path tal como se pasó (sin modificaciones intermedias)", () => {
    // Robusto a cualquier baseURL: el path queda intacto al final.
    expect(urlBackend("/api/x?q=1&z=2")).toMatch(/\/api\/x\?q=1&z=2$/);
  });
});
