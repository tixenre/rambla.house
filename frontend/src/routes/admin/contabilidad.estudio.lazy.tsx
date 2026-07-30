/**
 * contabilidad.estudio.lazy.tsx — Caja Estudio, economía separada del Estudio.
 *
 * Agrega datos que YA existen (saldo de la cuenta "Caja Estudio" vía `/saldos`,
 * sus movimientos + cobros mensuales vía `/movimientos?cuenta_id=`, y su fila
 * de la rendición mensual vía `/rendicion/{mes}`) en una vista dedicada — no
 * hay lógica nueva, todo sale de los mismos motores que ya alimentan
 * Cuentas/Movimientos/Rendición. El registro/anulación de movimientos sigue
 * viviendo en Movimientos (una sola forma de escribir plata); acá es lectura.
 */
import { createLazyFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Banknote, Clapperboard, ChevronDown, Clock, Wallet } from "lucide-react";

import { AdminPage } from "@/components/admin/AdminPage";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { QueryState } from "@/components/admin/QueryState";
import { TableSkeleton } from "@/components/admin/skeletons";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { Section } from "@/design-system/composites/Section";
import { StatCard } from "@/design-system/composites/StatCard";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { TipoMovimientoBadge } from "@/components/admin/badges";
import { adminApi, type CobroMensual, type Movimiento } from "@/lib/admin/api";
import { formatARS, formatMoney, formatFechaDisplay } from "@/lib/format";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { cn } from "@/lib/utils";

export const Route = createLazyFileRoute("/admin/contabilidad/estudio")({
  component: CajaEstudioPage,
});

function mesActual() {
  return new Date().toISOString().slice(0, 7);
}

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

type Fila =
  | { kind: "mov"; fecha: string; mov: Movimiento }
  | { kind: "cobro"; fecha: string; cobro: CobroMensual };

function descMovimiento(m: Movimiento): string {
  const o = m.cuenta_origen_nombre ?? "—";
  const d = m.cuenta_destino_nombre ?? "—";
  switch (m.tipo) {
    case "gasto":
      return `${m.categoria_nombre ?? "Sin categoría"} · sale de ${o}`;
    case "transferencia":
      return `${o} → ${d}`;
    case "aporte":
      return `Aporte a ${d}`;
    default:
      return [o !== "—" ? o : null, d !== "—" ? d : null].filter(Boolean).join(" → ") || "Ajuste";
  }
}

