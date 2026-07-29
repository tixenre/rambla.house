/**
 * pedido-combinado.ts — total/cobrado combinados de un pedido de alquiler +
 * sus turnos del Estudio vinculados (#1308: "si lo confirman, lo pagan...
 * es parte del pedido" — un solo número, no uno por fila).
 *
 * Cálculo 100% en el frontend, cero query nueva: `monto_total`/`monto_pagado`
 * de cada turno YA vienen resueltos en `GET /api/alquileres/{id}`
 * (`turnos_estudio_vinculados[]`) — sumarlos es una suma de totales ya
 * persistidos, sin recalcular IVA/descuento por turno (eso sigue siendo
 * responsabilidad exclusiva de cada fila real, ver `services/finanzas_flujo`).
 * El total del PRINCIPAL sigue siendo el vivo de `useCotizacion`
 * (`respetarPrecioItem: true`) — esta función no lo toca, solo lo suma.
 */
import { format } from "date-fns";
import { es } from "date-fns/locale";

import type { PedidoGeneradoEdicion } from "@/lib/admin/api";

/**
 * Cómo se nombra un turno del Estudio DENTRO de su pedido — por su franja,
 * nunca por un "#N" (#1308: "no quiero dobles pedidos fantasmas"). El turno es
 * una parte del pedido, no una venta aparte: lo que lo identifica para el admin
 * es cuándo es. Fuente única — la usan el rail del Desglose y el modal de pago,
 * para que la misma cosa se llame igual en las dos pantallas.
 */
export function etiquetaTurno(t: {
  fecha_desde?: string | null;
  fecha_hasta?: string | null;
}): string {
  if (!t.fecha_desde) return "Estudio";
  const desde = new Date(t.fecha_desde);
  const dia = format(desde, "d MMM", { locale: es });
  const hasta = t.fecha_hasta ? ` a ${format(new Date(t.fecha_hasta), "HH:mm")}` : "";
  return `Estudio · ${dia} ${format(desde, "HH:mm")}${hasta}`;
}

export type TurnoConResta = PedidoGeneradoEdicion & { resta: number };

export type TotalesCombinados = {
  totalCombinado: number;
  pagadoCombinado: number;
  restaCombinado: number;
  turnos: TurnoConResta[];
};

export function combinarTotales(
  totalPrincipal: number,
  pagadoPrincipal: number,
  turnos: PedidoGeneradoEdicion[],
  /**
   * Total combinado YA RESUELTO por el backend (`/api/cotizar` → `combinado`).
   * Cuando el pedido cotiza en vivo hay que pasarlo: `monto_total` de un turno
   * es NETO (sin IVA) y `totalPrincipal` viene CON IVA, así que sumarlos crudo
   * da MENOS de lo que factura el comprobante (que aplica el IVA sobre el neto
   * combinado, `finanzas_flujo.pedido.combinar_turnos_vinculados`). El backend
   * resuelve el IVA sobre el neto combinado y este parámetro lo trae ya hecho.
   *
   * Se omite donde los dos lados son de la MISMA naturaleza y sumar es exacto:
   * la lista de pedidos (netos persistidos, sin IVA en pantalla).
   */
  totalCombinadoResuelto?: number | null,
): TotalesCombinados {
  const turnosConResta: TurnoConResta[] = turnos.map((t) => ({
    ...t,
    resta: Math.max(0, (t.monto_total ?? 0) - (t.monto_pagado ?? 0)),
  }));
  const totalCombinado =
    totalCombinadoResuelto ??
    totalPrincipal + turnos.reduce((acc, t) => acc + (t.monto_total ?? 0), 0);
  const pagadoCombinado =
    pagadoPrincipal + turnos.reduce((acc, t) => acc + (t.monto_pagado ?? 0), 0);
  return {
    totalCombinado,
    pagadoCombinado,
    restaCombinado: Math.max(0, totalCombinado - pagadoCombinado),
    turnos: turnosConResta,
  };
}
