/**
 * mover-plata.ts — De lo que pasó en la vida real al `tipo` del libro contable.
 *
 * El form de movimientos obligaba a elegir, como PRIMER paso, una de 5 palabras
 * técnicas (`gasto` / `transferencia` / `retiro` / `aporte` / `ajuste`), más un
 * toggle aparte para "cambio de divisa". Son 6 decisiones sobre vocabulario
 * contable antes de poder cargar un peso — y varias se solapan: `transferencia` y
 * un `ajuste` con dos cuentas hacen exactamente lo mismo con el saldo; `retiro` y
 * `gasto` también, salvo por el P&L.
 *
 * Estructuralmente son solo **3 formas** (sale / entra / mueve entre dos) × *¿es un
 * costo del negocio?*. Este módulo hace esa derivación: el usuario contesta lo que
 * ya sabe (de dónde salió, a dónde fue, de qué es) y el `tipo` cae solo.
 *
 * **No cambia el libro por debajo.** Los 5 tipos siguen existiendo en la base
 * porque cargan semántica que consumen `gastos_por_categoria`/`pyl.py`/
 * `reporte_mensual`, y `crear_movimiento` sigue siendo la única puerta de escritura
 * con todas sus validaciones. Esto es solo la entrada.
 *
 * Es una función PURA a propósito (sin React): así la tabla de verdad completa se
 * testea sin montar nada. El componente solo pinta.
 *
 * `ajuste` NO sale de acá. Es la puerta de "el modelo no captura la realidad" y
 * ponerla como quinta opción normal invita a usarla de cajón de sastre — que es
 * como se pudre un libro contable. Vive aparte, en "Corregir un saldo a mano",
 * con nota obligatoria. Su otro uso legítimo (las dos patas de un cambio de
 * divisa) ya queda derivado automáticamente acá.
 */
import type { CambioDivisaInput, MovimientoInput } from "@/lib/admin/api";

/** Las 4 cosas que le pueden pasar a la plata, en el idioma del dueño. */
export const QUE_PASO = [
  { key: "pague", label: "Pagué algo", sub: "Sale plata de una caja" },
  { key: "entro", label: "Entró plata de afuera", sub: "Un aporte, un reintegro" },
  { key: "movi", label: "Moví plata entre mis cuentas", sub: "De una caja a otra" },
  { key: "reparto", label: "Repartimos", sub: "Una parte le pasa plata a otra" },
] as const;

export type QuePaso = (typeof QUE_PASO)[number]["key"];

export interface RespuestasMoverPlata {
  quePaso: QuePaso;
  monto: number;
  cuentaOrigenId: number | null;
  cuentaDestinoId: number | null;
  /** Solo cuando `quePaso === "pague"`: el rubro del gasto. `null` + `esDelSocio`
   *  → no es un costo del negocio (ver abajo). */
  categoriaId: number | null;
  /** "Pagué algo" pero NO es un gasto del negocio: plata que se llevó un socio.
   *  Es la única diferencia real entre `gasto` y `retiro`, y así se pregunta. */
  esDelSocio: boolean;
  /** Monedas de las cuentas elegidas — deciden solas si es un cambio de divisa,
   *  sin que el usuario tenga que saber que existe esa categoría. */
  monedaOrigen?: string | null;
  monedaDestino?: string | null;
  /** Solo para el cambio de divisa: pesos por dólar. */
  cotizacion?: number | null;
  montoDestino?: number | null;
  metodo?: string | null;
  fecha?: string | null;
  nota?: string | null;
  beneficiario?: string | null;
}

export type Derivado =
  | { kind: "movimiento"; body: MovimientoInput }
  | { kind: "cambio_divisa"; body: CambioDivisaInput };

/** Qué campos mostrar para cada respuesta — así el componente no repite el árbol. */
export function camposVisibles(quePaso: QuePaso) {
  return {
    origen: quePaso === "pague" || quePaso === "movi" || quePaso === "reparto",
    destino: quePaso === "entro" || quePaso === "movi" || quePaso === "reparto",
    // El rubro solo tiene sentido para un gasto del negocio.
    categoria: quePaso === "pague",
    beneficiario: quePaso === "pague",
  };
}

/** ¿Las dos cuentas elegidas son de monedas distintas? Entonces NO es una
 *  transferencia (el backend las rechaza: no hay conversión automática) sino un
 *  cambio de divisa. El usuario nunca elige eso — se deduce.
 *
 *  Vale para las DOS respuestas que mueven plata entre dos cuentas ("movi" y
 *  "reparto"): un socio también puede rendir en dólares. Sin esto, un reparto
 *  ARS↔USD salía como `transferencia` y moría en un 400 del backend
 *  ("No se puede transferir entre cuentas de distinta moneda"). Es seguro por
 *  debajo: `crear_cambio_divisa` genera dos `ajuste`, y `ajuste` SÍ está
 *  permitido contra la cuenta corriente de un socio — lo bloqueado ahí es
 *  `retiro`/`aporte` (MEMORIA 2026-07-02). */
export function esCambioDeDivisa(r: RespuestasMoverPlata): boolean {
  return Boolean(
    (r.quePaso === "movi" || r.quePaso === "reparto") &&
    r.monedaOrigen &&
    r.monedaDestino &&
    r.monedaOrigen !== r.monedaDestino,
  );
}

export class MoverPlataInvalido extends Error {}

