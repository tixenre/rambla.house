import type { ReactNode } from "react";

/**
 * Caja con chrome propio (borde + fondo tenue + eyebrow interno) para un
 * bloque de contenido de la página del taller — mismo tratamiento que ya
 * tenían "Orientado a"/"Sobre" (antes cada uno con sus propios números),
 * ahora una sola fuente para que cada sección "pertenezca al mismo diseño"
 * en vez de flotar suelta contra el fondo (pedido explícito del dueño,
 * mismo criterio ya aplicado a la card única de "Cuándo").
 */
export function SeccionCard({
  eyebrow,
  children,
  className = "",
}: {
  eyebrow?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-2xl border border-border/60 bg-muted/20 px-6 py-7 ${className}`}>
      {eyebrow && (
        <p className="font-mono text-2xs tracking-[0.25em] uppercase text-muted-foreground mb-4">
          {eyebrow}
        </p>
      )}
      {children}
    </section>
  );
}
