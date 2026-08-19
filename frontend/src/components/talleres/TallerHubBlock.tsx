import { DescripcionBloques, DescripcionRica } from "@/components/talleres/DescripcionRica";
import { InstructorCard } from "@/components/talleres/InstructorCard";
import { InteresadoForm } from "@/components/talleres/InteresadoForm";
import { ProgramaSection } from "@/components/talleres/ProgramaSection";
import { SeccionCard } from "@/components/talleres/SeccionCard";
import { TallerCalendario } from "@/components/talleres/TallerCalendario";
import { TallerFAQ } from "@/components/talleres/TallerFAQ";
import { TallerGaleria, TALLER_CONTENT_WIDTH } from "@/components/talleres/TallerGaleria";
import { TallerHero } from "@/components/talleres/TallerHero";
import { TallerTrabajos } from "@/components/talleres/TallerTrabajos";
import { WorkshopInscripcionForm } from "@/components/talleres/WorkshopInscripcionForm";
import { parseDescripcionRica, splitEnPrograma } from "@/lib/talleres/descripcionRica";
import { ordinalEdicion, resumenFechas, resumenHorario } from "@/lib/talleres/formato";
import type { Taller } from "@/lib/api";

/**
 * Contenido COMPLETO de un taller (hero + galería + cuerpo + FAQ), para
 * embeber uno o más talleres enteros en el hub de institución
 * (`/escuelas/instituciones/$slug`, pedido explícito del dueño: "me
 * gustaría que se vean los formularios/página completos", no un resumen).
 *
 * Espeja la composición de `escuelas.$slug.lazy.tsx` (la página individual)
 * — un reorden de bloques en una se replica en la otra, para que no
 * diverjan — con 2 recortes a propósito para el contexto "puede haber más
 * de un taller en la página":
 *   - `anchorSuffix={taller.slug}` en el hero: sin esto, el CTA de cada hero
 *     apuntaría al mismo "#inscripcion" (colisión — el de abajo scrollearía
 *     al form de arriba).
 *   - Sin `InstitucionesRow` (se leería "Presentado por: Filmar" adentro de
 *     la propia página de Filmar) ni `SoldOutModal`/`TallerCTABar` (pensados
 *     para una página con un solo taller).
 *
 * `showHermano` NO se pisa (queda en su default `true`): si el taller tiene
 * "taller hermano" (pareja de marketing, ej. los 2 niveles de Filmar), el
 * hero SÍ muestra el banner de pareja compartido — pedido explícito del
 * dueño tras ver el hub con 2 heroes completos apilados ("lo pensaba más en
 * este estilo", con captura del banner de pareja). El caller
 * (`escuelas.instituciones.$slug.lazy.tsx`) deduplica: cuando 2 talleres de
 * la misma institución son hermanos entre sí, solo renderiza UNO completo
 * (el "activo", con el hero de pareja); el otro se alcanza por el link
 * "Ver este taller" que el propio hero de pareja ya arma — no hay 2 cuerpos
 * completos apilados para un par. Talleres sueltos (sin hermano, o cuyo
 * hermano no pertenece a esta institución) se siguen mostrando cada uno con
 * su propio hero normal, sin pareja.
 */
