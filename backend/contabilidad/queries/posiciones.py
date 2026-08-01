"""Posición acumulada de cada parte — la lectura ÚNICA de "quién le debe a quién".
Nunca muta.

## El problema que resuelve

Hasta ahora la misma pregunta tenía dos respuestas que podían contradecirse:

- **Cuenta corriente** (`queries/saldos.py::calcular_saldos`): acumulada, pero SOLO
  para Pablo/Tincho. Una caja (Fondo Rental, Caja Estudio) no tiene ninguna — así
  que un crédito entre cajas (Rental cobró los $120.000 que le corresponden al
  Estudio) no existía en ninguna vista de saldos.
- **Rendición** (`queries/rendicion.py::_netting`): las 4 partes, pero POR MES —
  `ya_transferido` filtra `rendicion_mes = %s`, así que **arranca de cero cada mes
  por construcción**: un reparto parcial de julio es invisible en agosto.

Resultado real (agosto 2026): la rendición del mes sugería "Rental → Tincho
$110.500" mientras la cuenta corriente decía "Tincho le debe $734.088". Las dos
correctas en su propio marco; actuar sobre la mensual movía la plata al revés.

## La fórmula

    posicion[P] = devengado[P] − cobrado[P] − arranque[P] − flujo_neto[P]

    > 0 → a P LE FALTA RECIBIR   (devengó más de lo que tiene en la mano)
    < 0 → P TIENE DE MÁS         (tiene plata que le corresponde a otra parte)

Misma convención de signo que `rendicion.py::_netting` (`pendiente`), que es donde
vive la acción. Para un socio humano vale la identidad **`posicion == −saldo_cc`**
(la cuenta corriente de `saldos.py`, que usa el signo opuesto) — no son dos cálculos
distintos que hay que mantener sincronizados a mano: es el mismo número. Lo fija
`test_contabilidad_posiciones.py::test_posicion_de_socio_es_el_negativo_de_su_cc`.

## Por qué NO alcanza con `saldo − su_parte`

Porque el saldo de una caja se mueve por cosas que NO son un reparto. Si Rental paga
un gasto de $50.000 con la plata del Fondo, su cash baja pero **no cambia en nada lo
que le debe a Pablo/Tincho/Estudio** — la parte de cada uno es un porcentaje de lo
FACTURADO, no de lo que sobró después de los gastos. Restar `su_parte` del saldo
contaría ese gasto como si le bajara la deuda con los demás.

Por eso el flujo se clasifica (`clasificar_flujo`): solo los movimientos que
efectivamente mueven plata ENTRE partes cuentan para la posición. La regla, en una
línea: **la cuenta corriente de un socio humano no tiene caja, así que TODO lo que la
toca es un reparto con el negocio; una caja real solo reparte cuando del otro lado
hay otra parte.**

Efecto lateral valioso: el clasificador NO mira `es_rendicion`, así que también toma
los repartos cargados desde el botón "Me pagó / Le cargué" de la ficha del socio
(`contabilidad.cuentas.lazy.tsx`), que crea una `transferencia` SIN esa marca y por
eso era invisible para `ya_transferido`.

## Alcance

Módulo nuevo, `queries/` puro (CQRS-lite: no importa de `commands/`). **No toca
`calcular_saldos`**: se acopla al lado, sin cambiar ningún número que hoy se muestra
(_"el core que anda no se toca"_). Unificar las dos fórmulas en una sola es un paso
posterior, después de que el candado cruzado haya estado verde contra datos reales.
"""

from collections import defaultdict
from database import now_ar
from reportes.liquidacion import LIQUIDACION_INICIO

from contabilidad.constants import PARTES, SOCIOS_HUMANOS


def parte_de_cuenta(socio, tipo, nombre) -> str | None:
    """Mapea una cuenta a su parte de rendición (Pablo/Tincho/Rental/Estudio) o None.

    Fuente única — la usa el clasificador de acá Y `queries/rendicion.py`, que antes
    tenía su propia copia privada."""
    if socio in PARTES:
        return socio
    if tipo == "fondo" or (nombre or "").strip().lower() == "fondo rental":
        return "Rental"
    return None


