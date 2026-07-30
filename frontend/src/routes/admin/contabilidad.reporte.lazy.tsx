/**
 * contabilidad.reporte.lazy.tsx — Reporte mensual de Rental (#809).
 *
 * Todo derivado del motor (endpoint `reporte/{mes}`), sin recalcular en el front:
 * facturado (devengado) · comisiones a dueños · gastos · ganancia de Rental
 * (facturado − comisiones − gastos) · cobrado · cuenta corriente al día. La
 * comisión de los dueños es un COSTO, no ganancia. Devengado y percibido van
 * separados, nunca sumados.
 */
import { createLazyFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Receipt } from "lucide-react";

import { AdminPage } from "@/components/admin/AdminPage";
import { AdminTable } from "@/components/admin/AdminTable";
import { TableSkeleton } from "@/components/admin/skeletons";
import { ErrorState } from "@/components/admin/ErrorState";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { Section } from "@/design-system/composites/Section";
import { adminApi, type CuentaSaldo } from "@/lib/admin/api";
import { Input } from "@/design-system/ui/input";
import { formatARS } from "@/lib/format";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";

export const Route = createLazyFileRoute("/admin/contabilidad/reporte")({
  component: ReporteMensualPage,
});

function mesActual() {
  return new Date().toISOString().slice(0, 7);
}

function ReporteMensualPage() {
  useDocumentTitle("Reporte mensual · Finanzas");
  const [mes, setMes] = useState(mesActual());

  const q = useQuery({
    queryKey: ["admin", "contabilidad", "reporte", mes],
    queryFn: () => adminApi.getReporteMensual(mes),
    enabled: /^\d{4}-\d{2}$/.test(mes),
  });
  const r = q.data;
  const socios = ["Pablo", "Tincho"];

  return (
    <AdminPage
      title="Reporte mensual"
      maxW="detail"
      description="El mes de Rental, completo: lo facturado, lo que se llevan los dueños de los equipos, los gastos, y lo que realmente le queda a Rental. Todo sale del mismo motor — no hay un peso sumado dos veces."
      backTo={{ to: "/admin/contabilidad", label: "Tablero" }}
      actions={
        <Input
          type="month"
          value={mes}
          onChange={(e) => setMes(e.target.value)}
          className="w-auto"
        />
      }
    >
      <div className="space-y-6">
        {q.isLoading && <TableSkeleton rows={5} cols={5} />}
        {q.isError && <ErrorState error={q.error} onRetry={q.refetch} />}

        {r && (
          <>
            {r.cerrado && (
              <div className="rounded-md border border-amber/40 bg-amber/5 px-3 py-2 text-xs text-ink">
                Mes cerrado — los números son la foto congelada.
              </div>
            )}

            {/* Cascada del mes: facturado − comisiones a dueños − gastos = ganancia */}
            <div className="max-w-xl card-elevated p-5 sm:p-6">
              <div className="t-eyebrow">El mes de Rental</div>
              <div className="mt-3 space-y-0.5">
                <CascadaRow
                  label="Facturado"
                  note={`devengado · ${r.devengado.pedidos} pedido(s) saldado(s)`}
                  value={formatARS(r.devengado.total)}
                />
                <CascadaRow
                  label="Comisiones a dueños"
                  note="Pablo, Tincho, terceros"
                  value={`− ${formatARS(r.comisiones_duenos)}`}
                  cost
                />
                <CascadaRow
                  label="Parte del Estudio"
                  note="otra unidad de negocio, no una comisión"
                  value={`− ${formatARS(r.parte_estudio)}`}
                  cost
                />
                <CascadaRow
                  label="Gastos operativos"
                  value={`− ${formatARS(r.gastos.total)}`}
                  cost
                />
              </div>
              <div className="my-3 border-t-2 border-ink/15" />
              <CascadaRow
                label="Ganancia de Rental"
                value={formatARS(r.ganancia_neta)}
                total
                negative={r.ganancia_neta < 0}
              />
            </div>

            {/* Por socio: devengado vs percibido + movimientos del mes.
                "Estudio" entra sin cargos/pagos (no es socio humano, no tiene
                cuenta corriente) — el gate de abajo ya lo deja en "—". */}
            <Section variant="plain" title="Por socio">
              <AdminTable<string>
                rows={["Pablo", "Tincho", "Rental", "Estudio"]}
                getRowKey={(s) => s}
                columns={[
                  {
                    header: "Socio",
                    headClassName: "text-xs uppercase tracking-wider",
                    className: "font-medium text-ink",
                    cell: (s) => s,
                  },
                  {
                    header: "Su parte",
                    align: "right",
                    headClassName: "text-xs uppercase tracking-wider",
                    className: "font-mono tabular-nums",
                    cell: (s) => formatARS(r.devengado.por_socio[s] ?? 0),
                  },
                  {
                    header: "Cobró",
                    align: "right",
                    headClassName: "text-xs uppercase tracking-wider",
                    className: "font-mono tabular-nums",
                    cell: (s) => formatARS(r.cobrado.por_socio[s] ?? 0),
                  },
                  {
                    header: "Le cargué",
                    align: "right",
                    headClassName: "text-xs uppercase tracking-wider",
                    className: "font-mono tabular-nums text-muted-foreground",
                    cell: (s) =>
                      socios.includes(s) ? formatARS(r.socios_mes.cargos[s] ?? 0) : "—",
                  },
                  {
                    header: "Me pagó",
                    align: "right",
                    headClassName: "text-xs uppercase tracking-wider",
                    className: "font-mono tabular-nums text-muted-foreground",
                    cell: (s) => (socios.includes(s) ? formatARS(r.socios_mes.pagos[s] ?? 0) : "—"),
                  },
                ]}
              />
              <p className="text-xs text-muted-foreground">
                <strong>Su parte</strong> es lo que se ganó y le toca (devengado).{" "}
                <strong>Cobró</strong> es la plata que entró a su nombre (percibido). Son cosas
                distintas — no se suman. «Le cargué / Me pagó» son los movimientos con su cuenta
                corriente este mes.
              </p>
            </Section>

            {/* Gastos por categoría */}
            <Section variant="plain" title="Gastos del mes">
              {r.gastos.por_categoria.length === 0 ? (
                <EmptyState
                  icon={<Receipt className="h-6 w-6" />}
                  title="Sin gastos este mes"
                  sub="No hay gastos cargados para el período seleccionado."
                />
              ) : (
                <div className="rounded-lg border hairline divide-y divide-[var(--hairline)]">
                  {r.gastos.por_categoria.map((g) => (
                    <div key={g.categoria} className="flex items-center justify-between px-3 py-2">
                      <span className="text-sm text-ink">{g.categoria}</span>
                      <span className="font-mono text-sm tabular-nums text-destructive">
                        − {formatARS(g.monto)}
                      </span>
                    </div>
                  ))}
                  <div className="flex items-center justify-between px-3 py-2 font-medium">
                    <span className="text-sm">Total gastos</span>
                    <span className="font-mono text-sm tabular-nums">
                      {formatARS(r.gastos.total)}
                    </span>
                  </div>
                </div>
              )}
            </Section>

            {/* Cuenta corriente al día */}
            <Section variant="plain" title="Cuenta corriente de socios (al día de hoy)">
              <div className="grid gap-3 sm:grid-cols-2">
                {r.cuenta_corriente.map((s) => (
                  <CuentaCorrienteMini key={s.id} socio={s} />
                ))}
              </div>
            </Section>
          </>
        )}
      </div>
    </AdminPage>
  );
}

