/**
 * ClientePortalPedido.tsx — Componentes de pedido, documentos y timeline.
 *
 * Extraído de cliente.portal.tsx (move-verbatim, sin cambios de lógica).
 * Contiene: PedidoEmpty, PedidoCard, DocPath, DocActions, DocPreviewModal,
 * DocAvailablePopup, PedidoTimeline (+ helpers buildTimelineSteps, fmtTimelineDateTime).
 */

import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { clienteApi } from "@/lib/cliente/api";
import { EstadoBadge } from "@/design-system/ui/EstadoBadge";
import { PagoBadge } from "@/design-system/ui/PagoBadge";
import { Pill } from "@/design-system/ui/Pill";
import {
  ArrowRight,
  ChevronDown,
  ShoppingBag,
  Pencil,
  Clock,
  X as XIcon,
  CheckCircle2,
  XCircle,
  Info,
  FileText,
  FileSignature,
  Truck,
  Receipt,
  MessageCircle,
  Search,
  CircleCheckBig,
  RotateCcw,
} from "lucide-react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/design-system/ui/alert-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/design-system/ui/dialog";
import { Button } from "@/design-system/ui/button";
import { ModalBackdrop } from "@/design-system/ui/modal-backdrop";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { useBusinessPhone } from "@/lib/business";
import { jornadasFromISO as jornadasEntre } from "@/lib/rental-dates";
import { whatsappLink } from "@/lib/whatsapp";
import { MODIFICAR_PEDIDOS_HABILITADO } from "@/lib/features";
import { useCart } from "@/lib/cart-store";
import { rearmarCarrito } from "@/lib/rearmar-carrito";
import { GuardarComoListaButton } from "@/components/rental/GuardarComoListaButton";
import { CompartirComposicionButton } from "@/components/rental/CompartirComposicionButton";
import { cn } from "@/lib/utils";
import { ESTADO_SOLID, ESTADO_RING } from "@/design-system/ui/estado-color";
import type { EstadoPedido } from "@/lib/pedido-estados";
import {
  fmt,
  fmtDate,
  fmtTime,
  wasDocSeen,
  markDocSeen,
  MODIFICABLE_STATES,
} from "./ClientePortalTypes";
import { DOC_LABEL, DOC_DESCRIPTION, type Pedido, type DocTipo } from "./ClientePortalTypes";

// ── Constantes de docs (solo usadas aquí) ────────────────────────────────────
// DOC_LABEL/DOC_DESCRIPTION viven en ClientePortalTypes.ts (fuente única,
// reusada por el checkout); los íconos son propios de esta pantalla.

const DOC_ICONS: Record<DocTipo, string> = {
  remito:
    "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z M14 2v6h6 M16 13H8 M16 17H8 M10 9H8",
  contrato: "M9 11l3 3 8-8 M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11",
  albaran:
    "M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z",
  factura:
    "M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z M8 7h8 M8 11h8 M8 15h5",
  "packing-list":
    "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2 M9 5a2 2 0 012-2h2a2 2 0 012 2 M9 5a2 2 0 002 2h2a2 2 0 002-2 M9 14l2 2 4-4",
};

// ── Timeline constants (solo usadas aquí) ────────────────────────────────────

type TLState = "pending" | "done" | "current" | "rejected";
type TLStep = {
  key: string;
  label: string;
  desc: string;
  fecha?: string | null;
  nota?: string | null;
  state: TLState;
};

const FLOW_STEPS: ReadonlyArray<{ tipo: string; label: string; desc: string }> = [
  {
    tipo: "solicitado",
    label: "Solicitado",
    desc: "Recibimos tu pedido. Lo revisamos y te confirmamos disponibilidad.",
  },
  {
    tipo: "confirmado",
    label: "Confirmado",
    desc: "Equipos reservados a tu nombre. Listo para retirar en la fecha.",
  },
  { tipo: "retirado", label: "Retirado", desc: "Pasaste por el local y te llevaste el equipo." },
  { tipo: "devuelto", label: "Devuelto", desc: "Recibimos el equipo de vuelta y lo revisamos." },
  { tipo: "finalizado", label: "Finalizado", desc: "Pedido cerrado. Gracias por elegirnos." },
];

// Cuántos FLOW_STEPS están completados según el estado actual.
const ESTADO_PROGRESS: Record<string, number> = {
  borrador: 0,
  solicitado: 1,
  confirmado: 2,
  retirado: 3,
  devuelto: 4,
  finalizado: 5,
};