def clasificar_flujo(mov: dict, parte_por_cuenta: dict, cc_por_cuenta: dict):
    """PURA. ¿Este movimiento mueve plata ENTRE dos partes? Devuelve `(de, a)` o
    `None` si es plata que el negocio mueve puertas adentro (un gasto desde una caja
    real, una transferencia entre dos cajas propias, un aporte, las dos patas de un
    cambio de divisa).

    `parte_por_cuenta`: {cuenta_id: parte|None}. `cc_por_cuenta`: {cuenta_id: bool}
    (si esa cuenta es la cuenta corriente de un socio humano).

    **Una caja GENÉRICA (Efectivo, Banco — sin `socio`) cuenta como "Rental".** Es
    plata del negocio, y "Rental" es la parte que representa al negocio de alquiler
    (mismo criterio que el fallback de `parte_de_cuenta` para un `tipo='fondo'` sin
    socio). Sin esto el clasificador daba dos resultados para la MISMA operación
    económica: `Fondo Rental → Caja Estudio` contaba como reparto, pero
    `Efectivo → Caja Estudio` no — mientras que `Efectivo → Caja Pablo` sí, porque
    la rama de la cuenta corriente asumía "Rental" del otro lado. Con el fallback
    las tres se comportan igual (hallazgo del supervisor, verificado en vivo).

    Ojo: el fallback NO convierte en reparto lo que no lo es, porque la rama 1 exige
    DOS puntas y partes DISTINTAS: un gasto desde Efectivo (sin destino) o una
    transferencia Efectivo→Banco (las dos "Rental") siguen sin mover nada.

    Las ramas, en orden:
      1. Las dos puntas son partes distintas → reparto directo (incluye el saldado de
         una rendición y el "Me pagó / Le cargué" de la ficha del socio).
      2. Sale de la CC de un socio, sin destino → el socio le está devolviendo o
         adelantando plata al negocio (paga un gasto de Rental con la suya). Su CC no
         tiene caja: si sale plata de ahí, es contra el negocio.
      3. Entra a la CC de un socio, sin origen → el negocio le puso plata.
      4. Lo demás NO es reparto — es plata del negocio moviéndose puertas adentro.
    """
    o = mov.get("cuenta_origen_id")
    d = mov.get("cuenta_destino_id")
    po = (parte_por_cuenta.get(o) or "Rental") if o else None
    pd = (parte_por_cuenta.get(d) or "Rental") if d else None

    if po and pd and po != pd:
        return (po, pd)
    if o and cc_por_cuenta.get(o) and po:
        return (po, "Rental")
    if d and cc_por_cuenta.get(d) and pd:
        return ("Rental", pd)
    return None


def flujos_netos(movimientos: list[dict], parte_por_cuenta: dict, cc_por_cuenta: dict,
                 moneda_por_cuenta: dict | None = None):
    """PURA. Neto por parte de los movimientos que SON reparto (positivo = recibió).

    `moneda_por_cuenta` (opcional, {cuenta_id: 'ARS'|'USD'}): descarta los
    movimientos que tocan una cuenta que NO es en pesos. **La posición está en
    pesos** (`devengado` sale de la liquidación y `cobrado` de `alquiler_pagos`,
    los dos ARS), así que sumarle el `monto` de un movimiento en dólares mezclaría
    unidades — 500 dólares contarían como 500 pesos. Hoy no hay ninguna cuenta en
    USD vinculada a una parte, pero `parte_de_cuenta` mapea CUALQUIER `tipo='fondo'`
    a "Rental": el día que se cree un fondo en dólares, sin este filtro la posición
    de Rental se ensuciaría en silencio. Sin el mapa, no filtra (compatibilidad con
    los tests puros)."""
    neto: dict = defaultdict(int)
    for m in movimientos:
        if moneda_por_cuenta is not None:
            tocadas = [m.get("cuenta_origen_id"), m.get("cuenta_destino_id")]
            if any(c and moneda_por_cuenta.get(c, "ARS") != "ARS" for c in tocadas):
                continue
        par = clasificar_flujo(m, parte_por_cuenta, cc_por_cuenta)
        if not par:
            continue
        de, a = par
        monto = int(m["monto"] or 0)
        neto[de] -= monto
        neto[a] += monto
    return dict(neto)


