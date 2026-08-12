import { createLazyFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Calendar, MapPin, Users } from "lucide-react";

import { PublicLayout } from "@/components/rental/shell/PublicLayout";
import { SectionBanner } from "@/components/rental/landing/SectionBanner";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { Grain } from "@/components/common/Grain";
import { LogoMark } from "@/components/rental/shell/LogoMark";
import { apiGetTalleres, type Taller } from "@/lib/api";
import { useBusinessContact } from "@/hooks/useBusinessContact";
import { heroImgProps } from "@/lib/studio/hero-photos";

export const Route = createLazyFileRoute("/escuelas/")({
  component: TalleresPage,
});

// ── Card activa (horizontal) ──────────────────────────────────────────────────
function WorkshopCard({ taller }: { taller: Taller }) {
  const fechaInicio = new Date(taller.fecha_inicio + "T12:00:00");
  const fechaFin = new Date(taller.fecha_fin + "T12:00:00");
  const optsDate: Intl.DateTimeFormatOptions = { day: "numeric", month: "long" };
  const fechaStr =
    fechaInicio.getTime() === fechaFin.getTime()
      ? fechaInicio.toLocaleDateString("es-AR", optsDate)
      : `${fechaInicio.toLocaleDateString("es-AR", optsDate)} – ${fechaFin.toLocaleDateString("es-AR", optsDate)}`;

  const soldOut = taller.cupos_disponibles === 0;
  const cuposLabel =
    taller.cupos_disponibles > 0
      ? `${taller.cupos_disponibles} lugar${taller.cupos_disponibles === 1 ? "" : "es"} disponible${taller.cupos_disponibles === 1 ? "" : "s"}`
      : "Lista de espera";

  // Portada: mismo criterio que TallerGaleria (principal primero, después orden).
  const portada = [...taller.fotos].sort(
    (a, b) => Number(b.es_principal) - Number(a.es_principal) || a.orden - b.orden || a.id - b.id,
  )[0] as (typeof taller.fotos)[number] | undefined;
  const imgProps = portada
    ? heroImgProps(
        {
          url: portada.url,
          urlSm: portada.url_sm ?? undefined,
          urlAvif: portada.url_avif ?? undefined,
          urlSmAvif: portada.url_sm_avif ?? undefined,
        },
        { eager: false },
      )
    : null;

  return (
    <Link
      to="/escuelas/$slug"
      params={{ slug: taller.slug }}
      className={`group flex flex-col sm:flex-row rounded-2xl border overflow-hidden transition-all duration-200 ${
        soldOut
          ? "border-border/40 bg-muted/20 opacity-70 hover:opacity-80"
          : "border-border/60 bg-background hover:border-rosa/40 hover:shadow-md"
      }`}
    >
      {/* Bloque visual izquierdo: portada de la edición si hay, si no el
          fondo ink+grain de siempre (el título vive en el cuerpo derecho).
          Con foto: contenedor 4:5 (vertical, formato IG) que la foto llena
          entera vía object-cover; `self-start` para que el bloque NO se
          estire a la altura de la columna de texto (con `items-stretch` por
          defecto, forzar una altura distinta a la del aspect-ratio dejaba
          un tramo de ink liso abajo que se leía como la foto recortada/rota).
          Sin foto: sigue estirándose (el ink+grain+isologo llena todo el
          alto, se ve bien sin un "final" natural que respetar). */}
      <div
        className={`relative sm:w-64 shrink-0 overflow-hidden min-h-[130px] sm:min-h-0 bg-ink ${imgProps ? "self-start" : ""}`}
      >
        {imgProps ? (
          <img
            key={portada!.id}
            {...imgProps}
            alt={taller.nombre}
            className="w-full aspect-[4/5] object-cover"
            draggable={false}
          />
        ) : (
          <>
            <Grain color="white" opacity={6} />
            <div className="absolute inset-0 flex items-center justify-center">
              <LogoMark className="h-28 w-28 text-rosa/40" />
            </div>
          </>
        )}
        {soldOut && (
          <span className="absolute left-4 top-4 inline-block rounded-full border border-background/30 bg-ink/40 text-background/80 text-2xs font-mono tracking-widest uppercase px-3 py-1 backdrop-blur-sm">
            Sold out
          </span>
        )}
      </div>

      {/* Cuerpo derecho */}
      <div className="flex-1 px-6 sm:px-8 py-5 flex flex-col gap-3">
        <div>
          <p className="font-mono text-2xs tracking-[0.25em] uppercase text-rosa mb-2">Taller</p>
          <h2
            className="font-display font-black lowercase leading-[0.95] tracking-[-0.015em] text-ink"
            style={{ fontSize: "clamp(1.2rem, 2vw, 1.5rem)" }}
          >
            {taller.nombre}
          </h2>
          <p className="text-muted-foreground mt-1 text-sm">{taller.subtitulo}</p>
        </div>
        <div className="flex flex-col gap-3 text-sm">
          <span className="flex items-baseline gap-1.5 font-semibold text-ink">
            <Calendar className="h-4 w-4 shrink-0" />
            <span className="text-base">{fechaStr}</span>
            <span className="text-muted-foreground font-normal">· {taller.horario}</span>
          </span>
          <div className="flex flex-wrap gap-x-5 gap-y-1.5 text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <MapPin className="h-3.5 w-3.5 shrink-0" />
              {taller.direccion}
            </span>
            <span className="flex items-center gap-1.5">
              <Users className="h-3.5 w-3.5 shrink-0" />
              {cuposLabel}
            </span>
          </div>
        </div>
        <p className="text-sm text-muted-foreground line-clamp-3">
          {taller.resumen || taller.descripcion}
        </p>
        <div className="flex items-center justify-end pt-1 mt-auto">
          <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink group-hover:gap-3 transition-[gap]">
            Ver taller <ArrowRight className="h-4 w-4" />
          </span>
        </div>
      </div>
    </Link>
  );
}

