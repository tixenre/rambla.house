/**
 * /admin/email-templates — redirige a /admin/comunicacion.
 *
 * La administración de mails vivió en Settings y ahora es parte del módulo de
 * Comunicación (los dos canales + los eventos en un solo lugar). Esta ruta queda
 * como redirect para no romper bookmarks ni links viejos.
 */
import { createLazyFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createLazyFileRoute("/admin/email-templates")({
  component: () => <Navigate to="/admin/comunicacion" replace />,
});
