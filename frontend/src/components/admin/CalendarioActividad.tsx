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

// Un único timeline continuo entre `desde` y `hasta` — puede abarcar más de
// un año (modo "Todos"): las semanas NO se cortan ni reinician en cada 1° de
// enero, siguen fluyendo (mismo criterio que la vista "últimos 12 meses" de
// GitHub, generalizado a un rango arbitrario en vez de fijo a 1 año).
function buildSemanas(desde: Date, hasta: Date, porDia: PorDiaMap): Celda[][] {
  const offsetInicio = (desde.getDay() + 6) % 7; // getDay(): 0=domingo → acá 0=lunes

  const celdas: Celda[] = Array(offsetInicio).fill(null);
  const cursor = new Date(desde);
  while (cursor <= hasta) {
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

// El label de cada semana es el mes — salvo en la semana donde arranca enero,
// que muestra el AÑO en su lugar cuando `mostrarAnioEnEnero` (modo "Todos"):
// así un timeline multi-año deja clara la frontera entre años sin gastar una
// fila aparte. En modo un-solo-año se muestra "Ene" como siempre (el pill del
// año ya está arriba, repetirlo acá sería redundante). Semanas sin ningún día
// real (padding puro, solo en los bordes) no llevan label.
function semanaLabels(semanas: Celda[][], mostrarAnioEnEnero: boolean): (string | null)[] {
  const labels: (string | null)[] = [];
  let ultimoMes = -1;
  for (const semana of semanas) {
    const primerCeldaReal = semana.find((c): c is NonNullable<Celda> => c !== null);
    if (!primerCeldaReal) {
      labels.push(null);
      continue;
    }
    const [anioStr, mesStr] = primerCeldaReal.dia.split("-");
    const mes = Number(mesStr) - 1;
    if (mes === ultimoMes) {
      labels.push(null);
    } else if (mes === 0 && mostrarAnioEnEnero) {
      labels.push(anioStr);
    } else {
      labels.push(MESES_ABREV[mes]);
    }
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
  const anioActual = new Date().getFullYear();
  // Un año: desde el 1° de enero de ese año hasta su 31 de diciembre. Todos:
  // desde el primer año con datos hasta el último — un timeline continuo, no
  // grillas separadas por año.
  const { desde, hasta } =
    modo === "todos" && anios.length > 0
      ? { desde: new Date(anios[0], 0, 1), hasta: new Date(anios[anios.length - 1], 11, 31) }
      : {
          desde: new Date(data?.anio ?? anioSeleccionado ?? anioActual, 0, 1),
          hasta: new Date(data?.anio ?? anioSeleccionado ?? anioActual, 11, 31),
        };

  const semanas = useMemo(() => buildSemanas(desde, hasta, porDia), [desde, hasta, porDia]);
  const labels = useMemo(() => semanaLabels(semanas, modo === "todos"), [semanas, modo]);

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
                  modo === "anio" && a === (data?.anio ?? anioSeleccionado)
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
          <div className="inline-flex gap-1">
            <div className="flex flex-col gap-1 mr-1 pt-5">
              {DIAS_SEMANA.map((d, i) => (
                <div
                  key={i}
                  className="h-[13px] w-[18px] text-2xs leading-[13px] text-muted-foreground"
                >
                  {/* Lun/Miér/Vie (no cada fila) — mismo criterio que GitHub,
                      anclado al lunes (la primera fila visible). */}
                  {i === 0 || i === 2 || i === 4 ? d : ""}
                </div>
              ))}
            </div>
            {semanas.map((semana, wi) => (
              <div key={wi} className="flex flex-col gap-1">
                <div className="h-4 text-2xs leading-4 text-muted-foreground whitespace-nowrap">
                  {labels[wi] ?? ""}
                </div>
                {semana.map((celda, di) =>
                  celda ? (
                    <div
                      key={di}
                      title={`${fmtDiaLargo(celda.dia)}: ${celda.pedidosActivos} pedido${celda.pedidosActivos === 1 ? "" : "s"} con equipo afuera`}
                      className={cn("h-[13px] w-[13px] rounded-[3px]", TIER_BG[celda.tier])}
                    />
                  ) : (
                    <div key={di} className="h-[13px] w-[13px]" />
                  ),
                )}
              </div>
            ))}
          </div>
          <div className="flex items-center justify-end gap-1 mt-2">
            <span className="text-2xs text-muted-foreground">Menos</span>
            {[0, 1, 2, 3, 4].map((t) => (
              <div key={t} className={cn("h-[13px] w-[13px] rounded-[3px]", TIER_BG[t])} />
            ))}
            <span className="text-2xs text-muted-foreground">Más</span>
          </div>
        </div>
      )}
    </div>
  );
}
