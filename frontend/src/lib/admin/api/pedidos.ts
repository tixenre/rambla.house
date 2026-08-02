import { authedFetch, authedJson, authedPostJson } from "@/lib/authedFetch";
import type {
  PedidosListResp,
  Pedido,
  PedidoEstado,
  PedidoDatosInput,
  PagosLogResp,
  ClientesListResp,
  Cliente,
  ClienteInput,
  ClientePedidoRow,
  ClientePerfilesFiscales,
  PedidoCreateInput,
  CobroModo,
  CalendarioPedido,
  EstadisticasData,
  BusquedasData,
  LiquidacionData,
  ReconciliacionData,
  GrupoDuplicado,
  RepartoPagoLinea,
  EstudioReservaCreateInput,
  EstudioReservaUpdateInput,
} from "./types";

/** Body de `POST /alquileres/{id}/turnos-estudio` (#1308 Fase 4.4) — mismos
 *  campos que dar de alta un turno standalone, sin cliente/estado/
 *  pedido_principal_id: el turno embebido siempre hereda del pedido
 *  contenedor (ni siquiera los manda, a diferencia del mecanismo viejo que
 *  los ignoraba en el backend pero los ofrecía en el body). */
export type TurnoEmbebidoCreateInput = Omit<
  EstudioReservaCreateInput,
  "cliente_id" | "cliente_nombre" | "estado" | "pedido_principal_id"
>;

/** Body de `PATCH /alquileres/{id}/turnos-estudio/{turnoId}` — mismo shape
 *  que editar un turno standalone (incluido su descuento propio). */
export type TurnoEmbebidoUpdateInput = EstudioReservaUpdateInput;

