// Id sintético para una clase todavía no guardada (recién agregada, o copiada
// de una edición anterior) — el id real de Postgres es SERIAL (siempre
// positivo), así que un negativo nunca puede chocar. Sirve de identidad
// estable para React (`key`) y dnd-kit (`useSortable({id})`) ANTES del primer
// guardado; el backend lo ignora tal cual (una clase sin id real conocido cae
// siempre por la rama INSERT de `_upsert_clases`, sin leer `id`). Solo
// necesita ser único en esta sesión de browser, no persiste entre reloads.
let seq = -1;

export function nextDraftId(): number {
  return seq--;
}
