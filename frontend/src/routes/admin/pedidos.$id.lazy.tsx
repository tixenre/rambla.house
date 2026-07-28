import { createLazyFileRoute, useNavigate, useParams, Link } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  User,
  Calendar,
  Box,
  FileText,
  Check,
  AlertTriangle,
  Coins,
  Plus,
  Minus,
  X,
  Mail,
  Eye,
  Download,
  Info,
  Trash2,
  GripVertical,
  Tag,
  ShieldAlert,
  ShieldCheck,
  Copy,
} from "lucide-react";
import { toast } from "sonner";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { cn } from "@/lib/utils";

import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { MoneyInput } from "@/design-system/ui/money-input";
import { Textarea } from "@/design-system/ui/textarea";
import { Skeleton } from "@/design-system/ui/skeleton";
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
import { EstadoBadge } from "@/design-system/ui/EstadoBadge";
import { estadoClase, ESTADO_TEXT } from "@/design-system/ui/estado-color";
import { WhatsAppButton } from "@/components/admin/WhatsAppButton";
import {
  adminApi,
  estudioAdminApi,
  ESTADO_LABEL,
  pedidoPdfUrl,
  type Pedido,
  type PedidoEstado,
  type Equipo,
  type EstudioConfig,
} from "@/lib/admin/api";
import {
  usePedidoDraft,
  nuevoUidLinea,
  type DraftItem,
} from "@/components/admin/pedido/usePedidoDraft";
import { useDisponibilidadDraft } from "@/components/admin/pedido/useDisponibilidadDraft";
import { ClienteAutocomplete } from "@/components/admin/pedido/ClienteAutocomplete";
import { ClienteAvatar } from "@/design-system/ui/ClienteAvatar";
import { EquipoThumb } from "@/components/admin/pedido/EquipoThumb";
import { DateRangePickerModal } from "@/components/rental/dates/DateRangePickerModal";
import { computeJornadas, parseDateTimeParts, toLocalISO } from "@/lib/rental-dates";
import { format } from "date-fns";
import { es } from "date-fns/locale";
import { useCotizacion, descuentoLabel } from "@/lib/cotizacion";
import { combinarTotales } from "@/lib/pedido-combinado";
import { SegmentedControl } from "@/design-system/ui/segmented-control";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { fmtArs } from "@/lib/format";
import { nombreCliente } from "@/lib/cliente-nombre";
import { EquipoComboSearch } from "@/components/admin/pedido/EquipoComboSearch";
import { EnviarDocsDialog, DOCS_PEDIDO } from "@/components/admin/pedido/EnviarDocsDialog";
import { RegistrarPagoModal } from "@/components/admin/pedido/RegistrarPagoModal";
import { FLOW, transiciones, nextStep, otrosDestinos } from "@/lib/pedido-estados";
import {
  PagoRow,
  ItemRow,
  BackLink,
  SaveIndicator,
  RailSection,
  EstadoSplitButton,
  BdRow,
  FacturacionTargetSection,
  FacturacionRailSection,
} from "@/components/admin/pedido/PedidoPageHelpers";
import { Section } from "@/design-system/composites/Section";
import { FieldLabel } from "@/design-system/ui/Field";
import { esPedidoEstudio, esPedidoDerivado, esPedidoTaller } from "@/lib/tipos-pedido";
import { ReservaEstudioSection } from "@/components/admin/estudio/ReservaEstudioSection";
import { TurnosEstudioSection } from "@/components/admin/pedido/TurnosEstudioSection";

export const Route = createLazyFileRoute("/admin/pedidos/$id")({
  component: PedidoEditorRoute,
});

// `key={id}`: el panel maestro-detalle navega entre pedidos sin desmontar esta
// ruta (mismo patrón, solo cambia `$id`) — sin el key, el debounce +
// `keepPreviousData` de `useCotizacion` (lib/cotizacion.ts) no se resetea entre
// pedidos y el desglose puede mostrar, por una ventana breve, el descuento del
// pedido ANTERIOR combinado con el nombre del cliente NUEVO (bug real:
// "aparece un descuento que no existe", confirmado con datos en 0 en la base —
// era 100% un artefacto de caché del front, no del cálculo).
function PedidoEditorRoute() {
  const { id } = useParams({ from: "/admin/pedidos/$id" });
  return <PedidoEditorPage key={id} />;
}

// La máquina de estados (FLOW / transiciones / blockReason / nextStep) vive en
// @/lib/pedido-estados — fuente única compartida con el panel de detalle de la lista.

// ── Página ───────────────────────────────────────────────────────────────────

