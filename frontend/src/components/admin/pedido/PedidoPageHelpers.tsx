import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  Building2,
  Check,
  ChevronDown,
  ChevronLeft,
  Download,
  Eye,
  GripVertical,
  Mail,
  Receipt,
  Tag,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { Button } from "@/design-system/ui/button";
import { IconButton } from "@/design-system/ui/icon-button";
import { Input } from "@/design-system/ui/input";
import { RadioGroup, RadioGroupItem } from "@/design-system/ui/radio-group";
import { DraftNumberInput } from "@/design-system/ui/draft-number-input";
import { QtyInput } from "@/design-system/ui/qty-input";
import { Section } from "@/design-system/composites/Section";
import { Chequeos } from "@/design-system/composites/Chequeos";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/design-system/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/design-system/ui/select";
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
import { FacturaBadge } from "@/design-system/ui/FacturaBadge";
import { Spinner } from "@/design-system/ui/spinner";
import { cn } from "@/lib/utils";
import { ESTADO_DOT } from "@/design-system/ui/estado-color";
import { adminApi, ESTADO_LABEL, type PedidoEstado } from "@/lib/admin/api";
import { formatARS, formatFechaCorta, fmtArs } from "@/lib/format";
import {
  useFacturacionArca,
  LAYOUT_ASPECT,
  type FacturacionArca,
} from "@/components/admin/pedido/useFacturacionArca";
import { type DraftItem, subtotalDraftItem } from "@/components/admin/pedido/usePedidoDraft";
import { EquipoThumb } from "@/components/admin/pedido/EquipoThumb";

