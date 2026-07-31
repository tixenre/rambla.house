/**
 * orders.ts — API de pedidos del cliente.
 *
 * Habla con el backend FastAPI (Railway) usando el JWT de Supabase Auth.
 * El backend valida el JWT, hace upsert del cliente y crea/lee `alquileres`.
 * Antes esto vivía duplicado en una tabla `orders` de Supabase; ya no.
 */

import { authedJson, authedPostJson, authedFetch, AuthedHttpError } from "./authedFetch";
import { toLocalISO } from "./rental-dates";
import { trackSolicitarPedido } from "./analytics";
import { useCart } from "./cart-store";

/** El backend rechazó el pedido por falta de verificación de identidad (403).
 *  Las bocas la cazan para mostrar el panel de verificación en vez de un toast genérico. */
export class OrderVerificationError extends Error {}

export type OrderStatus =
  | "borrador"
  | "solicitado"
  | "confirmado"
  | "entregado"
  | "devuelto"
  | "cancelado";

export type OrderItemInput = {
  id: string;
  name: string;
  brand: string;
  category: string;
  qty: number;
  pricePerDay: number;
  /** ID numérico del equipo en el backend FastAPI. Requerido para crear pedido. */
  backendId?: number;
};

export type CreateOrderInput = {
  status: OrderStatus;
  startDate?: Date;
  endDate?: Date;
  startTime: string;
  endTime: string;
  days: number;
  resolvedItems: OrderItemInput[];
  notes?: string;
  /** Fallback de firma sin passkey ("Confirmo y acepto" por sesión) resuelto en
   *  el paso de resumen del checkout (`CheckoutResumen`) — ver
   *  `services/checkout/validar.py::_check_firma`. Inerte mientras
   *  `FIRMA_CHECKOUT_OBLIGATORIA` esté apagado server-side. */
  sessionConfirmed?: boolean;
  /** #1240: a nombre de quién se factura este pedido — mutuamente
   *  excluyentes, ambos `undefined` = perfil default de la cuenta. */
  perfilFiscalId?: number;
  productoraId?: number;
};

export type Order = {
  id: string;
  numero_pedido: string;
  status: OrderStatus;
  start_date: string | null;
  end_date: string | null;
  start_time: string;
  end_time: string;
  days: number;
  total: number;
  notes: string | null;
};

export type OrderItem = {
  id: string;
  name: string;
  brand: string;
  qty: number;
  price_per_day: number;
};

/* ── Mapeo backend → frontend ─────────────────────────────────────────────── */

