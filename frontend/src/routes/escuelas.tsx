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
    links: [{ rel: "canonical", href: `${SITE_URL}/escuelas` }],
  }),
});
