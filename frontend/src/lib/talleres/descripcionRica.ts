// Formato rico para descripción/público objetivo del TALLER — no confundir
// con el temario de una CLASE (`temario.ts`, deliberadamente más simple: ahí
// CUALQUIER línea no vacía es un punteo uniforme, para no romper contenido
// viejo sin marcar). Acá el contenido típico mezcla prosa corrida con un
// programa estructurado, así que distingue 3 tipos de línea:
// - "# " → título de sección (mismo prefijo que temario.ts, misma idea)
// - "N. " (número + punto) → ítem de lista numerada
// - "· " → sub-ítem, anidado bajo el último numerado abierto
// - cualquier otra línea no vacía → prosa; líneas de prosa consecutivas se
//   funden en UN párrafo (join con espacio)
// Una línea en blanco corta un párrafo en curso, pero NO cierra una lista —
// el programa real trae bloques numerados separados por líneas en blanco
// entre sí (los 6 puntos de "versión extensa", cada uno con sus sub-viñetas)
// y tienen que seguir siendo UNA sola lista, no una por bloque.

export type BloqueDescripcion =
  | { tipo: "titulo"; texto: string }
  | { tipo: "parrafo"; texto: string }
  | { tipo: "lista"; items: { texto: string; subitems: string[] }[] };

const RE_NUMERADO = /^\d+\.\s+(.*)/;
const BULLET_PREFIX = "· ";

export function parseDescripcionRica(texto: string): BloqueDescripcion[] {
  const bloques: BloqueDescripcion[] = [];
  let parrafoActual: string[] = [];
  let listaActual: { texto: string; subitems: string[] }[] | null = null;

  const cerrarParrafo = () => {
    if (parrafoActual.length > 0) {
      bloques.push({ tipo: "parrafo", texto: parrafoActual.join(" ") });
      parrafoActual = [];
    }
  };
  const cerrarLista = () => {
    if (listaActual) {
      bloques.push({ tipo: "lista", items: listaActual });
      listaActual = null;
    }
  };

  for (const raw of texto.split("\n")) {
    const linea = raw.trim();
    if (!linea) {
      cerrarParrafo();
      continue;
    }
    if (linea.startsWith("# ")) {
      cerrarParrafo();
      cerrarLista();
      bloques.push({ tipo: "titulo", texto: linea.slice(2).trim() });
      continue;
    }
    const numerado = RE_NUMERADO.exec(linea);
    if (numerado) {
      cerrarParrafo();
      (listaActual ??= []).push({ texto: numerado[1], subitems: [] });
      continue;
    }
    if (linea.startsWith(BULLET_PREFIX)) {
      cerrarParrafo();
      const sub = linea.slice(BULLET_PREFIX.length).trim();
      const lista = (listaActual ??= []);
      const ultimo = lista[lista.length - 1];
      if (ultimo) ultimo.subitems.push(sub);
      else lista.push({ texto: sub, subitems: [] });
      continue;
    }
    cerrarLista();
    parrafoActual.push(linea);
  }
  cerrarParrafo();
  cerrarLista();
  return bloques;
}
