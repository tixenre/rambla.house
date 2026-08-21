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

/** "1,2 MB" / "340 KB" / "512 B" — usado por la vista en lista de PhotoGallery. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIdx = 0;
  while (value >= 1024 && unitIdx < units.length - 1) {
    value /= 1024;
    unitIdx++;
  }
  return `${value.toFixed(value < 10 ? 1 : 0).replace(".", ",")} ${units[unitIdx]}`;
}

/** Extensión del archivo a partir de la URL — sin backend nuevo: `path`/`url`
 * ya la traen embebida (media/{...}/display-{hash}.webp). El punto se busca
 * SOLO en el último segmento de path (no en el dominio) — una URL sin
 * extensión ahí (ej. un host que sirve por id, `.../seed/g1/600/600`) no
 * tiene ningún "." en ese segmento y cae a "—", en vez de devolver la URL
 * entera (bug real encontrado en vivo con datos de prueba sin extensión).
 * Usado por la vista en lista de PhotoGallery. */
export function extFromUrl(url: string): string {
  const clean = url.split(/[?#]/)[0];
  const lastSegment = clean.slice(clean.lastIndexOf("/") + 1);
  const dotIdx = lastSegment.lastIndexOf(".");
  if (dotIdx <= 0) return "—";
  return lastSegment.slice(dotIdx + 1).toUpperCase();
}
