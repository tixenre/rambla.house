import { useEffect, useState } from "react";
import { Minus, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { buttonVariants } from "./button";

export interface QtyInputProps {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  /** Muestra el input con borde destructivo (ej. overstock) */
  error?: boolean;
  /** "sm" = h-7 botones (más compacto). "md" = h-9 (default). */
  size?: "sm" | "md";
  className?: string;
}

export function QtyInput({
  value,
  onChange,
  min = 1,
  max,
  error = false,
  size = "md",
  className,
}: QtyInputProps) {
  // 44px táctil en mobile, denso en desktop (gate de PROTOCOLO / Apple HIG,
  // MEMORIA 2026-06-05). El stepper es de lo MÁS tocado de la pantalla de
  // pedidos y venía en 28-36px.
  const btnH = size === "sm" ? "h-11 w-11 md:h-7 md:w-7" : "h-11 w-11 md:h-9 md:w-9";
  const inputH = size === "sm" ? "h-11 w-11 md:h-7 md:w-10" : "h-11 w-12 md:h-9 md:w-11";
  const iconSz = size === "sm" ? "h-2.5 w-2.5" : "h-3 w-3";

  function decrement() {
    onChange(Math.max(min, value - 1));
  }
  function increment() {
    onChange(max !== undefined ? Math.min(max, value + 1) : value + 1);
  }

  // Borrador local — no el `value` autoritativo directo. `handleChange`
  // hacía `parseInt(e.target.value, 10)` y, si el campo estaba vacío
  // (NaN, `!Number.isFinite`), retornaba SIN llamar a `onChange`: como el
  // input queda controlado por `value` (el prop, sin cambiar), el próximo
  // render de CUALQUIER otra cosa en la página lo pisaba de vuelta al
  // número viejo — no se podía borrar un dígito y escribir uno nuevo.
  // Acá se edita libre en un string local; confirma con cada tecla que YA
  // parsea a un número válido (a diferencia de KitComponentEditor, este es
  // un stepper — se espera feedback en vivo, ej. subtotales), pero sin
  // forzar un valor no vacío en el medio de una edición. Al salir del
  // campo, si quedó vacío/inválido, vuelve al último valor válido.
  const [draft, setDraft] = useState(String(value));
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (!focused) setDraft(String(value));
  }, [value, focused]);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const raw = e.target.value;
    setDraft(raw);
    if (raw.trim() === "") return;
    const parsed = parseInt(raw, 10);
    if (!Number.isFinite(parsed)) return;
    const clamped =
      max !== undefined ? Math.min(max, Math.max(min, parsed)) : Math.max(min, parsed);
    onChange(clamped);
  }

  function handleBlur() {
    setFocused(false);
    if (draft.trim() === "" || !Number.isFinite(parseInt(draft, 10))) {
      setDraft(String(value));
    }
  }

  return (
    <div className={cn("flex items-center gap-1", className)}>
      <button
        type="button"
        aria-label="Restar uno"
        onClick={decrement}
        disabled={value <= min}
        className={cn(buttonVariants({ variant: "outline", size: "icon" }), btnH)}
      >
        <Minus className={iconSz} />
      </button>
      <input
        type="number"
        min={min}
        max={max}
        value={draft}
        aria-label="Cantidad"
        onFocus={() => setFocused(true)}
        onChange={handleChange}
        onBlur={handleBlur}
        className={cn(
          "rounded-md border p-0 text-center font-mono text-base tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:text-sm",
          inputH,
          error
            ? "border-destructive text-destructive"
            : "border-input bg-background text-foreground",
        )}
      />
      <button
        type="button"
        aria-label="Sumar uno"
        onClick={increment}
        disabled={max !== undefined && value >= max}
        className={cn(buttonVariants({ variant: "outline", size: "icon" }), btnH)}
      >
        <Plus className={iconSz} />
      </button>
    </div>
  );
}
