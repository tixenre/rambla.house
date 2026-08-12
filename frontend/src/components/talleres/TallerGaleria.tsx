import { useEffect, useState } from "react";
import type { TallerFoto } from "@/lib/api";
import { heroImgProps, type HeroPhoto } from "@/lib/studio/hero-photos";
import { Lightbox } from "@/components/rental/Lightbox";
import { useReducedMotion } from "@/hooks/useReducedMotion";

// Misma cadencia que el hero rotante del catálogo (HeroSection/HeroBanner).
const AUTOPLAY_MS = 4500;

/**
 * Portada + galería de una EDICIÓN de taller — arriba de todo en la landing
 * pública, mismo tratamiento visual que el hero del catálogo (`heroImgProps`,
 * reusado tal cual: AVIF directo + fallback webp, misma fuente `TallerFoto`
 * que `estudio_fotos`/hero photos). Sin fotos cargadas → no se muestra nada,
 * `TallerHero` sigue cubriendo texto/video como hasta ahora.
 */
export function TallerGaleria({ fotos, alt }: { fotos: TallerFoto[]; alt: string }) {
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [selected, setSelected] = useState(0);
  const [paused, setPaused] = useState(false);
  const reducedMotion = useReducedMotion();

  // Auto-avanza como un carrusel; se detiene con el mouse encima, con el
  // lightbox abierto (no pelear con la navegación de ahí) o con reduced
  // motion. `selected` en las deps reinicia el conteo tras un click manual
  // en una miniatura, en vez de saltar a la próxima segundos después.
  useEffect(() => {
    if (fotos.length <= 1 || paused || reducedMotion || lightboxOpen) return;
    const id = setInterval(() => {
      setSelected((i) => (i + 1) % fotos.length);
    }, AUTOPLAY_MS);
    return () => clearInterval(id);
  }, [fotos.length, paused, reducedMotion, lightboxOpen, selected]);

  if (fotos.length === 0) return null;

  // Mismo orden que el hero del catálogo: principal primero, después `orden`.
  const sorted = [...fotos].sort(
    (a, b) => Number(b.es_principal) - Number(a.es_principal) || a.orden - b.orden || a.id - b.id,
  );
  const toHeroPhoto = (f: TallerFoto): HeroPhoto => ({
    url: f.url,
    urlSm: f.url_sm ?? undefined,
    urlAvif: f.url_avif ?? undefined,
    urlSmAvif: f.url_sm_avif ?? undefined,
  });

  const portada = sorted[Math.min(selected, sorted.length - 1)];
  const imgProps = heroImgProps(toHeroPhoto(portada), { eager: true });

  return (
    <div
      className="bg-ink"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <button
        type="button"
        className="block w-full cursor-zoom-in"
        onClick={() => {
          setLightboxIndex(selected);
          setLightboxOpen(true);
        }}
        aria-label="Ver en pantalla completa"
      >
        <img
          // `key` fuerza un DOM node nuevo por foto: el `onError` de
          // `heroImgProps` marca `dataset.fellBack` en el <img> para no
          // loopear si AVIF falla — pero ese flag vive en el elemento, no en
          // React state. Sin `key`, clickear miniaturas reusa el mismo nodo
          // y, tras el primer fallback, el guard bloquea el fallback de
          // CUALQUIER foto siguiente cuyo AVIF también falle (queda rota).
          key={portada.id}
          {...imgProps}
          alt={alt}
          // Antes h-[vh] puro: en pantallas anchas la altura no seguía el
          // ancho, así que el recorte se iba mucho más allá de panorámico
          // (una foto vertical/cuadrada quedaba irreconocible). aspect-ratio
          // real: 3:2 (el más común en fotografía) achicándose hasta 16:9 en
          // pantallas anchas — nunca más ancho que eso.
          className="w-full aspect-[3/2] sm:aspect-video object-cover"
          draggable={false}
        />
      </button>

      {sorted.length > 1 && (
        <div
          className="flex gap-2 overflow-x-auto px-4 py-3 sm:px-6"
          role="list"
          aria-label="Miniaturas de la galería"
        >
          {sorted.map((f, i) => (
            <button
              key={f.id}
              type="button"
              role="listitem"
              onClick={() => setSelected(i)}
              aria-label={`Foto ${i + 1}${f.es_principal ? " (portada)" : ""}`}
              aria-pressed={i === selected}
              className={`shrink-0 w-16 h-16 rounded overflow-hidden border-2 transition-colors ${
                i === selected ? "border-amber" : "border-background/15 hover:border-amber/40"
              }`}
            >
              <img
                src={f.url_sm ?? f.url}
                alt=""
                className="w-full h-full object-cover"
                loading="lazy"
                draggable={false}
              />
            </button>
          ))}
        </div>
      )}

      <Lightbox
        open={lightboxOpen}
        onClose={() => setLightboxOpen(false)}
        photos={sorted.map((f) => ({ url: f.url, alt }))}
        index={lightboxIndex}
        onIndexChange={(i) => {
          setLightboxIndex(i);
          setSelected(i);
        }}
      />
    </div>
  );
}
