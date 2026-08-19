import { useQuery } from "@tanstack/react-query";
import { createLazyFileRoute, Link } from "@tanstack/react-router";
import { Calendar, Instagram, Users } from "lucide-react";

import { PublicLayout } from "@/components/rental/shell/PublicLayout";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { LogoMark } from "@/components/rental/shell/LogoMark";
import { SeccionCard } from "@/components/talleres/SeccionCard";
import { WorkshopInscripcionForm } from "@/components/talleres/WorkshopInscripcionForm";
import { apiGetInstitucion, type Taller } from "@/lib/api";
import { formatARS } from "@/lib/format";
import { useBusinessContact } from "@/hooks/useBusinessContact";

export const Route = createLazyFileRoute("/escuelas/instituciones/$slug")({
  component: InstitucionPage,
});

function fechaRango(t: Taller): string {
  const inicio = new Date(t.fecha_inicio + "T12:00:00");
  const fin = new Date(t.fecha_fin + "T12:00:00");
  const opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "long" };
  return inicio.getTime() === fin.getTime()
    ? inicio.toLocaleDateString("es-AR", opts)
    : `${inicio.toLocaleDateString("es-AR", opts)} – ${fin.toLocaleDateString("es-AR", opts)}`;
}

function TallerBlock({ taller }: { taller: Taller }) {
  const soldOut = taller.cupos_disponibles === 0;
  const cuposLabel = soldOut
    ? "Lista de espera"
    : `${taller.cupos_disponibles} lugar${taller.cupos_disponibles === 1 ? "" : "es"} disponible${taller.cupos_disponibles === 1 ? "" : "s"}`;

  return (
    <SeccionCard eyebrow="Taller" className="flex flex-col gap-6">
      <div>
        <Link
          to="/escuelas/$slug"
          params={{ slug: taller.slug }}
          className="font-display font-black lowercase leading-[0.95] tracking-[-0.015em] text-ink hover:text-rosa transition-colors"
          style={{ fontSize: "clamp(1.3rem, 2.4vw, 1.75rem)" }}
        >
          {taller.nombre}
        </Link>
        {taller.subtitulo && (
          <p className="text-muted-foreground mt-1 text-sm">{taller.subtitulo}</p>
        )}
        <div className="flex flex-wrap gap-x-5 gap-y-1.5 text-sm text-muted-foreground mt-3">
          <span className="flex items-center gap-1.5 font-semibold text-ink">
            <Calendar className="h-4 w-4 shrink-0" />
            {fechaRango(taller)}
            <span className="text-muted-foreground font-normal">· {taller.horario}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <Users className="h-3.5 w-3.5 shrink-0" />
            {cuposLabel}
          </span>
          <span className="font-semibold text-ink">{formatARS(taller.precio_total)}</span>
        </div>
      </div>

      <div id={`inscripcion-${taller.slug}`}>
        <WorkshopInscripcionForm taller={taller} />
      </div>
    </SeccionCard>
  );
}

function InstitucionPage() {
  const { slug } = Route.useParams();
  const contact = useBusinessContact();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["institucion", slug],
    queryFn: () => apiGetInstitucion(slug),
    staleTime: 1000 * 60 * 5,
  });

  return (
    <PublicLayout topBar={{ variant: "escuela" }}>
      <div className="min-h-dvh bg-background pb-16">
        <div className="max-w-[900px] mx-auto px-4 sm:px-6 py-10 sm:py-14 flex flex-col gap-8">
          {isLoading && (
            <div className="py-16 text-center text-muted-foreground text-sm">Cargando…</div>
          )}
          {(isError || (!isLoading && !data)) && (
            <EmptyState
              icon={<Calendar className="h-6 w-6" />}
              title="No encontramos esta institución"
              sub="El link puede estar mal escrito o la institución ya no está activa."
            />
          )}

          {data && (
            <>
              {/* Header de la institución */}
              <div className="flex items-center gap-4">
                {data.institucion.logo_url ? (
                  <img
                    src={data.institucion.logo_url}
                    alt={data.institucion.nombre}
                    className="h-16 w-16 rounded-2xl object-contain bg-muted/30 shrink-0"
                  />
                ) : (
                  <div className="h-16 w-16 rounded-2xl bg-ink shrink-0 grid place-items-center">
                    <LogoMark className="h-9 w-9 text-rosa/70" />
                  </div>
                )}
                <div className="min-w-0">
                  <p className="font-mono text-2xs tracking-[0.25em] uppercase text-rosa mb-1">
                    Talleres con
                  </p>
                  <h1
                    className="font-display font-black lowercase leading-[0.95] tracking-[-0.015em] text-ink"
                    style={{ fontSize: "clamp(1.6rem, 3.5vw, 2.4rem)" }}
                  >
                    {data.institucion.nombre}
                  </h1>
                </div>
              </div>

              {data.institucion.descripcion && (
                <p className="text-muted-foreground text-sm leading-relaxed max-w-prose">
                  {data.institucion.descripcion}
                </p>
              )}

              {data.institucion.instagram && (
                <a
                  href={`https://instagram.com/${data.institucion.instagram}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink hover:text-rosa transition -mt-4 w-fit"
                >
                  <Instagram className="h-4 w-4" />@{data.institucion.instagram}
                </a>
              )}

              {data.talleres.length === 0 ? (
                <EmptyState
                  icon={<Calendar className="h-6 w-6" />}
                  title="No hay talleres activos por el momento"
                  sub="Seguinos en Instagram para enterarte de los próximos."
                >
                  <a
                    href={`https://instagram.com/${contact.instagram}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm font-semibold text-ink hover:text-rosa transition"
                  >
                    @{contact.instagram}
                  </a>
                </EmptyState>
              ) : (
                <div className="flex flex-col gap-6">
                  {data.talleres.map((t) => (
                    <TallerBlock key={t.id} taller={t} />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </PublicLayout>
  );
}