function buildTimelineSteps(pedido: Pedido): TLStep[] {
  const cancelado = pedido.estado === "cancelado";
  const progress = ESTADO_PROGRESS[pedido.estado] ?? 1;

  const flow: TLStep[] = FLOW_STEPS.map((step, idx) => ({
    key: step.tipo,
    label: step.label,
    desc: step.desc,
    // Solo el primer paso ("solicitado") tiene fecha exacta — viene de
    // created_at del pedido. Los demás no se loggean en backend (gap).
    fecha: step.tipo === "solicitado" ? (pedido.created_at ?? null) : null,
    state: idx < progress ? "done" : "pending",
  }));

  // Eventos de modificación derivados de solicitudes[]. Solo mostramos al
  // cliente las que él inició: pendiente/aprobada/rechazada, más las
  // canceladas-por-sistema (cuando el pedido cambia de estado y se anula
  // la solicitud). Las que él mismo canceló no las mostramos — ya lo sabe.
  const mods: TLStep[] = [];
  for (const sol of pedido.solicitudes ?? []) {
    mods.push({
      key: `mod_sol-${sol.id}`,
      label: "Modificación solicitada",
      desc: "Pediste un cambio en el pedido.",
      fecha: sol.created_at,
      state: sol.estado === "pendiente" ? "current" : "done",
    });
    if (sol.estado === "aprobada") {
      mods.push({
        key: `mod_ap-${sol.id}`,
        label: "Modificación aceptada",
        desc: "Aplicamos el cambio que pediste.",
        fecha: sol.resolved_at,
        nota: sol.respuesta,
        state: "done",
      });
    } else if (sol.estado === "rechazada") {
      mods.push({
        key: `mod_re-${sol.id}`,
        label: "Modificación rechazada",
        desc: "No pudimos aplicar el cambio.",
        fecha: sol.resolved_at,
        nota: sol.respuesta,
        state: "rejected",
      });
    } else if (sol.estado === "cancelada" && sol.resolved_by === "system") {
      mods.push({
        key: `mod_ca-${sol.id}`,
        label: "Solicitud anulada",
        desc: "El pedido cambió de estado y la solicitud quedó sin efecto.",
        fecha: sol.resolved_at,
        nota: sol.respuesta,
        state: "rejected",
      });
    }
  }

  // Mezclar: ítems con fecha en orden cronológico + flow sin fecha
  // mantienen su posición relativa después.
  const withDate = [...flow.filter((s) => s.fecha), ...mods.filter((m) => m.fecha)].sort((a, b) =>
    (a.fecha ?? "").localeCompare(b.fecha ?? ""),
  );
  const withoutDate = flow.filter((s) => !s.fecha);

  let merged: TLStep[] = [...withDate, ...withoutDate];

  if (cancelado) {
    merged = merged.filter((it) => it.state !== "pending");
    merged.push({
      key: "cancelado",
      label: "Cancelado",
      desc: "El pedido fue cancelado.",
      state: "rejected",
    });
    return merged;
  }

  // Marcar paso actual: si ya hay un "current" (por solicitud pendiente)
  // no tocamos; sino, el último "done" pasa a "current".
  const hasCurrent = merged.some((it) => it.state === "current");
  if (!hasCurrent) {
    let lastDone = -1;
    for (let i = 0; i < merged.length; i++) {
      if (merged[i].state === "done") lastDone = i;
    }
    if (lastDone >= 0) merged[lastDone].state = "current";
  }

  return merged;
}

