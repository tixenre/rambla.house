import { useState } from "react";
import { Clock } from "lucide-react";
import { es } from "date-fns/locale";
import { Calendar, CalendarDayButton } from "@/design-system/ui/calendar";
import { fmtHhmm } from "@/lib/talleres/formato";

// Minutos desde medianoche (Escuela v2 F1). `_str` viene resuelto del backend
// en datos guardados; el fallback fmtHhmm cubre estado local del admin (preview
// del asistente antes de guardar).
export type Sesion = {
  fecha: string;
  hora_inicio_min: number;
  hora_fin_min: number;
  hora_inicio_str?: string;
  hora_fin_str?: string;
};

interface TallerCalendarioProps {
  sesiones: Sesion[];
  horario?: string;
}

function fmtHora(s: Sesion, cual: "inicio" | "fin"): string {
  if (cual === "inicio") return s.hora_inicio_str ?? fmtHhmm(s.hora_inicio_min);
  return s.hora_fin_str ?? fmtHhmm(s.hora_fin_min);
}

function pluralWeekday(d: Date): string {
  const label = d.toLocaleDateString("es-AR", { weekday: "long" });
  return label.endsWith("s") ? label : `${label}s`;
}

type Grupo = {
  fechaDesde: string;
  fechaHasta: string;
  count: number;
  horaInicio: string;
  horaFin: string;
};

/** Agrupa sesiones CONSECUTIVAS (ya ordenadas por fecha) del mismo día de la
 * semana + horario en un solo rango — "13 clases sueltas" pasa a "6 sábados
 * 8:30-12:30 · 1 miércoles ...". Un patrón que se corta (día/horario distinto)
 * arranca grupo nuevo, aunque el mismo patrón reaparezca más adelante — así el
 * orden cronológico de la lista no se pierde. */
function agruparPorPatron(sorted: Sesion[]): Grupo[] {
  const grupos: Grupo[] = [];
  for (const s of sorted) {
    const horaInicio = fmtHora(s, "inicio");
    const horaFin = fmtHora(s, "fin");
    const weekday = new Date(s.fecha + "T12:00:00").getDay();
    const last = grupos[grupos.length - 1];
    const lastWeekday = last ? new Date(last.fechaHasta + "T12:00:00").getDay() : null;
    if (
      last &&
      lastWeekday === weekday &&
      last.horaInicio === horaInicio &&
      last.horaFin === horaFin
    ) {
      last.fechaHasta = s.fecha;
      last.count += 1;
    } else {
      grupos.push({ fechaDesde: s.fecha, fechaHasta: s.fecha, count: 1, horaInicio, horaFin });
    }
  }
  return grupos;
}

function GrupoPill({ grupo }: { grupo: Grupo }) {
  const dDesde = new Date(grupo.fechaDesde + "T12:00:00");
  const dHasta = new Date(grupo.fechaHasta + "T12:00:00");
  const optsLargo: Intl.DateTimeFormatOptions = { day: "numeric", month: "long" };
  const optsCorto: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" };

  const titulo =
    grupo.count === 1
      ? (() => {
          const s = dDesde.toLocaleDateString("es-AR", { weekday: "long", ...optsLargo });
          return s.charAt(0).toUpperCase() + s.slice(1);
        })()
      : `${grupo.count} ${pluralWeekday(dDesde)}`;

  const rango =
    grupo.count > 1
      ? `${dDesde.toLocaleDateString("es-AR", optsCorto)} – ${dHasta.toLocaleDateString("es-AR", optsCorto)}`
      : null;

  // Sin card propia (border/bg): el chip vive DENTRO de la card única del
  // calendario — antes cada grupo era una card aparte (rounded-xl bg-muted
  // border), así que el bloque completo se leía como dos diseños pegados en
  // vez de uno (pedido explícito: "unir el calendario y esto en un mismo
  // diseño"). El divide-y del padre dibuja el separador entre grupos.
  return (
    <div className="flex items-center gap-3 py-3">
      <div className="w-1 self-stretch rounded-full bg-rosa flex-none" />
      <div className="flex flex-col gap-1 min-w-0">
        <span className="font-semibold text-ink text-base sm:text-lg">
          {titulo}
          {rango && <span className="font-normal text-muted-foreground"> · {rango}</span>}
        </span>
        <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Clock className="h-3.5 w-3.5 text-rosa flex-none" />
          {grupo.horaInicio} — {grupo.horaFin} hs
        </span>
      </div>
    </div>
  );
}

