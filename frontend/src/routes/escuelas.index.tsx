import { createFileRoute } from "@tanstack/react-router";

import { SITE_URL } from "@/lib/site";

// El canonical vive ACÁ (no en escuelas.tsx, el layout): TanStack Router
// mergea el head() del layout + el de la ruta más profunda, y a diferencia
// de `meta` (que dedupea por name/property — el <title> de una ficha de
// taller ya pisa bien al del layout), los `links` NO dedupean por `rel` —
// un canonical acá y otro en escuelas.$slug.tsx quedaban los DOS en el
// <head>, algo que Google trata como conflictivo (puede ignorar ambos).
export const Route = createFileRoute("/escuelas/")({
  head: () => ({
    links: [{ rel: "canonical", href: `${SITE_URL}/escuelas` }],
  }),
});