function fmtTimelineDateTime(s?: string | null): string | null {
  if (!s) return null;
  const dStr = s.slice(0, 10);
  if (dStr.length < 10) return null;
  const d = new Date(dStr + "T" + (s.length >= 16 ? s.slice(11, 16) : "12:00") + ":00");
  if (Number.isNaN(d.getTime())) return null;
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
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${dias[d.getDay()]} ${d.getDate()} ${meses[d.getMonth()]} · ${hh}:${mm}`;
}

// ── PedidoEmpty ───────────────────────────────────────────────────────────────

export function PedidoEmpty({
  title,
  sub,
  cta,
  actionLabel,
  onAction,
  icon = "bag",
}: {
  title: string;
  sub: string;
  cta?: boolean;
  actionLabel?: string;
  onAction?: () => void;
  icon?: "bag" | "search";
}) {
  const Icon = icon === "search" ? Search : ShoppingBag;
  return (
    <EmptyState
      icon={<Icon className="h-6 w-6" strokeWidth={1.5} />}
      title={title}
      sub={sub}
      className="rounded-xl border border-dashed hairline px-6 py-[60px]"
    >
      {actionLabel && onAction ? (
        <button
          type="button"
          onClick={onAction}
          className="inline-flex items-center gap-1.5 rounded-full bg-ink px-5 py-2.5 font-sans text-sm font-bold text-amber transition hover:bg-amber hover:text-ink"
        >
          {actionLabel} <XIcon className="h-3.5 w-3.5" />
        </button>
      ) : (
        cta && (
          <Link
            to="/rental"
            className="inline-flex items-center gap-1.5 rounded-full bg-ink px-5 py-2.5 font-sans text-sm font-bold text-amber transition hover:bg-amber hover:text-ink"
          >
            Explorar catálogo <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        )
      )}
    </EmptyState>
  );
}

// ── PedidoCard ────────────────────────────────────────────────────────────────

export function PedidoCard({
  pedido,
  expanded,
  highlight = false,
  onToggle,
  ventanaHoras,
  onChanged,
  perfilImpuestos,
}: {
  pedido: Pedido;
  expanded: boolean;
  highlight?: boolean;
  onToggle: () => void;
  ventanaHoras: number;
  onChanged: () => void;
  perfilImpuestos: string | null;
}) {
  const navigate = useNavigate();
  const businessPhone = useBusinessPhone();
  const { documentos_disponibles: docs } = pedido;
  const numero = pedido.numero_pedido ?? pedido.id;
  // Pedido recién enviado: banner de bienvenida con los próximos pasos.
  const showWelcome = highlight && pedido.estado === "solicitado";
  const jornadas = jornadasEntre(pedido.fecha_desde, pedido.fecha_hasta);
  const tlCurrent = buildTimelineSteps(pedido).find((s) => s.state === "current");
  const cardRef = useRef<HTMLDivElement>(null);

  // Al colapsar, la página pierde alto y el scroll se clampea saltando arriba.
  // Capturamos el top del head antes del toggle y compensamos con scrollBy en
  // el próximo frame para que la card quede en la misma posición visual.
  function handleToggle() {
    if (expanded && cardRef.current) {
      const before = cardRef.current.getBoundingClientRect().top;
      onToggle();
      requestAnimationFrame(() => {
        if (!cardRef.current) return;
        const after = cardRef.current.getBoundingClientRect().top;
        if (after !== before) window.scrollBy(0, after - before);
      });
    } else {
      onToggle();
    }
  }

  const [askCancel, setAskCancel] = useState(false);

  // Repetir pedido: rearma el carrito con los equipos de catálogo de este pedido
  // y lleva a elegir nuevas fechas. Re-resuelve precio y disponibilidad ACTUALES
  // (no reusa el snapshot del pedido — ver lib/rearmar-carrito.ts). Las líneas
  // personalizadas (#805, sin equipo_id) no se pueden repetir → se omiten.
  const [askRepetir, setAskRepetir] = useState(false);
  const itemsRepetibles = pedido.items.filter((it) => it.equipo_id != null);
  function repetirPedido() {
    setAskRepetir(false);
    rearmarCarrito(
      itemsRepetibles.map((it) => ({ equipoId: it.equipo_id as number, cantidad: it.cantidad })),
    );
    toast.success(
      "Armamos tu carrito con los equipos de este pedido. Elegí las fechas para reservar.",
    );
    navigate({ to: "/rental", search: { openCarrito: true } });
  }
  function handleRepetirClick() {
    if (itemsRepetibles.length === 0) {
      toast.info("Este pedido no tiene equipos del catálogo para repetir.");
      return;
    }
    // Solo molestamos con la confirmación si hay algo que pisar en el carrito.
    if (useCart.getState().totalItems() > 0) {
      setAskRepetir(true);
      return;
    }
    repetirPedido();
  }

  const pendiente = (pedido.solicitudes ?? []).find((s) => s.estado === "pendiente");
  // Última solicitud que el cliente debe ver: aprobada, rechazada, o
  // cancelada por el sistema (cuando el pedido cambia de estado). Las
  // canceladas por el propio cliente las ocultamos: él la canceló.
  const ultimaResuelta = !pendiente
    ? (pedido.solicitudes ?? [])
        .filter((s) => {
          if (s.estado === "aprobada" || s.estado === "rechazada") return true;
          if (s.estado === "cancelada" && s.resolved_by === "system") return true;
          return false;
        })
        .sort((a, b) =>
          (b.resolved_at ?? b.created_at).localeCompare(a.resolved_at ?? a.created_at),
        )[0]
    : undefined;

  const dentroVentana = (() => {
    if (!pedido.fecha_desde) return true; // pedido sin fechas: permitir editar
    const desde = new Date(pedido.fecha_desde.slice(0, 10) + "T00:00:00").getTime();
    if (Number.isNaN(desde)) return true; // fecha inválida: no bloqueamos
    const ms = ventanaHoras * 60 * 60 * 1000;
    return desde - Date.now() >= ms;
  })();

  // Modificación de pedidos por el cliente: PAUSADA por feature flag (#750).
  const puedeModificar =
    MODIFICAR_PEDIDOS_HABILITADO &&
    MODIFICABLE_STATES.has(pedido.estado) &&
    !pendiente &&
    dentroVentana;

  async function cancelarSolicitud() {
    if (!pendiente) return;
    try {
      await clienteApi.cancelarSolicitud(pedido.id, pendiente.id);
      toast.success("Solicitud cancelada");
      onChanged();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  // Desglose canónico desde el backend (services/precios.calcular_total).
  // Antes este componente hardcodeaba `* 0.21` y comparaba el literal
  // "responsable_inscripto" — el backend ya lo provee aplicando la misma
  // regla que el carrito, el admin y el PDF (#496).
  const subtotalItems = pedido.bruto ?? pedido.items.reduce((acc, it) => acc + it.subtotal, 0);
  const descuentoPct = pedido.descuento_pct ?? 0;
  const descuentoMonto = pedido.descuento_monto ?? Math.round(subtotalItems * (descuentoPct / 100));
  const totalNeto = pedido.monto_neto ?? pedido.monto_total ?? subtotalItems - descuentoMonto;
  const conIva = pedido.con_iva ?? false;
  const ivaPct = pedido.iva_pct ?? 21;
  const ivaMonto = pedido.iva_monto ?? 0;
  const total = pedido.total_con_iva ?? totalNeto;
  const pagado = pedido.monto_pagado ?? 0;
  const balance = Math.max(0, total - pagado);

  const retiroTime = fmtTime(pedido.fecha_desde);
  const devolucionTime = fmtTime(pedido.fecha_hasta);

  return (
    <div
      ref={cardRef}
      id={`pedido-${pedido.id}`}
      className={cn(
        "rounded-xl border bg-surface overflow-hidden transition-[border-color,box-shadow] scroll-mt-4",
        expanded
          ? "border-amber shadow-[0_0_0_1px_var(--amber)]"
          : "border-[var(--hairline)] hover:border-ink/30",
        highlight && "ring-2 ring-amber ring-offset-2 ring-offset-background animate-pulse",
      )}
    >
      <div className="flex items-stretch">
        <button
          type="button"
          onClick={handleToggle}
          className="flex-1 min-w-0 flex items-center gap-3.5 px-portal py-3.5 transition hover:bg-[color-mix(in_oklch,var(--ink)_2%,transparent)] text-left"
        >
          <span className="font-mono text-sm font-bold text-ink tracking-[0.04em]">
            #{pedido.numero_pedido}
          </span>
          {pendiente ? (
            <Pill tone="warning">Mod. pendiente</Pill>
          ) : (
            <EstadoBadge estado={pedido.estado} />
          )}
          {pedido.monto_total != null && (
            <PagoBadge pagado={pagado} total={total} estado={pedido.estado} />
          )}
          <span className="font-sans text-sm text-muted-foreground flex-1 min-w-0 truncate">
            {fmtDate(pedido.fecha_desde)}
            <span className="opacity-40 mx-1">→</span>
            {fmtDate(pedido.fecha_hasta)}
          </span>
          {pedido.monto_total != null && (
            // eslint-disable-next-line no-restricted-syntax -- precio de resumen: entre text-base (16px) y text-lg (18px), extra-bold lo equilibra
            <span className="font-sans text-[17px] font-extrabold text-ink tabular-nums shrink-0">
              {/* Header colapsado: muestra el total que el cliente paga
                  (con IVA si es RI) — alineado con el desglose expandido y
                  el carrito/PDF. Fallback al neto si el backend no envió
                  el desglose (pedidos cargados desde un endpoint viejo). */}
              {fmt(pedido.total_con_iva ?? pedido.monto_total)}
            </span>
          )}
          <ChevronDown
            className={cn(
              "h-4 w-4 shrink-0 transition-[transform,color] duration-200",
              expanded ? "rotate-180 text-ink" : "text-muted-foreground",
            )}
          />
        </button>
        {!expanded && puedeModificar && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              navigate({
                to: "/cliente/pedidos/$id/editar",
                params: { id: String(pedido.id) },
              });
            }}
            className="shrink-0 px-3 sm:px-4 border-l border-[var(--hairline)] text-ink hover:bg-amber-soft transition inline-flex items-center gap-1.5"
            aria-label="Modificar pedido"
          >
            <Pencil className="h-3.5 w-3.5" />
            <span className="font-sans text-xs font-semibold hidden sm:inline">Modificar</span>
          </button>
        )}
      </div>

      {expanded && (
        <div className="border-t border-dashed border-[var(--hairline)] px-portal pt-[18px] pb-[22px] grid gap-y-5 gap-x-7 animate-[expand-in_.22s_ease-out] [grid-template-areas:'banner''timeline''docs''main''side'] lg:[grid-template-columns:minmax(0,1fr)_clamp(20rem,26%,25rem)] lg:[grid-template-rows:auto_auto_min-content_min-content_1fr] lg:[grid-template-areas:'banner_banner''timeline_timeline''main_docs''main_side''main_.']">
          {/* ── Banner: solicitud pendiente / resuelta / bienvenida (full width) ── */}
          {(pendiente || ultimaResuelta || showWelcome) && (
            <div className="[grid-area:banner] flex flex-col gap-3">
              {showWelcome && (
                <section className="rounded-md border border-amber bg-amber-soft px-3.5 py-3 flex items-start gap-2.5">
                  <CircleCheckBig className="h-4 w-4 text-amber mt-0.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="font-sans text-base font-semibold text-ink">
                      ¡Recibimos tu solicitud!
                    </div>
                    <div className="font-sans text-xs text-ink/70 mt-0.5">
                      La estamos revisando. Cuando confirmemos la disponibilidad vas a poder
                      descargar el remito y el contrato desde acá. Seguí el estado en la línea de
                      tiempo de abajo.
                    </div>
                  </div>
                </section>
              )}
              {pendiente && (
                <section className="rounded-md border border-amber bg-amber-soft px-3.5 py-3 flex items-start gap-2.5">
                  <Clock className="h-4 w-4 text-amber mt-0.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="font-sans text-base font-semibold text-ink">
                      Solicitud de modificación pendiente
                    </div>
                    <div className="font-sans text-xs text-ink/70 mt-0.5">
                      Estamos revisando los cambios que pediste. Te avisamos por mail cuando los
                      resolvamos.
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setAskCancel(true)}
                    className="rounded-full px-4 py-2 font-sans text-sm font-semibold text-ink border border-ink/20 hover:border-ink transition shrink-0 inline-flex items-center gap-1.5 min-h-[40px]"
                  >
                    <XIcon className="h-3.5 w-3.5" /> Cancelar
                  </button>
                </section>
              )}

              {ultimaResuelta &&
                (() => {
                  const isAprobada = ultimaResuelta.estado === "aprobada";
                  const isRechazada = ultimaResuelta.estado === "rechazada";
                  const isSystemCancel = ultimaResuelta.estado === "cancelada"; // ya filtramos por resolved_by='system'
                  const titulo = isAprobada
                    ? "Tu última solicitud fue aprobada"
                    : isRechazada
                      ? "Tu última solicitud fue rechazada"
                      : "Tu solicitud quedó sin efecto";
                  return (
                    <section
                      className={cn(
                        "rounded-md border px-3.5 py-3 flex items-start gap-2.5",
                        isAprobada
                          ? "border-verde/30 bg-verde/10"
                          : isRechazada
                            ? "border-destructive/30 bg-destructive/10"
                            : "border-azul/30 bg-azul/10",
                      )}
                    >
                      {isAprobada ? (
                        <CheckCircle2 className="h-4 w-4 text-verde mt-0.5 shrink-0" />
                      ) : isRechazada ? (
                        <XCircle className="h-4 w-4 text-destructive mt-0.5 shrink-0" />
                      ) : (
                        <Info className="h-4 w-4 text-azul mt-0.5 shrink-0" />
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="font-sans text-base font-semibold text-ink">{titulo}</div>
                        {ultimaResuelta.respuesta && (
                          <div className="font-sans text-xs text-ink/80 mt-0.5 whitespace-pre-wrap">
                            {isSystemCancel ? ultimaResuelta.respuesta : ultimaResuelta.respuesta}
                          </div>
                        )}
                      </div>
                    </section>
                  );
                })()}
            </div>
          )}

          {/* ── Timeline: card propia, full width ── */}
          <section className="[grid-area:timeline] rounded-lg border border-[var(--hairline)] bg-card px-5 pt-[18px] pb-4">
            <div className="flex items-baseline justify-between gap-3 mb-3.5">
              <h3 className="t-section">Estado del pedido</h3>
              {tlCurrent && (
                <div className="font-sans text-xs text-muted-foreground text-right flex-1 min-w-0 leading-[1.4]">
                  <strong className="text-ink font-semibold">{tlCurrent.label}</strong>
                  {tlCurrent.desc ? ` · ${tlCurrent.desc}` : ""}
                </div>
              )}
            </div>
            <PedidoTimeline pedido={pedido} />
          </section>

          {/* ── Documentos: grid-area propia. En mobile va acá arriba (bajo el
              estado) para que el cliente los alcance sin scrollear un pedido
              largo; en desktop la grilla lo ubica igual que antes, arriba de la
              columna derecha. DOM antes de `main` → orden de lectura correcto
              para SR en mobile. Solo se muestra si hay algún documento. */}
          {(docs.remito ||
            docs.contrato ||
            docs.albaran ||
            docs.factura ||
            docs["packing-list"]) && (
            <section
              className="[grid-area:docs] rounded-md border px-3 py-3"
              style={{
                background: "color-mix(in oklch, var(--amber) 6%, var(--background))",
                borderColor: "color-mix(in oklch, var(--amber) 35%, transparent)",
              }}
            >
              <h3 className="font-mono text-xs uppercase tracking-[0.18em] text-ink/70 mb-2">
                Documentos
              </h3>
              <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(150px,1fr))]">
                {docs.remito && (
                  <DocActions pedidoId={pedido.id} numero={numero} tipo="remito" label="Remito" />
                )}
                {docs.contrato && (
                  <DocActions
                    pedidoId={pedido.id}
                    numero={numero}
                    tipo="contrato"
                    label="Contrato"
                    description={DOC_DESCRIPTION.contrato}
                  />
                )}
                {docs.albaran && (
                  <DocActions
                    pedidoId={pedido.id}
                    numero={numero}
                    tipo="albaran"
                    label="Detalle de seguro"
                    description={DOC_DESCRIPTION.albaran}
                  />
                )}
                {docs["packing-list"] && (
                  <DocActions
                    pedidoId={pedido.id}
                    numero={numero}
                    tipo="packing-list"
                    label="Checklist de retiro"
                    description={DOC_DESCRIPTION["packing-list"]}
                  />
                )}
                {docs.factura && (
                  <DocActions
                    pedidoId={pedido.id}
                    numero={numero}
                    tipo="factura"
                    label="Factura"
                    description={DOC_DESCRIPTION.factura}
                  />
                )}
              </div>
            </section>
          )}

          {/* ── Main (izquierda): período → equipos → acciones ── */}
          <div className="[grid-area:main] flex flex-col gap-5 min-w-0">
            <section className="grid grid-cols-3 gap-2">
              <div className="rounded-md border border-[var(--hairline)] bg-card px-3 py-2.5">
                <div className="font-mono text-2xs uppercase tracking-[0.22em] text-muted-foreground">
                  Retiro
                </div>
                <div className="font-sans text-sm font-semibold text-ink mt-0.5">
                  {fmtDate(pedido.fecha_desde)}
                </div>
                {retiroTime && (
                  <div className="font-mono text-xs text-muted-foreground">{retiroTime}</div>
                )}
              </div>
              <div className="rounded-md border border-[var(--hairline)] bg-card px-3 py-2.5">
                <div className="font-mono text-2xs uppercase tracking-[0.22em] text-muted-foreground">
                  Devolución
                </div>
                <div className="font-sans text-sm font-semibold text-ink mt-0.5">
                  {fmtDate(pedido.fecha_hasta)}
                </div>
                {devolucionTime && (
                  <div className="font-mono text-xs text-muted-foreground">{devolucionTime}</div>
                )}
              </div>
              <div className="rounded-md border border-[var(--hairline)] bg-card px-3 py-2.5">
                <div className="font-mono text-2xs uppercase tracking-[0.22em] text-muted-foreground">
                  Jornadas
                </div>
                <div className="font-sans text-2xl font-extrabold text-ink tabular-nums leading-none mt-1">
                  {jornadas}
                </div>
              </div>
            </section>

            <section>
              <h3 className="t-section mb-2">Equipos ({pedido.items.length})</h3>
              <ul>
                {pedido.items.map((item, i) => {
                  const display = item.nombre_publico || item.nombre;
                  return (
                    <li
                      key={item.id ?? i}
                      className="flex items-center gap-2.5 py-2 border-b border-[var(--hairline)] last:border-b-0"
                    >
                      {item.foto_url ? (
                        <img
                          src={item.foto_url}
                          alt={display}
                          loading="lazy"
                          className="h-10 w-10 rounded-sm border border-[var(--hairline)] bg-white object-cover shrink-0"
                        />
                      ) : (
                        <div className="h-10 w-10 rounded-sm border border-[var(--hairline)] bg-white grid place-items-center shrink-0">
                          <ShoppingBag
                            className="h-4 w-4 text-muted-foreground"
                            strokeWidth={1.5}
                          />
                        </div>
                      )}
                      <div className="min-w-0 flex-1">
                        {item.marca && (
                          <div className="font-mono text-2xs uppercase tracking-[0.15em] text-muted-foreground leading-none">
                            {item.marca}
                          </div>
                        )}
                        <div className="font-sans text-sm font-semibold text-ink leading-tight mt-0.5 truncate">
                          {display}
                        </div>
                        <div className="font-mono text-xs text-muted-foreground tabular-nums mt-0.5">
                          {item.cantidad} × {fmt(item.precio_jornada)}/j · {jornadas}j
                        </div>
                      </div>
                      <div className="font-mono text-sm font-bold text-ink tabular-nums shrink-0">
                        {fmt(item.subtotal)}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>

            {puedeModificar && (
              <section>
                <button
                  type="button"
                  onClick={() =>
                    navigate({
                      to: "/cliente/pedidos/$id/editar",
                      params: { id: String(pedido.id) },
                    })
                  }
                  className="inline-flex items-center gap-1.5 rounded-full bg-ink px-4 py-2 font-sans text-sm font-bold text-amber hover:bg-amber hover:text-ink transition"
                >
                  <Pencil className="h-3.5 w-3.5" /> Modificar pedido
                </button>
                {pedido.estado === "confirmado" && (
                  <p className="mt-2 font-sans text-xs text-muted-foreground">
                    Los cambios necesitarán nuestra aprobación.
                  </p>
                )}
              </section>
            )}

            {MODIFICAR_PEDIDOS_HABILITADO &&
              !puedeModificar &&
              MODIFICABLE_STATES.has(pedido.estado) &&
              !pendiente &&
              !dentroVentana && (
                <section className="rounded-md border border-dashed border-[var(--hairline)] px-3.5 py-2.5 font-sans text-xs text-muted-foreground">
                  No es posible modificar este pedido a menos de {ventanaHoras} h del retiro.
                  Contactanos directamente.
                </section>
              )}

            {itemsRepetibles.length > 0 && (
              <section>
                <Button
                  type="button"
                  variant="primary"
                  shape="pill"
                  onClick={handleRepetirClick}
                  className="min-h-[44px] px-5"
                >
                  <RotateCcw /> Repetir pedido
                </Button>
                <p className="mt-2 font-sans text-xs text-muted-foreground">
                  Armamos tu carrito con estos equipos para que reserves de nuevo. Elegís las fechas
                  y se recalcula el precio con la disponibilidad actual.
                </p>
                {/* Guardar como lista reutilizable + compartir por link público (#1092). */}
                <div className="mt-3 flex max-w-xs flex-col gap-2">
                  <GuardarComoListaButton
                    items={itemsRepetibles.map((it) => ({
                      equipo_id: it.equipo_id as number,
                      cantidad: it.cantidad,
                    }))}
                  />
                  <CompartirComposicionButton
                    label="Compartir pedido"
                    items={itemsRepetibles.map((it) => ({
                      equipo_id: it.equipo_id as number,
                      cantidad: it.cantidad,
                    }))}
                  />
                </div>
              </section>
            )}

            {(() => {
              const waHref = whatsappLink({
                phone: businessPhone,
                message: `Hola, consulta sobre el pedido #${numero}`,
              });
              if (!waHref) return null;
              return (
                <section>
                  <a
                    href={waHref}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-2 rounded-full bg-[#25D366] text-white px-4 py-2.5 font-sans text-sm font-semibold hover:brightness-95 transition min-h-[44px]"
                  >
                    <MessageCircle className="h-4 w-4" strokeWidth={2.2} />
                    Consulta por WhatsApp
                  </a>
                </section>
              );
            })()}
          </div>

          {/* ── Side (derecha): totales → pagos → notas (Documentos se movió a su
              propia grid-area, ver arriba) ── */}
          <aside className="[grid-area:side] flex flex-col gap-4 min-w-0">
            <section className="flex flex-col gap-1.5 rounded-md border border-[var(--hairline)] bg-card px-3.5 py-3">
              <div className="flex justify-between items-baseline font-sans text-sm">
                <span className="text-muted-foreground">Subtotal equipos</span>
                <span className="font-mono font-semibold text-ink tabular-nums">
                  {fmt(subtotalItems)}
                </span>
              </div>
              {descuentoPct > 0 && (
                <div className="flex justify-between items-baseline font-sans text-sm">
                  <span className="text-muted-foreground">Descuento ({descuentoPct}%)</span>
                  <span className="font-mono font-semibold tabular-nums text-verde-ink">
                    −{fmt(descuentoMonto)}
                  </span>
                </div>
              )}
              {conIva && (
                <>
                  <div className="flex justify-between items-baseline font-sans text-sm">
                    <span className="text-muted-foreground">Subtotal neto</span>
                    <span className="font-mono font-semibold text-ink tabular-nums">
                      {fmt(totalNeto)}
                    </span>
                  </div>
                  <div className="flex justify-between items-baseline font-sans text-sm">
                    <span className="text-muted-foreground">IVA {ivaPct}%</span>
                    <span className="font-mono font-semibold text-ink tabular-nums">
                      +{fmt(ivaMonto)}
                    </span>
                  </div>
                </>
              )}
              <div className="flex justify-between items-baseline pt-1.5 mt-1 border-t border-[var(--hairline)]">
                <span className="font-sans text-15 font-bold text-ink">
                  Total{conIva ? " · IVA incluído" : ""}
                </span>
                <span className="font-sans text-22 font-extrabold text-ink tabular-nums">
                  {fmt(total)}
                </span>
              </div>
              {pagado > 0 && (
                <>
                  <div className="flex justify-between items-baseline font-sans text-sm">
                    <span className="text-muted-foreground">Pagado</span>
                    <span className="font-mono font-semibold tabular-nums text-verde-ink">
                      {fmt(pagado)}
                    </span>
                  </div>
                  <div className="flex justify-between items-baseline font-sans text-sm">
                    <span className="text-muted-foreground">
                      {balance > 0 ? "Balance pendiente" : "Saldo"}
                    </span>
                    <span
                      className={cn(
                        "font-mono font-bold tabular-nums",
                        balance > 0 ? "text-ink" : "text-verde-ink",
                      )}
                    >
                      {fmt(balance)}
                    </span>
                  </div>
                </>
              )}
            </section>

            {pedido.pagos && pedido.pagos.length > 0 && (
              <section>
                <h3 className="t-section mb-2">Pagos</h3>
                <ul className="flex flex-col gap-1">
                  {pedido.pagos.map((pg, i) => (
                    <li
                      key={pg.id ?? i}
                      className="flex items-center justify-between gap-2 font-sans text-xs text-muted-foreground"
                    >
                      <span className="truncate">
                        {fmtDate(pg.fecha)}
                        {pg.concepto ? ` · ${pg.concepto}` : ""}
                      </span>
                      <span className="font-mono tabular-nums text-verde-ink shrink-0">
                        {fmt(pg.monto)}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {pedido.notas && (
              <section>
                <h3 className="t-section mb-2">Notas</h3>
                <div className="rounded-md border border-[color-mix(in_oklch,var(--amber)_40%,transparent)] bg-amber-soft px-3.5 py-3 font-sans text-xs text-ink leading-[1.5] whitespace-pre-wrap">
                  {pedido.notas}
                </div>
              </section>
            )}
          </aside>
        </div>
      )}

      <AlertDialog open={askRepetir} onOpenChange={setAskRepetir}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reemplazar el carrito</AlertDialogTitle>
            <AlertDialogDescription>
              Ya tenés equipos en el carrito. Si repetís este pedido, los vamos a reemplazar por los
              de acá. ¿Seguimos?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Volver</AlertDialogCancel>
            <AlertDialogAction onClick={repetirPedido}>Reemplazar y repetir</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={askCancel} onOpenChange={setAskCancel}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancelar solicitud de modificación</AlertDialogTitle>
            <AlertDialogDescription>
              Vamos a descartar los cambios que pediste. El pedido va a quedar como estaba.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Volver</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setAskCancel(false);
                cancelarSolicitud();
              }}
            >
              Cancelar solicitud
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// ── DocPath ───────────────────────────────────────────────────────────────────

function DocPath({ tipo }: { tipo: keyof typeof DOC_ICONS }) {
  const paths = DOC_ICONS[tipo].split(" M");
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths.map((p, i) => (
        <path key={i} d={i === 0 ? p : `M${p}`} />
      ))}
    </svg>
  );
}

