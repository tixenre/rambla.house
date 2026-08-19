import { useQuery } from "@tanstack/react-query";
import { createLazyFileRoute } from "@tanstack/react-router";
import { Calendar, Instagram } from "lucide-react";

import { PublicLayout } from "@/components/rental/shell/PublicLayout";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { LogoMark } from "@/components/rental/shell/LogoMark";
import { TallerHubBlock } from "@/components/talleres/TallerHubBlock";
import { apiGetInstitucion, type Taller } from "@/lib/api";
import { useBusinessContact } from "@/hooks/useBusinessContact";

export const Route = createLazyFileRoute("/escuelas/instituciones/$slug")({
  component: InstitucionPage,
});

/**
 * Cuando 2 talleres de la MISMA institución son "hermanos" entre sí (pareja
 * de marketing, ej. los 2 niveles de Filmar), el hero de pareja de
 * `TallerHubBlock` ya arma el link "Ver este taller" hacia el otro lado —
 * mostrar los DOS bloques completos apilados sería redundante (pedido
 * explícito del dueño: "hero compartido + solo el taller activo abajo").
 * Se queda solo con el primero de cada par (el orden ya viene de
 * `ti.orden`, el que el admin definió al vincularlos a la institución); un
 * taller sin hermano, o cuyo hermano no pertenece a esta institución, se
 * muestra igual, suelto. */
function dedupHermanos(talleres: Taller[]): Taller[] {
  const idsEnEstaInstitucion = new Set(talleres.map((t) => t.taller_id));
  const yaCubierto = new Set<number>();
  return talleres.filter((t) => {
    if (yaCubierto.has(t.taller_id)) return false;
    const hermano = t.taller_hermano;
    if (hermano) {
      const otroId =
        hermano.principal.taller_id === t.taller_id
          ? hermano.secundario.taller_id
          : hermano.principal.taller_id;
      if (idsEnEstaInstitucion.has(otroId)) yaCubierto.add(otroId);
    }
    return true;
  });
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
              {/* Header de la institución — angosto y centrado, a diferencia
                  de los bloques de taller que van edge-to-edge más abajo
                  (cada uno arranca con su propio hero de página completa). */}
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

              {data.talleres.length === 0 && (
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

        {/* Bloques de taller completos — FUERA del max-w de arriba: cada uno
            necesita que su hero (bg-ink, edge-to-edge) respire igual que en
            su propia página individual, no encogido dentro de una card.
            dedupHermanos: un par (ej. Nivel 1 + Nivel 2) se muestra UNA vez,
            no 2 heroes completos apilados. */}
        {data && data.talleres.length > 0 && (
          <div className="flex flex-col gap-20 mt-8">
            {dedupHermanos(data.talleres).map((t) => (
              <TallerHubBlock key={t.id} taller={t} />
            ))}
          </div>
        )}
      </div>
    </PublicLayout>
  );
}
