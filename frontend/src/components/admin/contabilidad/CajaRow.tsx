/**
 * CajaRow — fila editable de una caja real del negocio (Efectivo/Banco/Fondo…).
 *
 * Extraído verbatim de `contabilidad.cuentas.lazy.tsx` cuando esa página se
 * fundió en Finanzas (`contabilidad.index.lazy.tsx`). Solo se edita el nombre:
 * el saldo se corrige con "Corregir un saldo a mano" (un `ajuste` registrado).
 */
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { adminApi, type CuentaSaldo } from "@/lib/admin/api";
import { useConfirm } from "@/components/admin/useConfirm";
import { formatMoney } from "@/lib/format";
import { Badge } from "@/design-system/ui/badge";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { cn } from "@/lib/utils";

export function CajaRow({ cuenta, onChanged }: { cuenta: CuentaSaldo; onChanged: () => void }) {
  const confirm = useConfirm();
  const [editando, setEditando] = useState(false);
  const [nombre, setNombre] = useState(cuenta.nombre);

  const cerrar = () => {
    setEditando(false);
    setNombre(cuenta.nombre);
  };

  // Solo el nombre: el saldo inicial fue del arranque del sistema (migración) y
  // ya no se muestra ni se edita — para corregir el saldo de una caja se usa
  // "Corregir un saldo a mano" (un `ajuste`, que queda registrado).
  const guardar = useMutation({
    mutationFn: () => adminApi.updateCuenta(cuenta.id, { nombre: nombre.trim() }),
    onSuccess: () => {
      setEditando(false);
      toast.success("Cuenta actualizada");
      onChanged();
    },
    onError: (e) => toast.error("No se pudo actualizar", { description: (e as Error).message }),
  });

  const baja = useMutation({
    mutationFn: () => adminApi.deactivateCuenta(cuenta.id),
    onSuccess: () => {
      toast.success("Cuenta dada de baja");
      onChanged();
    },
    onError: (e) => toast.error("No se pudo dar de baja", { description: (e as Error).message }),
  });

  // El Fondo Rental representa al cobrador Rental: recibe cobros, no se da de baja.
  const esCobrador = Boolean(cuenta.socio);

  return (
    <tr className="border-b hairline last:border-0">
      <td className="px-3 py-2 font-medium text-ink">
        {editando ? (
          <Input value={nombre} onChange={(e) => setNombre(e.target.value)} className="w-44" />
        ) : (
          cuenta.nombre
        )}
      </td>
      <td className="px-3 py-2">
        <Badge variant="secondary" className="capitalize">
          {cuenta.tipo}
        </Badge>
      </td>
      <td className="px-3 py-2 text-right font-mono font-semibold tabular-nums">
        {formatMoney(cuenta.saldo, cuenta.moneda)}
      </td>
      <td className="px-3 py-2 text-right">
        {editando ? (
          <div className="flex items-center justify-end gap-1">
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={() => guardar.mutate()}
              disabled={guardar.isPending || !nombre.trim()}
            >
              Guardar
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={cerrar}>
              Cancelar
            </Button>
          </div>
        ) : (
          <div className="flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={() => setEditando(true)}
              className="text-xs text-muted-foreground underline hover:text-ink"
              title="Editar nombre y saldo inicial"
            >
              Editar
            </button>
            <button
              type="button"
              onClick={async () => {
                if (
                  await confirm({
                    title: `¿Dar de baja "${cuenta.nombre}"?`,
                    description: "Solo se puede si su saldo es cero.",
                    danger: true,
                    confirmLabel: "Dar de baja",
                  })
                )
                  baja.mutate();
              }}
              disabled={baja.isPending || esCobrador}
              className={cn(
                "text-xs underline",
                esCobrador
                  ? "text-muted-foreground/40 cursor-not-allowed no-underline"
                  : "text-muted-foreground hover:text-destructive",
              )}
              title={esCobrador ? "El Fondo Rental no se da de baja" : "Dar de baja"}
            >
              Baja
            </button>
          </div>
        )}
      </td>
    </tr>
  );
}
