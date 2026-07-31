import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { formatARS } from "@/lib/format";
import type { Taller } from "@/lib/api";

/**
 * Barra sticky mobile — aparece cuando el CTA del hero sale del viewport y se
 * oculta cuando el form de inscripción (#inscripcion) entra. Mismo patrón que
 * MobileBookBar (estudio.lazy.tsx): IntersectionObserver sobre el target,
 * toggle por transform (no unmount) + safe-area.
 */
export function TallerCTABar({ taller, label }: { taller: Taller; label: string }) {
  const [hidden, setHidden] = useState(true);

  useEffect(() => {
    const target = document.getElementById("inscripcion");
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
          className="shrink-0 inline-flex min-h-11 items-center justify-center rounded-full bg-rosa text-ink px-5 py-2.5 text-sm font-bold hover:brightness-110 active:scale-[0.97] transition-all"
        >
          {label}
        </a>
      </div>
    </div>
  );
}
