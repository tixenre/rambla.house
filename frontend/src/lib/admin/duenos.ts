/**
 * Lista canónica de dueños posibles para los equipos.
 *
 * El campo `equipos.dueno` antes era texto libre — generaba inconsistencias
 * por capitalización ("Pablo" vs "pablo" vs "PABLO"), espacios, typos.
 * Reportes por dueño quedaban fragmentados (issue #90).
 *
 * Ahora es un set cerrado. El backend tolera valores fuera del set por
 * compat con datos viejos, pero los formularios solo permiten elegir
 * estos. Una migración Alembic normaliza los valores existentes.
 */

export const DUENOS = ["Rental", "Pablo", "Tincho"] as const;
export type Dueno = (typeof DUENOS)[number];

/** Devuelve true si el string ya es un dueño canónico. */
export function isCanonicalDueno(value: string | null | undefined): value is Dueno {
  if (!value) return false;
  return (DUENOS as readonly string[]).includes(value);
}
