import { test } from "node:test";
import assert from "node:assert/strict";
import {
  camposVisibles,
  derivarMovimiento,
  esCambioDeDivisa,
  MoverPlataInvalido,
  type RespuestasMoverPlata,
} from "./mover-plata.ts";

// Tabla de verdad del árbol de decisión. El riesgo real de este cambio es derivar
// un `tipo` con la semántica de P&L equivocada — un retiro cargado como gasto
// ensucia la ganancia del mes. Por eso se testea cada rama, no solo el happy path.

const base: RespuestasMoverPlata = {
  quePaso: "pague",
  monto: 50_000,
  cuentaOrigenId: null,
  cuentaDestinoId: null,
  categoriaId: null,
  esDelSocio: false,
};

const r = (over: Partial<RespuestasMoverPlata>): RespuestasMoverPlata => ({ ...base, ...over });

/** Deriva y estrecha a la rama `movimiento` (TS no estrecha desde un assert). */
function derivarMov(resp: RespuestasMoverPlata) {
  const d = derivarMovimiento(resp);
  assert.equal(d.kind, "movimiento");
  if (d.kind !== "movimiento") throw new Error("inalcanzable");
  return d.body;
}

test("pagué algo + rubro → gasto con categoría (cuenta en el P&L)", () => {
  const b = derivarMov(r({ cuentaOrigenId: 3, categoriaId: 7 }));
  assert.equal(b.tipo, "gasto");
  assert.equal(b.categoria_id, 7);
  assert.equal(b.cuenta_origen_id, 3);
  assert.equal(b.cuenta_destino_id, null);
});

test("pagué algo + se lo llevó un socio → retiro SIN categoría (fuera del P&L)", () => {
  // El candado que protege la ganancia: `gastos_por_categoria` filtra
  // `tipo = 'gasto'`, así que un retiro no puede contaminar el P&L.
  const b = derivarMov(r({ cuentaOrigenId: 3, esDelSocio: true }));
  assert.equal(b.tipo, "retiro");
  assert.equal(b.categoria_id, null);
});

test("entró plata de afuera → aporte, solo con destino", () => {
  const b = derivarMov(r({ quePaso: "entro", cuentaDestinoId: 5 }));
  assert.equal(b.tipo, "aporte");
  assert.equal(b.cuenta_origen_id, null);
  assert.equal(b.cuenta_destino_id, 5);
});

test("moví entre dos cuentas de la misma moneda → transferencia", () => {
  const b = derivarMov(
    r({
      quePaso: "movi",
      cuentaOrigenId: 3,
      cuentaDestinoId: 5,
      monedaOrigen: "ARS",
      monedaDestino: "ARS",
    }),
  );
  assert.equal(b.tipo, "transferencia");
});

test("moví entre monedas distintas → cambio de divisa, sin que el usuario lo elija", () => {
  const resp = r({
    quePaso: "movi",
    cuentaOrigenId: 3,
    cuentaDestinoId: 9,
    monedaOrigen: "ARS",
    monedaDestino: "USD",
    cotizacion: 1400,
  });
  assert.equal(esCambioDeDivisa(resp), true);
  const d = derivarMovimiento(resp);
  assert.equal(d.kind, "cambio_divisa");
  if (d.kind !== "cambio_divisa") throw new Error("inalcanzable");
  assert.equal(d.body.cotizacion, 1400);
  assert.equal(d.body.monto_origen, 50_000);
});

test("cambio de divisa NUNCA manda cotización y monto juntos (podrían contradecirse)", () => {
  // El backend acepta 2 de 3 y deriva el que falta, pero no cruza los que le
  // llegan: mandando los dos guardaba "140.000 ARS ↔ 999 USD @ 1400" sin chistar.
  const conAmbos = r({
    quePaso: "movi",
    cuentaOrigenId: 3,
    cuentaDestinoId: 9,
    monedaOrigen: "ARS",
    monedaDestino: "USD",
    cotizacion: 1400,
    montoDestino: 999,
  });
  const d = derivarMovimiento(conAmbos);
  assert.equal(d.kind, "cambio_divisa");
  if (d.kind !== "cambio_divisa") throw new Error("inalcanzable");
  assert.equal(d.body.monto_destino, 999, "el monto manda");
  assert.equal(d.body.cotizacion, null, "la cotización se deriva, no se impone");
});

test("cambio de divisa sin cotización ni monto destino → error claro, no un request roto", () => {
  assert.throws(
    () =>
      derivarMovimiento(
        r({
          quePaso: "movi",
          cuentaOrigenId: 3,
          cuentaDestinoId: 9,
          monedaOrigen: "ARS",
          monedaDestino: "USD",
        }),
      ),
    MoverPlataInvalido,
  );
});

