/**
 * ClientePortalTypes.ts — Tipos y utilidades compartidas del portal del cliente.
 *
 * Extraído de cliente.portal.tsx para evitar exportar no-componentes desde .tsx
 * (regla react-refresh/only-export-components).
 */

import { formatARS } from "@/lib/format";
import type { EstadoPedido } from "@/lib/pedido-estados";

// ── Tipos ────────────────────────────────────────────────────────────────────

export type Perfil = {
  id: number;
  nombre: string;
  apellido: string;
  email: string;
  telefono: string;
  direccion: string;
  cuit?: string | null;
  perfil_impuestos?: string | null;
  razon_social?: string | null;
  domicilio_fiscal?: string | null;
  email_facturacion?: string | null;
  descuento?: number;
  direccion_maps_url?: string | null;
  created_at?: string | null;
  // Identidad / RENAPER
  dni?: string | null;
  cuil?: string | null;
  dni_validado_at?: string | null;
  dni_verificacion_estado?: string | null;
  dni_verificacion_motivo?: string | null;
  nombre_renaper?: string | null;
  apellido_renaper?: string | null;
  fecha_nacimiento_renaper?: string | null;
  direccion_renaper?: string | null;
  apodo?: string | null;
  /** Consentimiento explícito para recibir avisos por WhatsApp (lo exige Meta). */
  whatsapp_opt_in?: boolean | null;
};

export type Item = {
  id?: number;
  /** ID del equipo del catálogo (clave del carrito). `null` en líneas
   *  personalizadas (#805), que no se pueden volver a agregar al carrito. */
  equipo_id?: number | null;
  nombre: string;
  marca: string;
  modelo?: string | null;
  cantidad: number;
  precio_jornada: number;
  subtotal: number;
  foto_url?: string;
  nombre_publico?: string | null;
  nombre_publico_largo?: string | null;
  /** Presente si esta línea pertenece a un turno del Estudio EMBEBIDO (#1308
   *  rediseño "turno como ítem") — el centinela/sueltos/pintura de un turno
   *  NO son equipos alquilables: no se listan como "Equipos" ni se pueden
   *  repetir al carrito, aunque `equipo_id` tenga un valor real. `null`/
   *  ausente = ítem normal, el 100% de los pedidos sin turno embebido. */
  turno_estudio_id?: number | null;
};
export type Pago = { id?: number; monto: number; concepto?: string | null; fecha: string };
export type Pedido = {
  id: number;
  numero_pedido: string;
  estado: string;
  fecha_desde?: string;
  fecha_hasta?: string;
  monto_total?: number;
  monto_pagado?: number;
  descuento_pct?: number | null;
  notas?: string | null;
  created_at?: string | null;
  items: Item[];
  pagos?: Pago[];
  documentos_disponibles: {
    remito: boolean;
    contrato: boolean;
    albaran: boolean;
    factura: boolean;
    "packing-list": boolean;
  };
  bruto?: number;
  descuento_monto?: number;
  monto_neto?: number;
  iva_pct?: number;
  iva_monto?: number;
  total_con_iva?: number;
  con_iva?: boolean;
  cantidad_jornadas?: number;
};

export type PortalTab = "pedidos" | "listas" | "notificaciones" | "perfil";
export type DocTipo = "remito" | "contrato" | "albaran" | "factura" | "packing-list";
export type Filtro = "todos" | "activos" | "historial";

// ── Constantes compartidas con el componente principal ───────────────────────

// Los literales se validan contra EstadoPedido (fuente única, lib/pedido-estados.ts)
// acá — un typo o un estado que no exista no compila. El Set queda Set<string>
// porque Pedido.estado es string (viene tal cual del backend), no EstadoPedido.
function estadosSet(...estados: EstadoPedido[]): Set<string> {
  return new Set(estados);
}

