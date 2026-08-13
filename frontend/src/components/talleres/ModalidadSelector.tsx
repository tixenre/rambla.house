import { RadioGroup, RadioGroupItem } from "@/design-system/ui/radio-group";
import type { Taller } from "@/lib/api";

/**
 * El lado del monto de una modalidad — con más de 1 cuota, el monto POR
 * cuota (ya calculado por el backend, `monto_total / n_cuotas`) es lo
 * prominente y el total queda como dato secundario más chico, para que "4
 * cuotas de $80.000" no se confunda con "$80.000 en total" (pedido explícito
 * del dueño: nunca calcular acá, solo mostrar lo que ya viene resuelto).
 * `n_cuotas === 1` (pago único, el caso más común) se ve exactamente igual
 * que siempre — cero regresión visual para "Pago total".
 */
function MontoModalidad({ m }: { m: Taller["modalidades"][number] }) {
  if (m.n_cuotas > 1) {
    return (
      <div className="text-right shrink-0">
        <p className="font-display text-ink tabular-nums leading-tight">
          <span className="text-xs font-semibold">{m.n_cuotas} cuotas de </span>
          <span className="text-lg font-bold">{m.monto_cuota_str}</span>
        </p>
        <p className="text-2xs text-muted-foreground tabular-nums">Total {m.monto_total_str}</p>
      </div>
    );
  }
  return (
    <p className="font-display text-sm font-bold text-ink tabular-nums shrink-0">
      {m.monto_total_str}
    </p>
  );
}

/**
 * Selector de modalidad de pago en el form de inscripción. 0 modalidades no
 * debería pasar (el backend siempre sintetiza "Pago total" si la edición no
 * configuró ninguna) — defensivo, sin nada que mostrar. 1 sola → el monto se
 * muestra igual (sin radio, cero fricción de elegir entre 1 sola opción) —
 * si no, el form se queda sin ningún monto visible antes del comprobante de
 * transferencia. 2+ → RadioGroup DS.
 */
export function ModalidadSelector({
  modalidades,
  value,
  onChange,
}: {
  modalidades: Taller["modalidades"];
  value: string;
  onChange: (codigo: string) => void;
}) {
  if (modalidades.length === 0) return null;

  // En cuotas primero, pago único después (pedido explícito del dueño) —
  // sort estable: entre 2+ opciones en cuotas, conserva el orden en que el
  // admin las cargó.
  const ordenadas = [...modalidades].sort(
    (a, b) => Number(b.n_cuotas > 1) - Number(a.n_cuotas > 1),
  );

  if (ordenadas.length === 1) {
    const m = ordenadas[0];
    // Rambla solo acepta transferencia para talleres (el comprobante de
    // transferencia del form, más abajo, es obligatorio) — nunca varía por
    // taller, así que "Transferencia" es texto fijo acá, nunca tipeado por
    // el admin. Con "En N cuotas" el label ya repetiría lo que dice
    // MontoModalidad ("N cuotas de $X") al lado, así que queda solo
    // "Transferencia"; "Pago único" no repite ningún número, se compone.
    const nombreVisible = m.n_cuotas > 1 ? "Transferencia" : `Transferencia · ${m.label}`;
    return (
      <div className="flex items-center justify-between gap-3 rounded-xl border border-border/60 px-4 py-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-ink">{nombreVisible}</p>
          {m.nota && <p className="text-xs text-rosa">{m.nota}</p>}
        </div>
        <MontoModalidad m={m} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
        Modalidad de pago — por transferencia
      </p>
      <RadioGroup value={value} onValueChange={onChange} className="gap-2">
        {ordenadas.map((m) => (
          <label
            key={m.codigo}
            className={`flex items-center gap-3 rounded-xl border px-4 py-3 cursor-pointer transition-colors ${
              value === m.codigo ? "border-rosa bg-rosa/5" : "border-border/60 hover:border-border"
            }`}
          >
            <RadioGroupItem value={m.codigo} />
            <div className="flex-1 min-w-0">
              {/* "En N cuotas" repetiría el número que ya dice MontoModalidad
                  ("N cuotas de $X") a la derecha — acá va genérico. "Pago
                  único" no repite ningún número, se muestra tal cual. */}
              <p className="text-sm font-semibold text-ink">
                {m.n_cuotas > 1 ? "En cuotas" : m.label}
              </p>
              {m.nota && <p className="text-xs text-rosa">{m.nota}</p>}
            </div>
            <MontoModalidad m={m} />
          </label>
        ))}
      </RadioGroup>
    </div>
  );
}
