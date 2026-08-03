/**
 * /admin/contabilidad/cuentas — redirige a /admin/contabilidad (Finanzas).
 *
 * Cuentas, Rendición y el Tablero se fundieron en una sola pantalla (decisión
 * del dueño, 2026-08-03). Esta ruta queda como redirect para no romper
 * bookmarks ni links viejos.
 */
import { createLazyFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createLazyFileRoute("/admin/contabilidad/cuentas")({
  component: () => <Navigate to="/admin/contabilidad" replace />,
});
