/**
 * DescuentoControl — el control de descuento manual (% o $ fijo) de un pedido.
 *
 * Fuente única de la FORMA del control: lo usan la sección "Alquiler de
 * equipos" (descuento del alquiler) y la de un turno del Estudio (su descuento
 * propio, #1308). Antes vivía inline en el rail de `pedidos.$id`; cuando el
 * descuento pasó a estar DENTRO de cada sección hubiera quedado copiado dos
 * veces — misma regla de siempre (reusar antes de recrear, MEMORIA
 * 2026-05-25 "Barra de calidad de ingeniería").
 *
 * No calcula plata (MEMORIA 2026-06-29): lo que edita es la INTENCIÓN (qué
 * descuento pidió el admin); el % y el $ efectivos los resuelve el backend y
 * se los pasa el caller (`efectivoPct`/`efectivoMonto`) solo para convertir de
 * unidad sin perder el valor al tocar el selector.
 */
import { Input } from "@/design-system/ui/input";
import { MoneyInput } from "@/design-system/ui/money-input";
import { SegmentedControl } from "@/design-system/ui/segmented-control";
import { cn } from "@/lib/utils";

export type DescuentoManual = {
  tipo: "pct" | "monto";
  pct: number;
  monto: number;
};

export function DescuentoControl({
  value,
  onChange,
  /** Tope del override en $: el bruto DESCONTABLE (sin las líneas de combo,
   *  que ya traen su propio descuento horneado). Lo resuelve el backend. */
  maxMonto,
  /** El % y el $ que el desglose muestra HOY — al cambiar de unidad se
   *  convierte a su equivalente en vez de resetear a 0. */
  efectivoPct,
  efectivoMonto,
  label = "Descuento manual (0 = automático)",
  className,
}: {
  value: DescuentoManual;
  onChange: (next: DescuentoManual) => void;
  maxMonto: number;
  efectivoPct: number;
  efectivoMonto: number;
  label?: string;
  className?: string;
}) {
  return (
    /* Div plano, NO <FieldLabel> (que renderiza un <label> nativo): un <label>
       reenvía cualquier click dentro de su área al PRIMER control enfocable de
       adentro (acá, el botón "%") — clickear "cerca" del input $ pero todavía
       dentro del label revertía el selector a "%" solo. Con 2+ controles
       adentro, un <label> no es seguro; FieldLabel sigue bien para los campos
       de un solo input. */
    <div className={cn("block", className)}>
      <span className="block t-eyebrow mb-1">{label}</span>
      <div className="flex items-center gap-2">
        <SegmentedControl
          value={value.tipo}
          onChange={(v) =>
            onChange(
              // Convertir al equivalente del OTRO campo (el % y el $ efectivos
              // que ya muestra el desglose, calculados por el backend) en vez
              // de resetear a 0 — cambiar de unidad no debería perder el
              // descuento actual. El campo que se deja de usar se resetea (sin
              // esto queda un valor "fantasma" que podía reaparecer si el admin
              // volvía a tocar el selector).
              v === "monto"
                ? { tipo: "monto", monto: efectivoMonto, pct: 0 }
                : { tipo: "pct", pct: efectivoPct, monto: 0 },
            )
          }
          options={[
            { value: "pct", label: "%" },
            { value: "monto", label: "$" },
          ]}
          className="w-20 shrink-0"
        />
        {value.tipo === "monto" ? (
          <MoneyInput
            min={0}
            max={maxMonto}
            step={100}
            value={value.monto}
            className="max-w-[140px]"
            ariaLabel="Descuento $ manual"
            onChange={(v) => onChange({ ...value, monto: v })}
          />
        ) : (
          <div className="relative max-w-[140px]">
            <Input
              type="number"
              min={0}
              max={100}
              step={0.1}
              aria-label="Descuento % manual"
              value={value.pct}
              className="pr-7"
              onChange={(e) =>
                onChange({
                  ...value,
                  pct: Math.max(0, Math.min(100, Number(e.target.value) || 0)),
                })
              }
            />
            <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
              %
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
