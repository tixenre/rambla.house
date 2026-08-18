import type { ReactNode } from "react";
import { Calendar, Clock, MapPin, Users } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { Grain } from "@/components/common/Grain";
import { YouTubeEmbed } from "@/components/common/YouTubeEmbed";
import { TALLER_CONTENT_WIDTH } from "@/components/talleres/TallerGaleria";
import { ordinalEdicion, resumenFechas, resumenHorario } from "@/lib/talleres/formato";
import { trackClickInscribirseTaller } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import type { HermanoLado, Taller } from "@/lib/api";

function Titulo({ taller }: { taller: Taller }) {
  return (
    <>
      <p className="font-mono text-2xs tracking-[0.3em] uppercase text-rosa mb-4">Taller</p>
      <h1
        className="font-display font-black lowercase leading-[0.88] tracking-[-0.02em] text-background"
        style={{ fontSize: "clamp(3rem, 9vw, 6rem)" }}
      >
        {taller.nombre}
      </h1>
      {taller.subtitulo && (
        <p
          className="font-display font-bold lowercase leading-tight tracking-[-0.01em] mt-3"
          style={{
            fontSize: "clamp(1.25rem, 3vw, 1.75rem)",
            color: "color-mix(in oklch, var(--color-rosa) 80%, white)",
          }}
        >
          {taller.subtitulo}
        </p>
      )}
      <p
        className="font-display font-bold lowercase leading-tight tracking-[-0.01em] mt-1"
        style={{
          fontSize: "clamp(0.875rem, 2vw, 1.125rem)",
          color: "color-mix(in oklch, var(--color-rosa) 55%, white 45%)",
        }}
      >
        {ordinalEdicion(taller.numero_edicion)} edición
      </p>
    </>
  );
}

function EdicionesContexto({
  taller,
  compact,
}: {
  taller: Pick<Taller, "edicion_anterior" | "proxima_edicion" | "cupos_disponibles">;
  /** Adentro de una mitad del banner de pareja (`MitadPareja`): menos
   * margen arriba — ya viene después de `MetaRow` compacto, no del H1. */
  compact?: boolean;
}) {
  if (!taller.edicion_anterior && !(taller.proxima_edicion && taller.cupos_disponibles === 0)) {
    return null;
  }
  return (
    <div className={cn("flex flex-wrap items-center gap-4", compact ? "mt-3" : "mt-5")}>
      {taller.edicion_anterior && (
        <Link
          to="/escuelas/$slug"
          params={{ slug: taller.edicion_anterior.slug }}
          className="text-xs text-background/35 hover:text-background/60 transition"
        >
          {ordinalEdicion(taller.edicion_anterior.numero_edicion)} edición — agotada
        </Link>
      )}
      {taller.proxima_edicion && taller.cupos_disponibles === 0 && (
        <Link
          to="/escuelas/$slug"
          params={{ slug: taller.proxima_edicion.slug }}
          className="inline-flex items-center gap-2 rounded-full border border-rosa/50 bg-rosa/10 px-4 py-1.5 text-sm font-semibold text-rosa hover:bg-rosa/20 transition"
        >
          {ordinalEdicion(taller.proxima_edicion.numero_edicion)} edición{" "}
          <span className="opacity-70">· {taller.proxima_edicion.cupos_disponibles} cupos</span>
        </Link>
      )}
    </div>
  );
}

/** Una mitad de la pantalla partida del banner de pareja — nombre +
 * subtítulo + fecha/horario/lugar/cupos de un taller del par (pedido del
 * dueño 2026-08-18: esa info "puede estar dentro del recuadro del
 * taller" en vez de en una fila genérica aparte). El resumen de fecha/
 * horario se calcula con las MISMAS `resumenFechas`/`resumenHorario` que
 * usa el taller actual (a partir de `sesiones`, que este lado trae
 * completo) — así las 2 mitades formatean igual, no una rica y la otra
 * genérica. Fondo propio (`bg-background/10`, el mismo tono que ya usan
 * las flechas del carrusel de `TallerGaleria` sobre el hero oscuro —
 * `bg-background/[0.03]` resultó imperceptible en pantalla) — más fuerte
 * en hover del lado clickeable — para que cada mitad "se note" contra el
 * negro del hero (pedido del dueño) — misma tipografía/peso en los 2
 * lados, la única
 * diferencia real sigue siendo la interactividad, no un resaltado
 * artificial. El lado ACTUAL suma, adentro de su propia mitad, el
 * contexto de edición (agotada/próxima) y el CTA de inscripción — ambos
 * son del taller actual, así que van CON su info, no flotando aparte
 * abajo de todo el banner ("parece un botón colgado ahí", pedido del
 * dueño). Texto plano si es el taller actual (nada que linkear a sí
 * mismo), link real si es el otro. */