export function PagoRow({
  pago,
  pedidoId,
}: {
  pago: {
    id: number;
    monto: number;
    concepto: string | null;
    fecha: string;
    anulado?: boolean;
    anulado_motivo?: string | null;
  };
  pedidoId: number;
}) {
  const qc = useQueryClient();
  const delMut = useMutation({
    mutationFn: (motivo: string) => adminApi.anularPago(pedidoId, pago.id, motivo),
    onSuccess: () => {
      toast.success("Pago anulado");
      qc.invalidateQueries({ queryKey: ["admin", "pedido", pedidoId] });
      qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div
      className={cn("flex items-center justify-between text-xs mt-1", pago.anulado && "opacity-50")}
    >
      <span className="text-muted-foreground">
        <span className={cn(pago.anulado && "line-through")}>
          {pago.concepto || "Pago"} · {formatFechaCorta(pago.fecha)}
        </span>
        {pago.anulado && pago.anulado_motivo && (
          <span className="text-destructive"> · Anulado: {pago.anulado_motivo}</span>
        )}
      </span>
      <div className="flex items-center gap-1">
        <span className={cn("font-mono", pago.anulado && "line-through")}>
          {formatARS(pago.monto)}
        </span>
        {!pago.anulado && (
          <IconButton
            aria-label="Anular pago"
            size="xs"
            onClick={() => {
              const motivo = window.prompt("Motivo de la anulación del pago:");
              if (motivo && motivo.trim()) delMut.mutate(motivo.trim());
            }}
            disabled={delMut.isPending}
            className="text-muted-foreground hover:text-destructive hover:bg-destructive/10"
          >
            <X className="h-3 w-3" />
          </IconButton>
        )}
      </div>
    </div>
  );
}

/** Fila de línea del pedido, arrastrable para reordenar (#806). El handle (grip)
 * lleva los listeners del drag; el resto queda libre para editar. Soporta líneas
 * de catálogo (equipo_id) y líneas personalizadas (#805, equipo_id null): nombre
 * libre + toggle de modo de cobro (fijo / por jornada). */
export function ItemRow({
  it,
  stock,
  jornadas,
  updateItem,
  removeItem,
}: {
  it: DraftItem;
  /** Libres del equipo tras TODO el draft (backend, expansión de kits incluida).
   *  Con signo: negativo = faltan unidades. undefined = sin dato (sin fechas). */
  stock?: number;
  jornadas: number;
  updateItem: (uid: string, patch: Partial<DraftItem>) => void;
  removeItem: (uid: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: it.uid,
  });
  const esLibre = it.equipo_id == null;
  // El backend ya descontó el draft completo (incluida esta línea y los kits
  // que consumen sus componentes) — acá NO se resta nada más.
  const disponible = stock;
  const overstock = disponible !== undefined && disponible < 0;
  const subtotal = subtotalDraftItem(it, jornadas);

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5 bg-surface",
        isDragging && "opacity-60",
      )}
    >
      {/* Identidad: grip + foto + nombre/meta (crece y ocupa el ancho sobrante) */}
      <div className="flex min-w-[200px] flex-1 items-center gap-2">
        <IconButton
          aria-label="Reordenar línea"
          size="lg"
          className="-ml-2 w-9 shrink-0 text-muted-foreground/60 hover:text-ink cursor-grab touch-none active:cursor-grabbing"
          {...attributes}
          {...listeners}
        >
          <GripVertical className="h-4 w-4" />
        </IconButton>
        {esLibre ? (
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-dashed hairline text-muted-foreground/60">
            <Tag className="h-4 w-4" />
          </div>
        ) : (
          <EquipoThumb
            src={it.foto_url}
            alt={it.nombre_publico || it.nombre}
            className="h-10 w-10 shrink-0"
          />
        )}
        <div className="min-w-0 flex-1">
          {esLibre ? (
            <Input
              value={it.nombre_libre ?? ""}
              placeholder="Descripción (ej. Flete, Operador…)"
              onChange={(e) => updateItem(it.uid, { nombre_libre: e.target.value })}
              className="h-8 text-sm"
            />
          ) : (
            <>
              <div className="text-sm text-ink truncate">{it.nombre_publico || it.nombre}</div>
              <div className="mt-0.5 flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
                {it.marca && <span className="truncate">{it.marca}</span>}
                {disponible !== undefined && (
                  <span
                    className={cn(
                      "inline-flex shrink-0 items-center rounded px-1.5 py-0.5 text-2xs",
                      disponible <= 0
                        ? "bg-destructive/10 text-destructive"
                        : "bg-muted text-muted-foreground",
                    )}
                  >
                    {disponible <= 0 ? `${disponible} restante` : `${disponible} libres`}
                  </span>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Controles: cantidad · precio · subtotal · quitar (alineados en columna) */}
      <div className="ml-auto flex flex-wrap items-center justify-end gap-x-2 gap-y-1.5">
        {/* Stepper de cantidad */}
        <QtyInput
          value={it.cantidad}
          onChange={(v) => updateItem(it.uid, { cantidad: v })}
          min={1}
          error={overstock}
        />

        {/* Precio editable por jornada */}
        <div className="flex items-center gap-1">
          <DraftNumberInput
            min={0}
            value={it.precio_jornada}
            ariaLabel="Precio por jornada"
            onCommit={(v) => updateItem(it.uid, { precio_jornada: v })}
            className="h-9 w-24 text-sm"
          />
          {esLibre ? (
            <select
              value={it.cobro_modo ?? "jornada"}
              onChange={(e) =>
                updateItem(it.uid, { cobro_modo: e.target.value as "jornada" | "fijo" })
              }
              className="h-9 rounded-md border hairline bg-surface-elevated px-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-ring"
              aria-label="Modo de cobro"
            >
              <option value="jornada">/jornada</option>
              <option value="fijo">fijo</option>
            </select>
          ) : it.cobro_modo === "fijo" ? (
            // Ítem de catálogo con cobro_modo='fijo' (ej. el centinela del
            // Estudio en un pedido de taller): no se multiplica por jornadas,
            // "/día" mentiría. No editable acá (a diferencia de una línea
            // libre) — el cobro_modo de un ítem de catálogo lo decide su
            // motor dueño (Estudio/Talleres), no el editor genérico.
            <span className="text-xs text-muted-foreground whitespace-nowrap">fijo</span>
          ) : (
            <span className="text-xs text-muted-foreground whitespace-nowrap">/día</span>
          )}
        </div>

        {/* Subtotal de la línea */}
        <div className="w-24 text-right font-mono text-sm font-semibold tabular-nums text-ink">
          {fmtArs(subtotal)}
        </div>

        {/* Quitar */}
        <IconButton
          aria-label="Quitar línea"
          onClick={() => removeItem(it.uid)}
          className="shrink-0 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
        >
          <X className="h-4 w-4" />
        </IconButton>
      </div>
    </li>
  );
}

export function BackLink({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-ink shrink-0"
    >
      <ChevronLeft className="h-4 w-4" /> Pedidos
    </button>
  );
}

export function SaveIndicator({
  status,
  /** Calla TODO salvo un error — para un indicador LOCAL (ej. el total de un
   *  turno del Estudio) cuando la pantalla ya tiene un indicador GENERAL
   *  propio (el de arriba a la derecha, que cubre el autosave del pedido).
   *  Un primer intento solo callaba "Guardado" pero dejaba "Sin guardar"/
   *  "Guardando…" — el dueño lo notó igual ("¿por qué aparecen estos textos
   *  aún?"): son transiciones de menos de un segundo (debounce 700ms + un
   *  PATCH rápido), no hace falta narrarlas — la señal real y accionable es
   *  solo el ERROR (el general no puede darla: son autosaves de recursos
   *  distintos, este PATCHea el turno, no el pedido). Default `false`: no
   *  cambia nada para el indicador general de la página. */
  onlyError = false,
}: {
  status: string;
  onlyError?: boolean;
}) {
  const map: Record<string, { tx: string; cls: string }> = {
    saving: { tx: "Guardando…", cls: "text-muted-foreground" },
    saved: { tx: "Guardado", cls: "text-verde-ink" },
    dirty: { tx: "Sin guardar", cls: "text-muted-foreground" },
    error: { tx: "Error al guardar", cls: "text-destructive" },
    idle: { tx: "", cls: "" },
  };
  const s = map[status] ?? map.idle;
  if (!s.tx) return null;
  if (onlyError && status !== "error") return null;
  return (
    <span className={cn("inline-flex items-center gap-1 font-mono text-xs", s.cls)}>
      {status === "saved" && <Check className="h-3 w-3" />}
      {s.tx}
    </span>
  );
}

/** "Facturar a nombre de" (#1251) — el renter sigue siendo `cliente_id`; esto
 * solo elige a quién se factura: la cuenta default, un perfil fiscal personal,
 * o una productora vinculada al cliente. Mismo patrón que el selector del
 * checkout (`CheckoutResumen.tsx`), reusado acá para el admin. Solo se
 * renderiza si el pedido tiene cliente Y ese cliente tiene más de una opción
 * (si no hay nada para elegir, no tiene sentido mostrar el selector). */
export function FacturacionTargetSection({
  clienteId,
  perfilFiscalId,
  productoraId,
  onChange,
}: {
  clienteId: number | null;
  perfilFiscalId: number | null;
  productoraId: number | null;
  onChange: (v: { perfilFiscalId: number | null; productoraId: number | null }) => void;
}) {
  const q = useQuery({
    queryKey: ["admin", "cliente-perfiles-fiscales", clienteId],
    queryFn: () => adminApi.getClientePerfilesFiscales(clienteId!),
    enabled: !!clienteId,
  });
  const perfiles = q.data?.perfiles ?? [];
  // Excluye productoras BORRADOR (sin CUIT, #1251 Fase 3) — no son facturables,
  // mismo criterio que `productoras_vinculadas(solo_facturables=True)` del checkout.
  const productoras = (q.data?.productoras ?? []).filter((pr) => pr.cuit);
  if (!clienteId || perfiles.length + productoras.length === 0) return null;

  const value = perfilFiscalId
    ? `perfil-${perfilFiscalId}`
    : productoraId
      ? `productora-${productoraId}`
      : "default";

  function handleChange(v: string) {
    if (v === "default") return onChange({ perfilFiscalId: null, productoraId: null });
    const [tipo, idStr] = v.split("-");
    const id = Number(idStr);
    return tipo === "perfil"
      ? onChange({ perfilFiscalId: id, productoraId: null })
      : onChange({ perfilFiscalId: null, productoraId: id });
  }

  return (
    <Section variant="card" tone="elevated" icon={Building2} title="Facturar a nombre de">
      <RadioGroup value={value} onValueChange={handleChange} className="gap-2">
        <label className="flex items-center gap-2 text-sm text-ink">
          <RadioGroupItem value="default" />
          Cuenta del cliente (default)
        </label>
        {perfiles.map((p) => (
          <label key={`perfil-${p.id}`} className="flex items-center gap-2 text-sm text-ink">
            <RadioGroupItem value={`perfil-${p.id}`} />
            {p.etiqueta || p.razon_social || p.cuit}
          </label>
        ))}
        {productoras.map((pr) => (
          <label key={`productora-${pr.id}`} className="flex items-center gap-2 text-sm text-ink">
            <RadioGroupItem value={`productora-${pr.id}`} />
            {pr.nombre || pr.razon_social || pr.cuit}
          </label>
        ))}
      </RadioGroup>
    </Section>
  );
}

export function RailSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="border-t hairline pt-4 first:border-t-0 first:pt-0">
      <div className="t-eyebrow mb-2">{label}</div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

/**
 * Fuente única para cambiar el estado de un pedido: "avanzar al paso feliz"
 * y "saltar a otro estado" viven en UN solo control (botón dividido) en vez
 * de 2 botones apilados — antes se leían como la misma acción repetida
 * (#pedido-estado-ux, a pedido del dueño). El cuerpo principal ejecuta el
 * paso feliz en 1 click, igual que antes; el chevron abre el menú con los
 * demás destinos legales (`otrosDestinos`, que ya excluye ese mismo paso).
 */
export function EstadoSplitButton({
  ns,
  otrosDestinos,
  onSelect,
  disabled,
}: {
  ns: { target: PedidoEstado; label: string; blocked: string | null } | null;
  otrosDestinos: PedidoEstado[];
  onSelect: (target: PedidoEstado) => void;
  disabled?: boolean;
}) {
  const tieneMenu = otrosDestinos.length > 0;

  // Estado terminal sin paso feliz (ej. "finalizado" puede volver a "devuelto"):
  // no hay cuerpo principal que mostrar — el menú, si existe, es el único control.
  if (!ns) {
    if (!tieneMenu) return null;
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className="w-full" disabled={disabled}>
            Cambiar estado
            <ChevronDown className="h-3.5 w-3.5 ml-1" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="center"
          className="w-full min-w-[--radix-dropdown-menu-trigger-width]"
        >
          {otrosDestinos.map((estado) => (
            <DropdownMenuItem key={estado} onClick={() => onSelect(estado)}>
              <span className={cn("mr-2 h-2 w-2 shrink-0 rounded-full", ESTADO_DOT[estado])} />
              {ESTADO_LABEL[estado]}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  }

  const variant = ns.blocked ? "outline" : "amber";
  const mainButton = (
    <Button
      variant={variant}
      className={cn("flex-1 justify-center", tieneMenu && "rounded-r-none")}
      disabled={!!ns.blocked || disabled}
      title={ns.blocked ?? ""}
      onClick={() => !ns.blocked && onSelect(ns.target)}
    >
      <ArrowRight className="h-4 w-4 mr-1" />
      {ns.blocked ? `Falta: ${ns.blocked}` : ns.label}
    </Button>
  );

  if (!tieneMenu) return mainButton;

  return (
    <div className="flex w-full">
      {mainButton}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant={variant}
            className="rounded-l-none border-l hairline px-2.5 shrink-0"
            disabled={disabled}
            aria-label="Elegir otro estado"
          >
            <ChevronDown className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {otrosDestinos.map((estado) => (
            <DropdownMenuItem key={estado} onClick={() => onSelect(estado)}>
              <span className={cn("mr-2 h-2 w-2 shrink-0 rounded-full", ESTADO_DOT[estado])} />
              {ESTADO_LABEL[estado]}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export function BdRow({
  l,
  v,
  neg,
  strong,
}: {
  l: string;
  v: string;
  neg?: boolean;
  strong?: boolean;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className={cn("text-muted-foreground", strong && "text-ink font-medium")}>{l}</span>
      <span
        className={cn(
          "font-mono tabular-nums",
          neg && "text-destructive",
          strong && "text-ink font-semibold text-base",
        )}
      >
        {v}
      </span>
    </div>
  );
}

// Copy corto para el selector de emisor del preview — mismo trío de condiciones que
// `CONDICIONES` en facturacion.emisores.lazy.tsx, acortado para que entre en un <SelectItem>.
const CONDICION_IVA_CORTA: Record<string, string> = {
  responsable_inscripto: "RI, Factura A",
  monotributo: "Monotributo, Factura C",
  exento: "Exento, Factura B",
};

/** Modal de preview + confirmación — compartido por el detalle y el listado. */
export function FacturaPreviewDialog({ f }: { f: FacturacionArca }) {
  return (
    <AlertDialog open={f.showPreview} onOpenChange={f.setShowPreview}>
      <AlertDialogContent className="flex h-[94vh] w-fit max-w-[95vw] flex-row overflow-hidden p-0">
        {/* Columna izquierda: info + chequeos + acciones. Columna derecha: la factura a pantalla
            completa de alto, dimensionada a la proporción REAL del layout elegido (LAYOUT_ASPECT)
            — así no queda el sobrante gris que el propio HTML de arca_fe deja alrededor cuando
            el viewport no matchea el aspecto (ese HTML centra y escala manteniendo proporción). */}
        <div className="flex w-[360px] shrink-0 flex-col overflow-y-auto border-r hairline">
          <AlertDialogHeader className="px-5 py-4 text-left">
            <AlertDialogTitle>Confirmar factura</AlertDialogTitle>
            <AlertDialogDescription>
              Revisá el documento antes de emitir — una vez que ARCA da el CAE, solo se puede
              corregir con una Nota de Crédito.
            </AlertDialogDescription>
          </AlertDialogHeader>

          {/* Se muestra apenas hay UN emisor elegible además de "Automático" — a diferencia del
              selector "Facturar a nombre de" de CheckoutResumen (que sí exige 2+ opciones), acá
              el caso motivador es justo tener un solo emisor configurado (ej. el monotributista)
              cuando la resolución automática pide uno DISTINTO que no existe (cliente RI sin
              emisor RI activo): con el gate en ">1" el override quedaría inalcanzable desde la UI
              exactamente en el caso que lo necesita. */}
          {f.emisoresElegibles.length >= 1 && (
            <div className="space-y-1.5 border-b hairline px-5 py-3">
              <div className="font-mono text-2xs uppercase tracking-widest text-muted-foreground">
                Emisor
              </div>
              <Select
                value={f.emisorOverrideId ? String(f.emisorOverrideId) : "auto"}
                onValueChange={(v) => f.setEmisorOverrideId(v === "auto" ? null : Number(v))}
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Automático (según el cliente)</SelectItem>
                  {f.emisoresElegibles.map((e) => (
                    <SelectItem key={e.id} value={String(e.id)}>
                      {e.nombre} — {CONDICION_IVA_CORTA[e.condicion_iva] ?? e.condicion_iva}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-2xs text-muted-foreground leading-snug">
                Fuerza la letra del comprobante a la que corresponda por la condición IVA de ese
                emisor, sin importar la del cliente.
              </p>
            </div>
          )}

          <div className="flex-1 px-5">
            {f.preview.isPending && (
              <div className="py-2 text-sm text-muted-foreground">Chequeando…</div>
            )}
            {f.preview.isError && (
              <div className="py-2 text-sm text-destructive">
                {(f.preview.error as Error).message}
              </div>
            )}
            {f.preview.data && <Chequeos items={f.preview.data.chequeos} />}
          </div>

          <AlertDialogFooter className="flex-col gap-2 border-t hairline px-5 py-4 sm:flex-col">
            <AlertDialogAction
              disabled={!f.preview.data?.listo || f.facturar.isPending}
              onClick={() => f.facturar.mutate()}
              className="w-full"
            >
              {f.facturar.isPending ? "Emitiendo…" : "Confirmar y emitir"}
            </AlertDialogAction>
            <AlertDialogCancel className="w-full">Cancelar</AlertDialogCancel>
          </AlertDialogFooter>
        </div>

        <div
          className="relative h-full shrink-0 overflow-hidden bg-muted"
          style={{ aspectRatio: LAYOUT_ASPECT[f.layout] ?? LAYOUT_ASPECT.simplificada }}
        >
          {!f.facturaHtmlError && (!f.facturaBlobUrl || !f.facturaIframeReady) && (
            <div className="absolute inset-0 flex items-center justify-center gap-2 bg-muted text-sm text-muted-foreground">
              <Spinner size="sm" />
              Armando la factura…
            </div>
          )}
          {f.facturaHtmlError && (
            <div className="flex h-full items-center justify-center px-6 text-center text-sm text-destructive">
              {f.facturaHtmlError}
            </div>
          )}
          {!f.facturaHtmlError && f.facturaBlobUrl && (
            <iframe
              src={f.facturaBlobUrl}
              title="Factura (borrador, sin CAE)"
              className="h-full w-full border-0"
              sandbox=""
              onLoad={() => f.setFacturaIframeReady(true)}
            />
          )}
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/**
 * El botón "Facturar"/"Reintentar" en sí — mismo componente en el rail del
 * detalle (`FacturacionRailSection`, abajo) y en la barra de acciones rápidas
 * del listado (`pedidos.index.lazy.tsx`). Antes estaba escrito dos veces con
 * el mismo `disabled`/`onClick`/label pero un `title` ligeramente distinto
 * entre copias — exactamente el tipo de drift silencioso que el dueño no
 * quiere: un cambio futuro (label, gate, ícono) ahora se hace una sola vez.
 */
export function FacturarButton({
  f,
  className,
  hideWhenUnavailable,
}: {
  f: FacturacionArca;
  className?: string;
  /**
   * Si el pedido todavía no se puede facturar (estado no facturable, sin
   * factura previa), no renderiza nada en vez de mostrar un botón gris muerto.
   * Lo usa la barra de acciones del listado (panel de triage — solo lo
   * accionable). El rail del detalle NO lo pasa: ahí conviene mostrarlo
   * deshabilitado con el `title` explicativo, porque es la vista donde el
   * usuario decide qué falta para poder facturar.
   */
  hideWhenUnavailable?: boolean;
}) {
  if (!((!f.principal || f.principal.estado === "error") && !f.q.isLoading)) return null;
  if (hideWhenUnavailable && !f.puedeFacturar) return null;
  return (
    <Button
      variant="outline"
      size="sm"
      className={className}
      disabled={!f.puedeFacturar || f.preview.isPending}
      title={!f.puedeFacturar ? "No se puede facturar en este estado" : undefined}
      onClick={() => {
        f.setShowPreview(true);
        f.preview.mutate(undefined);
      }}
    >
      <Receipt className="h-3.5 w-3.5 mr-1" />
      {f.preview.isPending ? "Calculando…" : f.principal ? "Reintentar" : "Facturar"}
    </Button>
  );
}

/** Vista rica de la factura ARCA para el rail del detalle de pedido (estado persistente:
 * badge/CAE/links/anular). El listado usa `useFacturacionArca` + `FacturaPreviewDialog` +
 * `FacturarButton` directo, sin este wrapper — su barra de acciones rápidas no tiene lugar
 * para tanto detalle. */
export function FacturacionRailSection({
  pedidoId,
  estadoPedido,
}: {
  pedidoId: number;
  estadoPedido: PedidoEstado;
}) {
  const f = useFacturacionArca(pedidoId, estadoPedido);

  return (
    <RailSection label="Factura ARCA">
      {f.q.isLoading && <div className="text-xs text-muted-foreground">Cargando…</div>}

      {f.principal && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <FacturaBadge estado={f.principal.estado} />
            {f.cbteLetra && (
              <span className="font-mono text-xs text-muted-foreground">Fact. {f.cbteLetra}</span>
            )}
            {f.principal.ambiente === "homologacion" && (
              // eslint-disable-next-line no-restricted-syntax -- amber: paleta categórica homologación (Tier 3)
              <span className="font-mono text-2xs text-amber-600 border border-amber-400/50 rounded px-1">
                TEST
              </span>
            )}
          </div>

          {f.principal.cbte_nro && (
            <div className="font-mono text-xs text-muted-foreground">
              {String(f.principal.pto_vta).padStart(5, "0")}-
              {String(f.principal.cbte_nro).padStart(8, "0")}
            </div>
          )}

          {f.principal.cae && (
            <div className="font-mono text-xs text-muted-foreground">CAE {f.principal.cae}</div>
          )}

          {f.principal.estado === "error" && f.principal.errores && (
            <div className="text-xs text-destructive rounded border border-destructive/20 bg-destructive/5 px-2 py-1.5">
              {Array.isArray(f.principal.errores)
                ? f.principal.errores.join(" / ")
                : String(f.principal.errores)}
            </div>
          )}

          {f.principal.estado === "emitida" && (
            <div className="space-y-1.5">
              <Select value={f.layout} onValueChange={f.setLayout}>
                <SelectTrigger className="h-7 text-xs">
                  <SelectValue placeholder="Formato" />
                </SelectTrigger>
                <SelectContent>
                  {f.layouts.map((l) => (
                    <SelectItem key={l.id} value={l.id} title={l.descripcion}>
                      {l.nombre}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {f.layoutInfo?.descripcion && (
                <p className="text-2xs text-muted-foreground leading-snug">
                  {f.layoutInfo.descripcion}
                </p>
              )}
              {f.layoutInfo?.advertencia && (
                // eslint-disable-next-line no-restricted-syntax -- amber: paleta categórica de advertencia (Tier 3)
                <p className="text-2xs text-amber-700 leading-snug flex items-start gap-1">
                  <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5" />
                  {f.layoutInfo.advertencia}
                </p>
              )}
              <div className="flex flex-wrap gap-1.5">
                <a
                  href={`/api/facturas/${f.principal.id}/pdf?format=html&layout=${f.layout}`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md border hairline text-xs text-muted-foreground hover:text-ink hover:border-ink/30"
                >
                  <Eye className="h-3 w-3" /> Ver
                </a>
                <a
                  href={`/api/facturas/${f.principal.id}/pdf?layout=${f.layout}`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md border hairline text-xs text-muted-foreground hover:text-ink hover:border-ink/30"
                >
                  <Download className="h-3 w-3" /> Descargar PDF
                </a>
                <button
                  type="button"
                  onClick={() => f.enviarMail.mutate(f.principal!.id)}
                  disabled={f.enviarMail.isPending}
                  className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md border hairline text-xs text-muted-foreground hover:text-ink hover:border-ink/30 disabled:opacity-50"
                >
                  <Mail className="h-3 w-3" />
                  {f.enviarMail.isPending ? "Enviando…" : "Enviar por mail"}
                </button>
              </div>
            </div>
          )}

          {f.nc && (
            <div className="mt-1 flex items-center gap-1.5">
              <FacturaBadge estado={f.nc.estado} />
              <span className="font-mono text-2xs text-muted-foreground">NC emitida</span>
            </div>
          )}

          {f.puedeAnular && (
            <Button
              variant="outline"
              size="sm"
              className="w-full border-destructive/30 text-destructive hover:bg-destructive/10 hover:text-destructive"
              disabled={f.notaCredito.isPending}
              onClick={() => f.notaCredito.mutate(f.principal!.id)}
            >
              <X className="h-3.5 w-3.5 mr-1" />
              {f.notaCredito.isPending ? "Emitiendo NC…" : "Anular con NC"}
            </Button>
          )}
        </div>
      )}

      <FacturarButton f={f} className="w-full" />
      <FacturaPreviewDialog f={f} />
    </RailSection>
  );
}