export function TallerCalendario({ sesiones, horario }: TallerCalendarioProps) {
  const sorted = [...(sesiones ?? [])].sort((a, b) => a.fecha.localeCompare(b.fecha));
  const sesionDates = sorted.map((s) => new Date(s.fecha + "T12:00:00"));
  const [month, setMonth] = useState(sesionDates[0]);

  if (sorted.length === 0) {
    if (!horario) return null;
    return (
      <div className="flex flex-col gap-3">
        <p className="font-mono text-2xs tracking-[0.25em] uppercase text-rosa">Cuándo</p>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Clock className="h-4 w-4 shrink-0 text-rosa" />
          <span>{horario}</span>
        </div>
      </div>
    );
  }

  const lastDate = sesionDates[sesionDates.length - 1];
  const firstMonthKey = sesionDates[0].getFullYear() * 12 + sesionDates[0].getMonth();
  const lastMonthKey = lastDate.getFullYear() * 12 + lastDate.getMonth();
  // Todos los meses que abarca el taller, uno al lado del otro (antes topeaba
  // en 3 y un taller de 4+ meses escondía el resto detrás de la navegación).
  const numberOfMonths = lastMonthKey - firstMonthKey + 1;
  // En mobile los meses siguen apilados 1 por fila (sin cambios, hay ancho de
  // sobra) — el achique es SOLO desktop, `md:`, donde el objetivo pasa a ser
  // que entren lado a lado en el ancho de la card (~530-610px) en vez de
  // apilarse. Sin el prefijo `md:` acá, un taller de 4 meses también
  // encogería el mobile (celdas de 16px con medio ancho de card vacío al
  // lado — nadie lo pidió, ahí sí sobra lugar). Base mobile-safe (44px)
  // siempre presente, el tramo por mes solo pisa desde `md:`. Números
  // calibrados contra el ancho REAL medido en el build de prod: 4 meses a
  // 1.75rem medía 784px reales contra una card de ~530-610px — hacía falta
  // bastante menos, no un ajuste fino. Clases completas y estáticas (no
  // template string) para que Tailwind las genere en el build.
  const cellSizeClass =
    numberOfMonths >= 4
      ? "[--cell-size:2.75rem] md:[--cell-size:1rem]"
      : numberOfMonths === 3
        ? "[--cell-size:2.75rem] md:[--cell-size:1.5rem]"
        : numberOfMonths === 2
          ? "[--cell-size:2.75rem] md:[--cell-size:2.25rem]"
          : "[--cell-size:2.75rem]";
  // El botón hereda `text-sm` (14-15px) del Button base — a 16-24px de celda
  // (desktop, 3+ meses) un número de 2 dígitos ("29") ya no entra sin pisar
  // la celda de al lado. Va atado al mismo tramo que cellSizeClass; `md:`
  // por la misma razón (mobile ya está bien con el tamaño heredado).
  // text-2xs/text-3xs = tokens del DS (10px/9px, ver typography.css), no
  // tamaños mágicos.
  const dayTextClass =
    numberOfMonths >= 4 ? "md:text-3xs" : numberOfMonths === 3 ? "md:text-2xs" : "";
  const weekdayTextClass = numberOfMonths >= 3 ? "md:text-3xs" : "";
  const grupos = agruparPorPatron(sorted);

  return (
    <div className="rounded-2xl bg-rosa/5 border border-rosa/20 overflow-hidden">
      {/* Eyebrow ADENTRO de la card (no arriba, suelta contra el fondo) —
          mismo criterio que "Orientado a"/"Sobre"/"Programa" (SeccionCard):
          cada bloque de la página es autocontenido, con su título como parte
          del mismo diseño en vez de una etiqueta flotando aparte. */}
      <p className="font-mono text-2xs tracking-[0.25em] uppercase text-rosa px-5 pt-5">Cuándo</p>
      <div className="flex justify-center py-2">
        <Calendar
          locale={es}
          month={month}
          onMonthChange={setMonth}
          numberOfMonths={numberOfMonths}
          startMonth={sesionDates[0]}
          endMonth={lastDate}
          showOutsideDays={false}
          // Default de la librería: "septiembre 2026" — con 4 meses angostos
          // envolvía en 2 líneas ("septiembre" / "2026"). El año no aporta acá
          // (las fechas completas ya están en el hero y en las píldoras de
          // abajo) — solo el nombre del mes, en las dos vistas (1 y N meses).
          formatters={{
            formatCaption: (m) => {
              const s = m.toLocaleDateString("es-AR", { month: "long" });
              return s.charAt(0).toUpperCase() + s.slice(1);
            },
          }}
          // No hay selección real (es un calendario de solo lectura) — pero
          // react-day-picker solo renderiza el día vía el <DayButton> con su
          // tamaño acotado (`min-w-(--cell-size)`) cuando `mode` u
          // `onDayClick` están presentes (`isInteractive` en su código
          // fuente); sin ninguno de los dos, cae a un <td> crudo sin límite
          // de ancho — cada celda terminaba tan ancha como le dejara la fila,
          // gigante en desktop/tablet. No-op a propósito, no agrega mode.
          onDayClick={() => {}}
          // El día NO es seleccionable — es un dato mostrado, no un control
          // (pedido explícito: "es meramente una imagen"). `pointer-events-none`
          // en el botón mata cursor/hover sin tocar el `disabled` semántico de
          // react-day-picker (ese sí atenuaría la opacidad — pisaría el círculo
          // rosa de "sesion"); `tabIndex={-1}` lo saca del tab order. Reusa
          // `CalendarDayButton` tal cual (mismo tamaño/estilo ya afinado), solo
          // le agrega el prop.
          components={{
            DayButton: (props) => <CalendarDayButton {...props} tabIndex={-1} />,
          }}
          modifiers={{ sesion: sesionDates }}
          // El modifier de react-day-picker pinta la clase en la CELDA
          // (<td>, `aspect-square h-full w-full` — una fracción flex del
          // ancho de la fila, ~80-100px en desktop/tablet), no en el botón:
          // correcto para un range-picker (barra continua entre días
          // seleccionados, ver DateRangePickerModal), pero acá cada sesión
          // es un círculo suelto — pintarlo en la celda daba un óvalo gigante
          // que se pisaba con la fila de abajo. `[&_button]:` redirige el
          // color/forma al <button> interno, que sí está acotado a
          // `--cell-size` (44px) vía `day_button` más abajo.
          modifiersClassNames={{
            sesion:
              "[&_button]:!bg-rosa [&_button]:!text-ink [&_button]:font-bold [&_button]:!opacity-100 [&_button]:!rounded-full",
          }}
          className={cellSizeClass}
          classNames={{
            // md:flex-wrap (no nowrap) a propósito: con el --cell-size chico
            // de arriba, N meses entran lado a lado en una fila — pero si algún
            // taller tuviera tantos meses que igual no entren, esto los manda a
            // una fila nueva en vez de desbordar/recortarse contra el
            // `overflow-hidden` de la card (default del DS es `md:flex-row`
            // sin wrap, pensado para 2 meses de un date-range picker).
            months:
              "relative flex flex-col gap-3 md:flex-row md:flex-wrap md:justify-center md:gap-2",
            // El default del DS es `w-full` — cada mes exige el 100% de la
            // fila, así que con flex-wrap SIEMPRE se apila 1 por fila sin
            // importar --cell-size (un % no se achica solo porque el
            // contenido es más chico). `flex-1 basis-0` los hace repartirse el
            // ancho por igual; `min-w-0` pisa el `min-width:auto` default de
            // flex (si no, el mes se resiste a achicarse por debajo de su
            // ancho de contenido y nunca entran 4 en una fila).
            month: "flex flex-col gap-2 md:min-w-0 md:flex-1 md:basis-0",
            // Default del DS: `table-layout: auto` — con 4 meses angostos el
            // navegador igual dimensiona cada columna por su contenido
            // (min-content de "30"/"29") e IGNORA el ancho angosto del <table>,
            // desbordando hacia el mes de al lado (números pisándose entre
            // meses). `table-fixed` fuerza a cada columna a `ancho_tabla / 7`
            // de verdad — pero el `<table>` es a su vez HIJO FLEX de `.rdp-
            // month` (`flex flex-col`) y por default un flex-item no se
            // achica por debajo de su min-content (`min-width:auto`), mismo
            // gotcha que en `.rdp-month` — sin `min-w-0` acá el ancho angosto
            // de arriba nunca llegaba a pegarle a la tabla.
            table: "w-full min-w-0 border-collapse table-fixed",
            // El botón base del DS fija `md:h-9 md:w-9` (36px, tap target grande
            // solo en mobile, patrón app-wide) — `min-w-(--cell-size)` de
            // CalendarDayButton es apenas un PISO: con 1 mes (44px) ya ganaba
            // por sí solo, pero con varios meses (--cell-size < 36px) el w-9
            // fijo pasa a ganar y el botón deja de achicarse aunque el resto sí
            // — hay que pisar ambos ejes con `!` para que seguir el tamaño
            // sea real en los dos sentidos, no solo la altura. `text-sm`
            // heredado (14-15px) no entra en una celda de 16-24px con 2
            // dígitos sin pisar la celda de al lado — de ahí dayTextClass.
            day_button: `!h-(--cell-size) !w-(--cell-size) pointer-events-none ${dayTextClass}`,
            weekday: `text-muted-foreground flex-1 select-none rounded-md text-xs font-normal ${weekdayTextClass}`,
          }}
        />
      </div>

      {/* Resumen agrupado por patrón (día de semana + horario) — misma card
          que el calendario, separado por una línea en vez de ser su propio
          bloque aparte. */}
      <div className="flex flex-col divide-y divide-rosa/15 border-t border-rosa/20 px-5">
        {grupos.map((g) => (
          <GrupoPill key={g.fechaDesde} grupo={g} />
        ))}
      </div>
    </div>
  );
}
