import { CheckCircle2 } from "lucide-react";
import type { Taller } from "@/lib/api";
import { formatARS } from "@/lib/format";

/**
 * Precio del taller — la info y la forma de pago son cosas DISTINTAS, no se
 * mezclan: el valor (`precio_total`) siempre encabeza como el número grande,
 * sea cual sea la cantidad de modalidades. "Modalidades de pago" (2+
 * configuradas) es una sub-sección secundaria debajo — son formas de pagar
 * ESE mismo valor (pago único o en cuotas), no precios distintos del taller;
 * por eso van con menos peso visual que el encabezado. Con 0-1 modalidad no
 * hay nada que elegir, así que la sub-sección no se muestra. La seña es de
 * la EDICIÓN, no de la modalidad — siempre se muestra debajo, sea cual sea
 * el caso de arriba.
 */
export function PrecioCard({ taller }: { taller: Taller }) {
  const porcentajeSena =
    taller.precio_total > 0 ? Math.round((taller.precio_sena / taller.precio_total) * 100) : 0;
  const unica = taller.modalidades.length <= 1;

  return (
    <div className="rounded-2xl border border-border/60 bg-background p-5 mb-4">
      <p className="text-xs text-muted-foreground mb-1">Costo total</p>
      <p className="font-display text-3xl font-bold text-ink tabular-nums">
        {formatARS(taller.precio_total)}
      </p>

      {!unica && (
        <div className="mt-4 pt-4 border-t border-border/50">
          <p className="text-xs text-muted-foreground mb-2">Modalidades de pago</p>
          <div className="flex flex-col gap-2">
            {taller.modalidades.map((m) => (
              <div
                key={m.codigo}
                className="flex items-baseline justify-between gap-3 rounded-lg bg-muted/30 px-3 py-2"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink">{m.label}</p>
                  {m.nota && <p className="text-xs text-rosa">{m.nota}</p>}
                </div>
                <p className="text-sm font-semibold text-ink tabular-nums shrink-0">
                  {m.monto_total_str}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      <ul className="mt-3 flex flex-col gap-1.5">
        {[
          `Seña del ${porcentajeSena}% al inscribirte (${formatARS(taller.precio_sena)})`,
          "Resto antes de la primera clase",
        ].map((item) => (
          <li key={item} className="flex items-start gap-2 text-xs text-muted-foreground">
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0 mt-0.5 text-verde" strokeWidth={1.5} />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