/** Una línea de la cascada: label (+ nota) a la izquierda, monto a la derecha.
 *  `cost` = renglón que resta (muted); `total` = el resultado, resaltado. */
function CascadaRow({
  label,
  note,
  value,
  cost,
  total,
  negative,
}: {
  label: string;
  note?: string;
  value: string;
  cost?: boolean;
  total?: boolean;
  negative?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <div className="min-w-0">
        <div className={total ? "font-display text-lg text-ink" : "text-sm text-ink"}>{label}</div>
        {note && <div className="text-2xs text-muted-foreground">{note}</div>}
      </div>
      <div
        className={
          total
            ? `shrink-0 font-mono text-2xl font-semibold tabular-nums ${negative ? "text-destructive" : "text-ink"}`
            : cost
              ? "shrink-0 font-mono text-sm tabular-nums text-muted-foreground"
              : "shrink-0 font-mono text-sm font-medium tabular-nums text-ink"
        }
      >
        {value}
      </div>
    </div>
  );
}

function CuentaCorrienteMini({ socio }: { socio: CuentaSaldo }) {
  const abs = Math.abs(socio.saldo);
  const frase =
    socio.estado === "deudor"
      ? `${socio.nombre} le debe a Rental`
      : socio.estado === "acreedor"
        ? `Rental le debe a ${socio.nombre}`
        : "A mano";
  const color =
    socio.estado === "deudor"
      ? "text-destructive"
      : socio.estado === "acreedor"
        ? "text-verde-ink"
        : "text-ink";
  return (
    <div className="rounded-lg border hairline p-4">
      <div className="font-medium text-ink">{socio.nombre}</div>
      <div className={`font-mono text-2xl font-semibold tabular-nums ${color}`}>
        {formatARS(abs)}
      </div>
      <div className="text-sm text-muted-foreground">{frase}</div>
    </div>
  );
}
