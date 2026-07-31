"""Saldos por cuenta (#809) — el corazón del cálculo. Nunca muta.

Hay DOS tipos de cuenta, que se calculan distinto:

**Cajas (plata real del negocio)** — Efectivo, Banco, Fondo Rental, Dólares, etc.:

    saldo = saldo_inicial
          + ingresos_alquiler   (cobrador Rental: Σ alquiler_pagos del cobrador)
          + entradas            (Σ movimientos donde la cuenta es destino)
          − egresos             (Σ movimientos donde la cuenta es origen)

**Cuentas corrientes de socio (Pablo/Tincho)** — NO son cajas de plata, son el
saldo de la rendición acumulada (quién le debe a quién). Un socio cobra en su
bolsillo plata del negocio → debe esa plata, menos la parte que es suya:

    saldo_cc = arranque           (saldo_inicial = lo que cobró de más PRE-sistema)
             + cobrado            (Σ alquiler_pagos del socio — plata que agarró)
             − su_parte           (su comisión devengada — la liquidación)
             + entradas − egresos (rendiciones: al rendir, baja su deuda)

    saldo_cc > 0 → DEUDOR   (el socio le debe a Rental)
    saldo_cc < 0 → ACREEDOR (Rental le debe al socio)
    saldo_cc = 0 → saldado (a mano)

`ingresos_alquiler`/`cobrado` DERIVAN de `alquiler_pagos` (única fuente del cobro,
#722): no se carga ningún movimiento por un cobro de cliente → cero doble-conteo.
`su_parte` viene de la liquidación (`reportes/`, devengado). El clean start se aplica
por la **fecha del alquiler** (`fecha_desde >= LIQUIDACION_INICIO`), MISMO corte que
la liquidación y la rendición (decisión 2026-06-03: corte por fecha del alquiler).

Las cuentas corrientes de socio NO suman al "total disponible" (esa plata la tiene
el socio en mano, no es caja del negocio). `calcular_saldos` es pura (testeable sin
DB). El SQL solo trae filas planas.
"""

from collections import defaultdict
from datetime import date

from reportes.liquidacion import LIQUIDACION_INICIO

from contabilidad.constants import SOCIOS_HUMANOS


def partes_socios(conn) -> dict[str, int]:
    """Lo que le CORRESPONDE a cada socio (su parte / comisión) acumulado desde el
    clean start hasta hoy, de la liquidación (`reportes/`). Devengado: solo pedidos
    saldados. Es lo que se le RESTA a la deuda de su cuenta corriente."""
    from reportes.liquidacion import liquidar

    data = liquidar(conn, LIQUIDACION_INICIO, date.today().isoformat())
    return {k: int(v) for k, v in data["resumen"]["por_beneficiario"].items()}


def ingresos_derivados(conn, desde: str | None = None, hasta: str | None = None) -> dict[str, int]:
    """Σ de `alquiler_pagos.monto` por `destinatario` (Pablo/Tincho/Rental), solo de
    pedidos cuyo ALQUILER cae en el clean start (`fecha_desde >= LIQUIDACION_INICIO`).
    Devuelve `{'Tincho': 480000, 'Pablo': 120000}`. Ventana opcional `desde`/`hasta`
    (por fecha de pago, inclusive por día)."""
    sql = """
        SELECT ap.destinatario, COALESCE(SUM(ap.monto), 0) AS total
        FROM alquiler_pagos ap
        JOIN alquileres al ON al.id = ap.pedido_id
        WHERE ap.destinatario IS NOT NULL
          AND NOT ap.anulado
          AND al.fecha_desde >= %s::date
    """
    params: list = [LIQUIDACION_INICIO]
    if desde:
        sql += " AND ap.fecha::date >= %s::date"
        params.append(desde)
    if hasta:
        sql += " AND ap.fecha::date <= %s::date"
        params.append(hasta)
    sql += " GROUP BY ap.destinatario"
    rows = conn.execute(sql, tuple(params)).fetchall()
    return {r["destinatario"]: int(r["total"] or 0) for r in rows}


