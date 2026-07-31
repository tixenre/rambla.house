/**
 * Overlay de textura granulada — para secciones ink/oscuras (hero editorial).
 * Única fuente: antes triplicada (estudio.lazy, escuela.$slug.lazy,
 * escuela.index.lazy) con la misma forma, ligeras variaciones de opacidad/color.
 */
export function Grain({
  opacity = 12,
  color = "oklch(0.85 0 0 / 12%)",
  className = "",
}: {
  opacity?: number;
  color?: string;
  className?: string;
}) {
  return (
    <div
      className={`pointer-events-none absolute inset-0 ${className}`}
      style={{
        backgroundImage: `radial-gradient(circle, ${color} 1px, transparent 1px)`,
        backgroundSize: "5px 5px",
        opacity: opacity / 100,
      }}
    />
  );
}
