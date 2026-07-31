import type { Sesion } from "@/lib/api";

/**
 * .ics client-side, un VEVENT por clase — no reusa `services/ical.py` del
 * backend (esa infra es pedido-shaped: reserva/cliente/equipos, ver
 * `reserva_to_vevent`) y no vale la pena un endpoint nuevo para esto. Hora
 * local "flotante" (sin TZID/Z) — mismo criterio de simplicidad que el
 * builder genérico del backend, razonable para un negocio de una sola ciudad.
 */
function escapeIcs(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");
}

function fold(line: string): string {
  // RFC 5545 §3.1: líneas > 75 octetos se pliegan con CRLF + espacio.
  if (line.length <= 75) return line;
  const parts: string[] = [];
  let rest = line;
  while (rest.length > 75) {
    parts.push(rest.slice(0, 75));
    rest = " " + rest.slice(75);
  }
  parts.push(rest);
  return parts.join("\r\n");
}

function fmtDtLocal(fecha: string, minutos: number): string {
  const [y, m, d] = fecha.split("-");
  const h = Math.floor(minutos / 60);
  const min = minutos % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${y}${m}${d}T${pad(h)}${pad(min)}00`;
}

function fmtDtStampUtc(): string {
  return new Date().toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
}

function claseToVevent(
  clase: Sesion,
  opts: { tallerNombre: string; direccion: string; uidPrefix: string; index: number },
): string {
  const summary = clase.titulo ? `${clase.titulo} — ${opts.tallerNombre}` : opts.tallerNombre;
  const lines = [
    "BEGIN:VEVENT",
    `UID:${opts.uidPrefix}-${opts.index}@rambla-rental`,
    `DTSTAMP:${fmtDtStampUtc()}`,
    `DTSTART:${fmtDtLocal(clase.fecha, clase.hora_inicio_min)}`,
    `DTEND:${fmtDtLocal(clase.fecha, clase.hora_fin_min)}`,
    `SUMMARY:${escapeIcs(summary)}`,
  ];
  if (clase.descripcion) lines.push(`DESCRIPTION:${escapeIcs(clase.descripcion)}`);
  if (opts.direccion) lines.push(`LOCATION:${escapeIcs(opts.direccion)}`);
  lines.push("END:VEVENT");
  return lines.map(fold).join("\r\n");
}

/** Arma el .ics completo (1 VEVENT por clase) y dispara la descarga. */
export function descargarIcsTaller(params: {
  tallerNombre: string;
  slug: string;
  direccion: string;
  clases: Sesion[];
}) {
  const { tallerNombre, slug, direccion, clases } = params;
  const vevents = clases.map((c, i) =>
    claseToVevent(c, { tallerNombre, direccion, uidPrefix: slug, index: i }),
  );
  const ics = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Rambla Rental//Escuela//ES",
    "CALSCALE:GREGORIAN",
    ...vevents,
    "END:VCALENDAR",
  ].join("\r\n");

  const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${slug}.ics`;
  a.click();
  URL.revokeObjectURL(url);
}
