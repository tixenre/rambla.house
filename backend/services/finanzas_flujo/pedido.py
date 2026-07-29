"""El desglose de plata de un pedido — cuánto sale, línea por línea.

OWNA: nada nuevo, delega en `services.precios.calcular_total`/`jornadas_periodo`.
Fixea el bug de `cobro_modo` (auditoría cruzada de plata, 2026-07-02): antes,
`routes/alquileres/core.py::_enriquecer_pedido_con_total` armaba los ítems para
`calcular_total` SIN pasarle `cobro_modo` — una línea 'fijo' (ej. flete, #805)
se multiplicaba igual por jornadas al mostrar/facturar, aunque `bruto_linea` ya
sabía manejarlo bien. Ahora hay un solo punto que arma el desglose para los 6
consumidores reales: detalle admin, PDF/mail, portal cliente, y el motor de
facturación (`services/facturacion/engine.py`).
"""
from database import to_datetime
from services.precios import IVA_PCT, calcular_total, jornadas_periodo


def desglose_de_pedido(conn, pedido: dict) -> dict:
    """Agrega al pedido el desglose canónico del total + IVA derivado (mutación
    in-place; retorna el mismo dict por conveniencia de los callers).

    Fuente de verdad: `services.precios.calcular_total`. `monto_total`
    persistido sigue siendo NETO (con descuento, sin IVA) — acá se computa
    el desglose para mostrar/facturar, nunca se sobreescribe esa columna.

    Jerarquía de descuento (Fase C-1, #1219): `pedido["descuento_pct"]` es el
    override MANUAL (0 = sin override); `pedido["descuento_cliente_pct"]` es el
    SNAPSHOT del descuento del cliente al último recálculo (persistido por
    `_recalcular_total_pedido`/`_apply_pedido_items`, NO se re-consulta en vivo
    acá) — leerlo en vivo divergiría de `monto_total` ya persistido para un
    pedido confirmado cuyo cliente cambió de descuento después (bug clase
    #405). `perfil_impuestos` sí se resuelve en vivo si falta (comportamiento
    preexistente, sin cambios). Expone `descuento_efectivo_pct`/
    `descuento_origen` (el % y la fuente que GANARON) para que los consumidores
    de display (mail/PDF) dejen de leer el campo crudo `descuento_pct` como si
    fuera el % aplicado — misma ambigüedad que causó el bug #1209 en otro lugar.

    Override en % o en $ fijo (Fase C-2, #1219): `pedido["descuento_manual_tipo"]`
    ("pct"/"monto") + `pedido["descuento_manual_monto"]` son columnas directas
    del pedido (no un snapshot aparte — el override ES el valor persistido,
    igual que `descuento_pct`), leídas tal cual están en la fila.

    Combos no acumulables (Fase C-3, #1219): `es_combo` por línea sale de
    `equipo_tipo` EN VIVO (join con `equipos.tipo` al armar `pedido["items"]`,
    ver `_get_alquiler_items`/`_batch_get_alquiler_items`), NO de un snapshot
    por línea. Limitación aceptada (hallazgo del supervisor, PR #1220): si un
    equipo se reclasifica de `combo` a `simple` (o viceversa) DESPUÉS de que
    un pedido confirmado lo usó, el desglose de ESE pedido puede moverse. Muy
    baja probabilidad (reclasificar el tipo de un equipo es una acción manual
    rara del catálogo, no un flujo de uso normal) — se acepta sin snapshot
    dedicado; si algún día se materializa, agregar `es_combo` congelado a
    `alquiler_items` sería la solución, mismo patrón que `descuento_cliente_pct`.
    """
    perfil = pedido.get("cliente_perfil_impuestos")
    if perfil is None and pedido.get("cliente_id"):
        # #1240: si el pedido eligió una productora o un perfil personal alternativo
        # (`productora_id`/`perfil_fiscal_id`, columnas reales de `alquileres`), ese
        # target gana sobre el perfil default de `clientes` — mismo criterio que
        # `services.pedidos_enriquecimiento._resolver_datos_fiscales_pedido`.
        from services.pedidos_enriquecimiento import _resolver_datos_fiscales_pedido

        c = _resolver_datos_fiscales_pedido(
            conn,
            pedido["cliente_id"],
            pedido.get("perfil_fiscal_id"),
            pedido.get("productora_id"),
        )
        if c:
            perfil = c.get("perfil_impuestos")
            pedido["cliente_perfil_impuestos"] = perfil

    descuento_cliente_pct = pedido.get("descuento_cliente_pct") or 0.0

    d0 = to_datetime(pedido["fecha_desde"]) if pedido.get("fecha_desde") else None
    d1 = to_datetime(pedido["fecha_hasta"]) if pedido.get("fecha_hasta") else None
    jornadas = jornadas_periodo(d0, d1)

    items_para_total = [
        {
            "equipo_id": it["equipo_id"],
            "cantidad": it["cantidad"],
            "precio_jornada": it["precio_jornada"],
            "cobro_modo": it.get("cobro_modo") or "jornada",
            # Fase C-3 (#1219): no acumula el descuento global — ya trae el
            # suyo propio (`kit_componentes.descuento_pct`) horneado en el precio.
            "es_combo": it.get("equipo_tipo") == "combo",
        }
        for it in pedido.get("items", [])
    ]

    descuento_jornadas_pct = pedido.get("descuento_jornadas_pct") or 0
    descuento_manual_pct = pedido.get("descuento_pct") or 0
    descuento_manual_tipo = pedido.get("descuento_manual_tipo") or "pct"
    descuento_manual_monto = pedido.get("descuento_manual_monto") or 0
    desglose = calcular_total(
        items=items_para_total,
        jornadas=jornadas,
        descuento_cliente_pct=descuento_cliente_pct,
        descuento_jornadas_pct=descuento_jornadas_pct,
        descuento_manual_pct=descuento_manual_pct,
        descuento_manual_tipo=descuento_manual_tipo,
        descuento_manual_monto=descuento_manual_monto,
        perfil_impuestos=perfil,
    )

    pedido["bruto"] = desglose["bruto"]
    pedido["descuento_monto"] = desglose["descuento_monto"]
    pedido["monto_neto"] = desglose["neto"]
    pedido["iva_pct"] = desglose["iva_pct"]
    pedido["iva_monto"] = desglose["iva_monto"]
    pedido["total_con_iva"] = desglose["total_final"]
    pedido["con_iva"] = desglose["con_iva"]
    pedido["cantidad_jornadas"] = jornadas
    pedido["descuento_efectivo_pct"] = desglose["descuento_pct"]
    from descuentos.queries.decision import resolver_origen_pedido_monto
    pedido["descuento_origen"] = resolver_origen_pedido_monto(
        descuento_manual_tipo, descuento_manual_pct, descuento_manual_monto,
        descuento_cliente_pct, descuento_jornadas_pct,
    )
    return pedido


