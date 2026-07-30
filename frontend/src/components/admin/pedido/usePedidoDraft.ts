/**
 * usePedidoDraft — estado local del pedido + autoguardado debounced.
 *
 * Patrón:
 *  - Lee el pedido desde el server (react-query) y hace de "fuente de verdad" inicial.
 *  - Mantiene un draft local mutable; cada cambio dispara un auto-save debounced
 *    (en `submitMode='autosave'`) o queda pendiente hasta que el caller invoque
 *    `submitProposal()` (en `submitMode='propose'`).
 *  - Persiste por separado (admin) o vía endpoint unificado (cliente):
 *     · admin    → PATCH /datos + PUT /items (separados)
 *     · cliente  → POST /api/cliente/pedidos/{id}/modificacion (unificado)
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { adminApi, type Pedido, type PedidoEstado } from "@/lib/admin/api";
import { clienteApi } from "@/lib/cliente/api";

export type DraftItem = {
  /** Key estable para render + drag (#806). equipo_id no sirve: las líneas
   * personalizadas (#805) no lo tienen y puede haber varias. */
  uid: string;
  /** null = línea personalizada (#805): no es del catálogo, no reserva stock. */
  equipo_id: number | null;
  cantidad: number;
  precio_jornada: number;
  nombre: string;
  marca: string | null;
  nombre_publico?: string | null;
  foto_url?: string | null;
  /** Línea personalizada (#805): nombre libre + modo de cobro. */
  nombre_libre?: string | null;
  cobro_modo?: "jornada" | "fijo";
};

let _uidSeq = 0;
/** uid para una línea nueva agregada en el cliente (antes de persistir). */
export function nuevoUidLinea(prefix = "tmp"): string {
  _uidSeq += 1;
  return `${prefix}-${Date.now()}-${_uidSeq}`;
}

/** Subtotal de una línea del draft — espeja `services.precios.bruto_linea`
 * del backend: una línea personalizada `cobro_modo='fijo'` (ej. flete, #805)
 * NO se multiplica por jornadas. Única fuente — antes `PedidoPageCards.tsx` y
 * `PedidoPageHelpers.tsx` tenían cada uno su propia fórmula, y ya habían
 * divergido (Cards ignoraba `cobro_modo`). Auditoría cruzada de plata, 2026-07-02. */
export function subtotalDraftItem(it: DraftItem, jornadas: number): number {
  const fijo = (it.cobro_modo ?? "jornada") === "fijo";
  return it.precio_jornada * it.cantidad * (fijo ? 1 : Math.max(1, jornadas));
}

export type DraftDatos = {
  cliente_id: number | null;
  cliente_nombre: string;
  cliente_email: string;
  cliente_telefono: string;
  /** Fecha de retiro. Por defecto `YYYY-MM-DD` (compat `<input type=date>`);
   * con la opción `keepDateTime` conserva la hora (`YYYY-MM-DDTHH:MM:SS`) para
   * el editor que usa el selector de fechas+horas. */
  fecha_desde: string;
  fecha_hasta: string;
  notas: string;
  descuento_pct: number;
  /** Fase C-2 (#1219): tipo del override manual — "pct" (default) o "monto"
   *  ($ fijo), mismo campo de la UI con un selector al lado. */
  descuento_manual_tipo: "pct" | "monto";
  descuento_manual_monto: number;
  /** A nombre de quién se factura este pedido (#1251) — mutuamente excluyentes,
   *  null/null = perfil default de la cuenta. El renter sigue siendo `cliente_id`. */
  perfil_fiscal_id: number | null;
  productora_id: number | null;
};

export type PedidoMode = "admin" | "cliente";
export type SubmitMode = "autosave" | "propose";

const DEBOUNCE_MS = 700;

