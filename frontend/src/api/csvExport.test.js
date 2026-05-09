import { describe, it, expect } from "vitest";
import { construirContenidoCSV, sanitizarCampo } from "./csvExport";

describe("sanitizarCampo — CSV injection", () => {
  it("prefija con apóstrofo valores que arrancan con = (fórmula Excel)", () => {
    // Solo apostrofes (no comillas dobles), sin separador ni `,` → no se
    // wrappea. El prefix `'` adelante alcanza para neutralizar.
    expect(sanitizarCampo("=cmd|'/c calc'")).toBe("'=cmd|'/c calc'");
  });

  it("prefija + wrappea cuando hay `=` Y comilla doble", () => {
    expect(sanitizarCampo('=HYPERLINK("evil")')).toBe('"\'=HYPERLINK(""evil"")"');
  });

  it("prefija con apóstrofo +, -, @, tab", () => {
    expect(sanitizarCampo("+SUM(A1)")).toBe("'+SUM(A1)");
    expect(sanitizarCampo("-1")).toBe("'-1");
    expect(sanitizarCampo("@import")).toBe("'@import");
    expect(sanitizarCampo("\tWHATEVER")).toBe("'\tWHATEVER");
  });

  it("NO prefija strings que arrancan con caracteres seguros", () => {
    expect(sanitizarCampo("hola")).toBe("hola");
    expect(sanitizarCampo("123")).toBe("123");
    expect(sanitizarCampo("Producto X")).toBe("Producto X");
  });
});

describe("sanitizarCampo — newlines", () => {
  it("reemplaza CR y LF por espacio (no permite newlines en celdas)", () => {
    expect(sanitizarCampo("línea1\nlínea2")).toBe("línea1 línea2");
    expect(sanitizarCampo("línea1\rlínea2")).toBe("línea1 línea2");
    expect(sanitizarCampo("a\r\nb")).toBe("a  b");
  });

  it("CR/LF al inicio se neutralizan ANTES del check de prefijos peligrosos", () => {
    // \n=cmd se convierte en " =cmd" (arranca con espacio, no con =)
    // → no requiere prefix de apóstrofo. Pero como tiene `=` igual no es
    // problema porque el espacio inicial impide que Excel lo evalúe.
    expect(sanitizarCampo("\n=cmd")).toBe(" =cmd");
    expect(sanitizarCampo("\r=cmd")).toBe(" =cmd");
  });
});

describe("sanitizarCampo — RFC 4180 escaping", () => {
  it("wrappea con comillas si contiene separador `;`", () => {
    expect(sanitizarCampo("a;b")).toBe('"a;b"');
  });

  it("wrappea con comillas si contiene `,` (CSV portable)", () => {
    expect(sanitizarCampo("a,b")).toBe('"a,b"');
  });

  it("escapa comillas dobles internas duplicándolas y wrappea", () => {
    expect(sanitizarCampo('hola "mundo"')).toBe('"hola ""mundo"""');
  });

  it("no wrappea strings sin caracteres especiales", () => {
    expect(sanitizarCampo("simple")).toBe("simple");
  });
});

describe("sanitizarCampo — null/undefined/edge", () => {
  it("null → string vacío", () => {
    expect(sanitizarCampo(null)).toBe("");
  });

  it("undefined → string vacío", () => {
    expect(sanitizarCampo(undefined)).toBe("");
  });

  it("string vacío → string vacío (no rompe)", () => {
    expect(sanitizarCampo("")).toBe("");
  });

  it("número se convierte a string", () => {
    expect(sanitizarCampo(1234.56)).toBe("1234.56");
  });

  it("número negativo: el `-` inicial dispara el prefix peligroso", () => {
    // Comportamiento intencional — Excel evalúa -1 como número OK pero
    // -1+CMD podría ser injection. Conservadores: prefijar siempre.
    expect(sanitizarCampo(-42)).toBe("'-42");
  });

  it("0 (falsy pero no null) se serializa como '0'", () => {
    expect(sanitizarCampo(0)).toBe("0");
  });

  it("false (boolean) se serializa como 'false'", () => {
    expect(sanitizarCampo(false)).toBe("false");
  });
});

