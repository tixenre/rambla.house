/**
 * fields.tsx — controles chicos compartidos entre los forms de contabilidad
 * (MoverPlataForm, CorregirSaldoForm). Extraídos para no duplicar
 * (una sola forma de cada cosa).
 */
import type { Cuenta } from "@/lib/admin/api";

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="space-y-1">
      <span className="block t-eyebrow">{label}</span>
      {children}
    </label>
  );
}

export function CuentaSelect({
  cuentas,
  value,
  onChange,
  placeholder = "Elegir…",
}: {
  cuentas: Cuenta[];
  value: string;
  onChange: (v: string) => void;
  /** Texto de la opción vacía — "Elegir…" en un form (requiere elegir),
   *  "Todas las cuentas" en un filtro (vacío = sin filtrar). */
  placeholder?: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-9 rounded-md border hairline bg-surface-elevated px-2 text-sm"
    >
      <option value="">{placeholder}</option>
      {cuentas.map((c) => (
        <option key={c.id} value={c.id}>
          {c.nombre}
        </option>
      ))}
    </select>
  );
}
