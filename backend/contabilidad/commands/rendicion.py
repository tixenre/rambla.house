"""Escritura de la rendición mensual (#809) — única puerta de mutación.

Al registrar un saldado (`saldar`) se crea como `transferencia` en el libro de
movimientos con `es_rendicion=True` — NO es un sistema paralelo. Lectura (el
cálculo de quién le debe a quién) → `queries/rendicion.py`.
"""

from reportes.cierres import validar_mes

from contabilidad.constants import PARTES
from contabilidad.queries.rendicion import cuenta_de_parte


def saldar(conn, mes: str, *, de: str, a: str, monto: int,
           metodo=None, fecha=None, nota=None, por=None) -> dict:
    """Registra un saldado de rendición: una transferencia entre las cajas de las
    partes, marcada `es_rendicion`. Reusa el libro de movimientos (no duplica)."""
    validar_mes(mes)
    if de not in PARTES or a not in PARTES:
        raise ValueError(f"Las partes de la rendición son {', '.join(PARTES)}.")
    if de == a:
        raise ValueError("El que paga y el que recibe no pueden ser la misma parte.")
    monto = int(monto or 0)
    if monto <= 0:
        raise ValueError("El monto debe ser mayor a cero.")

    origen = cuenta_de_parte(conn, de)
    destino = cuenta_de_parte(conn, a)
    if not origen or not destino:
        raise ValueError("Falta la caja de alguna de las partes (Caja del socio o Fondo Rental).")

    from contabilidad.commands.movimientos import crear_movimiento

    return crear_movimiento(
        conn, tipo="transferencia", monto=monto,
        cuenta_origen_id=origen, cuenta_destino_id=destino,
        metodo=metodo, fecha=fecha,
        nota=nota or f"Rendición {mes}: {de} → {a}", por=por,
        es_rendicion=True, rendicion_mes=mes,
    )