function MitadPareja({
  t,
  taller,
  cta,
  primero,
}: {
  t: HermanoLado;
  taller: Taller;
  cta: ReactNode;
  primero: boolean;
}) {
  const optsLong: Intl.DateTimeFormatOptions = { weekday: "long", day: "numeric", month: "long" };
  const fechaInicioStr = new Date(t.fecha_inicio + "T12:00:00").toLocaleDateString(
    "es-AR",
    optsLong,
  );
  const fechaFinStr = new Date(t.fecha_fin + "T12:00:00").toLocaleDateString("es-AR", optsLong);
  const fechasResumen = resumenFechas(t.sesiones, fechaInicioStr, fechaFinStr);
  const horarioResumen = resumenHorario(t.sesiones, t.horario);
  const esActual = t.taller_id === taller.taller_id;

  const contenido = (
    <>
      <p
        className="font-display font-bold lowercase leading-tight tracking-[-0.01em] text-background"
        style={{ fontSize: "clamp(1.1rem, 2.4vw, 1.5rem)" }}
      >
        {t.nombre}
      </p>
      {t.subtitulo && <p className="mt-1 text-xs text-background/50">{t.subtitulo}</p>}
      <MetaRow
        fechasResumen={fechasResumen}
        horarioResumen={horarioResumen}
        direccion={t.direccion}
        cuposTotal={t.cupos_total}
        compact
      />
      {esActual && <EdicionesContexto taller={taller} compact />}
      {esActual && <div className="mt-4">{cta}</div>}
    </>
  );

  const clases = cn(
    "block p-4 bg-background/10",
    primero ? "sm:border-r sm:border-background/15" : "border-t sm:border-t-0 border-background/15",
  );

  if (esActual) return <div className={clases}>{contenido}</div>;
  return (
    <Link
      to="/escuelas/$slug"
      params={{ slug: t.slug }}
      className={cn(clases, "transition-colors hover:bg-background/20")}
    >
      {contenido}
    </Link>
  );
}

/**
 * Título de un taller que es parte de una PAREJA de marketing (dos
 * talleres lanzados juntos, ej. nivel inicial + avanzado de la misma
 * institución) — invierte la jerarquía de siempre (pedido del dueño
 * 2026-08-18, "esto daría vuelta la lógica"): el título grande ya NO es
 * el nombre de ESTE taller, es el de la CAMPAÑA (`taller_hermano_titulo`,
 * lo que el dueño tipeó en el admin) — no una unión automática de los 2
 * nombres ("eso sea el título, no la unión de los dos títulos", pedido
 * del dueño). Fallback a esa unión SOLO si no cargó ningún título de
 * campaña (para no dejar el hero sin H1). Debajo, una pantalla partida en
 * 2 mitades de igual peso (`MitadPareja`) deja elegir cuál seguir viendo
 * — cada una con su propia fecha/hora/cupos, y la del taller ACTUAL
 * además con su contexto de edición + el CTA de inscripción adentro (el
 * `cta` se pasa desde `TallerHero`, mismo elemento con `id="hero-cta"`
 * que ya observa `TallerCTABar`). El resto de la página (contenido, form)
 * sigue siendo del taller actual sin cambios.
 */
function TituloPareja({ taller, cta }: { taller: Taller; cta: ReactNode }) {
  const hermano = taller.taller_hermano;
  if (!hermano) return null;
  const tituloGrande =
    hermano.titulo || `${hermano.principal.nombre} × ${hermano.secundario.nombre}`;
  return (
    <>
      <p className="font-mono text-2xs tracking-[0.3em] uppercase text-rosa mb-4">Talleres</p>
      <h1
        className="font-display font-black lowercase leading-[0.95] tracking-[-0.02em] text-background"
        style={{ fontSize: "clamp(1.75rem, 6vw, 4rem)" }}
      >
        {tituloGrande}
      </h1>
      <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 rounded-xl border border-background/15 overflow-hidden">
        <MitadPareja t={hermano.principal} taller={taller} cta={cta} primero />
        <MitadPareja t={hermano.secundario} taller={taller} cta={cta} primero={false} />
      </div>
    </>
  );
}

