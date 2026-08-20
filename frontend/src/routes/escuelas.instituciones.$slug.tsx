import { createFileRoute } from "@tanstack/react-router";

import { apiGetInstitucion } from "@/lib/api";
import { SITE_URL } from "@/lib/site";

export const Route = createFileRoute("/escuelas/instituciones/$slug")({
  loader: async ({ params, context }) => {
    const ctx = context as {
      queryClient?: {
        fetchQuery: <T>(opts: { queryKey: unknown[]; queryFn: () => Promise<T> }) => Promise<T>;
      };
    };
    const qc = ctx.queryClient;
    const fetcher = () => apiGetInstitucion(params.slug).catch(() => null);
    if (qc) {
      return qc.fetchQuery({ queryKey: ["institucion", params.slug], queryFn: fetcher });
    }
    return fetcher();
  },
  head: ({ loaderData }) => {
    const data = loaderData as Awaited<ReturnType<typeof apiGetInstitucion>> | null;
    if (!data) {
      return {
        meta: [
          { title: "Institución no encontrada — Rambla Rental" },
          { name: "robots", content: "noindex" },
        ],
      };
    }
    const { institucion, talleres } = data;
    const url = `${SITE_URL}/escuelas/instituciones/${institucion.slug}`;
    const title = `Talleres de ${institucion.nombre} en Rambla`;
    const desc = (institucion.descripcion || `Talleres de ${institucion.nombre} en Rambla.`)
      .slice(0, 155)
      .replace(/\s+/g, " ")
      .trim();

    const orgJsonLd = {
      "@context": "https://schema.org",
      "@type": "Organization",
      name: institucion.nombre,
      description: desc,
      url,
      logo: institucion.logo_url || undefined,
      sameAs:
        institucion.web || institucion.instagram
          ? [
              institucion.web,
              institucion.instagram && `https://instagram.com/${institucion.instagram}`,
            ].filter(Boolean)
          : undefined,
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
        ...(institucion.logo_url ? [{ property: "og:image", content: institucion.logo_url }] : []),
        { name: "twitter:card", content: "summary" },
        { name: "twitter:title", content: title },
        { name: "twitter:description", content: desc },
        // Sin talleres activos: no aporta indexar una página vacía.
        ...(talleres.length === 0 ? [{ name: "robots", content: "noindex" }] : []),
      ],
      links: [{ rel: "canonical", href: url }],
      scripts: [{ type: "application/ld+json", children: JSON.stringify(orgJsonLd) }],
    };
  },
});
