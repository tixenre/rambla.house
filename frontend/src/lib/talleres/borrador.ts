// ── Mensaje de WhatsApp para un borrador de inscripción sin enviar ─────────────
// Usado por InscripcionesSection (scoped a una edición) y SinEnviarAdminSection
// (vista global "Sin enviar") — una sola fuente para no divergir el copy.

import type { Borrador } from "@/lib/admin/api/types";

/** Mensaje de WhatsApp pre-armado — mismo criterio que `CarritoCard`. */
export function buildBorradorWhatsappMessage(b: Pick<Borrador, "nombre">): string {
  const nombre = b.nombre?.trim().split(/\s+/)[0];
  const saludo = nombre ? `Hola ${nombre}` : "Hola";
  return `${saludo}, te escribo de Rambla 👋 Vi que estabas por anotarte a uno de nuestros talleres. ¿Te ayudo a terminar la inscripción?`;
}
