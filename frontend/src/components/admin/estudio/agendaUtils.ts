import type { EstudioAgendaBloque } from "@/lib/admin/api";

/** Agrupa bloques de `GET /admin/estudio/agenda` por día calendario
 * ("YYYY-MM-DD" de `fecha_desde`) — cada turno/slot/clase vive dentro de un
 * solo día, nunca cruza medianoche. Compartido entre la vista semanal y la
 * mensual: misma fuente, misma agrupación. */
export function agruparBloquesPorDia(
  bloques: EstudioAgendaBloque[],
): Map<string, EstudioAgendaBloque[]> {
  const map = new Map<string, EstudioAgendaBloque[]>();
  for (const b of bloques) {
    const key = b.fecha_desde.slice(0, 10);
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(b);
  }
  return map;
}
