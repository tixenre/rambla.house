// ── Formato de horarios de talleres (minutos desde medianoche) ─────────────────
// Escuela v2 F1: las clases guardan horas en MINUTOS (510 = 8:30). El backend
// resuelve los strings de display (`hora_inicio_str`); este helper existe SOLO
// para estado local todavía no guardado (el asistente de clases del admin) —
// no reimplementar el formato en componentes.

/** 510 → "08:30", 780 → "13:00", 1440 → "24:00". */
export function fmtHhmm(minutos: number): string {
  const h = Math.floor(minutos / 60);
  const m = minutos % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/** 1 → "1ra", 2 → "2da", 3 → "3ra", 4 → "4ta", n → "nta". */
export function ordinalEdicion(n: number): string {
  const map: Record<number, string> = { 1: "1ra", 2: "2da", 3: "3ra", 4: "4ta" };
  return map[n] ?? `${n}ta`;
}

export type SesionFecha = {
  fecha: string;
  hora_inicio_min: number;
  hora_fin_min: number;
  hora_inicio_str?: string;
  hora_fin_str?: string;
  titulo?: string;
};

/** "sábado 11 de julio y sábado 18 de julio" (≤2 clases, el caso intensivo)
 * → "13 clases entre septiembre y noviembre" (3+, meses distintos) → "13
 * clases en septiembre" (3+, mismo mes). El resumen crudo fecha_inicio/
 * fecha_fin lee bien para 1-2 clases pero es engañoso para un curso semanal
 * largo (parece que hay solo 2 clases). */
export function resumenFechas(
  clases: SesionFecha[],
  fechaInicioStr: string,
  fechaFinStr: string,
): string {
  if (clases.length <= 1) return fechaInicioStr;
  if (clases.length === 2) return `${fechaInicioStr} y ${fechaFinStr}`;
  const optsMes: Intl.DateTimeFormatOptions = { month: "long" };
  const mesInicio = new Date(clases[0].fecha + "T12:00:00").toLocaleDateString("es-AR", optsMes);
  const mesFin = new Date(clases[clases.length - 1].fecha + "T12:00:00").toLocaleDateString(
    "es-AR",
    optsMes,
  );
  return mesInicio === mesFin
    ? `${clases.length} clases en ${mesInicio}`
    : `${clases.length} clases entre ${mesInicio} y ${mesFin}`;
}

/** Agrupa las clases por franja horaria distinta y arma un resumen tipo
 * "Preproducción 14:30 – 16:30 hs · Rodaje 14:30 – 21:30 hs", derivado
 * SIEMPRE de las clases reales — nunca de un campo de texto aparte, que
 * puede desincronizarse en silencio (bug real: el `horario` libre de un
 * taller quedó con los horarios viejos después de reprogramar las clases
 * en el calendario, 2026-08-20 — invisible mientras cayó al genérico, recién
 * se vio al empezar a mostrarlo). El label de cada franja es el título más
 * repetido entre sus clases, sin el número final ("Rodaje 1" → "Rodaje") —
 * tolera que una clase suelta (ej. "Proyección y devoluciones") comparta
 * franja con otra sin arruinar el resumen. `null` si hay una sola franja
 * (nada que agrupar) o ninguna clase tiene título cargado (nada que ofrezca
 * más que el genérico de siempre). */
function derivarHorarioPorFranja(clases: SesionFecha[]): string | null {
  type Franja = {
    inicio: number;
    fin: number;
    inicioStr: string;
    finStr: string;
    conteo: Map<string, number>;
  };
  const franjas: Franja[] = [];
  for (const c of clases) {
    let franja = franjas.find((f) => f.inicio === c.hora_inicio_min && f.fin === c.hora_fin_min);
    if (!franja) {
      franja = {
        inicio: c.hora_inicio_min,
        fin: c.hora_fin_min,
        inicioStr: c.hora_inicio_str ?? fmtHhmm(c.hora_inicio_min),
        finStr: c.hora_fin_str ?? fmtHhmm(c.hora_fin_min),
        conteo: new Map(),
      };
      franjas.push(franja);
    }
    const label = (c.titulo ?? "").replace(/\s*\d+\s*$/, "").trim();
    if (label) franja.conteo.set(label, (franja.conteo.get(label) ?? 0) + 1);
  }
  if (franjas.length < 2 || franjas.every((f) => f.conteo.size === 0)) return null;
  return franjas
    .map((f) => {
      let label = "";
      let max = 0;
      for (const [l, n] of f.conteo) {
        if (n > max) {
          max = n;
          label = l;
        }
      }
      return label ? `${label} ${f.inicioStr} – ${f.finStr} hs` : `${f.inicioStr} – ${f.finStr} hs`;
    })
    .join(" · ");
}

/** Horario de la landing: si todas las clases comparten franja horaria,
 * "08:30 — 12:30 hs" (o "Jueves 19:00 — 21:00 hs" si además caen siempre el
 * mismo día de la semana, el caso común del taller semanal); si varían (ej.
 * preproducción vs. rodaje), el detalle real derivado de las clases (ver
 * `derivarHorarioPorFranja`) — mostrar solo la primera franja mentiría sobre
 * el resto. Sin títulos que permitan derivarlo, cae al `horario` libre del
 * taller; sin ESE campo tampoco cargado, al genérico. Sin clases cargadas
 * (borrador recién creado), el `fallback` hace de horario principal. */
export function resumenHorario(clases: SesionFecha[], fallback: string): string {
  if (clases.length === 0) return fallback;
  const [primero] = clases;
  const mismaFranja = clases.every(
    (c) => c.hora_inicio_min === primero.hora_inicio_min && c.hora_fin_min === primero.hora_fin_min,
  );
  if (!mismaFranja)
    return derivarHorarioPorFranja(clases) ?? (fallback || "Horarios según la clase");
  const horario = `${primero.hora_inicio_str ?? fmtHhmm(primero.hora_inicio_min)} — ${primero.hora_fin_str ?? fmtHhmm(primero.hora_fin_min)} hs`;
  const primerDia = new Date(primero.fecha + "T12:00:00").getDay();
  const mismoDia = clases.every((c) => new Date(c.fecha + "T12:00:00").getDay() === primerDia);
  if (!mismoDia) return horario;
  const dia = new Date(primero.fecha + "T12:00:00").toLocaleDateString("es-AR", {
    weekday: "long",
  });
  return `${dia.charAt(0).toUpperCase()}${dia.slice(1)} ${horario}`;
}
