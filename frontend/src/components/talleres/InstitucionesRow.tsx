import { Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Taller } from "@/lib/api";

type Variant = "light" | "dark";

/** Eyebrow de arriba del H1 (`TallerHero`, función `Titulo`): "Taller" en
 * rosa por default — o el logo (nombre en texto si no hay logo cargado) de
 * la/s institución/es co-presentadoras cuando el taller tiene alguna.
 * Pedido del dueño 2026-08-20: "que el logo esté donde dice taller en
 * rosa" — el logo pasa al lugar más prominente de la jerarquía (lo primero
 * que se lee, antes del título), reemplazando el pill que vivía después
 * del CTA (ver `InstitucionesRow` más abajo, que ahora solo linkea).
 *
 * `ocultarInstituciones` (la institución en SU PROPIO hub, ver
 * `TallerHubBlock`) cae al "Taller" de siempre — mostrar su propio logo
 * ahí sería la misma circularidad que ya evita el resto de esta fila. Sin
 * logo cargado, el nombre queda de fallback con el mismo tratamiento
 * tipográfico (mono, rosa, tracking ancho) que el eyebrow que reemplaza —
 * nunca deja un hueco vacío arriba del título. */
export function InstitucionEyebrow({
  taller,
  ocultarInstituciones = false,
  size = "lg",
}: {
  taller: Taller;
  ocultarInstituciones?: boolean;
  // "lg" = hero del taller (default, sin cambios). "sm" = eyebrow de una
  // card compacta (ej. WorkshopCard del listado /escuelas) — mismo
  // componente, logo más chico para no pesar más que el título de la card.
  size?: "lg" | "sm";
}) {
  const mb = size === "lg" ? "mb-4" : "mb-2";
  if (ocultarInstituciones || taller.instituciones.length === 0) {
    return (
      <p className={`font-mono text-2xs tracking-[0.3em] uppercase text-rosa ${mb}`}>Taller</p>
    );
  }
  return (
    <div className={`flex flex-wrap items-center gap-3 ${mb}`}>
      {taller.instituciones.map((inst) => (
        <Link
          key={inst.id}
          to="/escuelas/instituciones/$slug"
          params={{ slug: inst.slug }}
          aria-label={`Presentado por ${inst.nombre}`}
          className="transition hover:opacity-70"
        >
          {inst.logo_url ? (
            // Logo desnudo — sin caja/borde alrededor: mismo tratamiento
            // que `InstitucionFotoHero` (el hero propio de la institución).
            // Un pill con borde se leía como "otro botón" compitiendo con
            // el CTA rosa (feedback del dueño en vivo, con captura: "queda
            // chico, raro con muchas cajitas chiquitas, no parece
            // integrado al diseño") — mismo criterio acá.
            <img
              src={inst.logo_url}
              alt={inst.nombre}
              className={
                size === "lg"
                  ? "h-8 sm:h-10 w-auto max-w-[9rem] object-contain"
                  : "h-5 w-auto max-w-[6rem] object-contain"
              }
            />
          ) : (
            <span className="font-mono text-2xs tracking-[0.3em] uppercase text-rosa">
              {inst.nombre}
            </span>
          )}
        </Link>
      ))}
    </div>
  );
}

/** Debajo del CTA del hero: si alguna institución co-presentadora tiene MÁS
 * de 1 taller activo, un link al hub ("Ver los N talleres") — pedido del
 * dueño 2026-08-20: quien aterriza directo en un taller (no por el hub) no
 * tenía forma de enterarse de que su institución ofrece más. El logo que
 * identifica CUÁL institución ya se muestra arriba del título
 * (`InstitucionEyebrow`) — acá no se repite, solo el link. Con exactamente
 * 1 taller no se muestra: el hub mostraría ese mismo taller, un click sin
 * destino nuevo. Data-driven: sin instituciones con 2+ talleres, no se
 * muestra nada. */
export function InstitucionesRow({
  taller,
  variant = "light",
  className,
}: {
  taller: Taller;
  // "dark" = sobre el hero (bg-ink) — usado por TallerHero, único lugar
  // donde se muestra esta fila. El default "light" queda por si se reusa
  // en un contexto claro a futuro.
  variant?: Variant;
  // El caller pone su propio margen acá (no en un wrapper aparte) — así,
  // sin nada que mostrar, el `return null` de abajo no deja un wrapper con
  // margen vacío colgando en el hero.
  className?: string;
}) {
  const conMasTalleres = taller.instituciones.filter((i) => (i.talleres_count ?? 0) > 1);
  if (conMasTalleres.length === 0) return null;
  return (
    <div className={cn("flex flex-col gap-2", className)}>
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
