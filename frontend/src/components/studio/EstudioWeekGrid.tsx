/**
 * Grilla semanal de disponibilidad de El Estudio — reemplaza el modelo
 * "elegís a ciegas y recién después te digo si se puede" por "ves de
 * entrada qué hay libre". Consume `GET /api/estudio/ocupacion-publica`
 * (vista pública y anónima — nunca cliente/nombre/número de pedido) para
 * pintar 7 días × las franjas de 30 min del horario del estudio.
 *
 * Es un ATAJO VISUAL, nunca el gate: `StudioBookingForm` sigue validando la
 * franja elegida con `apiGetEstudioDisponibilidad` antes de habilitar
 * "Reservar" — esta grilla solo ayuda a elegir sobre datos frescos (30s de
 * staleTime), no reemplaza esa verificación final.
 *
 * Variante desktop (`sm:` en adelante): grid real de 7 columnas × N filas.
 * La variante mobile (un día a la vez + lista vertical) vive en el mismo
 * componente, debajo — `docs/MOBILE_AUDIT.md` exige las dos, no un grid que
 * "colapsa solo" (7 columnas angostas en 375px son ilegibles/imposibles de
 * tocar con el dedo).
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { addDays, format } from "date-fns";
import { es } from "date-fns/locale";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiGetEstudioOcupacionPublica } from "@/lib/api";
import { pad } from "@/lib/estudio-slots";

type Seleccion = { date: Date; startSlot: string };

type EstudioWeekGridProps = {
  openHour: number;
  closeHour: number;
  /** Duración actual elegida (horas) — solo para el highlight de hover, no
   *  filtra ni bloquea ninguna celda (ver docstring del módulo). */
  hours: number;
  selected: Seleccion | null;
  onSelectSlot: (date: Date, startSlot: string) => void;
  className?: string;
};

function ymd(d: Date): string {
  return format(d, "yyyy-MM-dd");
}

/** Todas las medias horas de [openHour, closeHour) — a diferencia de
 *  `buildTimeSlots` (estudio-slots.ts), acá NO se recorta por duración: la
 *  grilla muestra el horario completo del estudio, el stepper de duración
 *  sigue siendo quien decide cuánto dura la reserva. */
function slotsDelDia(openHour: number, closeHour: number): string[] {
  const out: string[] = [];
  for (let h = openHour; h < closeHour; h++) {
    out.push(`${pad(h)}:00`, `${pad(h)}:30`);
  }
  return out;
}

function slotToMinutes(slot: string): number {
  const [h, m] = slot.split(":").map(Number);
  return h * 60 + m;
}

const DIAS_CORTOS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"];

