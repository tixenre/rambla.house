import { useState } from "react";
import { Play } from "lucide-react";
import { cn } from "@/lib/utils";
import type { MediaVariant } from "@/lib/media/types";
import { findVariant, DISPLAY_VARIANT, SM_VARIANT } from "@/lib/media/types";
import { youtubeNocookieUrl, youtubeThumbnailUrl } from "@/lib/media/youtube";

interface YouTubeEmbedProps {
  videoId: string;
  title?: string;
  /**
   * Variantes del poster almacenado en R2 (resultado de store_youtube_poster).
   * Si están disponibles, se muestran en lugar del thumbnail de YouTube (mejor LCP
   * y sin request a YouTube antes del play → privacidad mejorada).
   * Si no se pasan, cae a `posterUrl` y despues al thumbnail público de YouTube.
   */
  posterVariants?: MediaVariant[];
  /** Poster ya resuelto como URL plana (p.ej. `taller_trabajos.poster_url`,
   *  denormalizado — no siempre hay un `MediaAsset` con variantes a mano). */
  posterUrl?: string | null;
  className?: string;
}

/**
 * Embed YouTube responsivo con privacidad y LCP mejorados.
 *
 * - Usa youtube-nocookie.com: no deposita cookies hasta que el usuario hace Play.
 * - Muestra el poster (R2 o thumbnail YouTube) antes de cargar el iframe:
 *   el iframe solo se carga al hacer click — cero iframes pesados en el paint inicial.
 * - El poster desde R2 evita el request a YouTube antes del play (máxima privacidad).
 */
export function YouTubeEmbed({
  videoId,
  title = "Video demo",
  posterVariants,
  posterUrl,
  className,
}: YouTubeEmbedProps) {
  const [active, setActive] = useState(false);

  const embedUrl = youtubeNocookieUrl(videoId);

  const posterSrc =
    posterVariants && posterVariants.length > 0
      ? (
          findVariant(posterVariants, DISPLAY_VARIANT) ??
          findVariant(posterVariants, SM_VARIANT) ??
          posterVariants[0]
        )?.url
      : (posterUrl ?? youtubeThumbnailUrl(videoId));

  return (
    <div
      className={cn(
        "relative w-full overflow-hidden rounded-md border hairline bg-black",
        className,
      )}
      style={{ aspectRatio: "16 / 9" }}
    >
      {active ? (
        <iframe
          src={`${embedUrl}?autoplay=1`}
          title={title}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
          allowFullScreen
          className="absolute inset-0 h-full w-full"
        />
      ) : (
        <button
          type="button"
          className="absolute inset-0 flex h-full w-full items-center justify-center"
          onClick={() => setActive(true)}
          aria-label={`Reproducir: ${title}`}
        >
          {posterSrc && (
            <img
              src={posterSrc}
              alt={title}
              className="absolute inset-0 h-full w-full object-cover"
              loading="lazy"
              draggable={false}
            />
          )}
          {/* Overlay de play */}
          <span className="relative z-10 flex h-16 w-16 items-center justify-center rounded-full bg-black/70 text-white backdrop-blur-sm transition-transform hover:scale-110">
            <Play className="h-8 w-8 translate-x-0.5" fill="currentColor" />
          </span>
        </button>
      )}
    </div>
  );
}
