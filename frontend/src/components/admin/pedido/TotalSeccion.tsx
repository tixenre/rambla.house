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
      {/* Grid de 2 columnas, no filas `flex` independientes: cada fila
          anterior se auto-anchaba a su propio contenido ("Bruto · 1
          jornada" vs "Descuento manual · 20%" vs "Total" tienen largos
          distintos), así que aunque las tres estaban pegadas a la derecha,
          arrancaban en puntos distintos — se veía dentado, no alineado (el
          dueño: "¿podemos alinear mejor las cosas?"). Con `grid-cols-[1fr_auto]`
          + `text-right` en las dos columnas, los LABELS terminan todos en la
          MISMA x (columna 1, ancha) y los VALORES también (columna 2, ajustada
          al más largo) — recién ahí el bloque lee como una columna prolija,
          no una fila por fila. */}
      <div className="grid grid-cols-[1fr_auto] gap-x-2 gap-y-1">
        {hayDescuento && (
          <>
            <span className="text-right text-muted-foreground">{brutoLabel}</span>
            <span className="text-right font-mono tabular-nums text-muted-foreground">
              {fmtArs(bruto)}
            </span>
            <span className="text-right text-muted-foreground">
              {descuentoLabel ?? "Descuento"}
              {descuentoPct ? ` · ${descuentoPct}%` : ""}
            </span>
            <span className="text-right font-mono tabular-nums text-destructive">
              – {fmtArs(descuentoMonto ?? 0)}
            </span>
          </>
        )}
        <span className="text-right font-semibold text-ink">Total</span>
        <span className="flex items-center justify-end gap-2 font-mono tabular-nums font-semibold text-ink">
          {trailing}
          {fmtArs(total)}
        </span>
      </div>
    </div>
  );
}
