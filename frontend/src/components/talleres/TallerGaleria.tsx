import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { TallerFoto } from "@/lib/api";
import { heroImgProps, type HeroPhoto } from "@/lib/studio/hero-photos";
import { Lightbox } from "@/components/rental/Lightbox";
import { useReducedMotion } from "@/hooks/useReducedMotion";

// Misma cadencia que el hero rotante del catálogo (HeroSection/HeroBanner).
const AUTOPLAY_MS = 4500;
// Ancho de la foto activa dentro del carrusel — el resto (~11% por lado)
// deja asomar la foto anterior/siguiente, como un carrusel de verdad.
const SLIDE_WIDTH = 78;
// Exportado: el carrusel queda full-bleed (pedido explícito del dueño), pero
// el título/data del hero y el cuerpo de la página (descripción, programa)
// usan este MISMO ancho — así el texto queda alineado con el borde de la
// foto que se muestra, en vez de una columna angosta centrada aparte. Resta
// el `px-1` (0.25rem por lado) que tiene cada slide.
export const TALLER_CONTENT_WIDTH = `calc(${SLIDE_WIDTH}% - 0.5rem)`;

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
  // Se prende en la PRIMERA navegación manual (teclado/touch/wheel/click) y
  // apaga el autoplay para siempre — no solo reinicia su cuenta regresiva.
  // Antes, el autoplay podía volver a disparar en medio de una sesión de
  // uso activo (una pausa de unos segundos entre gestos alcanzaba) y
  // competía con lo que el usuario estaba haciendo con el trackpad: se
  // sentía "raro"/como si saltara solo (bug real reportado por el dueño).
  const [userInteracted, setUserInteracted] = useState(false);
  const reducedMotion = useReducedMotion();

  // Auto-avanza como un carrusel; se detiene con el mouse encima, con el
  // lightbox abierto (no pelear con la navegación de ahí), con reduced
  // motion, o apenas el usuario tocó un control manual una vez.
  useEffect(() => {
    if (fotos.length <= 1 || paused || reducedMotion || lightboxOpen || userInteracted) return;
    const id = setInterval(() => {
      setSelected((i) => (i + 1) % fotos.length);
    }, AUTOPLAY_MS);
    return () => clearInterval(id);
  }, [fotos.length, paused, reducedMotion, lightboxOpen, userInteracted]);

  // Mismo orden que el hero del catálogo: principal primero, después `orden`.
  // Calculado ANTES del early-return de abajo (fotos.length === 0) porque
  // los hooks de acá abajo (useRef/useEffect) lo necesitan — un hook no
  // puede quedar después de un return condicional (Rules of Hooks: mismo
  // orden en todos los renders). Sobre `fotos=[]` da `sorted=[]` sin error.
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
  const isCarousel = sorted.length > 1;

  // Pedido del dueño: navegar el carrusel con flechas de teclado, swipe
  // táctil y el gesto de 2 dedos del trackpad — además de los botones/clicks
  // que ya había. `goPrev`/`goNext` quedan como funciones planas (no
  // `useCallback`): las usan handlers JSX normales (botones, teclado,
  // touch), que no tienen el problema de dependencias de un `useEffect`.
  const goPrev = () => {
    setUserInteracted(true);
    setSelected((i) => (i - 1 + sorted.length) % sorted.length);
  };
  const goNext = () => {
    setUserInteracted(true);
    setSelected((i) => (i + 1) % sorted.length);
  };

  // Teclado: SOLO mientras el carrusel (o algo adentro) tiene foco — a
  // diferencia del Lightbox (modal, escucha global), acá secuestrar las
  // flechas del `window` entero rompería scroll/otros controles de la
  // página cuando el foco está en cualquier otro lado.
  function handleCarouselKeyDown(e: React.KeyboardEvent) {
    if (!isCarousel) return;
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      goPrev();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      goNext();
    }
  }

  const touchStart = useRef<{ x: number; y: number } | null>(null);
  function handleTouchStart(e: React.TouchEvent) {
    const t = e.touches[0];
    touchStart.current = { x: t.clientX, y: t.clientY };
  }
  function handleTouchEnd(e: React.TouchEvent) {
    if (!touchStart.current || !isCarousel) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - touchStart.current.x;
    const dy = t.clientY - touchStart.current.y;
    touchStart.current = null;
    // Umbral + más horizontal que vertical: swipe intencional, no un toque
    // que tiembla un poco al scrollear la página verticalmente.
    if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) {
      if (dx > 0) goPrev();
      else goNext();
    }
  }

  // Wheel = el gesto de 2 dedos del trackpad. Acumula el deltaX de TODA la
  // ráfaga que dispara un swipe físico (el trackpad manda muchos eventos
  // wheel seguidos, con "momentum" que sigue después de levantar los
  // dedos) y decide UNA sola vez cuando la ráfaga se queda quieta —
  // versión anterior navegaba por-evento con throttle, así que un swipe
  // largo/con momentum podía saltar 2-3 fotos de una (bug real, reportado
  // por el dueño: "se mueve raro"). `preventDefault()` en TODO evento
  // horizontal, no solo en el que dispara la navegación — sin eso el
  // browser sigue viendo delta sin frenar en la parte de la ráfaga que no
  // navega, y en algunos browsers alcanza para disparar su propio gesto de
  // "volver atrás" (reportado: "se me fue para la pantalla anterior").
  // Listener NATIVO vía ref, no el `onWheel` sintético de React: React
  // marca wheel/touch como passive por default (perf), así que un
  // `preventDefault()` adentro de un `onWheel` de JSX se ignora en
  // silencio.
  const carouselRef = useRef<HTMLDivElement>(null);
  const wheelAccum = useRef(0);
  const wheelTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    const el = carouselRef.current;
    if (!el || !isCarousel) return;
    const onWheel = (e: WheelEvent) => {
      if (Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;
      e.preventDefault();
      wheelAccum.current += e.deltaX;
      if (wheelTimer.current) clearTimeout(wheelTimer.current);
      wheelTimer.current = setTimeout(() => {
        const total = wheelAccum.current;
        wheelAccum.current = 0;
        if (Math.abs(total) < 60) return; // ruido/cola de momentum casi nula
        setUserInteracted(true);
        setSelected((i) =>
          total > 0 ? (i + 1) % sorted.length : (i - 1 + sorted.length) % sorted.length,
        );
      }, 100);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      el.removeEventListener("wheel", onWheel);
      if (wheelTimer.current) clearTimeout(wheelTimer.current);
    };
  }, [isCarousel, sorted.length]);

  if (fotos.length === 0) return null;

  // Antes h-[vh] puro: en pantallas anchas la altura no seguía el ancho, así
  // que el recorte se iba mucho más allá de panorámico (una foto vertical/
  // cuadrada quedaba irreconocible). aspect-ratio real: 3:2 (el más común en
  // fotografía) achicándose hasta 16:9 en pantallas anchas — nunca más ancho.
  const photoAspectClass = "aspect-[3/2] sm:aspect-video object-cover";

  return (
    <div
      className="bg-ink"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      {isCarousel ? (
        // overflow-clip (no -hidden): -hidden igual crea un contenedor
        // scrolleable — un click/foco en un botón que queda posicionado
        // afuera del recorte (foto vecina, flecha) dispara scrollIntoView
        // del browser, que mueve `scrollLeft` por su cuenta y desincroniza
        // todo del translateX que ya lo posiciona (confirmado midiendo
        // getBoundingClientRect: apareció un scrollLeft de 466px después de
        // un solo click). clip nunca crea ese contenedor scrolleable.
        <div
          ref={carouselRef}
          className="relative overflow-clip outline-none [overscroll-behavior-x:none] focus-visible:ring-2 focus-visible:ring-amber/60 focus-visible:ring-offset-2 focus-visible:ring-offset-ink"
          tabIndex={0}
          role="region"
          aria-roledescription="carousel"
          aria-label="Galería de fotos"
          onKeyDown={handleCarouselKeyDown}
          onTouchStart={handleTouchStart}
          onTouchEnd={handleTouchEnd}
        >
          <div
            className="flex transition-transform duration-500 ease-out"
            style={{ transform: `translateX(calc(50% - ${(selected + 0.5) * SLIDE_WIDTH}%))` }}
          >
            {sorted.map((f, i) => {
              const active = i === selected;
              // Solo la activa + sus vecinas inmediatas asoman de verdad —
              // el resto queda lazy (evita cargar TODAS las fotos de una).
              const slideImgProps = heroImgProps(toHeroPhoto(f), {
                eager: Math.abs(i - selected) <= 1,
              });
              return (
                <div key={f.id} className="shrink-0 px-1" style={{ width: `${SLIDE_WIDTH}%` }}>
                  <button
                    type="button"
                    className={`block w-full cursor-pointer overflow-hidden rounded-lg transition-[opacity,transform] duration-500 ${
                      active ? "cursor-zoom-in opacity-100" : "scale-[0.94] opacity-45"
                    }`}
                    onClick={() => {
                      if (!active) {
                        setUserInteracted(true);
                        setSelected(i);
                        return;
                      }
                      setLightboxIndex(i);
                      setLightboxOpen(true);
                    }}
                    aria-label={active ? "Ver en pantalla completa" : `Ver foto ${i + 1}`}
                  >
                    {/* `key` fuerza un DOM node nuevo por foto: el `onError`
                        de `heroImgProps` marca `dataset.fellBack` en el <img>
                        para no loopear si AVIF falla — pero ese flag vive en
                        el elemento, no en React state. Sin `key`, cambiar de
                        foto reusaría el mismo nodo y, tras el primer
                        fallback, el guard bloquearía el de cualquier foto
                        siguiente cuyo AVIF también falle (queda rota). */}
                    <img
                      key={f.id}
                      {...slideImgProps}
                      alt={active ? alt : ""}
                      className={`w-full ${photoAspectClass}`}
                      draggable={false}
                    />
                  </button>
                </div>
              );
            })}
          </div>

          <button
            type="button"
            onClick={goPrev}
            aria-label="Foto anterior"
            className="absolute left-3 top-1/2 z-10 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full bg-white/10 text-white transition hover:bg-white/20"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
          <button
            type="button"
            onClick={goNext}
            aria-label="Foto siguiente"
            className="absolute right-3 top-1/2 z-10 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full bg-white/10 text-white transition hover:bg-white/20"
          >
            <ChevronRight className="h-5 w-5" />
          </button>
        </div>
      ) : (
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
            key={portada.id}
            {...heroImgProps(toHeroPhoto(portada), { eager: true })}
            alt={alt}
            className={`w-full ${photoAspectClass}`}
            draggable={false}
          />
        </button>
      )}

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
              onClick={() => {
                setUserInteracted(true);
                setSelected(i);
              }}
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
