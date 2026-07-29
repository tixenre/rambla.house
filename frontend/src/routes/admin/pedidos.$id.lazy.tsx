import {
  createLazyFileRoute,
  Navigate,
  useNavigate,
  useParams,
  Link,
} from "@tanstack/react-router";
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
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { fmtArs } from "@/lib/format";
import { nombreCliente } from "@/lib/cliente-nombre";
import { EquipoComboSearch } from "@/components/admin/pedido/EquipoComboSearch";
import { EnviarDocsDialog, DOCS_PEDIDO } from "@/components/admin/pedido/EnviarDocsDialog";
import { RegistrarPagoModal } from "@/components/admin/pedido/RegistrarPagoModal";
import { FLOW, transiciones, nextStep, otrosDestinos, etiquetaPedido } from "@/lib/pedido-estados";
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
import { DescuentoControl } from "@/components/admin/pedido/DescuentoControl";
import { TotalSeccion } from "@/components/admin/pedido/TotalSeccion";

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
    // SIEMPRE el id del pedido — quién decide qué hacer con él es el backend.
    // Para el descuento su criterio no cambió: con plata congelada
    // (no-presupuesto) lo saca del snapshot del pedido; en `solicitado` lo
    // ignora y sigue al cliente en vivo (`pedido_congelado = None`), que es
    // exactamente lo mismo que pasaba cuando el front mandaba `null`.
    // Lo que sí necesita el id siempre es el TOTAL COMBINADO con los turnos
    // del Estudio: un pedido en `solicitado` también puede tener turnos, y
    // ocultándole el id el rail se quedaba sin `combinado` → mostraba
    // "Neto $0 / IVA $0" y un total que no incluía el IVA del turno (bug real,
    // visto en el navegador con el pedido #424).
    pedidoId,
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

  // Un turno del Estudio vinculado NO tiene página propia (#1308, "no quiero
  // dobles pedidos fantasmas"): es la misma venta que su pedido principal y se
  // administra desde ahí, en la sección "Turnos del Estudio". Los links viejos
  // (feed iCal, historiales, un tab guardado) aterrizan igual — en el pedido
  // real. Sin loop posible: un principal nunca es turno de otro
  // (`_resolver_pedido_principal` exige `tipo='diaria'`).
  if (p.pedido_principal) {
    return (
      <Navigate to="/admin/pedidos/$id" params={{ id: String(p.pedido_principal.id) }} replace />
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

  // Combinado con los turnos del Estudio vinculados (#1308). Lo COBRADO se
  // suma acá (son montos ya cobrados, no una regla de plata); el TOTAL viene
  // resuelto del backend (`totales.combinado`), que aplica el IVA sobre el neto
  // de las dos partes — sumar el total del principal (con IVA) a los turnos
  // (netos) daba menos de lo que factura el comprobante. Sin turnos vinculados,
  // `combinado` es `null` y todo esto es un pass-through exacto de
  // total/pagadoMonto/restante (mismos números, cero cambio visual).
  const turnosVinculados = p.turnos_estudio_vinculados ?? [];
  const combinado = combinarTotales(total, pagadoMonto, turnosVinculados, totales.combinado?.total);
  /** ¿El resumen se lee en dos partes? Sale de la lista de turnos del pedido
   *  (estable, viene con el payload) y no de `totales.combinado` (que llega
   *  con la cotización) — si no, el rail arrancaría en una parte y saltaría a
   *  dos en cuanto contestara el backend. */
  const hayTurnos = turnosVinculados.length > 0;
  /** Neto e IVA del RESUMEN: los del combinado cuando hay turnos, los del
   *  pedido solo cuando no. Los dos salen del backend — el front nunca aplica
   *  el 21% (MEMORIA 2026-06-29). */
  const netoResumen = hayTurnos ? (totales.combinado?.totalNeto ?? 0) : totales.totalNeto;
  const ivaResumen = hayTurnos ? (totales.combinado?.iva ?? 0) : totales.iva;

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
          <span className="font-mono text-xs text-muted-foreground">{etiquetaPedido(p)}</span>
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

          {/* (El breadcrumb "Turno vinculado al pedido #N" se retiró: un turno
              vinculado ya no llega hasta acá — redirige a su principal, arriba.) */}

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
            ) : null}

            {/* Verificación de identidad: la ACCIÓN, pegada al badge "Sin
                verificar" de la tarjeta de arriba. Vivía en su propio bloque
                del rail ("Identidad del cliente") que repetía ese mismo estado
                a dos columnas de distancia (el dueño: "esto me parece
                redundante, le sacaría lo de la identidad a la columna de la
                derecha"). El estado se lee UNA vez, en la tarjeta; acá queda
                solo lo que la tarjeta no tenía: generar/copiar el link. */}
            {clienteSinVerificar &&
              (linkVerif ? (
                <div className="mb-3 space-y-1.5">
                  <p className="text-xs text-muted-foreground">Mandá este link al cliente:</p>
                  <div className="flex items-center gap-2">
                    <Input
                      readOnly
                      value={linkVerif}
                      aria-label="Link de verificación de identidad"
                      className="flex-1 truncate font-mono text-xs"
                    />
                    <button
                      type="button"
                      onClick={() => {
                        void navigator.clipboard.writeText(linkVerif);
                        setCopiadoLink(true);
                        setTimeout(() => setCopiadoLink(false), 2000);
                      }}
                      className="flex h-9 shrink-0 items-center gap-1 rounded-md border hairline bg-surface px-2.5 text-xs text-ink transition-colors hover:bg-accent/30"
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
                  className="mb-3"
                  disabled={generandoLink}
                  onClick={() => void handleGenerarLink()}
                >
                  <ShieldCheck className="mr-1 h-4 w-4" />
                  {generandoLink ? "Generando…" : "Generar link de verificación"}
                </Button>
              ))}

            {!datos.cliente_id && (
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

          {/* Alquiler = fechas + equipos en UNA sola sección (#1308, pedido del
              dueño: "¿podemos unir lo del rango de fechas y los equipos? que
              esté la sección del rental y la sección del Estudio"). Las dos
              eran cards separadas aunque describen lo mismo: qué se alquila y
              cuándo. Queda hermanada con "Turnos del Estudio", que tiene la
              misma forma — banda de tiempo arriba, lista de qué incluye abajo.
              Taller (#1308): `fecha_desde`/`fecha_hasta` son el mes contable de
              la edición, no un evento real — se muestran las clases reales en
              su lugar. Un turno real del Estudio no repite esta Section: su
              franja y sus ítems ya se editan en `ReservaEstudioSection`. */}
          {!esEstudioReal && (
            <Section
              variant="card"
              tone="elevated"
              icon={Box}
              // "Alquiler de equipos" y no "Alquiler" a secas: es el nombre del
              // área (el mismo que usa el menú público) y hace pareja con
              // "Turnos del Estudio" — las dos secciones dicen QUÉ son, no una
              // el qué y la otra el cuándo.
              title={esTaller ? "Taller" : "Alquiler de equipos"}
              contentClassName="space-y-3"
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

              {/* Equipos — turno del Estudio: el centinela/promo/sueltos se
                  cargan desde Estudio → Reservas (el buscador y la edición por
                  línea se neutralizan acá, el backend los rechaza con 409). El
                  rótulo espeja al "Qué incluye este turno" del Estudio: banda de
                  tiempo arriba, qué incluye abajo. */}
              <div className="t-eyebrow pt-1">Equipos · {items.length}</div>

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

              {/* Descuento DEL ALQUILER, acá adentro y no en el rail (pedido del
                  dueño: "los descuentos creo que deberían ser por sección
                  también, ¿podemos hacer que los descuentos estén en la
                  sección?"). Es el descuento de los equipos: el turno del
                  Estudio tiene el suyo, en su propia sección. Taller: no lleva
                  descuento (2026-07-28 — el de jornadas/cliente no le aplica),
                  así que ni se ofrece. */}
              {!esTaller && !esEstudio && (
                // `border-t-2 border-ink/15`, no `border-t hairline`: separa
                // "qué se alquila" (equipos, línea personalizada) de "la
                // parte contable" (descuento + total) — el dueño la vio muy
                // fina ("¿podemos hacer una línea horizontal más ancha para
                // separar los equipos de la parte contable?"). Mismo patrón
                // ya usado para el mismo tipo de corte en
                // `contabilidad.reporte.lazy.tsx`, no uno nuevo.
                <div className="border-t-2 border-ink/35 pt-4">
                  {/* Total del ÁREA, acá y no solo en el rail (pedido del
                      dueño: "¿podemos poner un total por área, con los
                      descuentos y demás?"). El desglose de cómo se llega al
                      número vive en la sección que lo genera; el rail resume
                      las dos áreas. Misma pieza que usa el turno del Estudio
                      → las dos secciones cierran igual. La primera fila dice
                      "Subtotal" a secas: el sufijo "· N jornadas" que tenía
                      repetía la píldora "N JORNADAS" de la banda
                      Retiro/Devolución de arriba (el dueño: "el 1 jornada me
                      parece redundante").
                      El `DescuentoControl` va COMO PROP, dentro de la fila
                      "Descuento" — antes era un bloque suelto arriba del
                      ledger, o sea el control y su resultado separados
                      diciendo lo mismo ("¿podemos unificar esos dos campos?
                      ... y el modificador de descuento, in place"). */}
                  <TotalSeccion
                    bruto={totales.subtotal}
                    descuentoLabel={
                      descuentoLabel(totales.descuentoOrigen, jornadas, datos.cliente_nombre) ||
                      "Descuento"
                    }
                    descuentoPct={totales.descuentoPct}
                    descuentoMonto={totales.descuentoMonto}
                    total={totales.totalNeto}
                    descuentoControl={
                      <DescuentoControl
                        value={{
                          tipo: datos.descuento_manual_tipo,
                          pct: datos.descuento_pct,
                          monto: datos.descuento_manual_monto,
                        }}
                        onChange={(next) =>
                          setDatos(
                            (d) =>
                              d && {
                                ...d,
                                descuento_manual_tipo: next.tipo,
                                descuento_pct: next.pct,
                                descuento_manual_monto: next.monto,
                              },
                          )
                        }
                        maxMonto={totales.subtotalDescontable}
                        efectivoPct={totales.descuentoPct}
                        efectivoMonto={totales.descuentoMonto}
                      />
                    }
                  />
                </div>
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

          {/* Desglose — vivo via useCotizacion. Con turnos del Estudio
              vinculados se lee en DOS PARTES (pedido del dueño: "ordenaría
              mejor este resumen, con dos partes como el alquiler de equipos y
              turnos, y un solo total con IVA"): cada parte con su propio neto,
              y abajo un único Neto → IVA → Total de las dos juntas. El IVA
              combinado lo resuelve el backend (`totales.combinado`), nunca el
              front. Sin turnos, `combinado` es null y el bloque queda como
              siempre: bruto → descuento → neto → IVA → total. */}
          {/* UN SOLO BLOQUE de plata: desglose → cobranza → factura (pedido
              del dueño: "¿podemos unir visualmente estas dos cosas? Que esté
              el desglose, registrar pago y facturar como un bloque más
              coherente entre sí"). Antes eran 3 `RailSection` de primer nivel,
              cada una con su línea dura arriba, así que la plata del pedido se
              leía como tres temas distintos. Ahora es una sola sección con
              sub-partes separadas por un borde suave. */}
          <RailSection label="Plata del pedido">
            <div className="space-y-1 text-sm">
              {/* RESUMEN, no desglose: los dos montos por área, el total, y el
                  IVA solo si aplica (pedido del dueño: "en el resumen de la
                  derecha, los dos montos discriminados, un total, y el + IVA
                  si es necesario"). El bruto/descuento de cada área ya se ven
                  dentro de SU sección (`TotalSeccion`) — repetirlos acá era
                  escribir el mismo desglose dos veces, y además obligaba a
                  inventar un label de jornadas para un taller o un turno, cuyo
                  rango de fechas no son jornadas reales. */}
              <BdRow
                l={esTaller ? "Taller" : "Alquiler de equipos"}
                v={fmtArs(totales.totalNeto)}
              />
              {/* "Estudio" a secas, sin fecha/hora: la franja exacta YA se ve
                  en la sección "Turnos del Estudio" de arriba — repetirla acá
                  era el mismo dato dos veces (el dueño: "ese detalle de fecha
                  y hora me parece redundante"). Con más de un turno vinculado
                  se numeran (no hay otro identificador liviano y comparable al
                  de "Alquiler de equipos" de la fila de arriba). */}
              {hayTurnos &&
                combinado.turnos.map((t, i) => (
                  <BdRow
                    key={t.id}
                    l={combinado.turnos.length > 1 ? `Estudio ${i + 1}` : "Estudio"}
                    v={fmtArs(t.monto_total)}
                  />
                ))}

              <div className="border-t hairline my-1" />
              {/* Con IVA se muestra el neto para que el total se explique
                  (neto + IVA = total); sin IVA, neto y total son el mismo
                  número y va una sola línea. */}
              {totales.conIva && (
                <>
                  <BdRow l="Neto" v={fmtArs(netoResumen)} />
                  <BdRow l="IVA 21%" v={fmtArs(ivaResumen)} />
                </>
              )}
              <BdRow l="Total" v={fmtArs(combinado.totalCombinado)} strong />
            </div>

            {/* Cobranza — combinada con los turnos del Estudio vinculados
                (#1308): sin turnos, `combinado.*` es un pass-through exacto de
                pagadoMonto/total/restante (cero cambio visual). */}
            <div className="border-t hairline pt-3">
              <RailSection label="Cobranza" anidada>
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
                          ? Math.min(
                              100,
                              (combinado.pagadoCombinado / combinado.totalCombinado) * 100,
                            )
                          : 0
                      }%`,
                    }}
                  />
                </div>
                {(p.pagos ?? []).map((pago) => (
                  <PagoRow key={pago.id} pago={pago} pedidoId={p.id} />
                ))}
                {!(
                  combinado.pagadoCombinado >= combinado.totalCombinado &&
                  combinado.totalCombinado > 0
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
            </div>

            <div className="border-t hairline pt-3">
              <FacturacionRailSection pedidoId={p.id} estadoPedido={p.estado} />
            </div>
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
          {/* `combinado.totalCombinado`, no `total`: en mobile esta barra ES el
              total del pedido (el rail no se ve), así que tiene que incluir los
              turnos del Estudio igual que él. Con `total` mostraba solo la
              parte de equipos — un pedido de $337.590 se anunciaba como
              $185.130 justo arriba del botón de confirmar. Sin turnos los dos
              valores son idénticos. */}
          <div className="font-mono text-base font-semibold tabular-nums">
            {fmtArs(combinado.totalCombinado)}
          </div>
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
            <AlertDialogTitle>Cancelar {etiquetaPedido(p)}</AlertDialogTitle>
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