def combinar_turnos_vinculados(conn, pedido: dict, *, expandir_periodo: bool = False) -> dict:
    """Suma al desglose del pedido la plata de sus turnos del Estudio vinculados
    (`pedido_principal_id`, #1308) — mutación in-place, se corre DESPUÉS de
    `desglose_de_pedido`. Un pedido de alquiler y su turno del Estudio son UNA
    sola venta de cara al cliente ("cobrar una sola cosa y facturar", pedido del
    dueño): esta función es la que hace que un consumidor pueda preguntar "cuánto
    sale TODO este pedido" sin saber que por debajo son dos filas.

    **Opt-in, nunca default.** `desglose_de_pedido` sigue siendo por-fila a
    propósito: el chequeo `desglose_divergente` (`reportes/reconciliacion.py`)
    valida fila por fila que `desglose(items) == monto_total`, así que un
    desglose combinado por default marcaría divergente a todo principal con
    turnos → mail diario al dueño. Hoy el único consumidor es el motor de
    facturación (`services/facturacion/engine.py::_get_pedido`).

    **Suma totales YA congelados, no mergea ítems.** Meter los ítems del turno
    en `pedido["items"]` y recalcular haría que los descuentos del principal
    (cliente/jornadas/manual) se apliquen sobre la tarifa negociada del Estudio
    — plata cambiada en silencio. Mismo criterio que el pago combinado
    (`routes/alquileres/pagos.py::_agregar_pago_combinado`) y que
    `frontend/src/lib/pedido-combinado.ts`: se suman `monto_total`/`monto_pagado`
    persistidos, nada se recotiza.

    **NO toca la base** — `alquileres.monto_total` de cada fila queda intacto
    (cada fila conserva su plata: de eso dependen la liquidación, la economía del
    Estudio y la reconciliación). La combinación es de LECTURA.

    Filtro de turnos: `estado <> 'cancelado'`, byte-idéntico al del pago
    combinado — así lo facturado y lo cobrado cierran entre sí.

    `expandir_periodo=True` estira además `fecha_desde`/`fecha_hasta` para
    cubrir la franja de los turnos. Es SOLO para el comprobante fiscal (que
    declara el período de servicio de todo lo que factura); en una pantalla
    las fechas del alquiler tienen que seguir siendo las del alquiler — la
    franja del Estudio se muestra aparte, no estirando el rango de días.
    """
    if pedido.get("pedido_principal_id") is not None:
        # Es un turno: nunca puede ser principal de otro (`_resolver_pedido_principal`
        # exige `tipo='diaria'`), así que no hay nada que combinar ni recursión posible.
        return pedido

    turnos = conn.execute(
        "SELECT id, numero_pedido, fecha_desde, fecha_hasta, monto_total, monto_pagado "
        "FROM alquileres WHERE pedido_principal_id = %s AND estado <> 'cancelado' "
        "ORDER BY fecha_desde, id",
        (pedido["id"],),
    ).fetchall()
    if not turnos:
        return pedido

    extra_total = sum(t["monto_total"] or 0 for t in turnos)
    extra_pagado = sum(t["monto_pagado"] or 0 for t in turnos)

    # El turno no lleva descuento propio (su tarifa ya es la negociada), así que
    # su aporte entra igual al bruto y al neto — `bruto - descuento == neto` se
    # mantiene coherente para cualquier consumidor de display.
    pedido["bruto"] = (pedido.get("bruto") or 0) + extra_total
    pedido["monto_total"] = (pedido.get("monto_total") or 0) + extra_total
    pedido["monto_neto"] = pedido["monto_total"]
    pedido["monto_pagado"] = (pedido.get("monto_pagado") or 0) + extra_pagado

    # IVA recalculado sobre el neto COMBINADO con el perfil fiscal del PRINCIPAL:
    # el turno no tiene perfil propio (el INSERT del Estudio no copia
    # `perfil_fiscal_id`/`productora_id`) y un comprobante tiene un solo receptor
    # → una sola alícuota. Misma fórmula que `services.precios.calcular_total`.
    pedido["iva_monto"] = (
        int(round(pedido["monto_total"] * IVA_PCT / 100)) if pedido.get("con_iva") else 0
    )
    pedido["total_con_iva"] = pedido["monto_total"] + pedido["iva_monto"]

    if expandir_periodo:
        # Solo para el comprobante fiscal: el período declarado cubre también la
        # franja del turno, que puede caer fuera del rango de días del alquiler.
        validas_desde = [
            to_datetime(f)
            for f in [pedido.get("fecha_desde"), *(t["fecha_desde"] for t in turnos)]
            if f
        ]
        validas_hasta = [
            to_datetime(f)
            for f in [pedido.get("fecha_hasta"), *(t["fecha_hasta"] for t in turnos)]
            if f
        ]
        if validas_desde:
            pedido["fecha_desde"] = min(validas_desde)
        if validas_hasta:
            pedido["fecha_hasta"] = max(validas_hasta)

    pedido["turnos_combinados"] = [
        {
            "pedido_id": t["id"],
            "fecha_desde": t["fecha_desde"],
            "fecha_hasta": t["fecha_hasta"],
            "monto_total": t["monto_total"] or 0,
        }
        for t in turnos
    ]
    return pedido