def sugerir_transferencias(pendiente: dict, liquidez: dict | None = None) -> list[dict]:
    """PURA. Emparejamiento greedy: quién le transfiere a quién para que todas las
    partes queden en cero. Determinístico (orden fijo de `PARTES`).

    `pendiente[p] > 0` → le falta recibir; `< 0` → tiene de más y debe pagar.
    Extraída de `rendicion.py::_netting`, que ahora la importa de acá — una sola
    forma de emparejar, la use la vista mensual o la acumulada.

    `liquidez` (opcional): {parte: cash real en su caja}. Ordena a los pagadores de
    más a menos plata disponible, para no sugerir una transferencia que el pagador
    no puede hacer. Sin esto, el greedy tomaba a los pagadores en orden de `PARTES`
    y sugería cosas como "Pablo → Estudio $120.000" cuando la plata la tenía Rental:
    la deuda de un socio es puro balance (su plata está en un banco propio, fuera
    del sistema), mientras que el Fondo Rental es cash de verdad. El orden de
    `PARTES` se conserva como desempate — `sort` es estable, así que el resultado
    sigue siendo determinístico."""
    receptores = [[p, pendiente.get(p, 0)] for p in PARTES if pendiente.get(p, 0) > 0]
    pagadores = [[p, -pendiente.get(p, 0)] for p in PARTES if pendiente.get(p, 0) < 0]
    if liquidez:
        pagadores.sort(key=lambda par: -int(liquidez.get(par[0], 0)))

    sugeridos = []
    i = j = 0
    while i < len(pagadores) and j < len(receptores):
        monto = min(pagadores[i][1], receptores[j][1])
        if monto > 0:
            sugeridos.append({"de": pagadores[i][0], "a": receptores[j][0], "monto": monto})
        pagadores[i][1] -= monto
        receptores[j][1] -= monto
        if pagadores[i][1] == 0:
            i += 1
        if receptores[j][1] == 0:
            j += 1
    return sugeridos


def calcular_posiciones(devengado: dict, cobrado: dict, flujo_neto: dict,
                        arranques: dict) -> list[dict]:
    """PURA. La posición acumulada de cada parte + las transferencias que la cierran.

    `devengado`: {parte: monto} de la liquidación (lo que le CORRESPONDE).
    `cobrado`:   {parte: monto} de `alquiler_pagos` (lo que agarró de los clientes).
    `flujo_neto`:{parte: monto} de `flujos_netos` (positivo = recibió en repartos).
    `arranques`: {parte: monto} — SOLO socios humanos (ver `posiciones`)."""
    pendiente = {
        p: int(devengado.get(p, 0))
        - int(cobrado.get(p, 0))
        - int(arranques.get(p, 0))
        - int(flujo_neto.get(p, 0))
        for p in PARTES
    }
    partes = [
        {
            "parte": p,
            "le_corresponde": int(devengado.get(p, 0)),
            "cobro": int(cobrado.get(p, 0)),
            "arranque": int(arranques.get(p, 0)),
            "repartido": int(flujo_neto.get(p, 0)),
            "pendiente": pendiente[p],
        }
        for p in PARTES
    ]
    return partes


