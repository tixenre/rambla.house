/**
 * contabilidad.rendicion.lazy.tsx — Reparto entre las 4 partes (#809).
 *
 * DOS bloques, y el orden importa:
 *
 * 1. **"Al día de hoy"** (`/posiciones`, ACUMULADO) — la verdad de quién le debe a
 *    quién y de dónde salen las transferencias sugeridas. Para un socio es el mismo
 *    número que su cuenta corriente; Rental y el Estudio también tienen el suyo.
 * 2. **"Lo que se generó en {mes}"** (`/rendicion/{mes}`) — la foto del mes, para
 *    entender de dónde salió cada número. **Sin botones**: `ya_transferido` filtra
 *    por `rendicion_mes`, así que este bloque arranca de cero cada mes y puede
 *    sugerir lo contrario que el acumulado. Pasó de verdad en agosto 2026 (el mes
 *    decía "Rental → Tincho $110.500" mientras Tincho debía $734.088), y marcar ese
 *    saldado le SUBIÓ la deuda a Tincho.
 *
 * Por eso el botón dejó de decir "Marcar saldado" (que se lee como "dar el mes por
 * visto") y dice lo que de verdad hace: registra una transferencia real en el libro.
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
  type PosicionParte,
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

  // Query propia (no bloquea el mes): la posición acumulada recorre todos los meses
  // desde el clean start, así que es más cara que la foto de un mes.
  const posicionesQ = useQuery({
    queryKey: ["admin", "contabilidad", "posiciones"],
    queryFn: () => adminApi.getPosiciones(),
  });

  const invalidarTodo = () => {
    qc.invalidateQueries({ queryKey: ["admin", "contabilidad", "posiciones"] });
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
        {/* AL DÍA DE HOY — la lectura acumulada. Va PRIMERO a propósito: es la que
            dice si mover plata tiene sentido. El bloque mensual de abajo arranca de
            cero cada mes (`ya_transferido` filtra por `rendicion_mes`), así que
            puede sugerir lo contrario que el acumulado — fue exactamente lo que
            pasó con Tincho en agosto 2026. */}
        <QueryState query={posicionesQ} skeleton={<TableSkeleton rows={1} cols={4} />}>
          {(pos) => (
            <Section
              title="Al día de hoy"
              subtitle="Sumando todo desde el arranque, no un mes suelto. Es el mismo número que la cuenta corriente de cada socio — y acá también están Rental y el Estudio."
              icon={Scale}
            >
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {pos.partes.map((p) => (
                  <PosicionCard key={p.parte} parte={p} />
                ))}
              </div>
              {pos.float_sin_saldar > 0 && (
                <p className="mt-3 text-xs text-muted-foreground">
                  Ojo: {formatARS(pos.float_sin_saldar)} de esa plata es de pedidos que todavía no
                  se terminaron de cobrar. Está en la mano de alguien, pero no se repartió porque el
                  pedido no cerró.
                </p>
              )}

              {/* Las transferencias sugeridas salen de ACÁ (el acumulado), no del
                  mes: es lo que de verdad hay que mover. Un reparto parcial baja
                  la posición y el resto queda pendiente para la próxima, sin
                  depender de en qué mes se hizo. */}
              <div className="mt-4 border-t hairline pt-4">
                {pos.sugeridos.length === 0 ? (
                  <EmptyState
                    icon={<Scale className="h-6 w-6" />}
                    title="Nada pendiente de repartir"
                    sub="Las 4 partes están en cero entre ellas."
                  />
                ) : (
                  <div className="space-y-2">
                    <p className="text-xs text-muted-foreground">
                      Para que las 4 partes queden en cero. Cada botón registra una transferencia
                      REAL en el libro — usalo cuando la plata se movió de verdad, no para marcar el
                      mes como visto.
                    </p>
                    {pos.sugeridos.map((s, i) => (
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
                          Registrar la transferencia
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </Section>
          )}
        </QueryState>

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
              <Section
                title={`Lo que se generó en ${mesLabel(mes)}`}
                subtitle="La foto del mes, para entender de dónde salió cada número. Para decidir si mover plata, mirá 'Al día de hoy' arriba."
                variant="plain"
              >
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {data.personas.map((p) => (
                    <ParteCard key={p.persona} parte={p} />
                  ))}
                </div>
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

/** La posición ACUMULADA de una parte. A diferencia de `ParteCard` (la foto de un
 *  mes), este número no se reinicia: es lo que de verdad hay que saldar. Para
 *  Pablo/Tincho coincide con su cuenta corriente; para Rental y el Estudio es un
 *  número que antes no existía en ninguna pantalla de saldos. */
function PosicionCard({ parte }: { parte: PosicionParte }) {
  const p = parte.pendiente;
  const tono =
    p > 0
      ? "border-amber/50 bg-amber/10"
      : p < 0
        ? "border-destructive/30 bg-destructive/10"
        : "hairline bg-surface";

  return (
    <div className={cn("rounded-lg border p-3.5", tono)}>
      <div className="t-eyebrow">{parte.parte}</div>
      <div className="mt-1.5 font-mono text-xl font-semibold tabular-nums text-ink">
        {formatARS(Math.abs(p))}
      </div>
      <div className="text-sm text-muted-foreground">
        {p > 0 ? "le falta recibir" : p < 0 ? "tiene de más" : "al día"}
      </div>
      <div className="mt-2 border-t hairline pt-1.5 font-mono text-xs tabular-nums text-muted-foreground">
        le corresponde {formatARS(parte.le_corresponde)} · cobró {formatARS(parte.cobro)}
        {parte.arranque !== 0 && <> · arranque {formatARS(parte.arranque)}</>}
        {parte.repartido !== 0 && <> · repartido {formatARS(parte.repartido)}</>}
      </div>
    </div>
  );
}

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
  sugerido,
  onOpenChange,
  onSaldado,
}: {
  sugerido: SugeridoRendicion;
  onOpenChange: (open: boolean) => void;
  onSaldado: () => void;
}) {
  const [monto, setMonto] = useState(String(sugerido.monto));
  const [metodo, setMetodo] = useState<string>("transferencia");
  const [fecha, setFecha] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const [nota, setNota] = useState("");

  // El `rendicion_mes` del movimiento sale de la FECHA en que la plata se movió,
  // no del mes que el admin esté mirando arriba: la sugerencia es acumulada, así
  // que "qué mes estoy viendo" no dice nada sobre cuándo se hizo la transferencia.
  // Así el movimiento aparece en el registro del mes correcto.
  const mesDelMovimiento = (fecha || new Date().toISOString().slice(0, 10)).slice(0, 7);

  const saldar = useMutation({
    mutationFn: () =>
      adminApi.saldarRendicion(mesDelMovimiento, {
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
