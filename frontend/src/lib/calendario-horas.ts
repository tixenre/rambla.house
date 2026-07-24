/**
 * Utilidades compartidas para vistas de calendario con eje de horas —
 * `AgendaSemanal` (Estudio) y la vista Semana del Calendario general del
 * Dashboard. Un ítem cuyo fecha_desde/fecha_hasta caen en el MISMO día
 * calendario se puede posicionar por hora (mucho más legible que una barra
 * de un solo día sin horario); uno que cruza días no entra acá — sigue
 * siendo una barra multi-día (la mayoría de los alquileres normales).
 */

/** "2026-07-20T14:00:00" → minutos desde medianoche (840). Slice directo, NO
 *  `Date` — son horas locales "naive" (sin timezone) del backend; pasarlas
 *  por `Date` las reinterpretaría en el timezone del browser. */
export function minutosDelDia(iso: string): number {
  const hh = Number(iso.slice(11, 13));
  const mm = Number(iso.slice(14, 16));
  return hh * 60 + mm;
}

/** ¿fecha_desde y fecha_hasta caen en el mismo día calendario? Si no, el
 *  ítem es multi-día — no tiene sentido posicionarlo por hora. */
export function mismoDiaCalendario(fechaDesde: string, fechaHasta: string): boolean {
  return fechaDesde.slice(0, 10) === fechaHasta.slice(0, 10);
}

export type ConHorario = { fecha_desde: string; fecha_hasta: string };

export type SegmentoHora<T> = {
  item: T;
  carril: number;
  totalCarriles: number;
  top: number;
  height: number;
};

/** Empaquetado greedy simple: si dos ítems del MISMO día se solapan (no
 *  debería pasar con datos válidos — el motor de reservas lo impide para
 *  turnos del Estudio; acá es una red defensiva genérica), se dividen el
 *  ancho de la columna en partes iguales en vez de superponerse ilegibles.
 *  `horaDesde` es el offset (en horas) que corresponde a `top: 0`. */
export function ubicarEnCarriles<T extends ConHorario>(
  items: T[],
  horaDesde: number,
  pxPorHora: number,
): SegmentoHora<T>[] {
  const ordenados = [...items].sort(
    (a, b) => minutosDelDia(a.fecha_desde) - minutosDelDia(b.fecha_desde),
  );
  const finDeCarril: number[] = [];
  const porCarril: T[][] = [];
  for (const it of ordenados) {
    const inicio = minutosDelDia(it.fecha_desde);
    let carril = finDeCarril.findIndex((fin) => fin <= inicio);
    if (carril === -1) {
      carril = finDeCarril.length;
      porCarril.push([]);
    }
    finDeCarril[carril] = Math.max(minutosDelDia(it.fecha_hasta), inicio + 30);
    porCarril[carril].push(it);
  }
  const totalCarriles = porCarril.length || 1;
  return ordenados.map((it) => {
    const carril = porCarril.findIndex((xs) => xs.includes(it));
    const inicio = minutosDelDia(it.fecha_desde) - horaDesde * 60;
    const fin = minutosDelDia(it.fecha_hasta) - horaDesde * 60;
    return {
      item: it,
      carril,
      totalCarriles,
      top: (inicio / 60) * pxPorHora,
      height: Math.max(((fin - inicio) / 60) * pxPorHora, 20),
    };
  });
}
