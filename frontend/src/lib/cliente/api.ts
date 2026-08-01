/**
 * cliente/api.ts — API client del portal de cliente.
 *
 * Reusa los tipos `Pedido`, `PedidoEstado` del admin (es el mismo shape
 * — el cliente sólo ve sus propios pedidos). Los endpoints son
 * /api/cliente/... y validan ownership en el backend.
 */

import { authedJson } from "@/lib/authedFetch";
import type { Pedido } from "@/lib/admin/api";

export type ClientePedidoFull = Pedido & {
  documentos_disponibles?: {
    remito: boolean;
    contrato: boolean;
    albaran: boolean;
    factura: boolean;
    "packing-list": boolean;
  };
};

// ── Listas / kits personales del cliente (#1092) ──────────────────────────────
// Se guarda SOLO la composición (equipo_id + cantidad); nombre/foto/precio se
// resuelven en vivo desde el catálogo (igual que favoritos).
export type ListaItem = { equipo_id: number; cantidad: number };
export type ListaPersonal = {
  id: number;
  nombre: string;
  items: ListaItem[];
  created_at?: string | null;
  updated_at?: string | null;
};

export const clienteApi = {
  getPedido: (id: number) => authedJson<ClientePedidoFull>(`/api/cliente/pedidos/${id}`),

  // ── Favoritos ──────────────────────────────────────────────────────────────

  getFavoritos: () => authedJson<string[]>("/api/cliente/favoritos"),

  addFavorito: (id: string) =>
    authedJson<{ ok: boolean }>(`/api/cliente/favoritos/${id}`, { method: "POST" }),

  removeFavorito: (id: string) =>
    authedJson<{ ok: boolean }>(`/api/cliente/favoritos/${id}`, { method: "DELETE" }),

  /** Merge bulk de localStorage al servidor al hacer login. */
  syncFavoritos: (ids: string[]) =>
    authedJson<{ synced: number }>("/api/cliente/favoritos/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: ids.map(Number) }),
    }),

  // ── Listas / kits personales ─────────────────────────────────────────────

  getListas: () => authedJson<ListaPersonal[]>("/api/cliente/listas"),

  crearLista: (nombre: string, items: ListaItem[]) =>
    authedJson<ListaPersonal>("/api/cliente/listas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre, items }),
    }),

  renombrarLista: (id: number, nombre: string) =>
    authedJson<ListaPersonal>(`/api/cliente/listas/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre }),
    }),

  /** Reemplaza la composición completa (ej.: actualizar con el carrito actual). */
  reemplazarItemsLista: (id: number, items: ListaItem[]) =>
    authedJson<ListaPersonal>(`/api/cliente/listas/${id}/items`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    }),

  quitarItemLista: (id: number, equipoId: number) =>
    authedJson<ListaPersonal>(`/api/cliente/listas/${id}/items/${equipoId}`, {
      method: "DELETE",
    }),

  borrarLista: (id: number) =>
    authedJson<{ ok: boolean }>(`/api/cliente/listas/${id}`, { method: "DELETE" }),
};
