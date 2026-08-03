/**
 * SocioCard — la cuenta corriente de un socio humano (Pablo/Tincho).
 *
 * NO es una caja de plata: es el saldo de la rendición acumulada — DEUDOR (le
 * debe a Rental) / ACREEDOR (Rental le debe). Sale de: arranque + cobró − su
 * parte ± rendiciones. Se salda solo con su parte de lo que se alquila.
 *
 * Extraído verbatim de `contabilidad.cuentas.lazy.tsx` cuando esa página se
 * fundió en Finanzas (`contabilidad.index.lazy.tsx`).
 */
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { adminApi, type CuentaSaldo } from "@/lib/admin/api";
import { MoverPlataForm } from "@/components/admin/contabilidad/MoverPlataForm";
import { formatMoney } from "@/lib/format";
import { Button } from "@/design-system/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/design-system/ui/dialog";
import { Input } from "@/design-system/ui/input";
import { Pill, type PillTone } from "@/design-system/ui/Pill";
import { cn } from "@/lib/utils";

export function SocioCard({ socio, onChanged }: { socio: CuentaSaldo; onChanged: () => void }) {
  const [editando, setEditando] = useState(false);
  const [arranque, setArranque] = useState(String(socio.saldo_inicial));
  const [movAbierto, setMovAbierto] = useState(false);

  const guardar = useMutation({
    mutationFn: () => adminApi.updateCuenta(socio.id, { saldo_inicial: Number(arranque) || 0 }),
    onSuccess: () => {
      setEditando(false);
      toast.success("Arranque actualizado");
      onChanged();
    },
    onError: (e) => toast.error("No se pudo actualizar", { description: (e as Error).message }),
  });

  const abs = Math.abs(socio.saldo);
  // El nombre de la PERSONA ("Tincho"), no el de su cuenta ("Caja Tincho"):
  // "Rental le debe a Caja Tincho" se leía raro en la página unificada.
  const nombre = socio.socio ?? socio.nombre;
  const frase =
    socio.estado === "deudor"
      ? `${nombre} le debe a Rental`
      : socio.estado === "acreedor"
        ? `Rental le debe a ${nombre}`
        : "A mano";
  const color =
    socio.estado === "deudor"
      ? "text-destructive"
      : socio.estado === "acreedor"
        ? "text-verde-ink"
        : "text-ink";
  const tag =
    socio.estado === "deudor" ? "Deudor" : socio.estado === "acreedor" ? "Acreedor" : "Saldado";
  const tagTone: PillTone =
    socio.estado === "deudor" ? "danger" : socio.estado === "acreedor" ? "success" : "neutral";

  return (
    <div className="rounded-lg border hairline p-4 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="font-medium text-ink">{nombre}</div>
        <Pill tone={tagTone} className="font-mono uppercase tracking-wider">
          {tag}
        </Pill>
      </div>
      <div className={cn("font-mono text-2xl font-semibold tabular-nums", color)}>
        {formatMoney(abs, socio.moneda)}
      </div>
      <div className="text-sm text-muted-foreground">{frase}</div>
      <div className="font-mono text-xs text-muted-foreground tabular-nums">
        arranque {formatMoney(socio.saldo_inicial, socio.moneda)} · cobró{" "}
        {formatMoney(socio.ingresos_alquiler, socio.moneda)} · su parte{" "}
        {formatMoney(socio.su_parte, socio.moneda)}
      </div>
      {editando ? (
        <div className="flex items-center gap-1 pt-1">
          <Input
            type="number"
            value={arranque}
            onChange={(e) => setArranque(e.target.value)}
            className="w-32 text-right tabular-nums"
            aria-label="Arranque"
          />
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={() => guardar.mutate()}
            disabled={guardar.isPending}
          >
            Guardar
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setEditando(false);
              setArranque(String(socio.saldo_inicial));
            }}
          >
            Cancelar
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setMovAbierto(true)}
            className="text-xs text-ink underline hover:text-ink"
          >
            Registrar movimiento
          </button>
          <button
            type="button"
            onClick={() => setEditando(true)}
            className="text-xs text-muted-foreground underline hover:text-ink"
            title="Editar el arranque (lo que cobró antes del sistema)"
          >
            Editar arranque
          </button>
        </div>
      )}

      {/* Un socio rindiendo (o Rental cargándole algo) ES un reparto: la misma
          operación que "Repartimos" en Movimientos. Antes había acá un formulario
          propio —toggle "Me pagó / Le cargué", monto, caja, nota— que posteaba
          exactamente el mismo `transferencia`, con menos campos (sin fecha, método,
          beneficiario ni comprobante). Ahora se abre el form único, precargado con
          el socio de un lado; darlo vuelta es cambiar los dos selectores.

          Montado CONDICIONALMENTE, no solo `open`: `inicial` alimenta los valores
          iniciales de estado, así que un componente que sobrevive entre aperturas
          se quedaría con el socio anterior. */}
      <Dialog open={movAbierto} onOpenChange={setMovAbierto}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Mover plata · {socio.nombre}</DialogTitle>
          </DialogHeader>
          {movAbierto && (
            <MoverPlataForm
              chrome="plain"
              inicial={{ quePaso: "reparto", cuentaOrigenId: socio.id }}
              onCreated={() => {
                setMovAbierto(false);
                onChanged();
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
