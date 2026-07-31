import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";

import { adminApi } from "@/lib/admin/api";

/** Espeja `backend/reportes/comisiones.py::DEFAULT_MODELO` — solo se usa si
 *  todavía no hay setting persistido (instalación nueva). Padded a matriz
 *  cuadrada (con 0 explícitos) para que se vean todas las columnas editables,
 *  igual que hace el propio backend con el modelo real. */
const DEFAULT_COMISIONES: Record<string, Record<string, number>> = {
  Rental: { Rental: 100, Pablo: 0, Tincho: 0, Estudio: 0 },
  Pablo: { Pablo: 50, Rental: 45, Tincho: 5, Estudio: 0 },
  Tincho: { Tincho: 50, Rental: 45, Pablo: 5, Estudio: 0 },
  Estudio: { Estudio: 100, Rental: 0, Pablo: 0, Tincho: 0 },
};

/** Todos los dueños/beneficiarios que aparecen en el modelo (unión de claves de
 *  primer y segundo nivel) — el set de filas/columnas sale de LOS DATOS, no de
 *  una lista fija en el front (bug real: un beneficiario nuevo agregado del
 *  lado backend, como "Estudio", quedaba invisible acá y un "Guardar" lo
 *  borraba en silencio del setting persistido). */
function keysOf(m: Record<string, Record<string, number>>): string[] {
  const set = new Set<string>(Object.keys(m));
  for (const d of Object.keys(m)) for (const b of Object.keys(m[d] ?? {})) set.add(b);
  return Array.from(set);
}

export function ComisionesSection() {
  const qc = useQueryClient();
  const [model, setModel] = useState<Record<string, Record<string, number>> | null>(null);
  const keys = model ? Object.keys(model) : [];

  const settingQ = useQuery({
    queryKey: ["settings", "comisiones_modelo"],
    queryFn: () => adminApi.getSetting("comisiones_modelo"),
    retry: false,
    staleTime: 0,
  });

  // Inicializa desde el setting (o el default) una vez que el fetch terminó.
  useEffect(() => {
    if (model !== null || !settingQ.isFetched) return;
    let parsed: Record<string, Record<string, number>> | null = null;
    try {
      parsed = settingQ.data?.value ? JSON.parse(settingQ.data.value) : null;
    } catch {
      parsed = null;
    }
    const base = parsed ?? DEFAULT_COMISIONES;
    const baseKeys = keysOf(base);
    const next: Record<string, Record<string, number>> = {};
    for (const d of baseKeys) {
      next[d] = {};
      for (const b of baseKeys) next[d][b] = Number(base[d]?.[b] ?? 0);
    }
    setModel(next);
  }, [settingQ.data, settingQ.isFetched, model]);

  const updateMut = useMutation({
    mutationFn: (v: string) => adminApi.updateSetting("comisiones_modelo", v),
    onSuccess: () => {
      toast.success("Reparto de comisiones actualizado");
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["admin", "liquidacion"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const setPct = (dueno: string, benef: string, v: number) =>
    setModel((prev) => (prev ? { ...prev, [dueno]: { ...prev[dueno], [benef]: v } } : prev));

  const sumOf = (dueno: string) =>
    model ? keys.reduce((s, b) => s + (model[dueno][b] || 0), 0) : 0;

  const save = () => {
    if (!model) return;
    for (const d of keys) {
      if (Math.abs(sumOf(d) - 100) > 0.01) {
        toast.error(`${d}: los porcentajes deben sumar 100 (suman ${sumOf(d)}).`);
        return;
      }
    }
    updateMut.mutate(JSON.stringify(model));
  };

  return (
    <section className="card p-4 space-y-3">
      <div>
        <h2 className="font-display text-lg text-ink">Reparto de comisiones por dueño</h2>
        <p className="text-xs text-muted-foreground mt-0.5">
          Cuando un equipo de un dueño genera ingresos, así se reparte entre los beneficiarios. Los
          porcentajes de cada dueño deben sumar 100. Se usa en el reporte de liquidación
          (Estadísticas → Reportes).
        </p>
      </div>
      <div className="border-t hairline pt-3 space-y-4">
        {model &&
          keys.map((dueno) => {
            const suma = sumOf(dueno);
            const ok = Math.abs(suma - 100) <= 0.01;
            return (
              <div key={dueno} className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-ink">Equipos de {dueno}</span>
                  <span
                    className={`text-xs tabular-nums ${ok ? "text-muted-foreground" : "text-destructive"}`}
                  >
                    suma {suma}%
                  </span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {keys.map((benef) => (
                    <label key={benef} className="text-xs text-muted-foreground">
                      {benef}
                      <Input
                        type="number"
                        min={0}
                        max={100}
                        value={model[dueno][benef]}
                        onChange={(e) => setPct(dueno, benef, Number(e.target.value))}
                        className="mt-1"
                      />
                    </label>
                  ))}
                </div>
              </div>
            );
          })}
        <div className="pt-1">
          <Button size="sm" onClick={save} disabled={!model || updateMut.isPending}>
            {updateMut.isPending ? "Guardando…" : "Guardar reparto"}
          </Button>
        </div>
      </div>
    </section>
  );
}
