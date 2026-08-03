/**
 * NuevaCuentaForm — alta de una caja/cuenta genérica del negocio.
 *
 * Extraído verbatim de `contabilidad.cuentas.lazy.tsx` cuando esa página se
 * fundió en Finanzas (`contabilidad.index.lazy.tsx`). El socio se crea desde
 * el sistema (seed); acá solo cajas/cuentas genéricas, que nacen en 0.
 */
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { adminApi, type TipoCuenta } from "@/lib/admin/api";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";

// El socio se crea desde el sistema (seed); acá solo cajas/cuentas genéricas.
const TIPOS_CREABLES: TipoCuenta[] = ["caja", "banco", "fondo"];

export function NuevaCuentaForm({ onCreated }: { onCreated: () => void }) {
  const [nombre, setNombre] = useState("");
  const [tipo, setTipo] = useState<TipoCuenta>("caja");
  const [moneda, setMoneda] = useState("ARS");

  const crear = useMutation({
    mutationFn: () =>
      // Sin `saldo_inicial`: nace en 0. El saldo inicial fue del arranque del
      // sistema (migración) y se retiró — si la caja ya tiene plata, se carga
      // con "Corregir un saldo a mano" (queda registrado como un movimiento).
      adminApi.createCuenta({ nombre: nombre.trim(), tipo, moneda }),
    onSuccess: () => {
      setNombre("");
      setTipo("caja");
      setMoneda("ARS");
      toast.success("Cuenta creada");
      onCreated();
    },
    onError: (e) =>
      toast.error("No se pudo crear la cuenta", { description: (e as Error).message }),
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!nombre.trim()) return;
        crear.mutate();
      }}
      className="rounded-lg border hairline p-4 space-y-3"
    >
      <div className="t-eyebrow">Nueva caja</div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1">
          <span className="block t-eyebrow">Nombre</span>
          <Input
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            placeholder="Ej. Mercado Pago"
            className="w-48"
          />
        </label>
        <label className="space-y-1">
          <span className="block t-eyebrow">Tipo</span>
          <select
            value={tipo}
            onChange={(e) => setTipo(e.target.value as TipoCuenta)}
            className="h-9 rounded-md border hairline bg-surface-elevated px-2 text-sm capitalize"
          >
            {TIPOS_CREABLES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="block t-eyebrow">Moneda</span>
          <select
            value={moneda}
            onChange={(e) => setMoneda(e.target.value)}
            className="h-9 rounded-md border hairline bg-surface-elevated px-2 text-sm"
          >
            <option value="ARS">Pesos (ARS)</option>
            <option value="USD">Dólares (USD)</option>
          </select>
        </label>
        <Button type="submit" variant="primary" disabled={crear.isPending || !nombre.trim()}>
          {crear.isPending ? "Creando…" : "Crear"}
        </Button>
      </div>
    </form>
  );
}
