import * as React from "react";
import { cn } from "@/lib/utils";
import { buttonVariants, type ButtonProps } from "./button";

export type IconButtonSize = "xs" | "sm" | "md" | "lg";

// xs=28px tabla densa, sm=32px toolbars, md=36px default (HIG desktop), lg=44px siempre.
//
// EN MOBILE TODOS ARRANCAN EN 44px (`h-11 w-11`) y recién en `md:` bajan a su
// tamaño denso de desktop. El gate de `docs/PROTOCOLO.md` pide ≥44px táctil
// (Apple HIG, MEMORIA 2026-06-05) y la página de pedidos estaba llena de
// botones de 28-32px — incluidos destructivos como "Anular pago". Resolverlo
// acá lo arregla en TODOS los consumidores de una, sin tocar la densidad de
// desktop, en vez de ir componente por componente.
const SIZE: Record<IconButtonSize, string> = {
  xs: "h-11 w-11 md:h-7 md:w-7",
  sm: "h-11 w-11 md:h-8 md:w-8",
  md: "h-11 w-11 md:h-9 md:w-9",
  lg: "h-11 w-11",
};

export interface IconButtonProps extends Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  "children"
> {
  /** Obligatorio: usado por screen readers en lugar del texto visible. */
  "aria-label": string;
  children: React.ReactNode;
  variant?: ButtonProps["variant"];
  size?: IconButtonSize;
}

export const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ className, variant = "ghost", size = "md", disabled, children, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size: "icon" }), SIZE[size], className)}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  ),
);
IconButton.displayName = "IconButton";
