import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import { SITE_URL } from "@/lib/site";
import { useHeroPhotos } from "@/lib/studio/hero-photos";
import { Logo } from "@/components/rental/shell/Logo";
import { AreaMenu } from "@/components/rental/shell/AreaMenu";
import { AREAS } from "@/data/areas";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Rambla — Equipos, Estudio y Talleres en Mar del Plata" },
      {
        name: "description",
        content:
          "Alquilá equipos audiovisuales, reservá el estudio de foto y video, y sumate a un taller. Todo en Rambla, Mar del Plata.",
      },
      { property: "og:type", content: "website" },
      { property: "og:url", content: `${SITE_URL}/` },
      { property: "og:title", content: "Rambla — Equipos, Estudio y Talleres" },
      {
        property: "og:description",
        content:
          "Alquilá equipos audiovisuales, reservá el estudio y sumate a un taller. Mar del Plata.",
      },
      { property: "og:locale", content: "es_AR" },
    ],
    links: [{ rel: "canonical", href: `${SITE_URL}/` }],
  }),
  component: LandingHub,
});

function LandingHub() {
  const photos = useHeroPhotos();
  const studioPic = photos[0];

  return (
    // Mobile: alto fijo = 1 viewport (hero + 3 áreas repartidas en tercios, sin
    // scroll). Desktop (md+): layout natural de siempre (hero arriba + 3 columnas).
    <div className="flex flex-col h-[100dvh] overflow-hidden md:h-auto md:min-h-screen md:overflow-visible">
      <main className="flex-1 flex flex-col min-h-0">
        {/* ── Hero ─────────────────────────────────────────────────────────── */}
        <section className="relative shrink-0 flex flex-col items-center justify-center text-center px-4 py-6 sm:py-24 bg-background">
          {/* Menú de navegación entre áreas — la landing no lleva topbar, pero el
              menú da acceso a las áreas, al portal y a los links secundarios.
              `tone="onLight"` porque el hero es hueso, no un color de área. */}
          <div className="absolute top-3 right-3 sm:top-5 sm:right-5 z-20">
            <AreaMenu tone="onLight" />
          </div>
          <p className="font-mono text-2xs tracking-[0.35em] uppercase text-muted-foreground mb-3 sm:mb-6">
            Chaco 1392 — Mar del Plata
          </p>
          <Logo linkTo={null} color="text-ink" className="!h-[clamp(2.5rem,11vw,8rem)]" />
          <p className="mt-3 sm:mt-5 text-sm sm:text-lg text-muted-foreground max-w-md leading-relaxed">
            Equipos audiovisuales, estudio de foto y video, y talleres — todo en un lugar.
          </p>
        </section>

        {/* ── Tres propuestas ──────────────────────────────────────────────── */}
        {/* Mobile: flex column con áreas flex-1 (tercios iguales del alto restante).
            Desktop: grid de 3 columnas. En mobile cada banda muestra solo eyebrow +
            título + flecha (la banda entera es tappable); la descripción y el botón
            aparecen desde md. */}
        <div className="flex flex-col md:grid md:grid-cols-3 flex-1 min-h-0 md:min-h-[55vh]">
          {/* Rental */}
          <Link
            to="/rental"
            className="group relative flex flex-1 flex-col justify-center md:justify-start px-6 py-5 sm:p-10 bg-amber text-ink md:flex-none transition-[filter] hover:brightness-105 active:brightness-95"
          >
            <p className="font-mono text-2xs tracking-[0.28em] uppercase text-ink/55 mb-2 sm:mb-5">
              {AREAS.rental.eyebrow}
            </p>
            <h2
              className="font-display font-black lowercase leading-[0.9] tracking-[-0.02em] text-ink mb-3 sm:mb-4"
              style={{ fontSize: "clamp(1.75rem, 3.5vw, 2.5rem)" }}
            >
              rental.
              <br />
              <span className="opacity-60">
                alquilá lo
                <br />
                que necesitás.
              </span>
            </h2>
            <p className="hidden md:block text-ink/65 text-sm mb-7 leading-relaxed max-w-xs md:min-h-[2lh]">
              Cámaras, lentes, iluminación, audio y soportes. Retiro en el estudio.
            </p>
            <span className="hidden md:inline-flex items-center gap-2 w-fit rounded-full bg-ink text-background px-5 py-2.5 text-sm font-bold tracking-[-0.01em] transition-[gap] duration-150 group-hover:gap-3.5">
              Ver catálogo <ArrowRight className="h-3.5 w-3.5" />
            </span>
            <ArrowRight className="h-5 w-5 md:hidden" strokeWidth={2.5} />
          </Link>

          {/* Estudio */}
          <Link
            to="/estudio"
            className="group relative flex flex-1 flex-col justify-center md:justify-start px-6 py-5 sm:p-10 md:flex-none overflow-hidden transition-[filter] hover:brightness-105 active:brightness-95"
            style={{ backgroundColor: "var(--color-estudio)" }}
          >
            {studioPic && (
              <img
                src={studioPic.url}
                srcSet={
                  studioPic.urlSm ? `${studioPic.urlSm} 800w, ${studioPic.url} 1600w` : undefined
                }
                sizes="(max-width: 768px) 100vw, 33vw"
                alt="Rambla Estudio"
                className="absolute inset-0 w-full h-full object-cover opacity-[0.12] transition-transform duration-700 group-hover:scale-[1.04]"
                fetchPriority="high"
              />
            )}
            <div className="relative">
              <p className="font-mono text-2xs tracking-[0.28em] uppercase mb-2 sm:mb-5 text-ink">
                {AREAS.estudio.eyebrow}
              </p>
              <h2
                className="font-display font-black lowercase leading-[0.9] tracking-[-0.02em] text-ink mb-3 sm:mb-4"
                style={{ fontSize: "clamp(1.75rem, 3.5vw, 2.5rem)" }}
              >
                estudio.
                <br />
                <span className="opacity-70">
                  un lugar donde
                  <br />
                  pasan cosas.
                </span>
              </h2>
              <p className="hidden md:block text-ink text-sm mb-7 leading-relaxed max-w-xs md:min-h-[2lh]">
                Set con fondo infinito, ciclorama y luz natural. Por hora.
              </p>
              <span className="hidden md:inline-flex items-center gap-2 w-fit rounded-full bg-ink text-background px-5 py-2.5 text-sm font-bold tracking-[-0.01em] transition-[gap] duration-150 group-hover:gap-3.5">
                Ver el estudio <ArrowRight className="h-3.5 w-3.5" />
              </span>
              <ArrowRight className="h-5 w-5 md:hidden" strokeWidth={2.5} />
            </div>
          </Link>

          {/* Escuelas */}
          <Link
            to="/escuelas"
            className="group relative flex flex-1 flex-col justify-center md:justify-start px-6 py-5 sm:p-10 text-ink md:flex-none transition-[filter] hover:brightness-105 active:brightness-95"
            style={{ backgroundColor: "var(--color-rosa)" }}
          >
            <p className="font-mono text-2xs tracking-[0.28em] uppercase text-ink/55 mb-2 sm:mb-5">
              {AREAS.escuela.eyebrow}
            </p>
            <h2
              className="font-display font-black lowercase leading-[0.9] tracking-[-0.02em] text-ink mb-3 sm:mb-4"
              style={{ fontSize: "clamp(1.75rem, 3.5vw, 2.5rem)" }}
            >
              escuelas.
              <br />
              <span className="opacity-60">
                talleres y
                <br />
                workshops.
              </span>
            </h2>
            <p className="hidden md:block text-ink/65 text-sm mb-7 leading-relaxed max-w-xs md:min-h-[2lh]">
              Clases prácticas de dirección de arte, foto y video. Cupos limitados.
            </p>
            <span className="hidden md:inline-flex items-center gap-2 w-fit rounded-full bg-ink text-background px-5 py-2.5 text-sm font-bold tracking-[-0.01em] transition-[gap] duration-150 group-hover:gap-3.5">
              Ver talleres <ArrowRight className="h-3.5 w-3.5" />
            </span>
            <ArrowRight className="h-5 w-5 md:hidden" strokeWidth={2.5} />
          </Link>
        </div>
      </main>
    </div>
  );
}
