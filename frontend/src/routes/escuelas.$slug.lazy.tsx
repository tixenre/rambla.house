import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createLazyFileRoute, Link, notFound } from "@tanstack/react-router";
import { X } from "lucide-react";

import { PublicLayout } from "@/components/rental/shell/PublicLayout";
import { Button } from "@/design-system/ui/button";
import { IconButton } from "@/design-system/ui/icon-button";
import { ModalBackdrop } from "@/design-system/ui/modal-backdrop";
import { InteresadoForm } from "@/components/talleres/InteresadoForm";
import { WorkshopInscripcionForm } from "@/components/talleres/WorkshopInscripcionForm";
import { DescripcionRica, DescripcionBloques } from "@/components/talleres/DescripcionRica";
import { SeccionCard } from "@/components/talleres/SeccionCard";
import { parseDescripcionRica, splitEnPrograma } from "@/lib/talleres/descripcionRica";
import { TallerHero } from "@/components/talleres/TallerHero";
import { TallerGaleria, TALLER_CONTENT_WIDTH } from "@/components/talleres/TallerGaleria";
import { TallerCalendario } from "@/components/talleres/TallerCalendario";
import { ProgramaSection } from "@/components/talleres/ProgramaSection";
import { InstructorCard } from "@/components/talleres/InstructorCard";
import { InstitucionesRow } from "@/components/talleres/InstitucionesRow";
import { TallerTrabajos } from "@/components/talleres/TallerTrabajos";
import { TallerFAQ } from "@/components/talleres/TallerFAQ";
import { TallerCTABar } from "@/components/talleres/TallerCTABar";
import { apiGetTaller, type EdicionLite, type Taller } from "@/lib/api";
import { ordinalEdicion, resumenFechas, resumenHorario } from "@/lib/talleres/formato";

export const Route = createLazyFileRoute("/escuelas/$slug")({
  component: TallerLandingPage,
});

function SoldOutModal({
  proxima,
  currentEdicion,
  onDismiss,
}: {
  proxima: EdicionLite;
  currentEdicion: number;
  onDismiss: () => void;
}) {
  const opts: Intl.DateTimeFormatOptions = { weekday: "long", day: "numeric", month: "long" };
  const fechaA = new Date(proxima.fecha_inicio + "T12:00:00").toLocaleDateString("es-AR", opts);
  const fechaB = new Date(proxima.fecha_fin + "T12:00:00").toLocaleDateString("es-AR", opts);
  const labelActual = ordinalEdicion(currentEdicion);
  const labelProxima = ordinalEdicion(proxima.numero_edicion);
  return (
    <ModalBackdrop
      className="z-50 flex items-end sm:items-center justify-center bg-scrim p-4 sm:p-6"
      onClose={onDismiss}
    >
      <div className="relative w-full max-w-sm rounded-2xl bg-background border border-border/60 p-7 shadow-2xl">
        <IconButton
          aria-label="Cerrar"
          size="sm"
          onClick={onDismiss}
          className="absolute top-4 right-4 rounded-full text-muted-foreground hover:text-ink hover:bg-muted"
        >
          <X className="h-4 w-4" />
        </IconButton>
        <p className="font-mono text-2xs tracking-[0.25em] uppercase text-rosa mb-3">
          {labelActual} edición
        </p>
        <h2
          className="font-display font-bold lowercase text-ink leading-tight mb-2"
          style={{ fontSize: "1.6rem" }}
        >
          los cupos se agotaron
        </h2>
        <p className="text-sm text-muted-foreground mb-6">
          Pero hay lugar en la <strong className="text-ink">{labelProxima} edición</strong> —{" "}
          {fechaA} y {fechaB}.
        </p>
        <Link
          to="/escuelas/$slug"
          params={{ slug: proxima.slug }}
          className="flex items-center justify-center w-full rounded-full bg-rosa text-ink font-bold py-3 hover:brightness-110 active:scale-[0.97] transition-all"
          onClick={onDismiss}
        >
          Inscribirme en la {labelProxima} edición
        </Link>
        <button
          onClick={onDismiss}
          className="w-full mt-3 text-sm text-muted-foreground hover:text-ink transition py-1"
        >
          Cerrar
        </button>
      </div>
    </ModalBackdrop>
  );
}

// ── TallerLandingPage ─────────────────────────────────────────────────────────

