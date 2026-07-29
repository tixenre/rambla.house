import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";
import { Spinner } from "@/design-system/ui/spinner";

// eslint-disable-next-line react-refresh/only-export-components -- variantes cva del patrón shadcn; conviven con el componente Button en este archivo
export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition [transition-duration:var(--duration-base)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow hover:bg-primary/90",
        destructive: "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
        outline:
          "border border-input bg-background shadow-sm hover:bg-accent hover:text-accent-foreground",
        secondary: "bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",

        // ── Rambla brand variants ─────────────────────────────────────────────

        // primary — la jugada signature de marca: fondo ink, hover invierte al accent del área.
        // CTA principal del catálogo, carrito y flows de reserva.
        primary: "bg-ink text-background shadow-sm hover:bg-[var(--area-accent)] hover:text-ink",

        // amber — fondo accent del área, sin inversión. Para CTAs sobre fondos oscuros
        // (hero estudio, banners, etc.) o cuando el primario no tiene suficiente
        // contraste con el fondo. El nombre "amber" se mantiene (renombrar = churn).
        amber: "bg-[var(--area-accent)] text-ink shadow-sm hover:bg-[var(--area-accent-hot)]",

        // on-accent — CTA sobre fondos de color (hero amber, banners de área).
        // Reposo: bone/background + ink. Hover: invierte a ink + bone. Tres colores
        // distintos garantizados: fondo de área ≠ botón reposo ≠ botón hover.
        "on-accent": "bg-background text-ink shadow-sm hover:bg-ink hover:text-background",
      },
      size: {
        default: "h-11 px-4 py-2 md:h-9",
        sm: "h-11 rounded-md px-3 text-xs md:h-8",
        lg: "h-11 rounded-md px-8 md:h-10",
        icon: "h-11 w-11 md:h-9 md:w-9",
      },
      // Eje "shape" del kit Rambla. Default = rounded (radius-md, mismo que
      // el base actual). Pill = redondeo full, para CTAs y filter chips.
      // tailwind-merge resuelve el override de rounded-md ↔ rounded-full.
      shape: {
        rounded: "",
        pill: "rounded-full",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
      shape: "rounded",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  /** Muestra un Spinner y deshabilita el botón. No aplica cuando asChild=true. */
  loading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, shape, asChild = false, loading, disabled, children, ...props },
    ref,
  ) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, shape, className }))}
        ref={ref}
        disabled={disabled || (loading && !asChild)}
        aria-busy={loading && !asChild ? true : undefined}
        {...props}
      >
        {/* asChild ⇒ Comp es Radix Slot, que exige UN solo hijo: pasamos `children`
            crudo (sin el `null` del spinner, que lo convertiría en [null, child] y
            rompería React.Children.only). El loading no aplica con asChild. */}
        {asChild ? (
          children
        ) : (
          <>
            {loading ? <Spinner size="sm" /> : null}
            {children}
          </>
        )}
      </Comp>
    );
  },
);
Button.displayName = "Button";

export { Button };
