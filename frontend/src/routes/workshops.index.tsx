import { createFileRoute, redirect } from "@tanstack/react-router";

/** /workshops → /escuelas (área renombrada; redirect para links viejos de prod
 *  — apunta directo al canónico actual, sin pasar por el alias /escuela). */
export const Route = createFileRoute("/workshops/")({
  beforeLoad: () => {
    throw redirect({ to: "/escuelas", replace: true });
  },
  component: () => null,
});
