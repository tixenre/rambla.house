/**
 * contabilidad.movimientos.lazy.tsx — Libro de movimientos (#809, Fase 2/3).
 *
 * Registra y lista los movimientos manuales de plata: gastos, transferencias
 * entre cajas, retiros y aportes de socios. Los cobros de pedidos aparecen como
 * una línea mensual read-only (derivan de los pagos de alquiler, no se cargan a
 * mano) que se DESPLIEGA para ver los pagos individuales del mes inline — misma
 * fuente única que /admin/pagos (el "ver ledger completo"). La plata nunca se
 * borra: anular deja el registro tachado con su motivo.
 */
import { createLazyFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Wallet } from "lucide-react";
import { toast } from "sonner";

import {
  adminApi,
  TIPOS_MOVIMIENTO,
  type CobroMensual,
  type Cuenta,
  type Movimiento,
} from "@/lib/admin/api";
import { MoverPlataForm } from "@/components/admin/contabilidad/MoverPlataForm";
import { CorregirSaldoForm } from "@/components/admin/contabilidad/CorregirSaldoForm";
import { CuentaSelect, Field } from "@/components/admin/contabilidad/fields";
import { AdminPage } from "@/components/admin/AdminPage";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { QueryState } from "@/components/admin/QueryState";
import { TableSkeleton } from "@/components/admin/skeletons";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { formatMoney, formatFechaDisplay } from "@/lib/format";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { Badge } from "@/design-system/ui/badge";
import { TipoMovimientoBadge, TIPO_MOVIMIENTO_META } from "@/components/admin/badges";
import { cn } from "@/lib/utils";

export const Route = createLazyFileRoute("/admin/contabilidad/movimientos")({
  component: MovimientosPage,
});

function descMovimiento(m: Movimiento): string {
  const o = m.cuenta_origen_nombre ?? "—";
  const d = m.cuenta_destino_nombre ?? "—";
  switch (m.tipo) {
    case "gasto":
      return `${m.categoria_nombre ?? "Sin categoría"} · sale de ${o}`;
    case "transferencia":
      return `${o} → ${d}`;
    case "retiro":
      return `Retiro de ${o}`;
    case "aporte":
      return `Aporte a ${d}`;
    default: {
      // Cambio de divisa: cada pata es un `ajuste` con una sola cuenta y
      // `cotizacion` seteada (ver mover-plata.ts / commands/movimientos.py).
      if (m.cotizacion != null) {
        const cta = o !== "—" ? o : d;
        return `Cambio de divisa · ${o !== "—" ? "sale de" : "entra a"} ${cta} (cotización ${m.cotizacion})`;
      }
      return [o !== "—" ? o : null, d !== "—" ? d : null].filter(Boolean).join(" → ") || "Ajuste";
    }
  }
}

type Fila =
  | { kind: "mov"; fecha: string; mov: Movimiento }
  | { kind: "cobro"; fecha: string; cobro: CobroMensual };

// Fecha del último día del mes (para ordenar la línea de cobro al cierre del mes).
function finDeMes(mes: string): string {
  const [y, m] = mes.split("-").map(Number);
  const dia = new Date(y, m, 0).getDate();
  return `${mes}-${String(dia).padStart(2, "0")}`;
}

function mesLabel(mes: string): string {
  return new Date(`${mes}-01T00:00:00`).toLocaleDateString("es-AR", {
    month: "long",
    year: "numeric",
  });
}

// Dirección de la plata (guía visual estilo debe/haber): entra (haber, verde +),
// sale (debe, rojo −) o interno (transferencia/ajuste entre dos cajas, neutro).
type Direccion = "in" | "out" | "neutral";
function direccionMov(m: Movimiento): Direccion {
  const origen = !!m.cuenta_origen_id;
  const destino = !!m.cuenta_destino_id;
  if (origen && !destino) return "out";
  if (destino && !origen) return "in";
  return "neutral";
}
function montoClass(dir: Direccion): string {
  return dir === "in" ? "text-verde-ink" : dir === "out" ? "text-destructive" : "text-ink";
}
function montoSigno(dir: Direccion): string {
  return dir === "in" ? "+ " : dir === "out" ? "− " : "";
}

