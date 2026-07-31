import { createFileRoute, Outlet } from "@tanstack/react-router";

/**
 * /escuela → /escuelas. Layout solo para anidar los redirects de `/escuela`,
 * `/escuela/$slug` y `/escuela/sena/$token` (ver `escuela.index.tsx`,
 * `escuela.$slug.tsx`, `escuela.sena.$token.tsx`). El área se renombró a
 * `/escuelas` (plural, 2026-07-30) — mismo patrón que la redirección
 * `/workshops` → `/escuela` que ya existía (ver `workshops.tsx`).
 */
export const Route = createFileRoute("/escuela")({
  component: () => <Outlet />,
});