function PedidoEditorPage() {
  const { id } = useParams({ from: "/admin/pedidos/$id" });
  const navigate = useNavigate();
  const pedidoId = Number(id);
  useDocumentTitle("Pedido · Back-office");

  const pedidoQ = useQuery({
    queryKey: ["admin", "pedido", pedidoId],
    queryFn: () => adminApi.getPedido(pedidoId),
  });
  const p = pedidoQ.data;
  // keepDateTime: el selector de fechas+horas escribe datetime (con hora) en
  // fecha_desde/fecha_hasta; sin esto el draft las recortaría a date-only y se
  // perdería la hora en el round-trip del autosave.
  const draft = usePedidoDraft(p, { mode: "admin", keepDateTime: true });
  const [openDateModal, setOpenDateModal] = useState(false);

  // Sensores del drag-reorder de líneas (#806). Hook → antes de cualquier
  // early return para no violar las reglas de hooks.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  // Disponibilidad (stock) draft-aware — el backend descuenta TODO el draft con
  // la expansión de kits del motor (fuente única). Enabled cuando hay fechas.
  const dispo = useDisponibilidadDraft({
    pedidoId,
    fechaDesde: draft.datos?.fecha_desde,
    fechaHasta: draft.datos?.fecha_hasta,
    items: draft.items,
    enabled: !!p,
  });

  // Cotización en vivo (useCotizacion) — recalcula al editar items/fechas/descuento
  const cotizacionQ = useCotizacion({
    items: (draft.items ?? []).map((it) => ({
      equipoId: it.equipo_id,
      cantidad: it.cantidad,
      precioJornada: it.precio_jornada,
      cobroModo: it.cobro_modo,
    })),
    fechaDesde: draft.datos?.fecha_desde || null,
    fechaHasta: draft.datos?.fecha_hasta || null,
    clienteId: p?.cliente_id ?? null,
    descuentoPct: draft.datos?.descuento_pct ?? null,
    descuentoTipo: draft.datos?.descuento_manual_tipo ?? null,
    descuentoMonto: draft.datos?.descuento_manual_monto ?? null,
    // Pedido ya existente: el total en vivo tiene que coincidir con lo que
    // persiste el guardado (`_recalcular_total_pedido`, que usa el precio de
    // línea congelado) — no con el precio de catálogo de hoy. Regresión: este
    // flag se agregó en #1181 (commit 21642e70) pero se perdió al tocar este
    // mismo bloque en la Fase C de descuentos (#1219) — el editor volvió a
    // mostrar el precio de catálogo en vivo en vez del congelado.
    respetarPrecioItem: true,
    // Pedido con plata congelada (no-presupuesto): el descuento del preview sale
    // del snapshot del pedido, no del cliente en vivo → el total del editor
    // coincide con `monto_total` y con la lista. En presupuesto sigue en vivo
    // (para que el descuento siga al cliente que el admin elija en el builder).
    pedidoId: p && p.estado !== "solicitado" ? pedidoId : null,
    // Defensa en profundidad (sumado a `key={id}` en `PedidoEditorRoute`,
    // arriba): aunque este panel ya se remonta al cambiar de pedido, el hook
    // en sí queda protegido para cualquier otro consumidor que no lo haga.
    resetKey: pedidoId,
  });

  // Config del Estudio — solo hace falta para un turno real (tipo='estudio');
  // la sección de reserva inline (Fase 2, #1308) la necesita para franja/
  // tarifa/promo. Mismo queryKey que /admin/estudio y /admin/estudio/reservas
  // — comparte caché con esas pantallas.
  const estudioQ = useQuery({
    queryKey: ["admin", "estudio"],
    queryFn: () => estudioAdminApi.get(),
    enabled: p?.tipo === "estudio",
  });

  // Modales
  const [openPagoModal, setOpenPagoModal] = useState(false);
  const [openMailDialog, setOpenMailDialog] = useState(false);
  const [askDelete, setAskDelete] = useState(false);
  const [askCancel, setAskCancel] = useState(false);
  const [askVerif, setAskVerif] = useState(false);
  const [pendingEstado, setPendingEstado] = useState<PedidoEstado | null>(null);
  const [linkVerif, setLinkVerif] = useState<string | null>(null);
  const [generandoLink, setGenerandoLink] = useState(false);
  const [copiadoLink, setCopiadoLink] = useState(false);

  const qc = useQueryClient();
  const deleteMut = useMutation({
    mutationFn: () => adminApi.deletePedido(pedidoId),
    onSuccess: () => {
      toast.success("Pedido eliminado");
      qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
      navigate({ to: "/admin/pedidos" });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (pedidoQ.isError) {
    return (
      <div className="p-6 max-w-2xl mx-auto">
        <BackLink onClick={() => navigate({ to: "/admin/pedidos" })} />
        <div className="mt-4 rounded-md border hairline border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          No se pudo cargar el pedido: {(pedidoQ.error as Error).message}
        </div>
      </div>
    );
  }
  if (pedidoQ.isLoading || !p || !draft.datos || !draft.items) {
    return (
      <div className="p-6 space-y-4 max-w-5xl mx-auto">
        <Skeleton className="h-7 w-64" />
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
          <Skeleton className="h-96 w-full rounded-xl" />
          <Skeleton className="h-96 w-full rounded-xl" />
        </div>
      </div>
    );
  }

  const { datos, setDatos, items, setItems, saveStatus, estadoMut } = draft;
  const ns = nextStep(p);
  const otrosDestinosPedido = otrosDestinos(p);
  // Ítems/fechas de un turno o slot fijo del Estudio están blindados
  // server-side (409, Fase 1 #1283) — `esEstudio` cubre ambos tipos (sigue
  // usándose para eso + el destinatario default de cobranza).
  const esEstudio = esPedidoEstudio(p);
  // Un turno REAL (no un slot fijo) se administra inline con su propia
  // sección `ReservaEstudioSection` (Fase 2, #1308) — reemplaza el banner +
  // controles neutralizados de antes. `estudio_fijo` sigue sin editor
  // inline: su verdad es el slot recurrente, no este pedido.
  const esEstudioReal = p.tipo === "estudio";
  // Un pedido de taller (Fase 1, #1308) también tiene la fecha blindada server-
  // side (409) — pero, a diferencia de estudio, SÍ permite agregar/editar
  // ítems (matrícula), así que solo el control de fecha se neutraliza acá.
  const esTaller = esPedidoTaller(p);
  const fechaNoEditable = esPedidoDerivado(p);

  const clienteSinVerificar = !!p.cliente_id && !p.cliente_dni_validado_at;
  const ESTADOS_CON_AVISO: PedidoEstado[] = ["confirmado", "retirado"];

  const handleNextStep = (target: PedidoEstado) => {
    if (clienteSinVerificar && ESTADOS_CON_AVISO.includes(target)) {
      setPendingEstado(target);
      setAskVerif(true);
    } else {
      estadoMut.mutate(target);
    }
  };

  const handleGenerarLink = async () => {
    if (!p.cliente_id) return;
    setGenerandoLink(true);
    try {
      const r = await adminApi.generarLinkVerificacion(p.cliente_id);
      setLinkVerif(r.url);
    } catch {
      toast.error("No se pudo generar el link de verificación");
    } finally {
      setGenerandoLink(false);
    }
  };

  // Fechas+horas derivadas del draft (vivo). datos.fecha_desde/_hasta vienen
  // como datetime ISO (keepDateTime) o, en pedidos viejos sin hora, date-only
  // → default 09:00. El selector lee de acá y recombina al escribir.
  const { date: startDate, time: startTime } = parseDateTimeParts(datos.fecha_desde);
  const { date: endDate, time: endTime } = parseDateTimeParts(datos.fecha_hasta);

  // Jornadas con el mismo criterio que el carrito (devolver más tarde = +1).
  const jornadas = computeJornadas(startDate, endDate, startTime, endTime);

  // ── Handlers del selector de fechas (modo admin) ──────────────────────
  // Recombinan día+hora a datetime con toLocalISO y persisten vía autosave.
  // Mantienen el clamp fecha_hasta ≥ fecha_desde.
  const handleDatesChange = (start?: Date, end?: Date) => {
    setDatos((d) => {
      if (!d) return d;
      const fecha_desde = start ? toLocalISO(start, startTime) : "";
      let fecha_hasta = end ? toLocalISO(end, endTime) : "";
      if (fecha_desde && fecha_hasta && fecha_hasta < fecha_desde) fecha_hasta = fecha_desde;
      return { ...d, fecha_desde, fecha_hasta };
    });
  };
  const handleStartTimeChange = (t: string) => {
    setDatos((d) => (d && startDate ? { ...d, fecha_desde: toLocalISO(startDate, t) } : d));
  };
  const handleEndTimeChange = (t: string) => {
    setDatos((d) => {
      if (!d || !endDate) return d;
      let fecha_hasta = toLocalISO(endDate, t);
      if (datos.fecha_desde && fecha_hasta < datos.fecha_desde) fecha_hasta = datos.fecha_desde;
      return { ...d, fecha_hasta };
    });
  };

  // Totales vivos desde useCotizacion
  const totales = cotizacionQ.data;
  const total = totales.total;
  const pagadoMonto = p.monto_pagado ?? 0;
  const restante = Math.max(0, total - pagadoMonto);

  // Combinado con los turnos del Estudio vinculados (#1308) — cálculo 100%
  // frontend, cero query nueva (los montos de cada turno ya vienen en la
  // respuesta del pedido). Sin turnos vinculados, es un pass-through exacto
  // de total/pagadoMonto/restante (mismos números, cero cambio visual).
  const turnosVinculados = p.turnos_estudio_vinculados ?? [];
  const combinado = combinarTotales(total, pagadoMonto, turnosVinculados);

  // stockMap: { equipo_id → libres tras TODO el draft } (con signo; negativo =
  // faltan unidades). hasOverstock lo deriva el hook con la misma regla.
  const { stockMap, hasOverstock } = dispo;

  // Las líneas se identifican por `uid` (las personalizadas no tienen equipo_id).
  const updateItem = (uid: string, patch: Partial<DraftItem>) =>
    setItems((its) => (its ?? []).map((it) => (it.uid === uid ? { ...it, ...patch } : it)));

  const removeItem = (uid: string) => setItems((its) => (its ?? []).filter((it) => it.uid !== uid));

  // Agregar equipo del catálogo (desde el buscador inline). Si ya está en el
  // pedido, suma +1; si no, lo agrega como línea nueva. No cierra el buscador
  // → se pueden cargar varios seguidos.
  const handleAddEquipo = (eq: Equipo) => {
    const display = eq.nombre_publico || eq.nombre;
    const existing = items.find((i) => i.equipo_id === eq.id);
    if (existing) {
      updateItem(existing.uid, { cantidad: existing.cantidad + 1 });
      toast.success(`+1 ${display}`);
    } else {
      setItems((its) => [
        ...(its ?? []),
        {
          uid: `e${eq.id}`,
          equipo_id: eq.id,
          cantidad: 1,
          precio_jornada: eq.precio_jornada ?? 0,
          nombre: eq.nombre,
          marca: eq.marca,
          nombre_publico: eq.nombre_publico ?? null,
          foto_url: eq.foto_url ?? null,
          cobro_modo: "jornada",
        },
      ]);
      toast.success(`Agregado: ${display}`);
    }
  };

  // Agregar línea personalizada (#805): ítem de texto libre, fuera del catálogo.
  // Un pedido de taller cubre ~1 mes: defaultear a "jornada" multiplicaría el
  // valor tipeado por ~30 (silencioso y caro) — "fijo" es el default correcto acá.
  const addLineaLibre = () =>
    setItems((its) => [
      ...(its ?? []),
      {
        uid: nuevoUidLinea(),
        equipo_id: null,
        cantidad: 1,
        precio_jornada: 0,
        nombre: "",
        marca: null,
        nombre_libre: "",
        cobro_modo: p.tipo === "taller" ? "fijo" : "jornada",
      },
    ]);

  // Drag-reorder de líneas (#806). El nuevo orden viaja en el array de items;
  // el autosave lo persiste (el backend asigna `orden` por posición). `sensors`
  // es un hook → vive arriba con el resto (declarado antes de los early returns).
  const handleItemsDragEnd = (e: DragEndEvent) => {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    setItems((its) => {
      if (!its) return its;
      const oldIndex = its.findIndex((it) => it.uid === active.id);
      const newIndex = its.findIndex((it) => it.uid === over.id);
      if (oldIndex < 0 || newIndex < 0) return its;
      return arrayMove(its, oldIndex, newIndex);
    });
  };

  const goList = () => navigate({ to: "/admin/pedidos" });

  return (
    <div className="flex flex-col min-h-0">
      {/* Topbar del editor */}
      <header className="flex items-center gap-3 px-4 md:px-6 py-3 border-b hairline bg-surface-elevated">
        <BackLink onClick={goList} />
        <div className="min-w-0 flex items-center gap-2">
          <span className="font-display text-lg text-ink truncate">
            {p.cliente_nombre || "Sin cliente"}
          </span>
          <span className="font-mono text-xs text-muted-foreground">
            #{p.numero_pedido ?? p.id}
          </span>
          <EstadoBadge estado={p.estado} label={ESTADO_LABEL[p.estado]} />
        </div>
        <div className="ml-auto flex items-center gap-2">
          <SaveIndicator status={saveStatus} />
          <WhatsAppButton pedido={p} phone={p.cliente_telefono} variant="icon" />
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-0 lg:gap-0 min-h-0">
        {/* ── Columna de trabajo ── */}
        <div className="min-w-0 px-4 md:px-6 py-5 space-y-5 lg:border-r hairline pb-28 lg:pb-5">
          {/* Banner solicitud pendiente (deferido — solo aviso read-only) */}
          {p.tiene_solicitud_pendiente && (
            <div className="flex items-start gap-2 rounded-lg border border-amber/40 bg-amber/5 px-3 py-2.5 text-sm">
              <Info className="h-4 w-4 text-ink shrink-0 mt-0.5" />
              <div className="min-w-0">
                <span className="font-medium text-ink">Hay una solicitud de cambio pendiente.</span>{" "}
                <Link to="/admin/solicitudes" className="underline text-muted-foreground">
                  Revisarla en Solicitudes
                </Link>
                .
              </div>
            </div>
          )}

          {/* Breadcrumb de vuelta — este turno se creó desde la sección
              "Turnos del Estudio" de otro pedido (#1308). */}
          {p.pedido_principal && (
            <div className="flex items-start gap-2 rounded-lg border hairline bg-muted/20 px-3 py-2.5 text-sm">
              <Info className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
              <div className="min-w-0">
                Turno vinculado al pedido{" "}
                <Link
                  to="/admin/pedidos/$id"
                  params={{ id: String(p.pedido_principal.id) }}
                  className="underline text-ink"
                >
                  #{p.pedido_principal.numero_pedido ?? p.pedido_principal.id}
                </Link>
                {p.pedido_principal.cliente_nombre ? ` (${p.pedido_principal.cliente_nombre})` : ""}
                .
              </div>
            </div>
          )}

          {/* Banner slot fijo del Estudio — su verdad es el slot recurrente,
              no este pedido (que es solo una muestra mensual). A diferencia
              de un turno real, NO tiene editor inline acá. */}
          {esEstudio && !esEstudioReal && (
            <div className="flex items-start gap-2 rounded-lg border border-amber/40 bg-amber/5 px-3 py-2.5 text-sm">
              <Info className="h-4 w-4 text-ink shrink-0 mt-0.5" />
              <div className="min-w-0">
                <span className="font-medium text-ink">
                  Este pedido es un slot fijo del Estudio.
                </span>{" "}
                El horario, la promo y los equipos sueltos los gobierna el slot recurrente en{" "}
                <Link to="/admin/estudio" className="underline text-muted-foreground">
                  Estudio → Slots fijos
                </Link>
                . Acá se maneja el pago, la facturación y el estado.
              </div>
            </div>
          )}

          {/* Reserva del Estudio — franja, tarifa, promo y sueltos de un
              turno real, administrados inline (Fase 2, #1308). Reemplaza el
              viejo banner "andá a Estudio → Reservas": ahora se edita acá. */}
          {esEstudioReal &&
            (estudioQ.data ? (
              <ReservaEstudioSection
                pedido={p}
                estudio={estudioQ.data}
                onSaved={() => qc.invalidateQueries({ queryKey: ["admin", "pedido", pedidoId] })}
              />
            ) : (
              <Skeleton className="h-64 w-full rounded-xl" />
            ))}

          {/* Banner pedido de taller — resumen contable mensual generado por
              la edición (Fase 1, #1308): fechas bloqueadas server-side, pero
              SÍ se puede agregar una línea de matrícula acá. */}
          {esTaller && (
            <div className="flex items-start gap-2 rounded-lg border border-amber/40 bg-amber/5 px-3 py-2.5 text-sm">
              <Info className="h-4 w-4 text-ink shrink-0 mt-0.5" />
              <div className="min-w-0">
                <span className="font-medium text-ink">
                  Este pedido es el resumen mensual de un taller.
                </span>{" "}
                Las fechas y los ítems automáticos (espacio/equipos) los gobierna la edición en{" "}
                <Link to="/admin/talleres" className="underline text-muted-foreground">
                  Talleres
                </Link>
                . Podés agregar una línea nueva acá (ej. matrícula) sin problema.
              </div>
            </div>
          )}

          {/* Cliente */}
          <Section variant="card" tone="elevated" icon={User} title="Cliente">
            {/* Buscar ficha existente: al elegirla, el contacto y el descuento
                se completan solos. También se puede tipear a mano abajo (pedido
                sin ficha vinculada). */}
            {datos.cliente_id ? (
              // Cliente vinculado: tarjeta clara de QUIÉN está seleccionado.
              <div className="mb-3 flex items-center gap-3 rounded-lg border border-verde/30 bg-verde/[0.06] px-3 py-2.5">
                <ClienteAvatar nombre={datos.cliente_nombre} className="h-9 w-9 text-sm" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-medium text-ink">
                      {datos.cliente_nombre || "Cliente sin nombre"}
                    </span>
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 font-mono text-2xs",
                        p.cliente_dni_validado_at
                          ? "bg-verde/10 text-verde-ink"
                          : "bg-amber/15 text-ink",
                      )}
                    >
                      {p.cliente_dni_validado_at ? (
                        <ShieldCheck className="h-3 w-3" />
                      ) : (
                        <ShieldAlert className="h-3 w-3" />
                      )}
                      {p.cliente_dni_validado_at ? "Verificado" : "Sin verificar"}
                    </span>
                  </div>
                  <div className="mt-0.5 truncate font-mono text-xs text-muted-foreground">
                    {[datos.cliente_email, datos.cliente_telefono].filter(Boolean).join(" · ") ||
                      "sin contacto"}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setDatos((d) => d && { ...d, cliente_id: null })}
                  className="shrink-0 rounded-md border hairline px-2.5 py-1 text-xs text-muted-foreground hover:border-ink hover:text-ink"
                >
                  Desvincular
                </button>
              </div>
            ) : (
              // Sin ficha: buscar una, o cargar el contacto a mano abajo. Estos
              // 3 inputs son SOLO para este caso — con ficha vinculada, editarlos
              // acá no servía de nada: el contacto es en vivo (2026-06-06) y la
              // próxima lectura los pisaba en silencio con los datos del cliente.
              <div>
                <ClienteAutocomplete
                  placeholder="Buscar cliente por nombre, email o teléfono…"
                  onPick={(c) =>
                    setDatos((d) =>
                      d
                        ? {
                            ...d,
                            cliente_id: c.id,
                            cliente_nombre: nombreCliente(c),
                            cliente_email: c.email ?? "",
                            cliente_telefono: c.telefono ?? "",
                            // `descuento_pct` (override MANUAL) NO se toca acá
                            // (Fase C-1, #1219) — el descuento del cliente ya
                            // se sigue EN VIVO cuando no hay override (0 =
                            // "sin override"); copiarlo acá creaba un override
                            // fantasma que dejaba de seguir al cliente en vivo.
                          }
                        : d,
                    )
                  }
                />
                <p className="mt-1.5 font-mono text-xs text-muted-foreground">
                  O cargá el contacto a mano abajo (pedido sin ficha vinculada).
                </p>
                <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <FieldLabel>Nombre</FieldLabel>
                    <Input
                      value={datos.cliente_nombre}
                      onChange={(e) =>
                        setDatos((d) => d && { ...d, cliente_nombre: e.target.value })
                      }
                    />
                  </div>
                  <div className="space-y-1">
                    <FieldLabel>Teléfono</FieldLabel>
                    <Input
                      value={datos.cliente_telefono}
                      onChange={(e) =>
                        setDatos((d) => d && { ...d, cliente_telefono: e.target.value })
                      }
                    />
                  </div>
                  <div className="space-y-1 sm:col-span-2">
                    <FieldLabel>Email</FieldLabel>
                    <Input
                      value={datos.cliente_email}
                      placeholder="—"
                      onChange={(e) =>
                        setDatos((d) => d && { ...d, cliente_email: e.target.value })
                      }
                    />
                  </div>
                </div>
              </div>
            )}
          </Section>

          {/* Facturar a nombre de (#1251) — solo si el cliente tiene perfiles
              fiscales personales o productoras vinculadas para elegir. */}
          <FacturacionTargetSection
            clienteId={datos.cliente_id}
            perfilFiscalId={datos.perfil_fiscal_id}
            productoraId={datos.productora_id}
            onChange={({ perfilFiscalId, productoraId }) =>
              setDatos(
                (d) => d && { ...d, perfil_fiscal_id: perfilFiscalId, productora_id: productoraId },
              )
            }
          />

          {/* Fechas — editables con re-validación de stock. Taller (#1308):
              `fecha_desde`/`fecha_hasta` son el mes contable de la edición, no
              un evento real — se muestran las clases reales en su lugar. Un
              turno real del Estudio no repite esta Section: su franja ya se
              edita en `ReservaEstudioSection`, arriba. */}
          {!esEstudioReal && (
            <Section
              variant="card"
              tone="elevated"
              icon={Calendar}
              title={esTaller ? "Clases del taller" : "Fechas del alquiler"}
              actions={
                esTaller ? undefined : !datos.fecha_desde || !datos.fecha_hasta ? (
                  <span className="inline-flex items-center gap-1 font-mono text-2xs uppercase tracking-[0.2em] text-destructive">
                    <AlertTriangle className="h-3 w-3" /> sin fechas
                  </span>
                ) : hasOverstock ? (
                  <span className="inline-flex items-center gap-1 font-mono text-2xs uppercase tracking-[0.2em] text-destructive">
                    <AlertTriangle className="h-3 w-3" /> revisar stock
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 font-mono text-2xs uppercase tracking-[0.2em] text-verde-ink">
                    <Check className="h-3 w-3" /> stock OK
                  </span>
                )
              }
            >
              {esTaller ? (
                (p.clases_taller ?? []).length > 0 ? (
                  <ul className="space-y-2">
                    {(p.clases_taller ?? []).map((c) => (
                      <li
                        key={c.id}
                        className="flex items-center gap-3 rounded-lg border hairline bg-surface-elevated px-3.5 py-2.5 min-h-[44px]"
                      >
                        <Calendar className="h-4 w-4 text-muted-foreground shrink-0" />
                        <div className="min-w-0 flex-1">
                          <div className="font-mono text-sm tabular-nums text-ink">
                            {format(new Date(c.fecha + "T12:00:00"), "EEEE d 'de' MMMM", {
                              locale: es,
                            })}
                          </div>
                          <div className="mt-0.5 text-xs text-muted-foreground">
                            {c.hora_inicio_str}–{c.hora_fin_str}
                            {c.titulo ? ` · ${c.titulo}` : ""}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Sin clases cargadas en la edición todavía —{" "}
                    <Link to="/admin/talleres" className="underline">
                      cargalas en Talleres
                    </Link>
                    .
                  </p>
                )
              ) : (
                /* Píldora retiro→devolución — abre el selector de fechas+horas.
                  Turno del Estudio: se reprograma desde Estudio → Reservas. */
                <button
                  type="button"
                  disabled={fechaNoEditable}
                  onClick={() => setOpenDateModal(true)}
                  className={cn(
                    "@container flex w-full items-center gap-3 rounded-lg border hairline bg-surface-elevated px-3.5 py-2.5 text-left transition min-h-[44px]",
                    fechaNoEditable ? "cursor-not-allowed opacity-60" : "hover:border-ink",
                  )}
                >
                  {startDate && endDate ? (
                    <>
                      <Calendar className="h-4 w-4 text-muted-foreground shrink-0 self-start mt-0.5" />
                      <div className="min-w-0 flex-1 grid grid-cols-1 gap-x-6 gap-y-2 @2xl:grid-cols-2">
                        <div className="min-w-0">
                          <div className="t-eyebrow">Retiro</div>
                          <div className="font-mono text-sm tabular-nums text-ink mt-0.5">
                            {format(startDate, "EEEE d 'de' MMMM", { locale: es })} · {startTime}
                          </div>
                        </div>
                        <div className="min-w-0">
                          <div className="t-eyebrow">Devolución</div>
                          <div className="font-mono text-sm tabular-nums text-ink mt-0.5">
                            {format(endDate, "EEEE d 'de' MMMM", { locale: es })} · {endTime}
                          </div>
                        </div>
                      </div>
                      <span className="ml-auto card px-2.5 py-1 text-center shrink-0">
                        <span className="font-mono text-base font-semibold leading-none">
                          {jornadas}
                        </span>
                        <span className="t-eyebrow ml-1">
                          {jornadas === 1 ? "jornada" : "jornadas"}
                        </span>
                      </span>
                    </>
                  ) : (
                    <>
                      <Calendar className="h-4 w-4 text-muted-foreground shrink-0" />
                      <span className="text-sm text-muted-foreground">
                        Elegí las fechas de retiro y devolución…
                      </span>
                    </>
                  )}
                </button>
              )}
            </Section>
          )}

          {/* Equipos — turno del Estudio: el centinela/promo/sueltos se
              cargan desde Estudio → Reservas (el buscador y la edición por
              línea se neutralizan acá, el backend los rechaza con 409). Un
              turno real ya administra sus sueltos en `ReservaEstudioSection`,
              arriba — no repite esta Section. */}
          {!esEstudioReal && (
            <Section variant="card" tone="elevated" icon={Box} title={`Equipos · ${items.length}`}>
              {/* Buscador inline: resultados en dropdown debajo (no tapa el form) */}
              {!esEstudio && (
                <EquipoComboSearch
                  existing={items}
                  stockMap={stockMap}
                  onAdd={handleAddEquipo}
                  className="mb-2"
                />
              )}

              {items.length === 0 ? (
                <ul className="divide-y hairline">
                  <li className="py-4 text-sm text-muted-foreground">
                    Sin equipos. Agregá al menos uno para confirmar.
                  </li>
                </ul>
              ) : (
                <DndContext
                  sensors={sensors}
                  collisionDetection={closestCenter}
                  onDragEnd={esEstudio ? undefined : handleItemsDragEnd}
                >
                  <SortableContext
                    items={items.map((it) => it.uid)}
                    strategy={verticalListSortingStrategy}
                  >
                    <ul className="divide-y hairline">
                      {items.map((it) => (
                        <ItemRow
                          key={it.uid}
                          it={it}
                          stock={it.equipo_id != null ? stockMap[String(it.equipo_id)] : undefined}
                          jornadas={jornadas}
                          updateItem={esEstudio ? () => {} : updateItem}
                          removeItem={esEstudio ? () => {} : removeItem}
                        />
                      ))}
                    </ul>
                  </SortableContext>
                </DndContext>
              )}

              {/* Agregar línea personalizada (#805): ítem libre fuera del catálogo */}
              {!esEstudio && (
                <button
                  type="button"
                  onClick={addLineaLibre}
                  className="mt-2 flex w-full items-center gap-2.5 px-3 py-2.5 rounded-md border border-dashed hairline text-sm text-muted-foreground hover:bg-muted/30 transition"
                >
                  <Plus className="h-4 w-4 shrink-0" />
                  <span>Agregar línea personalizada (flete, servicio, etc.)</span>
                </button>
              )}
            </Section>
          )}

          {/* Turnos del Estudio vinculados (#1308) — solo para un pedido de
              alquiler normal (un turno/slot/taller no anida otro turno). */}
          {!esPedidoDerivado(p) && <TurnosEstudioSection pedido={p} />}

          {/* Notas */}
          <Section variant="card" tone="elevated" icon={FileText} title="Notas internas">
            <Textarea
              value={datos.notas}
              placeholder="Notas para el equipo de Rambla…"
              onChange={(e) => setDatos((d) => d && { ...d, notas: e.target.value })}
              className="min-h-[88px] resize-y"
            />
          </Section>
        </div>

        {/* ── Rail ── (visible en lg en el lado derecho; en mobile fluye debajo) */}
        <aside className="px-4 md:px-5 py-5 space-y-4 bg-surface/40 lg:border-t-0 border-t hairline pb-28 lg:pb-5">
          {/* Estado */}
          <RailSection label="Estado del pedido">
            <FlowStrip estado={p.estado} />
            <EstadoSplitButton
              ns={ns}
              otrosDestinos={otrosDestinosPedido}
              onSelect={handleNextStep}
              disabled={estadoMut.isPending}
            />
          </RailSection>

          {/* Identidad del cliente (solo cuando tiene ficha vinculada sin verificar) */}
          {clienteSinVerificar && (
            <RailSection label="Identidad del cliente">
              <div className="flex items-center gap-1.5 text-ink text-sm mb-2">
                <ShieldAlert className="h-4 w-4 shrink-0" />
                <span>Sin verificar</span>
              </div>
              {linkVerif ? (
                <div className="space-y-1.5">
                  <p className="text-xs text-muted-foreground">Mandá este link al cliente:</p>
                  <div className="flex items-center gap-2">
                    <Input
                      readOnly
                      value={linkVerif}
                      className="flex-1 font-mono text-xs truncate"
                    />
                    <button
                      type="button"
                      onClick={() => {
                        void navigator.clipboard.writeText(linkVerif);
                        setCopiadoLink(true);
                        setTimeout(() => setCopiadoLink(false), 2000);
                      }}
                      className="flex items-center gap-1 rounded-md border hairline bg-surface px-2.5 py-1.5 text-xs text-ink hover:bg-accent/30 transition-colors shrink-0 h-[30px]"
                    >
                      {copiadoLink ? (
                        <Check className="h-3.5 w-3.5 text-verde-ink" />
                      ) : (
                        <Copy className="h-3.5 w-3.5" />
                      )}
                      {copiadoLink ? "Copiado" : "Copiar"}
                    </button>
                  </div>
                </div>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full"
                  disabled={generandoLink}
                  onClick={() => void handleGenerarLink()}
                >
                  <ShieldCheck className="h-4 w-4 mr-1" />
                  {generandoLink ? "Generando…" : "Generar link de verificación"}
                </Button>
              )}
            </RailSection>
          )}

          {/* Desglose — vivo via useCotizacion */}
          <RailSection label="Desglose">
            <div className="space-y-1 text-sm">
              <BdRow
                // Taller: el rango es el mes contable, no jornadas reales
                // (las clases reales ya se muestran arriba) — "N jornadas"
                // acá sería el mismo tipo de invención que el "31 jornadas"
                // original del pedido #445. Estudio: la franja es horaria
                // (arriba, en `ReservaEstudioSection`) — "N jornadas" tampoco
                // describe un turno de unas pocas horas.
                l={
                  esTaller || esEstudioReal
                    ? "Bruto"
                    : `Bruto · ${jornadas} jornada${jornadas !== 1 ? "s" : ""}`
                }
                v={fmtArs(totales.subtotal)}
              />
              {totales.descuentoPct > 0 && (
                <BdRow
                  l={`${
                    descuentoLabel(totales.descuentoOrigen, jornadas, datos.cliente_nombre) ||
                    "Descuento"
                  } · ${totales.descuentoPct}%`}
                  v={`– ${fmtArs(totales.descuentoMonto)}`}
                  neg
                />
              )}
              <BdRow l="Neto" v={fmtArs(totales.totalNeto)} />
              <BdRow
                l={`IVA ${totales.conIva ? "21%" : ""}`}
                v={totales.conIva ? fmtArs(totales.iva) : "— sin IVA"}
              />
              <div className="border-t hairline my-1" />
              <BdRow
                l={combinado.turnos.length > 0 ? "Total del pedido" : "Total"}
                v={fmtArs(total)}
                strong
              />
              {combinado.turnos.length > 0 && (
                <>
                  {combinado.turnos.map((t) => (
                    <BdRow
                      key={t.id}
                      l={`Turno #${t.numero_pedido ?? t.id}${
                        t.fecha_desde
                          ? ` · ${format(new Date(t.fecha_desde), "d MMM", { locale: es })}`
                          : ""
                      }`}
                      v={fmtArs(t.monto_total)}
                    />
                  ))}
                  <div className="border-t hairline my-1" />
                  <BdRow l="Total combinado" v={fmtArs(combinado.totalCombinado)} strong />
                </>
              )}
            </div>
            {/* Div plano, NO <FieldLabel> (que renderiza un <label> nativo):
                un <label> reenvía cualquier click dentro de su área al PRIMER
                control enfocable de adentro (acá, el botón "%") — clickear
                "cerca" del input $ pero todavía dentro del label revertía el
                selector a "%" solo. Con 2+ controles adentro, un <label> no
                es seguro; FieldLabel sigue bien para los campos de un solo input. */}
            <div className="block mt-3">
              <span className="block t-eyebrow mb-1">Descuento manual (0 = automático)</span>
              <div className="flex items-center gap-2">
                <SegmentedControl
                  value={datos.descuento_manual_tipo}
                  onChange={(v) =>
                    setDatos(
                      (d) =>
                        d && {
                          ...d,
                          descuento_manual_tipo: v as "pct" | "monto",
                          // Convertir al equivalente del OTRO campo (el % y el
                          // $ efectivos que ya muestra el desglose, calculados
                          // por el backend) en vez de resetear a 0 — cambiar
                          // de unidad no debería perder el descuento actual.
                          // El campo que se deja de usar se resetea (sin esto
                          // queda un valor "fantasma" que podía reaparecer si
                          // el admin volvía a tocar el selector).
                          ...(v === "monto"
                            ? { descuento_manual_monto: totales.descuentoMonto, descuento_pct: 0 }
                            : { descuento_pct: totales.descuentoPct, descuento_manual_monto: 0 }),
                        },
                    )
                  }
                  options={[
                    { value: "pct", label: "%" },
                    { value: "monto", label: "$" },
                  ]}
                  className="w-20 shrink-0"
                />
                {datos.descuento_manual_tipo === "monto" ? (
                  <MoneyInput
                    min={0}
                    max={totales.subtotalDescontable}
                    step={100}
                    value={datos.descuento_manual_monto}
                    className="max-w-[140px]"
                    ariaLabel="Descuento $ manual"
                    onChange={(v) => setDatos((d) => d && { ...d, descuento_manual_monto: v })}
                  />
                ) : (
                  <div className="relative max-w-[140px]">
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      step={0.1}
                      value={datos.descuento_pct}
                      className="pr-7"
                      onChange={(e) =>
                        setDatos(
                          (d) =>
                            d && {
                              ...d,
                              descuento_pct: Math.max(
                                0,
                                Math.min(100, Number(e.target.value) || 0),
                              ),
                            },
                        )
                      }
                    />
                    <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
                      %
                    </span>
                  </div>
                )}
              </div>
            </div>
          </RailSection>

          {/* Cobranza — combinada con los turnos del Estudio vinculados
              (#1308): sin turnos, `combinado.*` es un pass-through exacto de
              pagadoMonto/total/restante (cero cambio visual). */}
          <RailSection label="Cobranza">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs text-muted-foreground">
                {fmtArs(combinado.pagadoCombinado)} de {fmtArs(combinado.totalCombinado)}
                {combinado.pagadoCombinado === 0 ? " · sin seña" : ""}
              </span>
              <span
                className={cn(
                  "font-mono text-xs font-semibold",
                  combinado.pagadoCombinado >= combinado.totalCombinado &&
                    combinado.totalCombinado > 0
                    ? "text-verde-ink"
                    : "text-destructive",
                )}
              >
                {combinado.pagadoCombinado >= combinado.totalCombinado &&
                combinado.totalCombinado > 0
                  ? "pagado"
                  : `resta ${fmtArs(combinado.restaCombinado)}`}
              </span>
            </div>
            <div className="mt-1.5 h-1.5 rounded-full bg-muted overflow-hidden">
              <div
                className={cn(
                  "h-full transition-colors",
                  combinado.pagadoCombinado >= combinado.totalCombinado &&
                    combinado.totalCombinado > 0
                    ? "bg-verde"
                    : "bg-amber",
                )}
                style={{
                  width: `${
                    combinado.totalCombinado
                      ? Math.min(100, (combinado.pagadoCombinado / combinado.totalCombinado) * 100)
                      : 0
                  }%`,
                }}
              />
            </div>
            {(p.pagos ?? []).map((pago) => (
              <PagoRow key={pago.id} pago={pago} pedidoId={p.id} />
            ))}
            {!(
              combinado.pagadoCombinado >= combinado.totalCombinado && combinado.totalCombinado > 0
            ) && (
              <Button
                variant="outline"
                size="sm"
                className="w-full mt-2"
                disabled={p.estado === "cancelado"}
                onClick={() => setOpenPagoModal(true)}
              >
                <Coins className="h-4 w-4 mr-1" /> Registrar pago
              </Button>
            )}
          </RailSection>

          {/* Documentos */}
          <RailSection label="Documentos">
            <div className="flex flex-wrap gap-1.5">
              {DOCS_PEDIDO.map((doc) => (
                <div key={doc.kind} className="flex items-center gap-0.5">
                  <a
                    href={`${pedidoPdfUrl(p.id, doc.kind)}?format=html`}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 rounded-md border hairline px-2 py-1 font-mono text-xs text-muted-foreground hover:text-ink hover:border-ink"
                    title={`Ver ${doc.label}`}
                  >
                    <Eye className="h-3 w-3" />
                    {doc.label}
                  </a>
                  <a
                    href={pedidoPdfUrl(p.id, doc.kind)}
                    className="inline-flex items-center justify-center h-7 w-7 rounded-md border hairline text-muted-foreground hover:text-ink hover:border-ink"
                    title={`Descargar ${doc.label} PDF`}
                  >
                    <Download className="h-3 w-3" />
                  </a>
                </div>
              ))}
            </div>
            <Button
              variant="outline"
              size="sm"
              className="w-full mt-2"
              onClick={() => setOpenMailDialog(true)}
            >
              <Mail className="h-4 w-4 mr-1" /> Enviar por mail
            </Button>
          </RailSection>

          {/* Factura ARCA */}
          <FacturacionRailSection pedidoId={p.id} estadoPedido={p.estado} />

          {/* Eliminar pedido */}
          <RailSection label="Zona peligrosa">
            {transiciones(p.estado).includes("cancelado") && (
              <Button
                variant="outline"
                size="sm"
                className="w-full border-destructive/30 text-destructive hover:bg-destructive/10 hover:text-destructive"
                disabled={estadoMut.isPending}
                onClick={() => setAskCancel(true)}
              >
                <X className="h-4 w-4 mr-1" /> Cancelar pedido
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              className="w-full border-destructive/30 text-destructive hover:bg-destructive/10 hover:text-destructive"
              onClick={() => setAskDelete(true)}
            >
              <Trash2 className="h-4 w-4 mr-1" /> Eliminar pedido
            </Button>
          </RailSection>
        </aside>
      </div>

      {/* Barra inferior sticky (mobile) */}
      <div className="lg:hidden fixed bottom-0 inset-x-0 z-40 flex items-center gap-2 px-4 py-2.5 border-t hairline bg-surface-elevated safe-b">
        <div>
          <div className="t-eyebrow">Total</div>
          <div className="font-mono text-base font-semibold tabular-nums">{fmtArs(total)}</div>
        </div>
        <SaveIndicator status={saveStatus} />
        <div className="ml-auto flex items-center gap-2">
          <WhatsAppButton pedido={p} phone={p.cliente_telefono} variant="icon" />
          {ns && (
            <Button
              variant={ns.blocked ? "outline" : "amber"}
              size="sm"
              disabled={!!ns.blocked || estadoMut.isPending}
              onClick={() => !ns.blocked && handleNextStep(ns.target)}
            >
              {ns.blocked ?? ns.label}
            </Button>
          )}
        </div>
      </div>

      {/* Modales */}
      <DateRangePickerModal
        open={openDateModal}
        onOpenChange={setOpenDateModal}
        startDate={startDate}
        endDate={endDate}
        startTime={startTime}
        endTime={endTime}
        onDatesChange={handleDatesChange}
        onStartTimeChange={handleStartTimeChange}
        onEndTimeChange={handleEndTimeChange}
        options={{ allowPast: true, respectHorarios: false }}
      />
      <RegistrarPagoModal
        pedidoId={p.id}
        total={total}
        pagado={pagadoMonto}
        open={openPagoModal}
        onOpenChange={setOpenPagoModal}
        esEstudio={esEstudio}
        turnosVinculados={turnosVinculados}
      />
      <EnviarDocsDialog
        pedidoId={p.id}
        clienteEmail={p.cliente_email ?? ""}
        open={openMailDialog}
        onOpenChange={setOpenMailDialog}
      />
      <AlertDialog open={askVerif} onOpenChange={setAskVerif}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-ink shrink-0" />
              Cliente sin identidad verificada
            </AlertDialogTitle>
            <AlertDialogDescription>
              {p.cliente_nombre} no verificó su identidad (DNI + selfie). Podés generar un link de
              verificación para mandárselo, o continuar de todas formas.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingEstado) estadoMut.mutate(pendingEstado);
                setAskVerif(false);
                setPendingEstado(null);
              }}
            >
              {pendingEstado === "confirmado"
                ? "Confirmar de todas formas"
                : "Continuar de todas formas"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={askCancel} onOpenChange={setAskCancel}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancelar pedido #{p.numero_pedido ?? p.id}</AlertDialogTitle>
            <AlertDialogDescription>
              El pedido pasa a estado <strong>Cancelado</strong> y libera el stock reservado. Queda
              en el historial (no se borra). Podés volver a eliminarlo definitivamente si hace
              falta.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Volver</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                estadoMut.mutate("cancelado");
                setAskCancel(false);
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Cancelar pedido
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={askDelete} onOpenChange={setAskDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Eliminar pedido #{p.numero_pedido ?? p.id}</AlertDialogTitle>
            <AlertDialogDescription>
              Se borran también sus ítems y pagos. No se puede deshacer.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteMut.mutate()}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Eliminar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function FlowStrip({ estado }: { estado: PedidoEstado }) {
  if (estado === "cancelado") {
    return (
      <div className="flex items-center">
        <span className="inline-flex items-center rounded-full border border-destructive/30 bg-destructive/10 px-2 py-0.5 text-2xs font-semibold text-destructive">
          Cancelado
        </span>
      </div>
    );
  }
  const idx = FLOW.indexOf(estado);
  // Breadcrumb del ciclo de vida: colorea el camino recorrido con la paleta de
  // marca (cada etapa su color), destaca la actual en pill, deja tenues las que
  // faltan. El color sale de la fuente única `estado-color.ts`.
  return (
    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs">
      {FLOW.map((e, i) => (
        <span key={e} className="inline-flex items-center gap-x-1.5">
          {i === idx ? (
            <span
              className={cn(
                "inline-flex items-center rounded-full border px-2 py-0.5 text-2xs font-semibold",
                estadoClase(e),
              )}
            >
              {ESTADO_LABEL[e]}
            </span>
          ) : (
            <span
              className={cn("font-medium", i < idx ? ESTADO_TEXT[e] : "text-muted-foreground/50")}
            >
              {ESTADO_LABEL[e]}
            </span>
          )}
          {i < FLOW.length - 1 && <span className="text-muted-foreground/40">›</span>}
        </span>
      ))}
    </div>
  );
}
