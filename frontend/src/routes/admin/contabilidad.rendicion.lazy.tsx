/**
 * contabilidad.rendicion.lazy.tsx — Rendición mensual entre las 4 partes (#809).
 *
 * El backend de rendición (`_netting`, `saldar`) ya calculaba todo esto — no
 * tenía ninguna pantalla propia. El único lugar que lo mencionaba (Caja
 * Estudio) linkeaba a Liquidación, que es un reporte totalmente distinto (el
 * devengado por dueño). Esta pantalla es la real: cuánto le corresponde a
 * cada parte (Pablo/Tincho/Rental/Estudio), cuánto cobró, cuánto ya se le
 * rindió, y qué transferencia falta para que cierre en cero — con un botón
 * para marcarla hecha.
 */
import { createLazyFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Scale } from "lucide-react";
import { toast } from "sonner";

import { AdminPage } from "@/components/admin/AdminPage";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { QueryState } from "@/components/admin/QueryState";
import { TableSkeleton } from "@/components/admin/skeletons";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { Section } from "@/design-system/composites/Section";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Label } from "@/design-system/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/design-system/ui/dialog";
import { SegmentedControl } from "@/design-system/ui/segmented-control";
import {
  adminApi,
  METODOS_PAGO,
  type RendicionPersona,
  type SugeridoRendicion,
} from "@/lib/admin/api";
import { formatARS, formatFechaDisplay } from "@/lib/format";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { cn } from "@/lib/utils";

export const Route = createLazyFileRoute("/admin/contabilidad/rendicion")({
  component: RendicionPage,
});

function mesActual() {
  return new Date().toISOString().slice(0, 7);
}

function mesLabel(mes: string): string {
  return new Date(`${mes}-01T00:00:00`).toLocaleDateString("es-AR", {
    month: "long",
    year: "numeric",
  });
}