function MetaRow({
  fechasResumen,
  horarioResumen,
  direccion,
  cuposTotal,
  compact,
}: {
  fechasResumen: string;
  horarioResumen: string;
  direccion: string;
  cuposTotal: number;
  /** Dentro de una mitad del banner de pareja (`MitadPareja`): más chico
   * y en columna — el ancho de cada mitad no alcanza para la fila
   * horizontal de siempre. */
  compact?: boolean;
}) {
  return (
    <div
      className={
        compact
          ? "mt-3 flex flex-col gap-1 text-xs text-background/50"
          : "mt-8 flex flex-wrap gap-x-6 gap-y-3 text-sm text-background/60"
      }
    >
      <span className="flex items-center gap-2">
        <Calendar className={compact ? "h-3.5 w-3.5 shrink-0" : "h-4 w-4 shrink-0"} />
        {fechasResumen}
      </span>
      <span className="flex items-center gap-2">
        <Clock className={compact ? "h-3.5 w-3.5 shrink-0" : "h-4 w-4 shrink-0"} />
        {horarioResumen}
      </span>
      <span className="flex items-center gap-2">
        <MapPin className={compact ? "h-3.5 w-3.5 shrink-0" : "h-4 w-4 shrink-0"} />
        {direccion}
      </span>
      <span className="flex items-center gap-2">
        <Users className={compact ? "h-3.5 w-3.5 shrink-0" : "h-4 w-4 shrink-0"} />
        {cuposTotal} cupos
      </span>
    </div>
  );
}

type Props = {
  taller: Taller;
  formTaller: { direccion: string; cupos_total: number };
  fechasResumen: string;
  horarioResumen: string;
};

/**
 * Hero de la landing — 2 variantes por datos (no una rama por `tipo_taller`):
 * con `video` configurado → split tipografía + YouTubeEmbed; sin video → el
 * hero tipográfico de siempre (cero regresión para talleres sin media, ej.
 * Jime). No hay variante "foto" — F4a solo construyó video hero, no un
 * campo de foto de portada separado; si se pide, es un campo nuevo a sumar
 * junto a video_url, no algo a inventar acá.
 */
export function TallerHero({ taller, formTaller, fechasResumen, horarioResumen }: Props) {
  const cta = (
    <a
      id="hero-cta"
      href="#inscripcion"
      onClick={() => trackClickInscribirseTaller(taller.id)}
      className="inline-flex items-center gap-2 rounded-full bg-rosa text-ink px-7 py-3.5 text-base font-bold hover:brightness-110 active:scale-[0.97] transition-all"
    >
      Quiero inscribirme
    </a>
  );

  if (taller.video) {
    return (
      <section className="relative bg-ink overflow-hidden">
        <Grain opacity={10} />
        <div
          className="relative mx-auto py-16 sm:py-24 grid lg:grid-cols-[1.1fr_1fr] gap-10 lg:gap-12 items-center"
          style={{ width: TALLER_CONTENT_WIDTH }}
        >
          <div>
            {taller.taller_hermano ? (
              <TituloPareja taller={taller} cta={cta} />
            ) : (
              <>
                <Titulo taller={taller} />
                <EdicionesContexto taller={taller} />
                <MetaRow
                  fechasResumen={fechasResumen}
                  horarioResumen={horarioResumen}
                  direccion={formTaller.direccion}
                  cuposTotal={formTaller.cupos_total}
                />
                <div className="mt-8">{cta}</div>
              </>
            )}
          </div>
          <YouTubeEmbed
            videoId={taller.video.youtube_id}
            title={taller.nombre}
            posterUrl={taller.video.poster}
            className="border-background/10"
          />
        </div>
      </section>
    );
  }

  return (
    <section className="relative bg-ink overflow-hidden">
      <Grain opacity={10} />
      <div className="relative mx-auto py-16 sm:py-24" style={{ width: TALLER_CONTENT_WIDTH }}>
        {taller.taller_hermano ? (
          <TituloPareja taller={taller} cta={cta} />
        ) : (
          <>
            <Titulo taller={taller} />
            <EdicionesContexto taller={taller} />
            <MetaRow
              fechasResumen={fechasResumen}
              horarioResumen={horarioResumen}
              direccion={formTaller.direccion}
              cuposTotal={formTaller.cupos_total}
            />
            <div className="mt-8">{cta}</div>
          </>
        )}
      </div>
    </section>
  );
}
