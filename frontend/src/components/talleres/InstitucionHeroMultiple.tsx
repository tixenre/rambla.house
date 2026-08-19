import type { ReactNode } from "react";
import { ArrowRight, Calendar, Clock, MapPin, Users } from "lucide-react";
import { Grain } from "@/components/common/Grain";
import { TALLER_CONTENT_WIDTH } from "@/components/talleres/TallerGaleria";
import { EdicionesContexto } from "@/components/talleres/TallerHero";
import { resumenFechas, resumenHorario } from "@/lib/talleres/formato";
import { trackClickInscribirseTaller } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import type { Institucion, Taller } from "@/lib/api";

/** Una card del selector — nombre + subtítulo + fecha/horario/lugar/cupos
 * de un taller de la institución. Sin fondo/recuadro (mismo criterio que
 * tenía el banner de pareja retirado: la jerarquía la da la TIPOGRAFÍA, no
 * un tinte): el activo es grande/pleno y suma el CTA adentro; el resto
 * queda apagado con un botón "Ver este taller" que cambia el activo EN LA
 * MISMA página (no navega — el contenido completo de cada taller de esta
 * institución ya está cargado en `data.talleres`). */
function TallerCard({
  taller,
  activo,
  cta,
  onSeleccionar,
}: {
  taller: Taller;
  activo: boolean;
  cta: ReactNode;
  onSeleccionar: (tallerId: number) => void;
}) {
  const optsLong: Intl.DateTimeFormatOptions = { weekday: "long", day: "numeric", month: "long" };
  const fechaInicioStr = new Date(taller.fecha_inicio + "T12:00:00").toLocaleDateString(
    "es-AR",
    optsLong,
  );
  const fechaFinStr = new Date(taller.fecha_fin + "T12:00:00").toLocaleDateString(
    "es-AR",
    optsLong,
  );
  const fechasResumen = resumenFechas(taller.sesiones, fechaInicioStr, fechaFinStr);
  const horarioResumen = resumenHorario(taller.sesiones, taller.horario);

  const contenido = (
    <>
      <p
        className={cn(
          "font-display lowercase leading-tight tracking-[-0.02em] transition-colors",
          activo
            ? "font-black text-background"
            : "font-bold text-background/45 group-hover:text-background/75",
        )}
        style={{
          fontSize: activo ? "clamp(1.5rem, 3.2vw, 2.125rem)" : "clamp(1.15rem, 2.4vw, 1.5rem)",
        }}
      >
        {taller.nombre}
      </p>
      {taller.subtitulo && (
        <p
          className={cn(
            "mt-1.5 text-xs transition-colors",
            activo ? "text-background/55" : "text-background/30 group-hover:text-background/45",
          )}
        >
          {taller.subtitulo}
        </p>
      )}
      <div
        className={cn(
          "flex flex-wrap items-center mt-3 gap-x-4 gap-y-1.5 text-xs",
          activo ? "text-background/55" : "text-background/35",
        )}
      >
        <span className="flex items-center gap-2">
          <Calendar className="h-3.5 w-3.5 shrink-0" />
          {fechasResumen}
        </span>
        <span className="flex items-center gap-2">
          <Clock className="h-3.5 w-3.5 shrink-0" />
          {horarioResumen}
        </span>
        <span className="flex items-center gap-2">
          <MapPin className="h-3.5 w-3.5 shrink-0" />
          {taller.direccion}
        </span>
        <span className="flex items-center gap-2">
          <Users className="h-3.5 w-3.5 shrink-0" />
          {taller.cupos_total} cupos
        </span>
      </div>
      {activo && <EdicionesContexto taller={taller} />}
      {activo && <div className="mt-5">{cta}</div>}
      {!activo && (
        <span className="mt-4 inline-flex items-center gap-1.5 text-xs font-semibold text-rosa/70 transition-colors group-hover:text-rosa">
          Ver este taller
          <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
        </span>
      )}
    </>
  );

  if (activo) return <div>{contenido}</div>;
  return (
    <button
      type="button"
      onClick={() => onSeleccionar(taller.taller_id)}
      className="group block w-full text-left"
    >
      {contenido}
    </button>
  );
}

/**
 * Hero compartido del hub de institución cuando hay 2+ talleres — reemplaza
 * el banner de "taller hermano" (que solo servía para pares) con un
 * selector N-way: el nombre grande de la campaña sale de unir los nombres
 * de TODOS los talleres, la grilla lista uno por card, y "Ver este taller"
 * cambia cuál está activo sin navegar (`InstitucionPage` guarda el
 * `taller_id` activo). Pedido del dueño 2026-08-19: "esa página compartida
 * lo haría cuando seleccionás la institución… si tiene 2 o más, mostrá la
 * página múltiple". Con exactamente 1 taller, este componente no se usa —
 * `TallerHubBlock` muestra su propio `TallerHero` normal (`InstitucionPage`
 * decide por cantidad).
 *
 * El logo (si la institución cargó uno) va arriba del eyebrow, como
 * `<img>` liso — funciona igual para raster y SVG (el navegador renderiza
 * SVG nativo vía `src`, sin necesitar `InlineSvg`) y a propósito NO fuerza
 * `currentColor`: es el logo REAL de un tercero (a diferencia del wordmark
 * propio de Rambla o el muro de marcas de equipos en `BrandCard`, donde SÍ
 * se homogeniza a un color), tiene que verse con sus colores originales.
 */
export function InstitucionHeroMultiple({
  institucion,
  talleres,
  activoId,
  onSeleccionar,
}: {
  institucion: Institucion;
  talleres: Taller[];
  activoId: number;
  onSeleccionar: (tallerId: number) => void;
}) {
  const tituloGrande = talleres.map((t) => t.nombre).join(" × ");
  const activo = talleres.find((t) => t.taller_id === activoId) ?? talleres[0];
  const cta = (
    <a
      id="hero-cta"
      href="#inscripcion"
      onClick={() => trackClickInscribirseTaller(activo.id)}
      className="inline-flex items-center gap-2 rounded-full bg-rosa text-ink px-7 py-3.5 text-base font-bold hover:brightness-110 active:scale-[0.97] transition-all"
    >
      Quiero inscribirme
    </a>
  );

  return (
    <section className="relative bg-ink overflow-hidden">
      <Grain opacity={10} />
      <div className="relative mx-auto py-16 sm:py-24" style={{ width: TALLER_CONTENT_WIDTH }}>
        {institucion.logo_url && (
          <img
            src={institucion.logo_url}
            alt={institucion.nombre}
            className="h-14 w-14 rounded-2xl object-contain bg-background/10 mb-5"
          />
        )}
        <p className="font-mono text-2xs tracking-[0.3em] uppercase text-rosa mb-4">Talleres</p>
        <h1
          className="font-display font-black lowercase leading-[0.95] tracking-[-0.02em] text-background"
          style={{ fontSize: "clamp(1.75rem, 6vw, 4rem)" }}
        >
          {tituloGrande}
        </h1>
        <div className="mt-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-12 gap-y-8">
          {talleres.map((t) => (
            <TallerCard
              key={t.taller_id}
              taller={t}
              activo={t.taller_id === activo.taller_id}
              cta={cta}
              onSeleccionar={onSeleccionar}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
