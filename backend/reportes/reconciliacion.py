"""Reconciliación de datos de liquidación (#88, hardening).

Chequeos de integridad que, si dan todos en cero, garantizan que el reporte de
liquidación es confiable. Pensado para mostrarse como semáforo en el reporte y
para cazar la divergencia entre las dos formas de marcar "pagado":
`alquileres.monto_pagado` (columna) vs `alquiler_pagos` (ledger, fuente de verdad
del reporte).
"""

from .comisiones import cargar_modelo
from .liquidacion import LIQUIDACION_INICIO, SALDADO_CTE

# Tope de ids de muestra a devolver por chequeo (no inundar la UI).
_SAMPLE = 25

# Corte del clean start (ver liquidacion.LIQUIDACION_INICIO): los chequeos de
# integridad solo miran pedidos cuyo alquiler entra en la ventana de liquidación.
# Un pedido pre-junio 2026 ya no afecta al reporte → no debe ensuciar el semáforo.
_CLEAN_START = f"AND a.fecha_desde >= '{LIQUIDACION_INICIO}'"


def _pedidos_para_desglose(conn) -> list[dict]:
    """Pedidos activos (no cancelados, `monto_total > 0`) dentro del clean start,
    con sus ítems — la forma que espera `finanzas_flujo.pedido.desglose_de_pedido`.
    Un solo `IN` para los ítems (no N+1 por pedido).

    Cubre TAMBIÉN los pedidos del Estudio (Fase 2, ítems veraces): sus ítems
    llevan el monto real (`cobro_modo='fijo'`, `subtotal` = precio del espacio/
    promo) en vez de $0, así que `desglose_de_pedido` cierra contra
    `monto_total` igual que un alquiler normal — no hace falta excluirlos.
    Backfill de los pedidos creados ANTES de este cambio: migración
    `q2r3s4t5u6v7_backfill_items_estudio_veraces`."""
    from database import row_to_dict

    rows = conn.execute(
        f"""
        SELECT a.id, a.fecha_desde, a.fecha_hasta, a.monto_total,
               a.descuento_pct, a.descuento_jornadas_pct, a.cliente_id,
               a.descuento_cliente_pct, a.descuento_manual_tipo, a.descuento_manual_monto
        FROM alquileres a
        WHERE a.estado <> 'cancelado'
          AND a.monto_total > 0
          {_CLEAN_START}
        ORDER BY a.id
        """
    ).fetchall()
    pedidos = [row_to_dict(r) for r in rows]
    if not pedidos:
        return []
    ids = tuple(p["id"] for p in pedidos)
    placeholders = ", ".join("%s" for _ in ids)
    items_rows = conn.execute(
        f"""SELECT pi.pedido_id, pi.equipo_id, pi.cantidad, pi.precio_jornada, pi.cobro_modo,
                   e.tipo AS equipo_tipo
            FROM alquiler_items pi
            LEFT JOIN equipos e ON e.id = pi.equipo_id
            WHERE pi.pedido_id IN ({placeholders})""",
        ids,
    ).fetchall()
    items_por_pedido: dict[int, list[dict]] = {}
    for r in items_rows:
        d = row_to_dict(r)
        items_por_pedido.setdefault(d["pedido_id"], []).append(d)
    for p in pedidos:
        p["items"] = items_por_pedido.get(p["id"], [])
    return pedidos