const ESTADO_MAP: Record<string, OrderStatus> = {
  borrador: "borrador",
  solicitado: "solicitado",
  confirmado: "confirmado",
  entregado: "entregado",
  devuelto: "devuelto",
  cancelado: "cancelado",
  finalizado: "devuelto",
};

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function timePart(d: Date | null, fallback: string) {
  if (!d || isNaN(d.getTime())) return fallback;
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function adaptOrder(b: Record<string, unknown>): Order {
  const fd = b.fecha_desde ? new Date(String(b.fecha_desde)) : null;
  const fh = b.fecha_hasta ? new Date(String(b.fecha_hasta)) : null;
  const days = fd && fh ? Math.max(1, Math.ceil((fh.getTime() - fd.getTime()) / 86_400_000)) : 1;
  return {
    id: String(b.id),
    numero_pedido: String(b.numero_pedido ?? b.id),
    status: ESTADO_MAP[String(b.estado)] ?? "solicitado",
    start_date: fd ? fd.toISOString() : null,
    end_date: fh ? fh.toISOString() : null,
    start_time: timePart(fd, "09:00"),
    end_time: timePart(fh, "18:00"),
    days,
    total: Number(b.monto_total ?? 0),
    notes: (b.notas as string | null) ?? null,
  };
}

function adaptItems(items: Array<Record<string, unknown>>): OrderItem[] {
  return items.map((it, i) => ({
    id: String(it.equipo_id ?? i),
    name: String(it.nombre ?? ""),
    brand: String(it.marca ?? ""),
    qty: Number(it.cantidad ?? 0),
    price_per_day: Number(it.precio_jornada ?? 0),
  }));
}

/* ── API pública ──────────────────────────────────────────────────────────── */

export async function createOrder(input: CreateOrderInput): Promise<Order> {
  const items = (input.resolvedItems ?? []).filter((it) => it.qty > 0);
  if (items.length === 0) throw new Error("El pedido está vacío.");

  const missing = items.find((it) => !it.backendId);
  if (missing) {
    throw new Error(
      `No se puede solicitar "${missing.name}" porque el catálogo está en modo offline.`,
    );
  }

  // Las fechas son obligatorias y deben estar bien ordenadas. El backend lo
  // valida también (fuente de verdad), pero acá damos un error claro antes de
  // hacer el request.
  if (!input.startDate || !input.endDate) {
    throw new Error("Elegí la fecha de retiro y de devolución.");
  }
  if (isNaN(input.startDate.getTime()) || isNaN(input.endDate.getTime())) {
    throw new Error("Las fechas seleccionadas no son válidas.");
  }

  const body = {
    fecha_desde: input.startDate ? toLocalISO(input.startDate, input.startTime) : null,
    fecha_hasta: input.endDate ? toLocalISO(input.endDate, input.endTime) : null,
    notas: input.notes ?? null,
    items: items.map((it) => ({
      equipo_id: it.backendId!,
      cantidad: it.qty,
      precio_jornada: Math.round(it.pricePerDay),
    })),
    // session_id del carrito (#280 Fase 1): cierra el funnel de conversión
    session_id: useCart.getState().sessionId,
    session_confirmed: input.sessionConfirmed ?? false,
    perfil_fiscal_id: input.perfilFiscalId ?? null,
    productora_id: input.productoraId ?? null,
  };

  let created: Record<string, unknown>;
  try {
    created = await authedPostJson<Record<string, unknown>>("/api/cliente/pedidos", body);
  } catch (e) {
    if (e instanceof AuthedHttpError && e.status === 403) {
      throw new OrderVerificationError(e.message);
    }
    throw e;
  }

  // Analytics: pedido solicitado (no-op si GA no está activo). El valor es el
  // total del alquiler = Σ(precio_jornada × cantidad) × jornadas.
  trackSolicitarPedido({
    value: items.reduce((acc, it) => acc + Math.round(it.pricePerDay) * it.qty, 0) * input.days,
    days: input.days,
    items: items.map((it) => ({
      item_id: String(it.backendId),
      item_name: it.name,
      item_brand: it.brand,
      item_category: it.category,
      quantity: it.qty,
      price: Math.round(it.pricePerDay),
    })),
  });

  return adaptOrder(created);
}

export async function listOrders(): Promise<Order[]> {
  const arr = await authedJson<Array<Record<string, unknown>>>("/api/cliente/pedidos");
  return arr.map(adaptOrder);
}

export type DocumentosDisponibles = {
  remito: boolean;
  contrato: boolean;
  albaran: boolean;
  "packing-list": boolean;
};

export type DocumentoTipo = keyof DocumentosDisponibles;

export const DOCUMENTO_LABEL: Record<DocumentoTipo, string> = {
  remito: "Remito",
  contrato: "Contrato",
  albaran: "Detalle de seguro",
  "packing-list": "Checklist de retiro",
};

export const DOCUMENTO_HINT: Record<DocumentoTipo, string> = {
  remito: "Disponible apenas se solicita el pedido",
  contrato: "Disponible apenas se solicita el pedido",
  albaran: "Disponible apenas se solicita el pedido",
  "packing-list": "Disponible apenas se solicita el pedido",
};

export async function getOrder(id: string) {
  const b = await authedJson<Record<string, unknown>>(`/api/cliente/pedidos/${id}`);
  const docs = (b.documentos_disponibles ?? {}) as Partial<DocumentosDisponibles>;
  return {
    order: adaptOrder(b),
    items: adaptItems((b.items as Array<Record<string, unknown>>) ?? []),
    documentosDisponibles: {
      remito: !!docs.remito,
      contrato: !!docs.contrato,
      albaran: !!docs.albaran,
      "packing-list": !!docs["packing-list"],
    } as DocumentosDisponibles,
  };
}

/** Descarga un PDF del pedido como Blob (con Authorization header). */
export async function fetchOrderDocument(orderId: string, tipo: DocumentoTipo): Promise<Blob> {
  const res = await authedFetch(`/api/cliente/pedidos/${orderId}/${tipo}.pdf`, {
    headers: { Accept: "application/pdf" },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? `No se pudo descargar el ${tipo}.`);
  }
  return res.blob();
}

/** Abre el PDF en una nueva pestaña. Devuelve la URL para limpiar luego. */
export async function openOrderDocument(orderId: string, tipo: DocumentoTipo): Promise<void> {
  const blob = await fetchOrderDocument(orderId, tipo);
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener,noreferrer");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Fuerza la descarga del PDF con nombre amigable. */
export async function downloadOrderDocument(orderId: string, tipo: DocumentoTipo): Promise<void> {
  const blob = await fetchOrderDocument(orderId, tipo);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `pedido-${orderId}-${tipo}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export async function cancelOrder(id: string): Promise<void> {
  const res = await authedFetch(`/api/cliente/pedidos/${id}/cancelar`, {
    method: "PATCH",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail ?? `PATCH cancelar → ${res.status}`);
  }
}