describe("construirContenidoCSV", () => {
  const BOM = "﻿";

  it("incluye BOM UTF-8 al inicio", () => {
    const csv = construirContenidoCSV([{ key: "a", label: "A" }], []);
    expect(csv.charCodeAt(0)).toBe(0xFEFF);
    expect(csv.startsWith(BOM)).toBe(true);
  });

  it("usa `;` como separador y `\\n` entre líneas", () => {
    const csv = construirContenidoCSV(
      [{ key: "a", label: "A" }, { key: "b", label: "B" }],
      [{ a: "1", b: "2" }, { a: "3", b: "4" }],
    );
    expect(csv).toBe(`${BOM}A;B\n1;2\n3;4\n`);
  });

  it("trailing LF al final del contenido", () => {
    const csv = construirContenidoCSV([{ key: "a", label: "A" }], [{ a: "x" }]);
    expect(csv.endsWith("\n")).toBe(true);
  });

  it("usa label si está, sino key como header", () => {
    const csv = construirContenidoCSV(
      [{ key: "fecha" }, { key: "monto", label: "Total" }],
      [],
    );
    expect(csv).toBe(`${BOM}fecha;Total\n`);
  });

  it("usa columna.format(row) cuando está, sino fallback a row[column.key]", () => {
    const csv = construirContenidoCSV(
      [
        { key: "a", label: "A" },
        { key: "b", label: "B", format: (r) => r.a + r.b },
      ],
      [{ a: 1, b: 2 }],
    );
    expect(csv).toBe(`${BOM}A;B\n1;3\n`);
  });

  it("filas vacías → solo header + LF", () => {
    const csv = construirContenidoCSV([{ key: "a", label: "A" }], []);
    expect(csv).toBe(`${BOM}A\n`);
  });

  it("sanitiza valores en cada celda (no solo en headers)", () => {
    const csv = construirContenidoCSV(
      [{ key: "valor", label: "Valor" }],
      [{ valor: "=HYPERLINK(\"http://evil\")" }],
    );
    // El valor arranca con = → prefix '. Tiene comillas → wrap + escape.
    expect(csv).toContain('"\'=HYPERLINK(""http://evil"")"');
  });

  it("celda con `;` queda wrappeada y no rompe estructura", () => {
    const csv = construirContenidoCSV(
      [{ key: "a", label: "A" }, { key: "b", label: "B" }],
      [{ a: "x;y", b: "z" }],
    );
    expect(csv).toBe(`${BOM}A;B\n"x;y";z\n`);
  });

  it("acepta valores null/undefined sin crashear", () => {
    const csv = construirContenidoCSV(
      [{ key: "a", label: "A" }, { key: "b", label: "B" }],
      [{ a: null, b: undefined }],
    );
    expect(csv).toBe(`${BOM}A;B\n;\n`);
  });

  it("formato custom puede devolver null sin romper", () => {
    const csv = construirContenidoCSV(
      [{ key: "x", label: "X", format: () => null }],
      [{ x: "ignored" }],
    );
    expect(csv).toBe(`${BOM}X\n\n`);
  });
});

describe("construirContenidoCSV — format que tira excepción", () => {
  // Decisión adversarial: catch + celda vacía + console.warn (NO fail-fast).
  // Razón: consistencia con allSettled+warn del resto del proyecto y UX
  // de no bloquear export por una sola fila rota.
  it("captura el throw y devuelve celda vacía sin romper otras filas", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const cols = [
      { key: "fecha", label: "Fecha", format: (r) => r.fecha.toISOString() },
      { key: "monto", label: "Monto" },
    ];
    const rows = [
      { fecha: new Date("2026-04-01"), monto: 100 },
      { fecha: null, monto: 200 }, // tira NPE en format
      { fecha: new Date("2026-04-03"), monto: 300 },
    ];
    const csv = construirContenidoCSV(cols, rows);

    // La fila rota tiene celda vacía en "fecha" pero monto se exporta OK.
    const lineas = csv.split("\n");
    expect(lineas[2]).toBe(";200"); // fila 2: fecha vacía, monto OK
    // Las otras filas no se ven afectadas.
    expect(lineas[1]).toBe("2026-04-01T00:00:00.000Z;100");
    expect(lineas[3]).toBe("2026-04-03T00:00:00.000Z;300");

    warn.mockRestore();
  });

  it("loguea warn detallado con key de columna y row afectada", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const cols = [{ key: "x", label: "X", format: () => { throw new Error("boom"); } }];
    construirContenidoCSV(cols, [{ x: "a" }]);

    expect(warn).toHaveBeenCalled();
    const llamadas = warn.mock.calls.map((c) => c.join(" "));
    // El warn menciona el key de la columna afectada y el prefix del módulo.
    expect(llamadas.some((l) => l.includes("[csvExport]") && l.includes('"x"'))).toBe(true);
    warn.mockRestore();
  });

  it("una columna rota NO impide que se exporten las otras columnas de la misma fila", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const cols = [
      { key: "a", label: "A" },
      { key: "b", label: "B", format: () => { throw new Error("ups"); } },
      { key: "c", label: "C" },
    ];
    const csv = construirContenidoCSV(cols, [{ a: "1", b: "2", c: "3" }]);
    const lineas = csv.split("\n");
    expect(lineas[1]).toBe("1;;3");
    warn.mockRestore();
  });
});
