import type { Taller } from "@/lib/api";

type InstructorEntity = Taller["instructores"][number];

function proyectosDe(instructor: InstructorEntity): string[] {
  if (!instructor.proyectos) return [];
  return instructor.proyectos
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function InstructorFoto({ instructor }: { instructor: InstructorEntity }) {
  if (!instructor.foto_url) return null;
  return (
    <img
      src={instructor.foto_url}
      alt={instructor.nombre}
      loading="lazy"
      className="shrink-0 w-16 h-16 rounded-full object-cover object-top border border-border/40"
    />
  );
}

/**
 * "Sobre" — 1 instructor mantiene el layout actual (foto grande + nombre +
 * bio + chips "trabajó con", desde `instructor.proyectos`); N instructores
 * pasa a grid de cards. Data-driven, no una variante por `tipo_taller`.
 */
export function InstructorCard({ taller }: { taller: Taller }) {
  const instructores = taller.instructores;
  if (instructores.length === 0) return null;

  if (instructores.length === 1) {
    const ins = instructores[0];
    const proyectos = proyectosDe(ins);
    return (
      <section className="rounded-2xl border border-border/60 bg-muted/20 px-6 py-7">
        <p className="font-mono text-2xs tracking-[0.25em] uppercase text-muted-foreground mb-4">
          Sobre
        </p>
        <div className="flex items-start gap-5 mb-5">
          <InstructorFoto instructor={ins} />
          <h2
            className="font-display font-black lowercase leading-[0.9] tracking-[-0.02em] text-ink self-center"
            style={{ fontSize: "clamp(1.75rem, 3.5vw, 2.5rem)" }}
          >
            {ins.nombre}
          </h2>
        </div>
        <p className="text-base text-ink/80 leading-relaxed">{ins.descripcion}</p>
        {proyectos.length > 0 && (
          <div className="mt-6">
            <p className="font-mono text-2xs tracking-[0.2em] uppercase text-muted-foreground mb-3">
              Trabajó con
            </p>
            <div className="flex flex-wrap gap-2">
              {proyectos.map((p) => (
                <span
                  key={p}
                  className="inline-block rounded-full border border-border/60 bg-background px-3 py-1 text-xs font-medium text-ink/70"
                >
                  {p}
                </span>
              ))}
            </div>
          </div>
        )}
      </section>
    );
  }

  return (
    <section>
      <p className="font-mono text-2xs tracking-[0.25em] uppercase text-rosa mb-4">Instructores</p>
      <div className="grid sm:grid-cols-2 gap-4">
        {instructores.map((ins) => (
          <div
            key={ins.id}
            className="rounded-2xl border border-border/60 bg-muted/20 px-5 py-5 flex flex-col gap-3"
          >
            <div className="flex items-center gap-3">
              <InstructorFoto instructor={ins} />
              <div className="min-w-0">
                <p className="font-display text-lg font-bold text-ink lowercase truncate">
                  {ins.nombre}
                </p>
                {ins.rol && <p className="text-xs text-rosa font-medium">{ins.rol}</p>}
              </div>
            </div>
            {ins.descripcion && (
              <p className="text-sm text-muted-foreground leading-relaxed">{ins.descripcion}</p>
            )}
            {(ins.instagram || ins.web) && (
              <div className="flex gap-3 text-xs">
                {ins.instagram && (
                  <a
                    href={`https://instagram.com/${ins.instagram.replace(/^@/, "")}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-ink font-medium hover:text-rosa transition"
                  >
                    @{ins.instagram.replace(/^@/, "")}
                  </a>
                )}
                {ins.web && (
                  <a
                    href={ins.web}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-muted-foreground hover:text-ink transition"
                  >
                    Portfolio
                  </a>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
