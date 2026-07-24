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
 * resto de los talleres sin institución siguen viéndose igual que siempre). */
export function InstitucionesRow({ taller }: { taller: Taller }) {
  if (taller.instituciones.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-3">
      <p className="text-xs font-mono uppercase tracking-widest text-muted-foreground shrink-0">
        Presentado por
      </p>
      {taller.instituciones.map((inst) => (
        <InstitucionPill key={inst.id} institucion={inst} />
      ))}
    </div>
  );
}
