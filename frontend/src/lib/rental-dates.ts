/**
 * Fuente de verdad ÚNICA del cálculo de fechas/jornadas del alquiler.
 *
 * MODELO 24h (decisión de producto): 1 jornada = un período de 24 h desde el
 * retiro. Devolver más tarde que la hora de retiro suma una jornada. Es el
 * mismo criterio que el backend (`ceil((hasta − desde) / 24h)` en
 * `routes/alquileres.py`). Cualquier UI que muestre jornadas debe usar estos
 * helpers para no divergir de lo que factura el backend.
 */
import { addDays, startOfDay } from "date-fns";

export const RENTAL_DAY_MS = 86_400_000;

/** Minutos desde medianoche para un string "HH:MM". */
export function timeToMinutes(time: string): number {
  const [h = 0, m = 0] = (time ?? "00:00").split(":").map(Number);
  return h * 60 + m;
}

/**
 * Fecha local → "YYYY-MM-DD" (sin corrimiento por timezone, a diferencia de
 * `toISOString()` que pasa a UTC). Formato que esperan los endpoints de
 * disponibilidad/días bloqueados.
 */
export const ymd = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Zona horaria del negocio. Espejo de `now_ar()` del backend
 *  (`backend/services/fechas.py`): Rambla razona SIEMPRE en hora de Argentina,
 *  no en la del dispositivo ni en UTC. */
export const TZ_AR = "America/Argentina/Buenos_Aires";

