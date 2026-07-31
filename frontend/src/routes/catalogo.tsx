import { createFileRoute, redirect } from "@tanstack/react-router";

/**
 * /catalogo → /rental — la ruta del catálogo se renombró a `/rental` para que cada
 * área tenga su URL (rental · estudio · escuela). Redirect para no romper links
 * viejos (bookmarks, indexado, compartidos) que ya estaban en prod.
 */
export const Route = createFileRoute("/catalogo")({
  beforeLoad: () => {
    throw redirect({ to: "/rental", replace: true });
  },
  component: () => null,
});