function pedidoToDatos(p: Pedido, keepDateTime = false): DraftDatos {
  return {
    cliente_id: p.cliente_id,
    cliente_nombre: p.cliente_nombre ?? "",
    cliente_email: p.cliente_email ?? "",
    cliente_telefono: p.cliente_telefono ?? "",
    // keepDateTime: conservar la hora para que el editor con selector de
    // fechas+horas no la pierda en el round-trip del autosave. Default: slice a
    // YYYY-MM-DD (los editores con `<input type=date>` esperan date-only).
    fecha_desde: keepDateTime ? (p.fecha_desde ?? "") : (p.fecha_desde ?? "").slice(0, 10),
    fecha_hasta: keepDateTime ? (p.fecha_hasta ?? "") : (p.fecha_hasta ?? "").slice(0, 10),
    notas: p.notas ?? "",
    descuento_pct: p.descuento_pct ?? 0,
    descuento_manual_tipo: p.descuento_manual_tipo ?? "pct",
    descuento_manual_monto: p.descuento_manual_monto ?? 0,
    perfil_fiscal_id: p.perfil_fiscal_id ?? null,
    productora_id: p.productora_id ?? null,
  };
}

function pedidoToItems(p: Pedido): DraftItem[] {
  return p.items.map((it) => ({
    // uid estable desde el server: equipo → `e<equipo_id>` (consolidado, único);
    // línea personalizada → `c<id de la fila>`.
    uid: it.equipo_id != null ? `e${it.equipo_id}` : `c${it.id}`,
    equipo_id: it.equipo_id,
    cantidad: it.cantidad,
    precio_jornada: it.precio_jornada,
    nombre: it.nombre,
    marca: it.marca,
    nombre_publico: it.nombre_publico ?? null,
    foto_url: it.foto_url ?? null,
    nombre_libre: it.nombre_libre ?? null,
    cobro_modo: it.cobro_modo ?? "jornada",
  }));
}

function shallowDatosEq(a: DraftDatos, b: DraftDatos): boolean {
  return (
    a.cliente_id === b.cliente_id &&
    a.cliente_nombre === b.cliente_nombre &&
    a.cliente_email === b.cliente_email &&
    a.cliente_telefono === b.cliente_telefono &&
    a.fecha_desde === b.fecha_desde &&
    a.fecha_hasta === b.fecha_hasta &&
    a.notas === b.notas &&
    a.descuento_pct === b.descuento_pct &&
    a.descuento_manual_tipo === b.descuento_manual_tipo &&
    a.descuento_manual_monto === b.descuento_manual_monto &&
    a.perfil_fiscal_id === b.perfil_fiscal_id &&
    a.productora_id === b.productora_id
  );
}

function shallowItemsEq(a: DraftItem[], b: DraftItem[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (
      a[i].equipo_id !== b[i].equipo_id ||
      a[i].cantidad !== b[i].cantidad ||
      a[i].precio_jornada !== b[i].precio_jornada ||
      // Líneas personalizadas (#805): nombre y modo también cuentan como cambio.
      (a[i].nombre_libre ?? "") !== (b[i].nombre_libre ?? "") ||
      (a[i].cobro_modo ?? "jornada") !== (b[i].cobro_modo ?? "jornada")
    )
      return false;
  }
  return true;
}

export type SaveStatus = "idle" | "dirty" | "saving" | "saved" | "error";

/** Devuelve un string con la razón por la que el draft no se puede enviar,
 * o null si está OK. Usado para gatear el botón de "Enviar solicitud". */
function validateForSubmit(d: DraftDatos, its: DraftItem[]): string | null {
  if (its.length === 0) return "Agregá al menos un equipo";
  for (const it of its) {
    if (!Number.isFinite(it.cantidad) || it.cantidad <= 0) {
      return `La cantidad de "${it.nombre}" debe ser mayor a 0`;
    }
  }
  if (d.fecha_desde && d.fecha_hasta) {
    if (d.fecha_desde >= d.fecha_hasta) {
      return "La fecha de devolución debe ser posterior a la de retiro";
    }
  }
  return null;
}

