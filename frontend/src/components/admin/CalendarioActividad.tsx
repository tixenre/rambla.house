import { useMemo } from "react";

import { cn } from "@/lib/utils";
import type { ActividadCalendarioData } from "@/lib/admin/api/types";

const DIAS_SEMANA = ["L", "M", "M", "J", "V", "S", "D"];
const MESES_ABREV = [
  "Ene",
  "Feb",
  "Mar",
  "Abr",
  "May",
  "Jun",
  "Jul",
  "Ago",
  "Sep",
  "Oct",
  "Nov",
  "Dic",
];

// tier 0-4 → los 5 tokens del heatmap (--color-heat-1..4 derivados de
// --color-amber por color-mix, ver tokens/colors.css; tier 0 = --color-muted).
const TIER_BG: Record<number, string> = {
  0: "bg-muted",
  1: "bg-heat-1",
  2: "bg-heat-2",
  3: "bg-heat-3",
  4: "bg-heat-4",
};

type Celda = { dia: string; pedidosActivos: number; tier: number } | null;
type PorDiaMap = Map<string, { pedidos_activos: number; tier: number }>;

// Evita Date#toISOString: convierte a UTC y en UTC-3 corre la medianoche
// local al día anterior — acá solo importan fechas de calendario, sin hora.
function isoLocal(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function buildSemanas(anio: number, porDia: PorDiaMap): Celda[][] {
  const primerDia = new Date(anio, 0, 1);
  const ultimoDia = new Date(anio, 11, 31);
  const offsetInicio = (primerDia.getDay() + 6) % 7; // getDay(): 0=domingo → acá 0=lunes

  const celdas: Celda[] = Array(offsetInicio).fill(null);
  const cursor = new Date(primerDia);
  while (cursor <= ultimoDia) {
    const iso = isoLocal(cursor);
    const info = porDia.get(iso);
    celdas.push({ dia: iso, pedidosActivos: info?.pedidos_activos ?? 0, tier: info?.tier ?? 0 });
    cursor.setDate(cursor.getDate() + 1);
  }
  while (celdas.length % 7 !== 0) celdas.push(null);

  const semanas: Celda[][] = [];
  for (let i = 0; i < celdas.length; i += 7) semanas.push(celdas.slice(i, i + 7));
  return semanas;
}

// El label de mes va en la primera columna (semana) donde aparece un día 1 —
// mismo criterio que GitHub. Semanas sin ningún día real (padding puro, solo
// puede pasar en los bordes) no llevan label.
function mesLabels(semanas: Celda[][]): (string | null)[] {
  const labels: (string | null)[] = [];
  let ultimoMes = -1;
  for (const semana of semanas) {
    const primerCeldaReal = semana.find((c): c is NonNullable<Celda> => c !== null);
    if (!primerCeldaReal) {
      labels.push(null);
      continue;
    }
    const mes = Number(primerCeldaReal.dia.slice(5, 7)) - 1;
    labels.push(mes !== ultimoMes ? MESES_ABREV[mes] : null);
    ultimoMes = mes;
  }
  return labels;
}

function fmtDiaLargo(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("es-AR", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

// Una grilla de un único año (weekday labels + semanas) — la unidad que se
// muestra sola en modo "un año" o apilada N veces en modo "Todos".
function GrillaAnio({
  anio,
  porDia,
  mostrarAnio,
}: {
  anio: number;
  porDia: PorDiaMap;
  mostrarAnio?: boolean;
}) {
  const semanas = useMemo(() => buildSemanas(anio, porDia), [anio, porDia]);
  const labels = useMemo(() => mesLabels(semanas), [semanas]);

  return (
    <div>
      {mostrarAnio && <div className="text-xs font-semibold text-ink mb-1">{anio}</div>}
      <div className="inline-flex gap-[3px]">
        <div className="flex flex-col gap-[3px] mr-1 pt-[18px]">
          {DIAS_SEMANA.map((d, i) => (
            <div key={i} className="h-[11px] w-4 text-3xs leading-[11px] text-muted-foreground">
              {/* Lun/Miér/Vie (no cada fila) — mismo criterio que GitHub,
                  anclado al lunes (la primera fila visible). */}
              {i === 0 || i === 2 || i === 4 ? d : ""}
            </div>
          ))}
        </div>
        {semanas.map((semana, wi) => (
          <div key={wi} className="flex flex-col gap-[3px]">
            <div className="h-[14px] text-3xs leading-[14px] text-muted-foreground whitespace-nowrap">
              {labels[wi] ?? ""}
            </div>
            {semana.map((celda, di) =>
              celda ? (
                <div
                  key={di}
                  title={`${fmtDiaLargo(celda.dia)}: ${celda.pedidosActivos} pedido${celda.pedidosActivos === 1 ? "" : "s"} con equipo afuera`}
                  className={cn("h-[11px] w-[11px] rounded-[2px]", TIER_BG[celda.tier])}
                />
              ) : (
                <div key={di} className="h-[11px] w-[11px]" />
              ),
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function CalendarioActividad({
  data,
  loading,
  modo,
  anioSeleccionado,
  onSeleccionarAnio,
  onSeleccionarTodos,
}: {
  data: ActividadCalendarioData | undefined;
  loading?: boolean;
  modo: "anio" | "todos";
  anioSeleccionado: number | undefined;
  onSeleccionarAnio: (anio: number) => void;
  onSeleccionarTodos: () => void;
}) {
  const porDia = useMemo(() => {
    const m: PorDiaMap = new Map();
    for (const d of data?.dias ?? []) m.set(d.dia, d);
    return m;
  }, [data]);

  const anios = data?.anios_disponibles ?? [];
  const anio = data?.anio ?? anioSeleccionado ?? new Date().getFullYear();

  return (
    <div>
      <div className="flex items-center justify-between gap-2 mb-3">
        <p className="text-sm text-muted-foreground">
          Días con equipo afuera — un pedido enciende todos sus días, no solo el retiro.
        </p>
        {anios.length > 1 && (
          <div className="flex gap-1">
            {anios.map((a) => (
              <button
                key={a}
                onClick={() => onSeleccionarAnio(a)}
                className={cn(
                  "rounded-full px-3 py-1 text-xs font-medium border hairline transition",
                  modo === "anio" && a === anio
                    ? "bg-ink text-background"
                    : "text-muted-foreground hover:text-ink",
                )}
              >
                {a}
              </button>
            ))}
            <button
              onClick={onSeleccionarTodos}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium border hairline transition",
                modo === "todos"
                  ? "bg-ink text-background"
                  : "text-muted-foreground hover:text-ink",
              )}
            >
              Todos
            </button>
          </div>
        )}
      </div>

      {loading ? (
        <div className="h-32 animate-pulse rounded-lg bg-muted" />
      ) : (
        <div className="overflow-x-auto">
          {modo === "todos" ? (
            <div className="space-y-4">
              {anios.map((a) => (
                <GrillaAnio key={a} anio={a} porDia={porDia} mostrarAnio />
              ))}
            </div>
          ) : (
            <GrillaAnio anio={anio} porDia={porDia} />
          )}
          <div className="flex items-center justify-end gap-1 mt-2">
            <span className="text-3xs text-muted-foreground">Menos</span>
            {[0, 1, 2, 3, 4].map((t) => (
              <div key={t} className={cn("h-[11px] w-[11px] rounded-[2px]", TIER_BG[t])} />
            ))}
            <span className="text-3xs text-muted-foreground">Más</span>
          </div>
        </div>
      )}
    </div>
  );
}
