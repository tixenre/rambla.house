import { CheckCircle2 } from "lucide-react";
import type { Taller } from "@/lib/api";
import { formatARS } from "@/lib/format";

/**
 * Precio del taller — "Modalidades de pago" ES el precio (el backend
 * siempre manda 1+ modalidad, sintetiza "Pago total" cuando la edición no
 * configuró ninguna — cero ruptura para talleres como el de Jime). No hay
 * un total aparte arriba duplicando el mismo número. La seña es de la
 * EDICIÓN, no de la modalidad — siempre se muestra debajo.
 */
export function PrecioCard({ taller }: { taller: Taller }) {
  const porcentajeSena =
    taller.precio_total > 0 ? Math.round((taller.precio_sena / taller.precio_total) * 100) : 0;

  return (
    <div className="rounded-2xl border border-border/60 bg-background p-5 mb-4">
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
