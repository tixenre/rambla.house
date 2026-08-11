import { useState } from "react";
import { Clock } from "lucide-react";
import { es } from "date-fns/locale";
import { Calendar } from "@/design-system/ui/calendar";
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

  return (
    <div className="flex items-center gap-3 rounded-xl bg-muted/40 border border-border/50 px-5 py-4">
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
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Clock className="h-4 w-4 shrink-0 text-rosa" />
        <span>{horario}</span>
      </div>
    );
  }

  const lastDate = sesionDates[sesionDates.length - 1];
  const firstMonthKey = sesionDates[0].getFullYear() * 12 + sesionDates[0].getMonth();
  const lastMonthKey = lastDate.getFullYear() * 12 + lastDate.getMonth();
  // Todos los meses que abarca el taller, uno al lado del otro (antes topeaba
  // en 3 y un taller de 4+ meses escondía el resto detrás de la navegación).
  const numberOfMonths = lastMonthKey - firstMonthKey + 1;
  const grupos = agruparPorPatron(sorted);

  return (
    <div className="flex flex-col gap-3">
      {/* Calendario en card con tinte rosa */}
      <div className="rounded-2xl bg-rosa/5 border border-rosa/20 overflow-hidden flex justify-center py-2">
        <Calendar
          locale={es}
          month={month}
          onMonthChange={setMonth}
          numberOfMonths={numberOfMonths}
          startMonth={sesionDates[0]}
          endMonth={lastDate}
          showOutsideDays={false}
          modifiers={{ sesion: sesionDates }}
          modifiersClassNames={{
            sesion: "bg-rosa text-ink font-bold !opacity-100 rounded-full",
          }}
          className="[--cell-size:2.75rem]"
          classNames={{
            // Un taller de 4+ meses no entra en una sola fila — sin esto se
            // recortaba contra el `overflow-hidden` de la card (default del DS
            // es `md:flex-row` sin wrap, pensado para 2 meses de un date-range picker).
            months: "relative flex flex-col gap-4 md:flex-row md:flex-wrap md:justify-center",
          }}
        />
      </div>

      {/* Píldoras agrupadas por patrón (día de semana + horario) */}
      <div className="flex flex-col gap-2">
        {grupos.map((g) => (
          <GrupoPill key={g.fechaDesde} grupo={g} />
        ))}
      </div>
    </div>
  );
}
