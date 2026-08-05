/**
 * AvanzadoSection — estado, valor de reposición, fecha de compra, serie,
 * notas internas.
 *
 * Extraído verbatim de `EquipoFormDialog.tsx` (split de god-module, Frente E
 * del skill `mantenimiento`, F2c #1263). Cero cambio de comportamiento.
 */
import type { UseFormReturn } from "react-hook-form";
import { Input } from "@/design-system/ui/input";
import { Textarea } from "@/design-system/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/design-system/ui/select";
import { MonthYearPicker } from "@/components/admin/MonthYearPicker";
import { Field, CollapsibleSection } from "./form-helpers";
import type { FormValues } from "./equipo-form-schema";

export function AvanzadoSection({
  form,
  notas,
  setNotas,
}: {
  form: UseFormReturn<FormValues>;
  notas: string;
  setNotas: (v: string) => void;
}) {
  return (
    <CollapsibleSection title="Avanzado">
      <div className="space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <Field label="Estado">
            <Select
              value={form.watch("estado")}
              onValueChange={(v) =>
                form.setValue("estado", v as FormValues["estado"], { shouldDirty: true })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="operativo">Operativo</SelectItem>
                <SelectItem value="en_mantenimiento">En mantenimiento</SelectItem>
                <SelectItem value="fuera_servicio">Fuera de servicio</SelectItem>
              </SelectContent>
            </Select>
          </Field>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <Field label="Valor reposición (USD)">
            <Input type="number" step="0.01" {...form.register("valor_reposicion")} />
          </Field>
          {/* ARS, no USD como valor_reposicion — lo que costó COMPRARLO, para
              el ranking "rentabilidad neta" (ingreso − costo) de Estadísticas.
              Nullable a propósito: un equipo sin este dato sigue en el resto
              de la pantalla, solo queda afuera de ese ranking puntual. */}
          <Field label="Costo de compra (ARS)">
            <Input type="number" step="1" {...form.register("costo_compra")} />
          </Field>
          <Field label="Fecha de compra">
            <MonthYearPicker
              value={form.watch("fecha_compra") ?? ""}
              onChange={(v) => form.setValue("fecha_compra", v, { shouldDirty: true })}
            />
          </Field>
          <Field label="N° de serie">
            <Input {...form.register("serie")} placeholder="N/A si no tenés" />
          </Field>
        </div>

        <Field label="Notas internas (no se muestran al cliente)">
          <Textarea rows={2} value={notas} onChange={(e) => setNotas(e.target.value)} />
        </Field>
      </div>
    </CollapsibleSection>
  );
}
