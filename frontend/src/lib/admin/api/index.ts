/**
 * Admin API client — barrel. Re-exports all types + assembles `adminApi`.
 *
 * El path @/lib/admin/api resuelve a este index, por lo que todos los
 * imports existentes (adminApi, tipos, constantes) siguen funcionando sin
 * cambios en los call sites.
 */

export * from "./types";
export { estudioAdminApi, trabajosAdminApi } from "./estudio";
export { descuentosJornadaApi } from "./estudio";
export { talleresAdminApi } from "./talleres";
export { dataioAdminApi } from "./dataio";
export { facturacionApi } from "./facturacion";
export type {
  EmisorArca,
  EstadoFacturacion,
  FacturaEstado,
  Factura,
  FacturasListResp,
} from "./facturacion";

// URL absoluta para abrir PDFs en nueva pestaña
const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");
export const pedidoPdfUrl = (
  id: number,
  kind: "remito" | "detalle-seguro" | "contrato" | "checklist-retiro" = "remito",
) => `${API_BASE}/api/alquileres/${id}/${kind}`;

import type { EstadoPedido } from "@/lib/pedido-estados";

export const ESTADO_LABEL: Record<EstadoPedido, string> = {
  borrador: "Borrador",
  // `solicitado` (ex-`presupuesto`, renombrado 2026-07-14): "Solicitud" — el
  // cliente lo solicitó, aún no confirmado. El documento PDF sigue siendo "Presupuesto".
  solicitado: "Solicitud",
  confirmado: "Confirmado",
  retirado: "Retirado",
  entregado: "Entregado",
  devuelto: "Devuelto",
  finalizado: "Finalizado",
  cancelado: "Cancelado",
};

import { equiposMethods } from "./equipos";
import { specsMethods } from "./specs";
import { pedidosMethods } from "./pedidos";
import { contabilidadMethods } from "./contabilidad";
import { brandingMethods } from "./branding";
import { carritosMethods } from "./carritos";
import { erroresMethods } from "./errores";
import { mediaMethods } from "./media";
export type { MediaStats, GcResult, RederiveResult } from "./media";

export const adminApi = {
  ...equiposMethods,
  ...specsMethods,
  ...pedidosMethods,
  ...contabilidadMethods,
  ...brandingMethods,
  ...carritosMethods,
  ...erroresMethods,
  ...mediaMethods,
};
