import { test } from "node:test";
import assert from "node:assert/strict";
import { espacioOverrideInicial } from "./estudio-slots.ts";

// Candado del bug real del pedido #445 (2026-07-28): `ReservaDialog` siempre
// hidrataba el campo de override vacío al editar → mandaba `espacio_monto:
// null` → `editar_reserva` recalculaba a lista, perdiendo en silencio
// cualquier tarifa negociada. `espacioOverrideInicial` decide qué mostrar.

test("espacioOverrideInicial vacío cuando el precio persistido coincide con el automático", () => {
  assert.equal(espacioOverrideInicial(80_000, 80_000), "");
});

test("espacioOverrideInicial devuelve el precio persistido cuando difiere del automático (tarifa negociada)", () => {
  assert.equal(espacioOverrideInicial(120_000, 80_000), "120000");
});

test("espacioOverrideInicial vacío cuando no hay centinela todavía (null/undefined)", () => {
  assert.equal(espacioOverrideInicial(null, 80_000), "");
  assert.equal(espacioOverrideInicial(undefined, 80_000), "");
});

test("espacioOverrideInicial distingue un override menor al automático (no solo mayor)", () => {
  assert.equal(espacioOverrideInicial(50_000, 80_000), "50000");
});
