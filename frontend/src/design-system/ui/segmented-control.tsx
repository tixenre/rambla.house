import * as React from "react";
import { cn } from "@/lib/utils";

export interface SegmentOption {
  value: string;
  label: string;
}

export interface SegmentedControlProps {
  value: string;
  onChange: (v: string) => void;
  options: SegmentOption[];
  /** "default" = botones separados con gap. "pill" = track conectado tipo capsule. */
  variant?: "default" | "pill";
  /** Nombre accesible del grupo. Obligatorio en la práctica cuando no hay un
   *  label visible al lado (ej. el toggle %/$ del descuento): sin esto un
   *  lector de pantalla solo oye dos radios sueltos, "%" y "$", sin saber de
   *  qué son. */
  ariaLabel?: string;
  className?: string;
}

export function SegmentedControl({
  value,
  onChange,
  options,
  variant = "default",
  ariaLabel,
  className,
}: SegmentedControlProps) {
  if (variant === "pill") {
    return (
      <div
        className={cn(
          "inline-flex overflow-hidden rounded-full border hairline bg-background",
          className,
        )}
        role="radiogroup"
        aria-label={ariaLabel}
      >
        {options.map((opt) => (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={value === opt.value}
            onClick={() => onChange(opt.value)}
            className={cn(
              "flex min-h-11 items-center px-3 py-1 font-mono text-xs uppercase tracking-[0.15em] transition md:min-h-0",
              value === opt.value
                ? "bg-ink text-background"
                : "text-muted-foreground hover:text-ink",
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>
    );
  }

  return (
    // `role="radiogroup"`, no `"group"`: los hijos son `role="radio"` y un radio
    // exige un radiogroup como dueño — con `group` el ARIA era inválido y un
    // lector de pantalla no anunciaba el conjunto. `aria-label` opcional para
    // los usos sin label visible (ej. el toggle %/$ del descuento, que quedó
    // sin texto al lado y se oía como dos radios sueltos "%" y "$").
    <div className={cn("flex flex-wrap gap-1", className)} role="radiogroup" aria-label={ariaLabel}>
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="radio"
          aria-checked={value === opt.value}
          onClick={() => onChange(opt.value)}
          className={cn(
            "flex min-h-11 flex-1 basis-[max-content] items-center justify-center rounded-md border px-2.5 py-1.5 text-xs font-medium capitalize transition md:min-h-0",
            value === opt.value
              ? "border-ink bg-ink text-background"
              : "border-muted-foreground/30 text-muted-foreground hover:border-ink hover:text-ink",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
