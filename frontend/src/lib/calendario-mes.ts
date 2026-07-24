/**
 * Grilla de mes reusable — semana arranca lunes, con celdas de relleno del
 * mes anterior/siguiente para completar semanas de 7. Antes este cálculo
 * vivía duplicado (CalendarioWidget del dashboard + cada vista semanal del
 * Estudio) — un solo lugar para no divergir si el criterio de semana cambia.
 */
export const MESES = [
  "Enero",
  "Febrero",
  "Marzo",
  "Abril",
  "Mayo",
  "Junio",
  "Julio",
  "Agosto",
  "Septiembre",
  "Octubre",
  "Noviembre",
  "Diciembre",
];

export function ymd(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function mesCells(cursor: Date): {
  cells: Date[];
  weeks: Date[][];
  rangeStart: string;
  rangeEnd: string;
  headerLabel: string;
} {
  const year = cursor.getFullYear();
  const month = cursor.getMonth();
  const firstDay = new Date(year, month, 1);
  const lastDay = new Date(year, month + 1, 0);
  const startOffset = (firstDay.getDay() + 6) % 7; // Lunes = 0
  const gridStart = new Date(year, month, 1 - startOffset);
  const totalCells = Math.ceil((startOffset + lastDay.getDate()) / 7) * 7;
  const cells = Array.from({ length: totalCells }, (_, i) => {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    return d;
  });
  const weeks: Date[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return {
    cells,
    weeks,
    rangeStart: ymd(cells[0]),
    rangeEnd: ymd(cells[cells.length - 1]),
    headerLabel: `${MESES[month]} ${year}`,
  };
}
