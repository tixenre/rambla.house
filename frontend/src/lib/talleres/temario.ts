// ── Formato básico del temario de una clase (Escuela v2) ────────────────────
// El temario es texto plano línea-por-línea (`clases_taller.descripcion`).
// Convención mínima: una línea que arranca con "# " es un TÍTULO (encabezado
// de sección dentro del temario, no numerado); cualquier otra línea no vacía
// es un PUNTEO (numerado) — el comportamiento de siempre, así que descripciones
// ya guardadas sin marcar nada siguen viéndose exactamente igual. Fuente única:
// ClasesAsistente (admin, toggle de línea) y ClaseCard (público, render) leen
// de acá — no reimplementar el parseo/toggle en ninguno de los dos.

export const TITULO_PREFIX = "# ";

export type LineaTemario = { tipo: "titulo" | "bullet"; texto: string };

/** Parsea el temario crudo a bloques tipados, en orden. Líneas vacías se descartan. */
export function parseTemario(descripcion: string): LineaTemario[] {
  return descripcion
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((linea) =>
      linea.startsWith(TITULO_PREFIX)
        ? { tipo: "titulo" as const, texto: linea.slice(TITULO_PREFIX.length).trim() }
        : { tipo: "bullet" as const, texto: linea },
    );
}

/** Encuentra los límites [inicio, fin) de la línea que contiene `cursor`. */
function limitesDeLinea(texto: string, cursor: number): [number, number] {
  const inicio = texto.lastIndexOf("\n", cursor - 1) + 1;
  const finRel = texto.indexOf("\n", cursor);
  const fin = finRel === -1 ? texto.length : finRel;
  return [inicio, fin];
}

/** Fija el formato de la línea actual (donde está el cursor) a "título" o
 * "bullet" — no un toggle: elegir un formato dos veces seguidas es un no-op,
 * evitando el estado confuso de un toggle clásico. Devuelve el texto nuevo +
 * la posición de cursor a restaurar (compensa el delta de largo del prefijo). */
export function fijarFormatoDeLinea(
  texto: string,
  cursor: number,
  formato: "titulo" | "bullet",
): { texto: string; cursor: number } {
  const [inicio, fin] = limitesDeLinea(texto, cursor);
  const linea = texto.slice(inicio, fin);
  const sinPrefijo = linea.startsWith(TITULO_PREFIX) ? linea.slice(TITULO_PREFIX.length) : linea;
  const nuevaLinea = formato === "titulo" ? TITULO_PREFIX + sinPrefijo : sinPrefijo;
  const nuevoTexto = texto.slice(0, inicio) + nuevaLinea + texto.slice(fin);
  const delta = nuevaLinea.length - linea.length;
  return { texto: nuevoTexto, cursor: Math.max(inicio, cursor + delta) };
}
