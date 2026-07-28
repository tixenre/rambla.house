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
import type { PedidoGeneradoEdicion } from "@/lib/admin/api";

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
): TotalesCombinados {
  const turnosConResta: TurnoConResta[] = turnos.map((t) => ({
    ...t,
    resta: Math.max(0, (t.monto_total ?? 0) - (t.monto_pagado ?? 0)),
  }));
  const totalCombinado = totalPrincipal + turnos.reduce((acc, t) => acc + (t.monto_total ?? 0), 0);
  const pagadoCombinado =
    pagadoPrincipal + turnos.reduce((acc, t) => acc + (t.monto_pagado ?? 0), 0);
  return {
    totalCombinado,
    pagadoCombinado,
    restaCombinado: Math.max(0, totalCombinado - pagadoCombinado),
    turnos: turnosConResta,
  };
}
