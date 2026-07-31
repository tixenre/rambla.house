import { RadioGroup, RadioGroupItem } from "@/design-system/ui/radio-group";
import type { Taller } from "@/lib/api";

/**
 * Selector de modalidad de pago en el form de inscripción. 1 sola modalidad
 * configurada (o el fallback sintético "Pago total") → texto sin radio, cero
 * fricción extra. 2+ → RadioGroup DS.
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
  if (modalidades.length <= 1) return null;

  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
        Modalidad de pago
      </p>
      <RadioGroup value={value} onValueChange={onChange} className="gap-2">
        {modalidades.map((m) => (
          <label
            key={m.codigo}
            className={`flex items-center gap-3 rounded-xl border px-4 py-3 cursor-pointer transition-colors ${
              value === m.codigo ? "border-rosa bg-rosa/5" : "border-border/60 hover:border-border"
            }`}
          >
            <RadioGroupItem value={m.codigo} />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-ink">{m.label}</p>
              {m.nota && <p className="text-xs text-rosa">{m.nota}</p>}
            </div>
            <p className="font-display text-sm font-bold text-ink tabular-nums shrink-0">
              {m.monto_total_str}
            </p>
          </label>
        ))}
      </RadioGroup>
    </div>
  );
}
