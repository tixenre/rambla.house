import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// tailwind-merge no lee el @theme de Tailwind v4 (frontend/src/design-system/styles/tokens/typography.css):
// sin este `extend`, agrupa nuestros tamaños custom (text-15/22/2xs/3xs) junto con las clases de
// color de texto (mismo prefijo `text-`) y borra en silencio una de las dos al mergear —
// ej. `cn("bg-ink text-background", "text-15")` perdía `text-background` (botón sin color de
// texto, invisible sobre el fondo). Ver test en utils.test.ts.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": ["text-15", "text-22", "text-2xs", "text-3xs"],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
