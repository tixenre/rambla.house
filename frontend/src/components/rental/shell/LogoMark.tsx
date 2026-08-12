import { useId } from "react";
import isologoMonoSvgRaw from "@/assets/rambla-isologo-mono.svg?raw";

/**
 * Isologo mono de Rambla (la R con puntas) para los topbars de color.
 *
 * Es la forma **themeable** del isologo: silueta en `currentColor` + la R recortada
 * (negativo). Con `text-white` la silueta queda blanca y la R muestra el color del
 * área, así funciona sobre los 4 colores de marca (amber/naranja/rosa/verde) — el
 * isologo "con color" del admin se funde sobre el amber del rental.
 *
 * El isologo de marca que sube el admin (con sus colores) se usa para los assets
 * derivados (favicon, ícono iOS, imagen para compartir) vía el backend, no acá.
 */
export function LogoMark({ className = "" }: { className?: string }) {
  // El SVG fuente trae un <mask id="rambla-r-cut"> fijo — dos instancias en la
  // misma página (ej. el logo mobile del topbar + un placeholder en otra
  // sección) colisionan por id duplicado y el navegador deja de aplicar el
  // mask (queda un cuadrado sólido, sin el recorte de la R). `useId()` lo
  // hace único por instancia.
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const svg = isologoMonoSvgRaw.replaceAll("rambla-r-cut", `rambla-r-cut-${uid}`);
  return (
    <span
      className={`inline-block shrink-0 ${className || "h-8 w-8"}`}
      dangerouslySetInnerHTML={{ __html: svg }}
      role="img"
      aria-label="Rambla"
    />
  );
}
