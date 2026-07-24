"""Reporte mensual de Rambla (#809) — compone las miradas del mes en una sola
respuesta, derivando TODO del motor (no recalcula ni doble-cuenta). Nunca muta.

Cada capa sale de UNA sola fuente del paquete:
- **Devengado** (lo que se ganó): la liquidación del mes (`reportes/`).
- **Percibido** (lo que entró): los cobros del mes por cobrador (`alquiler_pagos`).
- **Gastos del mes**: movimientos `tipo='gasto'`, por categoría.
- **Comisiones a dueños**: lo facturado que NO es de Rambla (la parte de Pablo/
  Tincho/terceros del reparto). Es un COSTO de Rambla, no ganancia.
- **Ganancia neta**: parte de Rambla − gastos (= facturado − comisiones − gastos).
  NO incluye los cargos a socios (son préstamos al socio, no gastos del negocio →
  no tocan la ganancia).
- **Cargos / pagos de socios del mes**: transferencias entre una caja y la cuenta
  corriente del socio (caja→socio = le cargué/sube deuda; socio→caja = me pagó/baja).
- **Cuenta corriente (al día)**: deudor/acreedor de cada socio.

Devengado y percibido van por separado y rotulados — NUNCA se suman entre sí.
"""

from reportes.cierres import rango_mes, snapshot_de, validar_mes
from reportes.liquidacion import liquidar

from contabilidad.constants import PARTES, SOCIOS_HUMANOS
from contabilidad.queries.pyl import ganancia_neta
from contabilidad.queries.saldos import ingresos_derivados, saldos


def _movimientos_socios_mes(conn, desde: str, hasta: str) -> dict:
    """Por socio humano: lo que Rambla le CARGÓ (caja→socio, sube deuda) y lo que el
    socio PAGÓ/rindió (socio→caja, baja deuda) este mes. Transferencias no anuladas."""
    ph = ", ".join("%s" for _ in SOCIOS_HUMANOS)
    rows = conn.execute(
        f"""
        SELECT cd.socio AS cargo_socio, co.socio AS pago_socio, m.monto
        FROM movimientos m
        LEFT JOIN cuentas co ON co.id = m.cuenta_origen_id
        LEFT JOIN cuentas cd ON cd.id = m.cuenta_destino_id
        WHERE m.tipo = 'transferencia' AND NOT m.anulado
          AND m.fecha BETWEEN %s::date AND %s::date
          AND (cd.socio IN ({ph}) OR co.socio IN ({ph}))
        """,
        (desde, hasta, *SOCIOS_HUMANOS, *SOCIOS_HUMANOS),
    ).fetchall()
    cargos = {s: 0 for s in SOCIOS_HUMANOS}
    pagos = {s: 0 for s in SOCIOS_HUMANOS}
    for r in rows:
        monto = int(r["monto"] or 0)
        destino_socio = r["cargo_socio"]  # caja real → socio = Rambla le cargó
        origen_socio = r["pago_socio"]    # socio → caja real = el socio pagó/rindió
        # Una transferencia socio↔socio es un arreglo interno, NO un cargo/pago de
        # Rambla: no entra en estas columnas (su efecto ya está en la cuenta corriente).
        if origen_socio in SOCIOS_HUMANOS and destino_socio in SOCIOS_HUMANOS:
            continue
        if destino_socio in SOCIOS_HUMANOS:
            cargos[destino_socio] += monto
        if origen_socio in SOCIOS_HUMANOS:
            pagos[origen_socio] += monto
    return {
        "cargos": cargos,
        "pagos": pagos,
        "cargos_total": sum(cargos.values()),
        "pagos_total": sum(pagos.values()),
    }


def reporte_mensual(conn, mes: str) -> dict:
    """El reporte completo del mes de Rambla. Compone liquidación + cobros + gastos
    + ganancia + cargos de socios + cuenta corriente. Si el mes está cerrado, el
    devengado sale de la foto congelada."""
    validar_mes(mes)
    desde, hasta = rango_mes(mes)

    # Devengado del mes (foto si está cerrado).
    snap = snapshot_de(conn, mes)
    liq = snap if snap is not None else liquidar(conn, desde, hasta)
    por_benef = liq["resumen"]["por_beneficiario"]
    devengado = {
        "total": int(liq["resumen"]["total"]),
        "pedidos": int(liq["resumen"]["pedidos"]),
        "por_socio": {p: int(por_benef.get(p, 0)) for p in PARTES},
    }

    # Percibido del mes (cobros por cobrador, mismo clean start que el devengado).
    cob = ingresos_derivados(conn, desde, hasta)
    cobrado = {p: int(cob.get(p, 0)) for p in PARTES}

    # Gastos + ganancia. La ganancia es la PARTE DE RAMBLA − gastos: la comisión
    # de los dueños es un costo, no ganancia. No incluye cargos a socios.
    gan = ganancia_neta(conn, mes)

    return {
        "mes": mes,
        "desde": desde,
        "hasta": hasta,
        "cerrado": snap is not None,
        "devengado": devengado,
        "cobrado": {"por_socio": cobrado, "total": sum(cobrado.values())},
        "gastos": {"total": int(gan["gastos"]), "por_categoria": gan["gastos_por_categoria"]},
        "comisiones_duenos": int(gan["comisiones_duenos"]),
        "parte_estudio": int(gan["parte_estudio"]),
        "ganancia_neta": int(gan["ganancia_neta"]),
        "socios_mes": _movimientos_socios_mes(conn, desde, hasta),
        "cuenta_corriente": saldos(conn)["socios"],
    }
