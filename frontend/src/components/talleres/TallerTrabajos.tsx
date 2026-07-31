import { YouTubeEmbed } from "@/components/common/YouTubeEmbed";
import { extractYoutubeId } from "@/lib/media/youtube";
import type { Taller } from "@/lib/api";

/**
 * "Lo que se produjo en el taller" — prueba social real de una escuela de
 * cine (sin testimonios/reseñas, decisión del dueño). Solo si hay datos.
 */
export function TallerTrabajos({ trabajos }: { trabajos: Taller["trabajos"] }) {
  if (trabajos.length === 0) return null;

  return (
    <section>
      <p className="font-mono text-2xs tracking-[0.25em] uppercase text-rosa mb-4">
        Lo que se produjo
      </p>
      <div className="grid sm:grid-cols-2 gap-4">
        {trabajos.map((t) => {
          const videoId = extractYoutubeId(t.youtube_url);
          if (!videoId) return null;
          return (
            <div key={t.id} className="flex flex-col gap-2">
              <YouTubeEmbed
                videoId={videoId}
                title={t.titulo || "Trabajo del taller"}
                posterUrl={t.poster_url}
              />
              {t.titulo && <p className="text-sm font-medium text-ink">{t.titulo}</p>}
            </div>
          );
        })}
      </div>
    </section>
  );
}