function RendicionPage() {
  useDocumentTitle("Rendición · Finanzas");
  const qc = useQueryClient();
  const [mes, setMes] = useState(mesActual());
  const [saldarSugerido, setSaldarSugerido] = useState<SugeridoRendicion | null>(null);

  const rendicionQ = useQuery({
    queryKey: ["admin", "contabilidad", "rendicion", mes],
    queryFn: () => adminApi.getRendicion(mes),
    enabled: /^\d{4}-\d{2}$/.test(mes),
  });

  const invalidarTodo = () => {
    qc.invalidateQueries({ queryKey: ["admin", "contabilidad", "rendicion", mes] });
    qc.invalidateQueries({ queryKey: ["admin", "contabilidad", "saldos"] });
    qc.invalidateQueries({ queryKey: ["admin", "contabilidad", "movimientos"] });
    qc.invalidateQueries({ queryKey: ["admin", "contabilidad", "tablero"] });
  };

  const movColumns: Column<(typeof movimientosVacios)[number]>[] = [
    {
      header: "Fecha",
      cell: (m) => formatFechaDisplay(m.fecha),
      className: "whitespace-nowrap text-muted-foreground",
    },
    {
      header: "Transferencia",
      cell: (m) => (
        <span className={cn(m.anulado && "line-through text-muted-foreground")}>
          {m.origen ?? "—"} → {m.destino ?? "—"}
        </span>
      ),
    },
    { header: "Método", cell: (m) => m.metodo ?? "—", className: "capitalize" },
    { header: "Nota", cell: (m) => m.nota ?? "—", className: "text-muted-foreground" },
    {
      header: "Monto",
      cell: (m) => formatARS(m.monto),
      align: "right",
      className: "font-mono tabular-nums",
    },
  ];

  return (
    <AdminPage
      title="Rendición"
      maxW="detail"
      description="Cuánto le corresponde cobrar a cada parte (Pablo, Tincho, Rental, Estudio), cuánto ya cobró, y qué transferencia falta para que quede saldado."
      backTo={{ to: "/admin/contabilidad", label: "Tablero" }}
      actions={
        <Input
          type="month"
          value={mes}
          onChange={(e) => setMes(e.target.value)}
          className="h-9 w-auto text-xs"
        />
      }
    >
      <div className="space-y-6">
        <QueryState query={rendicionQ} skeleton={<TableSkeleton rows={4} cols={4} />}>
          {(data) => (
            <div className="space-y-6">
              {(!data.cuadra || data.advertencias.length > 0 || data.sin_asignar > 0) && (
                <div className="rounded-md border border-amber/40 bg-amber/5 px-3 py-2.5 text-sm text-ink">
                  <div className="font-medium">{mesLabel(mes)} todavía no cuadra del todo</div>
                  <ul className="mt-1 list-disc pl-4 text-xs text-muted-foreground">
                    {data.advertencias.map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                    {data.sin_asignar > 0 && (
                      <li>{formatARS(data.sin_asignar)} cobrados sin destinatario asignado.</li>
                    )}
                  </ul>
                </div>
              )}

              {/* 4 partes: le corresponde / cobró / ya rindió / pendiente. */}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {data.personas.map((p) => (
                  <ParteCard key={p.persona} parte={p} />
                ))}
              </div>

              <Section
                title="Transferencias sugeridas"
                subtitle="Para que las 4 partes queden en cero — una sugerida por vez."
                icon={Scale}
              >
                {data.sugeridos.length === 0 ? (
                  <EmptyState
                    icon={<Scale className="h-6 w-6" />}
                    title="Nada pendiente de saldar"
                    sub={`${mesLabel(mes)} ya cierra en cero entre las 4 partes.`}
                  />
                ) : (
                  <div className="space-y-2">
                    {data.sugeridos.map((s, i) => (
                      <div
                        key={i}
                        className="flex flex-wrap items-center gap-3 rounded-md border hairline px-3 py-2.5"
                      >
                        <span className="font-medium text-ink">{s.de}</span>
                        <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="font-medium text-ink">{s.a}</span>
                        <span className="ml-auto font-mono text-sm tabular-nums text-ink">
                          {formatARS(s.monto)}
                        </span>
                        <Button variant="outline" size="sm" onClick={() => setSaldarSugerido(s)}>
                          Marcar saldado
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </Section>

              <Section title="Movimientos de rendición" variant="plain">
                {data.movimientos.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Todavía no se saldó ninguna transferencia este mes.
                  </p>
                ) : (
                  <AdminTable
                    columns={movColumns}
                    rows={data.movimientos}
                    getRowKey={(m) => m.id}
                  />
                )}
              </Section>
            </div>
          )}
        </QueryState>
      </div>

      {saldarSugerido && (
        <SaldarDialog
          mes={mes}
          sugerido={saldarSugerido}
          onOpenChange={(open) => !open && setSaldarSugerido(null)}
          onSaldado={() => {
            invalidarTodo();
            setSaldarSugerido(null);
          }}
        />
      )}
    </AdminPage>
  );
}

/** Fila vacía tipada — solo para que `Column<T>` infiera el tipo de `movimientos`
 *  sin importar el tipo exportado de `RendicionData` acá arriba. */
const movimientosVacios: {
  id: number;
  fecha: string;
  metodo: string | null;
  nota: string | null;
  anulado: boolean;
  origen: string | null;
  destino: string | null;
  monto: number;
}[] = [];

function ParteCard({ parte }: { parte: RendicionPersona }) {
  const pendiente = parte.pendiente;
  const tono =
    pendiente > 0
      ? "border-amber/50 bg-amber/10"
      : pendiente < 0
        ? "border-destructive/30 bg-destructive/10"
        : "hairline bg-surface";

  return (
    <div className={cn("rounded-lg border p-3.5", tono)}>
      <div className="t-eyebrow">{parte.persona}</div>
      <dl className="mt-2 space-y-1 text-xs">
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Le corresponde</dt>
          <dd className="font-mono tabular-nums text-ink">{formatARS(parte.le_corresponde)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Cobró</dt>
          <dd className="font-mono tabular-nums text-ink">{formatARS(parte.cobro)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Ya rindió</dt>
          <dd className="font-mono tabular-nums text-ink">{formatARS(parte.ya_rindio)}</dd>
        </div>
      </dl>
      <div className="mt-2 border-t hairline pt-1.5">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-muted-foreground">
            {pendiente > 0 ? "Le falta recibir" : pendiente < 0 ? "Tiene de más" : "Pendiente"}
          </span>
          <span className="font-mono text-base font-semibold tabular-nums text-ink">
            {formatARS(Math.abs(pendiente))}
          </span>
        </div>
      </div>
    </div>
  );
}

function SaldarDialog({
  mes,
  sugerido,
  onOpenChange,
  onSaldado,
}: {
  mes: string;
  sugerido: SugeridoRendicion;
  onOpenChange: (open: boolean) => void;
  onSaldado: () => void;
}) {
  const [monto, setMonto] = useState(String(sugerido.monto));
  const [metodo, setMetodo] = useState<string>("transferencia");
  const [fecha, setFecha] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const [nota, setNota] = useState("");

  const saldar = useMutation({
    mutationFn: () =>
      adminApi.saldarRendicion(mes, {
        de: sugerido.de,
        a: sugerido.a,
        monto: Math.max(0, Number(monto) || 0),
        metodo,
        fecha: fecha || undefined,
        nota: nota || undefined,
      }),
    onSuccess: () => {
      toast.success("Transferencia registrada");
      onSaldado();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const montoNum = Math.max(0, Number(monto) || 0);

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            Registrar transferencia: {sugerido.de} → {sugerido.a}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-1">
          <Label className="font-mono text-2xs uppercase tracking-[0.15em] text-muted-foreground">
            Monto
          </Label>
          <div className="flex items-center gap-1.5 card-elevated px-3 h-11 focus-within:ring-2 focus-within:ring-ring focus-within:border-transparent">
            <span className="font-mono text-muted-foreground text-sm">$</span>
            {/* eslint-disable-next-line no-restricted-syntax -- input custom borderless dentro de wrapper con focus-within, mismo patrón que RegistrarPagoModal */}
            <input
              type="number"
              min={0}
              value={monto}
              onChange={(e) => setMonto(e.target.value)}
              className="flex-1 bg-transparent font-mono text-lg font-semibold tabular-nums focus:outline-none"
            />
          </div>
        </div>

        <div className="space-y-1">
          <Label className="font-mono text-2xs uppercase tracking-[0.15em] text-muted-foreground">
            Método
          </Label>
          <SegmentedControl
            value={metodo}
            onChange={setMetodo}
            options={METODOS_PAGO.map((m) => ({ value: m, label: m }))}
            ariaLabel="Método"
          />
        </div>

        <div className="space-y-1">
          <Label
            htmlFor="rendicion-fecha"
            className="font-mono text-2xs uppercase tracking-[0.15em] text-muted-foreground"
          >
            Fecha
          </Label>
          <Input
            id="rendicion-fecha"
            type="date"
            value={fecha}
            onChange={(e) => setFecha(e.target.value)}
            className="h-9 text-base md:text-sm"
          />
        </div>

        <div className="space-y-1">
          <Label
            htmlFor="rendicion-nota"
            className="font-mono text-2xs uppercase tracking-[0.15em] text-muted-foreground"
          >
            Nota (opcional)
          </Label>
          <Input
            id="rendicion-nota"
            value={nota}
            onChange={(e) => setNota(e.target.value)}
            placeholder="Ej. transferencia por MercadoPago…"
            className="h-9 text-base md:text-sm"
          />
        </div>

        <Button
          variant="amber"
          className="w-full"
          disabled={montoNum <= 0 || saldar.isPending}
          onClick={() => {
            if (montoNum <= 0) {
              toast.error("Ingresá un monto válido");
              return;
            }
            saldar.mutate();
          }}
        >
          {saldar.isPending ? "Registrando…" : `Registrar ${formatARS(montoNum)}`}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
