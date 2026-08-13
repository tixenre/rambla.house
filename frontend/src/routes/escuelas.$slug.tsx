import { createFileRoute } from "@tanstack/react-router";

import { apiGetTaller } from "@/lib/api";
import { SITE_URL } from "@/lib/site";

export const Route = createFileRoute("/escuelas/$slug")({
  loader: async ({ params, context }) => {
    const ctx = context as {
      queryClient?: {
        fetchQuery: <T>(opts: { queryKey: unknown[]; queryFn: () => Promise<T> }) => Promise<T>;
      };
    };
    const qc = ctx.queryClient;
    const fetcher = () => apiGetTaller(params.slug).catch(() => null);
    if (qc) {
      return qc.fetchQuery({ queryKey: ["taller", params.slug], queryFn: fetcher });
    }
    return fetcher();
  },
  head: ({ loaderData }) => {
    const taller = loaderData as Awaited<ReturnType<typeof apiGetTaller>> | null;
    if (!taller) {
      return {
        meta: [
          { title: "Taller no encontrado — Rambla Rental" },
          { name: "robots", content: "noindex" },
        ],
      };
    }
    const url = `${SITE_URL}/escuelas/${taller.slug}`;
    const instructoresStr = taller.instructores.map((i) => i.nombre).join(" y ");
    const title = instructoresStr
      ? `${taller.nombre} con ${instructoresStr} — Rambla Rental`
      : `${taller.nombre} — Rambla Rental`;
    const desc = `${taller.descripcion}`.slice(0, 155).replace(/\s+/g, " ").trim();

    // `Course` (no `Event`): es el tipo que Google trata distinto cuando
    // alguien busca "cursos"/"talleres" — rich result propio. `CourseInstance`
    // sigue llevando fecha/lugar/instructor (es subtipo de Event, no se
    // pierde nada). Mismo criterio que el JSON-LD server-side de
    // `workshop_page` (backend/main.py) para los crawlers/agentes sin JS.
    const courseJsonLd = {
      "@context": "https://schema.org",
      "@type": "Course",
      name: taller.nombre,
      description: desc,
      url,
      image: taller.instructores[0]?.foto_url || undefined,
      provider: {
        "@type": "Organization",
        name: "Rambla",
        sameAs: SITE_URL,
      },
      hasCourseInstance: {
        "@type": "CourseInstance",
        courseMode: "Onsite",
        startDate: taller.fecha_inicio,
        endDate: taller.fecha_fin,
        location: {
          "@type": "Place",
          name: "Rambla",
          address: {
            "@type": "PostalAddress",
            streetAddress: taller.direccion || "Chaco 1392",
            addressLocality: "Mar del Plata",
            addressRegion: "Buenos Aires",
            addressCountry: "AR",
          },
        },
        ...(taller.instructores.length > 0
          ? {
              instructor: taller.instructores.map((i) => ({
                "@type": "Person",
                name: i.nombre,
              })),
            }
          : {}),
      },
      offers: {
        "@type": "Offer",
        price: taller.precio_total,
        priceCurrency: "ARS",
        availability: "https://schema.org/InStock",
        url,
        category: taller.precio_total === 0 ? "Free" : "Paid",
      },
    };

    // FAQPage — mismas FAQs que muestra <TallerFAQ> (editables desde el admin,
    // FaqSection). Condicionado a que haya al menos una completa: no emitir un
    // schema vacío mientras el taller no tenga FAQ cargada todavía.
    const faqItems = (taller.faqs ?? []).filter((f) => f.pregunta.trim() && f.respuesta.trim());
    const faqJsonLd =
      faqItems.length > 0
        ? {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            mainEntity: faqItems.map((f) => ({
              "@type": "Question",
              name: f.pregunta,
              acceptedAnswer: { "@type": "Answer", text: f.respuesta },
            })),
          }
        : null;

    return {
      meta: [
        { title },
        { name: "description", content: desc },
        { property: "og:type", content: "website" },
        { property: "og:url", content: url },
        { property: "og:title", content: title },
        { property: "og:description", content: desc },
        { property: "og:locale", content: "es_AR" },
        { name: "twitter:card", content: "summary_large_image" },
        { name: "twitter:title", content: title },
        { name: "twitter:description", content: desc },
      ],
      links: [{ rel: "canonical", href: url }],
      scripts: [
        {
          type: "application/ld+json",
          children: JSON.stringify(courseJsonLd),
        },
        ...(faqJsonLd
          ? [{ type: "application/ld+json", children: JSON.stringify(faqJsonLd) }]
          : []),
      ],
    };
  },
});
