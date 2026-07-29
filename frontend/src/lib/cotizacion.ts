/**
 * cotizacion.ts — Cliente del endpoint canónico de cotización (`POST /api/cotizar`).
 *
 * El total del carrito lo calcula EL BACKEND (fuente única,
 * `services/precios.calcular_total`). El front ya NO reimplementa la fórmula:
 * manda los ítems (equipo_id + cantidad) y, si hay, las fechas, y muestra el
 * desglose que devuelve el backend tal cual. Reemplaza al viejo `cart-total.ts`.
 * Ver #617 / #508.
 *
 * Reglas (las decide el backend, no el front):
 *  - Sin fechas → estimado de UNA jornada, sin descuento ni IVA.
 *  - Cliente logueado → su perfil/descuento. Admin → el del `clienteId` que
 *    pase (arma pedidos para terceros). Anónimo / sin cliente → consumidor final.
 */

import { useEffect, useRef, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { authedPostJson } from "@/lib/authedFetch";

/** Debounce del recálculo en vivo. Sin esto, `useCotizacion` le pega a
 * `/api/cotizar` en CADA tecla (tipear un %, arrastrar una fecha, cambiar una
 * cantidad) → editando activamente se supera el rate-limit del endpoint
 * (30/min) → 429 → el desglose se queda mostrando el último valor bueno en
 * silencio (bug "el descuento no se aplica"). Coalescemos los cambios rápidos
 * en UN solo request. El primer cálculo NO se debouncea (estado inicial
 * inmediato). */
const COTIZAR_DEBOUNCE_MS = 300;

export type DescuentoOrigen = "manual" | "cliente" | "jornadas" | "ninguno";

/** Detalle por equipo que el front MUESTRA (no calcula): el backend lo resuelve
 *  en `/api/cotizar` con el precio efectivo (combo-aware). Ver FASE 3 / #1110. */
export type CotizacionLinea = {
  /** Backend id del equipo (null = línea personalizada del builder admin, #805). */
  equipoId: number | null;
  cantidad: number;
  /** Precio efectivo por jornada del ítem (combo → derivado de componentes). */
  precioJornada: number;
  /** precioJornada × cantidad (el "$X/día" del ítem). */
  subtotalPorJornada: number;
  /** Bruto del período: × jornadas (antes de descuento). */
  bruto: number;
  /** Neto del período: con el descuento ganado repartido por línea. */
  neto: number;
};

/** Desglose normalizado para el UI (mismas keys que usaba `CartTotal`). */
export type Cotizacion = {
  /** Σ(precio_jornada × cantidad), sin multiplicar por jornadas. */
  subtotalPorJornada: number;
  jornadas: number;
  /** Bruto del período: subtotalPorJornada × jornadas (antes de descuentos). */
  subtotal: number;
  /** Bruto SIN las líneas de combo (C-3, #1219) — el tope real de un
   *  descuento manual en $: no se le puede descontar más a un pedido que a
   *  su parte descontable (los combos ya vienen con su propio descuento). */
  subtotalDescontable: number;
  descuentoPct: number;
  descuentoOrigen: DescuentoOrigen;
  descuentoMonto: number;
  /** Neto = subtotal − descuento. Es lo que se PERSISTE en `monto_total`. */
  totalNeto: number;
  /** IVA (0 si el cliente no es responsable_inscripto). */
  iva: number;
  conIva: boolean;
  /** Total a mostrar: neto + IVA. */
  total: number;
  /** Detalle por equipo (para el caján/teasers; el front lo muestra, no lo calcula). */
  lineas: CotizacionLinea[];
  /** Pedido + sus turnos del Estudio vinculados como UNA sola venta (#1308).
   *  `null` cuando el pedido no tiene turnos (el caso normal). El IVA acá es el
   *  del neto COMBINADO, resuelto por el backend — el front no puede sumarlo
   *  él: `monto_total` de un turno es NETO, así que sumar el total CON IVA del
   *  principal a turnos SIN IVA daba menos de lo que factura el comprobante. */
  combinado: CotizacionCombinada | null;
};

/** Las dos partes de un pedido (equipos + turnos) resueltas como un solo total. */
export type CotizacionCombinada = {
  /** Σ de los `monto_total` (netos) de los turnos vinculados no cancelados. */
  turnosTotal: number;
  /** Neto de las dos partes: `totalNeto` del pedido + `turnosTotal`. */
  totalNeto: number;
  conIva: boolean;
  iva: number;
  /** El número grande de la pantalla: neto combinado + su IVA. */
  total: number;
};

/** Una línea cruda del backend. */
type CotizarLineaResp = {
  equipo_id: number | null;
  cantidad: number;
  precio_jornada: number;
  subtotal_por_jornada: number;
  bruto: number;
  neto: number;
};

/** Respuesta cruda del backend (`/api/cotizar`). */
type CotizarResp = {
  jornadas: number;
  subtotal_por_jornada: number;
  descuento_origen: DescuentoOrigen;
  bruto: number;
  bruto_descontable: number;
  descuento_pct: number;
  descuento_monto: number;
  neto: number;
  con_iva: boolean;
  iva_pct: number;
  iva_monto: number;
  total_final: number;
  lineas?: CotizarLineaResp[];
  combinado?: {
    turnos_total: number;
    neto: number;
    con_iva: boolean;
    iva_monto: number;
    total_final: number;
  } | null;
};

export const COTIZACION_VACIA: Cotizacion = {
  subtotalPorJornada: 0,
  jornadas: 1,
  subtotal: 0,
  subtotalDescontable: 0,
  descuentoPct: 0,
  descuentoOrigen: "ninguno",
  descuentoMonto: 0,
  totalNeto: 0,
  iva: 0,
  conIva: false,
  total: 0,
  lineas: [],
  combinado: null,
};

function adaptar(r: CotizarResp): Cotizacion {
  return {
    subtotalPorJornada: r.subtotal_por_jornada,
    jornadas: r.jornadas,
    subtotal: r.bruto,
    subtotalDescontable: r.bruto_descontable,
    descuentoPct: r.descuento_pct,
    descuentoOrigen: r.descuento_origen,
    descuentoMonto: r.descuento_monto,
    totalNeto: r.neto,
    iva: r.iva_monto,
    conIva: r.con_iva,
    total: r.total_final,
    lineas: (r.lineas ?? []).map((l) => ({
      equipoId: l.equipo_id,
      cantidad: l.cantidad,
      precioJornada: l.precio_jornada,
      subtotalPorJornada: l.subtotal_por_jornada,
      bruto: l.bruto,
      neto: l.neto,
    })),
    combinado: r.combinado
      ? {
          turnosTotal: r.combinado.turnos_total,
          totalNeto: r.combinado.neto,
          conIva: r.combinado.con_iva,
          iva: r.combinado.iva_monto,
          total: r.combinado.total_final,
        }
      : null,
  };
}

/** Lookup por equipo_id (backend id) del detalle por línea de una cotización. */
export function lineaPorEquipo(
  cot: Cotizacion,
  equipoId: number | null | undefined,
): CotizacionLinea | undefined {
  if (equipoId == null) return undefined;
  return cot.lineas.find((l) => l.equipoId === equipoId);
}

export type CotizarItemInput = {
  /** null = línea personalizada (#805): manda su precio y modo (no se busca en `equipos`). */
  equipoId: number | null;
  cantidad: number;
  /** Línea personalizada: precio libre y modo de cobro. */
  precioJornada?: number;
  cobroModo?: "jornada" | "fijo";
};

/**
 * Cotiza el carrito contra el backend. Refetch automático al cambiar ítems o
 * fechas; mantiene el valor anterior mientras recalcula (sin parpadeo).
 * Carrito vacío → devuelve `COTIZACION_VACIA` sin pegarle al backend.
 */
export function useCotizacion(args: {
  items: CotizarItemInput[];
  /** ISO-local `YYYY-MM-DDTHH:MM:00` (usar `toLocalISO`). Sin fechas → estimado. */
  fechaDesde?: string | null;
  fechaHasta?: string | null;
  /** Solo admin: cotizar para el cliente del pedido. */
  clienteId?: number | null;
  /** Solo admin: override manual del pedido en % (el builder lo edita en vivo). */
  descuentoPct?: number | null;
  /** Solo admin, Fase C-2 (#1219): tipo del override manual — "pct" (default)
   *  o "monto" ($ fijo). Mismo campo de la UI, un selector al lado. */
  descuentoTipo?: "pct" | "monto" | null;
  /** Solo admin, Fase C-2: override manual del pedido en $ fijo, usado cuando
   *  `descuentoTipo === "monto"`. */
  descuentoMonto?: number | null;
  /**
   * Solo admin, para el editor de un pedido YA EXISTENTE: respeta el
   * `precioJornada` de cada ítem (el snapshot congelado del pedido, editable
   * por el admin) en vez de recotizar contra el precio de catálogo de HOY.
   * Sin esto, el total "en vivo" del editor podía no coincidir con el que
   * persiste el guardado — dos totales del mismo pedido. Ver MEMORIA
   * 2026-06-06 "Datos del pedido: plata congelada".
   */
  respetarPrecioItem?: boolean;
  /**
   * Solo admin, editor de un pedido existente: id del pedido para respetar el
   * descuento CONGELADO (cliente + jornadas) cuando el pedido ya no es
   * `presupuesto`. Sin esto, el editor recotiza el descuento del cliente en vivo
   * y muestra un total distinto al persistido / a la lista. Ver
   * `CotizarRequest.pedido_id` (backend). En presupuesto no se pasa (vivo).
   */
  pedidoId?: number | null;
  /**
   * Identidad de la entidad DUEÑA de esta cotización (ej. el id del pedido).
   * Sin esto, el hook asume una identidad estable (ej. "el carrito"), donde
   * mostrar el valor anterior mientras se recalcula es lo deseado (sin
   * parpadeo al editar). Con un `resetKey` que cambia — ej. el admin navega
   * a OTRO pedido en un panel maestro-detalle que no desmonta el componente
   * (`/admin/pedidos/$id`) — el hook deja de mostrar el placeholder de la
   * entidad ANTERIOR: mejor un instante en $0 que el desglose de otro pedido
   * superpuesto al nombre del nuevo (bug real, confirmado con los valores en
   * 0 en la base — no era un cálculo mal hecho, era este hook mostrando la
   * cotización vieja mientras la nueva todavía viajaba por la red).
   */
  resetKey?: string | number | null;
  enabled?: boolean;
}): { data: Cotizacion; isFetching: boolean; isError: boolean } {
  const {
    items,
    fechaDesde,
    fechaHasta,
    clienteId,
    descuentoPct,
    descuentoTipo,
    descuentoMonto,
    respetarPrecioItem = false,
    pedidoId = null,
    resetKey = null,
    enabled = true,
  } = args;

  const body = {
    items: items
      .filter((i) => i.cantidad > 0)
      .map((i) => ({
        equipo_id: i.equipoId,
        cantidad: i.cantidad,
        // Personalizadas (equipoId null): siempre mandan precio/modo propios.
        // Catálogo con `respetarPrecioItem`: el backend solo lo honra si la
        // sesión es admin; en el resto de los usos (carrito público) el
        // backend ignora estos campos y toma el precio de `equipos`.
        ...(i.equipoId == null || respetarPrecioItem
          ? { precio_jornada: i.precioJornada ?? 0, cobro_modo: i.cobroModo ?? "jornada" }
          : {}),
      })),
    fecha_desde: fechaDesde ?? null,
    fecha_hasta: fechaHasta ?? null,
    cliente_id: clienteId ?? null,
    descuento_pct: descuentoPct ?? null,
    descuento_manual_tipo: descuentoTipo ?? null,
    descuento_manual_monto: descuentoMonto ?? null,
    respetar_precio_item: respetarPrecioItem,
    pedido_id: pedidoId ?? null,
  };

  // Debounce: la query usa el body DEBOUNCEADO. Al tipear rápido, `bodyKey`
  // cambia por tecla pero solo el último (tras COTIZAR_DEBOUNCE_MS de quietud)
  // dispara un fetch → un request por edición, no por tecla. El estado inicial
  // es inmediato (`useState(body)`).
  const bodyKey = JSON.stringify(body);
  const [debounced, setDebounced] = useState({ key: bodyKey, body });

  // Generación: se incrementa cada vez que cambia `resetKey`. Ajuste de
  // estado DURANTE el render (patrón oficial de React para resetear estado
  // al cambiar de identidad, no en un efecto) — salta el debounce en el
  // mismo render, antes de pintar, para que el body ya sea el de la entidad
  // nueva en el primer frame.
  const prevResetKeyRef = useRef(resetKey);
  const [generation, setGeneration] = useState(0);
  if (prevResetKeyRef.current !== resetKey) {
    prevResetKeyRef.current = resetKey;
    setGeneration((g) => g + 1);
    if (bodyKey !== debounced.key) setDebounced({ key: bodyKey, body });
  }

  useEffect(() => {
    if (bodyKey === debounced.key) return;
    const t = setTimeout(() => setDebounced({ key: bodyKey, body }), COTIZAR_DEBOUNCE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- debounce: dispara por el hash del body; `body` se captura fresco cuando cambia el hash
  }, [bodyKey, debounced.key]);

  const hayItems = debounced.body.items.length > 0;
  const q = useQuery({
    queryKey: ["cotizar", debounced.body],
    queryFn: () => authedPostJson<CotizarResp>("/api/cotizar", debounced.body),
    enabled: enabled && hayItems,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });

  // Mientras el dato que devuelve `q` sea un PLACEHOLDER (de `keepPreviousData`,
  // de una generación anterior) no lo mostramos como si fuera de la entidad
  // actual — se corrige solo apenas responde el fetch real de la generación
  // nueva. Sin `resetKey` (default `null`, nunca cambia) esto es un no-op:
  // mismo comportamiento de siempre para los demás consumidores del hook.
  const lastGoodGenerationRef = useRef(-1);
  if (q.data && !q.isPlaceholderData) {
    lastGoodGenerationRef.current = generation;
  }
  const identityPending = lastGoodGenerationRef.current !== generation;

  // `isFetching` cubre TAMBIÉN el intervalo de debounce (hay una edición
  // pendiente de recalcular) → el consumidor puede mostrar "recalculando…" y
  // no presentar el número viejo como definitivo. `isError` surfacea un fallo
  // del recálculo (ej. 429) en vez de quedarse mudo con el valor stale.
  const pendingDebounce = bodyKey !== debounced.key;

  // Carrito vacío → cero, sin arrastrar el último valor cacheado por
  // `keepPreviousData` (si no, al vaciar el carrito quedaría el total viejo).
  return {
    data: hayItems && q.data && !identityPending ? adaptar(q.data) : COTIZACION_VACIA,
    isFetching: q.isFetching || pendingDebounce || identityPending,
    isError: q.isError,
  };
}

/** Etiqueta de la fila de descuento. Cuando gana el del cliente se personaliza
 *  con su nombre ("Descuento para Tincho") — atención manual del dueño.
 *  "manual" (jerarquía, #1219): el admin lo seteó a mano para ESE pedido —
 *  gana outright, no compite con cliente/jornadas. */
export function descuentoLabel(
  origen: DescuentoOrigen,
  jornadas: number,
  nombreCliente?: string | null,
): string {
  if (origen === "manual") {
    return "Descuento manual";
  }
  if (origen === "jornadas") {
    return `Descuento jornadas (${jornadas} ${jornadas === 1 ? "jornada" : "jornadas"})`;
  }
  if (origen === "cliente") {
    const nombre = nombreCliente?.trim();
    return nombre ? `Descuento para ${nombre}` : "Descuento cliente";
  }
  return "";
}