/**
 * El árbol de decisión completo:
 *
 * | qué pasó   | + condición                | → tipo                       |
 * |------------|----------------------------|------------------------------|
 * | Pagué algo | es un gasto del negocio    | `gasto` (con categoría)      |
 * | Pagué algo | se lo llevó un socio       | `retiro` (fuera del P&L)     |
 * | Entró      | —                          | `aporte`                     |
 * | Moví       | misma moneda               | `transferencia`              |
 * | Moví       | distinta moneda            | `cambio_divisa` (2 `ajuste`) |
 * | Repartimos | misma moneda               | `transferencia`              |
 * | Repartimos | distinta moneda            | `cambio_divisa` (2 `ajuste`) |
 *
 * "Repartimos" y "Moví" producen el MISMO tipo a propósito: para el libro son la
 * misma operación. Se preguntan distinto porque para el dueño no lo son, y porque
 * el reparto llega precargado desde la ficha del socio (`inicial`).
 *
 * ⚠️ Un "Repartimos" cargado acá NO queda marcado `es_rendicion` — esa marca solo
 * la pone `POST /rendicion/{mes}/saldar`, que a cambio resuelve las cuentas solo y
 * no deja elegir la caja. **No es un número mal:** la posición ACUMULADA
 * (`contabilidad/queries/posiciones.py::clasificar_flujo`) no mira `es_rendicion` a
 * propósito, justamente para contar estos repartos; lo único que no los ve es la
 * lista mensual "Movimientos de rendición". Exponer `es_rendicion` en
 * `MovimientoCreate` sería peor: `ya_transferido` mapea cuenta→parte y devuelve
 * `None` para una caja genérica, así que marcar "Tincho → Efectivo" restaría de
 * Tincho sin sumarle a nadie y dejaría la vista mensual asimétrica.
 *
 * Tira `MoverPlataInvalido` con un mensaje en castellano si falta algo. El backend
 * revalida todo igual (`validar_estructura_movimiento` + `_validar_cuentas_y_categoria`):
 * esto es para no mandar un request que ya sabemos que va a fallar.
 */
export function derivarMovimiento(r: RespuestasMoverPlata): Derivado {
  if (!(r.monto > 0)) throw new MoverPlataInvalido("Poné un monto mayor a cero.");

  const comun = {
    metodo: r.metodo || null,
    fecha: r.fecha || null,
    nota: r.nota || null,
  };

  if (r.quePaso === "pague") {
    if (!r.cuentaOrigenId) throw new MoverPlataInvalido("Elegí de qué caja salió la plata.");
    if (r.esDelSocio) {
      // No es un costo del negocio → NO lleva categoría y queda fuera del P&L.
      return {
        kind: "movimiento",
        body: {
          tipo: "retiro",
          monto: r.monto,
          cuenta_origen_id: r.cuentaOrigenId,
          cuenta_destino_id: null,
          categoria_id: null,
          beneficiario: r.beneficiario || null,
          ...comun,
        },
      };
    }
    if (!r.categoriaId) throw new MoverPlataInvalido("Elegí de qué es el gasto.");
    return {
      kind: "movimiento",
      body: {
        tipo: "gasto",
        monto: r.monto,
        cuenta_origen_id: r.cuentaOrigenId,
        cuenta_destino_id: null,
        categoria_id: r.categoriaId,
        beneficiario: r.beneficiario || null,
        ...comun,
      },
    };
  }

  if (r.quePaso === "entro") {
    if (!r.cuentaDestinoId) throw new MoverPlataInvalido("Elegí a qué caja entró la plata.");
    return {
      kind: "movimiento",
      body: {
        tipo: "aporte",
        monto: r.monto,
        cuenta_origen_id: null,
        cuenta_destino_id: r.cuentaDestinoId,
        categoria_id: null,
        beneficiario: null,
        ...comun,
      },
    };
  }

  // "movi" y "reparto": las dos son una transferencia entre dos cuentas.
  if (!r.cuentaOrigenId) throw new MoverPlataInvalido("Elegí de qué cuenta sale la plata.");
  if (!r.cuentaDestinoId) throw new MoverPlataInvalido("Elegí a qué cuenta va la plata.");
  if (r.cuentaOrigenId === r.cuentaDestinoId)
    throw new MoverPlataInvalido("El origen y el destino no pueden ser la misma cuenta.");

  if (esCambioDeDivisa(r)) {
    if (!r.cotizacion && !r.montoDestino)
      throw new MoverPlataInvalido(
        "Para cambiar de moneda necesito la cotización o el monto en la otra moneda.",
      );
    // Se manda UNO SOLO de los dos, nunca los dos juntos. `derivar_cambio_divisa`
    // (backend) acepta 2 de 3 y deriva el que falte, pero NO cruza los que le
    // llegan: mandando monto+cotización contradictorios guardaba
    // "140.000 ARS ↔ 999 USD @ 1400" sin chistar. Los montos son lo que de verdad
    // mueve plata (la cotización queda informativa), así que si hay monto de
    // destino gana ese y la cotización se deriva de él.
    const porMonto = r.montoDestino != null && r.montoDestino > 0;
    return {
      kind: "cambio_divisa",
      body: {
        cuenta_origen_id: r.cuentaOrigenId,
        cuenta_destino_id: r.cuentaDestinoId,
        monto_origen: r.monto,
        monto_destino: porMonto ? r.montoDestino : null,
        cotizacion: porMonto ? null : (r.cotizacion ?? null),
        fecha: r.fecha || null,
        nota: r.nota || null,
      },
    };
  }

  return {
    kind: "movimiento",
    body: {
      tipo: "transferencia",
      monto: r.monto,
      cuenta_origen_id: r.cuentaOrigenId,
      cuenta_destino_id: r.cuentaDestinoId,
      categoria_id: null,
      beneficiario: null,
      ...comun,
    },
  };
}