function TallerLandingPage() {
  const { slug } = Route.useParams();
  const {
    data: taller,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["taller", slug],
    queryFn: () => apiGetTaller(slug),
    staleTime: 0,
  });

  // Hooks antes del early-return (regla de hooks de React)
  const [soldOutModalDismissed, setSoldOutModalDismissed] = useState(false);

  if (isLoading) {
    return (
      <div className="min-h-dvh flex items-center justify-center text-muted-foreground text-sm">
        Cargando…
      </div>
    );
  }

  if (isError || !taller) {
    throw notFound();
  }

  const proxima = taller.proxima_edicion;
  const isFrozen = taller.frozen_at != null;
  const isFullySoldOut = !isFrozen && taller.cupos_disponibles === 0 && proxima == null;
  const switchToProxima =
    !isFrozen && taller.cupos_disponibles === 0 && proxima != null && proxima.cupos_disponibles > 0;
  const formTaller: Taller = switchToProxima ? ({ ...taller, ...proxima } as Taller) : taller;

  // Cuando está sold out, las fechas de toda la página muestran la 2da edición
  const optsLong: Intl.DateTimeFormatOptions = { weekday: "long", day: "numeric", month: "long" };
  const fechaInicio = new Date(formTaller.fecha_inicio + "T12:00:00");
  const fechaFin = new Date(formTaller.fecha_fin + "T12:00:00");
  const fechaInicioStr = fechaInicio.toLocaleDateString("es-AR", optsLong);
  const fechaFinStr = fechaFin.toLocaleDateString("es-AR", optsLong);

  const clases = formTaller.sesiones;
  const fechasResumen = resumenFechas(clases, fechaInicioStr, fechaFinStr);
  const horarioResumen = resumenHorario(clases, formTaller.horario);

  // El programa a veces viene redactado como parte del texto libre de la
  // descripción (un título "# Programa" seguido de la lista), en vez de
  // cargado clase-por-clase (`ProgramaSection`, más abajo) — separado en su
  // propia card en vez de mezclado con "De qué se trata" (pedido explícito).
  const { antes: bloquesDescripcion, programa: bloquesPrograma } = splitEnPrograma(
    parseDescripcionRica(taller.descripcion),
  );

  return (
    <>
      {switchToProxima && !soldOutModalDismissed && (
        <SoldOutModal
          proxima={proxima!}
          currentEdicion={taller.numero_edicion}
          onDismiss={() => setSoldOutModalDismissed(true)}
        />
      )}
      <PublicLayout
        topBar={{ variant: "escuela", cta: { label: "Inscribirme", href: "#inscripcion" } }}
      >
        <div className="min-h-dvh bg-background pb-24 lg:pb-0">
          {/* F2: preview admin de una edición en borrador — el público recibe
              404; este banner solo puede aparecer con sesión admin. */}
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
          />

          <TallerGaleria fotos={formTaller.fotos} alt={taller.nombre} />

          {/* ── Cuerpo ─────────────────────────────────────────────────────── */}
          <div className="mx-auto py-12 sm:py-16" style={{ width: TALLER_CONTENT_WIDTH }}>
            <div className="grid lg:grid-cols-[1fr_380px] gap-10 lg:gap-16 items-start">
              {/* Columna principal */}
              <div className="flex flex-col gap-12">
                {/* Orden: de qué se trata → a quién está orientado → el
                    desarrollo completo del programa → cuándo es (pedido
                    explícito del dueño: las fechas van después de las
                    clases, no antes — ya se sabe de qué se trata el taller
                    antes de mostrar el calendario). */}
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

                <InstitucionesRow taller={taller} />
                <InstructorCard taller={taller} />
                <TallerTrabajos trabajos={taller.trabajos} />
              </div>

              {/* Sidebar sticky */}
              <div className="lg:sticky lg:top-20">
                {/* Formulario de inscripción */}
                <div id="inscripcion" className="scroll-mt-20">
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
                            {new Date(proxima!.fecha_inicio + "T12:00:00").toLocaleDateString(
                              "es-AR",
                              { day: "numeric", month: "long" },
                            )}{" "}
                            y{" "}
                            {new Date(proxima!.fecha_fin + "T12:00:00").toLocaleDateString(
                              "es-AR",
                              {
                                day: "numeric",
                                month: "long",
                              },
                            )}
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
      </PublicLayout>
      {!isFrozen && (
        <TallerCTABar
          taller={formTaller}
          label={isFullySoldOut ? "Avisame de nuevas fechas" : "Inscribirme"}
        />
      )}
    </>
  );
}