export function TallerHubBlock({ taller }: { taller: Taller }) {
  const proxima = taller.proxima_edicion;
  const isFrozen = taller.frozen_at != null;
  const isFullySoldOut = !isFrozen && taller.cupos_disponibles === 0 && proxima == null;
  const switchToProxima =
    !isFrozen && taller.cupos_disponibles === 0 && proxima != null && proxima.cupos_disponibles > 0;
  const formTaller: Taller = switchToProxima ? ({ ...taller, ...proxima } as Taller) : taller;

  const optsLong: Intl.DateTimeFormatOptions = { weekday: "long", day: "numeric", month: "long" };
  const fechaInicio = new Date(formTaller.fecha_inicio + "T12:00:00");
  const fechaFin = new Date(formTaller.fecha_fin + "T12:00:00");
  const fechaInicioStr = fechaInicio.toLocaleDateString("es-AR", optsLong);
  const fechaFinStr = fechaFin.toLocaleDateString("es-AR", optsLong);

  const clases = formTaller.sesiones;
  const fechasResumen = resumenFechas(clases, fechaInicioStr, fechaFinStr);
  const horarioResumen = resumenHorario(clases, formTaller.horario);

  const { antes: bloquesDescripcion, programa: bloquesPrograma } = splitEnPrograma(
    parseDescripcionRica(taller.descripcion),
  );

  const anchorId = `inscripcion-${taller.slug}`;

  return (
    <div>
      {taller.borrador && (
        <div className="bg-amber text-ink text-center text-sm font-semibold px-4 py-2">
          Borrador — solo visible para vos. Publicalo desde el admin cuando esté listo.
        </div>
      )}

      <TallerHero
        taller={taller}
        formTaller={formTaller}
        fechasResumen={fechasResumen}
        horarioResumen={horarioResumen}
        anchorSuffix={taller.slug}
      />

      <TallerGaleria fotos={formTaller.fotos} alt={taller.nombre} />

      <div className="mx-auto py-12 sm:py-16 bg-background" style={{ width: TALLER_CONTENT_WIDTH }}>
        <div className="grid lg:grid-cols-[1fr_380px] gap-10 lg:gap-16 items-start">
          <div className="flex flex-col gap-12">
            <SeccionCard eyebrow="De qué se trata">
              <DescripcionBloques
                bloques={bloquesDescripcion}
                className="text-lg sm:text-xl text-muted-foreground"
              />
            </SeccionCard>

            {taller.publico_objetivo && (
              <SeccionCard eyebrow="Orientado a">
                <DescripcionRica
                  texto={taller.publico_objetivo}
                  className="text-base text-muted-foreground"
                />
              </SeccionCard>
            )}

            {bloquesPrograma && bloquesPrograma.length > 0 && (
              <SeccionCard eyebrow="Programa">
                <DescripcionBloques
                  bloques={bloquesPrograma}
                  className="text-base text-muted-foreground"
                />
              </SeccionCard>
            )}
            <ProgramaSection clases={clases} />

            {formTaller.sesiones.length > 0 && (
              <TallerCalendario sesiones={formTaller.sesiones} horario={formTaller.horario} />
            )}

            <InstructorCard taller={taller} />
            <TallerTrabajos trabajos={taller.trabajos} />
          </div>

          <div className="lg:sticky lg:top-20">
            <div id={anchorId} className="scroll-mt-20">
              {isFrozen ? (
                <div className="rounded-2xl border border-border/60 bg-muted/20 px-5 py-6 text-center">
                  <p className="text-sm font-medium text-ink mb-1">Inscripciones cerradas</p>
                  <p className="text-xs text-muted-foreground">
                    Esta edición ya no acepta nuevas inscripciones.
                  </p>
                </div>
              ) : isFullySoldOut ? (
                <>
                  <div className="mb-4 rounded-xl border border-border/60 bg-ink px-4 py-3 text-background">
                    <p className="text-xs font-mono uppercase tracking-widest opacity-50 mb-0.5">
                      {ordinalEdicion(taller.numero_edicion)} edición
                    </p>
                    <p className="font-bold text-sm">Sold out</p>
                    <p className="text-xs opacity-60 mt-1">Sin fechas próximas por ahora.</p>
                  </div>
                  <InteresadoForm slug={taller.slug} />
                </>
              ) : (
                <>
                  {switchToProxima && (
                    <div className="mb-4 rounded-xl border border-border/60 bg-ink px-4 py-3 text-background">
                      <p className="text-xs font-mono uppercase tracking-widest opacity-50 mb-0.5">
                        {ordinalEdicion(taller.numero_edicion)} edición
                      </p>
                      <p className="font-bold text-sm">Sold out</p>
                      <p className="text-xs opacity-60 mt-1">
                        Te anotamos en la {ordinalEdicion(proxima!.numero_edicion)} edición (
                        {new Date(proxima!.fecha_inicio + "T12:00:00").toLocaleDateString("es-AR", {
                          day: "numeric",
                          month: "long",
                        })}{" "}
                        y{" "}
                        {new Date(proxima!.fecha_fin + "T12:00:00").toLocaleDateString("es-AR", {
                          day: "numeric",
                          month: "long",
                        })}
                        )
                      </p>
                    </div>
                  )}
                  <WorkshopInscripcionForm taller={formTaller} />
                </>
              )}
            </div>
          </div>
        </div>

        <div className="mt-16 flex flex-col gap-12">
          <TallerFAQ faqs={taller.faqs} />
        </div>
      </div>
    </div>
  );
}
