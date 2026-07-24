import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { createLazyFileRoute, Link, notFound } from "@tanstack/react-router";
import { CalendarPlus, CheckCircle2, X } from "lucide-react";

import { PublicLayout } from "@/components/rental/shell/PublicLayout";
import { Button } from "@/design-system/ui/button";
import { IconButton } from "@/design-system/ui/icon-button";
import { ModalBackdrop } from "@/design-system/ui/modal-backdrop";
import { WorkshopInscripcionForm } from "@/components/talleres/WorkshopInscripcionForm";
import { TallerHero } from "@/components/talleres/TallerHero";
import { TallerCalendario } from "@/components/talleres/TallerCalendario";
import { ProgramaSection } from "@/components/talleres/ProgramaSection";
import { InstructorCard } from "@/components/talleres/InstructorCard";
import { InstitucionesRow } from "@/components/talleres/InstitucionesRow";
import { PrecioCard } from "@/components/talleres/PrecioCard";
import { TallerTrabajos } from "@/components/talleres/TallerTrabajos";
import { TallerFAQ } from "@/components/talleres/TallerFAQ";
import { TallerCTABar } from "@/components/talleres/TallerCTABar";
import { Input } from "@/design-system/ui/input";
import { apiGetTaller, type EdicionLite, type Taller } from "@/lib/api";
import { ordinalEdicion, resumenFechas, resumenHorario } from "@/lib/talleres/formato";
import { descargarIcsTaller } from "@/lib/talleres/ical";

export const Route = createLazyFileRoute("/escuela/$slug")({
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
          to="/escuela/$slug"
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

// ── InteresadoForm ────────────────────────────────────────────────────────────

function InteresadoForm({ slug }: { slug: string }) {
  const [form, setForm] = useState({ nombre: "", email: "", telefono: "" });
  const [status, setStatus] = useState<"idle" | "sending" | "ok" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!form.nombre.trim() || !form.email.trim()) return;
    setStatus("sending");
    try {
      const res = await fetch(`/api/talleres/${slug}/interesado`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j?.detail ?? `Error ${res.status}`);
      }
      setStatus("ok");
    } catch (err) {
      setErrorMsg((err as Error).message);
      setStatus("error");
    }
  }

  if (status === "ok") {
    return (
      <div className="rounded-2xl border border-verde/40 bg-verde/10 px-5 py-6 text-center">
        <CheckCircle2 className="h-8 w-8 text-verde mx-auto mb-3" strokeWidth={1.5} />
        <p className="font-semibold text-ink">¡Anotado/a!</p>
        <p className="text-sm text-muted-foreground mt-1">Te avisamos cuando haya nuevas fechas.</p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
        Avisame si hay más fechas
      </p>
      <Input
        required
        type="text"
        placeholder="Tu nombre"
        value={form.nombre}
        onChange={(e) => setForm((f) => ({ ...f, nombre: e.target.value }))}
      />
      <Input
        required
        type="email"
        placeholder="Tu email"
        value={form.email}
        onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
      />
      <Input
        type="tel"
        placeholder="Tu teléfono (opcional)"
        value={form.telefono}
        onChange={(e) => setForm((f) => ({ ...f, telefono: e.target.value }))}
      />
      {status === "error" && <p className="text-xs text-destructive">{errorMsg}</p>}
      <Button
        type="submit"
        variant="amber"
        shape="pill"
        disabled={status === "sending"}
        className="w-full py-3.5 text-base font-bold"
      >
        {status === "sending" ? "Enviando…" : "Avisame"}
      </Button>
    </form>
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

          {/* ── Cuerpo ─────────────────────────────────────────────────────── */}
          <div className="max-w-[1100px] mx-auto px-4 sm:px-6 py-12 sm:py-16">
            <div className="grid lg:grid-cols-[1fr_380px] gap-10 lg:gap-16 items-start">
              {/* Columna principal */}
              <div className="flex flex-col gap-12">
                {/* Descripción + público */}
                <section>
                  <p className="text-base sm:text-lg leading-relaxed text-muted-foreground">
                    {taller.descripcion}
                  </p>
                  {taller.publico_objetivo && (
                    <div className="mt-6 rounded-xl bg-muted/30 border border-border/50 px-5 py-4">
                      <p className="text-xs font-mono uppercase tracking-widest text-muted-foreground mb-2">
                        Orientado a
                      </p>
                      <p className="text-sm text-muted-foreground leading-relaxed">
                        {taller.publico_objetivo}
                      </p>
                    </div>
                  )}
                </section>

                {formTaller.sesiones.length > 0 && (
                  <section>
                    <div className="flex items-center justify-between gap-3 mb-4">
                      <p className="font-mono text-2xs tracking-[0.25em] uppercase text-rosa">
                        Cuándo
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-1.5 h-7 text-xs"
                        onClick={() =>
                          descargarIcsTaller({
                            tallerNombre: taller.nombre,
                            slug: formTaller.slug,
                            direccion: formTaller.direccion,
                            clases: formTaller.sesiones,
                          })
                        }
                      >
                        <CalendarPlus className="h-3 w-3" />
                        Agregar a mi calendario
                      </Button>
                    </div>
                    <TallerCalendario sesiones={formTaller.sesiones} horario={formTaller.horario} />
                  </section>
                )}
                <ProgramaSection clases={clases} />
                <InstitucionesRow taller={taller} />
                <InstructorCard taller={taller} />
                <TallerTrabajos trabajos={taller.trabajos} />
              </div>

              {/* Sidebar sticky */}
              <div className="lg:sticky lg:top-20">
                <PrecioCard taller={formTaller} />

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
