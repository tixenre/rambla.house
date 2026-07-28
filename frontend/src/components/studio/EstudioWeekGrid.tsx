/**
 * Grilla semanal de disponibilidad de El Estudio — reemplaza el modelo
 * "elegís a ciegas y recién después te digo si se puede" por "ves de
 * entrada qué hay libre". Consume `GET /api/estudio/ocupacion-publica`
 * (vista pública y anónima — nunca cliente/nombre/número de pedido) para
 * pintar 7 días × las franjas de 30 min del horario del estudio — cada hora
 * son 2 filas ANGOSTAS pegadas (`:00`/`:30`), no una fila por hora: eso
 * lo probamos (menos filas, más altas) y perdía la precisión de media hora
 * al clickear; acá se recupera esa precisión sin volver a la altura total
 * de antes (ver `slotsDelDia`).
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
  /** Mínimo de horas que exige el estudio (`estudio.min_horas`) — a
   *  diferencia de `hours`, ESTO SÍ deshabilita celdas: un inicio que no
   *  deja lugar para el mínimo antes de `closeHour` no es una franja
   *  reservable de verdad, aunque esté libre (ver bug de abajo). */
  minHours: number;
  /** Duración actual elegida (horas) — solo para el highlight de hover, no
   *  filtra ni bloquea ninguna celda (ver docstring del módulo). */
  hours: number;
  /** Horas de anticipación EFECTIVAS que hay que respetar ahora mismo — el
   *  caller ya resolvió cuál aplica (la general, o el máximo contra la del
   *  add-on "recién pintado" si está tildado); acá solo se usa para grisar.
   *  0 = sin restricción extra (además del chequeo de "ya pasó"). */
  anticipacionHoras: number;
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
 *  sigue siendo quien decide cuánto dura la reserva. Filas ANGOSTAS (ver
 *  `Celda`, h-3) + el divisor de hora solo en `:00` para que las dos mitades
 *  de una hora se lean pegadas — la altura total queda cerca de la versión
 *  "solo horas" que probamos, pero sin perder el clic directo a media hora. */
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

type CeldaProps = {
  day: Date;
  dayIdx: number;
  slot: string;
  disabled: boolean;
  ocupado: boolean;
  sinTiempo: boolean;
  antelacionInsuficiente: boolean;
  seleccionado: boolean;
  highlight: boolean;
  onSelectSlot: (date: Date, startSlot: string) => void;
};

/** Hoisteado a nivel de módulo a propósito — declararlo DENTRO de
 *  `EstudioWeekGrid` (como estaba) hace que React vea un componente "nuevo"
 *  en cada render del padre (nueva identidad de función), así que cualquier
 *  cambio de estado durante un hover — incluido el hover delegado del
 *  contenedor — remontaba TODOS los botones. Si el remount caía entre el
 *  mousedown y el mouseup de un click real, el navegador perdía el click
 *  (reproducido con un mouse.move+down+up realista, no con `.click()` que
 *  lo teletransporta). Acá recibe todo por props: misma identidad de
 *  función siempre, un re-render solo actualiza props sobre el MISMO nodo. */
