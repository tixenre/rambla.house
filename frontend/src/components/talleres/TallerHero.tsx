import { Calendar, Clock, MapPin, Users } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { Grain } from "@/components/common/Grain";
import { YouTubeEmbed } from "@/components/common/YouTubeEmbed";
import { ordinalEdicion } from "@/lib/talleres/formato";
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
      href="#inscripcion"
      className="inline-flex items-center gap-2 rounded-full bg-rosa text-ink px-7 py-3.5 text-base font-bold hover:brightness-110 active:scale-[0.97] transition-all"
    >
      Quiero inscribirme
    </a>
  );

  if (taller.video) {
    return (
      <section className="relative bg-ink overflow-hidden">
        <Grain opacity={10} />
        <div className="relative max-w-[1100px] mx-auto px-4 sm:px-6 py-16 sm:py-24 grid lg:grid-cols-[1.1fr_1fr] gap-10 lg:gap-12 items-center">
          <div>
            <Titulo taller={taller} />
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
      <div className="relative max-w-[1100px] mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <Titulo taller={taller} />
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
