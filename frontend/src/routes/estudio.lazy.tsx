import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createLazyFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, MessageCircle, MapPin } from "lucide-react";
import { StudioBookingForm } from "@/components/studio/StudioBookingForm";
import { STUDIO, STUDIO_PHONE } from "@/data/studio";
import { apiGetEstudio, type EstudioTrabajo, type EstudioMedia } from "@/lib/api";
import { formatARS } from "@/lib/format";
import { cn } from "@/lib/utils";
import { PublicLayout } from "@/components/rental/shell/PublicLayout";
import { Button } from "@/design-system/ui/button";
import { Grain } from "@/components/common/Grain";
import { BoxItemsSection } from "@/components/rental/KitSection";

export const Route = createLazyFileRoute("/estudio")({
  component: EstudioPage,
});

const MAPA_EMBED_DEFAULT =
  "https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d5418.432520284455!2d-57.56597107511356!3d-37.98649647543215!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1!3m3!1m2!1s0x9584db0050a8b0bf%3A0x3860608ed96f47f1!2sRambla%20Estudio%20y%20Rental!5e0!3m2!1ses-419!2sar!4v1782432663360!5m2!1ses-419!2sar";

type Photo = { src: string; alt: string; hero?: boolean; ciclorama?: boolean };

// ── Galería horizontal arrastrable ─────────────────────────────────────────
// ── Trabajos: carrusel + modal ────────────────────────────────────────────────

function extractYtId(url: string): string | null {
  const m = url.match(/(?:v=|\/embed\/|youtu\.be\/)([A-Za-z0-9_-]{11})/);
  return m?.[1] ?? null;
}

const IgIcon = () => (
  <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 shrink-0" fill="currentColor">
    <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z" />
  </svg>
);

const WebIcon = () => (
  <svg
    viewBox="0 0 24 24"
    className="h-3.5 w-3.5 shrink-0"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
  >
    <circle cx="12" cy="12" r="10" />
    <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
  </svg>
);

function ytThumb(ytId: string) {
  return `https://img.youtube.com/vi/${ytId}/maxresdefault.jpg`;
}
function ytThumbFallback(ytId: string) {
  return `https://img.youtube.com/vi/${ytId}/hqdefault.jpg`;
}

// Thumbnail de un medio para la card. Los links traen un thumbnail permanente
// procesado por el backend; si falta (best-effort falló), YouTube cae a su
// thumbnail en vivo.
function mediaThumb(m: EstudioMedia): { src: string; fallback?: string } | null {
  if (m.kind === "foto") {
    const src = m.url_sm ?? m.url;
    return src ? { src } : null;
  }
  if (m.thumbnail) return { src: m.thumbnail };
  if (m.kind === "youtube") {
    const id = extractYtId(m.url);
    if (id) return { src: ytThumb(id), fallback: ytThumbFallback(id) };
  }
  return null;
} // El embed oficial de IG muestra el post completo (foto/video + descripción +
// likes + comentarios). Usamos CSS clipping para mostrar header + media + chrome
// (dots, "View more", action bar, likes, input de comentario) pero NO el texto de
// la descripción ni los hilos de comentarios que vienen después:
// height = min(94vw,480px) * (h/w) + 260px
//   ≈ imagen + 72px (header) + 44px (View more) + 52px (bar) + 24px (likes) + 54px (input) + margen
declare global {
  interface Window {
    instgrm?: { Embeds: { process: () => void } };
  }
}
const IG_EMBED_SCRIPT = "https://www.instagram.com/embed.js";

function loadIgScript(onLoad: () => void) {
  const existing = document.querySelector<HTMLScriptElement>(`script[src="${IG_EMBED_SCRIPT}"]`);
  if (existing) {
    existing.addEventListener("load", onLoad, { once: true });
    return;
  }
  const s = document.createElement("script");
  s.src = IG_EMBED_SCRIPT;
  s.async = true;
  s.addEventListener("load", onLoad, { once: true });
  document.body.appendChild(s);
}

function IgEmbed({ url }: { url: string }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const process = () => window.instgrm?.Embeds?.process();

    // Cargar el script de IG solo cuando el embed entre al viewport (lazy).
    // Protege el LCP: la sección Trabajos está bajo el fold.
    if (window.instgrm) {
      process();
      return;
    }
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          obs.disconnect();
          loadIgScript(process);
        }
      },
      { rootMargin: "200px" },
    );
    obs.observe(container);
    return () => obs.disconnect();
  }, [url]);

  return (
    <div key={url} ref={containerRef} className="flex w-full justify-center">
      <blockquote
        className="instagram-media"
        data-instgrm-permalink={url}
        data-instgrm-version="14"
        style={{ width: "100%", maxWidth: "100%", minWidth: 0, margin: 0 }}
      />
    </div>
  );
}

