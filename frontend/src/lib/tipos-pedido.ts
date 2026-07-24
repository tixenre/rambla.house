/** Espejo frontend de `backend/tipos_pedido.py` — mismo predicado, mismos
 *  valores. Ítems/fechas de un pedido del Estudio se editan desde
 *  Admin → Estudio → Reservas (Fase 1 del #1283 los bloquea server-side con
 *  409; acá solo evitamos que el admin intente y choque con eso). */
export const TIPOS_ESTUDIO = ["estudio", "estudio_fijo"] as const;

export function esPedidoEstudio(p: { tipo?: string | null }): boolean {
  return !!p.tipo && (TIPOS_ESTUDIO as readonly string[]).includes(p.tipo);
}