def movimientos_planos(conn, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Movimientos NO anulados (filas planas para el cálculo de saldos). Ventana
    opcional por `fecha`."""
    from database import row_to_dict

    sql = """
        SELECT id, tipo, monto, cuenta_origen_id, cuenta_destino_id,
               categoria_id, metodo, fecha, es_rendicion, rendicion_mes
        FROM movimientos
        WHERE NOT anulado
    """
    params: list = []
    if desde:
        sql += " AND fecha >= %s::date"
        params.append(desde)
    if hasta:
        sql += " AND fecha <= %s::date"
        params.append(hasta)
    return [row_to_dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def calcular_saldos(
    cuentas: list[dict],
    movimientos: list[dict],
    ingresos: dict[str, int],
    partes: dict[str, int] | None = None,
) -> list[dict]:
    """PURA. Para cada cuenta, su saldo y el desglose. Devuelve una lista en el
    mismo orden que `cuentas`.

    Una cuenta de socio HUMANO (Pablo/Tincho) se trata como **cuenta corriente**
    (deudor/acreedor); el resto como **caja** de plata real. Ver el módulo arriba.

    `cuentas`: filas con id/nombre/tipo/socio/saldo_inicial.
    `movimientos`: filas con monto/cuenta_origen_id/cuenta_destino_id (no anulados).
    `ingresos`: {socio: monto} derivado de alquiler_pagos (lo que cobró cada uno).
    `partes`: {socio: monto} de la liquidación (su parte / comisión devengada).
    """
    partes = partes or {}
    egresos_por: dict = defaultdict(int)   # cuenta es origen → sale plata
    entradas_por: dict = defaultdict(int)  # cuenta es destino → entra plata
    for m in movimientos:
        monto = int(m["monto"] or 0)
        origen = m.get("cuenta_origen_id")
        destino = m.get("cuenta_destino_id")
        if origen:
            egresos_por[origen] += monto
        if destino:
            entradas_por[destino] += monto

    filas: list[dict] = []
    for c in cuentas:
        cid = c["id"]
        socio = c.get("socio")
        moneda = c.get("moneda") or "ARS"
        saldo_inicial = int(c.get("saldo_inicial") or 0)
        # Los cobros de clientes son en ARS → solo alimentan cuentas en pesos.
        cobrado = int(ingresos.get(socio, 0)) if (socio and moneda == "ARS") else 0
        entradas = int(entradas_por.get(cid, 0))
        egresos = int(egresos_por.get(cid, 0))
        es_cc = socio in SOCIOS_HUMANOS

        fila = {
            "id": cid,
            "nombre": c["nombre"],
            "tipo": c["tipo"],
            "socio": socio,
            "moneda": moneda,
            "saldo_inicial": saldo_inicial,
            "ingresos_alquiler": cobrado,
            "entradas": entradas,
            "egresos": egresos,
            "es_cuenta_corriente": es_cc,
            "su_parte": 0,
            "estado": None,
        }
        if es_cc:
            # Cuenta corriente del socio: deuda = arranque + cobró − su parte ± rendiciones.
            su_parte = int(partes.get(socio, 0))
            saldo = saldo_inicial + cobrado - su_parte + entradas - egresos
            fila["su_parte"] = su_parte
            fila["estado"] = "deudor" if saldo > 0 else ("acreedor" if saldo < 0 else "saldado")
            fila["saldo"] = saldo
        else:
            # Caja de plata real (incluye el Fondo Rental, que sí es cash del negocio).
            fila["saldo"] = saldo_inicial + cobrado + entradas - egresos
        filas.append(fila)
    return filas


def _totales_por_moneda(filas: list[dict]) -> dict[str, int]:
    """Suma de saldos agrupada por moneda (no se mezclan ARS y USD). PURA."""
    tot: dict[str, int] = defaultdict(int)
    for f in filas:
        tot[f.get("moneda") or "ARS"] += int(f["saldo"])
    return dict(tot)


def saldos(conn, as_of: str | None = None) -> dict:
    """Saldos de todas las cuentas activas. Separa las **cajas** (plata real del
    negocio, que suman al total disponible) de las **cuentas corrientes de socio**
    (deudor/acreedor — esa plata la tiene el socio en mano, no es caja). Compone la
    derivación de ingresos + la liquidación (su parte) con el libro de movimientos."""
    cuentas = _cuentas_activas(conn)
    movs = movimientos_planos(conn)
    ingresos = ingresos_derivados(conn)
    partes = partes_socios(conn)
    filas = calcular_saldos(cuentas, movs, ingresos, partes)
    cajas = [f for f in filas if not f["es_cuenta_corriente"]]
    socios = [f for f in filas if f["es_cuenta_corriente"]]
    totales = _totales_por_moneda(cajas)  # el disponible es solo plata real del negocio
    return {
        "cuentas": filas,   # solo activas (_cuentas_activas filtra) — saldo_de_cuenta
                            # tiene su propio fallback para inactivas/inexistentes
        "cajas": cajas,
        "socios": socios,
        "totales": totales,
        "total_disponible": totales.get("ARS", 0),  # ARS (compat); USD va en `totales`
        "as_of": as_of or date.today().isoformat(),
    }


def saldo_de_cuenta(conn, cuenta_id: int) -> int:
    """Saldo actual de UNA cuenta (entero ARS). Usado por la baja lógica."""
    for f in saldos(conn)["cuentas"]:
        if f["id"] == cuenta_id:
            return int(f["saldo"])
    # Cuenta inactiva o inexistente: recalcular incluyéndola explícitamente.
    from contabilidad.queries.cuentas import obtener_cuenta
    cuenta = obtener_cuenta(conn, cuenta_id)
    if not cuenta:
        return 0
    filas = calcular_saldos(
        [cuenta], movimientos_planos(conn), ingresos_derivados(conn), partes_socios(conn)
    )
    return int(filas[0]["saldo"]) if filas else 0


def _cuentas_activas(conn) -> list[dict]:
    from contabilidad.queries.cuentas import listar_cuentas
    return listar_cuentas(conn, incluir_inactivas=False)
