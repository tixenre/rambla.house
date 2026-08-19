import { Instagram } from "lucide-react";
import { Grain } from "@/components/common/Grain";
import { TALLER_CONTENT_WIDTH } from "@/components/talleres/TallerGaleria";
import type { Institucion } from "@/lib/api";

/**
 * Hero de la institución cuando cargó una foto destacada en su galería
 * propia (`institucion_fotos`, `es_principal`) — idea del dueño 2026-08-19:
 * "ya que va a haber una galería de fotos por institución, en la sección
 * blanca, hacer un hero con la foto destacada, que esté el logo y la info
 * arriba de la foto". Reemplaza el header plano en `bg-background` SOLO
 * cuando hay foto — sin foto, `InstitucionPage` sigue usando el
 * tratamiento de siempre (logo/ícono sobre cream, texto oscuro).
 *
 * Misma decisión logo-es-el-título que el header plano (2026-08-19): CON
 * logo, el logo alcanza como identidad visual — el h1 va `sr-only` (salvo
 * la excepción de 1 taller, que resuelve `TallerHero` más abajo). SIN
 * logo, el nombre se muestra como h1 real — acá recoloreado a texto claro
 * (antes era `text-ink`, pensado para fondo cream) porque ahora se lee
 * sobre la foto, con scrim.
 *
 * AVIF directo + fallback webp (misma regla que el hero del catálogo,
 * MEMORIA 2026-06-25) — es la imagen más grande de la página, con scrim
 * encima para que el texto claro se lea sin importar qué tan clara/oscura
 * sea la foto real.
 */
export function InstitucionFotoHero({
  institucion,
  h1SrOnly,
}: {
  institucion: Institucion;
  h1SrOnly: boolean;
}) {
  const foto = institucion.foto_destacada;
  if (!foto) return null;

  return (
    <section className="relative bg-ink overflow-hidden min-h-[420px] sm:min-h-[520px] flex items-end">
      <img
        src={foto.url_avif || foto.url}
        alt=""
        loading="eager"
        decoding="async"
        onError={(e) => {
          if (e.currentTarget.src !== foto.url) e.currentTarget.src = foto.url;
        }}
        className="absolute inset-0 h-full w-full object-cover"
      />
      <div className="absolute inset-0 bg-gradient-to-t from-ink via-ink/70 to-ink/20" />
      <Grain opacity={8} />
      <div
        className="relative z-10 mx-auto w-full py-10 sm:py-14 flex flex-col items-center text-center gap-4"
        style={{ width: TALLER_CONTENT_WIDTH }}
      >
        {institucion.logo_url ? (
          <>
            {h1SrOnly && <h1 className="sr-only">{institucion.nombre}</h1>}
            <img
              src={institucion.logo_url}
              alt={institucion.nombre}
              className="h-16 sm:h-20 w-auto max-w-full object-contain"
            />
          </>
        ) : (
          <h1
            className="font-display font-black lowercase leading-[0.95] tracking-[-0.015em] text-background"
            style={{ fontSize: "clamp(1.8rem, 4.5vw, 3rem)" }}
          >
            {institucion.nombre}
          </h1>
        )}

        {institucion.descripcion && (
          // Sin max-w-2xl: mismo ajuste que ya se hizo en el header plano
          // (2026-08-19) — un cap angosto adentro de una columna que ya es
          // TALLER_CONTENT_WIDTH duplicaba la restricción y dejaba el
          // párrafo con demasiados renglones cortos.
          <p className="text-background/85 text-sm leading-relaxed">{institucion.descripcion}</p>
        )}

        {institucion.instagram && (
          <a
            href={`https://instagram.com/${institucion.instagram}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-sm font-semibold text-background hover:text-rosa transition"
          >
            <Instagram className="h-4 w-4" />@{institucion.instagram}
          </a>
        )}
      </div>
    </section>
  );
}
