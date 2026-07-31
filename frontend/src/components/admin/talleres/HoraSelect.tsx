import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/design-system/ui/select";
import { fmtHhmm } from "@/lib/talleres/formato";

/**
 * Selector de horario en MINUTOS desde medianoche (Escuela v2 F1), paso 30 min:
 * "08:00, 08:30, …, 24:00". `min`/`max` también en minutos (0..1440).
 */
export function HoraSelect({
  value,
  onChange,
  min = 0,
  max = 1440,
  className,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  className?: string;
}) {
  const opciones: number[] = [];
  for (let m = min; m <= max; m += 30) opciones.push(m);
  return (
    <Select value={String(value)} onValueChange={(v) => onChange(Number(v))}>
      <SelectTrigger className={className ?? "w-[100px]"}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {opciones.map((m) => (
          <SelectItem key={m} value={String(m)}>
            {fmtHhmm(m)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
