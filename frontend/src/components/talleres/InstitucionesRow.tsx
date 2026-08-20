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
  return (
    <Link
      to="/escuelas/instituciones/$slug"
      params={{ slug: institucion.slug }}
      aria-label={institucion.nombre}
      className="transition hover:opacity-70"
    >
      {institucion.logo_url ? (
        // Logo desnudo — sin caja/borde alrededor: mismo tratamiento que
        // `InstitucionFotoHero` (el hero propio de la institución), la
        // única otra superficie que muestra este logo sobre fondo oscuro.
        // Un pill con borde acá se leía como "otro botón" compitiendo con
        // el CTA rosa, no como parte del diseño (feedback del dueño en
        // vivo, con captura: "queda chico, raro con muchas cajitas
        // chiquitas, no parece integrado al diseño").
        <img
          src={institucion.logo_url}
          alt={institucion.nombre}
          className="h-7 w-auto max-w-28 object-contain"
        />
      ) : (
        // Sin logo cargado: el nombre queda como texto plano con
        // subrayado al hover — mismo lenguaje de link que "Ver los N
        // talleres" de abajo, no una caja aparte.
        <span
          className={cn(
            "text-sm font-medium underline-offset-4 hover:underline",
            variant === "dark" ? "text-background" : "text-ink",
          )}
        >
          {institucion.nombre}
        </span>
      )}
    </Link>
  );
}

/** "Presentado por" — instituciones co-presentadoras (ej. "Rambla" + "Filmar").
 * Data-driven: sin instituciones vinculadas, no se muestra nada (Jime y el
 * resto de los talleres sin institución siguen viéndose igual que siempre).
 *
 * El pill es SOLO el logo (sin nombre al lado — pedido del dueño
 * 2026-08-20, "no le pondría el texto al lado del logo") y clickeable
 * hacia el hub interno (`/escuelas/instituciones/$slug`, no `institucion.web`
 * — siempre existe, a diferencia de la web externa, que muchas instituciones
 * no cargan). Sin logo cargado, el nombre queda de fallback visible (mismo
 * destino) para que el pill nunca se vea vacío.
 *
 * Debajo, si alguna institución tiene MÁS de 1 taller activo, un segundo
 * link al mismo hub ("Ver los N talleres", sin repetir el nombre — el logo
 * de arriba ya identifica cuál institución) — pedido del dueño 2026-08-20:
 * quien aterriza directo en un taller (no por el hub) no tenía forma de
 * enterarse de que su institución ofrece más. Con exactamente 1 taller no
 * se muestra: el hub mostraría ese mismo taller, un click sin destino
 * nuevo (el logo de arriba igual lleva ahí). */
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
          Ver los {inst.talleres_count} talleres
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      ))}
    </div>
  );
}
