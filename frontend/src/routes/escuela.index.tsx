import { createFileRoute, redirect } from "@tanstack/react-router";

/** /escuela → /escuelas (área renombrada; redirect para links viejos de prod). */
export const Route = createFileRoute("/escuela/")({
  beforeLoad: () => {
    throw redirect({ to: "/escuelas", replace: true });
  },
  component: () => null,
});
