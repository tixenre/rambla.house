// Sub-components extracted verbatim from PedidoPage.tsx (legacy).
// Moved here to keep PedidoPage.tsx under a manageable line count.
// Zero logic changes — move-verbatim only.

import { useState } from "react";
import { useQueryClient, useMutation } from "@tanstack/react-query";
import {
  Search,
  X,
  Plus,
  Minus,
  AlertTriangle,
  Check,
  Eye,
  Download,
  ShoppingCart,
  Mail,
} from "lucide-react";
import { Spinner } from "@/design-system/ui/spinner";
import { toast } from "sonner";

import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { DraftNumberInput } from "@/design-system/ui/draft-number-input";
import { MoneyInput } from "@/design-system/ui/money-input";
import { Label } from "@/design-system/ui/label";
import { Badge } from "@/design-system/ui/badge";
import { Pill } from "@/design-system/ui/Pill";
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
import { cn } from "@/lib/utils";

import { adminApi, pedidoPdfUrl, type PedidoHistorialItem } from "@/lib/admin/api";
import {
  type DraftItem,
  type DraftDatos,
  type PedidoMode,
  subtotalDraftItem,
} from "./usePedidoDraft";
import { fmtArs, formatFechaDisplay } from "@/lib/format";
import { descuentoLabel, type DescuentoOrigen } from "@/lib/cotizacion";
import { SegmentedControl } from "@/design-system/ui/segmented-control";
import { EquipoSearchSheet } from "./EquipoSearchSheet";
import { EnviarDocsDialog, DOCS_PEDIDO } from "./EnviarDocsDialog";

const fmtFecha = (s: string) => formatFechaDisplay(s);

// ─────────────────────────────────────────────────────────────────────────
// Items card
// ─────────────────────────────────────────────────────────────────────────

