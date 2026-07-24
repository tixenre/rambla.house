/** Slots de hora de inicio disponibles para una reserva del Estudio — cada
 *  media hora entre `openHour` y el último inicio que deja lugar a `minHours`
 *  antes de `closeHour`. Fuente única: reserva pública (StudioBookingForm) y
 *  alta/edición admin (ReservaDialog) generan la MISMA grilla. */
export function pad(n: number) {
  return n.toString().padStart(2, "0");
}

export type EstudioSlot = { value: string; label: string; hour: number; minute: 0 | 30 };

export function buildTimeSlots(
  openHour: number,
  closeHour: number,
  minHours: number,
): EstudioSlot[] {
  const slots: EstudioSlot[] = [];
  const lastStartMin = closeHour * 60 - minHours * 60;
  for (let h = openHour; h < closeHour; h++) {
    for (const m of [0, 30] as const) {
      if (h * 60 + m > lastStartMin) continue;
      slots.push({
        value: `${pad(h)}:${pad(m)}`,
        label: `${pad(h)}:${pad(m)}`,
        hour: h,
        minute: m,
      });
    }
  }
  return slots;
}
