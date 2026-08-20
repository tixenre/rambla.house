import { useEffect, useRef } from "react";
import { XIcon, ChevronLeft, ChevronRight } from "lucide-react";
import { ModalBackdrop } from "@/design-system/ui/modal-backdrop";

interface LightboxPhoto {
  url: string;
  alt: string;
}

interface LightboxProps {
  open: boolean;
  onClose: () => void;
  photos: LightboxPhoto[];
  index: number;
  onIndexChange: (i: number) => void;
}

/**
 * Lightbox fullscreen — visor de fotos con nav por teclado/botones/swipe
 * táctil/gesto de trackpad y pinch-zoom nativo en mobile. Reutilizable para
 * cualquier galería del repo (talleres, equipo.$slug, MediaGallery).
 *
 * Props: `photos` (url + alt), `index` controlado, `onIndexChange`, `onClose`.
 */
export function Lightbox({ open, onClose, photos, index, onIndexChange }: LightboxProps) {
  // No wrap-around a propósito (a diferencia del carrusel chico de
  // TallerGaleria): en pantalla completa, llegar a la última foto y que
  // "siguiente" salte a la primera desorienta más de lo que ayuda.
  const goPrev = () => {
    if (index > 0) onIndexChange(index - 1);
  };
  const goNext = () => {
    if (index < photos.length - 1) onIndexChange(index + 1);
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowLeft" && index > 0) onIndexChange(index - 1);
      if (e.key === "ArrowRight" && index < photos.length - 1) onIndexChange(index + 1);
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, index, photos.length, onClose, onIndexChange]);

  // Swipe táctil + gesto de 2 dedos del trackpad — pedido del dueño, mismo
  // patrón que TallerGaleria. El listener de wheel es nativo (no el
  // `onWheel` sintético de React): wheel es passive por default en React,
  // así que `preventDefault()` adentro se ignora en silencio.
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  function handleTouchStart(e: React.TouchEvent) {
    const t = e.touches[0];
    touchStart.current = { x: t.clientX, y: t.clientY };
  }
  function handleTouchEnd(e: React.TouchEvent) {
    if (!touchStart.current) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - touchStart.current.x;
    const dy = t.clientY - touchStart.current.y;
    touchStart.current = null;
    if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) {
      if (dx > 0) goPrev();
      else goNext();
    }
  }

  const imgAreaRef = useRef<HTMLDivElement>(null);
  const lastWheelNav = useRef(0);
  useEffect(() => {
    const el = imgAreaRef.current;
    if (!open || !el || photos.length <= 1) return;
    const onWheel = (e: WheelEvent) => {
      if (Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;
      e.preventDefault();
      const now = Date.now();
      if (now - lastWheelNav.current < 450) return;
      lastWheelNav.current = now;
      if (e.deltaX > 0) {
        if (index < photos.length - 1) onIndexChange(index + 1);
      } else if (index > 0) {
        onIndexChange(index - 1);
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [open, index, photos.length, onIndexChange]);

  if (!open || photos.length === 0) return null;
  const current = photos[Math.min(index, photos.length - 1)];

  return (
    <ModalBackdrop
      onClose={onClose}
      className="z-[100] bg-black/95 flex flex-col"
      role="dialog"
      aria-modal="true"
    >
      <header className="flex items-center justify-between px-3 sm:px-4 py-3 shrink-0 text-white/90">
        <span className="font-mono text-xs tabular-nums">
          {photos.length > 1 ? `${index + 1} / ${photos.length}` : ""}
        </span>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onClose();
          }}
          className="grid h-11 w-11 place-items-center rounded-full hover:bg-white/10 transition"
          aria-label="Cerrar"
        >
          <XIcon className="h-5 w-5" />
        </button>
      </header>

      {/* Imagen — pinch-zoom nativo en mobile. */}
      <div
        ref={imgAreaRef}
        className="flex-1 flex items-center justify-center overflow-auto px-2"
        onClick={(e) => e.stopPropagation()}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
        style={{ touchAction: "pinch-zoom" }}
      >
        <img
          src={current.url}
          alt={current.alt}
          loading="eager"
          decoding="async"
          className="max-h-full max-w-full object-contain select-none"
          draggable={false}
        />
      </div>

      <div
        className="px-4 py-2 text-center text-white/80 text-xs sm:text-sm shrink-0"
        onClick={(e) => e.stopPropagation()}
      >
        {current.alt}
      </div>

      {photos.length > 1 && (
        <>
          {index > 0 && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                goPrev();
              }}
              className="hidden sm:grid absolute left-3 top-1/2 -translate-y-1/2 h-12 w-12 place-items-center rounded-full bg-white/10 text-white hover:bg-white/20 transition"
              aria-label="Foto anterior"
            >
              <ChevronLeft className="h-6 w-6" />
            </button>
          )}
          {index < photos.length - 1 && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                goNext();
              }}
              className="hidden sm:grid absolute right-3 top-1/2 -translate-y-1/2 h-12 w-12 place-items-center rounded-full bg-white/10 text-white hover:bg-white/20 transition"
              aria-label="Foto siguiente"
            >
              <ChevronRight className="h-6 w-6" />
            </button>
          )}

          <div
            className="shrink-0 flex gap-1.5 overflow-x-auto px-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-2"
            onClick={(e) => e.stopPropagation()}
          >
            {photos.map((p, i) => (
              <button
                key={`${p.url}-${i}`}
                type="button"
                onClick={() => onIndexChange(i)}
                className={`h-14 w-14 shrink-0 rounded-md overflow-hidden border-2 transition ${
                  i === index ? "border-amber" : "border-transparent opacity-60 hover:opacity-100"
                }`}
                aria-label={`Ver ${p.alt}`}
              >
                <img
                  src={p.url}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  className="h-full w-full object-cover bg-white"
                />
              </button>
            ))}
          </div>
        </>
      )}
    </ModalBackdrop>
  );
}