function SectionLabel({ label }: { label: string }) {
  return (
    <p className="font-mono text-xs tracking-[0.2em] uppercase text-muted-foreground mt-4 mb-1">
      {label}
    </p>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
function TalleresPage() {
  const contact = useBusinessContact();
  const {
    data: talleres = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["talleres"],
    queryFn: apiGetTalleres,
    staleTime: 1000 * 60 * 5,
  });

  const hoy = new Date();
  hoy.setHours(0, 0, 0, 0);

  const proximos = talleres
    .filter((t) => new Date(t.fecha_inicio + "T00:00:00") > hoy)
    // ASC: el más cercano primero (antes ordenaba DESC — el más cercano
    // quedaba al final de la lista, bug reportado en el plan de F5).
    .sort((a, b) => new Date(a.fecha_inicio).getTime() - new Date(b.fecha_inicio).getTime());

  const enCurso = talleres
    .filter((t) => {
      const inicio = new Date(t.fecha_inicio + "T00:00:00");
      const fin = new Date(t.fecha_fin + "T00:00:00");
      return inicio <= hoy && fin >= hoy;
    })
    .sort((a, b) => new Date(a.fecha_inicio).getTime() - new Date(b.fecha_inicio).getTime());

  const pasadosApi = talleres
    .filter((t) => new Date(t.fecha_fin + "T00:00:00") < hoy)
    .sort((a, b) => new Date(b.fecha_inicio).getTime() - new Date(a.fecha_inicio).getTime());

  const hayTalleres = talleres.length > 0;

  return (
    <PublicLayout topBar={{ variant: "escuela" }}>
      <SectionBanner section="escuela" />

      <div className="max-w-[900px] mx-auto px-4 sm:px-6 py-10 sm:py-14 flex flex-col gap-4">
        {isLoading && (
          <div className="py-16 text-center text-muted-foreground text-sm">Cargando talleres…</div>
        )}
        {isError && (
          <div className="py-16 text-center text-muted-foreground text-sm">
            No se pudieron cargar los talleres. Intentá de nuevo.
          </div>
        )}

        {!isLoading && !isError && !hayTalleres && (
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

        {proximos.length > 0 && (
          <>
            <SectionLabel label="Próximos" />
            {proximos.map((t) => (
              <WorkshopCard key={t.id} taller={t} />
            ))}
          </>
        )}

        {enCurso.length > 0 && (
          <>
            <SectionLabel label="En curso" />
            {enCurso.map((t) => (
              <WorkshopCard key={t.id} taller={t} />
            ))}
          </>
        )}

        {pasadosApi.length > 0 && (
          <>
            <SectionLabel label="Ediciones anteriores" />
            {pasadosApi.map((t) => (
              <WorkshopCard key={t.id} taller={t} />
            ))}
          </>
        )}
      </div>
    </PublicLayout>
  );
}
