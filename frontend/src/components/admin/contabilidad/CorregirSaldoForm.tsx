/**
 * CorregirSaldoForm.tsx — el `ajuste`, aparte y con fricción a propósito.
 *
 * `ajuste` es, por definición, "el modelo no captura la realidad": acepta una
 * cuenta o dos, no lleva categoría y no cuenta en el P&L. Ponerlo como quinta
 * opción al lado de las 4 reales (`MoverPlataForm`) invita a usarlo de cajón de
 * sastre para cualquier cosa que no se sepa cómo cargar — que es exactamente cómo
 * se pudre un libro contable. Por eso vive acá: colapsado, fuera del flujo normal,
 * y con **nota obligatoria** (el form general la deja opcional).
 *
 * Su otro uso legítimo —las dos patas de un cambio de divisa— ya lo deriva
 * `mover-plata.ts` solo, sin que nadie tenga que elegir "ajuste".
 */
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { CuentaSelect, Field } from "@/components/admin/contabilidad/fields";
import { adminApi, type Cuenta } from "@/lib/admin/api";

export function CorregirSaldoForm({ onCreated }: { onCreated: () => void }) {
  const [abierto, setAbierto] = useState(false);
  const [monto, setMonto] = useState("");
  const [origen, setOrigen] = useState("");
  const [destino, setDestino] = useState("");
  const [fecha, setFecha] = useState("");
  const [nota, setNota] = useState("");

  const cuentasQ = useQuery({
    queryKey: ["admin", "contabilidad", "cuentas-list"],
    queryFn: () => adminApi.listCuentas(),
  });
  const cuentas: Cuenta[] = cuentasQ.data?.cuentas ?? [];

  const crear = useMutation({
    mutationFn: () =>
      adminApi.createMovimiento({
        tipo: "ajuste",
        monto: Number(monto) || 0,
        cuenta_origen_id: origen ? Number(origen) : null,
        cuenta_destino_id: destino ? Number(destino) : null,
        categoria_id: null,
        metodo: null,
        fecha: fecha || null,
        nota: nota.trim(),
        beneficiario: null,
      }),
    onSuccess: () => {
      setMonto("");
      setOrigen("");
      setDestino("");
      setFecha("");
      setNota("");
      setAbierto(false);
      toast.success("Corrección registrada");
      onCreated();
    },
    onError: (e) => toast.error("No se pudo registrar", { description: (e as Error).message }),
  });

  if (!abierto) {
    return (
      <button
        type="button"
        onClick={() => setAbierto(true)}
        className="min-h-11 text-xs text-muted-foreground underline underline-offset-2 hover:text-ink"
      >
        ¿Necesitás corregir un saldo a mano?
      </button>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!(Number(monto) > 0)) return toast.error("Poné un monto mayor a cero.");
        if (!origen && !destino) return toast.error("Elegí al menos una cuenta.");
        if (!nota.trim()) return toast.error("Contá por qué hacés la corrección — es obligatorio.");
        crear.mutate();
      }}
      className="rounded-lg border border-amber/40 bg-amber/5 p-4 space-y-3"
    >
      <div>
        <div className="t-eyebrow">Corregir un saldo a mano</div>
        <p className="mt-1 text-xs text-muted-foreground">
          Solo cuando la plata no se movió como el sistema la registró. No cuenta en la ganancia y
          no lleva rubro — por eso la nota es obligatoria.
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Monto">
          <Input
            type="number"
            step="1"
            min="1"
            value={monto}
            onChange={(e) => setMonto(e.target.value)}
            className="w-32 text-right tabular-nums"
          />
        </Field>
        <Field label="Sale de (opcional)">
          <CuentaSelect cuentas={cuentas} value={origen} onChange={setOrigen} placeholder="—" />
        </Field>
        <Field label="Entra a (opcional)">
          <CuentaSelect cuentas={cuentas} value={destino} onChange={setDestino} placeholder="—" />
        </Field>
        <Field label="Fecha">
          <Input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />
        </Field>
      </div>
      <Field label="Por qué (obligatorio)">
        <Input
          value={nota}
          onChange={(e) => setNota(e.target.value)}
          placeholder="Ej. el banco cobró una comisión que no estaba registrada"
          className="w-full"
        />
      </Field>
      <div className="flex items-center gap-2">
        <Button
          type="submit"
          variant="primary"
          disabled={crear.isPending}
          loading={crear.isPending}
        >
          {crear.isPending ? "Guardando…" : "Registrar corrección"}
        </Button>
        <Button type="button" variant="outline" onClick={() => setAbierto(false)}>
          Cancelar
        </Button>
      </div>
    </form>
  );
}