function CajaEstudioPage() {
  useDocumentTitle("Caja Estudio · Finanzas");
  const [mes, setMes] = useState(mesActual());
  const [expandedMes, setExpandedMes] = useState<string | null>(null);

  const saldosQ = useQuery({
    queryKey: ["admin", "contabilidad", "saldos"],
    queryFn: () => adminApi.getSaldos(),
  });
  const caja = saldosQ.data?.cajas.find((c) => c.socio === "Estudio");

  const rendicionQ = useQuery({
    queryKey: ["admin", "contabilidad", "rendicion", mes],
    queryFn: () => adminApi.getRendicion(mes),
    enabled: /^\d{4}-\d{2}$/.test(mes),
  });
  const parte = rendicionQ.data?.personas.find((p) => p.persona === "Estudio");

  const movsQ = useQuery({
    queryKey: ["admin", "contabilidad", "movimientos", { cuenta: caja?.id }],
    queryFn: () => adminApi.listMovimientos({ cuenta_id: caja!.id }),
    enabled: !!caja,
  });

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
          <span className="rounded-md bg-muted px-2 py-0.5 text-xs">Cobros</span>
        ),
    },
    {
      header: "Detalle",
      cell: (f) =>
        f.kind === "mov" ? (
          <>
            <span className={cn(f.mov.anulado && "line-through")}>{descMovimiento(f.mov)}</span>
            {f.mov.nota && <div className="text-xs text-muted-foreground">{f.mov.nota}</div>}
          </>
        ) : (
          <>
            <span className="capitalize text-ink">
              Cobros del Estudio · {mesLabel(f.cobro.mes)}
            </span>
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
          formatMoney(f.mov.monto, f.mov.moneda)
        ) : (
          <span className="text-verde-ink">+ {formatMoney(f.cobro.monto, "ARS")}</span>
        ),
      align: "right",
      className: "font-mono tabular-nums",
    },
  ];

  return (
    <AdminPage
      title="Caja Estudio"
      maxW="detail"
      description="La economía del Estudio, separada del Rental — hoy no se reparte ganancia, así que esto es lo único que hace falta ver: qué entra y qué sale de su propia caja."
      backTo={{ to: "/admin/contabilidad", label: "Tablero" }}
      actions={
        <Button variant="outline" size="sm" asChild>
          <Link to="/admin/contabilidad/movimientos">Registrar / anular movimiento</Link>
        </Button>
      }
    >
      <div className="space-y-6">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          <StatCard label="Saldo actual" value={caja ? formatARS(caja.saldo) : "—"} icon={Wallet} />
          <StatCard
            label="Ingresos por alquiler (histórico)"
            value={caja ? formatARS(caja.ingresos_alquiler) : "—"}
            icon={Banknote}
          />
          <StatCard
            label={`Pendiente de rendición · ${mesLabel(mes)}`}
            value={parte ? formatARS(parte.pendiente) : "—"}
            icon={Clock}
            tone={parte && parte.pendiente > 0 ? "warn" : "default"}
          />
        </div>

        {parte && parte.pendiente > 0 && (
          <div className="rounded-md border border-amber/40 bg-amber/5 px-3 py-2 text-sm text-ink">
            Este mes le corresponden <b>{formatARS(parte.le_corresponde)}</b> y cobró{" "}
            <b>{formatARS(parte.cobro)}</b> — falta que le rindan{" "}
            <b>{formatARS(parte.pendiente)}</b> (alguien más cobró plata que era del Estudio). Vas a
            ver a quién pedírselo en{" "}
            <Link
              to="/admin/contabilidad/rendicion"
              className="underline decoration-amber/60 underline-offset-2"
            >
              Rendición
            </Link>
            .
          </div>
        )}

        <Section
          title="Movimientos"
          subtitle="Cobros de pedidos del Estudio + movimientos manuales de su caja."
          icon={Clapperboard}
          actions={
            <Input
              type="month"
              value={mes}
              onChange={(e) => setMes(e.target.value)}
              className="h-8 w-auto text-xs"
            />
          }
        >
          <QueryState
            query={movsQ}
            isEmpty={(d) => d.movimientos.length === 0 && (d.cobros ?? []).length === 0}
            skeleton={<TableSkeleton rows={5} cols={4} />}
            empty={
              <EmptyState
                icon={<Wallet className="h-6 w-6" />}
                title="Sin movimientos todavía"
                sub="Cuando el Estudio cobre un turno o se registre un gasto contra su caja, va a aparecer acá."
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
                    ? cn(f.mov.anulado && "opacity-50")
                    : "bg-muted/10 cursor-pointer"
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
        </Section>
      </div>
    </AdminPage>
  );
}

/** Detalle desplegable de un cobro mensual — misma fuente que Movimientos. */
function CobroDetalle({ mes }: { mes: string }) {
  const desde = `${mes}-01`;
  const hasta = finDeMes(mes);
  const q = useQuery({
    queryKey: ["admin", "pagos", "mes", mes, "estudio"],
    queryFn: () => adminApi.listPagosLog({ desde, hasta, destinatario: "Estudio" }),
  });

  const pagos = q.data?.pagos ?? [];
  if (q.isLoading) {
    return <div className="px-4 py-3 text-xs text-muted-foreground">Cargando pagos…</div>;
  }
  if (pagos.length === 0) {
    return <div className="px-4 py-3 text-xs text-muted-foreground">Sin pagos en el mes.</div>;
  }
  return (
    <div className="space-y-1.5 px-4 py-3">
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
