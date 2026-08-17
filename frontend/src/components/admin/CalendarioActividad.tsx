import { Fragment, useMemo } from "react";

import { cn } from "@/lib/utils";
import type { ActividadCalendarioData } from "@/lib/admin/api/types";

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
const MESES_LARGO = [
  "enero",
  "febrero",
  "marzo",
  "abril",
  "mayo",
  "junio",
  "julio",
  "agosto",
  "septiembre",
  "octubre",
  "noviembre",
  "diciembre",
];

// Fila = mes, columna = día del mes (1-31) — así el 1°, el 15°, etc. de cada
// mes quedan siempre en la misma columna. Grilla fluida (columnas `1fr`):
// las celdas ocupan todo el ancho disponible de la card en vez de un tamaño
// fijo chico — `minmax` evita que se aplasten en viewports angostos.
const DIAS_DEL_MES = Array.from({ length: 31 }, (_, i) => i + 1);
const GRID_COLS = "auto repeat(31, minmax(20px, 1fr))";

// tier 0-4 → los 5 tokens del heatmap (--color-heat-1..4 derivados de
// --color-amber por color-mix, ver tokens/colors.css; tier 0 = --color-muted).
const TIER_BG: Record<number, string> = {
  0: "bg-muted",
  1: "bg-heat-1",
  2: "bg-heat-2",
  3: "bg-heat-3",
  4: "bg-heat-4",
};

type CeldaInfo = { pedidosActivos: number; tier: number };

// Clave de lookup: modo año usa la fecha real (`YYYY-MM-DD`, matchea
// `dia` tal cual lo manda el backend); modo "todos" usa `MM-DD` (el backend
// ya la manda así — sin año, es la suma cross-year de ese día del año).
function claveCelda(modo: "anio" | "todos", anio: number | undefined, mes: number, dia: number) {
  const mm = String(mes).padStart(2, "0");
  const dd = String(dia).padStart(2, "0");
  return modo === "todos" ? `${mm}-${dd}` : `${anio}-${mm}-${dd}`;
}

// El backend solo manda filas para días CON actividad (`pedidos_activos >
// 0`) — un día real sin actividad simplemente no aparece. Sin esto, "sin
// datos" sería ambiguo entre "31 de abril no existe" (celda vacía) y "1 de
// abril existió y tuvo 0 pedidos" (celda tier 0, como el resto del heatmap).
// Modo "todos": sin un año único, se usa el máximo posible por mes (29 en
// febrero) para no esconder ese día según qué años haya en el rango.
const DIAS_EN_MES_GENERICO = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
function diasEnMes(modo: "anio" | "todos", anio: number, mes: number): number {
  return modo === "todos" ? DIAS_EN_MES_GENERICO[mes - 1] : new Date(anio, mes, 0).getDate();
}

// Un día FUTURO (respecto de hoy) tampoco "existe" todavía — mismo criterio
// que un día que no existe en el mes: sin esto, diciembre de un año en
// curso se veía igual de gris que un diciembre que YA pasó con cero
// actividad (bug real, dueño 2026-08-17). Solo aplica en modo año — en
// "todos" un día del año (ej. 15 de diciembre) ya ocurrió en años pasados
// aunque el año actual todavía no llegue ahí, así que sí cuenta.
function esFuturo(modo: "anio" | "todos", anio: number, mes: number, dia: number, hoy: Date) {
  if (modo === "todos") return false;
  const hoySinHora = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate());
  return new Date(anio, mes - 1, dia).getTime() > hoySinHora.getTime();
}

function fmtDiaLargo(anio: number, mes: number, dia: number): string {
  return new Date(anio, mes - 1, dia).toLocaleDateString("es-AR", {
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
    const m = new Map<string, CeldaInfo>();
    for (const d of data?.dias ?? []) {
      m.set(d.dia, { pedidosActivos: d.pedidos_activos, tier: d.tier });
    }
    return m;
  }, [data]);

  const anios = data?.anios_disponibles ?? [];
  const anioActual = new Date().getFullYear();
  const anioParaClave = data?.anio ?? anioSeleccionado ?? anioActual;
  const hoy = new Date();

  return (
    <div>
      <div className="flex items-center justify-between gap-2 mb-3">
        <p className="text-sm text-muted-foreground">
          Días con equipo afuera — un pedido enciende todos sus días, no solo el retiro.
          {modo === "todos" && " Cada celda suma todos los años juntos para ese día del año."}
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
        <div className="h-[400px] animate-pulse rounded-lg bg-muted" />
      ) : (
        <div className="overflow-x-auto">
          <div className="grid gap-1" style={{ gridTemplateColumns: GRID_COLS }}>
            <div />
            {DIAS_DEL_MES.map((dia) => (
              <div key={`h-${dia}`} className="text-center text-2xs text-muted-foreground">
                {dia}
              </div>
            ))}
            {MESES_ABREV.map((mesLabel, mesIdx) => {
              const mes = mesIdx + 1;
              return (
                <Fragment key={mes}>
                  <div className="flex items-center justify-end pr-1 text-2xs text-muted-foreground">
                    {mesLabel}
                  </div>
                  {DIAS_DEL_MES.map((dia) => {
                    if (
                      dia > diasEnMes(modo, anioParaClave, mes) ||
                      esFuturo(modo, anioParaClave, mes, dia, hoy)
                    ) {
                      // No existe (ej. 31 de abril) o todavía no pasó — celda vacía, ni gris.
                      return <div key={dia} className="aspect-square" />;
                    }
                    const clave = claveCelda(modo, anioParaClave, mes, dia);
                    const info = porDia.get(clave) ?? { pedidosActivos: 0, tier: 0 };
                    const titulo =
                      modo === "todos"
                        ? `${dia} de ${MESES_LARGO[mesIdx]} (todos los años): ${info.pedidosActivos} pedido${info.pedidosActivos === 1 ? "" : "s"} con equipo afuera en total`
                        : `${fmtDiaLargo(anioParaClave, mes, dia)}: ${info.pedidosActivos} pedido${info.pedidosActivos === 1 ? "" : "s"} con equipo afuera`;
                    return (
                      <div
                        key={dia}
                        title={titulo}
                        className={cn("aspect-square rounded-[3px]", TIER_BG[info.tier])}
                      />
                    );
                  })}
                </Fragment>
              );
            })}
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
