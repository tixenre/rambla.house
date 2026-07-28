/**
 * RegistrarPagoModal — Modal para registrar un pago sobre un pedido.
 * Wired a adminApi.addPago() — o a addPagoCombinado() cuando hay turnos del
 * Estudio vinculados (#1308, "un pago, reparte solo"): un solo botón cobra
 * el total combinado y el backend lo reparte fila por fila real. Diseño
 * según proto/app.jsx (PagoModal).
 */

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Label } from "@/design-system/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/design-system/ui/dialog";
import { SegmentedControl } from "@/design-system/ui/segmented-control";
import {
  adminApi,
  DESTINATARIOS_PAGO,
  METODOS_PAGO,
  type Pedido,
  type PedidoGeneradoEdicion,
  type RepartoPagoLinea,
} from "@/lib/admin/api";
import { fmtArs } from "@/lib/format";
import { combinarTotales } from "@/lib/pedido-combinado";

export function RegistrarPagoModal({
  pedidoId,
  total,
  pagado,
  open,
  onOpenChange,
  esEstudio = false,
  turnosVinculados = [],
}: {
  pedidoId: number;
  total: number;
  pagado: number;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** El pedido es un turno/slot del Estudio (economía separada, #1283) — el
   *  cobro va por defecto a "Estudio", no a "Rambla". */
  esEstudio?: boolean;
  /** Turnos del Estudio vinculados a `pedidoId` (#1308) — si hay al menos
   *  uno, el modal cobra el TOTAL COMBINADO y usa `addPagoCombinado` en vez
   *  de `addPago`; sin turnos, cero cambio de comportamiento. */
  turnosVinculados?: PedidoGeneradoEdicion[];
}) {
  const qc = useQueryClient();
  const combinado = combinarTotales(total, pagado, turnosVinculados);
  const saldo = combinado.restaCombinado;
  // La sola presencia de un turno vinculado ya implica plata del Estudio
  // (`_crear_pedido_estudio` siempre lo crea `tipo='estudio'`) — sin este
  // OR, cobrar acá (un pedido `tipo='diaria'`, esEstudio=false) con turnos
  // vinculados sin cobrar no mostraba el aviso pese a que parte de lo
  // combinado SÍ es plata del Estudio.
  const hayParteEstudio = esEstudio || turnosVinculados.length > 0;
  const destinatarioDefault = hayParteEstudio ? "Estudio" : "Rambla";

  // Presets: Seña 50% / Saldo total / Otro
  type Preset = "sena" | "saldo" | "otro";
  const sena50 = Math.round(combinado.totalCombinado * 0.5);

  const [preset, setPreset] = useState<Preset>("saldo");
  const [montoInput, setMontoInput] = useState<string>(String(saldo));
  const [concepto, setConcepto] = useState("Saldo final");
  // A quién se cobró y cómo. Default del dueño: Rambla + transferencia (Estudio
  // si el pedido es del Estudio — esa plata no es de Rambla ni de los socios).
  const [destinatario, setDestinatario] = useState<string>(destinatarioDefault);
  const [metodo, setMetodo] = useState<string>("transferencia");
  const [fecha, setFecha] = useState<string>(() => new Date().toISOString().slice(0, 10));

  const monto = Math.max(0, Number(montoInput) || 0);

  // Al abrir, re-inicializar contra el total/pagado COMBINADOS actuales (el
  // pedido pudo editarse desde que se montó el modal → los presets deben
  // reflejar lo vigente).
  useEffect(() => {
    if (!open) return;
    setDestinatario(destinatarioDefault);
    setMetodo("transferencia");
    setFecha(new Date().toISOString().slice(0, 10));
    setPreset("saldo");
    setMontoInput(String(combinado.restaCombinado));
    setConcepto("Saldo final");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- destinatarioDefault deriva de hayParteEstudio, estable por pedido
  }, [open, combinado.totalCombinado, combinado.restaCombinado]);

  const selectPreset = (p: Preset) => {
    setPreset(p);
    if (p === "sena") {
      setMontoInput(String(sena50));
      setConcepto("Seña");
    } else if (p === "saldo") {
      setMontoInput(String(saldo));
      setConcepto("Saldo final");
    }
    // "otro" → deja el input libre
  };

  const handleMontoChange = (v: string) => {
    setMontoInput(v);
    const n = Number(v) || 0;
    // Si el monto editado a mano ya no coincide con los presets → "otro"
    if (n !== sena50 && n !== saldo) {
      setPreset("otro");
    } else if (n === sena50) {
      setPreset("sena");
    } else if (n === saldo) {
      setPreset("saldo");
    }
  };

  const addMut = useMutation({
    mutationFn: (): Promise<Pedido & { reparto?: RepartoPagoLinea[] }> =>
      turnosVinculados.length > 0
        ? adminApi.addPagoCombinado(
            pedidoId,
            monto,
            concepto || undefined,
            fecha || undefined,
            destinatario,
            metodo,
          )
        : adminApi.addPago(
            pedidoId,
            monto,
            concepto || undefined,
            fecha || undefined,
            destinatario,
            metodo,
          ),
    onSuccess: (p) => {
      toast.success("Pago registrado");
      qc.invalidateQueries({ queryKey: ["admin", "pedido", pedidoId] });
      qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
      qc.invalidateQueries({ queryKey: ["admin", "pagos-log"] });
      turnosVinculados.forEach((t) =>
        qc.invalidateQueries({ queryKey: ["admin", "pedido", t.id] }),
      );
      const reparto = p.reparto;
      if (reparto && reparto.length > 1) {
        toast.info(
          "Reparto: " +
            reparto
              .map((r) => `#${r.pedido_id} ${fmtArs(r.monto)}${r.excedente ? " (excedente)" : ""}`)
              .join(" · "),
          { duration: 8000 },
        );
      }
      onOpenChange(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const progressPct =
    combinado.totalCombinado > 0
      ? Math.min(100, (combinado.pagadoCombinado / combinado.totalCombinado) * 100)
      : 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Registrar pago</DialogTitle>
        </DialogHeader>

        {/* Barra de progreso — combinada con los turnos vinculados (#1308):
            sin turnos, es un pass-through exacto de pagado/total/saldo. */}
        <div className="space-y-1">
          <div className="h-2 rounded-full bg-muted overflow-hidden">
            <div className="h-full bg-amber transition-all" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="font-mono text-xs text-muted-foreground">
            {fmtArs(combinado.pagadoCombinado)} de {fmtArs(combinado.totalCombinado)} · resta{" "}
            {fmtArs(saldo)}
          </div>
          {combinado.turnos.length > 0 && (
            <div className="space-y-0.5 pt-1 text-2xs text-muted-foreground">
              <div>Pedido: resta {fmtArs(Math.max(0, total - pagado))}</div>
              {combinado.turnos.map((t) => (
                <div key={t.id}>
                  Turno #{t.numero_pedido ?? t.id}: resta {fmtArs(t.resta)}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Presets */}
        <SegmentedControl
          value={preset}
          onChange={(v) => selectPreset(v as Preset)}
          options={[
            { value: "sena", label: "Seña 50%" },
            { value: "saldo", label: "Saldo total" },
            { value: "otro", label: "Otro" },
          ]}
        />

        {/* Monto */}
        <div className="space-y-1">
          <Label className="font-mono text-2xs uppercase tracking-[0.15em] text-muted-foreground">
            Monto
          </Label>
          <div className="flex items-center gap-1.5 card-elevated px-3 h-12 focus-within:ring-2 focus-within:ring-ring focus-within:border-transparent">
            <span className="font-mono text-muted-foreground text-sm">$</span>
            {/* eslint-disable-next-line no-restricted-syntax -- input custom borderless dentro de wrapper con focus-within (monto grande del modal) */}
            <input
              type="number"
              min={0}
              value={montoInput}
              onChange={(e) => handleMontoChange(e.target.value)}
              className="flex-1 bg-transparent font-mono text-xl font-semibold tabular-nums focus:outline-none"
              placeholder="0"
            />
          </div>
        </div>

        {/* Concepto */}
        <div className="space-y-1">
          <Label
            htmlFor="pago-concepto"
            className="font-mono text-2xs uppercase tracking-[0.15em] text-muted-foreground"
          >
            Concepto
          </Label>
          <Input
            id="pago-concepto"
            value={concepto}
            onChange={(e) => setConcepto(e.target.value)}
            placeholder="Seña, saldo final…"
            className="h-9 text-sm"
          />
        </div>

        {/* Fecha */}
        <div className="space-y-1">
          <Label
            htmlFor="pago-fecha"
            className="font-mono text-2xs uppercase tracking-[0.15em] text-muted-foreground"
          >
            Fecha del cobro
          </Label>
          <Input
            id="pago-fecha"
            type="date"
            value={fecha}
            onChange={(e) => setFecha(e.target.value)}
            className="h-9 text-sm"
          />
        </div>

        {/* Destinatario + método */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label className="font-mono text-2xs uppercase tracking-[0.15em] text-muted-foreground">
              Cobró
            </Label>
            <SegmentedControl
              value={destinatario}
              onChange={setDestinatario}
              options={DESTINATARIOS_PAGO.map((d) => ({ value: d, label: d }))}
            />
          </div>
          <div className="space-y-1">
            <Label className="font-mono text-2xs uppercase tracking-[0.15em] text-muted-foreground">
              Método
            </Label>
            <SegmentedControl
              value={metodo}
              onChange={setMetodo}
              options={METODOS_PAGO.map((m) => ({ value: m, label: m }))}
            />
          </div>
        </div>

        {hayParteEstudio && destinatario !== "Estudio" && (
          <p className="rounded-md border border-amber/40 bg-amber/5 px-2.5 py-2 text-xs text-ink">
            Esta plata es del Estudio — si la cobra {destinatario}, va a quedar pendiente de que{" "}
            {destinatario} se la rinda (lo vas a ver en Finanzas → Caja Estudio).
          </p>
        )}

        {/* CTA */}
        <Button
          variant="amber"
          className="w-full"
          disabled={monto <= 0 || addMut.isPending}
          onClick={() => {
            if (!monto || monto <= 0) {
              toast.error("Ingresá un monto válido");
              return;
            }
            addMut.mutate();
          }}
        >
          {addMut.isPending ? "Registrando…" : `Cobrar ${fmtArs(monto)}`}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
