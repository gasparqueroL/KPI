/**
 * Export de datos a CSV en el cliente, sin endpoint backend.
 *
 * Features:
 * - Sanitización contra CSV injection (mismo criterio que `_safe_csv_field`
 *   del backend): valores que arrancan con =, +, -, @ o tab se prefijan con
 *   apóstrofo para evitar que Excel/Sheets ejecuten fórmulas. CR y LF se
 *   neutralizan reemplazándolos por espacio (más fuerte que prefijar — no
 *   queremos newlines crudos dentro de celdas porque rompen el parseo).
 * - BOM UTF-8 (﻿) para que Excel detecte encoding correcto.
 * - Separador `;` para que Excel es-AR lo abra en columnas sin "Texto en columnas".
 * - Trigger download automático via blob URL.
 *
 * Arquitectura: lógica pura (sanitizarCampo, construirContenidoCSV) separada
 * del trigger DOM (descargarComoCSV). Lo pure es testeable sin jsdom y
 * exportado para que los tests no dependan de internals.
 */

const PREFIJOS_PELIGROSOS = ["=", "+", "-", "@", "\t"];

const BOM_UTF8 = "﻿";

export function sanitizarCampo(v) {
  if (v == null) return "";
  // CR/LF → espacio: un valor con `\n=cmd` quedaría en una segunda línea
  // que Excel parsearía como fórmula. Hecho ANTES del check de prefijos
  // porque después del replace la cadena ya no arranca con \n/\r.
  let s = String(v).replace(/\r/g, " ").replace(/\n/g, " ");
  if (s && PREFIJOS_PELIGROSOS.includes(s[0])) {
    s = "'" + s;
  }
  // Escapar comillas dobles (RFC 4180) y wrappear si tiene separador o "
  if (s.includes(";") || s.includes('"') || s.includes(",")) {
    s = '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

/**
 * Construye el contenido CSV completo (BOM + header + rows + trailing LF)
 * sin tocar el DOM. Útil para tests y para callers que quieran inyectar
 * el contenido en otro flow (mailto, clipboard, etc).
 *
 * Si `column.format(row)` arroja, capturamos y devolvemos celda vacía +
 * console.warn detallado. Decisión deliberada (jurado adversarial):
 * priorizamos que la dueña obtenga el CSV completo aunque algunas filas
 * tengan datos faltantes (consistente con el patrón `Promise.allSettled`
 * + warn del resto del proyecto). La alternativa (fail-fast) bloquearía
 * el export de 1500 filas por 1 sola con shape inesperado — UX inaceptable.
 * Trade-off: si nadie mira la consola, los format-bugs pasan inadvertidos.
 *
 * @param {Array<{key: string, label?: string, format?: (row) => any}>} columns
 * @param {Array} rows
 * @returns {string} CSV completo, listo para escribir a disco.
 */
export function construirContenidoCSV(columns, rows) {
  const lineas = [];
  lineas.push(columns.map((c) => sanitizarCampo(c.label || c.key)).join(";"));
  for (const r of rows) {
    const linea = columns.map((c) => {
      let val;
      if (c.format) {
        try {
          val = c.format(r);
        } catch (e) {
          console.warn(`[csvExport] format de columna "${c.key}" tiró excepción:`, e, "row:", r);
          val = "";
        }
      } else {
        val = r[c.key];
      }
      return sanitizarCampo(val);
    }).join(";");
    lineas.push(linea);
  }
  return BOM_UTF8 + lineas.join("\n") + "\n";
}

/**
 * Descarga `rows` como archivo CSV.
 * @param {string} filename - nombre del archivo (sin path).
 * @param {Array<{key: string, label: string, num?: boolean, format?: (row) => any}>} columns - definición.
 * @param {Array} rows - datos.
 */
export function descargarComoCSV(filename, columns, rows) {
  const csv = construirContenidoCSV(columns, rows);
  const blob = new Blob([csv], { type: "text/csv; charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Liberar memoria del blob — no es bug si no se hace pero buena práctica.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