def reconciliar(conn) -> dict:
    """Corre los chequeos de integridad. Devuelve `ok` global + detalle por chequeo
    (cantidad + ids de muestra)."""
    from database import row_to_dict

    # 1. Pagados según la columna pero invisibles para el reporte: el pedido dice
    #    monto_pagado >= monto_total, pero el ledger de pagos no llega al total
    #    (típico del endpoint legacy que setea la columna sin registrar el pago).
    sin_ledger = conn.execute(
        f"""
        SELECT a.id
        FROM alquileres a
        LEFT JOIN (
            SELECT pedido_id, COALESCE(SUM(monto), 0) AS pagado
            FROM alquiler_pagos WHERE NOT anulado GROUP BY pedido_id
        ) p ON p.pedido_id = a.id
        WHERE a.estado <> 'cancelado'
          AND a.monto_total > 0
          AND a.monto_pagado >= a.monto_total
          AND COALESCE(p.pagado, 0) < a.monto_total
          {_CLEAN_START}
        ORDER BY a.id
        """
    ).fetchall()

    # 2. La columna monto_pagado no coincide con la suma del ledger (cache stale o
    #    escritura por fuera del recálculo). NOT anulado: monto_pagado ya excluye
    #    los pagos anulados (_recalcular_monto_pagado, #1184) — la comparación
    #    tiene que usar la misma fuente o cada pago anulado marcaría un falso
    #    divergente.
    divergentes = conn.execute(
        f"""
        SELECT a.id
        FROM alquileres a
        LEFT JOIN (
            SELECT pedido_id, COALESCE(SUM(monto), 0) AS pagado
            FROM alquiler_pagos WHERE NOT anulado GROUP BY pedido_id
        ) p ON p.pedido_id = a.id
        WHERE a.estado <> 'cancelado'
          AND a.monto_pagado <> COALESCE(p.pagado, 0)
          {_CLEAN_START}
        ORDER BY a.id
        """
    ).fetchall()

    # 3. Sobrepagados: se cobró MÁS que el total actual del pedido. Pasa típicamente
    #    al editar un pedido (sacar un ítem) DESPUÉS de cobrarlo: el reporte imputa el
    #    monto_total nuevo (más bajo) y la diferencia cobrada quedaría fuera.
    sobrepagados = conn.execute(
        f"""
        SELECT a.id
        FROM alquileres a
        WHERE a.estado <> 'cancelado'
          AND a.monto_total > 0
          AND a.monto_pagado > a.monto_total
          {_CLEAN_START}
        ORDER BY a.id
        """
    ).fetchall()

    # 4bis. Mes cerrado desactualizado (#721): un pedido saldado dentro de un mes
    #    YA CERRADO recibió actividad DESPUÉS del cierre (se editó el pedido, o
    #    entró/cambió un pago) → la foto inmutable quedó vieja. No es un error: hay
    #    que reabrir el mes y volver a cerrarlo para incorporar el cambio. Si la
    #    tabla de cierres no existe todavía (init_db no corrió), el chequeo es vacío.
    mes_cerrado_pedidos: list[int] = []
    meses_afectados: list[str] = []
    try:
        filas_stale = conn.execute(
            f"""
            WITH {SALDADO_CTE}
            SELECT DISTINCT al.id AS id, c.mes AS mes
            FROM saldado s
            JOIN alquileres al ON al.id = s.pedido_id
            JOIN liquidacion_cierres c
              ON to_char(s.fecha_saldado::date, 'YYYY-MM') = c.mes
            WHERE al.updated_at > c.cerrado_at
               OR EXISTS (
                   SELECT 1 FROM alquiler_pagos ap
                   WHERE ap.pedido_id = al.id
                     AND (ap.created_at > c.cerrado_at
                          OR ap.anulado_at > c.cerrado_at)
               )
            ORDER BY al.id
            """
        ).fetchall()
        for r in filas_stale:
            d = row_to_dict(r)
            mes_cerrado_pedidos.append(d["id"])
            if d["mes"] not in meses_afectados:
                meses_afectados.append(d["mes"])
        meses_afectados.sort()
    except Exception:
        # Tabla inexistente u otro problema de esquema: no romper el semáforo.
        # Un error aborta la transacción en Postgres → rollback para que los
        # chequeos siguientes (cargar_modelo, dueños) puedan seguir consultando.
        try:
            conn.rollback()
        except Exception:
            pass
        mes_cerrado_pedidos = []
        meses_afectados = []

    # 4. Dueños fuera del modelo de comisiones → en el reporte cobrarían como un
    #    "beneficiario" fantasma (100% a sí mismos). Suele ser un typo en equipos.dueno.
    modelo = cargar_modelo(conn)
    canonicos = set(modelo.keys())
    duenos = conn.execute(
        "SELECT DISTINCT COALESCE(dueno, 'Rambla') AS dueno FROM equipos"
    ).fetchall()
    no_canonicos = sorted(
        row_to_dict(d)["dueno"] for d in duenos if row_to_dict(d)["dueno"] not in canonicos
    )

    # 5. Desglose recalculado del pedido (vía la fachada `finanzas_flujo`, con el
    #    precio de LÍNEA persistido de cada ítem — no el de catálogo, mismo
    #    criterio que el fix de #1181) debe coincidir con `monto_total`.
    #    Generaliza el patrón del bug #405: si el módulo de pedidos vuelve a
    #    desincronizarse por cualquier motivo futuro, este chequeo lo caza solo,
    #    sin depender de que el dueño note un reporte puntual (#1184 Fase 2).
    desglose_divergentes: list[int] = []
    try:
        from services.finanzas_flujo.pedido import desglose_de_pedido

        for p in _pedidos_para_desglose(conn):
            d = desglose_de_pedido(conn, p)
            if int(round(d["monto_neto"])) != int(p["monto_total"]):
                desglose_divergentes.append(p["id"])
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        desglose_divergentes = []

    def chk(rows):
        ids = [row_to_dict(r)["id"] for r in rows]
        return {"cantidad": len(ids), "ids": ids[:_SAMPLE]}

    pagados_sin_ledger = chk(sin_ledger)
    monto_pagado_divergente = chk(divergentes)
    sobrepagados_chk = chk(sobrepagados)
    mes_cerrado_stale = {
        "cantidad": len(mes_cerrado_pedidos),
        "ids": mes_cerrado_pedidos[:_SAMPLE],
        "meses": meses_afectados,
    }
    desglose_stale = {
        "cantidad": len(desglose_divergentes),
        "ids": desglose_divergentes[:_SAMPLE],
    }

    ok = (
        pagados_sin_ledger["cantidad"] == 0
        and monto_pagado_divergente["cantidad"] == 0
        and sobrepagados_chk["cantidad"] == 0
        and mes_cerrado_stale["cantidad"] == 0
        and len(no_canonicos) == 0
        and desglose_stale["cantidad"] == 0
    )

    return {
        "ok": ok,
        "pagados_sin_ledger": pagados_sin_ledger,
        "monto_pagado_divergente": monto_pagado_divergente,
        "sobrepagados": sobrepagados_chk,
        "mes_cerrado_desactualizado": mes_cerrado_stale,
        "duenos_no_canonicos": no_canonicos,
        "desglose_divergente": desglose_stale,
    }
