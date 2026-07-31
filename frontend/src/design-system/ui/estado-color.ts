import type { EstadoPedido } from "./types";

/**
 * Mapa único de color (bg/text/border) + label por estado de pedido — paleta
 * de marca Rambla. Fuente única del repo: `EstadoBadge` la consume para el
 * chip con forma de pill; `estadoClase` la expone para consumidores que
 * necesitan el color SIN esa forma (ej. la barra del calendario admin).
 * Nunca reimplementar este mapeo aparte — un color nuevo entra acá.
 *
 * Separado de `EstadoBadge.tsx` (que solo puede exportar el componente, por
 * Fast Refresh) — mismo patrón que separar un hook de sus componentes.
 */
export const ESTADO_MAP: Record<EstadoPedido, { label: string; cls: string }> = {
  // Ciclo de vida por color (2026-07-14): cada etapa activa tiene su propio color
  // de marca, la progresión "avanza" con el pedido. Borrador (provisorio) y
  // Finalizado (definitivo) se distinguen por PESO — borrador punteado sin fondo,
  // finalizado gris sólido con texto oscuro — antes ambos eran el mismo gris.
  borrador: {
    label: "Borrador",
    cls: "bg-transparent text-muted-foreground border-dashed border-muted-foreground/45",
  },
  // `solicitado` (ex-`presupuesto`, renombrado 2026-07-14): el estado inicial. Se
  // MUESTRA "Solicitud" — el cliente lo solicitó, todavía no es un rental
  // confirmado. El documento PDF sigue llamándose "Presupuesto" (es el papel, no
  // el estado). `entregado` es display del portal (hereda el naranja de retirado).
  solicitado: {
    label: "Solicitud",
    cls: "bg-azul/10 text-azul-ink border-azul/30",
  },
  confirmado: {
    label: "Confirmado",
    cls: "bg-verde/10 text-verde-ink border-verde/30",
  },
  retirado: {
    label: "Retirado",
    cls: "bg-naranja/15 text-naranja-ink border-naranja/45",
  },
  entregado: {
    label: "Entregado",
    cls: "bg-naranja/15 text-naranja-ink border-naranja/45",
  },
  devuelto: {
    label: "Devuelto",
    cls: "bg-rosa/15 text-rosa-ink border-rosa/45",
  },
  finalizado: {
    label: "Finalizado",
    cls: "bg-muted text-ink border-muted-foreground/45",
  },
  cancelado: {
    label: "Cancelado",
    cls: "bg-destructive/10 text-destructive border-destructive/30",
  },
};

/** Clases de color (bg/text/border) del estado — sin la forma de pill. */
export function estadoClase(estado: EstadoPedido | string): string {
  return (ESTADO_MAP[estado as EstadoPedido] ?? ESTADO_MAP.borrador).cls;
}

/** Variante del Estudio para `estadoClase`: en vistas donde un turno del
 *  Estudio conviene distinguirse por marca en vez de por el ciclo de vida
 *  genérico (calendario admin, agenda del Estudio) — dos baldes nomás,
 *  "por venir" (suave) vs. "realizado" (fuerte, `finalizado`); `cancelado`
 *  cae al color universal (no es ninguno de los dos). Usa `--color-estudio`
 *  (no `--color-naranja`, que es el status `retirado` — semántica distinta
 *  aunque comparta hex). Excepción acotada a turnos del Estudio, no
 *  reintroduce theming por área en el resto del back-office. */
export function estadoClaseEstudio(estado: EstadoPedido | string): string {
  if (estado === "cancelado") return estadoClase(estado);
  if (estado === "finalizado") {
    return "bg-[var(--color-estudio)] text-white border-[var(--color-estudio)]";
  }
  return "bg-[var(--color-estudio-soft)] text-[var(--color-estudio)] border-[var(--color-estudio)]/40";
}

/** Solo el color de TEXTO del estado (sin fondo) — para breadcrumbs/timelines
 *  donde el estado se muestra como texto coloreado, no como pill (ej. FlowStrip
 *  del pedido). Mismo criterio de color que `ESTADO_MAP`, una sola fuente. */
export const ESTADO_TEXT: Record<EstadoPedido, string> = {
  borrador: "text-muted-foreground",
  solicitado: "text-azul-ink",
  confirmado: "text-verde-ink",
  retirado: "text-naranja-ink",
  entregado: "text-naranja-ink",
  devuelto: "text-rosa-ink",
  finalizado: "text-muted-foreground",
  cancelado: "text-destructive",
};

/** Solo el color del DOT (fondo sólido) del estado — para puntitos en menús o
 *  leyendas compactas (ej. el menú "Cambiar a otro estado"). */
export const ESTADO_DOT: Record<EstadoPedido, string> = {
  borrador: "bg-muted-foreground/50",
  solicitado: "bg-azul",
  confirmado: "bg-verde",
  retirado: "bg-naranja",
  entregado: "bg-naranja",
  devuelto: "bg-rosa",
  finalizado: "bg-muted-foreground",
  cancelado: "bg-destructive",
};

/** Fondo + borde SÓLIDOS (color pleno) del estado — para marcadores RELLENOS
 *  (ej. el dot de un paso completado/actual en un timeline). El ícono/texto de
 *  adentro va en blanco. Misma fuente de color que `ESTADO_MAP`/`ESTADO_DOT`. */
export const ESTADO_SOLID: Record<EstadoPedido, string> = {
  borrador: "bg-muted-foreground border-muted-foreground",
  solicitado: "bg-azul border-azul",
  confirmado: "bg-verde border-verde",
  retirado: "bg-naranja border-naranja",
  entregado: "bg-naranja border-naranja",
  devuelto: "bg-rosa border-rosa",
  finalizado: "bg-muted-foreground border-muted-foreground",
  cancelado: "bg-destructive border-destructive",
};

/** Ring del color del estado — para resaltar el marcador ACTUAL de un timeline. */
export const ESTADO_RING: Record<EstadoPedido, string> = {
  borrador: "ring-muted-foreground/25",
  solicitado: "ring-azul/25",
  confirmado: "ring-verde/25",
  retirado: "ring-naranja/25",
  entregado: "ring-naranja/25",
  devuelto: "ring-rosa/25",
  finalizado: "ring-muted-foreground/25",
  cancelado: "ring-destructive/25",
};
