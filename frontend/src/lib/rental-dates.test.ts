/**
 * Candado del "hoy" del negocio (`hoyAR`).
 *
 * Bug real 2026-08-02: un pago cargado a las 21:54 hora argentina quedó fechado
 * el día siguiente porque el front usaba `new Date().toISOString().slice(0, 10)`
 * — la fecha UTC. En el borde de mes eso mueve la plata al reporte del mes que
 * viene. Estos tests fijan que la fecha salga del reloj de Argentina.
 */
import { test } from "node:test";
import assert from "node:assert/strict";

import { hoyAR, TZ_AR, ymd } from "./rental-dates.ts";

/** Formato YYYY-MM-DD estricto. */
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

test("hoyAR devuelve YYYY-MM-DD", () => {
  assert.match(hoyAR(), ISO_DATE);
});

test("hoyAR usa el reloj de Argentina, no UTC", () => {
  // La fecha que un reloj argentino muestra ahora mismo, calculada de otra
  // forma (partes de Intl) para no repetir la implementación.
  const partes = new Intl.DateTimeFormat("es-AR", {
    timeZone: TZ_AR,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const p = (t: string) => partes.find((x) => x.type === t)!.value;
  assert.equal(hoyAR(), `${p("year")}-${p("month")}-${p("day")}`);
});

test("a las 21:54 de Argentina la fecha NO es la de mañana (el bug del pago)", () => {
  // 2026-08-02 21:54 ART == 2026-08-03 00:54 UTC. `toISOString()` habría dicho
  // "2026-08-03"; en hora argentina sigue siendo el 2.
  const instante = new Date("2026-08-03T00:54:00Z");
  const enAR = new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ_AR,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(instante);
  assert.equal(enAR, "2026-08-02");
  assert.equal(instante.toISOString().slice(0, 10), "2026-08-03"); // lo que hacía antes
});

test("ymd formatea una fecha elegida sin correrla de día", () => {
  // Un Date construido en hora local: `toISOString()` puede saltar de día según
  // la hora; `ymd` respeta el día que el usuario eligió.
  const d = new Date(2026, 7, 5, 23, 30); // 5 de agosto, 23:30 local
  assert.equal(ymd(d), "2026-08-05");
});
