/** Espejo frontend de `backend/tipos_pedido.py` — mismos valores, mismos
 *  predicados. Ítems/fechas de un pedido del Estudio se editan desde
 *  Admin → Estudio → Reservas (server-side 409, acá solo evitamos que el
 *  admin intente y choque con eso). Un pedido de taller (Fase 1, #1308) está
 *  blindado igual en fecha/ítem-auto, pero SÍ permite agregar una línea
 *  nueva (matrícula) — ver el comentario de `TIPOS_DERIVADOS` en el backend
 *  para el detalle de qué diverge entre estudio y taller. */
export const TIPOS_ESTUDIO = ["estudio", "estudio_fijo"] as const;

/** Pedido DERIVADO: `fecha_desde`/`fecha_hasta` NO representan un evento real
 *  de un día puntual — superset de `TIPOS_ESTUDIO` + `taller` (mes calendario
 *  completo de la edición). */
export const TIPOS_DERIVADOS = [...TIPOS_ESTUDIO, "taller"] as const;

export function esPedidoEstudio(p: { tipo?: string | null }): boolean {
  return !!p.tipo && (TIPOS_ESTUDIO as readonly string[]).includes(p.tipo);
}

export function esPedidoDerivado(p: { tipo?: string | null }): boolean {
  return !!p.tipo && (TIPOS_DERIVADOS as readonly string[]).includes(p.tipo);
}

export function esPedidoTaller(p: { tipo?: string | null }): boolean {
  return p.tipo === "taller";
}