test("repartimos → transferencia (para el libro es lo mismo que mover entre cuentas)", () => {
  const b = derivarMov(r({ quePaso: "reparto", cuentaOrigenId: 5, cuentaDestinoId: 1 }));
  assert.equal(b.tipo, "transferencia");
});

test("repartimos entre monedas distintas → cambio de divisa, no un 400 del backend", () => {
  // El form de la ficha del socio se protegía filtrando las cajas por moneda; al
  // colapsarlo sobre este form ese filtro no existe, así que la rama tiene que
  // cubrir "reparto" igual que "movi" — si no, un socio que rinde en dólares
  // arma una `transferencia` que el backend rechaza.
  const resp = r({
    quePaso: "reparto",
    cuentaOrigenId: 5,
    cuentaDestinoId: 9,
    monedaOrigen: "ARS",
    monedaDestino: "USD",
    cotizacion: 1400,
  });
  assert.equal(esCambioDeDivisa(resp), true);
  const d = derivarMovimiento(resp);
  assert.equal(d.kind, "cambio_divisa");
  if (d.kind !== "cambio_divisa") throw new Error("inalcanzable");
  assert.equal(d.body.cotizacion, 1400);
  assert.equal(d.body.cuenta_origen_id, 5);
  assert.equal(d.body.cuenta_destino_id, 9);
});

test("un reparto de la misma moneda NO se confunde con un cambio de divisa", () => {
  assert.equal(
    esCambioDeDivisa(
      r({
        quePaso: "reparto",
        cuentaOrigenId: 5,
        cuentaDestinoId: 1,
        monedaOrigen: "ARS",
        monedaDestino: "ARS",
      }),
    ),
    false,
  );
});

test("NINGUNA respuesta produce un ajuste", () => {
  // `ajuste` es la puerta de "el modelo no captura la realidad" y vive aparte,
  // con fricción. Si alguna rama empieza a producirlo, este candado se rompe.
  const casos: RespuestasMoverPlata[] = [
    r({ cuentaOrigenId: 3, categoriaId: 7 }),
    r({ cuentaOrigenId: 3, esDelSocio: true }),
    r({ quePaso: "entro", cuentaDestinoId: 5 }),
    r({
      quePaso: "movi",
      cuentaOrigenId: 3,
      cuentaDestinoId: 5,
      monedaOrigen: "ARS",
      monedaDestino: "ARS",
    }),
    r({ quePaso: "reparto", cuentaOrigenId: 5, cuentaDestinoId: 1 }),
  ];
  for (const c of casos) {
    const d = derivarMovimiento(c);
    if (d.kind === "movimiento") assert.notEqual(d.body.tipo, "ajuste");
  }
});

test("monto en cero o negativo se rechaza antes de armar nada", () => {
  assert.throws(() => derivarMovimiento(r({ monto: 0, cuentaOrigenId: 3 })), MoverPlataInvalido);
  assert.throws(() => derivarMovimiento(r({ monto: -1, cuentaOrigenId: 3 })), MoverPlataInvalido);
});

test("falta la cuenta → error en castellano, distinto según qué falta", () => {
  assert.throws(() => derivarMovimiento(r({ categoriaId: 7 })), /de qué caja salió/);
  assert.throws(() => derivarMovimiento(r({ quePaso: "entro" })), /a qué caja entró/);
  assert.throws(
    () => derivarMovimiento(r({ quePaso: "movi", cuentaOrigenId: 3 })),
    /a qué cuenta va/,
  );
});

test("un gasto sin rubro se frena acá, no en el backend", () => {
  assert.throws(() => derivarMovimiento(r({ cuentaOrigenId: 3 })), /de qué es el gasto/);
});

test("origen y destino iguales se rechaza", () => {
  assert.throws(
    () => derivarMovimiento(r({ quePaso: "movi", cuentaOrigenId: 3, cuentaDestinoId: 3 })),
    /misma cuenta/,
  );
});

test("camposVisibles espeja el árbol (el componente no lo repite)", () => {
  assert.deepEqual(camposVisibles("pague"), {
    origen: true,
    destino: false,
    categoria: true,
    beneficiario: true,
  });
  assert.deepEqual(camposVisibles("entro"), {
    origen: false,
    destino: true,
    categoria: false,
    beneficiario: false,
  });
  assert.deepEqual(camposVisibles("movi"), {
    origen: true,
    destino: true,
    categoria: false,
    beneficiario: false,
  });
  assert.deepEqual(camposVisibles("reparto"), {
    origen: true,
    destino: true,
    categoria: false,
    beneficiario: false,
  });
});