export function EstudioWeekGrid({
  openHour,
  closeHour,
  hours,
  selected,
  onSelectSlot,
  className,
}: EstudioWeekGridProps) {
  const today = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d;
  }, []);
  // Ventana ROLLING de 7 días desde hoy — no la semana calendario (Lun-Dom).
  // Con semana calendario, un domingo mostraba Lun-Sáb ya pasados (grises) y
  // solo hoy útil: casi toda la grilla se veía vacía/gris sin sentido.
  const [weekStart, setWeekStart] = useState(today);
  const [mobileDayIdx, setMobileDayIdx] = useState(0);
  const [hoverCell, setHoverCell] = useState<{ dayIdx: number; slot: string } | null>(null);

  const dias = useMemo(
    () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  );
  const desde = ymd(weekStart);
  const hasta = ymd(dias[6]);

  const ocupacionQ = useQuery({
    queryKey: ["estudio-ocupacion-publica", desde, hasta],
    queryFn: () => apiGetEstudioOcupacionPublica(desde, hasta),
    staleTime: 30_000,
  });

  const bloques = useMemo(
    () =>
      (ocupacionQ.data?.bloques ?? []).map((b) => ({
        desde: new Date(b.fecha_desde),
        hasta: new Date(b.fecha_hasta),
      })),
    [ocupacionQ.data],
  );

  const slots = useMemo(() => slotsDelDia(openHour, closeHour), [openHour, closeHour]);
  const ahora = useMemo(() => new Date(), []);

  const estaOcupado = (day: Date, slot: string): boolean => {
    const [h, m] = slot.split(":").map(Number);
    const inicio = new Date(day);
    inicio.setHours(h, m, 0, 0);
    const fin = new Date(inicio.getTime() + 30 * 60_000);
    return bloques.some((b) => inicio < b.hasta && fin > b.desde);
  };

  const yaPaso = (day: Date, slot: string): boolean => {
    const [h, m] = slot.split(":").map(Number);
    const inicio = new Date(day);
    inicio.setHours(h, m, 0, 0);
    return inicio < ahora;
  };

  const cantidadFranjas = Math.max(1, Math.ceil(hours * 2));

  const enHighlight = (dayIdx: number, slot: string): boolean => {
    if (!hoverCell || hoverCell.dayIdx !== dayIdx) return false;
    const base = slotToMinutes(hoverCell.slot);
    const actual = slotToMinutes(slot);
    return actual >= base && actual < base + cantidadFranjas * 30;
  };

  // Igual que `enHighlight`, pero contra la SELECCIÓN actual (no el hover) —
  // sin esto, la duración solo se veía marcada mientras el mouse seguía
  // encima; al alejar el mouse (o en touch, que no tiene hover) la franja de
  // más de un bloque quedaba sin ninguna marca más allá de la celda inicial.
  const enSeleccionActual = (dayIdx: number, slot: string): boolean => {
    if (!selected || ymd(selected.date) !== ymd(dias[dayIdx])) return false;
    const base = slotToMinutes(selected.startSlot);
    const actual = slotToMinutes(slot);
    return actual >= base && actual < base + cantidadFranjas * 30;
  };

  const estaSeleccionado = (day: Date, slot: string): boolean =>
    !!selected && ymd(selected.date) === ymd(day) && selected.startSlot === slot;

  const puedeIrAtras = weekStart.getTime() > today.getTime();

  const cabeceraSemana = `${format(weekStart, "d MMM", { locale: es })} – ${format(dias[6], "d MMM", { locale: es })}`;

  const Celda = ({ day, dayIdx, slot }: { day: Date; dayIdx: number; slot: string }) => {
    const ocupado = estaOcupado(day, slot);
    const pasado = yaPaso(day, slot);
    const disabled = ocupado || pasado;
    const seleccionado = estaSeleccionado(day, slot);
    const highlight = !disabled && (enHighlight(dayIdx, slot) || enSeleccionActual(dayIdx, slot));
    const horaEnPunto = slot.endsWith(":00");

    return (
      <button
        type="button"
        disabled={disabled}
        data-day-idx={dayIdx}
        data-slot={slot}
        aria-label={`${format(day, "EEEE d", { locale: es })} ${slot}${ocupado ? " — ocupado" : ""}`}
        aria-pressed={seleccionado}
        onClick={() => !disabled && onSelectSlot(day, slot)}
        className={cn(
          "h-4 w-full rounded-[2px] border transition-colors",
          // Línea de hora — ancla visual para no perderse escaneando el scroll.
          horaEnPunto ? "border-t-ink/10" : "border-t-transparent",
          disabled && "cursor-not-allowed border-x-transparent border-b-transparent bg-muted/60",
          !disabled &&
            !seleccionado &&
            "cursor-pointer border-x-verde/25 border-b-verde/25 bg-verde/10 hover:border-[var(--area-accent)]",
          highlight && !seleccionado && "border-[var(--area-accent)] bg-[var(--area-accent-soft)]",
          seleccionado && "border-[var(--area-accent)] bg-[var(--area-accent)]",
        )}
      />
    );
  };

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => setWeekStart((w) => addDays(w, -7))}
          disabled={!puedeIrAtras}
          aria-label="Semana anterior"
          className="hit-area-44 grid place-items-center rounded-md text-muted-foreground hover:bg-ink/5 hover:text-ink disabled:opacity-30"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="t-eyebrow tabular">{cabeceraSemana}</span>
        <button
          type="button"
          onClick={() => setWeekStart((w) => addDays(w, 7))}
          aria-label="Semana siguiente"
          className="hit-area-44 grid place-items-center rounded-md text-muted-foreground hover:bg-ink/5 hover:text-ink"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      {/* ── Desktop/tablet (≥640px): grid 7 columnas × N filas ────────── */}
      {/* Sin scroll interno a propósito (pedido del dueño) — el día completo
          se ve entero, la página scrollea como un todo en vez de un scroll
          anidado adentro de otro. */}
      <div className="hidden overflow-hidden rounded-xl border hairline sm:block">
        <div
          className="grid bg-surface border-b hairline text-2xs text-muted-foreground"
          style={{ gridTemplateColumns: "2.75rem repeat(7, 1fr)" }}
        >
          <div />
          {dias.map((d) => (
            <div key={ymd(d)} className="px-1 py-1 text-center">
              <div className="capitalize">{DIAS_CORTOS[d.getDay() === 0 ? 6 : d.getDay() - 1]}</div>
              <div className="tabular font-medium text-ink">{format(d, "d")}</div>
            </div>
          ))}
        </div>
        <div
          className="grid gap-y-px p-1"
          style={{ gridTemplateColumns: "2.75rem repeat(7, 1fr)" }}
          // Hover DELEGADO al contenedor (en vez de onMouseEnter/onMouseLeave
          // por celda): con ~decenas de <button> chicos, un mouse rápido podía
          // saltarse el mouseleave de la última celda hovereada — quedaba un
          // preview de duración pegado aunque el mouse ya estuviera afuera de
          // la grilla. Una sola fuente de verdad por movimiento elimina la raza.
          onMouseOver={(e) => {
            const btn = (e.target as HTMLElement).closest("button[data-slot]");
            if (!(btn instanceof HTMLButtonElement) || btn.disabled) {
              setHoverCell(null);
              return;
            }
            setHoverCell({ dayIdx: Number(btn.dataset.dayIdx), slot: btn.dataset.slot! });
          }}
          onMouseLeave={() => setHoverCell(null)}
        >
          {slots.map((slot) => (
            <div key={slot} className="contents">
              <div
                className={cn(
                  "tabular pr-1.5 text-right leading-4 text-muted-foreground",
                  slot.endsWith(":00") ? "text-3xs font-medium text-ink/70" : "text-3xs opacity-0",
                )}
              >
                {slot.endsWith(":00") ? slot : "·"}
              </div>
              {dias.map((d, dayIdx) => (
                <div key={`${ymd(d)}-${slot}`} className="px-0.5">
                  <Celda day={d} dayIdx={dayIdx} slot={slot} />
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* ── Mobile (<640px): un día a la vez — carrusel de día + lista ──
          vertical de franjas. 7 columnas angostas son ilegibles/imposibles
          de tocar en 375px; acá la densidad se reparte en un eje por vez:
          horizontal para elegir día, vertical para elegir hora. */}
      <div className="sm:hidden">
        <div className="flex snap-x snap-mandatory gap-1.5 overflow-x-auto pb-1">
          {dias.map((d, dayIdx) => {
            const activo = dayIdx === mobileDayIdx;
            return (
              <button
                key={ymd(d)}
                type="button"
                onClick={() => setMobileDayIdx(dayIdx)}
                aria-pressed={activo}
                className={cn(
                  "hit-area-44 flex shrink-0 snap-start flex-col items-center justify-center rounded-lg border px-3",
                  activo
                    ? "border-[var(--area-accent)] bg-[var(--area-accent-soft)]"
                    : "hairline bg-surface text-muted-foreground",
                )}
              >
                <span className="text-2xs capitalize">
                  {DIAS_CORTOS[d.getDay() === 0 ? 6 : d.getDay() - 1]}
                </span>
                <span className={cn("tabular text-sm font-medium", activo && "text-ink")}>
                  {format(d, "d")}
                </span>
              </button>
            );
          })}
        </div>

        <div className="mt-2 space-y-1 rounded-xl border hairline p-1.5">
          {slots.map((slot) => {
            const day = dias[mobileDayIdx];
            const ocupado = estaOcupado(day, slot);
            const pasado = yaPaso(day, slot);
            const disabled = ocupado || pasado;
            const seleccionado = estaSeleccionado(day, slot);
            return (
              <button
                key={slot}
                type="button"
                disabled={disabled}
                onClick={() => !disabled && onSelectSlot(day, slot)}
                aria-pressed={seleccionado}
                className={cn(
                  "min-h-11 flex w-full items-center justify-between rounded-md border border-transparent px-3 text-sm",
                  disabled && "cursor-not-allowed text-muted-foreground/50",
                  !disabled && !seleccionado && "bg-verde/10 text-ink",
                  seleccionado && "bg-[var(--area-accent)] text-ink",
                )}
              >
                <span className="tabular">{slot}</span>
                {disabled && !pasado && <span className="text-2xs">Ocupado</span>}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
