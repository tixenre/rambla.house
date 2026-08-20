import { Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import type { Taller } from "@/lib/api";

type InstitucionEntity = Taller["instituciones"][number];

function InstitucionPill({ institucion }: { institucion: InstitucionEntity }) {
  const content = (
    <>
      {institucion.logo_url && (
        <img
          src={institucion.logo_url}
          alt={institucion.nombre}
          className="h-5 w-auto max-w-16 object-contain"
        />
      )}
      <span className="text-sm font-medium text-ink">{institucion.nombre}</span>
    </>
  );
  const cls =
    "flex items-center gap-2 rounded-full border border-border/50 bg-muted/20 px-3 py-1.5 transition";
  if (institucion.web) {
    return (
      <a
        href={institucion.web}
        target="_blank"
        rel="noopener noreferrer"
        className={`${cls} hover:border-border`}
      >
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
export function InstitucionesRow({ taller }: { taller: Taller }) {
  if (taller.instituciones.length === 0) return null;
  const conMasTalleres = taller.instituciones.filter((i) => (i.talleres_count ?? 0) > 1);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-xs font-mono uppercase tracking-widest text-muted-foreground shrink-0">
          Presentado por
        </p>
        {taller.instituciones.map((inst) => (
          <InstitucionPill key={inst.id} institucion={inst} />
        ))}
      </div>
      {conMasTalleres.map((inst) => (
        <Link
          key={`hub-${inst.id}`}
          to="/escuelas/instituciones/$slug"
          params={{ slug: inst.slug }}
          className="inline-flex w-fit items-center gap-1 text-sm font-semibold text-ink hover:text-rosa transition"
        >
          Ver los {inst.talleres_count} talleres de {inst.nombre}
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      ))}
    </div>
  );
}
