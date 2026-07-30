import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";

import { apiGetTalleres, type Taller } from "@/lib/api";

function proximoTaller(talleres: Taller[]): Taller | null {
  const hoy = new Date();
  hoy.setHours(0, 0, 0, 0);
  const activos = talleres
    .filter((t) => new Date(t.fecha_fin + "T00:00:00") >= hoy)
    .sort((a, b) => new Date(a.fecha_inicio).getTime() - new Date(b.fecha_inicio).getTime());
  return activos[0] ?? null;
}

/** Data-driven — antes mostraba a Jime hardcodeada ("11 y 18 de julio", quedaba
 * stale apenas pasaba esa fecha). Ahora trae el próximo taller activo (en
 * curso o por venir) de la API; sin ninguno, la card de la derecha se omite
 * (el copy de la izquierda es marketing genérico, no depende de un taller). */
export function TalleresBand() {
  const { data: talleres = [] } = useQuery({
    queryKey: ["talleres"],
    queryFn: apiGetTalleres,
    staleTime: 1000 * 60 * 5,
  });
  const taller = proximoTaller(talleres);

  const optsLargo: Intl.DateTimeFormatOptions = { day: "numeric", month: "long" };
  const fechaInicioStr = taller
    ? new Date(taller.fecha_inicio + "T12:00:00").toLocaleDateString("es-AR", optsLargo)
    : "";
  const fechaFinStr = taller
    ? new Date(taller.fecha_fin + "T12:00:00").toLocaleDateString("es-AR", optsLargo)
    : "";

  return (
    <section className="bg-background border-y border-border/60">
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6 py-12 sm:py-16 flex flex-col sm:flex-row items-center justify-between gap-8">
        <div className="flex flex-col gap-4 max-w-xl">
          <p className="font-mono text-xs tracking-[0.25em] uppercase text-muted-foreground">
            Escuelas
          </p>
          <h2
            className="font-display font-black lowercase leading-[0.9] tracking-[-0.01em] text-ink"
            style={{ fontSize: "clamp(1.75rem, 4vw, 2.75rem)" }}
          >
            talleres y workshops.
          </h2>
          <p className="text-15 leading-[1.5] text-muted-foreground">
            Clases prácticas de dirección de arte, fotografía y video en Rambla Estudio. Cupos
            limitados.
          </p>
          <Link
            to="/escuelas"
            className="inline-flex items-center gap-[9px] w-fit rounded-full border border-ink text-ink px-6 py-3 text-15 font-bold tracking-[-0.01em] transition-[gap,background] duration-[180ms] hover:gap-[13px] hover:bg-ink hover:text-background active:scale-[0.97]"
          >
            Ver talleres <ArrowRight size={15} strokeWidth={2.4} />
          </Link>
        </div>
        {taller && (
          <Link
            to="/escuelas/$slug"
            params={{ slug: taller.slug }}
            className="hidden sm:flex flex-col items-end gap-2 text-right shrink-0"
          >
            <div className="rounded-2xl border border-border/60 bg-muted/30 px-6 py-4 text-sm text-muted-foreground hover:border-rosa/40 transition-colors">
              <p className="font-medium text-ink text-base">{taller.nombre}</p>
              {taller.instructores.length > 0 && (
                <p className="mt-0.5">x {taller.instructores.map((i) => i.nombre).join(" y ")}</p>
              )}
              <p className="mt-2 text-xs">
                {fechaInicioStr} y {fechaFinStr} · {taller.direccion}
              </p>
            </div>
          </Link>
        )}
      </div>
    </section>
  );
}