export type UsePedidoDraftOptions = {
  /** 'admin' (default) usa endpoints /api/alquileres/...; 'cliente' usa /api/cliente/... */
  mode?: PedidoMode;
  /** 'autosave' (default) guarda con debounce; 'propose' acumula hasta submitProposal(). */
  submitMode?: SubmitMode;
  /** Mensaje opcional que viaja en submit del cliente (sólo modo cliente). */
  mensaje?: string;
  /** Callback cuando una propuesta se envía con éxito. Sólo modo cliente+propose. */
  onProposalSent?: (tipo: "directo" | "aprobacion") => void;
  /** Conservar la hora en `fecha_desde`/`fecha_hasta` (datetime, no date-only).
   * Para el editor que usa el selector de fechas+horas; el resto deja date-only
   * por compat con `<input type=date>`. Default false. */
  keepDateTime?: boolean;
};

export function usePedidoDraft(pedido: Pedido | undefined, opts: UsePedidoDraftOptions = {}) {
  const {
    mode = "admin",
    submitMode = "autosave",
    mensaje,
    onProposalSent,
    keepDateTime = false,
  } = opts;
  const qc = useQueryClient();

  // Snapshot del server (lo que está persistido)
  const serverRef = useRef<{ datos: DraftDatos; items: DraftItem[] } | null>(null);

  // Estado local editable
  const [datos, setDatos] = useState<DraftDatos | null>(null);
  const [items, setItems] = useState<DraftItem[] | null>(null);

  // ── Mutations (admin) ──────────────────────────────────────────────────
  const datosMut = useMutation({
    mutationFn: (d: DraftDatos) =>
      adminApi.updatePedidoDatos(pedido!.id, {
        cliente_id: d.cliente_id,
        cliente_nombre: d.cliente_nombre || null,
        cliente_email: d.cliente_email || null,
        cliente_telefono: d.cliente_telefono || null,
        fecha_desde: d.fecha_desde || null,
        fecha_hasta: d.fecha_hasta || null,
        notas: d.notas || null,
        descuento_pct: d.descuento_pct || 0,
        descuento_manual_tipo: d.descuento_manual_tipo,
        descuento_manual_monto: d.descuento_manual_monto || 0,
        perfil_fiscal_id: d.perfil_fiscal_id,
        productora_id: d.productora_id,
      }),
    onSuccess: (p) => {
      qc.setQueryData(["admin", "pedido", p.id], p);
      qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
      if (serverRef.current) serverRef.current.datos = pedidoToDatos(p, keepDateTime);
    },
    onError: (e: Error) => toast.error(`Datos: ${e.message}`),
  });

  const itemsMut = useMutation({
    mutationFn: (its: DraftItem[]) =>
      adminApi.updatePedidoItems(
        pedido!.id,
        its.map((it) => ({
          equipo_id: it.equipo_id,
          cantidad: it.cantidad,
          precio_jornada: it.precio_jornada,
          nombre_libre: it.equipo_id == null ? (it.nombre_libre ?? "") : null,
          cobro_modo: it.cobro_modo ?? "jornada",
        })),
      ),
    onSuccess: (p) => {
      qc.setQueryData(["admin", "pedido", p.id], p);
      qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
      if (serverRef.current) {
        serverRef.current.items = pedidoToItems(p);
        serverRef.current.datos = pedidoToDatos(p, keepDateTime);
      }
    },
    onError: (e: Error) => toast.error(`Equipos: ${e.message}`),
  });

  // ── Mutation (cliente) — envía datos+items combinados ──────────────────
  const clienteMut = useMutation({
    mutationFn: (payload: { d: DraftDatos; its: DraftItem[] }) =>
      clienteApi.enviarModificacion(pedido!.id, {
        fecha_desde: payload.d.fecha_desde || null,
        fecha_hasta: payload.d.fecha_hasta || null,
        // El portal del cliente no maneja líneas personalizadas (#805) → solo
        // ítems de catálogo (con equipo_id).
        items: payload.its
          .filter((it) => it.equipo_id != null)
          .map((it) => ({
            equipo_id: it.equipo_id as number,
            cantidad: it.cantidad,
          })),
        mensaje: mensaje || null,
      }),
    onSuccess: (resp) => {
      qc.invalidateQueries({ queryKey: ["cliente", "pedido", pedido!.id] });
      qc.invalidateQueries({ queryKey: ["cliente", "pedidos"] });
      if (resp.tipo === "directo" && "pedido" in resp && serverRef.current) {
        serverRef.current.datos = pedidoToDatos(resp.pedido, keepDateTime);
        serverRef.current.items = pedidoToItems(resp.pedido);
      }
      onProposalSent?.(resp.tipo);
    },
    onError: (e: Error) => {
      // Importante: NO invalidamos la query. El refetch + useEffect reset
      // pisaría los cambios locales del cliente sin que se dé cuenta. En
      // su lugar dejamos el draft "dirty" y mostramos el error claro.
      // El SaveIndicator muestra "Error al guardar" hasta que vuelva a
      // editar y disparar otro autosave.
      const m = e.message || "";
      const friendly = m.includes("Sin stock")
        ? `${m} — ajustá las cantidades o las fechas y volvemos a guardar.`
        : m.includes("ventana")
          ? m
          : `No pudimos guardar: ${m}`;
      toast.error(friendly);
    },
  });

  const estadoMut = useMutation({
    mutationFn: (estado: PedidoEstado) => adminApi.setPedidoEstado(pedido!.id, estado),
    onSuccess: (p) => {
      toast.success("Estado actualizado");
      qc.setQueryData(["admin", "pedido", p.id], p);
      qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
      // El descuento (cliente + jornadas) pasa de seguir al cliente EN VIVO a
      // leer el snapshot congelado apenas el pedido deja 'solicitado'
      // (`pedido_congelado` en `cotizacion.py`) — sin invalidar acá, el
      // Desglose podía seguir mostrando el descuento viejo justo después de
      // confirmar, hasta que otra edición no relacionada limpiara la caché.
      qc.invalidateQueries({ queryKey: ["cotizar"] });
      // Cascada a turnos del Estudio vinculados (#1308, "avanzan juntos"): ya
      // corrió en el backend — acá solo refrescamos cada turno tocado (su
      // propia query, si está montada en TurnosEstudioSection) y avisamos si
      // alguno quedó sin poder avanzar (el pedido principal SÍ avanzó igual).
      (p.turnos_estudio_vinculados ?? []).forEach((t) =>
        qc.invalidateQueries({ queryKey: ["admin", "pedido", t.id] }),
      );
      if (p.turnos_vinculados_sin_avanzar?.length) {
        toast.warning("Algún turno vinculado no pudo avanzar", {
          description: p.turnos_vinculados_sin_avanzar
            .map((w) => `#${w.numero_pedido ?? w.turno_id}: ${w.error}`)
            .join(" · "),
          duration: 8000,
        });
      }
    },
    onError: (e: Error) => toast.error(e.message),
  });

  // ── Sincronizar cuando llega o cambia el pedido del server ───────────────
  // Guard anti-race: si la mutación correspondiente está en vuelo, NO pisamos
  // el estado local con datos del server que pueden ser "viejos".
  //
  // Caso típico: el usuario agrega un ítem (itemsMut en vuelo) y a la vez
  // tiene un cambio de datos pendiente (datosMut en vuelo). Si datosMut
  // completa primero, su onSuccess llama setQueryData con el pedido del
  // server que todavía tiene los ítems VIEJOS. Sin el guard, el sync effect
  // llamaría setItems(old items) y el nuevo ítem desaparecería del UI —
  // aunque SÍ se guarda después cuando itemsMut completa. (#bug "se agrega
  // pero no se ve guardado hasta reentrar").
  useEffect(() => {
    if (!pedido) return;
    const d = pedidoToDatos(pedido, keepDateTime);
    const it = pedidoToItems(pedido);
    serverRef.current = { datos: d, items: it };
    // Solo sincronizamos el estado local si la mutación correspondiente no
    // está en vuelo. Cuando la mutación complete, su isPending pasa a false,
    // este effect se re-ejecuta con el pedido fresco de onSuccess, y entonces
    // sí actualizamos.
    // `isError` en el guard, además de `isPending`: si el guardado FALLÓ, el
    // servidor sigue teniendo el valor viejo y `pedido` no cambió (onSuccess
    // nunca corrió). Sin este chequeo, al pasar la mutación de pending→error
    // este mismo effect se re-ejecutaba y pisaba la edición del usuario con
    // el valor viejo del server: el campo volvía solo mientras el cartel
    // decía "Error al guardar" — el texto y la pantalla contradiciéndose, y
    // el trabajo perdido. Manteniendo lo local, el próximo tecleo reintenta
    // (mutate() resetea isError) y el estado "error" queda visible hasta que
    // efectivamente guarde.
    if (!datosMut.isPending && !datosMut.isError) {
      setDatos((cur) => (cur && shallowDatosEq(cur, d) ? cur : d));
    }
    if (!itemsMut.isPending && !itemsMut.isError) {
      setItems((cur) => (cur && shallowItemsEq(cur, it) ? cur : it));
    }
  }, [
    pedido,
    datosMut.isPending,
    datosMut.isError,
    itemsMut.isPending,
    itemsMut.isError,
    keepDateTime,
  ]);

  // ── Autosave debounced ─────────────────────────────────────────────────
  // Admin: dos efectos separados (datos / items) que dispatchean a sus mutations.
  // Cliente + autosave: un solo efecto que dispatchea a clienteMut con todo.
  const autosaveAdmin = mode === "admin" && submitMode === "autosave";
  const autosaveCliente = mode === "cliente" && submitMode === "autosave";

  // Payload pendiente de enviar. Si se navega antes de que corra el debounce,
  // el efecto de unmount lo flushea — sino el cambio se pierde en silencio.
  // `pendingFlushRef` es el del cliente (datos+ítems en una sola mutation);
  // el admin tiene dos mutations separadas, así que lleva un ref por cada una.
  const pendingFlushRef = useRef<{ d: DraftDatos; its: DraftItem[] } | null>(null);
  const pendingDatosRef = useRef<DraftDatos | null>(null);
  const pendingItemsRef = useRef<DraftItem[] | null>(null);

  useEffect(() => {
    if (!autosaveAdmin) return;
    if (!pedido || !datos || !serverRef.current) return;
    if (shallowDatosEq(datos, serverRef.current.datos)) {
      pendingDatosRef.current = null;
      return;
    }
    // Se anota el payload para el flush de unmount (ver abajo): si el admin
    // navega dentro de la ventana del debounce, el cambio se manda igual.
    pendingDatosRef.current = datos;
    const t = setTimeout(() => {
      datosMut.mutate(datos);
      pendingDatosRef.current = null;
    }, DEBOUNCE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- autosave con debounce: dispara por datos/pedido/flag; incluir datosMut reiniciaría el timer en cada render
  }, [datos, pedido?.id, autosaveAdmin]);

  useEffect(() => {
    if (!autosaveAdmin) return;
    if (!pedido || !items || !serverRef.current) return;
    if (shallowItemsEq(items, serverRef.current.items)) return;
    // OJO: acá NO va un `if (items.length === 0) return`. Lo había, y hacía que
    // sacar el ÚLTIMO equipo no se guardara nunca: la pantalla quedaba en "Sin
    // guardar" para siempre y el cambio se perdía al recargar (lo reportó el
    // dueño). Quedarse sin equipos es un estado legítimo —un borrador que se
    // está armando, o un pedido cuyo contenido son horas de Estudio— y quién
    // puede quedar vacío lo decide el backend (`_puede_quedar_sin_items`), no
    // un guard mudo del front: si no puede, contesta 400 y se ve el error.
    // Línea personalizada recién agregada, todavía sin nombre (#805): no
    // autoguardar todavía — dispararía el 422 "necesita un nombre" mientras
    // el usuario recién hace foco en el input, antes de tipear una letra.
    if (items.some((it) => it.equipo_id == null && !(it.nombre_libre ?? "").trim())) return;
    pendingItemsRef.current = items;
    const t = setTimeout(() => {
      itemsMut.mutate(items);
      pendingItemsRef.current = null;
    }, DEBOUNCE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- autosave con debounce: dispara por items/pedido/flag; incluir itemsMut reiniciaría el timer en cada render
  }, [items, pedido?.id, autosaveAdmin]);

  useEffect(() => {
    if (!autosaveCliente) return;
    if (!pedido || !datos || !items || !serverRef.current) return;
    const dirty =
      !shallowDatosEq(datos, serverRef.current.datos) ||
      !shallowItemsEq(items, serverRef.current.items);
    if (!dirty) {
      pendingFlushRef.current = null;
      return;
    }
    if (items.length === 0) return;
    pendingFlushRef.current = { d: datos, its: items };
    const t = setTimeout(() => {
      clienteMut.mutate({ d: datos, its: items });
      pendingFlushRef.current = null;
    }, DEBOUNCE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- autosave con debounce: dispara por datos/items/pedido/flag; incluir clienteMut reiniciaría el timer en cada render
  }, [datos, items, pedido?.id, autosaveCliente]);

  // Flush en unmount: si quedó un cambio sin enviar (se navegó antes del
  // debounce), lo disparamos best-effort sin debounce. El efecto se monta una
  // vez; el cleanup corre sólo al desmontar.
  //
  // Antes solo cubría al CLIENTE: `pendingFlushRef` se escribía únicamente en
  // el autosave del cliente, así que en admin el ref era siempre null y los
  // últimos 700ms de cualquier edición se perdían al navegar (volver a la
  // lista justo después de tipear). Ahora las tres mutations tienen su flush.
  useEffect(() => {
    return () => {
      if (pendingFlushRef.current) {
        clienteMut.mutate(pendingFlushRef.current);
        pendingFlushRef.current = null;
      }
      if (pendingDatosRef.current) {
        datosMut.mutate(pendingDatosRef.current);
        pendingDatosRef.current = null;
      }
      if (pendingItemsRef.current) {
        itemsMut.mutate(pendingItemsRef.current);
        pendingItemsRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- flush best-effort solo al desmontar (efecto mount-once); deps vacías a propósito
  }, []);

  // ── Submit explícito (propose) ─────────────────────────────────────────
  async function submitProposal() {
    if (!pedido || !datos || !items) return;
    const reason = validateForSubmit(datos, items);
    if (reason) {
      toast.error(reason);
      return;
    }
    await clienteMut.mutateAsync({ d: datos, its: items });
  }

  const isPending = datosMut.isPending || itemsMut.isPending || clienteMut.isPending;
  const isError = datosMut.isError || itemsMut.isError || clienteMut.isError;

  const saveStatus: SaveStatus = useMemo(() => {
    if (isPending) return "saving";
    if (isError) return "error";
    if (!datos || !items || !serverRef.current) return "idle";
    const dirty =
      !shallowDatosEq(datos, serverRef.current.datos) ||
      !shallowItemsEq(items, serverRef.current.items);
    if (dirty) return "dirty";
    return "saved";
  }, [datos, items, isPending, isError]);

  const submitBlockedReason = datos && items ? validateForSubmit(datos, items) : "Cargando…";

  return {
    datos,
    setDatos,
    items,
    setItems,
    saveStatus,
    estadoMut,
    submitProposal,
    isSubmitting: clienteMut.isPending,
    /** null si se puede enviar; string con la razón si no. */
    submitBlockedReason,
    /** Expuesta para deshabilitar un control puntual (ej. el descuento del
     *  alquiler) mientras SU autosave está en vuelo — evita el doble-submit
     *  donde una edición nueva dispara un segundo PATCH antes de que el
     *  primero responda, y el que responde último pisa al que responde
     *  primero con datos más viejos. */
    datosMut,
  };
}

// Re-export del cálculo canónico (modelo 24h, espejo del backend). Antes este
// helper sumaba +1 (días inclusivos), lo que mostraba 1 jornada de más
// respecto a lo que factura el backend.
export { jornadasFromISO as jornadasEntre } from "@/lib/rental-dates";