def posiciones(conn) -> dict:
    """La posición acumulada de las 4 partes, al día de hoy. Compone el devengado
    (liquidación), lo cobrado (`alquiler_pagos`) y los repartos ya hechos.

    El devengado sale de `liquidar_rango` y NO de `liquidar` crudo: un mes ya cerrado
    tiene una foto congelada (`liquidacion_cierres`) y el acumulado tiene que aportar
    exactamente lo que dice esa foto, no un recálculo en vivo que podría
    contradecirla. (`partes_socios` en `saldos.py` sigue usando `liquidar` crudo — que
    ignora los cierres. Es una divergencia REAL y conocida: la caza el chequeo
    `cc_vs_posicion_divergente` de `reconciliacion.py`, y se cierra recién cuando las
    dos fórmulas se unifiquen, con el diff a la vista del dueño.)"""
    from contabilidad.queries.cuentas import listar_cuentas
    from contabilidad.queries.saldos import ingresos_derivados, movimientos_planos
    from reportes.cierres import liquidar_rango

    # `now_ar()` y no `date.today()`: la hora del server puede estar en UTC y
    # adelantar el día (MEMORIA 2026-06-30, `services/fechas.py`).
    hoy = now_ar().date().isoformat()
    devengado = {
        k: int(v)
        for k, v in liquidar_rango(conn, LIQUIDACION_INICIO, hoy)["resumen"][
            "por_beneficiario"
        ].items()
    }
    cobrado = ingresos_derivados(conn)

    # Inactivas incluidas A PROPÓSITO: un movimiento contra una cuenta dada de baja
    # sigue habiendo movido plata: si no se mapea, su reparto se pierde en silencio.
    cuentas = listar_cuentas(conn, incluir_inactivas=True)
    parte_por_cuenta = {
        c["id"]: parte_de_cuenta(c.get("socio"), c.get("tipo"), c.get("nombre"))
        for c in cuentas
    }
    cc_por_cuenta = {c["id"]: c.get("socio") in SOCIOS_HUMANOS for c in cuentas}
    moneda_por_cuenta = {c["id"]: (c.get("moneda") or "ARS") for c in cuentas}
    # El arranque (`saldo_inicial`) es una DEUDA pre-sistema solo para un socio
    # humano. Para una caja real es "cuánto cash había el día 1" — un concepto de
    # caja, no de posición: sumarlo acá arruinaría los dos números.
    #
    # **Solo cuentas ACTIVAS**, aunque el mapa de arriba incluya las inactivas: la
    # cuenta corriente (`calcular_saldos` vía `saldos()`) solo mira activas, y un
    # dict comprehension sobre las dos habría dejado que una Caja Tincho vieja,
    # dada de baja con otro arranque, pisara en silencio a la vigente — rompiendo
    # la identidad `posicion == −saldo_cc` sin que nada avisara. El índice único
    # parcial `idx_cuentas_socio` garantiza una sola cuenta activa por socio, así
    # que acá no hay ambigüedad.
    arranques = {
        c["socio"]: int(c.get("saldo_inicial") or 0)
        for c in cuentas
        if c.get("socio") in SOCIOS_HUMANOS and c.get("activa")
    }

    movs = movimientos_planos(conn)
    flujo = flujos_netos(movs, parte_por_cuenta, cc_por_cuenta, moneda_por_cuenta)
    partes = calcular_posiciones(devengado, cobrado, flujo, arranques)
    pendiente = {p["parte"]: p["pendiente"] for p in partes}

    # Quién tiene cash de verdad para pagar. La CC de un socio NO es plata (su
    # dinero está en un banco propio, fuera del sistema) → queda en 0 y el greedy
    # la deja para el final.
    #
    # Se calcula con `calcular_saldos` (la función PURA) sobre los datos que esta
    # función YA trajo, en vez de llamar a `saldos(conn)`: ese wrapper invoca
    # `partes_socios()`, que corre una liquidación COMPLETA más — y acá no hace
    # falta, porque el saldo de una CAJA no resta `su_parte` (por eso `partes={}`).
    # Llamarlo costaba una liquidación entera de gusto en cada carga de la pantalla,
    # y `reconciliar()` —que ya llama a `saldos()` por su cuenta— pagaba el doble.
    from contabilidad.queries.saldos import calcular_saldos

    activas = [c for c in cuentas if c.get("activa")]
    liquidez: dict = {}
    for f in calcular_saldos(activas, movs, cobrado, {}):
        if f["es_cuenta_corriente"] or (f.get("moneda") or "ARS") != "ARS":
            continue
        parte = parte_de_cuenta(f.get("socio"), f.get("tipo"), f.get("nombre"))
        if parte:
            liquidez[parte] = liquidez.get(parte, 0) + int(f["saldo"])

    return {
        "partes": partes,
        "sugeridos": sugerir_transferencias(pendiente, liquidez),
        "liquidez": liquidez,
        "float_sin_saldar": _float_sin_saldar(conn),
        "as_of": hoy,
    }


def _float_sin_saldar(conn) -> int:
    """Plata ya cobrada de pedidos que TODAVÍA no se terminaron de cobrar.

    Está adentro de la posición (es plata del negocio que la parte tiene en la mano)
    pero su devengado todavía no existe — la liquidación solo cuenta pedidos
    SALDADOS. Sin nombrarlo, el número de la posición incluye una parte que no es
    "ganancia repartible todavía" y nadie lo sabría. Es la diferencia entre las dos
    definiciones de "cobrado" que conviven en el módulo (`ingresos_derivados` cuenta
    todos los pagos; `cobrado_por_socio` solo los de pedidos saldados)."""
    row = conn.execute(
        """SELECT COALESCE(SUM(ap.monto), 0) AS m
           FROM alquiler_pagos ap
           JOIN alquileres al ON al.id = ap.pedido_id
           WHERE NOT ap.anulado
             AND al.fecha_desde >= %s::date
             AND COALESCE(al.monto_pagado, 0) < COALESCE(al.monto_total, 0)""",
        (LIQUIDACION_INICIO,),
    ).fetchone()
    return int(row["m"] or 0)
