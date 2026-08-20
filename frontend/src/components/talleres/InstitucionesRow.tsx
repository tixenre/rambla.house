import { Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Taller } from "@/lib/api";

type InstitucionEntity = Taller["instituciones"][number];
type Variant = "light" | "dark";

function InstitucionPill({
  institucion,
  variant,
}: {
  institucion: InstitucionEntity;
  variant: Variant;
}) {
  const content = (
    <>
      {institucion.logo_url && (
        <img
          src={institucion.logo_url}
          alt={institucion.nombre}
          className="h-5 w-auto max-w-16 object-contain"
        />
      )}
      <span
        className={cn("text-sm font-medium", variant === "dark" ? "text-background" : "text-ink")}
      >
        {institucion.nombre}
      </span>
    </>
  );
  const cls = cn(
    "flex items-center gap-2 rounded-full border px-3 py-1.5 transition",
    variant === "dark"
      ? "border-background/20 bg-background/10 hover:border-background/40"
      : "border-border/50 bg-muted/20 hover:border-border",
  );
  if (institucion.web) {
    return (
      <a href={institucion.web} target="_blank" rel="noopener noreferrer" className={cls}>
        {content}
      </a>
    );
  }
  return <div className={cls}>{content}</div>;
}

/** "Presentado por" — instituciones co-presentadoras (ej. "Rambla" + "Filmar").
 * Data-driven: sin instituciones vinculadas, no se muestra nada (Jime y el
 * resto de los talleres sin institución siguen viéndose igual que siempre).
 *
 * Debajo, si alguna institución tiene MÁS de 1 taller activo, un link al hub
 * (`/escuelas/instituciones/$slug`) — pedido del dueño 2026-08-20: quien
 * aterriza directo en un taller (no por el hub) no tenía forma de enterarse
 * de que su institución ofrece más. Con exactamente 1 taller no se muestra:
 * el hub mostraría ese mismo taller, un click sin destino nuevo. */
export function InstitucionesRow({
  taller,
  variant = "light",
  className,
}: {
  taller: Taller;
  // "dark" = sobre el hero (bg-ink) — usado por TallerHero, único lugar
  // donde se muestra esta fila (se sacó del cuerpo claro de la página,
  // pedido del dueño 2026-08-20: quería el bloque junto al CTA del hero,
  // no más abajo). El default "light" queda por si se reusa en un
  // contexto claro a futuro.
  variant?: Variant;
  // El caller pone su propio margen acá (no en un wrapper aparte) — así,
  // sin instituciones vinculadas, el `return null` de abajo no deja un
  // wrapper con margen vacío colgando en el hero.
  className?: string;
}) {
  if (taller.instituciones.length === 0) return null;
  const conMasTalleres = taller.instituciones.filter((i) => (i.talleres_count ?? 0) > 1);
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="flex flex-wrap items-center gap-3">
        <p
          className={cn(
            "text-xs font-mono uppercase tracking-widest shrink-0",
            variant === "dark" ? "text-background/50" : "text-muted-foreground",
          )}
        >
          Presentado por
        </p>
        {taller.instituciones.map((inst) => (
          <InstitucionPill key={inst.id} institucion={inst} variant={variant} />
        ))}
      </div>
      {conMasTalleres.map((inst) => (
        <Link
          key={`hub-${inst.id}`}
          to="/escuelas/instituciones/$slug"
          params={{ slug: inst.slug }}
          className={cn(
            "inline-flex w-fit items-center gap-1 text-sm font-semibold transition hover:text-rosa",
            variant === "dark" ? "text-background" : "text-ink",
          )}
        >
          Ver los {inst.talleres_count} talleres de {inst.nombre}
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      ))}
    </div>
  );
}
