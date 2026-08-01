"""Reconciliación contable (#809, Fase 6) — semáforo de confianza.

Chequeos de integridad que verifican que la plata del módulo cuadre. Devuelve
`{ok: bool, ...}`; cada chequeo lista lo que encontró. Read-only.
"""

from reportes.liquidacion import LIQUIDACION_INICIO

from contabilidad.constants import COBRADORES


def reconciliar(conn) -> dict:
    from contabilidad.queries.saldos import saldos

    out: dict = {}

    # 1. Cajas con saldo negativo (no debería pasar: algo se cargó de más o falta
    #    un ingreso/aporte). Solo cajas de plata real — una cuenta corriente de socio
    #    SÍ puede ser negativa (acreedor: Rental le debe al socio), no es un error.
    s = saldos(conn)
    negativos = [
        {"cuenta": c["nombre"], "saldo": c["saldo"]} for c in s["cajas"] if c["saldo"] < 0
    ]
    out["saldos_negativos"] = {"cantidad": len(negativos), "cuentas": negativos}

    # 2. Cobros de pedidos dentro del clean start (por fecha del alquiler) sin un
    #    cobrador válido como destinatario → no entran a ninguna caja y rompen la
    #    derivación de ingresos. Mismo recorte que `ingresos_derivados`.
    _ph = ", ".join("%s" for _ in COBRADORES)
    row = conn.execute(
        f"""SELECT COUNT(*) AS n, COALESCE(SUM(ap.monto), 0) AS m
           FROM alquiler_pagos ap
           JOIN alquileres al ON al.id = ap.pedido_id
           WHERE NOT ap.anulado
             AND al.fecha_desde >= %s::date
             AND (ap.destinatario IS NULL OR ap.destinatario NOT IN ({_ph}))""",
        (LIQUIDACION_INICIO, *COBRADORES),
    ).fetchone()
    out["pagos_sin_socio"] = {"cantidad": int(row["n"]), "monto": int(row["m"] or 0)}

    # 3. Movimientos activos que apuntan a una cuenta dada de baja.
    row = conn.execute(
        """SELECT COUNT(*) AS n
           FROM movimientos m
           WHERE m.anulado = FALSE AND (
                 m.cuenta_origen_id IN (SELECT id FROM cuentas WHERE activa = FALSE)
              OR m.cuenta_destino_id IN (SELECT id FROM cuentas WHERE activa = FALSE))"""
    ).fetchone()
    out["movimientos_cuenta_inactiva"] = {"cantidad": int(row["n"])}

    # 4. Devengado que cae en un beneficiario SIN caja donde verse. La posición de
    #    una parte (`calcular_saldos`) es `bruto − su_parte`, y `su_parte` sale del
    #    modelo de comisiones — que es editable desde el back-office. Si el modelo
    #    reparte a un beneficiario que no está en `PARTES` o que no tiene cuenta
    #    activa, esa plata se devenga contra nadie: no aparece en ninguna posición,
    #    no la sugiere la rendición, y nadie se entera. Es el "pendiente conocido"
    #    que quedó anotado al construir el motor (DECISIONES 2026-06-07) y hasta
    #    ahora no tenía red.
    from contabilidad.queries.rendicion import cuenta_de_parte
    from contabilidad.queries.saldos import partes_socios

    huerfanos = [
        {"beneficiario": b, "monto": int(m)}
        for b, m in sorted(partes_socios(conn).items())
        if int(m) != 0 and cuenta_de_parte(conn, b) is None
    ]
    out["devengado_sin_cuenta"] = {
        "cantidad": len(huerfanos),
        "monto": sum(h["monto"] for h in huerfanos),
        "beneficiarios": huerfanos,
    }

    # 5. Las dos lecturas de "quién le debe a quién" tienen que dar el MISMO número.
    #    La cuenta corriente de un socio (`saldos.calcular_saldos`) y su posición
    #    acumulada (`posiciones.calcular_posiciones`) son la misma cantidad con el
    #    signo al revés → `saldo_cc + pendiente` tiene que dar 0. Si no da, hay drift
    #    real entre las dos fórmulas: un socio con dos cuentas, un movimiento contra
    #    una cuenta que no mapea a ninguna parte, o el caso concreto que ya sabemos
    #    que existe — `partes_socios` usa `liquidar` en vivo (ignora los cierres de
    #    mes) y `posiciones` usa `liquidar_rango` (los respeta), así que un mes
    #    cerrado con foto desactualizada las separa. Este chequeo es el que hace
    #    visible esa clase de divergencia, que hasta ahora no tenía red: el semáforo
    #    de saldos negativos corre SOLO sobre cajas y saltea las cuentas corrientes
    #    a propósito.
    from contabilidad.queries.posiciones import posiciones

    pos = posiciones(conn)
    pendiente_por_parte = {p["parte"]: p["pendiente"] for p in pos["partes"]}
    divergentes = []
    for c in s["socios"]:
        pend = pendiente_por_parte.get(c["socio"])
        if pend is None:
            continue
        dif = int(c["saldo"]) + int(pend)
        if dif != 0:
            divergentes.append({
                "parte": c["socio"], "cuenta_corriente": int(c["saldo"]),
                "posicion": int(pend), "diferencia": dif,
            })
    #    INFORMATIVO: no baja el semáforo todavía. Dos motivos concretos, no
    #    prudencia genérica: (a) la divergencia `liquidar` vs `liquidar_rango` es
    #    conocida y esperada mientras las dos fórmulas convivan — ponerla en rojo
    #    desde el día uno sería crying wolf; (b) `liquidar` redondea una vez al
    #    final y `liquidar_rango` redondea por mes antes de sumar, así que puede
    #    haber diferencias de ±1 peso que no son drift real. Pasa a afectar `ok`
    #    cuando las dos lecturas se unifiquen y quede tautológico que coincidan.
    out["cc_vs_posicion_divergente"] = {
        "cantidad": len(divergentes), "partes": divergentes, "informativo": True,
    }
    out["float_sin_saldar"] = pos["float_sin_saldar"]

    # 6. Hereda el semáforo del reporte (pagos marcados sin ledger, sobrepagos),
    #    que afectan los ingresos derivados del módulo.
    try:
        from reportes.reconciliacion import reconciliar as reconciliar_reporte

        rep = reconciliar_reporte(conn)
    except Exception:
        rep = {"ok": True}
    out["reporte"] = {
        "ok": bool(rep.get("ok", True)),
        "pagados_sin_ledger": rep.get("pagados_sin_ledger"),
        "sobrepagados": rep.get("sobrepagados"),
    }

    out["ok"] = (
        not negativos
        and out["pagos_sin_socio"]["cantidad"] == 0
        and out["movimientos_cuenta_inactiva"]["cantidad"] == 0
        and out["devengado_sin_cuenta"]["cantidad"] == 0
        and out["reporte"]["ok"]
    )
    return out