export const pedidosMethods = {
  // pedidos / alquileres
  listPedidos: (
    params: {
      estado?: string;
      q?: string;
      con_saldo?: boolean;
      per_page?: number;
      page?: number;
    } = {},
  ) => {
    const sp = new URLSearchParams();
    if (params.estado) sp.set("estado", params.estado);
    if (params.q) sp.set("q", params.q);
    if (params.con_saldo) sp.set("con_saldo", "true");
    sp.set("per_page", String(params.per_page ?? 100));
    sp.set("page", String(params.page ?? 1));
    return authedJson<PedidosListResp>(`/api/alquileres?${sp.toString()}`);
  },
  getPedido: (id: number) => authedJson<Pedido>(`/api/alquileres/${id}`),
  enviarDocumentos: (
    id: number,
    payload: { docs: string[]; to?: string; mensaje?: string; template?: string },
  ) =>
    authedJson<{ ok: true; to: string; docs: string[]; template?: string; provider?: string }>(
      `/api/alquileres/${id}/enviar-documentos`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  // Preview del mail (plantilla + nota + adjuntos) con los datos reales del
  // pedido, sin enviar. Mismo render que el envío (el backend reusa helpers).
  previewMailPedido: (
    id: number,
    payload: { docs: string[]; mensaje?: string; template?: string },
  ) =>
    authedJson<{ subject: string; html: string; text: string }>(
      `/api/alquileres/${id}/mail-preview`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  setPedidoEstado: (id: number, estado: PedidoEstado) =>
    authedJson<Pedido>(`/api/alquileres/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ estado }),
    }),
  updatePedidoDatos: (id: number, data: Partial<PedidoDatosInput>) =>
    authedJson<Pedido>(`/api/alquileres/${id}/datos`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deletePedido: async (id: number) => {
    const res = await authedFetch(`/api/alquileres/${id}`, { method: "DELETE" });
    if (!res.ok && res.status !== 204) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail?.detail ?? `DELETE → ${res.status}`);
    }
  },
  addPago: (
    id: number,
    monto: number,
    concepto?: string,
    fecha?: string,
    destinatario?: string,
    metodo?: string,
  ) =>
    authedPostJson<Pedido>(`/api/alquileres/${id}/pagos`, {
      monto,
      concepto,
      fecha,
      destinatario,
      metodo,
    }),
  /** Igual que `addPago`, pero reparte el monto entre `id` (el pedido
   *  principal) y sus turnos del Estudio vinculados (#1308, "un pago,
   *  reparte solo") — cada parte queda como una fila real de
   *  `alquiler_pagos` con su `pedido_id` propio. Sin turnos vinculados se
   *  comporta idéntico a `addPago`. */
  addPagoCombinado: (
    id: number,
    monto: number,
    concepto?: string,
    fecha?: string,
    destinatario?: string,
    metodo?: string,
  ) =>
    authedPostJson<Pedido & { reparto: RepartoPagoLinea[] }>(
      `/api/alquileres/${id}/pagos-combinado`,
      { monto, concepto, fecha, destinatario, metodo },
    ),
  /** Ledger global de pagos — vista de logs del back-office. */
  listPagosLog: (params?: {
    destinatario?: string;
    metodo?: string;
    desde?: string;
    hasta?: string;
    incluirAnulados?: boolean;
  }) => {
    const sp = new URLSearchParams();
    if (params?.destinatario) sp.set("destinatario", params.destinatario);
    if (params?.metodo) sp.set("metodo", params.metodo);
    if (params?.desde) sp.set("desde", params.desde);
    if (params?.hasta) sp.set("hasta", params.hasta);
    if (params?.incluirAnulados) sp.set("incluir_anulados", "true");
    const qs = sp.toString();
    return authedJson<PagosLogResp>(`/api/admin/pagos${qs ? `?${qs}` : ""}`);
  },
  /** Anula un pago (soft-delete) — reemplaza el viejo DELETE real. El `motivo`
   *  es opcional desde 2026-08, igual que en los movimientos de Finanzas. */
  anularPago: (id: number, pagoId: number, motivo?: string) =>
    authedPostJson<Pedido>(`/api/alquileres/${id}/pagos/${pagoId}/anular`, {
      motivo: motivo || null,
    }),

  // clientes
  listClientes: (params: { q?: string; per_page?: number } = {}) => {
    const sp = new URLSearchParams();
    if (params.q) sp.set("q", params.q);
    sp.set("per_page", String(params.per_page ?? 200));
    return authedJson<ClientesListResp>(`/api/clientes?${sp.toString()}`);
  },
  createCliente: (data: ClienteInput) => authedPostJson<Cliente>("/api/clientes", data),

  // disponibilidad por rango (mapa equipo_id → libres)
  getDisponibilidad: (
    fechaDesde: string,
    fechaHasta: string,
    excludePedidoId?: number,
    items?: string,
  ) => {
    const sp = new URLSearchParams({ fecha_desde: fechaDesde, fecha_hasta: fechaHasta });
    if (excludePedidoId) sp.set("exclude_pedido_id", String(excludePedidoId));
    // `items` ("id:cantidad,..." — el draft del editor): el backend descuenta
    // TODO el draft con la expansión de kits del motor y devuelve valores CON
    // SIGNO (negativo = faltan unidades). Sin `items`, devuelve los libres
    // netos clásicos (≥ 0). Ver `reservas.calcular_disponibilidad[_draft]`.
    if (items) sp.set("items", items);
    return authedJson<Record<string, number>>(`/api/disponibilidad?${sp.toString()}`);
  },

  // crear pedido nuevo (wizard / página /nuevo)
  createPedido: (data: PedidoCreateInput) => authedPostJson<Pedido>("/api/alquileres", data),

  // reemplazar items completos del pedido (PUT, requiere ≥1 ítem)
  updatePedidoItems: (
    id: number,
    items: {
      equipo_id: number | null;
      cantidad: number;
      precio_jornada: number;
      nombre_libre?: string | null;
      cobro_modo?: CobroModo;
    }[],
  ) =>
    authedJson<Pedido>(`/api/alquileres/${id}/items`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    }),

  // turnos del Estudio EMBEBIDOS en este pedido (#1308 Fase 4.4) — las 3
  // devuelven el pedido CONTENEDOR completo (mismo shape que `getPedido`),
  // no "un turno": no hay una fila `alquileres` propia que devolver.
  agregarTurnoEstudio: (id: number, data: TurnoEmbebidoCreateInput) =>
    authedJson<Pedido>(`/api/alquileres/${id}/turnos-estudio`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  editarTurnoEstudio: (id: number, turnoId: number, data: TurnoEmbebidoUpdateInput) =>
    authedJson<Pedido>(`/api/alquileres/${id}/turnos-estudio/${turnoId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  eliminarTurnoEstudio: (id: number, turnoId: number) =>
    authedJson<Pedido>(`/api/alquileres/${id}/turnos-estudio/${turnoId}`, { method: "DELETE" }),

  // clientes — detalle / edición
  getCliente: (id: number) => authedJson<Cliente>(`/api/clientes/${id}`),
  getClientePedidos: (id: number) => authedJson<ClientePedidoRow[]>(`/api/clientes/${id}/pedidos`),
  // Solo lectura (#1240): perfiles fiscales personales + productoras vinculadas.
  getClientePerfilesFiscales: (id: number) =>
    authedJson<ClientePerfilesFiscales>(`/api/clientes/${id}/perfiles-fiscales`),
  updateCliente: (id: number, data: Partial<ClienteInput>) =>
    authedJson<Cliente>(`/api/clientes/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deleteCliente: async (id: number) => {
    const res = await authedFetch(`/api/clientes/${id}`, { method: "DELETE" });
    if (!res.ok && res.status !== 204) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail?.detail ?? `DELETE → ${res.status}`);
    }
  },
  generarLinkVerificacion: (clienteId: number) =>
    authedJson<{ session_id: string; url: string }>(`/api/admin/verificacion/sesion/${clienteId}`, {
      method: "POST",
    }),
  rechequearVerificacion: (clienteId: number, sessionIdOverride?: string) =>
    authedJson<{ status: string; aplicado: boolean | null; session_id: string }>(
      `/api/admin/verificacion/recheck/${clienteId}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sessionIdOverride ? { session_id: sessionIdOverride } : {}),
      },
    ),

  // clientes — fusión de duplicados (mismo CUIL verificado)
  getClientesDuplicados: () => authedJson<GrupoDuplicado[]>(`/api/clientes/duplicados`),
  // Sugerencia de fusión desde la propia ficha (#1251 Fase 2) — null si no hay duplicado.
  getClienteDuplicados: (id: number) =>
    authedJson<GrupoDuplicado | null>(`/api/clientes/${id}/duplicados`),
  mergeClientes: (source: number, target: number) =>
    authedPostJson<{ ok: boolean; merged_into: number }>(`/api/clientes/merge`, { source, target }),

  // clientes — invitación (white-glove): crea/reusa la cuenta + link de activación
  invitarCliente: (email: string, nombre?: string, telefono?: string) =>
    authedPostJson<{ ok: boolean; cliente_id: number; ya_existia: boolean; url: string }>(
      `/api/clientes/invitar`,
      { email, nombre, telefono },
    ),

  // calendario
  getCalendario: (desde: string, hasta: string) => {
    const sp = new URLSearchParams({ desde, hasta });
    return authedJson<CalendarioPedido[]>(`/api/calendario?${sp.toString()}`);
  },

  // estadísticas
  getEstadisticas: () => authedJson<EstadisticasData>("/api/estadisticas"),

  // analítica de búsquedas del catálogo público
  getBusquedas: (dias?: number) =>
    authedJson<BusquedasData>(`/api/admin/busquedas${dias && dias > 0 ? `?dias=${dias}` : ""}`),

  // Reportes (#88) — liquidación por dueño (pedidos 100% pagados, repartidos)
  getLiquidacion: (desde: string, hasta: string) =>
    authedJson<LiquidacionData>(`/api/admin/reportes/liquidacion?desde=${desde}&hasta=${hasta}`),
  liquidacionCsv: (desde: string, hasta: string) =>
    authedFetch(`/api/admin/reportes/liquidacion?desde=${desde}&hasta=${hasta}&formato=csv`).then(
      (r) => r.blob(),
    ),
  // Reporte en PDF branded + envío por mail (misma maquinaria que los documentos
  // de pedido). El preview se trae como HTML y se muestra con iframe srcDoc para
  // no depender de cookies cross-origin en un iframe.
  liquidacionPreviewHtml: (desde: string, hasta: string) =>
    authedFetch(
      `/api/admin/reportes/liquidacion/pdf?desde=${desde}&hasta=${hasta}&format=html`,
    ).then((r) => r.text()),
  getReporteDestinatarios: () =>
    authedJson<{ destinatarios: string[] }>("/api/admin/reportes/liquidacion/destinatarios"),
  enviarReporteMail: (payload: {
    desde: string;
    hasta: string;
    destinatarios: string[];
    mensaje?: string;
  }) =>
    authedPostJson<{ enviados: string[]; fallidos: string[] }>(
      "/api/admin/reportes/liquidacion/enviar-mail",
      payload,
    ),
  getReconciliacion: () => authedJson<ReconciliacionData>("/api/admin/reportes/reconciliacion"),
  // Cierre de mes (#721): congelar/reabrir la foto inmutable de un mes liquidado.
  cerrarMes: (mes: string) =>
    authedJson<LiquidacionData>(`/api/admin/reportes/cierres/${mes}`, { method: "POST" }),
  reabrirMes: (mes: string) =>
    authedJson<{ mes: string; cerrado: boolean; reabierto: boolean }>(
      `/api/admin/reportes/cierres/${mes}`,
      { method: "DELETE" },
    ),
};