function MovimientosPage() {
  useDocumentTitle("Movimientos · Finanzas");
  const qc = useQueryClient();
  const [tipoFiltro, setTipoFiltro] = useState<string>("");
  const [beneficiarioFiltro, setBeneficiarioFiltro] = useState<string>("");
  const [cuentaFiltro, setCuentaFiltro] = useState<string>("");
  // Mes del cobro expandido (muestra los pagos individuales inline). Uno a la vez.
  const [expandedMes, setExpandedMes] = useState<string | null>(null);

  const invalidar = () => qc.invalidateQueries({ queryKey: ["admin", "contabilidad"] });

  const cuentasQ = useQuery({
    queryKey: ["admin", "contabilidad", "cuentas-list"],
    queryFn: () => adminApi.listCuentas(),
  });
  const cuentas: Cuenta[] = cuentasQ.data?.cuentas ?? [];

  const movsQ = useQuery({
    queryKey: [
      "admin",
      "contabilidad",
      "movimientos",
      { tipo: tipoFiltro, ben: beneficiarioFiltro, cuenta: cuentaFiltro },
    ],
    queryFn: () =>
      adminApi.listMovimientos({
        tipo: tipoFiltro || undefined,
        beneficiario: beneficiarioFiltro || undefined,
        cuenta_id: cuentaFiltro ? Number(cuentaFiltro) : undefined,
      }),
  });

  // Vista unificada: movimientos manuales + cobros de pedidos (agregados por mes,
  // read-only), ordenados por fecha.
  const filas: Fila[] = [];
  if (movsQ.data) {
    for (const m of movsQ.data.movimientos) filas.push({ kind: "mov", fecha: m.fecha, mov: m });
    for (const c of movsQ.data.cobros ?? [])
      filas.push({ kind: "cobro", fecha: finDeMes(c.mes), cobro: c });
    filas.sort((a, b) => b.fecha.localeCompare(a.fecha));
  }

  const columns: Column<Fila>[] = [
    {
      header: "Fecha",
      cell: (f) =>
        f.kind === "mov" ? (
          formatFechaDisplay(f.mov.fecha)
        ) : (
          <span className="capitalize">{mesLabel(f.cobro.mes)}</span>
        ),
      className: "whitespace-nowrap text-muted-foreground",
    },
    {
      header: "Tipo",
      cell: (f) =>
        f.kind === "mov" ? (
          <TipoMovimientoBadge tipo={f.mov.tipo} />
        ) : (
          <Badge variant="secondary">Cobros</Badge>
        ),
    },
    {
      header: "Detalle",
      cell: (f) =>
        f.kind === "mov" ? (
          <>
            <span className={cn(f.mov.anulado && "line-through")}>{descMovimiento(f.mov)}</span>
            {f.mov.beneficiario && (
              <div>
                <button
                  type="button"
                  onClick={() => setBeneficiarioFiltro(f.mov.beneficiario!)}
                  className="text-xs text-ink underline decoration-amber/60 underline-offset-2 hover:decoration-amber"
                  title="Ver el historial de este beneficiario"
                >
                  {f.mov.beneficiario}
                </button>
              </div>
            )}
            {f.mov.nota && <div className="text-xs text-muted-foreground">{f.mov.nota}</div>}
            {f.mov.anulado && f.mov.anulado_motivo && (
              <div className="text-xs text-destructive">Anulado: {f.mov.anulado_motivo}</div>
            )}
            {f.mov.comprobante_url && (
              <a
                href={f.mov.comprobante_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-ink underline decoration-amber/60 underline-offset-2 hover:decoration-amber"
              >
                Ver comprobante
              </a>
            )}
          </>
        ) : (
          <>
            <span className="capitalize text-ink">Cobro alquileres · {mesLabel(f.cobro.mes)}</span>
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <ChevronDown
                className={cn(
                  "h-3.5 w-3.5 transition-transform",
                  expandedMes === f.cobro.mes && "rotate-180",
                )}
              />
              {f.cobro.cantidad} pago(s) — {expandedMes === f.cobro.mes ? "ocultar" : "ver detalle"}
            </div>
          </>
        ),
    },
    {
      header: "Monto",
      cell: (f) =>
        f.kind === "mov" ? (
          <span className={montoClass(direccionMov(f.mov))}>
            {montoSigno(direccionMov(f.mov))}
            {formatMoney(f.mov.monto, f.mov.moneda)}
          </span>
        ) : (
          <span className="text-verde-ink">+ {formatMoney(f.cobro.monto, "ARS")}</span>
        ),
      align: "right",
      className: "font-mono tabular-nums",
    },
    {
      header: "Acciones",
      cell: (f) =>
        f.kind === "mov" ? (
          <AnularMovimiento mov={f.mov} onChanged={invalidar} />
        ) : (
          <span className="text-xs text-muted-foreground">automático</span>
        ),
      align: "right",
    },
  ];

  return (
    <AdminPage
      title="Movimientos"
      maxW="list"
      description="Toda la plata de las cajas: los cobros de pedidos (que entran solos, una línea por mes) más los gastos, transferencias, retiros y aportes."
      backTo={{ to: "/admin/contabilidad", label: "Tablero" }}
    >
      <div className="space-y-6">
        {/* Una sola entrada. Antes había que elegir modo (movimiento / cambio de
            divisa) y después uno de 5 tipos contables — 6 decisiones de vocabulario
            antes de cargar un peso. `MoverPlataForm` pregunta qué pasó y deriva el
            tipo solo (`lib/admin/mover-plata.ts`). El `ajuste` queda aparte y
            colapsado, con nota obligatoria: es la puerta de "el modelo no captura
            la realidad", no una opción más. */}
        <MoverPlataForm onCreated={invalidar} />
        <CorregirSaldoForm onCreated={invalidar} />

        {/* Filtro por tipo + cuenta */}
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-wrap gap-1">
            {[
              ["", "Todos"],
              ["cobro", "Cobros"],
              ...TIPOS_MOVIMIENTO.map(
                (t) => [t, TIPO_MOVIMIENTO_META[t].label] as [string, string],
              ),
            ].map(([val, lbl]) => (
              <button
                key={val}
                type="button"
                onClick={() => setTipoFiltro(val)}
                className={cn(
                  "rounded-md border px-2.5 py-1.5 text-xs font-medium transition",
                  tipoFiltro === val
                    ? "border-ink bg-ink text-background"
                    : "border-muted-foreground/30 text-muted-foreground hover:border-ink hover:text-ink",
                )}
              >
                {lbl}
              </button>
            ))}
          </div>
          <Field label="Cuenta">
            <CuentaSelect
              cuentas={cuentas}
              value={cuentaFiltro}
              onChange={setCuentaFiltro}
              placeholder="Todas las cuentas"
            />
          </Field>
        </div>

        {beneficiarioFiltro && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Beneficiario:</span>
            <span className="rounded-md bg-ink px-2 py-0.5 text-xs text-background">
              {beneficiarioFiltro}
            </span>
            <button
              type="button"
              onClick={() => setBeneficiarioFiltro("")}
              className="text-xs text-muted-foreground hover:text-ink underline"
            >
              quitar
            </button>
          </div>
        )}

        <QueryState
          query={movsQ}
          isEmpty={(d) => d.movimientos.length === 0 && (d.cobros ?? []).length === 0}
          skeleton={<TableSkeleton rows={6} cols={5} />}
          empty={
            <EmptyState
              icon={<Wallet className="h-6 w-6" />}
              title="No hay movimientos"
              sub="Todavía no hay movimientos para este filtro."
            />
          }
        >
          {() => (
            <AdminTable
              columns={columns}
              rows={filas}
              getRowKey={(f) => (f.kind === "mov" ? `m${f.mov.id}` : `c${f.cobro.mes}`)}
              rowClassName={(f) =>
                f.kind === "mov"
                  ? cn("cursor-default", f.mov.anulado && "opacity-50")
                  : "bg-muted/10"
              }
              onRowClick={(f) => {
                if (f.kind === "cobro")
                  setExpandedMes((m) => (m === f.cobro.mes ? null : f.cobro.mes));
              }}
              isExpanded={(f) => f.kind === "cobro" && expandedMes === f.cobro.mes}
              renderExpanded={(f) =>
                f.kind === "cobro" ? <CobroDetalle mes={f.cobro.mes} /> : null
              }
            />
          )}
        </QueryState>
      </div>
    </AdminPage>
  );
}

