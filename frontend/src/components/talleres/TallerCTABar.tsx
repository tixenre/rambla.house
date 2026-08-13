import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { formatARS } from "@/lib/format";
import { trackClickInscribirseTaller } from "@/lib/analytics";
import type { Taller } from "@/lib/api";

/**
 * Barra sticky mobile — visible solo en el hueco entre que el CTA del hero
 * (#hero-cta) sale del viewport y que el form de inscripción (#inscripcion)
 * todavía no entra; oculta mientras cualquiera de los dos esté visible. Dos
 * IntersectionObserver (uno por target, no uno compartido con `entries[0]` —
 * el orden/batching de un observer con 2+ targets no está garantizado) +
 * toggle por transform (no unmount) + safe-area. Mismo patrón base que
 * MobileBookBar (estudio.lazy.tsx).
 */
export function TallerCTABar({ taller, label }: { taller: Taller; label: string }) {
  const [heroCtaVisible, setHeroCtaVisible] = useState(true);
  const [inscripcionVisible, setInscripcionVisible] = useState(false);

  useEffect(() => {
    const heroCta = document.getElementById("hero-cta");
    const inscripcion = document.getElementById("inscripcion");
    if (!heroCta || !inscripcion) return;

    const heroObs = new IntersectionObserver(([entry]) => setHeroCtaVisible(entry.isIntersecting), {
      threshold: 0,
    });
    const inscripcionObs = new IntersectionObserver(
      ([entry]) => setInscripcionVisible(entry.isIntersecting),
      { threshold: 0 },
    );
    heroObs.observe(heroCta);
    inscripcionObs.observe(inscripcion);
    return () => {
      heroObs.disconnect();
      inscripcionObs.disconnect();
    };
  }, []);

  const hidden = heroCtaVisible || inscripcionVisible;

  return (
    <div
      className={cn(
        "fixed inset-x-0 bottom-0 z-40 lg:hidden transition-transform duration-200",
        hidden ? "translate-y-full" : "translate-y-0",
      )}
      aria-hidden={hidden}
    >
      <div className="flex items-center gap-3 border-t border-border/60 bg-background/95 backdrop-blur-xl px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
        <div className="min-w-0 flex-1">
          <div className="text-2xs font-mono uppercase tracking-wider text-muted-foreground">
            {taller.nombre}
          </div>
          <div className="truncate text-sm font-bold text-ink tabular-nums">
            {formatARS(taller.precio_total)}
          </div>
        </div>
        <a
          href="#inscripcion"
          onClick={() => trackClickInscribirseTaller(taller.id)}
          className="shrink-0 inline-flex min-h-11 items-center justify-center rounded-full bg-rosa text-ink px-5 py-2.5 text-sm font-bold hover:brightness-110 active:scale-[0.97] transition-all"
        >
          {label}
        </a>
      </div>
    </div>
  );
}
