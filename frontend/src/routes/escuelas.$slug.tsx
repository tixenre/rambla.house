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

    const eventJsonLd = {
      "@context": "https://schema.org",
      "@type": "Event",
      name: instructoresStr ? `${taller.nombre} con ${instructoresStr}` : taller.nombre,
      description: desc,
      startDate: taller.fecha_inicio,
      endDate: taller.fecha_fin,
      location: {
        "@type": "Place",
        name: "Rambla Estudio",
        address: {
          "@type": "PostalAddress",
          streetAddress: "Chaco 1392",
          addressLocality: "Mar del Plata",
          addressRegion: "Buenos Aires",
          addressCountry: "AR",
        },
      },
      url,
      organizer: {
        "@type": "Organization",
        name: "Rambla Rental",
        url: SITE_URL,
      },
    };

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
          children: JSON.stringify(eventJsonLd),
        },
      ],
    };
  },
});