// ── DocActions ────────────────────────────────────────────────────────────────

/**
 * Acciones por documento: Ver (preview HTML en modal) + Descargar (PDF).
 * Issue #106.
 */
function DocActions({
  pedidoId,
  numero,
  tipo,
  label,
  description,
}: {
  pedidoId: number;
  numero: string;
  tipo: DocTipo;
  label: string;
  description?: string;
}) {
  const [previewOpen, setPreviewOpen] = useState(false);
  // Badge "Nuevo" si todavía no se vio — solo para los notificables
  // (`DOC_NOTIFICABLE`). "remito" y "packing-list" quedan siempre vistos:
  // están disponibles desde que se crea el pedido, no son una novedad que
  // "aparece después" (a diferencia de contrato/albaran/factura). El estado
  // vive en localStorage; lo trackeamos con un ref local para que el badge
  // desaparezca instantáneamente al tocar.
  const [seen, setSeen] = useState<boolean>(() =>
    tipo === "remito" || tipo === "packing-list" ? true : wasDocSeen(pedidoId, tipo),
  );
  const showNewBadge = !seen;

  function markSeen() {
    if (tipo === "remito" || tipo === "packing-list") return;
    markDocSeen(pedidoId, tipo);
    setSeen(true);
  }

  return (
    <>
      <div className="flex items-stretch gap-1">
        <button
          type="button"
          onClick={() => {
            markSeen();
            setPreviewOpen(true);
          }}
          className="flex-1 relative flex items-center gap-2.5 rounded-md border border-[var(--hairline)] bg-card px-3 py-2.5 text-left transition hover:border-ink hover:bg-muted"
        >
          {showNewBadge && (
            <span className="absolute -top-1.5 -right-1.5 rounded-full bg-ink text-amber text-2xs font-bold tracking-wide px-1.5 py-0.5 leading-none shadow">
              Nuevo
            </span>
          )}
          <div className="grid h-8 w-8 place-items-center rounded-sm bg-amber-soft text-amber shrink-0">
            <DocPath tipo={tipo} />
          </div>
          <div className="min-w-0">
            <div className="font-sans text-xs font-semibold text-ink leading-tight">{label}</div>
            {description ? (
              <div className="font-sans text-xs text-muted-foreground leading-tight mt-0.5 line-clamp-2">
                {description}
              </div>
            ) : (
              <div className="font-mono text-2xs uppercase tracking-[0.1em] text-muted-foreground mt-0.5">
                Ver · PDF
              </div>
            )}
          </div>
        </button>
        <a
          href={`/api/cliente/pedidos/${pedidoId}/${tipo}.pdf`}
          download={`${tipo}-${numero}.pdf`}
          onClick={markSeen}
          className="grid place-items-center w-10 rounded-md border border-[var(--hairline)] bg-card text-muted-foreground transition hover:border-ink hover:text-ink"
          title={`Descargar ${label} en PDF`}
          aria-label={`Descargar ${label} en PDF`}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
        </a>
      </div>

      {previewOpen && (
        <DocPreviewModal
          title={label}
          url={`/api/cliente/pedidos/${pedidoId}/${tipo}?format=html`}
          downloadUrl={`/api/cliente/pedidos/${pedidoId}/${tipo}.pdf`}
          downloadFilename={`${tipo}-${numero}.pdf`}
          onClose={() => setPreviewOpen(false)}
        />
      )}
    </>
  );
}

