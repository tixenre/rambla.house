/**
 * TotalSeccion — el cierre de plata de una sección del pedido: bruto →
 * descuento → total.
 *
 * Fuente única de la FORMA de ese bloque. Lo usan "Alquiler de equipos" y cada
 * turno del Estudio, que ahora cierran igual (pedido del dueño: "¿podemos
 * poner un total por área, con los descuentos y demás?"). El detalle de cómo
 * se llega al número vive acá, en la sección; el rail de la derecha solo
 * resume — así el mismo desglose no está escrito en dos lugares.
 *
 * No calcula nada (MEMORIA 2026-06-29): los tres números los resuelve el
 * backend y este componente los muestra.
 */
import { type ReactNode } from "react";

import { fmtArs } from "@/lib/format";

export function TotalSeccion({
  brutoLabel = "Bruto",
  bruto,
  descuentoLabel,
  descuentoPct,
  descuentoMonto,
  total,
  /** Ej. el indicador de guardado del turno, al lado del número grande. */
  trailing,
}: {
  brutoLabel?: string;
  bruto: number;
  descuentoLabel?: string;
  descuentoPct?: number;
  descuentoMonto?: number;
  total: number;
  trailing?: ReactNode;
}) {
  // Sin descuento, "Bruto" y "Total" serían el mismo número dos veces — se
  // muestra solo el Total. Las tres líneas aparecen recién cuando hay algo
  // que explicar.
  const hayDescuento = (descuentoMonto ?? 0) > 0;
  return (
    <div className="rounded-lg border hairline bg-muted/20 p-3 text-sm">
      {/* justify-end, no justify-between: el label va PEGADO a su número,
          los dos juntos contra el borde derecho — no repartidos en las dos
          puntas de la fila (el dueño: "este texto al lado de los números,
          ¿me explico? justificado a la derecha"). */}
      <div className="space-y-1">
        {hayDescuento && (
          <>
            <div className="flex items-center justify-end gap-2 text-muted-foreground">
              <span>{brutoLabel}</span>
              <span className="font-mono tabular-nums">{fmtArs(bruto)}</span>
            </div>
            <div className="flex items-center justify-end gap-2 text-muted-foreground">
              <span>
                {descuentoLabel ?? "Descuento"}
                {descuentoPct ? ` · ${descuentoPct}%` : ""}
              </span>
              <span className="font-mono tabular-nums text-destructive">
                – {fmtArs(descuentoMonto ?? 0)}
              </span>
            </div>
          </>
        )}
        <div className="flex items-center justify-end gap-2 font-semibold text-ink">
          <span>Total</span>
          <span className="flex items-center gap-2 font-mono tabular-nums">
            {trailing}
            {fmtArs(total)}
          </span>
        </div>
      </div>
    </div>
  );
}
