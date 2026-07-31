import { createFileRoute, Outlet } from "@tanstack/react-router";

/**
 * /workshops → /escuelas. Layout solo para anidar los redirects de `/workshops` y
 * `/workshops/$slug` (ver `workshops.index.tsx` y `workshops.$slug.tsx`). El área
 * se renombró primero a `/escuela` (2026-xx-xx) y después a `/escuelas` (plural,
 * 2026-07-30) — este redirect apunta directo al canónico actual. El nombre viejo
 * `/talleres` se dejó de soportar.
 */
export const Route = createFileRoute("/workshops")({
  component: () => <Outlet />,
});