// Slide individual dentro del lightbox. Activo → embed completo + info.
// Inactivo → thumbnail 4:5 con overlay, clickeable para ir a ese trabajo.
function LightboxSlide({
  idx,
  trabajo,
  isActive,
  onActivate,
}: {
  idx: number;
  trabajo: EstudioTrabajo;
  isActive: boolean;
  onActivate: () => void;
}) {
  const first = trabajo.media[0] ?? null;
  const t = first ? mediaThumb(first) : null;
  const isShort = first?.kind === "youtube" && /\/shorts\//.test(first.url);
  const isLandscapeYt = first?.kind === "youtube" && !isShort;

  const igAr = first?.kind === "instagram" && first.w && first.h ? first.h / first.w : null;
  // Clip IG: altura natural capped a 80dvh para no rebasar la pantalla.
  const igClipH = igAr
    ? `min(calc(min(88vw, 520px) * ${igAr.toFixed(4)} + 260px), 80dvh)`
    : "min(70dvh, 80dvh)";

  return (
    <div
      data-slide-idx={idx}
      className={cn(
        "snap-center shrink-0 flex flex-col rounded-2xl overflow-hidden transition-[opacity,transform] duration-300",
        // Mobile: portrait para todo. Desktop (md+): landscape YouTube → 70vw.
        isLandscapeYt ? "w-[min(88vw,520px)] md:w-[70vw]" : "w-[min(88vw,520px)]",
        isActive
          ? "opacity-100 scale-[1.08] z-10"
          : "opacity-40 scale-[0.88] cursor-pointer hover:opacity-60",
      )}
      onClick={!isActive ? onActivate : undefined}
    >
      {isActive ? (
        // ── Slide activo: embed real ──────────────────────────────────────────
        <div className="shrink-0">
          {first?.kind === "youtube" &&
            (() => {
              const ytId = extractYtId(first.url);
              if (!ytId) return null;
              return (
                <div className="w-full" style={{ aspectRatio: isShort ? "9/16" : "16/9" }}>
                  <iframe
                    src={`https://www.youtube-nocookie.com/embed/${ytId}?autoplay=1`}
                    title={trabajo.titulo}
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowFullScreen
                    className="w-full h-full"
                  />
                </div>
              );
            })()}

          {first?.kind === "instagram" && (
            <div
              className="relative w-full bg-muted"
              style={{ height: igClipH, overflow: "hidden" }}
            >
              <IgEmbed key={first.url} url={first.url} />
              <a
                href={first.url}
                target="_blank"
                rel="noopener noreferrer"
                className="absolute bottom-2 right-2 z-10 flex items-center gap-1.5 rounded-full bg-black/55 px-3 py-1.5 text-xs text-background/80 hover:text-background transition-colors"
                aria-label="Ver en Instagram"
              >
                <IgIcon />
                Ver en Instagram
              </a>
            </div>
          )}

          {first?.kind === "foto" && (
            <img
              src={
                (first as EstudioMedia & { url_avif?: string }).url_avif ??
                first.url_sm ??
                first.url
              }
              alt={trabajo.titulo}
              className="w-full object-contain max-h-[70dvh]"
            />
          )}
        </div>
      ) : (
        // ── Slide inactivo: thumbnail 4:5 ─────────────────────────────────────
        <div className="relative overflow-hidden" style={{ aspectRatio: "4/5" }}>
          {t?.src ? (
            <img
              src={t.src}
              alt={trabajo.titulo}
              className="w-full h-full object-cover"
              loading="lazy"
              onError={
                t.fallback
                  ? (e) => {
                      e.currentTarget.src = t.fallback!;
                      e.currentTarget.onerror = null;
                    }
                  : undefined
              }
            />
          ) : (
            <div className="w-full h-full bg-background/5" />
          )}
          <div className="absolute inset-0 bg-black/25" />
          {trabajo.titulo && (
            <div className="absolute bottom-0 inset-x-0 p-3">
              <p className="text-xs text-background/70 font-medium truncate">{trabajo.titulo}</p>
            </div>
          )}
        </div>
      )}

      {/* Info */}
      <div className="px-5 py-4 space-y-2 overflow-y-auto">
        {trabajo.categorias.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {trabajo.categorias.map((cat) => (
              <span
                key={cat}
                className="rounded-full border border-[color-mix(in_oklch,var(--area-accent)_40%,transparent)] px-2.5 py-0.5 font-mono text-2xs uppercase tracking-[0.15em] text-[var(--area-accent)]"
              >
                {cat}
              </span>
            ))}
          </div>
        )}
        {trabajo.titulo && (
          <h3 className="font-display font-bold text-background text-lg leading-tight">
            {trabajo.titulo}
          </h3>
        )}
        {trabajo.descripcion && (
          <p className="text-sm text-background/55 leading-relaxed line-clamp-3">
            {trabajo.descripcion}
          </p>
        )}
        {trabajo.realizador && (
          <div className="flex items-center gap-2 flex-wrap">
            {trabajo.realizador_logo_url && (
              <img
                src={trabajo.realizador_logo_url}
                alt={trabajo.realizador}
                className="h-5 w-5 rounded object-contain border border-background/10 shrink-0"
              />
            )}
            <span className="text-sm font-medium text-background/65">{trabajo.realizador}</span>
            {trabajo.realizador_instagram && (
              <a
                href={`https://instagram.com/${trabajo.realizador_instagram.replace(/^@/, "")}`}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-1 flex items-center gap-1 text-xs text-background/35 hover:text-[var(--area-accent)] transition-colors"
              >
                <IgIcon />
                {trabajo.realizador_instagram.startsWith("@")
                  ? trabajo.realizador_instagram
                  : `@${trabajo.realizador_instagram}`}
              </a>
            )}
            {trabajo.realizador_web && (
              <a
                href={
                  trabajo.realizador_web.startsWith("http")
                    ? trabajo.realizador_web
                    : `https://${trabajo.realizador_web}`
                }
                target="_blank"
                rel="noopener noreferrer"
                className="ml-1 flex items-center gap-1 text-xs text-background/35 hover:text-[var(--area-accent)] transition-colors"
              >
                <WebIcon />
                {trabajo.realizador_web.replace(/^https?:\/\//, "").replace(/\/$/, "")}
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// Lightbox de carrusel: todos los trabajos en un snap-scroll horizontal.
// El slide centrado muestra el embed; los de los costados muestran el thumbnail
// con opacidad reducida (asoman desde los bordes).
function TrabajoLightbox({
  trabajos,
  initialIdx,
  onClose,
}: {
  trabajos: EstudioTrabajo[];
  initialIdx: number;
  onClose: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [activeIdx, setActiveIdx] = useState(initialIdx);

  // Scroll al slide inicial (sin animación) tras el primer render.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      const target = el.querySelector<HTMLElement>(`[data-slide-idx="${initialIdx}"]`);
      if (!target) return;
      const targetCenter = target.offsetLeft + target.offsetWidth / 2;
      el.scrollLeft = targetCenter - el.clientWidth / 2;
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Trackear qué slide está centrado mientras el usuario scrollea.
  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const cx = el.scrollLeft + el.clientWidth / 2;
    const slides = el.querySelectorAll<HTMLElement>("[data-slide-idx]");
    let best = activeIdx;
    let bestDist = Infinity;
    slides.forEach((s) => {
      const i = Number(s.dataset.slideIdx);
      const d = Math.abs(s.offsetLeft + s.offsetWidth / 2 - cx);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    if (best !== activeIdx) setActiveIdx(best);
  }, [activeIdx]);

  // Helper: scroll suave a un slide por índice.
  const scrollToIdx = useCallback((idx: number) => {
    const el = scrollRef.current;
    const target = el?.querySelector<HTMLElement>(`[data-slide-idx="${idx}"]`);
    if (!target || !el) return;
    const targetCenter = target.offsetLeft + target.offsetWidth / 2;
    el.scrollTo({ left: targetCenter - el.clientWidth / 2, behavior: "smooth" });
  }, []);

  // Teclado: Escape cierra, flechas navegan.
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft") scrollToIdx(Math.max(0, activeIdx - 1));
      else if (e.key === "ArrowRight") scrollToIdx(Math.min(trabajos.length - 1, activeIdx + 1));
    };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, [onClose, activeIdx, trabajos.length, scrollToIdx]);

  // Bloquear scroll del body mientras el lightbox está abierto.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  // Spacers al inicio/fin para que el primer y último slide puedan centrarse.
  // spacerW = (100vw - slideW) / 2 - gap/2  (gap = 12px → mitad = 6px)
  // En mobile todos los slides son portrait; en desktop los landscape usan 70vw.
  const firstMedia = trabajos[0]?.media[0];
  const lastMedia = trabajos[trabajos.length - 1]?.media[0];
  const firstIsLandscape = firstMedia?.kind === "youtube" && !/\/shorts\//.test(firstMedia.url);
  const lastIsLandscape = lastMedia?.kind === "youtube" && !/\/shorts\//.test(lastMedia.url);
  // Clase base: portrait (mobile + portrait content). Extensión md: landscape desktop.
  const SPACER_BASE = "shrink-0 w-[max(0px,calc((100vw-min(88vw,520px))/2-6px))]";
  const SPACER_LG_MD = "md:w-[max(0px,calc(15vw-6px))]";

  return (
    <div className="fixed inset-0 z-50 bg-black/95">
      {/* Cerrar */}
      <button
        onClick={onClose}
        className="absolute top-4 right-4 z-20 h-11 w-11 rounded-full bg-white/10 flex items-center justify-center text-white/70 hover:text-white transition-colors"
        aria-label="Cerrar"
      >
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
        >
          <path d="M18 6L6 18M6 6l12 12" />
        </svg>
      </button>

      {/* Flechas de navegación (desktop) */}
      {activeIdx > 0 && (
        <button
          onClick={() => scrollToIdx(activeIdx - 1)}
          className="absolute left-3 top-1/2 -translate-y-1/2 z-20 h-10 w-10 rounded-full bg-white/10 items-center justify-center text-white/70 hover:text-white transition-colors hidden md:flex"
          aria-label="Anterior"
        >
          <ArrowLeft className="h-5 w-5" />
        </button>
      )}
      {activeIdx < trabajos.length - 1 && (
        <button
          onClick={() => scrollToIdx(activeIdx + 1)}
          className="absolute right-3 top-1/2 -translate-y-1/2 z-20 h-10 w-10 rounded-full bg-white/10 items-center justify-center text-white/70 hover:text-white transition-colors hidden md:flex"
          aria-label="Siguiente"
        >
          <ArrowRight className="h-5 w-5" />
        </button>
      )}

      {/* Carrusel */}
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="h-full flex items-center overflow-x-auto snap-x snap-mandatory [&::-webkit-scrollbar]:hidden"
        style={{ gap: "12px" }}
      >
        {/* Spacer inicial: permite centrar el primer slide */}
        <div className={cn(SPACER_BASE, firstIsLandscape && SPACER_LG_MD)} />

        {trabajos.map((trabajo, i) => (
          <LightboxSlide
            key={trabajo.id}
            idx={i}
            trabajo={trabajo}
            isActive={i === activeIdx}
            onActivate={() => scrollToIdx(i)}
          />
        ))}

        {/* Spacer final: permite centrar el último slide */}
        <div className={cn(SPACER_BASE, lastIsLandscape && SPACER_LG_MD)} />
      </div>
    </div>
  );
}

// Card del carrusel. Alto fijo, ancho según la proporción REAL del thumbnail
// (vertical/cuadrado/horizontal) — sin recortar. Las dimensiones vienen del
// backend (links) o se miden al cargar la imagen (fotos); default 4/5 vertical.
function TrabajoCard({ trabajo, onOpen }: { trabajo: EstudioTrabajo; onOpen: () => void }) {
  const first = trabajo.media[0];
  const hasVideo = trabajo.media.some((m) => m.kind !== "foto");
  const t = first ? mediaThumb(first) : null;
  const multi = trabajo.media.length > 1;

  const initial = first && first.w && first.h ? first.w / first.h : null;
  const [aspect, setAspect] = useState<number | null>(initial);
  const rawAr = aspect ?? 4 / 5;
  // Para IG, la og:image puede tener proporciones extremas (9:16 Reels, crops)
  // que no representan el display real. Clampear a [4:5, 16:9] — rango nativo de IG.
  const ar = first?.kind === "instagram" ? Math.min(Math.max(rawAr, 4 / 5), 16 / 9) : rawAr;
  // El ancho de la card sale del alto base × la proporción real, topado a 86vw.
  // El thumbnail usa `aspect-ratio` (no alto fijo) → si el ancho topa en mobile,
  // baja el alto y la proporción se mantiene (un video horizontal no se recorta).
  const CARD_H = "clamp(12rem, 40vh, 22rem)";

  return (
    <button
      onClick={onOpen}
      className="snap-start shrink-0 rounded-xl overflow-hidden border border-background/10 bg-background/5 text-left group"
      style={{ width: `min(calc(${CARD_H} * ${ar}), 86vw)` }}
      draggable={false}
    >
      {/* Thumbnail — proporción real del medio (sin recortar) */}
      <div className="relative w-full overflow-hidden bg-background/5" style={{ aspectRatio: ar }}>
        {t?.src ? (
          <img
            src={t.src}
            alt={trabajo.titulo}
            loading="lazy"
            draggable={false}
            onLoad={(e) => {
              const w = e.currentTarget.naturalWidth;
              const h = e.currentTarget.naturalHeight;
              if (w && h) setAspect(w / h);
            }}
            onError={
              t.fallback
                ? (e) => {
                    e.currentTarget.src = t.fallback!;
                    e.currentTarget.onerror = null;
                  }
                : undefined
            }
            className="h-full w-full object-cover pointer-events-none transition-transform duration-500 group-hover:scale-[1.04]"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-background/15 text-xs">sin imagen</span>
          </div>
        )}
        {/* Play badge */}
        {hasVideo && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/20 group-hover:bg-black/30 transition-colors">
            <div className="h-10 w-10 rounded-full bg-background/85 flex items-center justify-center shadow group-hover:scale-110 transition-transform">
              <svg viewBox="0 0 24 24" className="h-4 w-4 text-ink ml-0.5" fill="currentColor">
                <path d="M8 5v14l11-7z" />
              </svg>
            </div>
          </div>
        )}
        {/* Indicador de varios medios (estilo carrusel IG) */}
        {multi && (
          <div className="absolute top-2 right-2 rounded-full bg-black/55 px-2 py-0.5 flex items-center gap-1 text-background/90">
            <svg
              viewBox="0 0 24 24"
              className="h-3 w-3"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <rect x="8" y="8" width="12" height="12" rx="2" />
              <path d="M4 16V6a2 2 0 0 1 2-2h10" />
            </svg>
            <span className="font-mono text-2xs">{trabajo.media.length}</span>
          </div>
        )}
      </div>

      {/* Footer compacto */}
      <div className="px-3 py-2.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            {trabajo.titulo && (
              <p className="text-sm font-semibold text-background leading-snug truncate">
                {trabajo.titulo}
              </p>
            )}
            {trabajo.realizador && (
              <p className="text-xs text-background/45 truncate mt-0.5">{trabajo.realizador}</p>
            )}
          </div>
          {trabajo.categoria && (
            <span className="shrink-0 rounded-full bg-[color-mix(in_oklch,var(--area-accent)_15%,transparent)] px-2 py-0.5 font-mono text-2xs uppercase tracking-[0.1em] text-[color-mix(in_oklch,var(--area-accent)_80%,transparent)] whitespace-nowrap">
              {trabajo.categoria}
            </span>
          )}
        </div>
      </div>
    </button>
  );
}

function TrabajosSection({ trabajos }: { trabajos: EstudioTrabajo[] }) {
  const [filtro, setFiltro] = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const drag = useRef({ active: false, startX: 0, startScroll: 0, moved: false });

  const categorias = useMemo(() => {
    const set = new Set<string>();
    trabajos.forEach((t) => t.categorias.forEach((c) => set.add(c)));
    return [...set];
  }, [trabajos]);

  const visibles = filtro ? trabajos.filter((t) => t.categorias.includes(filtro)) : trabajos;

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el) return;
    drag.current = { active: true, startX: e.clientX, startScroll: el.scrollLeft, moved: false };
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current.active || !ref.current) return;
    const dx = e.clientX - drag.current.startX;
    if (Math.abs(dx) > 4) {
      drag.current.moved = true;
      ref.current.scrollLeft = drag.current.startScroll - dx;
    }
  };
  const onPointerUp = () => {
    drag.current.active = false;
  };

  return (
    <section className="bg-ink py-14">
      <div className="px-4 lg:px-12 mb-8">
        <p className="font-mono text-2xs uppercase tracking-[0.3em] text-[var(--area-accent)] mb-2.5">
          Producciones
        </p>
        <h2 className="font-display font-black lowercase leading-[0.9] text-[var(--area-accent)] text-[clamp(2rem,6vw,3.5rem)]">
          en acción.
        </h2>
        <p className="mt-3 text-15 text-background/55 max-w-md">
          Trabajos hechos por gente copada que pasó por el estudio.
        </p>
        {/* Filtros */}
        {categorias.length > 1 && (
          <div className="flex flex-wrap gap-2 mt-6">
            <button
              onClick={() => setFiltro(null)}
              className={cn(
                "rounded-full px-3.5 py-1.5 font-mono text-2xs uppercase tracking-[0.15em] transition-colors",
                filtro === null
                  ? "bg-[var(--area-accent)] text-ink"
                  : "border border-background/20 text-background/50 hover:border-background/40 hover:text-background/80",
              )}
            >
              Todo
            </button>
            {categorias.map((cat) => (
              <button
                key={cat}
                onClick={() => setFiltro(filtro === cat ? null : cat)}
                className={cn(
                  "rounded-full px-3.5 py-1.5 font-mono text-2xs uppercase tracking-[0.15em] transition-colors",
                  filtro === cat
                    ? "bg-amber text-ink"
                    : "border border-background/20 text-background/50 hover:border-background/40 hover:text-background/80",
                )}
              >
                {cat}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Carrusel */}
      <div
        ref={ref}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        className="flex gap-3 overflow-x-auto px-4 pb-2 lg:px-12 scroll-pl-4 lg:scroll-pl-12 snap-x snap-mandatory [&::-webkit-scrollbar]:hidden [scrollbar-width:none] cursor-grab active:cursor-grabbing select-none"
      >
        {visibles.map((trabajo, i) => (
          <TrabajoCard
            key={trabajo.id}
            trabajo={trabajo}
            onOpen={() => {
              if (!drag.current.moved) setSelectedIdx(i);
            }}
          />
        ))}
      </div>

      {selectedIdx !== null && (
        <TrabajoLightbox
          trabajos={visibles}
          initialIdx={selectedIdx}
          onClose={() => setSelectedIdx(null)}
        />
      )}
    </section>
  );
}

function DragGallery({ photos, compact = false }: { photos: Photo[]; compact?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [canPrev, setCanPrev] = useState(false);
  const [canNext, setCanNext] = useState(true);
  const drag = useRef({ active: false, startX: 0, startScroll: 0 });

  const update = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    setCanPrev(el.scrollLeft > 4);
    setCanNext(el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
  }, []);

  useEffect(() => {
    update();
    const el = ref.current;
    if (!el) return;
    el.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      el.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [update]);

  const scrollBy = (dir: 1 | -1) => {
    const el = ref.current;
    if (!el) return;
    el.scrollBy({ left: dir * Math.round(el.clientWidth * 0.8), behavior: "smooth" });
  };

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.pointerType !== "mouse") return;
    const el = ref.current;
    if (!el) return;
    drag.current = { active: true, startX: e.clientX, startScroll: el.scrollLeft };
    el.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current.active) return;
    const el = ref.current;
    if (!el) return;
    el.scrollLeft = drag.current.startScroll - (e.clientX - drag.current.startX);
  };
  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (el?.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
    drag.current.active = false;
  };

  const arrowCls = compact
    ? "absolute top-1/2 -translate-y-1/2 hidden lg:grid h-9 w-9 place-items-center rounded-full bg-black/55 hover:bg-black/75 text-background transition"
    : "absolute top-1/2 -translate-y-1/2 hidden lg:grid h-10 w-10 place-items-center rounded-full bg-background/90 border hairline backdrop-blur shadow-sm transition";

  return (
    <div className="relative">
      <div
        ref={ref}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        className={cn(
          "flex gap-3 overflow-x-auto snap-x snap-mandatory [&::-webkit-scrollbar]:hidden [scrollbar-width:none] cursor-grab active:cursor-grabbing select-none touch-pan-x",
          compact ? "px-4 pb-4 pt-5 scroll-pl-4" : "px-4 pb-2 lg:px-12 scroll-pl-4 lg:scroll-pl-12",
        )}
      >
        {photos.map((photo, i) => (
          <div
            key={photo.src}
            className={cn(
              "snap-start shrink-0 aspect-[4/3] overflow-hidden rounded-xl bg-surface",
              compact ? "basis-[82%] sm:basis-[60%]" : "basis-[86%] sm:basis-[56%] lg:basis-[36%]",
            )}
          >
            <img
              src={photo.src}
              alt={photo.alt}
              loading={i < 3 ? "eager" : "lazy"}
              draggable={false}
              className="h-full w-full object-cover pointer-events-none select-none"
            />
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={() => scrollBy(-1)}
        disabled={!canPrev}
        aria-label="Foto anterior"
        className={cn(
          arrowCls,
          "left-3",
          canPrev
            ? "hover:bg-ink hover:text-[var(--area-accent)] hover:border-ink"
            : "opacity-0 pointer-events-none",
        )}
      >
        <ArrowLeft className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={() => scrollBy(1)}
        disabled={!canNext}
        aria-label="Foto siguiente"
        className={cn(
          arrowCls,
          "right-3",
          canNext
            ? "hover:bg-ink hover:text-[var(--area-accent)] hover:border-ink"
            : "opacity-0 pointer-events-none",
        )}
      >
        <ArrowRight className="h-4 w-4" />
      </button>
    </div>
  );
}

// ── Barra mobile fija ──────────────────────────────────────────────────────
function MobileBookBar({ priceLabel }: { priceLabel: string }) {
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    const target = document.getElementById("reservar");
    if (!target) return;
    const obs = new IntersectionObserver((entries) => setHidden(entries[0].isIntersecting), {
      threshold: 0,
    });
    obs.observe(target);
    return () => obs.disconnect();
  }, []);

  return (
    <div
      className={cn(
        "fixed inset-x-0 bottom-0 z-40 lg:hidden transition-transform duration-200",
        hidden ? "translate-y-full" : "translate-y-0",
      )}
      aria-hidden={hidden}
    >
      <div className="flex items-center gap-3 border-t hairline bg-background/95 backdrop-blur-xl px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
        <div className="min-w-0 flex-1">
          <div className="t-eyebrow">Reservar el estudio</div>
          <div className="truncate text-sm font-medium">{priceLabel}</div>
        </div>
        <Button
          asChild
          variant="primary"
          shape="pill"
          className="min-h-11 h-auto px-5 py-2.5 font-semibold shrink-0"
        >
          <a href="#reservar">Reservar</a>
        </Button>
      </div>
    </div>
  );
}

// ── Página principal ───────────────────────────────────────────────────────
function EstudioPage() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["estudio"],
    queryFn: apiGetEstudio,
    retry: 2,
  });

  const precioHora = data?.precio_hora ?? STUDIO.pricePerHour;
  const minHours = data?.min_horas ?? STUDIO.minHours;
  const promo = data?.promo ?? null;
  const trabajos = useMemo(() => data?.trabajos ?? [], [data?.trabajos]);
  const faq = data?.faq ?? STUDIO.faq;
  const features = data?.features ?? STUDIO.features;

  // Structured data FAQPage (rich snippets de Google), mismo patrón que
  // /preguntas-frecuentes: inyectado client-side desde las FAQ en vivo (así
  // refleja lo editado en el back-office). El backend (`estudio_page` en
  // main.py) ya lo sirve server-side para crawlers sin JS con el mismo
  // `estudio.faq_json` — esto es lo que ve un lector que SÍ ejecuta JS.
  useEffect(() => {
    const items = faq.filter((f) => f.q.trim() && f.a.trim());
    if (items.length === 0) return;
    const schema = {
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: items.map((it) => ({
        "@type": "Question",
        name: it.q,
        acceptedAnswer: { "@type": "Answer", text: it.a },
      })),
    };
    const el = document.createElement("script");
    el.type = "application/ld+json";
    el.dataset.estudioFaqJsonld = "true";
    el.textContent = JSON.stringify(schema);
    document.head.appendChild(el);
    return () => {
      el.remove();
    };
  }, [faq]);

  // Ubicación — admin primero, fallback a coordenadas fijas MDQ
  const direccion = data?.direccion ?? "Mar del Plata, Buenos Aires, Argentina";
  const iframeSrc = data?.mapa_embed_url || MAPA_EMBED_DEFAULT;

  const bookingConfig = data
    ? {
        pricePerHour: data.precio_hora,
        minHours: data.min_horas,
        openHour: data.open_hour,
        closeHour: data.close_hour,
        promo: data.promo,
        precioPinturaReciente: data.precio_pintura_reciente,
        anticipacionMinHoras: data.anticipacion_min_horas,
        anticipacionPinturaHoras: data.anticipacion_pintura_horas,
      }
    : undefined;

  const priceLabel = `${formatARS(precioHora)} / hora · mín ${minHours}h`;

  const photos = useMemo(
    () =>
      (data?.fotos ?? []).map((f) => ({
        src: f.url,
        alt: "El Estudio",
        hero: f.es_principal,
        ciclorama: false as const,
      })),
    [data?.fotos],
  );
  const heroPhoto = photos.find((p) => p.hero) ?? photos[0];

  const [withPromo, setWithPromo] = useState(false);

  // Skeleton de carga inicial (solo cuando no hay data de cache)
  if (isLoading && !data) {
    return (
      <PublicLayout
        topBar={{ variant: "estudio", cta: { label: "Reservar el estudio", href: "#reservar" } }}
      >
        <div className="flex flex-1 flex-col gap-6 px-4 lg:px-12 py-16 animate-pulse">
          <div className="h-8 w-48 rounded-md bg-surface" />
          <div className="h-[clamp(8rem,20vw,14rem)] w-full max-w-md rounded-xl bg-surface" />
          <div className="h-4 w-64 rounded-md bg-surface" />
          <div className="h-4 w-40 rounded-md bg-surface" />
        </div>
      </PublicLayout>
    );
  }

  // Error de red — mostramos un estado claro con opción de reintentar.
  // El contenido de la página igual se renderiza con los datos estáticos de fallback.
  const networkError = isError;

  return (
    <PublicLayout
      topBar={{ variant: "estudio", cta: { label: "Reservar el estudio", href: "#reservar" } }}
    >
      {networkError && (
        <div
          role="alert"
          className="flex items-center justify-between gap-3 bg-destructive/10 border-b border-destructive/30 px-4 py-3 text-sm text-destructive"
        >
          <span>No se pudo cargar la info actualizada del estudio. Mostrando datos guardados.</span>
          <Button
            variant="outline"
            size="sm"
            shape="pill"
            onClick={() => refetch()}
            className="shrink-0 border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
          >
            Reintentar
          </Button>
        </div>
      )}

      <main>
        {/* ── Hero — ink editorial ──────────────────────────────────── */}
        <section className="relative overflow-hidden bg-ink px-4 lg:px-12 py-[clamp(2.5rem,5vw,4.5rem)] pb-[clamp(3rem,6vw,5rem)]">
          <Grain />
          <div className="relative">
            <p className="font-mono text-2xs uppercase tracking-[0.3em] text-[color-mix(in_oklch,var(--area-accent)_80%,transparent)] mb-4">
              Estudio fotográfico y de video · Mar del Plata
            </p>
            <h1 className="font-display font-black text-[var(--area-accent)] leading-[0.88] tracking-[-0.02em] lowercase text-[clamp(5rem,22vw,13rem)]">
              el estudio.
            </h1>
            <p className="mt-5 max-w-lg text-base leading-relaxed text-background/65">
              Un espacio para producciones audiovisuales con todos los equipos de Rambla a mano.
              Ideal para rodajes grandes — flexible para los chicos.
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-3">
              <Button asChild variant="amber" shape="pill" className="h-auto px-6 py-3 font-bold">
                <a href="#reservar">Reservar</a>
              </Button>
              <span className="inline-flex items-center rounded-full border border-background/20 px-4 py-2 font-mono text-xs text-background/70 tabular-nums whitespace-nowrap">
                {priceLabel}
              </span>
            </div>
          </div>
        </section>

        {/* Foto hero — full-bleed */}
        <div className="aspect-[16/9] md:aspect-[21/9] w-full overflow-hidden bg-ink">
          {heroPhoto && (
            <img
              src={heroPhoto.src}
              alt="El Estudio — Rambla Rental"
              loading="eager"
              fetchPriority="high"
              decoding="async"
              sizes="100vw"
              className="h-full w-full object-cover block"
            />
          )}
        </div>

        {/* ── Ciclorama + galería — split editorial ink ────────────── */}
        <section className="grid lg:grid-cols-2">
          {/* Texto — ink */}
          <div className="relative overflow-hidden bg-ink px-[clamp(1.5rem,4vw,3.5rem)] py-[clamp(2.5rem,5vw,4.5rem)] flex flex-col justify-center">
            <Grain opacity={10} />
            <div className="relative">
              <p className="font-mono text-2xs uppercase tracking-[0.3em] text-[color-mix(in_oklch,var(--area-accent)_80%,transparent)] mb-5">
                La pieza central
              </p>
              <div className="flex items-baseline gap-1 leading-none">
                <span className="font-display font-black text-[var(--area-accent)] leading-[0.88] tracking-[-0.02em] text-[clamp(5rem,14vw,9rem)]">
                  6×6
                </span>
                <span className="font-mono text-[color-mix(in_oklch,var(--area-accent)_80%,transparent)] text-[clamp(1.25rem,3vw,2rem)] mb-1">
                  m
                </span>
              </div>
              <h2 className="font-display font-black text-[var(--area-accent)] lowercase leading-[0.9] tracking-[-0.02em] text-[clamp(2.25rem,6vw,4rem)] mt-1">
                ciclorama.
              </h2>
              <p className="mt-5 max-w-sm text-15 leading-relaxed text-background/65">
                La curva continua elimina el horizonte. Fondo limpio, sin sombras, listo para usar —
                sin postproducción.
              </p>
              <p className="mt-3 text-sm leading-relaxed text-background/50">
                Ideal para retratos, moda, productos, contenido de marca y rodajes comerciales.
              </p>
              <div className="mt-7 flex flex-wrap gap-2">
                {["Curva continua", "Sin sombras", "Potencia extra", "Fondos de papel"].map((t) => (
                  <span
                    key={t}
                    className="inline-flex items-center rounded-full border border-[color-mix(in_oklch,var(--area-accent)_30%,transparent)] px-3.5 py-1 font-mono text-2xs uppercase tracking-[0.2em] text-[color-mix(in_oklch,var(--area-accent)_80%,transparent)] whitespace-nowrap"
                  >
                    {t}
                  </span>
                ))}
              </div>
              <Button
                asChild
                variant="amber"
                shape="pill"
                className="mt-8 self-start h-auto px-5 py-2.5 font-bold"
              >
                <a href="#reservar">
                  Reservar el espacio
                  <ArrowRight className="h-3.5 w-3.5" />
                </a>
              </Button>
            </div>
          </div>
          {/* Galería del espacio */}
          <div className="min-h-72 lg:min-h-0 flex flex-col justify-center overflow-hidden bg-ink border-t lg:border-t-0 lg:border-l border-background/10">
            {photos.length > 0 ? (
              <DragGallery photos={photos} compact />
            ) : (
              <div className="flex-1" />
            )}
          </div>
        </section>

        {/* ── El espacio incluye ────────────────────────────────────── */}
        {(() => {
          const visibles = features.filter((f) => (f.value ?? "").trim().length > 0);
          if (visibles.length === 0) return null;
          return (
            <section className="bg-surface px-4 lg:px-12 py-12">
              <h2 className="font-display font-black lowercase text-[clamp(1.5rem,3vw,2rem)]">
                el espacio incluye.
              </h2>
              <div className="mt-5 grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                {visibles.map((f) => (
                  <div key={f.label} className="card p-3.5">
                    <div className="t-eyebrow mb-1">{f.label}</div>
                    <div className="font-semibold text-15">{f.value}</div>
                  </div>
                ))}
              </div>
            </section>
          );
        })()}

        {/* ── Reservar ─────────────────────────────────────────────── */}
        <section
          id="reservar"
          className="relative overflow-hidden bg-[var(--area-accent)] px-4 lg:px-12 py-14 scroll-mt-16"
        >
          <Grain opacity={14} />
          <div className="relative">
            <div className="flex flex-wrap items-end justify-between gap-3 mb-7">
              <div>
                <p className="font-mono text-2xs uppercase tracking-[0.3em] text-ink mb-2.5">
                  Reservas
                </p>
                <h2 className="font-display font-black lowercase leading-[0.95] text-ink text-[clamp(1.75rem,4vw,2.75rem)]">
                  reservá tu sesión.
                </h2>
                <p className="mt-2.5 max-w-md text-15 text-ink leading-relaxed">
                  Mínimo {minHours} horas. Elegí día y horario — te contactamos para confirmar.
                </p>
              </div>
              <span className="font-mono text-2xs uppercase tracking-[0.2em] text-ink tabular-nums whitespace-nowrap shrink-0">
                {priceLabel}
              </span>
            </div>
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] lg:items-start">
              <StudioBookingForm
                config={bookingConfig}
                withPromo={withPromo}
                onPromoChange={setWithPromo}
              />
              {promo && (
                <aside className="rounded-2xl border border-ink/20 bg-ink/8 p-5 lg:sticky lg:top-20 lg:self-start">
                  <div className="font-mono text-2xs uppercase tracking-[0.2em] text-ink mb-3.5">
                    Estudio + equipos · qué incluye
                  </div>
                  {withPromo ? (
                    <div className="flex flex-col gap-3">
                      {promo.foto_url && (
                        <img
                          src={promo.foto_url}
                          alt={promo.nombre}
                          loading="lazy"
                          className="aspect-video w-full rounded-lg object-cover"
                        />
                      )}
                      <div>
                        <p className="font-semibold text-ink">{promo.nombre}</p>
                        {promo.descripcion && (
                          <p className="mt-1 text-sm text-ink/80 leading-relaxed">
                            {promo.descripcion}
                          </p>
                        )}
                      </div>
                      {promo.componentes.length > 0 && (
                        <BoxItemsSection
                          title="Incluye"
                          items={promo.componentes.map((c) => ({
                            name: c.nombre,
                            qty: c.cantidad,
                            fotoUrl: c.foto_url,
                          }))}
                        />
                      )}
                    </div>
                  ) : (
                    <p className="text-sm text-ink leading-relaxed">
                      Seleccioná "Estudio + {promo.nombre}" para ver el detalle.
                    </p>
                  )}
                </aside>
              )}
            </div>
          </div>
        </section>

        {/* ── En acción — trabajos ──────────────────────────────────── */}
        {trabajos.length > 0 && <TrabajosSection trabajos={trabajos} />}

        {/* ── Dónde estamos ─────────────────────────────────────────── */}
        <section className="border-t hairline bg-surface px-4 lg:px-12 py-14">
          <h2 className="font-display font-black lowercase leading-[0.92] text-[clamp(1.75rem,4vw,2.5rem)] mb-8">
            dónde estamos.
          </h2>
          <div className="flex items-start gap-3 mb-6">
            <MapPin className="h-4 w-4 text-[var(--area-accent)] mt-0.5 shrink-0" />
            <p className="text-base font-semibold leading-snug">{direccion}</p>
          </div>
          <div className="w-full aspect-[16/7] overflow-hidden rounded-2xl border hairline bg-surface min-h-60">
            <iframe
              title="Mapa del estudio"
              src={iframeSrc}
              className="h-full w-full border-0 block"
              loading="lazy"
              referrerPolicy="no-referrer-when-downgrade"
            />
          </div>
        </section>

        {/* ── FAQ ───────────────────────────────────────────────────── */}
        {faq.filter((f) => f.q.trim() && f.a.trim()).length > 0 && (
          <section className="border-t hairline px-4 lg:px-12 py-12">
            <h2 className="font-display font-black lowercase text-[clamp(1.5rem,3vw,2rem)] mb-5">
              preguntas frecuentes.
            </h2>
            <div className="flex flex-col gap-2 max-w-2xl">
              {faq
                .filter((f) => f.q.trim() && f.a.trim())
                .map((item) => (
                  <details key={item.q} className="group card overflow-hidden">
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-4 py-3.5 font-semibold text-15 select-none">
                      {item.q}
                      <span className="text-muted-foreground shrink-0 transition-transform group-open:rotate-180">
                        ▾
                      </span>
                    </summary>
                    <p className="px-4 pb-4 text-sm text-muted-foreground leading-relaxed">
                      {item.a}
                    </p>
                  </details>
                ))}
            </div>
          </section>
        )}

        {/* ── CTA "hablemos." ───────────────────────────────────────── */}
        <section className="bg-ink px-4 lg:px-12 py-16">
          <div className="max-w-xl">
            <p className="font-mono text-2xs uppercase tracking-[0.3em] text-[color-mix(in_oklch,var(--area-accent)_80%,transparent)] mb-3">
              ¿Tenés dudas?
            </p>
            <h2 className="font-display font-black lowercase leading-[0.9] text-[var(--area-accent)] text-[clamp(2rem,6vw,4rem)]">
              hablemos.
            </h2>
            <p className="mt-4 text-15 leading-relaxed text-[color-mix(in_oklch,var(--area-accent)_80%,transparent)] max-w-sm">
              Te respondemos en el día. Contanos qué necesitás y armamos un presupuesto a medida.
            </p>
            <Button
              asChild
              variant="amber"
              shape="pill"
              className="mt-7 h-auto px-6 py-3 text-15 font-bold"
            >
              <a
                href={`https://wa.me/${STUDIO_PHONE}?text=${encodeURIComponent("Hola Rambla! Quería consultar por el estudio.")}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                <MessageCircle className="h-4 w-4" />
                Escribir por WhatsApp
              </a>
            </Button>
          </div>
        </section>
      </main>

      {/* Spacer mobile (detrás de la barra fija) */}
      <div className="h-20 lg:hidden" aria-hidden />
      <MobileBookBar priceLabel={priceLabel} />
    </PublicLayout>
  );
}
