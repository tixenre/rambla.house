import { createLazyFileRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  PanelLeft,
  Pencil,
  Coins,
  Mail,
  ArrowRight,
  Trash2,
  ShieldAlert,
  X,
  Clapperboard,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

import { Button } from "@/design-system/ui/button";
import { AdminPage } from "@/components/admin/AdminPage";
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
import { SearchInput } from "@/design-system/ui/search-input";
import { Skeleton } from "@/design-system/ui/skeleton";
import { CountBadge } from "@/design-system/ui/count-badge";
import { adminApi, ESTADO_LABEL, type Pedido } from "@/lib/admin/api";
import { etiquetaPedido, nextStep, type EstadoPedido } from "@/lib/pedido-estados";
import { esPedidoEstudio } from "@/lib/tipos-pedido";
import { EquipoThumb } from "@/components/admin/pedido/EquipoThumb";
import { EstadoBadge } from "@/design-system/ui/EstadoBadge";
import { PagoBadge } from "@/design-system/ui/PagoBadge";
import { PagoFacturaBadge } from "@/design-system/ui/PagoFacturaBadge";
import { WhatsAppButton } from "@/components/admin/WhatsAppButton";
import { ClienteAvatar } from "@/design-system/ui/ClienteAvatar";
import { RegistrarPagoModal } from "@/components/admin/pedido/RegistrarPagoModal";
import { EnviarDocsDialog } from "@/components/admin/pedido/EnviarDocsDialog";
import { FacturaPreviewDialog, FacturarButton } from "@/components/admin/pedido/PedidoPageHelpers";
import { useFacturacionArca } from "@/components/admin/pedido/useFacturacionArca";
import { AdminCard, FAB } from "@/components/mobile";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { formatARS, formatFechaCorta, fmtArs } from "@/lib/format";

export const Route = createLazyFileRoute("/admin/pedidos/")({
  component: PedidosPage,
});

// ── Helpers de fecha / cobranza ──────────────────────────────────────────────

const todayYmd = () => new Date().toISOString().slice(0, 10);
const esHoy = (s: string | null) => !!s && s.slice(0, 10) === todayYmd();

const DIAS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
/** "lun 1 jun 10:00" — día de semana + fecha corta + hora si está presente. */
function fechaDia(s: string | null): string {
  if (!s) return "—";
  const d = new Date(s.slice(0, 10) + "T12:00:00");
  const base = `${DIAS[d.getDay()]} ${formatFechaCorta(s)}`;
  const tIdx = s.indexOf("T");
  if (tIdx !== -1) {
    const hora = s.slice(tIdx + 1, tIdx + 6);
    if (hora && hora !== "00:00") return `${base} ${hora}`;
  }
  return base;
}

/** "creado hace 2 h" — relativo simple desde created_at. */
function creadoHace(iso?: string): string | null {
  if (!iso) return null;
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return null;
  const h = Math.floor(diff / 3_600_000);
  if (h < 1) return "recién";
  if (h < 24) return `hace ${h} h`;
  const d = Math.floor(h / 24);
  return `hace ${d} d`;
}

/** Cuántos turnos del Estudio tiene vinculados este pedido (#1308) — el
 *  turno en sí ya no aparece como fila propia en esta lista, esta señal
 *  es para no perderlo de vista. */
function TurnosVinculadosTag({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span
      className="inline-flex items-center gap-0.5"
      title={`${count} turno(s) del Estudio vinculado(s)`}
    >
      <Clapperboard className="h-3 w-3 text-muted-foreground" />
      <CountBadge count={count} size="sm" />
    </span>
  );
}

const saldoDe = (p: Pedido) => Math.max(0, (p.monto_total ?? 0) - (p.monto_pagado ?? 0));
// Pagado completo: mismo criterio que el "Pagado" de PagoBadge (pagado ≥ total > 0).
const estaPagado = (p: Pedido) => (p.monto_total ?? 0) > 0 && saldoDe(p) === 0;
const tieneSaldo = (p: Pedido) => !["borrador", "cancelado"].includes(p.estado) && saldoDe(p) > 0;

/** Origen del pedido → etiqueta legible (en vez del slug crudo "sistema"/"booqable-historico"/etc.). */
function fuenteLabel(fuente: string | null): string | null {
  if (!fuente) return null;
  // Cualquier importado histórico (ej. "booqable-historico") → "histórico".
  if (fuente.includes("historico") || fuente.includes("booqable")) return "histórico";
  const map: Record<string, string> = {
    sistema: "back-office",
    estudio: "Estudio",
    portal: "portal del cliente",
  };
  return map[fuente] ?? fuente;
}

type EstadoFilter = "activos" | "solicitado" | "confirmado" | "cerrados" | "todos";
const ESTADO_FILTERS: { id: EstadoFilter; label: string }[] = [
  { id: "activos", label: "Activos" },
  { id: "solicitado", label: "Solicitados" },
  { id: "confirmado", label: "Confirmados" },
  { id: "cerrados", label: "Cerrados" },
  { id: "todos", label: "Todos" },
];

/** Filtro de "atajo" del día — llega por deep-link (?f=) desde el Dashboard, no como chip visible. */
type DayFilter = "retiraHoy" | "devuelveHoy" | "nuevos" | "saldo";
const DAY_FILTER_LABEL: Record<DayFilter, string> = {
  retiraHoy: "Retiran hoy",
  devuelveHoy: "Devuelven hoy",
  nuevos: "Solicitudes nuevas",
  saldo: "Con saldo",
};
const matchesDayFilter = (p: Pedido, f: DayFilter): boolean => {
  if (f === "retiraHoy") return esHoy(p.fecha_desde) && p.estado === "confirmado";
  if (f === "devuelveHoy") return esHoy(p.fecha_hasta) && p.estado === "retirado";
  if (f === "nuevos") return p.estado === "solicitado";
  return tieneSaldo(p);
};

// ── Página ───────────────────────────────────────────────────────────────────

function PedidosPage() {
  useDocumentTitle("Pedidos · Back Office");
  const navigate = useNavigate();
  // Deep-link ?f= (atajos del día desde el Dashboard). strict:false → search laxo.
  const search = useSearch({ strict: false }) as { f?: string };
  const dayFilter: DayFilter | null =
    search.f && search.f in DAY_FILTER_LABEL ? (search.f as DayFilter) : null;

  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [estadoF, setEstadoF] = useState<EstadoFilter>("todos");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const [askDelete, setAskDelete] = useState(false);
  const qc = useQueryClient();

  // Lista de pedidos (per_page alto cubre el volumen real).
  const pedidosQ = useQuery({
    queryKey: ["admin", "pedidos", { q: debouncedQ }],
    queryFn: () => adminApi.listPedidos({ q: debouncedQ || undefined, per_page: 200 }),
    refetchInterval: 60_000,
    staleTime: 0,
  });

  const solicitudesQ = useQuery({
    queryKey: ["admin", "solicitudes", "count"],
    queryFn: () => adminApi.listPedidos({ estado: "solicitado", per_page: 1 }),
  });
  const pendientes = solicitudesQ.data?.total ?? 0;

  const raw = useMemo(() => pedidosQ.data?.items ?? [], [pedidosQ.data]);

  // Conteo de activos para el chip de estado.
  // El badge de "Activos" cuenta PEDIDOS reales: un borrador es un presupuesto
  // rápido, no una venta activa (sigue listándose dentro de la pestaña, pero no
  // infla el número que el admin lee de un vistazo).
  const activosCount = useMemo(
    () =>
      raw.filter(
        (p) => p.estado !== "finalizado" && p.estado !== "cancelado" && p.estado !== "borrador",
      ).length,
    [raw],
  );

  // Filtros: si llega un atajo del día (?f=) define la lista; si no, manda el chip de estado.
  const items = useMemo(() => {
    if (dayFilter) return raw.filter((p) => matchesDayFilter(p, dayFilter));
    if (estadoF === "activos")
      return raw.filter((p) => p.estado !== "finalizado" && p.estado !== "cancelado");
    if (estadoF === "cerrados")
      return raw.filter((p) => p.estado === "finalizado" || p.estado === "cancelado");
    if (estadoF === "solicitado") return raw.filter((p) => p.estado === "solicitado");
    if (estadoF === "confirmado") return raw.filter((p) => p.estado === "confirmado");
    return raw;
  }, [raw, dayFilter, estadoF]);

  // Selección: la primera de la lista si no hay ninguna válida.
  const selId =
    selectedId != null && items.some((p) => p.id === selectedId)
      ? selectedId
      : (items[0]?.id ?? null);
  const total = pedidosQ.data?.total ?? 0;
  // Los borradores se listan igual, pero NO son ventas: son presupuestos
  // rápidos. El "N pedidos" del header cuenta solo lo real y los nombra aparte,
  // para que un par de borradores sueltos no inflen el número del negocio.
  const borradores = pedidosQ.data?.borradores ?? 0;
  const totalReales = Math.max(0, total - borradores);
  const resumenConteo = borradores
    ? `${totalReales} en total · ${borradores} borrador${borradores === 1 ? "" : "es"}.`
    : `${totalReales} en total.`;
  // Los que se ven AHORA (después del filtro de pestaña/día) — el contador de
  // la barra del listado cuenta filas visibles, no el universo del filtro.
  const borradoresVisibles = items.filter((p) => p.estado === "borrador").length;

  const openEditor = (id: number) =>
    navigate({ to: "/admin/pedidos/$id", params: { id: String(id) } });

  // Borrar el pedido seleccionado (la acción vive arriba de la lista, no en el panel).
  const selPedido = items.find((p) => p.id === selId) ?? null;
  const deleteMut = useMutation({
    mutationFn: () => adminApi.deletePedido(selId as number),
    onSuccess: () => {
      toast.success("Pedido eliminado");
      qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
      setSelectedId(null);
      setAskDelete(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <AdminPage
      layout="fullHeight"
      title="Pedidos"
      description={
        <>
          Reservas activas y solicitudes de cambio de tus clientes.{" "}
          {pedidosQ.isLoading ? "Cargando…" : resumenConteo}
        </>
      }
      actions={
        <div className="hidden md:flex md:flex-wrap items-center gap-2">
          <Button
            variant="outline"
            onClick={() => navigate({ to: "/admin/solicitudes" })}
            className="relative"
          >
            <Pencil className="h-4 w-4 mr-1" /> Solicitudes
            {pendientes > 0 && (
              <span className="ml-1.5 inline-flex min-w-[18px] items-center justify-center rounded-full bg-amber px-1.5 font-mono text-2xs font-bold text-ink">
                {pendientes}
              </span>
            )}
          </Button>
          <Button onClick={() => navigate({ to: "/admin/pedidos/nuevo" })}>
            <Plus className="h-4 w-4 mr-1" /> Nuevo pedido
          </Button>
        </div>
      }
      className="flex flex-col"
    >
      {/* Búsqueda + chips de estado */}
      <div className="px-4 md:px-6 pb-2 md:pb-3 shrink-0">
        <div className="flex flex-col md:flex-row md:items-center gap-2">
          <SearchInput
            value={q}
            onValueChange={setQ}
            debounceMs={300}
            onDebouncedChange={setDebouncedQ}
            placeholder="Buscar cliente o número…"
            wrapperClassName="md:max-w-sm flex-1"
          />
          {dayFilter ? (
            // Atajo del día activo (vino del Dashboard) — mostrar y permitir limpiar.
            <button
              type="button"
              onClick={() => navigate({ to: "/admin/pedidos" })}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-ink bg-ink px-3 py-1 text-xs font-semibold text-amber md:ml-auto"
            >
              {DAY_FILTER_LABEL[dayFilter]}
              <X className="h-3 w-3" />
            </button>
          ) : (
            <div className="flex items-center gap-1 overflow-x-auto pb-0.5 md:flex-wrap md:gap-1.5 md:ml-auto">
              {ESTADO_FILTERS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setEstadoF(f.id)}
                  className={cn(
                    "inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold transition-colors",
                    estadoF === f.id
                      ? "bg-ink text-amber border-ink"
                      : "border-hairline text-muted-foreground hover:text-ink hover:border-ink",
                  )}
                >
                  {f.label}
                  {f.id === "activos" && (
                    <span className="font-mono text-2xs tabular-nums">{activosCount}</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Split master / detail (desktop) */}
      <div className="flex-1 min-h-0 hidden md:flex border-t hairline">
        <div
          className={cn(
            "shrink-0 flex flex-col min-h-0 border-r hairline",
            panelOpen ? "w-[360px]" : "flex-1",
          )}
        >
          {/* Barra del listado: contador + acciones (eliminar el seleccionado · ancho del panel) */}
          <div className="flex items-center gap-1 px-3 py-2 border-b hairline bg-surface-elevated shrink-0">
            <span className="t-eyebrow">
              {/* Mismo criterio que el header: los borradores se listan pero se
                  nombran aparte — no son "pedidos". */}
              {items.length - borradoresVisibles} pedido
              {items.length - borradoresVisibles !== 1 ? "s" : ""}
              {borradoresVisibles > 0 &&
                ` · ${borradoresVisibles} borrador${borradoresVisibles === 1 ? "" : "es"}`}
            </span>
            <div className="flex-1" />
            <button
              type="button"
              onClick={() => setAskDelete(true)}
              disabled={selId == null}
              aria-label="Eliminar pedido seleccionado"
              title="Eliminar pedido seleccionado"
              className="inline-flex h-9 w-9 items-center justify-center rounded-md border hairline text-muted-foreground hover:border-destructive/40 hover:text-destructive disabled:opacity-40 disabled:hover:border-hairline disabled:hover:text-muted-foreground"
            >
              <Trash2 className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setPanelOpen((o) => !o)}
              aria-label={panelOpen ? "Ensanchar lista" : "Mostrar detalle"}
              title={panelOpen ? "Ensanchar la lista" : "Mostrar el detalle"}
              className="inline-flex h-9 w-9 items-center justify-center rounded-md border hairline text-muted-foreground hover:text-ink"
            >
              <PanelLeft className="h-4 w-4" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            <MasterList
              items={items}
              loading={pedidosQ.isLoading}
              selId={selId}
              onSelect={setSelectedId}
              onOpen={openEditor}
            />
          </div>
        </div>
        {panelOpen && (
          <div className="flex-1 min-w-0 overflow-y-auto bg-surface/40">
            <PreviewPane id={selId} onOpen={openEditor} />
          </div>
        )}
      </div>

      {/* Eliminar el pedido seleccionado (acción de la barra del listado) */}
      <AlertDialog open={askDelete} onOpenChange={setAskDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Eliminar {selPedido ? etiquetaPedido(selPedido) : "pedido"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {selPedido?.cliente_nombre ? `${selPedido.cliente_nombre} · ` : ""}Se borran también
              sus ítems y pagos. No se puede deshacer.
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

      {/* Mobile: cards */}
      <div className="md:hidden flex-1 overflow-y-auto px-4 pb-24 space-y-2 border-t hairline pt-3">
        {/* Acceso a Solicitudes (en mobile no está el sidebar para llegar) */}
        <button
          type="button"
          onClick={() => navigate({ to: "/admin/solicitudes" })}
          className="flex w-full items-center gap-2 rounded-xl border hairline bg-surface-elevated px-4 py-2.5 text-sm text-ink"
        >
          <Pencil className="h-4 w-4 text-muted-foreground" />
          Solicitudes de cambio
          {pendientes > 0 && (
            <span className="ml-auto inline-flex min-w-[18px] items-center justify-center rounded-full bg-amber px-1.5 font-mono text-2xs font-bold text-ink">
              {pendientes}
            </span>
          )}
        </button>
        {pedidosQ.isLoading &&
          Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full rounded-xl" />
          ))}
        {!pedidosQ.isLoading && items.length === 0 && (
          <div className="py-12 text-center text-sm text-muted-foreground">Sin pedidos.</div>
        )}
        {items.map((p) => (
          <AdminCard key={p.id} onClick={() => openEditor(p.id)}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="mb-0.5 flex items-center gap-1.5 t-eyebrow">
                  <span>{etiquetaPedido(p)}</span>
                  <TurnosVinculadosTag count={p.turnos_vinculados_count ?? 0} />
                </div>
                <div className="truncate font-medium text-ink">
                  {p.cliente_nombre || "Sin cliente"}
                </div>
              </div>
              <div className="shrink-0 flex flex-col items-end gap-1">
                <EstadoBadge estado={p.estado} label={ESTADO_LABEL[p.estado]} />
                <span
                  className={cn(
                    "font-semibold text-sm tabular-nums",
                    (p.monto_total ?? 0) === 0 ? "text-muted-foreground" : "text-ink",
                  )}
                >
                  {formatARS(p.monto_total ?? 0)}
                </span>
                {tieneSaldo(p) && (
                  <span className="text-xs tabular-nums text-destructive">
                    saldo {formatARS(saldoDe(p))}
                  </span>
                )}
              </div>
            </div>
            <div className="flex items-center justify-between gap-2 text-sm text-muted-foreground">
              <span>{hoyTag(p) ?? `${fechaDia(p.fecha_desde)} → ${fechaDia(p.fecha_hasta)}`}</span>
              <WhatsAppButton pedido={p} phone={p.cliente_telefono} variant="icon" />
            </div>
          </AdminCard>
        ))}
      </div>

      <FAB
        className="md:hidden"
        onClick={() => navigate({ to: "/admin/pedidos/nuevo" })}
        label="Nuevo pedido"
      />
    </AdminPage>
  );
}

// ── Subcomponentes ───────────────────────────────────────────────────────────

/** Tag "RETIRA HOY" / "DEVUELVE HOY" si aplica (para meta de fila/card). */
function hoyTag(p: Pedido): ReactNode | null {
  if (esHoy(p.fecha_desde) && p.estado === "confirmado")
    return (
      <span className="font-mono text-2xs font-bold uppercase tracking-[0.2em] text-ink">
        retira hoy
      </span>
    );
  if (esHoy(p.fecha_hasta) && p.estado === "retirado")
    return (
      <span className="font-mono text-2xs font-bold uppercase tracking-[0.2em] text-ink">
        devuelve hoy
      </span>
    );
  return null;
}

function MasterList({
  items,
  loading,
  selId,
  onSelect,
  onOpen,
}: {
  items: Pedido[];
  loading: boolean;
  selId: number | null;
  onSelect: (id: number) => void;
  onOpen: (id: number) => void;
}) {
  if (loading) {
    return (
      <div className="p-2 space-y-1.5">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-[72px] w-full rounded-lg" />
        ))}
      </div>
    );
  }
  if (items.length === 0) {
    return <div className="py-16 text-center text-sm text-muted-foreground">Sin pedidos.</div>;
  }
  return (
    <ul className="divide-y hairline">
      {items.map((p) => {
        const sel = p.id === selId;
        return (
          <li key={p.id}>
            <button
              type="button"
              onClick={() => onSelect(p.id)}
              onDoubleClick={() => onOpen(p.id)}
              className={cn(
                "flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors border-l-2",
                sel ? "border-amber bg-amber-soft" : "border-transparent hover:bg-surface",
              )}
            >
              <ClienteAvatar nombre={p.cliente_nombre} className="mt-0.5 h-9 w-9 text-xs" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium text-ink">
                    {p.cliente_nombre || "Sin cliente"}
                  </span>
                  <EstadoBadge
                    estado={p.estado}
                    label={ESTADO_LABEL[p.estado]}
                    className="shrink-0"
                  />
                </div>
                <div className="mt-0.5 flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
                  <span>{etiquetaPedido(p)}</span>
                  <span>·</span>
                  {hoyTag(p) ?? (
                    <span className="truncate tabular-nums">
                      {fechaDia(p.fecha_desde)} → {fechaDia(p.fecha_hasta)}
                    </span>
                  )}
                  <TurnosVinculadosTag count={p.turnos_vinculados_count ?? 0} />
                </div>
                <div className="mt-1.5 flex items-center gap-2">
                  {!estaPagado(p) && (
                    <PagoBadge
                      pagado={p.monto_pagado ?? 0}
                      total={p.monto_total ?? 0}
                      estado={p.estado}
                    />
                  )}
                  <PagoFacturaBadge
                    pagado={estaPagado(p)}
                    facturado={!!p.facturado}
                    detallePago={`Pagado ${fmtArs(p.monto_pagado ?? 0)}`}
                  />
                  <span className="ml-auto font-mono text-sm font-semibold tabular-nums text-ink">
                    {fmtArs(p.monto_total)}
                  </span>
                </div>
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function PreviewPane({ id, onOpen }: { id: number | null; onOpen: (id: number) => void }) {
  const detalleQ = useQuery({
    queryKey: ["admin", "pedido", id],
    queryFn: () => adminApi.getPedido(id as number),
    enabled: id != null,
  });
  const p = detalleQ.data;
  const qc = useQueryClient();
  const [openPago, setOpenPago] = useState(false);
  const [openMail, setOpenMail] = useState(false);
  const [askVerif, setAskVerif] = useState(false);
  const [pendingEstado, setPendingEstado] = useState<EstadoPedido | null>(null);

  // Avanzar estado inline (quick-action). Misma máquina que el editor
  // (@/lib/pedido-estados); el backend rechaza transiciones inválidas igual.
  const estadoMut = useMutation({
    mutationFn: (estado: EstadoPedido) => adminApi.setPedidoEstado(id as number, estado),
    onSuccess: (_d, estado) => {
      toast.success(`Pedido → ${ESTADO_LABEL[estado]}`);
      qc.invalidateQueries({ queryKey: ["admin", "pedido", id] });
      qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  // Regla de hooks: no puede esperar a que `p` cargue para llamarse — por eso el
  // id "de respaldo" y el gate `enabled` (ver useFacturacionArca) en vez de mover
  // esto después de los early-return de abajo.
  const facturacion = useFacturacionArca(id ?? -1, p?.estado ?? "borrador", {
    enabled: id != null,
  });

  if (id == null) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-muted-foreground">
        Elegí un pedido de la lista.
      </div>
    );
  }
  if (detalleQ.isLoading || !p) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-20 w-full rounded-lg" />
        <Skeleton className="h-32 w-full rounded-lg" />
      </div>
    );
  }

  const pagado = p.monto_pagado ?? 0;
  const total = p.monto_total ?? 0;
  const saldo = Math.max(0, total - pagado);
  const jornadas = p.cantidad_jornadas ?? 1;
  const nItems = p.items?.length ?? 0;
  const fuente = fuenteLabel(p.fuente);

  // Próximo paso del flujo (compartido con el editor).
  const ns = nextStep(p);
  const clienteSinVerificar = !!p.cliente_id && !p.cliente_dni_validado_at;
  const ESTADOS_CON_AVISO: EstadoPedido[] = ["confirmado", "retirado"];
  const advanceEstado = (target: EstadoPedido) => {
    if (clienteSinVerificar && ESTADOS_CON_AVISO.includes(target)) {
      setPendingEstado(target);
      setAskVerif(true);
    } else {
      estadoMut.mutate(target);
    }
  };

  return (
    <div className="min-h-full pb-6">
      {/* Toolbar sticky — datos read-only + quick-actions siempre visibles */}
      <div className="sticky top-0 z-10 border-b hairline bg-surface/85 px-5 md:px-6 py-3 backdrop-blur-md">
        <div className="flex items-start gap-3">
          <ClienteAvatar nombre={p.cliente_nombre} className="h-10 w-10 shrink-0 text-sm" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="font-display text-2xl text-ink truncate">
                {p.cliente_nombre || "Sin cliente"}
              </h2>
              <EstadoBadge estado={p.estado} label={ESTADO_LABEL[p.estado]} />
            </div>
            <div className="mt-1 font-mono text-xs text-muted-foreground flex items-center gap-1.5 flex-wrap">
              <span>Pedido {etiquetaPedido(p)}</span>
              {creadoHace(p.created_at) && (
                <>
                  <span>·</span>
                  <span>creado {creadoHace(p.created_at)}</span>
                </>
              )}
              {fuente && (
                <>
                  <span>·</span>
                  <span>{fuente}</span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Quick-actions, agrupadas por familia (a pedido del dueño: antes eran 6
            botones sueltos con peso parejo). Proximidad + un divisor sutil separan
            tres grupos: TRABAJO del pedido (siguiente paso · editar) · PLATA (cobrar ·
            facturar) · CONTACTO con el cliente (mail · whatsapp). Gap chico dentro del
            grupo, gap grande entre grupos; el divisor se oculta en mobile (ahí la
            proximidad sola alcanza y no queda una rayita colgada al hacer wrap). */}
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
          {/* Trabajo del pedido */}
          <div className="flex items-center gap-1.5">
            {ns && (
              <Button
                variant={ns.blocked ? "outline" : "amber"}
                size="sm"
                disabled={!!ns.blocked || estadoMut.isPending}
                title={ns.blocked ?? ""}
                onClick={() => !ns.blocked && advanceEstado(ns.target)}
              >
                <ArrowRight className="h-3.5 w-3.5 mr-1" />
                {ns.blocked ? `Falta: ${ns.blocked}` : ns.label}
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={() => onOpen(p.id)}>
              <Pencil className="h-3.5 w-3.5 mr-1" /> Editar
            </Button>
          </div>

          <div aria-hidden className="hidden h-5 self-center border-l hairline sm:block" />

          {/* Plata */}
          <div className="flex items-center gap-1.5">
            <Button
              variant="outline"
              size="sm"
              disabled={p.estado === "cancelado"}
              onClick={() => setOpenPago(true)}
            >
              <Coins className="h-3.5 w-3.5 mr-1" /> Registrar pago
            </Button>
            <FacturarButton f={facturacion} hideWhenUnavailable />
          </div>

          <div aria-hidden className="hidden h-5 self-center border-l hairline sm:block" />

          {/* Contacto con el cliente */}
          <div className="flex items-center gap-1.5">
            <Button variant="outline" size="sm" onClick={() => setOpenMail(true)}>
              <Mail className="h-3.5 w-3.5 mr-1" /> Mandar mail
            </Button>
            <WhatsAppButton pedido={p} phone={p.cliente_telefono} variant="compact" />
          </div>
        </div>
      </div>

      {/* Cuerpo */}
      <div className="px-5 md:px-6 py-5 space-y-4">
        {/* Fechas + total */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="card-elevated px-4 py-3">
            <div className="t-eyebrow">Fechas</div>
            <div className="mt-1 text-ink font-medium tabular-nums">
              {fechaDia(p.fecha_desde)} → {fechaDia(p.fecha_hasta)}
            </div>
            <div className="mt-0.5 font-mono text-xs text-muted-foreground">
              {jornadas} jornada{jornadas !== 1 ? "s" : ""}
            </div>
          </div>
          <div className="card-elevated px-4 py-3">
            <div className="t-eyebrow">Total neto</div>
            <div className="mt-1 font-mono text-2xl font-semibold tabular-nums text-ink">
              {fmtArs(total)}
            </div>
            <div className="mt-0.5 font-mono text-xs text-muted-foreground">
              {pagado >= total && total > 0
                ? "pagado"
                : pagado > 0
                  ? `seña ${fmtArs(pagado)} · resta ${fmtArs(saldo)}`
                  : "sin seña registrada"}
            </div>
          </div>
        </div>

        {/* Equipos */}
        <div className="card-elevated">
          <div className="flex items-center justify-between px-4 py-2.5 border-b hairline">
            <span className="t-eyebrow">Equipos · {nItems}</span>
            {nItems > 0 && <span className="t-eyebrow">precio / jornada</span>}
          </div>
          <ul className="divide-y hairline">
            {(p.items ?? []).map((it) => (
              <li key={it.id} className="flex items-center gap-3 px-4 py-2.5">
                <EquipoThumb
                  src={it.foto_url}
                  alt={it.nombre_publico || it.nombre}
                  className="h-9 w-9 shrink-0"
                />
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-ink truncate">{it.nombre_publico || it.nombre}</div>
                  {it.marca && (
                    <div className="font-mono text-xs text-muted-foreground">{it.marca}</div>
                  )}
                </div>
                <div className="font-mono text-sm tabular-nums text-ink shrink-0">
                  {it.cantidad}× {fmtArs(it.precio_jornada)}
                </div>
              </li>
            ))}
            {nItems === 0 && (
              <li className="px-4 py-6 text-center text-sm text-muted-foreground">
                Sin equipos cargados.
              </li>
            )}
          </ul>
        </div>
      </div>

      {/* Modales (quick-actions inline) */}
      <RegistrarPagoModal
        pedidoId={p.id}
        total={total}
        pagado={pagado}
        open={openPago}
        onOpenChange={setOpenPago}
        esEstudio={esPedidoEstudio(p)}
      />
      <EnviarDocsDialog
        pedidoId={p.id}
        clienteEmail={p.cliente_email ?? ""}
        open={openMail}
        onOpenChange={setOpenMail}
      />
      <FacturaPreviewDialog f={facturacion} />

      <AlertDialog open={askVerif} onOpenChange={setAskVerif}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-ink shrink-0" />
              Cliente sin identidad verificada
            </AlertDialogTitle>
            <AlertDialogDescription>
              {p.cliente_nombre} no verificó su identidad (DNI + selfie). Podés avanzar igual, o
              gestionarlo desde el editor.
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
              Avanzar de todas formas
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
