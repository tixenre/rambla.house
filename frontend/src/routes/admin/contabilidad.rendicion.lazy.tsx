/**
 * /admin/contabilidad/rendicion — redirige a /admin/contabilidad (Finanzas).
 *
 * Cuentas, Rendición y el Tablero se fundieron en una sola pantalla (decisión
 * del dueño, 2026-08-03). El bloque mensual "Lo que se generó en {mes}" murió
 * con esta página (arrancaba de cero cada mes y podía sugerir lo contrario que
 * el acumulado); el endpoint `GET /rendicion/{mes}` sigue vivo en el backend.
 * Esta ruta queda como redirect para no romper bookmarks ni links viejos.
 */
import { createLazyFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createLazyFileRoute("/admin/contabilidad/rendicion")({
  component: () => <Navigate to="/admin/contabilidad" replace />,
});
