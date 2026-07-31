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

    **Suma totales YA congelados, nunca mergea ítems entre filas.** Cada turno
    resuelve SU PROPIO bruto/descuento con sus propios ítems + su propio
    descuento (mismas columnas que un pedido) — nunca se mete un ítem del
    turno en `pedido["items"]` del principal, que aplicaría los descuentos del
    principal (cliente/jornadas/manual) sobre la tarifa negociada del Estudio
    — plata cambiada en silencio. Mismo criterio que el pago combinado
    (`routes/alquileres/pagos.py::_agregar_pago_combinado`) y que
    `frontend/src/lib/pedido-combinado.ts`: se suman los RESULTADOS
    (`monto_total`/`monto_pagado`/`bruto`/`descuento_monto`) ya persistidos o
    resueltos por fila, nada se recotiza cruzando filas.

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

    turnos_rows = conn.execute(
        "SELECT * FROM alquileres WHERE pedido_principal_id = %s AND estado <> 'cancelado' "
        "ORDER BY fecha_desde, id",
        (pedido["id"],),
    ).fetchall()
    if not turnos_rows:
        return pedido

    from database import row_to_dict
    from services.pedidos_enriquecimiento import _batch_get_alquiler_items

    turnos = [row_to_dict(t) for t in turnos_rows]
    items_map = _batch_get_alquiler_items(conn, [t["id"] for t in turnos])

    extra_total = sum(t["monto_total"] or 0 for t in turnos)
    extra_pagado = sum(t["monto_pagado"] or 0 for t in turnos)

    # Un turno puede tener SU PROPIO descuento (mismas columnas que un pedido —
    # sesión de "descuento por sección" del rail, posterior a cuando se escribió
    # el supuesto de abajo). "El turno no lleva descuento propio" ya no es
    # cierto: sumar directo su `monto_total` (ya neto) al `bruto` del principal
    # dejaba `bruto - descuento_monto != monto_total` para el combinado —
    # inconsistente para cualquier consumidor de display, aunque hoy ninguno
    # lea esos dos campos combinados (dormant, no explotado). Se resuelve el
    # bruto/descuento de CADA turno con la misma `desglose_de_pedido` que el
    # principal — una sola forma de calcular esos números para cualquier fila
    # de `alquileres`, sea principal o turno. Se le pasa un perfil sentinel
    # (nunca None) para no disparar la resolución fiscal en vivo por turno:
    # bruto/descuento_monto no dependen del perfil impositivo (solo iva_monto/
    # con_iva, que este combinado ya recalcula aparte más abajo).
    for t in turnos:
        t["items"] = items_map.get(t["id"], [])
        t["cliente_perfil_impuestos"] = pedido.get("cliente_perfil_impuestos") or "consumidor_final"
        desglose_de_pedido(conn, t)
    extra_bruto = sum(t["bruto"] for t in turnos)
    extra_descuento = sum(t["descuento_monto"] for t in turnos)

    pedido["bruto"] = (pedido.get("bruto") or 0) + extra_bruto
    pedido["descuento_monto"] = (pedido.get("descuento_monto") or 0) + extra_descuento
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


def expandir_periodo_turnos_embebidos(conn, pedido: dict) -> dict:
    """Estira `fecha_desde`/`fecha_hasta` del pedido para cubrir también la
    franja de sus turnos del Estudio EMBEBIDOS (`alquiler_turnos_estudio`,
    #1308 rediseño "turno como ítem") — mutación in-place, mismo propósito y
    mismo patrón min/max que `combinar_turnos_vinculados(expandir_periodo=
    True)` de acá arriba, pero para el mecanismo NUEVO.

    **No hay nada que sumar en plata acá** (a diferencia de la hermana de
    arriba): un turno embebido no es una fila `alquileres` aparte con su
    propio `monto_total` — es un GRUPO de `alquiler_items` del MISMO pedido,
    así que `desglose_de_pedido` ya lo incluyó al iterar `pedido["items"]`
    (aislado del descuento automático desde la Fase 3.1, #1308). Esta función
    solo resuelve la fecha declarada del comprobante.

    Se llama SOLO desde el motor de facturación (`services/facturacion/
    engine.py::_get_pedido`), DESPUÉS de `desglose_de_pedido` — igual que su
    hermana, nunca desde la pantalla del pedido: ahí las fechas tienen que
    seguir siendo las del retiro/devolución de EQUIPOS; la franja de cada
    turno se muestra aparte (`pdf_templates._turno_embebido_label`), no
    estirando el rango de días del documento en pantalla.
    """
    turnos = conn.execute(
        "SELECT fecha_desde, fecha_hasta FROM alquiler_turnos_estudio WHERE pedido_id = %s",
        (pedido["id"],),
    ).fetchall()
    if not turnos:
        return pedido

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
    return pedido
