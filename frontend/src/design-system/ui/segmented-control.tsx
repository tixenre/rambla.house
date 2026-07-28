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
  className?: string;
}

export function SegmentedControl({
  value,
  onChange,
  options,
  variant = "default",
  className,
}: SegmentedControlProps) {
  if (variant === "pill") {
    return (
      <div
        className={cn(
          "inline-flex overflow-hidden rounded-full border hairline bg-background",
          className,
        )}
        role="group"
      >
        {options.map((opt) => (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={value === opt.value}
            onClick={() => onChange(opt.value)}
            className={cn(
              "px-3 py-1 font-mono text-xs uppercase tracking-[0.15em] transition",
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
    <div className={cn("flex flex-wrap gap-1", className)} role="group">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="radio"
          aria-checked={value === opt.value}
          onClick={() => onChange(opt.value)}
          className={cn(
            "flex-1 basis-[max-content] rounded-md border px-2.5 py-1.5 text-xs font-medium capitalize transition",
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
