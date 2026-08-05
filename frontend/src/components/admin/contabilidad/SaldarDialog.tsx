/**
 * SaldarDialog — registrar una transferencia REAL entre dos partes de la
 * rendición (Pablo/Tincho/Rental/Estudio), desde una sugerencia acumulada.
 *
 * Extraído verbatim de `contabilidad.rendicion.lazy.tsx` cuando esa página se
 * fundió en Finanzas (`contabilidad.index.lazy.tsx`). El botón dice lo que hace
 * —registra un movimiento en el libro— y no "marcar saldado", que se leía como
 * "dar el mes por visto".
 */
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Label } from "@/design-system/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/design-system/ui/dialog";
import { SegmentedControl } from "@/design-system/ui/segmented-control";
import { adminApi, METODOS_PAGO, type SugeridoRendicion } from "@/lib/admin/api";
import { formatARS } from "@/lib/format";
import { hoyAR } from "@/lib/rental-dates";

export function SaldarDialog({
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
  const [fecha, setFecha] = useState<string>(hoyAR);
  const [nota, setNota] = useState("");

  // El `rendicion_mes` del movimiento sale de la FECHA en que la plata se movió,
  // no del mes que el admin esté mirando: la sugerencia es acumulada, así que
  // "qué mes estoy viendo" no dice nada sobre cuándo se hizo la transferencia.
  // Así el movimiento aparece en el registro del mes correcto.
  const mesDelMovimiento = (fecha || hoyAR()).slice(0, 7);

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
