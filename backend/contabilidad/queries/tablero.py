"""Tablero financiero (#809) — compone las miradas en una sola respuesta. Nunca muta.

1. **Disponible**: cuánta plata hay y dónde (saldos por caja). Plata percibida.
2. **Ganancia del mes**: la parte de Rental − gastos. Resultado del negocio.

**Rental y el Estudio son dos economías distintas** (#1283) y el tablero las
devuelve SEPARADAS (2026-08-02, pedido del dueño): la plata del Estudio no es
ingreso de Rental ni un costo suyo — es otra unidad de negocio. Antes la
pantalla mostraba `ingresos` = devengado TOTAL (Rental + dueños + Estudio)
contra los gastos de Rental, así que un mes con un turno grande del Estudio se
leía como "ingresos $1.421.000 − gastos $217.659" y abajo un número rojo que no
era esa resta. Ahora viajan `parte_rental` (el ingreso real de Rental),
`comisiones_duenos`, `parte_estudio` y el disponible partido en
`total_rental`/`total_estudio` — el front muestra, no calcula.

La rendición / quién le debe a quién vive en la cuenta corriente de socios
(`saldos().socios`, que ya viaja en `disponible`).
"""

from services.fechas import mes_actual_ar

from contabilidad.constants import SOCIOS_HUMANOS
from contabilidad.queries.cierres import cierre_de
from contabilidad.queries.posiciones import parte_de_cuenta
from contabilidad.queries.pyl import ganancia_neta
from contabilidad.queries.saldos import saldos

# La parte/cobrador del Estudio dentro de `PARTES` — su caja (Caja Estudio,
# `socio='Estudio'`) es plata de la OTRA economía. Constante local con nombre,
# en vez del literal suelto repartido por el módulo.
PARTE_ESTUDIO = "Estudio"


def _totales_por_economia(cajas: list[dict]) -> dict:
    """Parte el disponible en ARS entre las cajas del Estudio y el resto (Rental).

    Usa `parte_de_cuenta` (la misma función que clasifica una cuenta para la
    posición acumulada) en vez de mirar `socio` a mano: una caja genérica sin
    socio cae a Rental por el mismo criterio que ya usa el motor. Los socios
    humanos no entran (sus cuentas corrientes no son caja — `saldos()` ya las
    separó en `socios`, pero el guard queda explícito)."""
    rental = estudio = 0
    for c in cajas:
        if (c.get("moneda") or "ARS") != "ARS" or c.get("socio") in SOCIOS_HUMANOS:
            continue
        saldo = int(c["saldo"])
        if parte_de_cuenta(c.get("socio"), c.get("tipo"), c.get("nombre")) == PARTE_ESTUDIO:
            estudio += saldo
        else:
            rental += saldo
    return {"rental": rental, "estudio": estudio}


def mes_actual() -> str:
    return mes_actual_ar()


def tablero(conn, mes: str | None = None) -> dict:
    mes = mes or mes_actual()
    disponible = saldos(conn)
    gan = ganancia_neta(conn, mes)
    c = cierre_de(conn, mes)
    return {
        "mes": mes,
        "cierre": {
            "cerrado": c is not None,
            "cerrado_por": c["cerrado_por"] if c else None,
            "cerrado_at": c["cerrado_at"] if c else None,
        },
        "disponible": disponible,
        "ganancia_mes": {
            "mes": mes,
            # `ingresos` = devengado TOTAL del mes; se conserva por compatibilidad
            # pero NO es el ingreso de Rental (incluye dueños + Estudio) — la
            # pantalla usa `parte_rental`.
            "ingresos": gan["facturado"],
            "parte_rental": gan["parte_rental"],
            "comisiones_duenos": gan["comisiones_duenos"],
            "parte_estudio": gan["parte_estudio"],
            "gastos": gan["gastos"],
            "neta": gan["ganancia_neta"],
        },
        # El disponible partido por economía (ARS): la Caja Estudio no es plata
        # de Rental. `disponible.totales` sigue siendo el total de todas las cajas.
        "disponible_por_economia": _totales_por_economia(disponible["cajas"]),
    }
