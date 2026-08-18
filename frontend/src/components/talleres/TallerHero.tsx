import { Calendar, Clock, MapPin, Users } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { Grain } from "@/components/common/Grain";
import { YouTubeEmbed } from "@/components/common/YouTubeEmbed";
import { TALLER_CONTENT_WIDTH } from "@/components/talleres/TallerGaleria";
import { ordinalEdicion } from "@/lib/talleres/formato";
import { trackClickInscribirseTaller } from "@/lib/analytics";
import type { Taller } from "@/lib/api";

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
}: {
  taller: Pick<Taller, "edicion_anterior" | "proxima_edicion" | "cupos_disponibles">;
}) {
  if (!taller.edicion_anterior && !(taller.proxima_edicion && taller.cupos_disponibles === 0)) {
    return null;
  }
  return (
    <div className="mt-5 flex flex-wrap items-center gap-4">
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
 * subtítulo de un taller del par (el subtítulo es lo que deja diferenciar
 * "nivel inicial"/"nivel avanzado" sin inventar un campo nuevo). Texto
 * plano si es el taller actual (nada que linkear a sí mismo), link real si
 * es el otro — misma tipografía en los 2 casos, la única diferencia es la
 * interactividad, no el peso visual (pedido del dueño 2026-08-18: que las
 * 2 mitades se vean iguales, sin una "resaltada"). */
function MitadPareja({
  t,
  taller,
}: {
  t: { taller_id: number; nombre: string; subtitulo: string; slug: string };
  taller: Taller;
}) {
  const contenido = (
    <>
      <p
        className="font-display font-bold lowercase leading-tight tracking-[-0.01em] text-background"
        style={{ fontSize: "clamp(1.1rem, 2.4vw, 1.5rem)" }}
      >
        {t.nombre}
      </p>
      {t.subtitulo && <p className="mt-1 text-xs text-background/50">{t.subtitulo}</p>}
    </>
  );
  if (t.taller_id === taller.taller_id) return <div>{contenido}</div>;
  return (
    <Link
      to="/escuelas/$slug"
      params={{ slug: t.slug }}
      className="block transition-opacity hover:opacity-70"
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
 * el nombre de ESTE taller, es el de LOS DOS juntos. Debajo, una pantalla
 * partida en 2 mitades de igual peso (`MitadPareja`) deja elegir cuál
 * seguir viendo. Todo lo de más abajo (fecha/hora/cupos/CTA, y el resto
 * de la página/form) sigue siendo del taller ACTUAL sin cambios — acá
 * solo se comparte el título.
 */
function TituloPareja({ taller }: { taller: Taller }) {
  const hermano = taller.taller_hermano;
  if (!hermano) return null;
  return (
    <>
      <p className="font-mono text-2xs tracking-[0.3em] uppercase text-rosa mb-4">Talleres</p>
      <h1
        className="font-display font-black lowercase leading-[0.95] tracking-[-0.02em] text-background"
        style={{ fontSize: "clamp(1.75rem, 6vw, 4rem)" }}
      >
        {hermano.principal.nombre} <span className="text-rosa">×</span> {hermano.secundario.nombre}
      </h1>
      {hermano.titulo && (
        <p
          className="font-display font-bold lowercase leading-tight tracking-[-0.01em] mt-3"
          style={{
            fontSize: "clamp(1.1rem, 2.6vw, 1.5rem)",
            color: "color-mix(in oklch, var(--color-rosa) 80%, white)",
          }}
        >
          {hermano.titulo}
        </p>
      )}
      <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 rounded-xl border border-background/15 overflow-hidden">
        <div className="p-4 sm:border-r sm:border-background/15">
          <MitadPareja t={hermano.principal} taller={taller} />
        </div>
        <div className="p-4 border-t sm:border-t-0 border-background/15">
          <MitadPareja t={hermano.secundario} taller={taller} />
        </div>
      </div>
    </>
  );
}

function MetaRow({
  fechasResumen,
  horarioResumen,
  direccion,
  cuposTotal,
}: {
  fechasResumen: string;
  horarioResumen: string;
  direccion: string;
  cuposTotal: number;
}) {
  return (
    <div className="mt-8 flex flex-wrap gap-x-6 gap-y-3 text-sm text-background/60">
      <span className="flex items-center gap-2">
        <Calendar className="h-4 w-4 shrink-0" />
        {fechasResumen}
      </span>
      <span className="flex items-center gap-2">
        <Clock className="h-4 w-4 shrink-0" />
        {horarioResumen}
      </span>
      <span className="flex items-center gap-2">
        <MapPin className="h-4 w-4 shrink-0" />
        {direccion}
      </span>
      <span className="flex items-center gap-2">
        <Users className="h-4 w-4 shrink-0" />
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
            {taller.taller_hermano ? <TituloPareja taller={taller} /> : <Titulo taller={taller} />}
            <EdicionesContexto taller={taller} />
            <MetaRow
              fechasResumen={fechasResumen}
              horarioResumen={horarioResumen}
              direccion={formTaller.direccion}
              cuposTotal={formTaller.cupos_total}
            />
            <div className="mt-8">{cta}</div>
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
        {taller.taller_hermano ? <TituloPareja taller={taller} /> : <Titulo taller={taller} />}
        <EdicionesContexto taller={taller} />
        <MetaRow
          fechasResumen={fechasResumen}
          horarioResumen={horarioResumen}
          direccion={formTaller.direccion}
          cuposTotal={formTaller.cupos_total}
        />
        <div className="mt-8">{cta}</div>
      </div>
    </section>
  );
}
