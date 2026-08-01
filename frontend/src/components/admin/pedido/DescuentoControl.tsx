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
  className,
  /** Mientras el autosave de ESTE valor está en vuelo: sin esto, dos
   *  ediciones rápidas disparan dos PATCH y el que responde último pisa al
   *  que responde primero con un valor más viejo — una regresión silenciosa,
   *  no solo un dato stale en pantalla. */
  disabled,
  /** Oculta el toggle %/$ y fuerza el modo %: lo usa el ledger COMBINADO de
   *  "Turnos del Estudio" (2+ turnos) — un $ fijo repartido entre varios
   *  turnos con brutos distintos obligaría al FRONT a decidir cuánto le toca
   *  a cada uno, justo lo que "el front no calcula plata" prohíbe (MEMORIA
   *  2026-06-29). Un % combinado no tiene ese problema — el backend lo aplica
   *  igual a cada turno. */
  soloPct = false,
}: {
  value: DescuentoManual;
  onChange: (next: DescuentoManual) => void;
  maxMonto: number;
  efectivoPct: number;
  efectivoMonto: number;
  className?: string;
  disabled?: boolean;
  soloPct?: boolean;
}) {
  return (
    // Sin wrapper ni label propios: este control ya NO es un bloque aparte —
    // se renderiza IN PLACE, dentro de la fila "Descuento" del ledger de
    // `TotalSeccion` (pedido del dueño: "¿podemos unificar esos dos campos?
    // ... y el modificador de descuento, in place"). Antes eran dos cosas
    // separadas diciendo lo mismo: un control arriba y una fila abajo con el
    // resultado. Ahora la fila ES el control.
    <div className={cn("flex items-center gap-1.5", className)}>
      {!soloPct && (
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
          ariaLabel="Unidad del descuento: porcentaje o pesos"
          className="w-[96px] shrink-0 md:w-[68px]"
          disabled={disabled}
        />
      )}
      {!soloPct && value.tipo === "monto" ? (
        <MoneyInput
          min={0}
          max={maxMonto}
          step={100}
          value={value.monto}
          className="w-[112px]"
          ariaLabel="Descuento $ manual"
          onChange={(v) => onChange({ ...value, monto: v })}
          disabled={disabled}
        />
      ) : (
        <div className="relative w-[84px]">
          <Input
            type="number"
            min={0}
            max={100}
            step={0.1}
            aria-label="Descuento % manual"
            value={value.pct}
            disabled={disabled}
            className="pr-7"
            // Seleccionar el valor entero al enfocar: sin esto, arrancar en
            // 0 y tipear "2" insertaba el dígito DESPUÉS del cero ("02") en
            // vez de reemplazarlo — el cero visible quedaba pegado hasta
            // borrarlo a mano (lo reportó el dueño). Con el texto
            // seleccionado, la primera tecla lo reemplaza entero, como
            // espera cualquiera al ver un campo numérico en 0.
            onFocus={(e) => e.currentTarget.select()}
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
  );
}
