/**
 * Disponibilidad DRAFT-AWARE del editor de pedidos (admin).
 *
 * Fuente única del mapa "unidades libres" que ven las líneas del editor y los
 * buscadores de equipos. El cálculo vive ENTERO en el backend
 * (`reservas.calcular_disponibilidad_draft`): se le manda el draft completo
 * ("id:cantidad,...") y devuelve, por equipo, cuántas unidades quedan DESPUÉS
 * de descontar todo el draft con la expansión recursiva de kits del motor —
 * la misma pieza que usa el gate de guardado. El front NO vuelve a restar nada
 * (antes hacía `libres - cantidad_de_la_línea` por su cuenta y un kit y sus
 * componentes en el mismo draft no se descontaban entre sí → "2 libres" con 0
 * reales, bug del editor con kits).
 *
 * Los valores vienen CON SIGNO: negativo = cuántas unidades faltan (overstock,
 * el gate va a rechazar el guardado). Un compuesto hereda el faltante de sus
 * hojas vía la derivación del motor.
 */
import { useQuery, keepPreviousData } from "@tanstack/react-query";

import { adminApi } from "@/lib/admin/api";
import type { DraftItem } from "./usePedidoDraft";

/** `equipo_id → unidades libres tras el draft` (con signo). */
export type StockMap = Record<string, number>;

/** Serialización canónica del draft para el backend: solo líneas de catálogo,
 *  orden estable (el drag-reorder no refetchea). */
export function serializarItemsDraft(items: DraftItem[] | null | undefined): string {
  return (items ?? [])
    .filter((it) => it.equipo_id != null && it.cantidad > 0)
    .map((it) => `${it.equipo_id}:${it.cantidad}`)
    .sort()
    .join(",");
}

export function useDisponibilidadDraft({
  pedidoId,
  fechaDesde,
  fechaHasta,
  items,
  enabled = true,
}: {
  pedidoId: number | undefined;
  fechaDesde: string | undefined;
  fechaHasta: string | undefined;
  items: DraftItem[] | null | undefined;
  enabled?: boolean;
}) {
  const itemsParam = serializarItemsDraft(items);

  const q = useQuery({
    queryKey: ["admin", "disponibilidad", fechaDesde, fechaHasta, pedidoId, itemsParam],
    queryFn: () => adminApi.getDisponibilidad(fechaDesde!, fechaHasta!, pedidoId, itemsParam),
    enabled: enabled && !!pedidoId && !!fechaDesde && !!fechaHasta,
    // El mapa cambia con cada tecleo de cantidad: mantener el valor anterior
    // mientras llega el nuevo evita que los badges parpadeen.
    placeholderData: keepPreviousData,
  });

  const stockMap: StockMap = {};
  for (const [k, v] of Object.entries(q.data ?? {})) {
    const n = Number(v);
    if (Number.isFinite(n)) stockMap[k] = n;
  }

  // Overstock = alguna línea del draft quedó en negativo (el faltante de una
  // hoja burbujea a la línea del kit que la contiene, así que mirar las líneas
  // alcanza). Equipos sin dato (sin fechas todavía) no bloquean.
  const hasOverstock = (items ?? []).some((it) => {
    if (it.equipo_id == null) return false;
    const v = stockMap[String(it.equipo_id)];
    return v !== undefined && v < 0;
  });

  return { stockMap, hasOverstock, query: q };
}
