import { createFileRoute, Outlet } from "@tanstack/react-router";

import { SITE_URL } from "@/lib/site";

export const Route = createFileRoute("/escuelas")({
  component: () => <Outlet />,
  head: () => ({
    meta: [
      { title: "Escuelas — Talleres de Rambla" },
      { name: "theme-color", content: "#ed7bad" },
      {
        name: "description",
        content:
          "Talleres de fotografía, video y dirección de arte en Rambla Estudio, Mar del Plata.",
      },
      { property: "og:type", content: "website" },
      { property: "og:url", content: `${SITE_URL}/escuelas` },
      { property: "og:title", content: "Escuelas — Talleres de Rambla" },
      {
        property: "og:description",
        content:
          "Talleres de fotografía, video y dirección de arte en Rambla Estudio, Mar del Plata.",
      },
      { property: "og:locale", content: "es_AR" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    // El canonical de /escuelas vive en escuelas.index.tsx, NO acá — un
    // layout + su ruta hija (escuelas.$slug.tsx) mergean head(), y los
    // `links` no dedupean por `rel` como sí lo hace `meta` por name/
    // property: tenerlo acá duplicaba el canonical en la ficha de un taller.
  }),
});
