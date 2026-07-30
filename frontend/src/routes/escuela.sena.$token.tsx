import { createFileRoute, redirect } from "@tanstack/react-router";

/**
 * /escuela/sena/$token → /escuelas/sena/$token (área renombrada; redirect que
 * **preserva el token** — este link se manda por mail cuando se libera un
 * cupo, así que un link viejo ya enviado tiene que seguir funcionando).
 */
export const Route = createFileRoute("/escuela/sena/$token")({
  beforeLoad: ({ params }) => {
    throw redirect({ to: "/escuelas/sena/$token", params: { token: params.token }, replace: true });
  },
  component: () => null,
});
