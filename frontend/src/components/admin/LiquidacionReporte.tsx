/**
 * LiquidacionReporte.tsx — reporte de liquidación (devengado por dueño/socio).
 *
 * Extraído de la pantalla de Estadísticas para vivir en Finanzas (su lugar: es
 * plata). Mantiene TODAS sus features: navegación por mes, día a día, mes a mes,
 * resumen por dueño, cierre/reapertura de mes (#721), reconciliación, export CSV
 * y enviar por mail. Los primitivos de presentación (`BarChart`/`RankList`/`fmtArs`)
 * se exportan para reusarlos donde haga falta (ej. el Resumen de Estadísticas) —
 * única fuente, sin duplicar. `Kpi`/`Section` migraron a composites del DS
 * (`StatCard`/`Section`).
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DollarSign,
  Wallet,
  Package,
  Receipt,
  ChevronLeft,
  ChevronRight,
  Lock,
  LockOpen,
  Mail,
  Download,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";

import { adminApi } from "@/lib/admin/api";
import type { LiquidacionMes } from "@/lib/admin/api";
import { fmtArs } from "@/lib/format";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Label } from "@/design-system/ui/label";
import { Textarea } from "@/design-system/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "@/design-system/ui/dialog";
import { useConfirm } from "@/components/admin/useConfirm";
import { Section } from "@/design-system/composites/Section";
import { StatCard } from "@/design-system/composites/StatCard";

export function LiquidacionReporte() {
  const pad = (n: number) => String(n).padStart(2, "0");
  const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const [anchor, setAnchor] = useState(() => new Date());
  const [downloading, setDownloading] = useState(false);
  const [mailOpen, setMailOpen] = useState(false);
  const confirm = useConfirm();

  const y = anchor.getFullYear();
  const m = anchor.getMonth();
  const mesDesde = iso(new Date(y, m, 1));
  const mesHasta = iso(new Date(y, m + 1, 0)); // último día del mes
  const anioDesde = iso(new Date(y, 0, 1));
  const anioHasta = iso(new Date(y, 11, 31));

  const mesQ = useQuery({
    queryKey: ["admin", "liquidacion", "mes", mesDesde, mesHasta],
    queryFn: () => adminApi.getLiquidacion(mesDesde, mesHasta),
  });
  const anioQ = useQuery({
    queryKey: ["admin", "liquidacion", "anio", anioDesde, anioHasta],
    queryFn: () => adminApi.getLiquidacion(anioDesde, anioHasta),
  });
  const mes = mesQ.data;
  const anio = anioQ.data;

  const reconQ = useQuery({
    queryKey: ["admin", "liquidacion", "reconciliacion"],
    queryFn: () => adminApi.getReconciliacion(),
  });
  const recon = reconQ.data;

  // Cierre del mes (#721). `mesKey` = el mes que se está viendo ('YYYY-MM').
  const mesKey = `${y}-${pad(m + 1)}`;
  const cerrado = mes?.cerrado === true;
  const qc = useQueryClient();
  const invalidarLiquidacion = () => qc.invalidateQueries({ queryKey: ["admin", "liquidacion"] });

  const mesLabel = new Intl.DateTimeFormat("es-AR", { month: "long", year: "numeric" }).format(
    anchor,
  );

  const cerrarM = useMutation({
    mutationFn: () => adminApi.cerrarMes(mesKey),
    onSuccess: async () => {
      await invalidarLiquidacion();
      toast.success(`${mesLabel} cerrado — la foto quedó congelada.`);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const reabrirM = useMutation({
    mutationFn: () => adminApi.reabrirMes(mesKey),
    onSuccess: async () => {
      await invalidarLiquidacion();
      toast.success(`${mesLabel} reabierto — vuelve a calcularse en vivo.`);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const cierreBusy = cerrarM.isPending || reabrirM.isPending;
  const onReabrir = async () => {
    const ok = await confirm({
      title: `¿Reabrir ${mesLabel}?`,
      description:
        "El reporte vuelve a calcularse en vivo y la foto congelada se descarta. Vas a poder cerrarlo de nuevo cuando termines de corregir.",
      confirmLabel: "Reabrir",
    });
    if (ok) reabrirM.mutate();
  };
  const cerradoAtLabel = mes?.cerrado_at
    ? new Intl.DateTimeFormat("es-AR", { day: "numeric", month: "long", year: "numeric" }).format(
        new Date(mes.cerrado_at),
      )
    : null;

  const beneficiarios = mes?.beneficiarios ?? anio?.beneficiarios ?? [];
  const err = (mesQ.error || anioQ.error) as Error | null;

  const descargarCsv = async () => {
    setDownloading(true);
    try {
      const blob = await adminApi.liquidacionCsv(mesDesde, mesHasta);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `liquidacion_${mesDesde}_a_${mesHasta}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(false);
    }
  };

  const shiftMonth = (delta: number) => setAnchor(new Date(y, m + delta, 1));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="icon"
            onClick={() => shiftMonth(-1)}
            aria-label="Mes anterior"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="font-display text-lg text-ink capitalize min-w-[9rem] text-center">
            {mesLabel}
          </span>
          <Button
            type="button"
            variant="outline"
            size="icon"
            onClick={() => shiftMonth(1)}
            aria-label="Mes siguiente"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {cerrado ? (
            <Button
              type="button"
              variant="outline"
              onClick={onReabrir}
              disabled={cierreBusy}
              className="gap-1.5"
            >
              <LockOpen className="h-4 w-4" /> {reabrirM.isPending ? "Reabriendo…" : "Reabrir mes"}
            </Button>
          ) : (
            <Button
              type="button"
              variant="outline"
              onClick={() => cerrarM.mutate()}
              disabled={cierreBusy || !mes || mes.resumen.pedidos === 0}
              title={
                mes && mes.resumen.pedidos === 0
                  ? "No hay pedidos saldados este mes para cerrar"
                  : "Congelar la foto de este mes"
              }
              className="gap-1.5"
            >
              <Lock className="h-4 w-4" /> {cerrarM.isPending ? "Cerrando…" : "Cerrar mes"}
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            onClick={() => setMailOpen(true)}
            className="gap-1.5"
          >
            <Mail className="h-4 w-4" /> Enviar por mail
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={descargarCsv}
            disabled={downloading}
            className="gap-1.5"
          >
            <Download className="h-4 w-4" /> {downloading ? "Generando…" : "Exportar CSV"}
          </Button>
        </div>
      </div>

      <EnviarReporteDialog
        open={mailOpen}
        onOpenChange={setMailOpen}
        desde={mesDesde}
        hasta={mesHasta}
        periodoLabel={mesLabel}
      />

      {cerrado && (
        <div className="flex items-center gap-2 rounded-md border hairline border-ink/15 bg-ink/[0.03] px-3 py-2 text-sm text-ink">
          <Lock className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span>
            <span className="font-medium">Mes cerrado</span>
            {cerradoAtLabel ? ` el ${cerradoAtLabel}` : ""}
            {mes?.cerrado_por ? ` por ${mes.cerrado_por}` : ""}. Los números están congelados —
            cambiar el reparto o editar un pedido no los altera. Reabrí para recalcular.
          </span>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Solo pedidos 100% pagados. Cada pedido cuenta en el mes/día en que quedó saldado. El reparto
        entre dueños se configura en{" "}
        <a href="/admin/settings" className="underline hover:text-ink">
          Ajustes
        </a>
        . Arranque limpio: los alquileres anteriores a junio 2026 no se cuentan.
      </p>

      {recon && recon.ok && (
        <div className="flex items-center gap-2 rounded-md border hairline border-verde/30 bg-verde/5 px-3 py-2 text-sm text-verde-ink">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          Datos de liquidación consistentes.
        </div>
      )}
      {recon && !recon.ok && (
        <div className="rounded-md border hairline border-amber/40 bg-amber/5 px-3 py-2 text-sm text-ink space-y-1">
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4 shrink-0 text-ink" />
            Revisá estos datos — pueden afectar los números del reporte:
          </div>
          <ul className="list-disc pl-6 text-xs text-muted-foreground space-y-0.5">
            {recon.pagados_sin_ledger.cantidad > 0 && (
              <li>
                {recon.pagados_sin_ledger.cantidad} pedido(s) marcados pagados pero sin pagos
                registrados (no aparecen en el reporte): #{recon.pagados_sin_ledger.ids.join(", #")}
              </li>
            )}
            {recon.monto_pagado_divergente.cantidad > 0 && (
              <li>
                {recon.monto_pagado_divergente.cantidad} pedido(s) con monto pagado distinto a la
                suma de sus pagos: #{recon.monto_pagado_divergente.ids.join(", #")}
              </li>
            )}
            {recon.sobrepagados.cantidad > 0 && (
              <li>
                {recon.sobrepagados.cantidad} pedido(s) con más cobrado que su total actual (¿lo
                editaste después de cobrar?): #{recon.sobrepagados.ids.join(", #")}
              </li>
            )}
            {recon.mes_cerrado_desactualizado.cantidad > 0 && (
              <li>
                {recon.mes_cerrado_desactualizado.cantidad} pedido(s) editados/pagados dentro de un
                mes ya cerrado ({recon.mes_cerrado_desactualizado.meses.join(", ")}): la foto quedó
                vieja → reabrí ese mes y volvé a cerrarlo. #
                {recon.mes_cerrado_desactualizado.ids.join(", #")}
              </li>
            )}
            {recon.duenos_no_canonicos.length > 0 && (
              <li>Dueños fuera del reparto configurado: {recon.duenos_no_canonicos.join(", ")}</li>
            )}
          </ul>
        </div>
      )}

      {err && (
        <div className="rounded-md border hairline border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          Error: {err.message}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          icon={DollarSign}
          label={`Total ${mesLabel}`}
          value={fmtArs(mes?.resumen.total)}
        />
        {beneficiarios.map((b) => (
          <StatCard
            key={b}
            icon={Wallet}
            label={b}
            value={fmtArs(mes?.resumen.por_beneficiario[b] ?? 0)}
          />
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <Section title="Día a día" subtitle={`Lo que entró cada día de ${mesLabel}`}>
          <BarChart
            data={(mes?.por_dia ?? []).map((d) => ({ label: d.dia, value: d.total }))}
            labelFn={(l) => l.slice(8)}
          />
        </Section>

        <Section title={`Mes a mes · ${y}`} subtitle="Total y reparto por mes">
          <MesAMesTabla meses={anio?.por_mes ?? []} beneficiarios={beneficiarios} />
        </Section>
      </div>

      <div className="space-y-3">
        <h3 className="font-display text-lg text-ink">
          Resumen por dueño
          {mes ? (
            <span className="text-sm font-normal text-muted-foreground">
              {" "}
              · este mes hubo {mes.resumen.pedidos} alquiler
              {mes.resumen.pedidos !== 1 ? "es" : ""} cobrado
              {mes.resumen.pedidos !== 1 ? "s" : ""}
            </span>
          ) : null}
        </h3>
        <div className="grid lg:grid-cols-2 gap-6">
          {(mes?.por_dueno ?? []).map((d) => (
            <Section
              key={d.dueno}
              title={`${d.dueno} · ${d.pedidos} alquiler${d.pedidos !== 1 ? "es" : ""}`}
              subtitle={`Generó ${fmtArs(d.monto_generado)} · reparte ${beneficiarios
                .filter((b) => d.reparto[b])
                .map((b) => `${b} ${fmtArs(d.reparto[b])}`)
                .join(" · ")}`}
            >
              <div className="space-y-4">
                <div>
                  <div className="t-eyebrow mb-1.5">Equipos</div>
                  <RankList
                    icon={Package}
                    items={d.equipos.map((eq) => ({
                      primary: eq.equipo,
                      secondary: `${eq.veces}× alquilado`,
                      value: fmtArs(eq.monto),
                    }))}
                  />
                </div>
                <div>
                  <div className="t-eyebrow mb-1.5">Pedidos</div>
                  <RankList
                    icon={Receipt}
                    items={(d.pedidos_detalle ?? []).map((p) => ({
                      primary: `#${p.numero_pedido} · ${p.cliente || "—"}`,
                      secondary: p.fecha,
                      value: fmtArs(p.monto),
                    }))}
                  />
                </div>
              </div>
            </Section>
          ))}
          {mes && mes.por_dueno.length === 0 && (
            <div className="text-sm text-muted-foreground">Sin pedidos saldados en {mesLabel}.</div>
          )}
        </div>
      </div>
    </div>
  );
}

function MesAMesTabla({
  meses,
  beneficiarios,
}: {
  meses: LiquidacionMes[];
  beneficiarios: string[];
}) {
  if (!meses.length) return <div className="text-sm text-muted-foreground">Sin datos</div>;
  const fmtMes = (mes: string) => {
    const [yy, mm] = mes.split("-").map(Number);
    return new Intl.DateTimeFormat("es-AR", { month: "short" }).format(new Date(yy, mm - 1, 1));
  };
  // Más reciente primero — el backend/CSV siguen cronológicos (ascendente,
  // la convención contable), esto es solo la lectura de la tabla en pantalla.
  const mesesDesc = [...meses].sort((a, b) => b.mes.localeCompare(a.mes));
  return (
    <div className="overflow-x-auto">
      {/* eslint-disable-next-line no-restricted-syntax -- tabla mes-a-mes con columnas dinámicas por beneficiario; AdminTable es de columnas fijas */}
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-muted-foreground">
            <th className="text-left font-normal py-1">Mes</th>
            {beneficiarios.map((b) => (
              <th key={b} className="text-right font-normal py-1">
                {b}
              </th>
            ))}
            <th className="text-right font-normal py-1">Total</th>
          </tr>
        </thead>
        <tbody>
          {mesesDesc.map((mes) => (
            <tr key={mes.mes} className="border-t hairline">
              <td className="py-1.5 text-ink capitalize">{fmtMes(mes.mes)}</td>
              {beneficiarios.map((b) => (
                <td key={b} className="py-1.5 text-right tabular-nums text-muted-foreground">
                  {fmtArs(mes.por_beneficiario[b] ?? 0)}
                </td>
              ))}
              <td className="py-1.5 text-right tabular-nums text-ink font-medium">
                {fmtArs(mes.total)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BarChart({
  data,
  labelFn = (l) => l.slice(5),
  valueFormat = fmtArs,
}: {
  data: { label: string; value: number }[];
  labelFn?: (label: string) => string;
  /** Formato del valor en el tooltip. Default pesos; pasar otro para conteos. */
  valueFormat?: (value: number) => string;
}) {
  if (!data.length) return <div className="text-sm text-muted-foreground">Sin datos</div>;
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <div className="space-y-1">
      {/* Área del gráfico — altura fija para que % de las barras resuelva */}
      <div className="relative flex items-end gap-1 h-28">
        {data.map((d) => (
          <div key={d.label} className="relative flex-1 h-full group">
            <div
              className="absolute bottom-0 left-0 right-0 bg-ink/80 hover:bg-ink rounded-sm transition-colors"
              style={{ height: `${Math.max((d.value / max) * 100, d.value > 0 ? 2 : 0)}%` }}
            >
              {/* Tooltip de valor al hover */}
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 whitespace-nowrap text-3xs font-mono text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity tabular-nums pointer-events-none">
                {valueFormat(d.value)}
              </div>
            </div>
          </div>
        ))}
      </div>
      {/* Etiquetas debajo, en fila separada */}
      <div className="flex gap-1">
        {data.map((d) => (
          <div
            key={d.label}
            className="flex-1 text-3xs font-mono text-muted-foreground truncate text-center"
          >
            {labelFn(d.label)}
          </div>
        ))}
      </div>
    </div>
  );
}

export function RankList({
  items,
  icon: Icon,
}: {
  items: { primary: string; secondary: string; value: string }[];
  icon: React.ComponentType<{ className?: string }>;
}) {
  if (!items.length) return <div className="text-sm text-muted-foreground">Sin datos</div>;
  return (
    <div className="space-y-1.5">
      {items.map((it, i) => (
        <div key={i} className="flex items-center gap-2 text-sm">
          <div className="w-5 font-mono text-xs text-muted-foreground tabular-nums">{i + 1}</div>
          <Icon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-ink truncate">{it.primary}</div>
            <div className="text-xs text-muted-foreground">{it.secondary}</div>
          </div>
          <div className="tabular-nums text-ink">{it.value}</div>
        </div>
      ))}
    </div>
  );
}

function EnviarReporteDialog({
  open,
  onOpenChange,
  desde,
  hasta,
  periodoLabel,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  desde: string;
  hasta: string;
  periodoLabel: string;
}) {
  const [to, setTo] = useState("");
  const [mensaje, setMensaje] = useState("");
  const [touched, setTouched] = useState(false);

  const destQ = useQuery({
    queryKey: ["admin", "reporte-destinatarios"],
    queryFn: () => adminApi.getReporteDestinatarios(),
    enabled: open,
  });
  useEffect(() => {
    if (open && !touched && destQ.data) {
      setTo(destQ.data.destinatarios.join(", "));
    }
  }, [open, touched, destQ.data]);

  const previewQ = useQuery({
    queryKey: ["admin", "reporte-preview", desde, hasta],
    queryFn: () => adminApi.liquidacionPreviewHtml(desde, hasta),
    enabled: open,
  });

  const parseMails = (raw: string) =>
    raw
      .split(/[,;\n]+/)
      .map((s) => s.trim())
      .filter(Boolean);

  const enviarMut = useMutation({
    mutationFn: () =>
      adminApi.enviarReporteMail({
        desde,
        hasta,
        destinatarios: parseMails(to),
        mensaje: mensaje.trim() || undefined,
      }),
    onSuccess: (r) => {
      toast.success(
        r.fallidos.length
          ? `Enviado a ${r.enviados.length}. No salió a: ${r.fallidos.join(", ")}`
          : `Reporte enviado a ${r.enviados.length} ${
              r.enviados.length === 1 ? "destinatario" : "destinatarios"
            }.`,
      );
      onOpenChange(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const hayDestino = parseMails(to).length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Enviar reporte por mail</DialogTitle>
          <DialogDescription>
            Se manda el reporte de <strong className="capitalize">{periodoLabel}</strong> en PDF
            adjunto. El CSV seguís pudiendo exportarlo aparte.
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-md border hairline overflow-hidden bg-white">
          {previewQ.isLoading ? (
            <div className="p-8 text-sm text-muted-foreground text-center">Generando preview…</div>
          ) : previewQ.error ? (
            <div className="p-8 text-sm text-destructive text-center">
              No se pudo generar el preview del reporte.
            </div>
          ) : (
            <iframe
              title="Preview del reporte de liquidación"
              srcDoc={previewQ.data ?? ""}
              className="w-full h-72 border-0"
            />
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="reporte-to">Para (uno o más mails, separados por coma)</Label>
          <Textarea
            id="reporte-to"
            rows={2}
            value={to}
            onChange={(e) => {
              setTouched(true);
              setTo(e.target.value);
            }}
            placeholder="dueño1@mail.com, dueño2@mail.com"
            className="resize-none"
          />
          <p className="text-xs text-muted-foreground">Se guardan para la próxima vez.</p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="reporte-msg">Mensaje (opcional)</Label>
          <Input
            id="reporte-msg"
            value={mensaje}
            onChange={(e) => setMensaje(e.target.value)}
            placeholder="Va arriba del reporte en el cuerpo del mail"
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button onClick={() => enviarMut.mutate()} disabled={!hayDestino || enviarMut.isPending}>
            {enviarMut.isPending ? "Enviando…" : "Enviar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
