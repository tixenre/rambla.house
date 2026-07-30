import { createFileRoute, redirect } from "@tanstack/react-router";

/**
 * /escuela/$slug → /escuelas/$slug (área renombrada; redirect que **preserva el
 * slug** para no romper links viejos de prod a un taller puntual).
 */
export const Route = createFileRoute("/escuela/$slug")({
  beforeLoad: ({ params }) => {
    throw redirect({ to: "/escuelas/$slug", params: { slug: params.slug }, replace: true });
  },
  component: () => null,
});