// "solicitado"/"entregado" son estados del portal (ver TRANSICIONES en
// pedido-estados.ts) — el backend hoy no los emite (ver ESTADOS_VALIDOS en
// backend/routes/alquileres/core.py), pero si algún día lo hace, un pedido en
// esos estados ya cae en Activos, no en el limbo.
export const ACTIVE_STATES = estadosSet(
  "borrador",
  "solicitado",
  "solicitado",
  "confirmado",
  "retirado",
  "entregado",
);
export const HIST_STATES = estadosSet("devuelto", "finalizado", "cancelado");

// "packing-list" (Checklist de retiro) queda afuera a propósito, igual que
// "remito": ambos están disponibles desde el mismo momento que se crea el
// pedido — no son una novedad que "aparece después" (a diferencia de
// contrato/albaran/factura, que antes llegaban en estados posteriores). Sin
// esto, el popup "documentos nuevos" se dispara para TODOS los pedidos
// históricos apenas se habilita un doc nuevo (nunca se marcó "visto" antes).
export const DOC_NOTIFICABLE: DocTipo[] = ["contrato", "albaran", "factura"];

// Copy de los documentos — fuente única (portal + checkout, que muestra la
// sección "Documentos de tu pedido" antes de confirmar). "remito" no tenía
// descripción propia porque el portal ya lo identifica por el label solo.
export const DOC_LABEL: Record<DocTipo, string> = {
  remito: "Remito",
  contrato: "Contrato",
  albaran: "Detalle de seguro",
  factura: "Factura",
  "packing-list": "Checklist de retiro",
};
export const DOC_DESCRIPTION: Partial<Record<DocTipo, string>> = {
  remito: "El comprobante de tu pedido: ítems, fechas y precio.",
  contrato: "Es el documento de alquiler firmado entre vos y nosotros.",
  albaran: "Te sirve para tener constancia ante tu aseguradora.",
  factura: "Tu factura electrónica, ya autorizada por ARCA.",
  "packing-list": "El detalle de equipos para controlar al retirar y al devolver.",
};

export const TAB_OPTIONS: { value: Filtro; label: string }[] = [
  { value: "todos", label: "Todos" },
  { value: "activos", label: "Activos" },
  { value: "historial", label: "Historial" },
];

// ── Utilidades compartidas ────────────────────────────────────────────────────

// Reemplazar fmt() con formatARS() del sistema
export function fmt(n?: number) {
  if (n == null) return "—";
  return formatARS(n);
}
export function fmtDate(s?: string) {
  if (!s) return "—";
  const d = new Date(s.slice(0, 10) + "T12:00:00");
  const dias = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
  const meses = [
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
  ];
  return `${dias[d.getDay()]} ${d.getDate()} ${meses[d.getMonth()]}`;
}
export function fmtTime(s?: string) {
  if (!s || s.length < 16) return null;
  return s.slice(11, 16);
}

export const docSeenKey = (pedidoId: number, tipo: DocTipo) =>
  `rambla.doc_seen.${pedidoId}.${tipo}`;
export function wasDocSeen(pedidoId: number, tipo: DocTipo): boolean {
  try {
    return localStorage.getItem(docSeenKey(pedidoId, tipo)) === "1";
  } catch {
    return false;
  }
}
export function markDocSeen(pedidoId: number, tipo: DocTipo): void {
  try {
    localStorage.setItem(docSeenKey(pedidoId, tipo), "1");
  } catch {
    /* ignore */
  }
}

// El "visto" de docs vive en localStorage → un device nuevo (o storage limpio)
// no tiene nada marcado y vería TODOS los docs históricos como "nuevos". Este flag
// marca que ya se hizo la inicialización: en la primera carga con pedidos se marca
// lo existente como visto (silencioso, sin popup) y solo los docs que aparezcan
// DESPUÉS disparan la notificación.
const DOC_SEEN_INIT_KEY = "rambla.doc_seen.initialized";
export function docSeenInitialized(): boolean {
  try {
    return localStorage.getItem(DOC_SEEN_INIT_KEY) === "1";
  } catch {
    return false;
  }
}
export function markDocSeenInitialized(): void {
  try {
    localStorage.setItem(DOC_SEEN_INIT_KEY, "1");
  } catch {
    /* ignore */
  }
}
