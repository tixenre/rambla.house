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

/** Horario de la landing: si todas las clases comparten franja horaria,
 * "08:30 — 12:30 hs" (o "Jueves 19:00 — 21:00 hs" si además caen siempre el
 * mismo día de la semana, el caso común del taller semanal); si varían (ej.
 * preproducción vs. rodaje), el `horario` libre del taller (ej.
 * "Preproducción 13:30 a 16:00 hs · Rodaje 13:30 a 21:30 hs") — mostrar solo
 * la primera franja mentiría sobre el resto, pero un genérico "según la
 * clase" sin el detalle real tampoco ayuda si el dato ya está cargado
 * (pedido del dueño, 2026-08-20). Sin ESE campo tampoco cargado, recién ahí
 * cae al genérico. Sin clases cargadas (borrador recién creado), el mismo
 * `fallback` hace de horario principal. */
export function resumenHorario(clases: SesionFecha[], fallback: string): string {
  if (clases.length === 0) return fallback;
  const [primero] = clases;
  const mismaFranja = clases.every(
    (c) => c.hora_inicio_min === primero.hora_inicio_min && c.hora_fin_min === primero.hora_fin_min,
  );
  if (!mismaFranja) return fallback || "Horarios según la clase";
  const horario = `${primero.hora_inicio_str ?? fmtHhmm(primero.hora_inicio_min)} — ${primero.hora_fin_str ?? fmtHhmm(primero.hora_fin_min)} hs`;
  const primerDia = new Date(primero.fecha + "T12:00:00").getDay();
  const mismoDia = clases.every((c) => new Date(c.fecha + "T12:00:00").getDay() === primerDia);
  if (!mismoDia) return horario;
  const dia = new Date(primero.fecha + "T12:00:00").toLocaleDateString("es-AR", {
    weekday: "long",
  });
  return `${dia.charAt(0).toUpperCase()}${dia.slice(1)} ${horario}`;
}
