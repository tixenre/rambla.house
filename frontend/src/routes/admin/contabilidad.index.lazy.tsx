/**
 * contabilidad.index.lazy.tsx — Tablero financiero (#809, Fase 1).
 *
 * Muestra la "plata disponible ahora": total + desglose por caja. Los ingresos
 * por alquiler ya vienen DERIVADOS de los cobros (alquiler_pagos) — no se carga
 * nada a mano. En fases siguientes se suman ganancia neta del mes y rendición.
 */
import { createLazyFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { adminApi, type CuentaSaldo } from "@/lib/admin/api";
import { AdminPage } from "@/components/admin/AdminPage";
import { CardGridSkeleton } from "@/components/admin/skeletons";
import { ErrorState } from "@/components/admin/ErrorState";
import { formatARS, formatMoney } from "@/lib/format";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { Badge } from "@/design-system/ui/badge";
import { Button } from "@/design-system/ui/button";

export const Route = createLazyFileRoute("/admin/contabilidad/")({
  component: ContabilidadTablero,
});

function ContabilidadTablero() {
  useDocumentTitle("Finanzas · Back Office");

  const q = useQuery({
    queryKey: ["admin", "contabilidad", "tablero"],
    queryFn: () => adminApi.getTablero(),
  });

  const data = q.data;

  return (
    <AdminPage
      title="Tablero"
      maxW="list"
      description="Cuánta plata hay y dónde. Los cobros de clientes ya entran solos a la caja de quien los cobró."
      actions={
        <Button asChild variant="outline" className="shrink-0">
          <Link to="/admin/contabilidad/cuentas">Administrar cuentas</Link>
        </Button>
      }
    >
      <div className="space-y-6">
        {q.isLoading && <CardGridSkeleton count={4} />}
        {q.isError && <ErrorState error={q.error} onRetry={q.refetch} />}

        {data && (
          <>
            {/* KPIs: disponible · ganancia del mes (la rendición vive en la cuenta corriente) */}
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="card-elevated p-5">
                <div className="t-eyebrow">Plata disponible</div>
                <div className="font-mono text-3xl font-semibold tabular-nums text-ink mt-1">
                  {formatMoney(data.disponible.totales.ARS ?? 0, "ARS")}
                </div>
                {(data.disponible.totales.USD ?? 0) !== 0 && (
                  <div className="font-mono text-lg font-semibold tabular-nums text-ink">
                    {formatMoney(data.disponible.totales.USD, "USD")}
                  </div>
                )}
                <div className="text-xs text-muted-foreground mt-1">
                  Suma de las cajas · al {data.disponible.as_of}
                </div>
              </div>

              <div className="card-elevated p-5">
                <div className="t-eyebrow">Ganancia neta · {data.ganancia_mes.mes}</div>
                <div
                  className={`font-mono text-3xl font-semibold tabular-nums mt-1 ${
                    data.ganancia_mes.neta >= 0 ? "text-ink" : "text-destructive"
                  }`}
                >
                  {formatARS(data.ganancia_mes.neta)}
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  Ingresos {formatARS(data.ganancia_mes.ingresos)} − gastos{" "}
                  {formatARS(data.ganancia_mes.gastos)}
                </div>
              </div>
            </div>

            {/* Socios · Cuenta corriente */}
            {(data.disponible.socios?.length ?? 0) > 0 && (
              <div>
                <div className="t-eyebrow mb-2">Socios · Cuenta corriente</div>
                <div className="grid gap-3 sm:grid-cols-2">
                  {data.disponible.socios.map((s) => (
                    <SocioCard key={s.id} socio={s} />
                  ))}
                </div>
              </div>
            )}

            {/* Por caja */}
            <div>
              <div className="t-eyebrow mb-2">Por caja</div>
              <div className="grid gap-3 sm:grid-cols-2">
                {data.disponible.cajas.map((c) => (
                  <CajaCard key={c.id} cuenta={c} />
                ))}
              </div>
            </div>
          </>
        )}

        <ReconciliacionPanel />
      </div>
    </AdminPage>
  );
}

function ReconciliacionPanel() {
  const q = useQuery({
    queryKey: ["admin", "contabilidad", "reconciliacion"],
    queryFn: () => adminApi.getReconciliacionContable(),
  });
  const r = q.data;
  if (!r) return null;

  const problemas: string[] = [];
  if (r.saldos_negativos.cantidad > 0)
    problemas.push(`${r.saldos_negativos.cantidad} caja(s) con saldo negativo`);
  if (r.pagos_sin_socio.cantidad > 0)
    problemas.push(
      `${r.pagos_sin_socio.cantidad} cobro(s) sin socio asignado (${formatARS(r.pagos_sin_socio.monto)})`,
    );
  if (r.movimientos_cuenta_inactiva.cantidad > 0)
    problemas.push(
      `${r.movimientos_cuenta_inactiva.cantidad} movimiento(s) en cuentas dadas de baja`,
    );
  // Este chequeo BAJA el semáforo, así que tiene que poder explicarse: sin esta
  // línea la caja se pintaba roja con la lista vacía.
  if (r.devengado_sin_cuenta && r.devengado_sin_cuenta.cantidad > 0)
    problemas.push(
      `${formatARS(r.devengado_sin_cuenta.monto)} devengados para ` +
        `${r.devengado_sin_cuenta.beneficiarios.map((b) => b.beneficiario).join(", ")} — ` +
        `no tienen caja donde verse (revisá el modelo de comisiones o creá la cuenta)`,
    );
  if (!r.reporte.ok) {
    const sl = r.reporte.pagados_sin_ledger;
    const sp = r.reporte.sobrepagados;
    if (sl && sl.cantidad > 0)
      problemas.push(
        `${sl.cantidad} pedido(s) marcados pagados pero sin pagos registrados ` +
          `(no entran al reporte): #${sl.ids.join(", #")}`,
      );
    if (sp && sp.cantidad > 0)
      problemas.push(
        `${sp.cantidad} pedido(s) con más cobrado que su total (¿se editó el pedido ` +
          `después de cobrar?): #${sp.ids.join(", #")}`,
      );
    if (!(sl && sl.cantidad > 0) && !(sp && sp.cantidad > 0))
      problemas.push("el reporte de liquidación tiene observaciones — revisalas en Liquidación");
  }

  return (
    <div
      className={`rounded-lg border p-4 ${
        r.ok ? "hairline bg-muted/10" : "border-destructive/40 bg-destructive/5"
      }`}
    >
      <div className="t-eyebrow mb-1">Reconciliación</div>
      {r.ok ? (
        <div className="text-sm text-ink">✓ Todo cuadra.</div>
      ) : (
        <ul className="text-sm text-destructive list-disc pl-5 space-y-0.5">
          {problemas.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SocioCard({ socio }: { socio: CuentaSaldo }) {
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
  const tag =
    socio.estado === "deudor" ? "Deudor" : socio.estado === "acreedor" ? "Acreedor" : "Saldado";
  return (
    <div className="rounded-lg border hairline p-4 space-y-1">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-ink">{socio.nombre}</span>
        <span className="font-mono text-2xs uppercase tracking-wider text-muted-foreground">
          {tag}
        </span>
      </div>
      <div className={`font-mono text-2xl font-semibold tabular-nums ${color}`}>
        {formatMoney(abs, socio.moneda)}
      </div>
      <div className="text-xs text-muted-foreground">{frase}</div>
    </div>
  );
}

function CajaCard({ cuenta }: { cuenta: CuentaSaldo }) {
  return (
    <div className="rounded-lg border hairline p-4 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-ink">{cuenta.nombre}</span>
        <Badge variant="secondary" className="capitalize">
          {cuenta.tipo}
        </Badge>
      </div>
      <div className="font-mono text-2xl font-semibold tabular-nums text-ink">
        {formatMoney(cuenta.saldo, cuenta.moneda)}
      </div>
      <dl className="text-xs text-muted-foreground space-y-0.5">
        {cuenta.saldo_inicial !== 0 && (
          <Row label="Saldo inicial" value={formatMoney(cuenta.saldo_inicial, cuenta.moneda)} />
        )}
        {cuenta.ingresos_alquiler !== 0 && (
          <Row
            label="Cobros de alquiler"
            value={formatMoney(cuenta.ingresos_alquiler, cuenta.moneda)}
          />
        )}
        {cuenta.entradas !== 0 && (
          <Row label="Entradas" value={formatMoney(cuenta.entradas, cuenta.moneda)} />
        )}
        {cuenta.egresos !== 0 && (
          <Row label="Salidas" value={`− ${formatMoney(cuenta.egresos, cuenta.moneda)}`} />
        )}
      </dl>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt>{label}</dt>
      <dd className="font-mono tabular-nums">{value}</dd>
    </div>
  );
}
