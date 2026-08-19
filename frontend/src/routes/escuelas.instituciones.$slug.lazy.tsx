import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createLazyFileRoute } from "@tanstack/react-router";
import { Calendar, Instagram } from "lucide-react";

import { PublicLayout } from "@/components/rental/shell/PublicLayout";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { LogoMark } from "@/components/rental/shell/LogoMark";
import { InstitucionFotoHero } from "@/components/talleres/InstitucionFotoHero";
import { InstitucionHeroMultiple } from "@/components/talleres/InstitucionHeroMultiple";
import { TallerHubBlock } from "@/components/talleres/TallerHubBlock";
import { TALLER_CONTENT_WIDTH } from "@/components/talleres/TallerGaleria";
import { apiGetInstitucion } from "@/lib/api";
import { useBusinessContact } from "@/hooks/useBusinessContact";
import { cn } from "@/lib/utils";

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

  // Con foto destacada Y al menos 1 taller, el bloque de abajo (header
  // plano + empty state de "sin talleres") queda vacío — todo lo que
  // mostraría ya lo mostró InstitucionFotoHero arriba, o TallerHero/
  // InstitucionHeroMultiple abajo. Sin este chequeo, su padding dejaba un
  // hueco cream visible entre 2 secciones negras (confirmado en vivo).
  const bloqueMedioVacio =
    !isLoading && !isError && !!data && !!data.institucion.foto_destacada && talleres.length > 0;

  // Pedido del dueño 2026-08-19: "la foto esa de header + el listado de
  // talleres, que ocupe lo que ocupa la pantalla de alto dinámicamente,
  // así se ve toda la info y no se corta" — con foto Y switcher (2+
  // talleres) los dos comparten un mínimo de "1 pantalla" (mínimo, no
  // fijo: si el contenido real necesita más alto —descripción larga, 3+
  // talleres— crece más, no se recorta). Sin uno de los dos no hay
  // "combo" que encajar a pantalla completa — cada cual sigue solo, como
  // antes.
  const heroCombinado = esMultiple && !!data?.institucion.foto_destacada;
  // "1 pantalla" = el viewport MENOS el topbar (`h-16` = 4rem, fuente
  // única en TopBar.tsx — mismo alto siempre, sin variante responsive):
  // el wrapper vive DENTRO de <main>, debajo del topbar sticky de
  // PublicLayout, así que un `min-h-dvh` liso ahí contaba el 100% del
  // viewport DE NUEVO, después de los 4rem que ya se comió el topbar —
  // el combo terminaba más abajo del fondo de pantalla real (bug real,
  // confirmado en vivo: "me sigue quedando espacio solapado... por la
  // barra rosa de arriba").
  const HERO_COMBO_MIN_H = "calc(100dvh - 4rem)";

  return (
    <PublicLayout topBar={{ variant: "escuela" }}>
      <div className="min-h-dvh bg-background pb-16">
        {/* Hero con foto destacada — idea del dueño 2026-08-19: "ya que va a
            haber una galería de fotos por institución... hacer un hero con
            la foto destacada, que esté el logo y la info arriba de la
            foto". Solo si la institución cargó una (`institucion_fotos`,
            `es_principal`) — sin foto, el bloque de abajo sigue con el
            header plano de siempre. */}
        {data && activo && heroCombinado ? (
          <div className="flex flex-col" style={{ minHeight: HERO_COMBO_MIN_H }}>
            <InstitucionFotoHero
              institucion={data.institucion}
              h1SrOnly={talleres.length !== 1}
              className="flex-1"
            />
            <InstitucionHeroMultiple
              talleres={talleres}
              activoId={activo.taller_id}
              onSeleccionar={setActivoId}
              className="flex-1"
            />
          </div>
        ) : (
          data?.institucion.foto_destacada && (
            <InstitucionFotoHero institucion={data.institucion} h1SrOnly={talleres.length !== 1} />
          )
        )}
        <div
          className={cn("mx-auto flex flex-col gap-8", !bloqueMedioVacio && "py-10 sm:py-14")}
          style={{ width: TALLER_CONTENT_WIDTH }}
        >
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
              {/* Header plano de la institución — SOLO sin foto destacada
                  (con foto, `InstitucionFotoHero` de arriba ya muestra
                  logo/descripción/instagram sobre la foto; duplicarlo acá
                  abajo, otra vez, sería ruido). Mismo ancho que el hero de
                  abajo (TALLER_CONTENT_WIDTH, antes un max-w-[900px] angosto
                  y desalineado — pedido del dueño 2026-08-19: "que ocupe el
                  mismo ancho de abajo"), pero en `bg-background` (cream): el
                  fondo negro unificado se probó y se descartó el mismo día —
                  un párrafo largo en texto claro sobre negro se lee peor que
                  texto oscuro sobre claro. Con logo: SOLO el logo, centrado,
                  sin fondo ni texto al lado — el logo YA es un wordmark (ej.
                  "FILMAR") y ES el título visual de la página (mismo pedido,
                  con captura real: "que el logo no tenga fondo... y el texto
                  no esté"; "sacá también el título grande de abajo — ahora
                  el logo pasa a ser el título"). El h1 REAL de la página
                  (accesibilidad/SEO, no visual) va acá mismo como `sr-only`
                  salvo cuando hay exactamente 1 taller activo — ahí
                  `TallerHubBlock` renderiza `TallerHero`, que ya trae su
                  propio h1 visible con el nombre del taller. Sin logo
                  (fallback): ícono + "Talleres con" + h1 visible — no hay
                  wordmark que haga de identidad visual. */}
              {!data.institucion.foto_destacada && (
                <>
                  {data.institucion.logo_url ? (
                    <div className="flex flex-col items-center text-center">
                      {talleres.length !== 1 && (
                        <h1 className="sr-only">{data.institucion.nombre}</h1>
                      )}
                      <img
                        src={data.institucion.logo_url}
                        alt={data.institucion.nombre}
                        className="h-20 sm:h-24 w-auto max-w-full object-contain"
                      />
                    </div>
                  ) : (
                    <div className="flex items-center gap-4">
                      <div className="h-16 w-16 rounded-2xl bg-ink shrink-0 grid place-items-center">
                        <LogoMark className="h-9 w-9 text-rosa/70" />
                      </div>
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
                  )}

                  {data.institucion.descripcion && (
                    // Sin max-w-prose (65ch): con una descripción larga se
                    // leía angosta/apretada — usa el ancho completo de la
                    // columna.
                    <p className="text-muted-foreground text-sm leading-relaxed">
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
                </>
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

        {/* Contenido del/los taller(es) — FUERA del contenedor de arriba: el
            hero (bg-ink, edge-to-edge) necesita respirar igual que en su
            propia página individual, no encogido dentro de una card (su
            ancho interno igual coincide con el del header, vía la misma
            TALLER_CONTENT_WIDTH). */}
        {data && activo && (
          <>
            {/* Sin foto destacada, el switcher sigue en su lugar de
                siempre — el combo min-h-dvh de arriba solo aplica cuando
                HAY foto (`heroCombinado`); ya se renderizó ahí si
                corresponde, no de nuevo acá. */}
            {esMultiple && !heroCombinado && (
              <InstitucionHeroMultiple
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
