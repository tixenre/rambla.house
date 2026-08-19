import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createLazyFileRoute } from "@tanstack/react-router";
import { Calendar, Instagram } from "lucide-react";

import { PublicLayout } from "@/components/rental/shell/PublicLayout";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { LogoMark } from "@/components/rental/shell/LogoMark";
import { InstitucionHeroMultiple } from "@/components/talleres/InstitucionHeroMultiple";
import { TallerHubBlock } from "@/components/talleres/TallerHubBlock";
import { apiGetInstitucion } from "@/lib/api";
import { useBusinessContact } from "@/hooks/useBusinessContact";

export const Route = createLazyFileRoute("/escuelas/instituciones/$slug")({
  component: InstitucionPage,
});

function InstitucionPage() {
  const { slug } = Route.useParams();
  const contact = useBusinessContact();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["institucion", slug],
    queryFn: () => apiGetInstitucion(slug),
    staleTime: 1000 * 60 * 5,
  });

  // Layout por CANTIDAD de talleres — reemplaza el "taller hermano" (solo
  // pares) retirado (pedido del dueño 2026-08-19: "esa página compartida lo
  // haría cuando seleccionás la institución… si tiene 2 o más, mostrá la
  // página múltiple. Sino el que tenga solo"). 2+ → hero compartido con
  // selector N-way + el activo abajo; 1 → ese taller tal cual, con su
  // propio hero normal (TallerHubBlock sin `ocultarHero`).
  const talleres = data?.talleres ?? [];
  const esMultiple = talleres.length >= 2;
  const [activoId, setActivoId] = useState<number | null>(null);
  const activo = talleres.find((t) => t.taller_id === activoId) ?? talleres[0];

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
              {/* Header de la institución — angosto y centrado, a diferencia
                  del hero de abajo (bg-ink, edge-to-edge). */}
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

              {talleres.length === 0 && (
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
              )}
            </>
          )}
        </div>

        {/* Contenido del/los taller(es) — FUERA del max-w de arriba: el hero
            (bg-ink, edge-to-edge) necesita respirar igual que en su propia
            página individual, no encogido dentro de una card. */}
        {data && activo && (
          <>
            {esMultiple && (
              <InstitucionHeroMultiple
                institucion={data.institucion}
                talleres={talleres}
                activoId={activo.taller_id}
                onSeleccionar={setActivoId}
              />
            )}
            <TallerHubBlock key={activo.id} taller={activo} ocultarHero={esMultiple} />
          </>
        )}
      </div>
    </PublicLayout>
  );
}
