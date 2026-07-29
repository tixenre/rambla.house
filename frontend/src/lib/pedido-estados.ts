/**
 * Tipo canónico de estados de pedido — fuente única para todo el repo.
 *
 * Admin y portal cliente importan desde acá.
 * El orden refleja el ciclo de vida típico de un pedido.
 */
export type EstadoPedido =
  | "borrador"
  | "solicitado"
  | "confirmado"
  | "retirado"
  | "entregado"
  | "devuelto"
  | "finalizado"
  | "cancelado";

/** Label del CTA del "siguiente paso feliz" — compartido entre lista y editor de pedidos. */
export const PEDIDO_NEXT_LABEL: Partial<Record<EstadoPedido, string>> = {
  borrador: "Pasar a solicitud",
  solicitado: "Confirmar pedido",
  confirmado: "Marcar retirado",
  retirado: "Registrar devolución",
  entregado: "Registrar devolución",
  devuelto: "Cobrar saldo y finalizar",
};

// ── Máquina de estados (espeja `routes/alquileres/transiciones.py::TRANSICIONES`
// del backend) ─────────────────────────────────────────────────────────────
// El back-office NO ofrece transiciones que el backend rechazaría. Fuente única
// compartida entre el editor (pedidos.$id) y el panel de detalle (pedidos.index).
//
// Rediseño 2026-07-06 (a pedido del dueño: "puedo volver atrás a modificar los
// pedidos, porque suele pasar"): el admin ahora puede moverse en cualquier
// dirección entre los estados operativos, no solo avanzar — `TRANSICIONES` es
// el grafo COMPLETO (bidireccional), usado para el menú secundario "Cambiar a
// otro estado". El "siguiente paso feliz" (un solo botón primario, sin
// ambigüedad) es un concepto APARTE — ver `SIGUIENTE_PASO` — para no romper
// `nextStep()` al volverse el grafo bidireccional.

/** Secuencia del "camino feliz" para el indicador de progreso (FlowStrip). */
export const FLOW: EstadoPedido[] = [
  "solicitado",
  "confirmado",
  "retirado",
  "devuelto",
  "finalizado",
];

/**
 * Transiciones permitidas por estado (espeja el backend, grafo completo
 * incluyendo retrocesos). `entregado` es un estado de display del portal, no un
 * valor real de `alquileres.estado` — su entrada queda tal cual (nunca se
 * consulta con un `estado` real del editor admin). `solicitado` (ex-`presupuesto`,
 * renombrado 2026-07-14) SÍ es el estado real inicial del pedido.
 */
export const TRANSICIONES: Partial<Record<EstadoPedido, EstadoPedido[]>> = {
  borrador: ["solicitado", "confirmado", "retirado", "devuelto", "cancelado"],
  solicitado: ["borrador", "confirmado", "retirado", "devuelto", "cancelado"],
  confirmado: ["borrador", "solicitado", "retirado", "devuelto", "cancelado"],
  retirado: ["borrador", "solicitado", "confirmado", "devuelto"],
  entregado: ["devuelto", "cancelado"], // estado del portal
  devuelto: ["borrador", "solicitado", "confirmado", "retirado", "finalizado"],
  finalizado: ["devuelto"],
  cancelado: [],
};

export const transiciones = (e: EstadoPedido): EstadoPedido[] => TRANSICIONES[e] ?? [];

/**
 * El "siguiente paso feliz" — un único destino por estado, sin ambigüedad,
 * para el botón primario (`nextStep`). Antes se derivaba de `transiciones()[0]`,
 * lo cual funcionaba solo mientras el grafo era forward-only; con el grafo
 * bidireccional de arriba, `[0]` ya no identifica de forma confiable "el paso
 * de avance" — por eso es una tabla aparte, no derivada.
 */
const SIGUIENTE_PASO: Partial<Record<EstadoPedido, EstadoPedido>> = {
  borrador: "solicitado",
  solicitado: "confirmado",
  confirmado: "retirado",
  retirado: "devuelto",
  entregado: "devuelto",
  devuelto: "finalizado",
};

/** Datos mínimos de un pedido para evaluar bloqueos de transición (evita acoplar al tipo Pedido). */
export type PedidoTransicionable = {
  estado: EstadoPedido;
  fecha_desde?: string | null;
  fecha_hasta?: string | null;
  items?: { length: number } | null;
};

/** Motivo por el que un destino está bloqueado (faltan fechas / sin equipos) — espeja la validación del backend. */
export function blockReason(p: PedidoTransicionable, target: EstadoPedido): string | null {
  const needs: EstadoPedido[] = ["confirmado", "retirado", "devuelto", "finalizado"];
  if (needs.includes(target)) {
    if (!p.fecha_desde || !p.fecha_hasta) return "faltan fechas";
    if (!p.items?.length) return "sin equipos";
  }
  return null;
}

/** Próximo paso "feliz" (el único de `SIGUIENTE_PASO`) + label + motivo de bloqueo; null si es estado terminal. */
export function nextStep(
  p: PedidoTransicionable,
): { target: EstadoPedido; label: string; blocked: string | null } | null {
  const target = SIGUIENTE_PASO[p.estado];
  if (!target) return null;
  return {
    target,
    label: PEDIDO_NEXT_LABEL[p.estado] ?? "Avanzar",
    blocked: blockReason(p, target),
  };
}

/**
 * Otros destinos legales desde `estado`, para el menú secundario "Cambiar a
 * otro estado" — todo lo que `transiciones()` permite MENOS el paso feliz
 * (ya tiene su botón primario) y "cancelado" (tiene su propio botón en "Zona
 * peligrosa"). Ordenado según `FLOW` cuando aplica, para que se lea como una
 * línea de tiempo — los estados fuera de `FLOW` (ninguno hoy) quedarían al final.
 */
export function otrosDestinos(p: PedidoTransicionable): EstadoPedido[] {
  const siguiente = SIGUIENTE_PASO[p.estado];
  const candidatos = transiciones(p.estado).filter((e) => e !== "cancelado" && e !== siguiente);
  return [...candidatos].sort((a, b) => FLOW.indexOf(a) - FLOW.indexOf(b));
}

/**
 * Cómo se identifica un pedido en pantalla. Un BORRADOR no tiene
 * `numero_pedido`: es un presupuesto rápido, no una venta (decisión del dueño)
 * — mostrar su id interno como "#425" lo hacía pasar por un pedido real, que es
 * justamente la confusión que se quiso sacar.
 *
 * Los registros históricos/manuales sin número (que NO son borradores)
 * conservan el fallback de siempre al id — ahí el "#" sigue siendo la mejor
 * referencia disponible.
 */
export function etiquetaPedido(p: {
  id: number;
  numero_pedido?: number | null;
  estado?: string;
}): string {
  if (p.numero_pedido) return `#${p.numero_pedido}`;
  return p.estado === "borrador" ? "Borrador" : `#${p.id}`;
}
