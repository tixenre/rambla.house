"""Ganancia neta del mes (#809) — la parte de Rambla menos los gastos. Nunca muta.

Criterio (decisión del dueño): la **ganancia de Rambla** es lo que le toca a
Rambla de los alquileres MENOS los gastos operativos. La comisión que se llevan
los dueños de los equipos (Pablo, Tincho, terceros) **NO es ganancia de Rambla**:
es un costo — plata facturada que se les debe. Por eso el P&L muestra el desglose:

    facturado (devengado total)  −  comisiones a dueños  −  gastos  =  ganancia

donde `comisiones a dueños = facturado − parte de Rambla` (todo lo facturado que
no es de Rambla, según el reparto de la liquidación). La parte de Rambla ya la
calcula el reparto (`reportes/comisiones`); acá solo se compone.

**El Estudio (economía separada, #1283) NO es una "comisión a dueños"**: es otra
unidad de negocio de la misma empresa, no un costo pagado a un tercero. Por eso
se descuenta APARTE (`parte_estudio`) en vez de mezclarse en `comisiones_duenos`
— mostrarlo como "costo" en la cascada del P&L sería engañoso. `ganancia_neta`
sigue siendo solo la parte de Rambla menos gastos (el Estudio nunca formó parte
de esa ganancia; esto es sobre cómo se ETIQUETA el desglose, no un cambio en el
número final).

OJO: la base de ingreso (devengado) es distinta a la del **saldo de caja** (que se
mueve por plata entrante, incluidas señas). La dualidad devengado vs percibido es
a propósito. Si el mes está cerrado (#721) el devengado sale de la foto congelada.
"""

from reportes.cierres import rango_mes, snapshot_de
from reportes.liquidacion import liquidar

from contabilidad.queries.movimientos import gastos_por_categoria


def _resumen_devengado(conn, mes: str) -> dict:
    """Resumen de la liquidación del mes (foto si está cerrado): `total` + `por_beneficiario`."""
    desde, hasta = rango_mes(mes)
    snap = snapshot_de(conn, mes)
    data = snap if snap is not None else liquidar(conn, desde, hasta)
    return data["resumen"]


def ganancia_neta(conn, mes: str) -> dict:
    """Ganancia de Rambla del mes = **parte de Rambla − gastos**. Expone el desglose
    completo: facturado (devengado total), comisiones a dueños, parte del Estudio
    y gastos por categoría.

    La comisión de los dueños NO se cuenta como ganancia de Rambla: se descuenta
    (vía usar la parte de Rambla en lugar del total facturado). La parte del
    Estudio TAMPOCO es comisión a dueños (es otra economía, no un costo) — se
    descuenta aparte para que `comisiones_duenos` no la mezcle con Pablo/Tincho.
    """
    desde, hasta = rango_mes(mes)
    resumen = _resumen_devengado(conn, mes)
    facturado = int(resumen["total"])
    por_benef = resumen["por_beneficiario"]
    parte_rambla = int(por_benef.get("Rambla", 0))
    parte_estudio = int(por_benef.get("Estudio", 0))
    comisiones_duenos = facturado - parte_rambla - parte_estudio
    por_categoria = gastos_por_categoria(conn, desde, hasta)
    gastos = sum(int(g["monto"]) for g in por_categoria)
    return {
        "mes": mes,
        "facturado": facturado,
        "comisiones_duenos": comisiones_duenos,
        "parte_estudio": parte_estudio,
        "gastos": gastos,
        "ganancia_neta": parte_rambla - gastos,
        "gastos_por_categoria": por_categoria,
    }