// ── DocPreviewModal ───────────────────────────────────────────────────────────

/**
 * Modal con iframe que muestra el HTML del documento. Botón de descargar
 * PDF en el header. ESC o click afuera cierra.
 */
function DocPreviewModal({
  title,
  url,
  downloadUrl,
  downloadFilename,
  onClose,
}: {
  title: string;
  url: string;
  downloadUrl: string;
  downloadFilename: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  return (
    <ModalBackdrop
      onClose={onClose}
      className="z-50 bg-black/60 flex items-stretch sm:items-center justify-center sm:p-6"
    >
      <div className="bg-background w-full sm:max-w-4xl h-full sm:h-[90vh] flex flex-col sm:rounded-lg overflow-hidden shadow-xl">
        <header className="flex items-center justify-between gap-2 border-b hairline px-3 sm:px-4 py-3 shrink-0">
          <h2 className="font-display text-base text-ink truncate min-w-0">{title}</h2>
          <div className="flex items-center gap-1 sm:gap-2 shrink-0">
            <a
              href={downloadUrl}
              download={downloadFilename}
              className="inline-flex items-center gap-1.5 rounded-md bg-ink text-amber px-2.5 sm:px-3 py-2 text-xs font-medium hover:brightness-110 transition"
              aria-label="Descargar PDF"
            >
              <span aria-hidden>⬇</span>
              <span className="hidden sm:inline">Descargar PDF</span>
            </a>
            <button
              type="button"
              onClick={onClose}
              className="grid h-11 w-11 place-items-center rounded-md hover:bg-muted transition"
              aria-label="Cerrar"
            >
              ✕
            </button>
          </div>
        </header>
        <iframe src={url} title={title} className="flex-1 w-full bg-white border-0" />
      </div>
    </ModalBackdrop>
  );
}

// ── DocAvailablePopup ─────────────────────────────────────────────────────────

/**
 * Popup one-shot que notifica al cliente cuando un documento nuevo
 * (Contrato/Albarán) está disponible. Cada (pedido, doc) se persiste en
 * localStorage al cerrar para no volver a aparecer.
 */
export function DocAvailablePopup({
  nuevos,
  onDismiss,
  onVerPedido,
}: {
  nuevos: Array<{ pedidoId: number; numero: string; tipo: DocTipo }>;
  onDismiss: () => void;
  onVerPedido: (pedidoId: number) => void;
}) {
  const open = nuevos.length > 0;
  const MAX_VISIBLE = 4;
  const visibles = nuevos.slice(0, MAX_VISIBLE);
  const resto = nuevos.length - visibles.length;
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onDismiss();
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Tenés documentos nuevos disponibles</DialogTitle>
          <DialogDescription>
            Estos documentos quedaron habilitados en tu portal. Podés verlos cuando quieras.
          </DialogDescription>
        </DialogHeader>
        <ul className="space-y-2.5 my-2">
          {visibles.map((d) => {
            const Icon =
              d.tipo === "contrato"
                ? FileSignature
                : d.tipo === "albaran"
                  ? Truck
                  : d.tipo === "factura"
                    ? Receipt
                    : FileText;
            return (
              <li
                key={`${d.pedidoId}-${d.tipo}`}
                className="flex items-start gap-3 rounded-md border hairline px-3 py-2.5"
              >
                <div className="grid h-9 w-9 place-items-center rounded-sm bg-amber-soft text-amber shrink-0">
                  <Icon className="h-4 w-4" strokeWidth={1.7} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="font-sans text-sm font-semibold text-ink">
                    {DOC_LABEL[d.tipo]}
                    <span className="text-muted-foreground font-mono text-xs ml-1.5">
                      #{d.numero}
                    </span>
                  </div>
                  {DOC_DESCRIPTION[d.tipo] && (
                    <div className="font-sans text-xs text-muted-foreground mt-0.5">
                      {DOC_DESCRIPTION[d.tipo]}
                    </div>
                  )}
                </div>
                <Button
                  variant="outline"
                  className="shrink-0 min-h-11"
                  onClick={() => onVerPedido(d.pedidoId)}
                >
                  Ver pedido
                </Button>
              </li>
            );
          })}
          {resto > 0 && (
            <li className="px-3 py-1 text-center font-sans text-xs text-muted-foreground">
              y {resto} documento{resto > 1 ? "s" : ""} más en tu portal
            </li>
          )}
        </ul>
        <DialogFooter>
          <Button className="min-h-11" onClick={onDismiss}>
            Entendido
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── PedidoTimeline ────────────────────────────────────────────────────────────

export function PedidoTimeline({ pedido }: { pedido: Pedido }) {
  const steps = buildTimelineSteps(pedido);
  return (
    <div className="flex flex-row items-start gap-0 pt-1">
      {steps.map((s, i) => {
        const isLast = i === steps.length - 1;
        // El color sale de la fuente única `estado-color.ts` cuando el paso es un
        // ESTADO del pedido (su `key` es el estado: solicitado/confirmado/…). Los
        // pasos de "modificación" (no son estados) mantienen el neutro del portal.
        const solid = ESTADO_SOLID[s.key as EstadoPedido];
        const dotCls =
          s.state === "rejected"
            ? "border-destructive bg-destructive text-white"
            : s.state === "pending"
              ? "border-[var(--hairline)] bg-background text-muted-foreground border-dashed"
              : solid
                ? cn(
                    "text-white",
                    solid,
                    s.state === "current" &&
                      cn("ring-4 ring-offset-0", ESTADO_RING[s.key as EstadoPedido]),
                  )
                : s.state === "current"
                  ? "border-amber bg-amber text-ink shadow-[0_0_0_4px_var(--amber-soft)]"
                  : "border-ink bg-ink text-amber";
        const connectorCls =
          s.state === "rejected"
            ? "after:bg-destructive/30"
            : s.state === "pending"
              ? "after:bg-[var(--hairline)]"
              : "after:bg-ink/20";
        const Icon =
          s.state === "rejected"
            ? XCircle
            : s.state === "current"
              ? Clock
              : s.state === "done"
                ? CircleCheckBig
                : Clock;
        return (
          <div
            key={s.key}
            className={cn(
              "relative flex-1 min-w-0 flex flex-col items-center text-center px-1 gap-2",
              !isLast &&
                "after:content-[''] after:absolute after:top-[13px] after:left-[calc(50%+18px)] after:right-[calc(-50%+18px)] after:h-0.5",
              !isLast && connectorCls,
            )}
          >
            <div
              className={cn(
                "z-[1] grid h-7 w-7 shrink-0 place-items-center rounded-full border-2",
                dotCls,
              )}
            >
              <Icon className="h-3 w-3" strokeWidth={2} />
            </div>
            <div className="w-full min-w-0">
              <div
                className={cn(
                  "font-sans text-xs leading-tight truncate",
                  s.state === "pending"
                    ? "text-muted-foreground font-semibold"
                    : "font-bold text-ink",
                )}
              >
                {s.label}
              </div>
              <div className="font-mono text-2xs uppercase tracking-[0.06em] text-muted-foreground tabular-nums mt-0.5">
                {s.fecha ? fmtTimelineDateTime(s.fecha) : "—"}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
