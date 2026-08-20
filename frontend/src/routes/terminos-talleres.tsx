import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";

import { PublicLayout } from "@/components/rental/shell/PublicLayout";
import { LAST_UPDATED, TALLER_TERMS_SECTIONS } from "@/data/legal";
import { SITE_URL } from "@/lib/site";

export const Route = createFileRoute("/terminos-talleres")({
  head: () => ({
    meta: [
      { title: "Términos y condiciones de talleres — Rambla" },
      {
        name: "description",
        content:
          "Términos y condiciones para inscribirse a un taller de Rambla en Mar del Plata. Inscripción, pago, cancelación, uso de equipos, derecho de imagen.",
      },
      { property: "og:title", content: "Términos y condiciones de talleres — Rambla" },
      { property: "og:type", content: "website" },
      { property: "og:url", content: `${SITE_URL}/terminos-talleres` },
    ],
    links: [{ rel: "canonical", href: `${SITE_URL}/terminos-talleres` }],
  }),
  component: TerminosTalleresPage,
});

function TerminosTalleresPage() {
  return (
    <PublicLayout>
      <div className="max-w-3xl mx-auto w-full px-4 md:px-6 py-8 md:py-12">
        <Link
          to="/escuelas"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-ink transition mb-6"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Volver a talleres
        </Link>

        <div className="t-eyebrow">Legal</div>
        <h1 className="font-display text-3xl md:text-4xl text-ink mt-1">
          Términos y condiciones de talleres
        </h1>
        <p className="text-sm text-muted-foreground mt-2">Última actualización: {LAST_UPDATED}</p>

        <article className="mt-8 space-y-6 text-15 leading-relaxed text-foreground/90">
          {TALLER_TERMS_SECTIONS.map((s) => (
            <section key={s.id} id={s.id}>
              <h2 className="font-display text-xl text-ink mb-2">{s.title}</h2>
              <p className="whitespace-pre-line">{s.content}</p>
            </section>
          ))}
        </article>

        <div className="mt-12 pt-6 border-t hairline text-xs text-muted-foreground">
          Si tenés dudas sobre algún punto, escribinos antes de inscribirte — los datos de contacto
          están en la última sección.
        </div>
      </div>
    </PublicLayout>
  );
}