const _fmtHoyAR = new Intl.DateTimeFormat("en-CA", {
  timeZone: TZ_AR,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/**
 * HOY en Argentina, "YYYY-MM-DD" — la fecha que el dueño ve en su reloj.
 *
 * **Fuente única del "hoy" del front.** Antes cada pantalla hacía
 * `new Date().toISOString().slice(0, 10)`, que devuelve la fecha **UTC**: de
 * las 21:00 en adelante (hora argentina) ya proponía la de MAÑANA. Bug real
 * 2026-08-02: un pago registrado a las 21:54 quedó fechado el 3 de agosto, y
 * en el borde de mes se iba al mes siguiente (mueve la plata de reporte).
 *
 * Pinnea Argentina en vez de usar la hora local del dispositivo: el negocio
 * factura en hora argentina aunque el que cargue esté de viaje o tenga el
 * reloj mal configurado — mismo criterio que `now_ar()` en el backend.
 */
export const hoyAR = () => _fmtHoyAR.format(new Date());

/**
 * Fecha local + "HH:MM" → string ISO-local `YYYY-MM-DDTHH:MM:00` (sin pasar a
 * UTC). Es el formato que esperan los endpoints de pedidos/cotización para
 * `fecha_desde`/`fecha_hasta`. Fuente única para no divergir entre el submit
 * del pedido y la cotización del carrito.
 */
export const toLocalISO = (date: Date, time: string) => `${ymd(date)}T${time}:00`;

/** Combina una fecha (se ignora su hora) con "HH:MM" en un Date local. */
export function combineDateTime(date: Date, time: string): Date {
  const d = startOfDay(date);
  d.setMinutes(timeToMinutes(time));
  return d;
}

/**
 * Jornadas entre dos instantes — espejo exacto del backend
 * `ceil((hasta − desde) / 24h)`, mínimo 1.
 */
export function jornadasBetween(start: Date, end: Date): number {
  const ms = end.getTime() - start.getTime();
  if (!Number.isFinite(ms) || ms <= 0) return 1;
  return Math.max(1, Math.ceil(ms / RENTAL_DAY_MS));
}

/** Jornadas a partir de fecha + hora de retiro y devolución. */
export function computeJornadas(
  startDate: Date | undefined,
  endDate: Date | undefined,
  startTime: string,
  endTime: string,
): number {
  if (!startDate || !endDate) return 1;
  return jornadasBetween(combineDateTime(startDate, startTime), combineDateTime(endDate, endTime));
}

/** Parsea un string ISO (date-only o datetime) a Date local estable. */
export function parseRentalDate(s: string): Date {
  return s.includes("T") ? new Date(s) : new Date(s + "T12:00:00");
}

/**
 * Parsea `fecha_desde`/`fecha_hasta` (datetime ISO `YYYY-MM-DDTHH:MM...` o
 * date-only `YYYY-MM-DD`) en `{ date, time }`: el día como Date local a
 * medianoche y la hora como "HH:MM". Si el string no trae hora, usa
 * `fallbackTime`. Inverso de `toLocalISO`. Devuelve `date: undefined` si el
 * string está vacío o es inválido (rango sin fechas).
 *
 * Fuente única para el editor admin de pedidos, que guarda con hora y debe
 * recombinar día+hora a datetime con `toLocalISO`.
 */
export function parseDateTimeParts(
  s: string | null | undefined,
  fallbackTime = "09:00",
): { date: Date | undefined; time: string } {
  if (!s) return { date: undefined, time: fallbackTime };
  const [datePart, timePartRaw] = s.split("T");
  const [y, mo, d] = datePart.split("-").map(Number);
  if (!y || !mo || !d) return { date: undefined, time: fallbackTime };
  const date = new Date(y, mo - 1, d); // local, medianoche
  if (Number.isNaN(date.getTime())) return { date: undefined, time: fallbackTime };
  const time = timePartRaw ? timePartRaw.slice(0, 5) : fallbackTime;
  return { date, time };
}

/** Jornadas entre dos strings ISO (date-only o datetime completo). */
export function jornadasFromISO(desde?: string, hasta?: string): number {
  if (!desde || !hasta) return 1;
  const a = parseRentalDate(desde);
  const b = parseRentalDate(hasta);
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return 1;
  return jornadasBetween(a, b);
}

/**
 * Fecha de devolución (solo día) para alcanzar `jornadas` exactas dados los
 * horarios. Inverso de computeJornadas, para el stepper de jornadas:
 *   jornadas = dayDiff + (endTime > startTime ? 1 : 0)
 *   ⇒ dayDiff = jornadas − (endsLater ? 1 : 0)
 */
export function deriveEndDate(
  startDate: Date,
  jornadas: number,
  startTime: string,
  endTime: string,
): Date {
  const endsLater = timeToMinutes(endTime) > timeToMinutes(startTime);
  const dayDiff = Math.max(0, Math.max(1, jornadas) - (endsLater ? 1 : 0));
  return addDays(startOfDay(startDate), dayDiff);
}

// ── Horarios habilitados (retiro/devolución) ────────────────────────────────
// Config settable en el back-office: una franja apertura–cierre por día de
// semana, misma para retiro y devolución. Se guarda como JSON en el setting
// `horarios_retiro`, keyed por día (3 letras, índice = Date.getDay()).

export type FranjaHoraria = { desde: string; hasta: string };
/** Mapa día→franja. `null` en un día = cerrado. */
export type HorariosSemana = Record<string, FranjaHoraria | null>;

/** Índice por Date.getDay(): 0=domingo … 6=sábado. */
export const DIAS_KEY = ["dom", "lun", "mar", "mie", "jue", "vie", "sab"] as const;
export const DIAS_LABEL: Record<string, string> = {
  lun: "Lunes",
  mar: "Martes",
  mie: "Miércoles",
  jue: "Jueves",
  vie: "Viernes",
  sab: "Sábado",
  dom: "Domingo",
};

export function diaKey(date: Date): string {
  return DIAS_KEY[date.getDay()];
}

/** Parsea el JSON del setting. Devuelve null = sin restricción (todo abierto). */
export function parseHorarios(raw?: string | null): HorariosSemana | null {
  if (!raw) return null;
  try {
    const o = JSON.parse(raw);
    return o && typeof o === "object" ? (o as HorariosSemana) : null;
  } catch {
    return null;
  }
}

/** Franja del día de esa fecha. null = cerrado o sin restricción (ver diaAbierto). */
export function franjaParaFecha(
  horarios: HorariosSemana | null,
  date: Date | null | undefined,
): FranjaHoraria | null {
  if (!horarios || !date) return null;
  return horarios[diaKey(date)] ?? null;
}

/** ¿El día está habilitado? Sin config global → siempre abierto. */
export function diaAbierto(
  horarios: HorariosSemana | null,
  date: Date | null | undefined,
): boolean {
  if (!horarios || !date || Object.keys(horarios).length === 0) return true;
  return !!horarios[diaKey(date)];
}

/** Slots de 30 min dentro de [desde, hasta] inclusive. */
export function slotsEntre(desde: string, hasta: string): string[] {
  const out: string[] = [];
  const start = timeToMinutes(desde);
  const end = timeToMinutes(hasta);
  for (let t = start; t <= end; t += 30) {
    out.push(`${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`);
  }
  return out;
}

// ── Piso de retiro: "ahora" + antelación mínima (#1126) ─────────────────────
// El backend es la fuente de verdad (portero + backstop de creación en
// `services/fechas.py`); estos helpers reproducen el mismo piso en el picker
// para que no se puedan ELEGIR fechas/horas que el backend igual rechazaría.

/**
 * Instante más temprano de retiro permitido: `now` + `leadTimeHoras` (setting
 * `antelacion_minima_horas`). `leadTimeHoras=0` → simplemente "ahora" (no se
 * puede elegir un horario ya pasado). Redondea hacia el próximo slot de 30 min
 * (los únicos que ofrece `TimeStepSelect`) para no mostrar una hora que ya
 * venció apenas se calcula.
 */
export function earliestRetiro(now: Date, leadTimeHoras: number): Date {
  const withLead = new Date(now.getTime() + Math.max(0, leadTimeHoras) * 3_600_000);
  withLead.setSeconds(0, 0);
  const resto = withLead.getMinutes() % 30;
  if (resto !== 0) withLead.setMinutes(withLead.getMinutes() + (30 - resto));
  return withLead;
}

/**
 * Hora mínima seleccionable ("HH:MM") para `date`, dado el piso `earliest`
 * (ver `earliestRetiro`). `undefined` si falta `date` o `earliest` (piso aún
 * desconocido — no clampear en base a un dato incompleto), o si `date` es un
 * día posterior al de `earliest` (ese día no tiene piso).
 */
export function minTimeForDate(
  date: Date | undefined,
  earliest: Date | undefined,
): string | undefined {
  if (!date || !earliest) return undefined;
  if (startOfDay(date).getTime() !== startOfDay(earliest).getTime()) return undefined;
  return `${String(earliest.getHours()).padStart(2, "0")}:${String(earliest.getMinutes()).padStart(2, "0")}`;
}

/** La más tardía de dos horas "HH:MM" — combina dos pisos independientes
 *  (horarios habilitados + antelación mínima) sin que uno pise al otro.
 *  `undefined` si ninguno de los dos aplica. */
export function laterTime(a?: string, b?: string): string | undefined {
  if (!a) return b;
  if (!b) return a;
  return timeToMinutes(a) >= timeToMinutes(b) ? a : b;
}