function Celda({
  day,
  dayIdx,
  slot,
  disabled,
  ocupado,
  sinTiempo,
  antelacionInsuficiente,
  seleccionado,
  highlight,
  onSelectSlot,
}: CeldaProps) {
  const motivo = ocupado
    ? " — ocupado"
    : sinTiempo
      ? " — no alcanza para la duración mínima"
      : antelacionInsuficiente
        ? " — necesita más anticipación"
        : "";
  const horaEnPunto = slot.endsWith(":00");

  return (
    <button
      type="button"
      disabled={disabled}
      data-day-idx={dayIdx}
      data-slot={slot}
      aria-label={`${format(day, "EEEE d", { locale: es })} ${slot}${motivo}`}
      aria-pressed={seleccionado}
      onClick={() => !disabled && onSelectSlot(day, slot)}
      className={cn(
        "h-3 w-full rounded-[2px] border transition-colors",
        // Línea de hora — separa un grupo de hora del siguiente; entre :00 y
        // :30 de la MISMA hora no hay línea, para que se lean pegados.
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
}

export function EstudioWeekGrid({
  openHour,
  closeHour,
  minHours,
  hours,
  anticipacionHoras,
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
  // Barra mínima de inicio: "ahora" + la anticipación efectiva (0 = sin
  // restricción extra, la barra queda en "ahora" — mismo comportamiento que
  // antes de que existiera este prop). Generaliza el viejo `yaPaso` (que era
  // el caso particular anticipacionHoras=0): un inicio futuro pero DEMASIADO
  // pronto es tan no-reservable como uno ya pasado — mismo motivo de gris,
  // solo cambia el label del porqué (ver `Celda`).
  const minInicio = useMemo(
    () => new Date(ahora.getTime() + Math.max(0, anticipacionHoras) * 60 * 60_000),
    [ahora, anticipacionHoras],
  );

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

  // Futuro, pero no deja la anticipación exigida — distinto de `yaPaso`
  // (ya en el pasado) para poder mostrar un motivo de a11y más preciso.
  const antelacionInsuficiente = (day: Date, slot: string): boolean => {
    const [h, m] = slot.split(":").map(Number);
    const inicio = new Date(day);
    inicio.setHours(h, m, 0, 0);
    return inicio >= ahora && inicio < minInicio;
  };

  // Un inicio que no deja lugar para `minHours` antes de `closeHour` no es
  // una franja reservable — mismo criterio que `buildTimeSlots` (el <select>
  // de Hora ya los excluye). Sin este chequeo, la grilla dejaba clickear un
  // horario tarde-en-el-día (libre, no pasado) que igual era inválido: el
  // `useEffect` de `StudioBookingForm` que corrige un `startSlot` inválido
  // lo revertía al toque a `slots[0]` — la selección "no se quedaba
  // seleccionada" (bug real reportado en vivo).
  const noAlcanzaDuracionMinima = (slot: string): boolean =>
    slotToMinutes(slot) + minHours * 60 > closeHour * 60;

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
          // `gridAutoRows` explícito (no dejar que el browser infiera del
          // contenido): con los `<div className="contents">` que agrupan
          // label+celdas de una fila, Chrome calculaba el alto de cada
          // track de grid MAL — 24px en vez de los 12px reales de cada
          // celda (`h-3`), confirmado con align-self:start (que debería
          // mostrar el alto natural) y seguía en 24px. Fijar el track a
          // mano es más robusto que perseguir el bug de auto-sizing.
          style={{ gridTemplateColumns: "2.75rem repeat(7, 1fr)", gridAutoRows: "0.75rem" }}
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
                  // text-3xs/3 (no `leading-3` aparte): `cn()` usa tailwind-merge
                  // con text-3xs registrado en el grupo "font-size" (utils.ts) —
                  // por las reglas default de esa librería, cualquier `leading-*`
                  // agregado aparte SIEMPRE se descarta al mergear con un
                  // integrante de ese grupo (confirmado con un test aislado de
                  // twMerge). El shorthand `size/leading` es UN solo token —
                  // sobrevive el merge porque no hay nada que pueda pisarlo.
                  "tabular pr-1.5 text-right text-3xs/3 text-muted-foreground",
                  slot.endsWith(":00") ? "font-medium text-ink/70" : "opacity-0",
                )}
              >
                {slot.endsWith(":00") ? slot : "·"}
              </div>
              {dias.map((d, dayIdx) => {
                const ocupado = estaOcupado(d, slot);
                const pasado = yaPaso(d, slot);
                const sinTiempo = noAlcanzaDuracionMinima(slot);
                const antelacion = !pasado && antelacionInsuficiente(d, slot);
                const disabled = ocupado || pasado || sinTiempo || antelacion;
                const seleccionado = estaSeleccionado(d, slot);
                const highlight =
                  !disabled && (enHighlight(dayIdx, slot) || enSeleccionActual(dayIdx, slot));
                return (
                  <div key={`${ymd(d)}-${slot}`} className="px-0.5">
                    <Celda
                      day={d}
                      dayIdx={dayIdx}
                      slot={slot}
                      disabled={disabled}
                      ocupado={ocupado}
                      sinTiempo={sinTiempo}
                      antelacionInsuficiente={antelacion}
                      seleccionado={seleccionado}
                      highlight={highlight}
                      onSelectSlot={onSelectSlot}
                    />
                  </div>
                );
              })}
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
            const sinTiempo = noAlcanzaDuracionMinima(slot);
            const antelacion = !pasado && antelacionInsuficiente(day, slot);
            const disabled = ocupado || pasado || sinTiempo || antelacion;
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
                {ocupado && <span className="text-2xs">Ocupado</span>}
                {!ocupado && antelacion && <span className="text-2xs">Muy pronto</span>}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
