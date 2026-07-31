/**
 * usePedidoDraft — estado local del pedido (admin) + autoguardado debounced.
 *
 * Patrón: lee el pedido desde el server (react-query) como "fuente de verdad"
 * inicial, mantiene un draft local mutable, y cada cambio dispara un auto-save
 * debounced vía PATCH /datos + PUT /items (separados).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { adminApi, type Pedido, type PedidoEstado } from "@/lib/admin/api";

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
  return (
    p.items
      // Un ítem con `turno_estudio_id` (#1308 Fase 4, "turno como ítem") es del
      // grupo de un turno del Estudio EMBEBIDO — se administra desde
      // `TurnosEstudioSection`/`ReservaEstudioSection`, no desde acá. SIN este
      // filtro, el centinela/sueltos/pintura del turno aparecían TAMBIÉN como
      // filas de "Alquiler de equipos" (doble listado) y, peor, el próximo
      // autosave de equipos los reenviaba a `PUT .../items` SIN su
      // `turno_estudio_id` (`DraftItem` no lo lleva) — el backend los insertaba
      // de nuevo como ítems NUEVOS sin marca de turno, duplicando el centinela
      // y volando el total (confirmado en vivo: $114.000 en vez de $69.000 con
      // un solo turno de por medio). El total en vivo (`useCotizacion`) SÍ
      // necesita verlos — los suma aparte, directo de `pedido.items`, en
      // `pedidos.$id.lazy.tsx` (no desde acá).
      .filter((it) => it.turno_estudio_id == null)
      .map((it) => ({
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
      }))
  );
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

export type UsePedidoDraftOptions = {
  /** Conservar la hora en `fecha_desde`/`fecha_hasta` (datetime, no date-only).
   * Para el editor que usa el selector de fechas+horas; el resto deja date-only
   * por compat con `<input type=date>`. Default false. */
  keepDateTime?: boolean;
};

export function usePedidoDraft(pedido: Pedido | undefined, opts: UsePedidoDraftOptions = {}) {
  const { keepDateTime = false } = opts;
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
  // Dos efectos separados (datos / items), cada uno dispatchea a su mutation.

  // Payload pendiente de enviar. Si se navega antes de que corra el debounce,
  // el efecto de unmount lo flushea — sino el cambio se pierde en silencio.
  const pendingDatosRef = useRef<DraftDatos | null>(null);
  const pendingItemsRef = useRef<DraftItem[] | null>(null);

  useEffect(() => {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- autosave con debounce: dispara por datos/pedido; incluir datosMut reiniciaría el timer en cada render
  }, [datos, pedido?.id]);

  useEffect(() => {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- autosave con debounce: dispara por items/pedido; incluir itemsMut reiniciaría el timer en cada render
  }, [items, pedido?.id]);

  // Flush en unmount: si quedó un cambio sin enviar (se navegó antes del
  // debounce), lo disparamos best-effort sin debounce. El efecto se monta una
  // vez; el cleanup corre sólo al desmontar.
  useEffect(() => {
    return () => {
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

  const isPending = datosMut.isPending || itemsMut.isPending;
  const isError = datosMut.isError || itemsMut.isError;

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

  return {
    datos,
    setDatos,
    items,
    setItems,
    saveStatus,
    estadoMut,
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