export function ItemsCard({
  items,
  setItems,
  jornadas,
  stockMap,
  mode = "admin",
}: {
  items: DraftItem[];
  setItems: (v: DraftItem[]) => void;
  jornadas: number;
  /** equipo_id → libres tras TODO el draft (backend, kits expandidos; con signo). */
  stockMap: Record<string, number>;
  mode?: PedidoMode;
}) {
  const [openSearch, setOpenSearch] = useState(false);
  const isCliente = mode === "cliente";

  // Las líneas se identifican por `uid` (las personalizadas no tienen equipo_id, #805).
  const updateItem = (uid: string, patch: Partial<DraftItem>) =>
    setItems(items.map((it) => (it.uid === uid ? { ...it, ...patch } : it)));

  const removeItem = (uid: string) => {
    if (items.length === 1) {
      toast.error("El pedido debe tener al menos un equipo.");
      return;
    }
    setItems(items.filter((it) => it.uid !== uid));
  };

  return (
    <section className="card overflow-hidden">
      {/* Search trigger */}
      <button
        type="button"
        onClick={() => setOpenSearch(true)}
        className="flex w-full items-center gap-2.5 px-4 py-3 border-b hairline text-sm text-muted-foreground hover:bg-muted/30 transition"
      >
        <Search className="h-4 w-4 shrink-0" />
        <span>Buscar para añadir productos</span>
      </button>

      {/* Column headers */}
      {items.length > 0 && (
        <div className="grid grid-cols-[1fr_auto_auto_auto] gap-2 px-4 py-2 border-b hairline bg-muted/20 text-2xs uppercase tracking-wide text-muted-foreground">
          <span>Producto</span>
          <span className="text-right w-20">Disponible</span>
          <span className="text-right w-16">Cantidad</span>
          <span className="text-right w-24">Cargo</span>
        </div>
      )}

      {items.length === 0 && (
        <div className="px-4 py-10 text-center text-sm text-muted-foreground">
          Sin equipos. Usá el buscador para agregar.
        </div>
      )}

      <ul className="divide-y hairline">
        {items.map((it, idx) => {
          // El backend ya descontó el draft completo (incluida esta línea y
          // los kits que consumen sus componentes) — acá NO se resta nada más.
          const disponible = stockMap[String(it.equipo_id)];
          const overstock = disponible !== undefined && disponible < 0;
          const subtotal = subtotalDraftItem(it, jornadas);

          return (
            <li key={`${it.equipo_id}-${idx}`} className="px-4 py-3 space-y-2.5">
              {/* Row 1: thumb + info + disponible + total + remove */}
              <div className="flex items-start gap-3">
                <div className="h-10 w-10 rounded-md bg-muted/50 border hairline shrink-0 flex items-center justify-center text-muted-foreground">
                  <ShoppingCart className="h-4 w-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-ink truncate">
                    {it.nombre_publico || it.nombre}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {it.marca ?? "—"}
                    {disponible !== undefined && (
                      <Pill tone={disponible <= 0 ? "danger" : "neutral"} className="ml-1.5">
                        {disponible <= 0 ? `${disponible} restante` : `${disponible} libres`}
                      </Pill>
                    )}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-sm tabular-nums font-medium text-ink">
                    {fmtArs(subtotal)}
                  </div>
                  <div className="text-xs text-muted-foreground">{jornadas}j</div>
                </div>
                <button
                  type="button"
                  onClick={() => removeItem(it.uid)}
                  className="rounded p-1 text-muted-foreground hover:text-destructive transition shrink-0"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {/* Row 2: controls */}
              <div className="flex items-center gap-2 pl-13">
                <div className="flex items-center gap-1">
                  <Button
                    size="icon"
                    variant="outline"
                    className="h-9 w-9 sm:h-7 sm:w-7"
                    onClick={() => updateItem(it.uid, { cantidad: Math.max(1, it.cantidad - 1) })}
                  >
                    <Minus className="h-3 w-3" />
                  </Button>
                  <DraftNumberInput
                    min={1}
                    value={it.cantidad}
                    onCommit={(v) => updateItem(it.uid, { cantidad: v })}
                    ariaLabel="Cantidad"
                    className={cn(
                      "h-9 w-10 text-center text-sm p-0 sm:h-7",
                      overstock && "border-destructive text-destructive",
                    )}
                  />
                  <Button
                    size="icon"
                    variant="outline"
                    className="h-9 w-9 sm:h-7 sm:w-7"
                    onClick={() => updateItem(it.uid, { cantidad: it.cantidad + 1 })}
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
                <div className="flex items-center gap-1 ml-2">
                  {isCliente ? (
                    <div className="h-9 sm:h-7 px-2 inline-flex items-center text-sm text-muted-foreground tabular-nums">
                      {fmtArs(it.precio_jornada)}
                    </div>
                  ) : (
                    <DraftNumberInput
                      min={0}
                      value={it.precio_jornada}
                      onCommit={(v) => updateItem(it.uid, { precio_jornada: v })}
                      ariaLabel="Precio por jornada"
                      className="h-9 w-24 text-sm text-base sm:text-sm sm:h-7"
                    />
                  )}
                  {/* cobro_modo='fijo' (ej. centinela del Estudio en un pedido
                      de taller): no se multiplica por jornadas, "/día" mentiría. */}
                  <span className="text-xs text-muted-foreground whitespace-nowrap">
                    {it.cobro_modo === "fijo" ? "fijo" : "/día"}
                  </span>
                </div>
                {overstock && (
                  <div className="ml-auto text-xs text-destructive flex items-center gap-1">
                    <AlertTriangle className="h-3 w-3" /> Excede stock (faltan{" "}
                    {Math.abs(disponible ?? 0)})
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      <EquipoSearchSheet
        open={openSearch}
        onOpenChange={setOpenSearch}
        existing={items}
        stockMap={stockMap}
        onAdd={(eq) => {
          const display = eq.nombre_publico || eq.nombre;
          const idx = items.findIndex((i) => i.equipo_id === eq.id);
          if (idx >= 0) {
            updateItem(items[idx].uid, { cantidad: items[idx].cantidad + 1 });
            toast.success(`+1 ${display}`);
          } else {
            setItems([
              ...items,
              {
                uid: `e${eq.id}`,
                equipo_id: eq.id,
                cantidad: 1,
                precio_jornada: eq.precio_jornada ?? 0,
                nombre: eq.nombre,
                marca: eq.marca,
                nombre_publico: eq.nombre_publico ?? null,
                cobro_modo: "jornada",
              },
            ]);
            toast.success(`Agregado: ${display}`);
          }
          setOpenSearch(false);
        }}
      />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Totales card
// ─────────────────────────────────────────────────────────────────────────

export function TotalesCard({
  bruto,
  brutoDescontable,
  totalNeto,
  total,
  conIva,
  ivaPct,
  ivaMonto,
  jornadas,
  descuentoPct,
  setDescuentoPct,
  descuentoManualTipo,
  setDescuentoManualTipo,
  descuentoManualMonto,
  setDescuentoManualMonto,
  descuentoEfectivoPct,
  descuentoOrigen,
  nombreCliente,
  pagado,
  saldo,
  mode = "admin",
}: {
  bruto: number;
  /** Bruto SIN las líneas de combo (C-3, #1219) — tope real del input $ del
   *  override manual: no se le puede descontar más a un pedido que a su
   *  parte descontable. */
  brutoDescontable: number;
  totalNeto: number;
  total: number;
  conIva: boolean;
  ivaPct: number;
  ivaMonto: number;
  jornadas: number;
  /** Override MANUAL crudo (`alquileres.descuento_pct`, 0 = sin override) —
   * solo para el input editable del admin. Para MOSTRAR usar
   * `descuentoEfectivoPct`/`descuentoOrigen` (el que ganó de verdad). */
  descuentoPct: number;
  setDescuentoPct: (v: number) => void;
  /** Fase C-2 (#1219): tipo del override manual — "pct" (usa `descuentoPct`)
   * o "monto" (usa `descuentoManualMonto`, $ fijo). Mismo campo, un selector. */
  descuentoManualTipo: "pct" | "monto";
  setDescuentoManualTipo: (v: "pct" | "monto") => void;
  descuentoManualMonto: number;
  setDescuentoManualMonto: (v: number) => void;
  /** % ganador real (jerarquía manual > cliente > jornadas, `/api/cotizar`). */
  descuentoEfectivoPct: number;
  descuentoOrigen: DescuentoOrigen;
  nombreCliente?: string | null;
  pagado: number;
  saldo: number;
  mode?: PedidoMode;
}) {
  const isCliente = mode === "cliente";
  const labelDescuento = descuentoLabel(descuentoOrigen, jornadas, nombreCliente);
  return (
    <section className="card overflow-hidden">
      <div className="px-4 py-3 space-y-2.5 text-sm">
        <div className="flex justify-between text-muted-foreground">
          <span>Subtotal</span>
          <span className="tabular-nums">{fmtArs(bruto)}</span>
        </div>
        {isCliente ? (
          descuentoEfectivoPct > 0 && (
            <div className="flex items-center justify-between gap-3 text-muted-foreground">
              <span>{labelDescuento || `Descuento ${descuentoEfectivoPct}%`}</span>
              <span className="tabular-nums">−{fmtArs(bruto - totalNeto)}</span>
            </div>
          )
        ) : (
          <div className="flex items-center justify-between gap-3">
            <span className="text-muted-foreground">Descuento manual (0 = automático)</span>
            <div className="flex items-center gap-1.5">
              <SegmentedControl
                value={descuentoManualTipo}
                onChange={(v) => setDescuentoManualTipo(v as "pct" | "monto")}
                options={[
                  { value: "pct", label: "%" },
                  { value: "monto", label: "$" },
                ]}
                className="w-16 shrink-0"
              />
              {descuentoManualTipo === "monto" ? (
                <MoneyInput
                  min={0}
                  max={brutoDescontable}
                  step={100}
                  value={descuentoManualMonto}
                  onChange={setDescuentoManualMonto}
                  ariaLabel="Descuento $ manual"
                  className="h-7 w-28 text-right text-sm"
                />
              ) : (
                <DraftNumberInput
                  min={0}
                  max={100}
                  step="0.1"
                  value={descuentoPct}
                  onCommit={setDescuentoPct}
                  ariaLabel="Descuento % manual"
                  className="h-7 w-20 text-right text-sm"
                />
              )}
            </div>
          </div>
        )}
        {/* Fila de MONTO del descuento efectivo — no del override crudo (que
            puede estar en 0 mientras igual gana cliente/jornadas). */}
        {!isCliente && descuentoEfectivoPct > 0 && (
          <div className="flex justify-between text-muted-foreground">
            <span>{labelDescuento || `−${descuentoEfectivoPct}%`}</span>
            <span className="tabular-nums">−{fmtArs(bruto - totalNeto)}</span>
          </div>
        )}
        {conIva && (
          <>
            <div className="flex justify-between text-muted-foreground">
              <span>Subtotal neto</span>
              <span className="tabular-nums">{fmtArs(totalNeto)}</span>
            </div>
            <div className="flex justify-between text-muted-foreground">
              <span>IVA {ivaPct}%</span>
              <span className="tabular-nums">+{fmtArs(ivaMonto)}</span>
            </div>
          </>
        )}
        <div className="flex justify-between border-t hairline pt-2.5 font-semibold text-ink">
          <span>Total{conIva ? " · IVA incluído" : ""}</span>
          <span className="tabular-nums">{fmtArs(total)}</span>
        </div>
        {jornadas > 0 && (
          <div className="text-xs text-muted-foreground text-right">
            {jornadas} jornada{jornadas !== 1 ? "s" : ""}
          </div>
        )}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Pagos sidebar
// ─────────────────────────────────────────────────────────────────────────

export function PagosSidebar({
  pedidoId,
  total,
  pagado,
  saldo,
  pagos,
}: {
  pedidoId: number;
  total: number;
  pagado: number;
  saldo: number;
  pagos: {
    id: number;
    monto: number;
    concepto: string | null;
    fecha: string;
    anulado?: boolean;
    anulado_motivo?: string | null;
  }[];
}) {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [monto, setMonto] = useState("");
  const [concepto, setConcepto] = useState("");

  const addMut = useMutation({
    mutationFn: () => adminApi.addPago(pedidoId, parseInt(monto || "0", 10), concepto || undefined),
    onSuccess: () => {
      toast.success("Pago registrado");
      setMonto("");
      setConcepto("");
      setShowForm(false);
      qc.invalidateQueries({ queryKey: ["admin", "pedido", pedidoId] });
      qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const delMut = useMutation({
    mutationFn: ({ pagoId, motivo }: { pagoId: number; motivo: string }) =>
      adminApi.anularPago(pedidoId, pagoId, motivo),
    onSuccess: () => {
      toast.success("Pago anulado");
      qc.invalidateQueries({ queryKey: ["admin", "pedido", pedidoId] });
      qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const estadoPago = saldo <= 0 ? "pagado" : "pendiente";

  return (
    <div className="space-y-3">
      {/* Badge estado + importes */}
      <Pill tone={estadoPago === "pagado" ? "success" : "warning"} className="px-3 py-1 text-xs">
        {estadoPago === "pagado" ? "Pagado" : "Pago pendiente"}
      </Pill>
      <div className="text-sm space-y-1">
        <div className="flex justify-between text-muted-foreground">
          <span>Pagado</span>
          <span className="tabular-nums">{fmtArs(pagado)}</span>
        </div>
        <div className="flex justify-between font-medium text-ink">
          <span>Debido</span>
          <span className="tabular-nums">{fmtArs(total)}</span>
        </div>
      </div>

      {/* Historial */}
      {pagos.length > 0 && (
        <div className="divide-y hairline rounded-md border hairline overflow-hidden">
          {pagos.map((pg) => (
            <div
              key={pg.id}
              className={cn(
                "flex items-center justify-between px-3 py-2 text-xs",
                pg.anulado && "opacity-50",
              )}
            >
              <div>
                <div
                  className={cn("tabular-nums font-medium text-ink", pg.anulado && "line-through")}
                >
                  {fmtArs(pg.monto)}
                </div>
                <div className="text-muted-foreground">
                  <span className={cn(pg.anulado && "line-through")}>
                    {pg.fecha}
                    {pg.concepto ? ` · ${pg.concepto}` : ""}
                  </span>
                  {pg.anulado && pg.anulado_motivo && (
                    <span className="text-destructive"> · Anulado: {pg.anulado_motivo}</span>
                  )}
                </div>
              </div>
              {!pg.anulado && (
                <button
                  type="button"
                  onClick={() => {
                    const motivo = window.prompt("Motivo de la anulación del pago:");
                    if (motivo && motivo.trim())
                      delMut.mutate({ pagoId: pg.id, motivo: motivo.trim() });
                  }}
                  disabled={delMut.isPending}
                  className="rounded p-1 text-muted-foreground hover:text-destructive transition"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Nuevo pago */}
      {showForm ? (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label className="text-xs">Monto</Label>
              <Input
                type="number"
                value={monto}
                onChange={(e) => setMonto(e.target.value)}
                placeholder="0"
                className="h-8 text-sm text-base sm:text-sm"
              />
            </div>
            <div>
              <Label className="text-xs">Concepto</Label>
              <Input
                value={concepto}
                onChange={(e) => setConcepto(e.target.value)}
                placeholder="Seña, saldo…"
                className="h-8 text-sm text-base sm:text-sm"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              className="flex-1"
              onClick={() => {
                const n = parseInt(monto || "0", 10);
                if (!n || n <= 0) return toast.error("Monto inválido");
                addMut.mutate();
              }}
              disabled={addMut.isPending}
            >
              {addMut.isPending ? <Spinner size="xs" /> : <Check className="h-3.5 w-3.5" />} Guardar
            </Button>
            <Button size="sm" variant="outline" onClick={() => setShowForm(false)}>
              Cancelar
            </Button>
          </div>
        </div>
      ) : (
        <Button variant="outline" size="sm" className="w-full" onClick={() => setShowForm(true)}>
          <Plus className="h-3.5 w-3.5 mr-1" /> Nuevo Pago
        </Button>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Documentos sidebar
// ─────────────────────────────────────────────────────────────────────────

export function DocumentosSidebar({
  pedidoId,
  clienteEmail,
}: {
  pedidoId: number;
  clienteEmail: string;
}) {
  const [mailOpen, setMailOpen] = useState(false);

  return (
    <div className="space-y-1.5">
      {DOCS_PEDIDO.map((d) => (
        <div key={d.kind} className="flex items-center gap-2 rounded-md border hairline px-3 py-2">
          <d.Icon className="h-4 w-4 text-muted-foreground shrink-0" />
          <span className="flex-1 text-sm text-ink">{d.label}</span>
          <div className="flex items-center gap-1 shrink-0">
            <a
              href={`${pedidoPdfUrl(pedidoId, d.kind)}?format=html`}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded p-1 text-muted-foreground hover:text-ink transition"
              title="Ver"
            >
              <Eye className="h-3.5 w-3.5" />
            </a>
            <a
              href={pedidoPdfUrl(pedidoId, d.kind)}
              className="rounded p-1 text-muted-foreground hover:text-ink transition"
              title="Descargar PDF"
            >
              <Download className="h-3.5 w-3.5" />
            </a>
          </div>
        </div>
      ))}

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-full mt-1"
        onClick={() => setMailOpen(true)}
      >
        <Mail className="h-4 w-4 mr-1.5" />
        Enviar por mail
      </Button>

      <EnviarDocsDialog
        pedidoId={pedidoId}
        clienteEmail={clienteEmail}
        open={mailOpen}
        onOpenChange={setMailOpen}
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Historial de modificaciones del cliente (sidebar admin)
// ─────────────────────────────────────────────────────────────────────────

const HIST_ESTADO_VARIANT: Record<
  PedidoHistorialItem["estado"],
  "default" | "secondary" | "destructive" | "outline"
> = {
  pendiente: "secondary",
  aprobada: "default",
  rechazada: "destructive",
  cancelada: "outline",
};

const HIST_ESTADO_LABEL: Record<PedidoHistorialItem["estado"], string> = {
  pendiente: "Pendiente",
  aprobada: "Aprobada",
  rechazada: "Rechazada",
  cancelada: "Cancelada",
};

export function HistorialModificaciones({ items }: { items: PedidoHistorialItem[] }) {
  return (
    <ol className="space-y-2.5">
      {items.map((h) => {
        const c = h.cambios_json;
        const a = h.cambios_aplicados;
        const itemDeltas = Array.isArray(c?.items) ? (c?.items ?? []) : [];
        const isDirecto = h.tipo === "directo";
        // Si lo aplicado difiere de lo propuesto, marcamos "Modificada por admin".
        const overrideAplicado = !!(
          a &&
          c &&
          ((a.fecha_desde ?? null) !== (c.fecha_desde ?? null) ||
            (a.fecha_hasta ?? null) !== (c.fecha_hasta ?? null) ||
            (a.items?.length ?? 0) !== (c.items?.length ?? 0) ||
            (a.items ?? []).some((ai) => {
              const ci = (c.items ?? []).find((x) => x.equipo_id === ai.equipo_id);
              return !ci || ci.cantidad !== ai.cantidad;
            }))
        );
        return (
          <li key={h.id} className="rounded border hairline bg-card px-2.5 py-2">
            <div className="flex items-center gap-1.5 flex-wrap">
              <Badge variant={HIST_ESTADO_VARIANT[h.estado]} className="text-2xs">
                {HIST_ESTADO_LABEL[h.estado]}
              </Badge>
              {isDirecto && (
                <span className="text-2xs uppercase tracking-wide text-muted-foreground">Auto</span>
              )}
              {overrideAplicado && <span className="text-2xs text-ink">modificada al aprobar</span>}
              <span className="ml-auto text-2xs text-muted-foreground tabular-nums">
                {fmtFecha(h.created_at)}
              </span>
            </div>
            {(c?.fecha_desde || c?.fecha_hasta) && (
              <div className="text-xs text-muted-foreground mt-1.5 tabular-nums">
                Fechas: {fmtFecha(c?.fecha_desde ?? "")} → {fmtFecha(c?.fecha_hasta ?? "")}
              </div>
            )}
            {itemDeltas.length > 0 && (
              <div className="text-xs text-muted-foreground mt-1">
                {itemDeltas.length} item{itemDeltas.length !== 1 ? "s" : ""} en la propuesta
              </div>
            )}
            {overrideAplicado && a && (
              <div className="text-xs text-ink mt-1 tabular-nums">
                Aplicado: {fmtFecha(a.fecha_desde ?? "")} → {fmtFecha(a.fecha_hasta ?? "")}
                {a.items && ` · ${a.items.length} item${a.items.length !== 1 ? "s" : ""}`}
              </div>
            )}
            {h.mensaje && (
              <div className="text-xs text-ink mt-1.5 whitespace-pre-wrap line-clamp-3">
                {h.mensaje}
              </div>
            )}
            {h.respuesta && (
              <div className="text-xs text-muted-foreground mt-1.5 italic line-clamp-2">
                Respuesta: {h.respuesta}
              </div>
            )}
            {h.resolved_by && h.resolved_at && (
              <div className="text-2xs text-muted-foreground mt-1">
                {h.resolved_by} · {fmtFecha(h.resolved_at)}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Modal de confirmación con diff (cliente, modo propose)
// ─────────────────────────────────────────────────────────────────────────

export function SolicitudDiffDialog({
  open,
  onOpenChange,
  original,
  datos,
  items,
  isSubmitting,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  original: {
    fecha_desde: string | null;
    fecha_hasta: string | null;
    items: {
      equipo_id: number | null;
      cantidad: number;
      nombre: string;
      nombre_publico?: string | null;
    }[];
  };
  datos: DraftDatos;
  items: DraftItem[];
  isSubmitting: boolean;
  onConfirm: () => void;
}) {
  const origDesde = (original.fecha_desde ?? "").slice(0, 10);
  const origHasta = (original.fecha_hasta ?? "").slice(0, 10);
  const fechasCambian = origDesde !== datos.fecha_desde || origHasta !== datos.fecha_hasta;

  // Diff por equipo (cliente no maneja líneas personalizadas #805 → equipo_id null fuera).
  const beforeQty = new Map<number, number>();
  for (const it of original.items)
    if (it.equipo_id != null) beforeQty.set(it.equipo_id, it.cantidad);
  const afterQty = new Map<number, number>();
  for (const it of items) if (it.equipo_id != null) afterQty.set(it.equipo_id, it.cantidad);
  const nombres = new Map<number, string>();
  for (const it of original.items)
    if (it.equipo_id != null) nombres.set(it.equipo_id, it.nombre_publico || it.nombre);
  for (const it of items) {
    if (it.equipo_id != null && !nombres.has(it.equipo_id))
      nombres.set(it.equipo_id, it.nombre_publico || it.nombre);
  }
  const equipoIds = new Set<number>([...beforeQty.keys(), ...afterQty.keys()]);
  const itemsDiff = Array.from(equipoIds)
    .map((id) => ({
      id,
      antes: beforeQty.get(id) ?? 0,
      despues: afterQty.get(id) ?? 0,
      nombre: nombres.get(id) ?? `equipo #${id}`,
    }))
    .filter((d) => d.antes !== d.despues);

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="max-w-lg max-h-[85vh] flex flex-col">
        <AlertDialogHeader>
          <AlertDialogTitle>Confirmar solicitud de modificación</AlertDialogTitle>
          <AlertDialogDescription>
            Estos son los cambios que vas a pedirnos. Te avisamos por mail cuando los revisemos.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-3 max-h-[50vh] overflow-y-auto">
          {fechasCambian && (
            <div className="rounded-md border hairline px-3 py-2.5 text-sm">
              <div className="text-xs text-muted-foreground mb-1">Fechas</div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <div className="text-muted-foreground">Antes</div>
                  <div className="text-ink tabular-nums">
                    {fmtFecha(origDesde)} → {fmtFecha(origHasta)}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">Nuevas</div>
                  <div className="text-ink font-medium tabular-nums">
                    {fmtFecha(datos.fecha_desde)} → {fmtFecha(datos.fecha_hasta)}
                  </div>
                </div>
              </div>
            </div>
          )}

          {itemsDiff.length > 0 && (
            <div className="rounded-md border hairline px-3 py-2.5 text-sm">
              <div className="text-xs text-muted-foreground mb-2">Equipos</div>
              <ul className="divide-y hairline -mx-3">
                {itemsDiff.map((d) => {
                  const delta = d.despues - d.antes;
                  const cls = delta > 0 ? "text-verde-ink" : "text-destructive";
                  return (
                    <li key={d.id} className="px-3 py-1.5 flex items-center gap-2">
                      <span className="flex-1 text-ink truncate">{d.nombre}</span>
                      <span className="text-muted-foreground tabular-nums">{d.antes}</span>
                      <span className="text-muted-foreground">→</span>
                      <span className={`font-medium tabular-nums ${cls}`}>{d.despues}</span>
                      <span className={`text-xs tabular-nums w-10 text-right ${cls}`}>
                        {delta > 0 ? `+${delta}` : delta}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {!fechasCambian && itemsDiff.length === 0 && (
            <div className="text-sm text-muted-foreground">Sin cambios detectados.</div>
          )}
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel disabled={isSubmitting}>Volver</AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => {
              e.preventDefault();
              onConfirm();
            }}
            disabled={isSubmitting || (!fechasCambian && itemsDiff.length === 0)}
          >
            {isSubmitting ? "Enviando…" : "Enviar solicitud"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
