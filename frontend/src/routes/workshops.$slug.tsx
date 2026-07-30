import { createFileRoute, redirect } from "@tanstack/react-router";

/**
 * /workshops/$slug → /escuelas/$slug (área renombrada; redirect que **preserva
 * el slug** para no romper links viejos de prod a un taller puntual — apunta
 * directo al canónico actual, sin pasar por el alias /escuela/$slug).
 */
export const Route = createFileRoute("/workshops/$slug")({
  beforeLoad: ({ params }) => {
    throw redirect({ to: "/escuelas/$slug", params: { slug: params.slug }, replace: true });
  },
  component: () => null,
});