/** Detalle desplegable de un cobro mensual: los pagos individuales de ese mes,
 *  traídos del ledger único de pagos (read-only, misma fuente que Cobros). */
function CobroDetalle({ mes }: { mes: string }) {
  const desde = `${mes}-01`;
  const hasta = finDeMes(mes);
  const q = useQuery({
    queryKey: ["admin", "pagos", "mes", mes],
    queryFn: () => adminApi.listPagosLog({ desde, hasta }),
  });

  if (q.isLoading) {
    return <div className="px-4 py-3 text-xs text-muted-foreground">Cargando pagos…</div>;
  }
  if (q.isError) {
    return (
      <div className="px-4 py-3 text-xs text-destructive">No se pudieron cargar los pagos.</div>
    );
  }
  const pagos = q.data?.pagos ?? [];
  if (pagos.length === 0) {
    return <div className="px-4 py-3 text-xs text-muted-foreground">Sin pagos en el mes.</div>;
  }

  return (
    <div className="space-y-1.5 px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="t-eyebrow">Pagos del mes</div>
        <Link
          to="/admin/pagos"
          className="text-xs text-ink underline decoration-amber/60 underline-offset-2 hover:decoration-amber"
        >
          ver ledger completo →
        </Link>
      </div>
      <div className="divide-y hairline card-elevated">
        {pagos.map((p) => (
          <div key={p.id} className="flex items-center gap-3 px-3 py-1.5 text-xs">
            <span className="whitespace-nowrap text-muted-foreground">
              {formatFechaDisplay(p.fecha)}
            </span>
            <Link
              to="/admin/pedidos/$id"
              params={{ id: String(p.pedido_id) }}
              className="whitespace-nowrap font-mono text-ink underline decoration-amber/60 underline-offset-2 hover:decoration-amber"
            >
              #{p.numero_pedido ?? p.pedido_id}
            </Link>
            <span className="flex-1 truncate text-muted-foreground">{p.cliente_nombre ?? "—"}</span>
            <span className="whitespace-nowrap capitalize text-muted-foreground">
              {p.metodo ?? "—"}
            </span>
            <span className="whitespace-nowrap font-mono tabular-nums text-ink">
              {formatMoney(p.monto, "ARS")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AnularMovimiento({ mov, onChanged }: { mov: Movimiento; onChanged: () => void }) {
  const anular = useMutation({
    mutationFn: (motivo: string) => adminApi.anularMovimiento(mov.id, motivo),
    onSuccess: () => {
      toast.success("Movimiento anulado");
      onChanged();
    },
    onError: (e) => toast.error("No se pudo anular", { description: (e as Error).message }),
  });

  if (mov.anulado) return null;

  return (
    <button
      type="button"
      onClick={() => {
        const motivo = window.prompt("Motivo de la anulación:");
        if (motivo && motivo.trim()) anular.mutate(motivo.trim());
      }}
      disabled={anular.isPending}
      className="text-xs text-muted-foreground hover:text-destructive underline"
    >
      Anular
    </button>
  );
}
