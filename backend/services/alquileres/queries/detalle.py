"""Lectura del detalle de un pedido — Fase 1 del split CQRS-lite de
`routes/alquileres/` (#1312).

Move-verbatim desde `routes/alquileres/detalle.py`: el armado del pedido completo
(`_get_alquiler_detail` + sus piezas — ítems con componentes de kit, pagos,
historial, enriquecimiento de cliente/total) y los helpers de lectura chicos.
`_maybe_finalizar`/`_next_numero_pedido` (escriben pese a su forma) se quedan en
`routes/alquileres/detalle.py` — van a `commands/` en la Fase 2.
`routes/alquileres/detalle.py` re-exporta estos nombres tal cual para no romper
los call-sites existentes (`core.py`, `transiciones.py`, tests).
"""
from fastapi import HTTPException

from database import row_to_dict, MARCA_SUBQUERY
from services.contenido import contenido_de_batch
from services.pedidos_enriquecimiento import _enriquecer_pedido_con_cliente
from services.talleres.queries.clases import clases_de_edicion


def _es_historico(fuente: str | None) -> bool:
    """Pedidos historicos (importados) no validan fechas ni stock.

    Soporta `historico` y prefijos tipo `<sistema>-historico` (ej.
    `booqable-historico` que generan los converters de migracion). Asi un
    converter futuro puede usar su propio prefijo sin tocar el backend.
    """
    return bool(fuente) and fuente.endswith("historico")


def _get_alquiler_items(conn, pedido_id: int) -> list[dict]:
    # `ate.fecha_desde/hasta AS turno_fecha_desde/hasta` (#1308 rediseño "turno
    # como ítem"): la PROPIA ventana horaria de un ítem de turno embebido
    # (`pi.turno_estudio_id`, ya viene en `pi.*`) — puede no coincidir con el
    # período del pedido (equipos de un `diaria` mixto). Consumido por
    # `pdf_templates.py::_turno_embebido_label`. LEFT JOIN: NULL para el 100%
    # de los ítems sin turno, para siempre.
    rows = conn.execute(f"""
        SELECT pi.*, COALESCE(e.nombre, pi.nombre_libre) AS nombre,
               {MARCA_SUBQUERY},
               e.modelo, e.serie, e.valor_reposicion,
               e.foto_url, e.foto_url_sm, e.foto_url_thumb, e.cantidad AS stock_total,
               e.nombre_publico, e.nombre_publico_largo, e.tipo AS equipo_tipo,
               ef.contenido_incluido_json,
               ate.fecha_desde AS turno_fecha_desde, ate.fecha_hasta AS turno_fecha_hasta
        FROM alquiler_items pi
        LEFT JOIN equipos e ON e.id = pi.equipo_id
        LEFT JOIN equipo_fichas ef ON ef.equipo_id = e.id
        LEFT JOIN alquiler_turnos_estudio ate ON ate.id = pi.turno_estudio_id
        WHERE pi.pedido_id = %s
        ORDER BY pi.orden, pi.id
    """, (pedido_id,)).fetchall()
    items = [row_to_dict(r) for r in rows]
    if not items:
        return items

    # Componentes de kits vía la puerta única `services.contenido` (antes: SQL
    # inline contra `kit_componentes` acá mismo — excepción documentada en
    # `test_contenido_sql_safety.py`, migrada ahora). `solo_activos=False`:
    # el detalle de un pedido ya hecho muestra TODOS los componentes que la
    # receta referencia, incluso uno retirado después (mismo criterio que
    # `documentos.py::_add_componentes`, ya en la puerta) — no el catálogo/
    # ficha, que sí oculta lo retirado. Las líneas personalizadas (#805) no
    # tienen equipo → se excluyen del batch (equipo_id None).
    equipo_ids = list({item["equipo_id"] for item in items if item["equipo_id"] is not None})
    for item in items:
        item.setdefault("componentes", [])
    if not equipo_ids:
        return items
    componentes_por_equipo = contenido_de_batch(conn, equipo_ids, solo_activos=False)
    for item in items:
        item["componentes"] = componentes_por_equipo.get(item["equipo_id"], [])

    return items


def _get_alquiler_pagos(conn, pedido_id: int) -> list[dict]:
    rows = conn.execute("""
        SELECT * FROM alquiler_pagos WHERE pedido_id = %s ORDER BY fecha, created_at
    """, (pedido_id,)).fetchall()
    return [row_to_dict(r) for r in rows]


def _get_alquiler_detail(conn, id: int) -> dict:
    row = conn.execute("SELECT * FROM alquileres WHERE id=%s", (id,)).fetchone()
    if not row:
        raise HTTPException(404, "Pedido no encontrado")
    pedido = row_to_dict(row)
    pedido["items"] = _get_alquiler_items(conn, id)
    pedido["pagos"] = _get_alquiler_pagos(conn, id)
    pedido["clases_taller"] = (
        _clases_del_taller(conn, pedido["taller_edicion_id"])
        if pedido.get("taller_edicion_id") else []
    )
    pedido["pedido_principal"] = (
        _pedido_principal_liviano(conn, pedido["pedido_principal_id"])
        if pedido.get("pedido_principal_id") else None
    )
    pedido["turnos_estudio_vinculados"] = _turnos_vinculados(conn, id)
    # Turnos EMBEBIDOS (#1308 rediseño "turno como ítem", Fase 4) — a
    # diferencia de los vinculados (arriba, fila `alquileres` aparte), sus
    # ítems YA están en `pedido["items"]` (con `turno_estudio_id`) — este
    # array es SOLO metadata de agrupación (fecha/hora propia + descuento
    # propio) para que el front pueda listar "Turnos del Estudio" de este
    # pedido sin tener que reagrupar `items` a mano.
    pedido["turnos_estudio_embebidos"] = _turnos_embebidos(conn, id)
    # ¿Tiene contenido real (ítems O un turno vinculado activo)? Fuente única
    # (`_pedido_tiene_contenido`) que el front consume en vez de mirar solo
    # `items.length` — un pedido "2 horas de estudio y nada más" SÍ tiene
    # contenido (#1313/#1314-adjacent). Un turno EMBEBIDO no necesita entrar
    # acá aparte: sus ítems ya cuentan en `pedido["items"]`.
    pedido["tiene_contenido"] = _pedido_tiene_contenido(
        pedido["items"],
        any(t["estado"] != "cancelado" for t in pedido["turnos_estudio_vinculados"]),
    )
    pedido["saldo_pendiente"] = _tiene_saldo_pendiente(pedido["monto_total"], pedido["monto_pagado"])
    _enriquecer_pedido_con_cliente(conn, pedido)
    _enriquecer_pedido_con_total(conn, pedido)
    return pedido


def _pedido_principal_liviano(conn, pedido_principal_id: int) -> dict | None:
    """Breadcrumb de vuelta para un turno del Estudio vinculado (#1308): el
    pedido de alquiler normal del que "cuelga". `None` si se borró (el link
    es `ON DELETE SET NULL`, no debería pasar, pero no reventar si pasa)."""
    row = conn.execute(
        "SELECT id, numero_pedido, cliente_nombre FROM alquileres WHERE id = %s",
        (pedido_principal_id,),
    ).fetchone()
    return row_to_dict(row) if row else None


def _tiene_turno_estudio_activo(conn, pedido_id: int) -> bool:
    """¿`pedido_id` tiene al menos un turno del Estudio activo, **por
    CUALQUIERA de los dos mecanismos**? Fuente ÚNICA de esta pregunta — antes
    se respondía con la MISMA query inline en 3 lugares
    (`_puede_quedar_sin_items` en `commands/items.py`, y las dos gates de
    `cambiar_estado` en `commands/transiciones.py`, que directamente no la
    respondían y solo miraban `alquiler_items` — el hallazgo real: un pedido
    "2 horas de estudio y nada más" no podía salir de `borrador` porque esas
    dos gates nunca contemplaban el turno, #1313/#1314-adjacent).

    Los DOS mecanismos, porque conviven:

    1. **VINCULADO** (el viejo): una fila `alquileres` aparte apuntando acá con
       `pedido_principal_id`. Tiene `estado` propio → un turno cancelado ya no
       es contenido.
    2. **EMBEBIDO** (#1308 Fase 4, el actual): una fila
       `alquiler_turnos_estudio` + sus `alquiler_items`. No tiene `estado`
       —sacarlo es un DELETE con cascade— así que existir ES estar activo.

    El (2) faltaba (bug real, encontrado arreglando las fechas derivadas del
    pedido #454): el rediseño de la Fase 4 movió el mecanismo por default a
    embebido pero no arrastró este helper, así que `_puede_quedar_sin_items`
    rechazaba con "Debe tener al menos un ítem" al admin que sacaba el último
    equipo de un pedido cuyo contenido real era un turno embebido. (Las dos
    gates de `cambiar_estado` no llegaban a romperse por esto: su `tiene_items`
    consulta `alquiler_items` SIN filtrar `turno_estudio_id`, así que los ítems
    del turno embebido ya las satisfacían — igual pasan por acá ahora, que
    responde la pregunta de verdad en vez de depender de esa coincidencia.)
    """
    vinculado = conn.execute(
        "SELECT 1 FROM alquileres WHERE pedido_principal_id = %s AND estado <> 'cancelado' LIMIT 1",
        (pedido_id,),
    ).fetchone()
    if vinculado:
        return True
    return bool(conn.execute(
        "SELECT 1 FROM alquiler_turnos_estudio WHERE pedido_id = %s LIMIT 1",
        (pedido_id,),
    ).fetchone())


def _pedido_tiene_contenido(items: list, turnos_vinculados_activos: int | bool) -> bool:
    """¿Este pedido tiene contenido real — al menos un ítem de alquiler O un
    turno del Estudio vinculado activo? Pura (sin DB): el caller ya trae
    ambos datos (batch en la lista, ya cargados en el detalle) — evita una
    query extra. Fuente ÚNICA de "qué cuenta como contenido de un pedido",
    consumida tanto por el backend (gates de `cambiar_estado`,
    `_puede_quedar_sin_items`) como expuesta al front (`tiene_contenido` en
    la respuesta) para que el front deje de adivinarlo mirando solo
    `items.length` (hallazgo de auditoría, #1313/#1314)."""
    return bool(items) or bool(turnos_vinculados_activos)


def _tiene_saldo_pendiente(monto_total: int | None, monto_pagado: int | None) -> bool:
    """¿Este pedido todavía tiene plata por cobrar? Pura (sin DB) — mismo
    criterio que `_maybe_finalizar` (commands/pedido.py): un pedido
    `monto_total=0` (comp/cortesía) nunca tiene saldo pendiente, sea cual sea
    `monto_pagado`. Fuente ÚNICA de "¿está pago?", consumida tanto por el
    gate de `cambiar_estado` (bloquea `finalizado` manual con saldo) como
    expuesta al front (`saldo_pendiente`) para que el botón "Finalizar" deje
    de ofrecerse como si fuera gratis (hallazgo del dueño, 2026-07-30: un
    pedido con $120.000 sin cobrar ofrecía "Cobrar saldo y finalizar" sin que
    nada impidiera finalizarlo sin cobrar)."""
    total = monto_total or 0
    return total > 0 and (monto_pagado or 0) < total


def _turnos_vinculados(conn, pedido_id: int) -> list[dict]:
    """Turnos del Estudio vinculados a este pedido (#1308) — mismo shape
    liviano que `services.talleres` usa para "pedidos generados" de una
    edición (`PedidoGeneradoEdicion` en el front), más sus propios `pagos`.

    El pago combinado (`_agregar_pago_combinado`) reparte filas REALES de
    `alquiler_pagos` con el `pedido_id` del turno — sin traerlas acá, esa
    plata quedaba invisible y sin forma de anularse desde la página del
    pedido principal (la única que el admin abre; el turno no tiene página
    propia). Turnos son 0-2 por pedido en la práctica — un `_get_alquiler_pagos`
    por turno no vale la pena batchear."""
    rows = conn.execute(
        """
        SELECT id, numero_pedido, estado, fecha_desde, fecha_hasta,
               monto_total, monto_pagado
        FROM alquileres
        WHERE pedido_principal_id = %s
        ORDER BY fecha_desde
        """,
        (pedido_id,),
    ).fetchall()
    turnos = [row_to_dict(r) for r in rows]
    for t in turnos:
        t["pagos"] = _get_alquiler_pagos(conn, t["id"])
    return turnos


def _turnos_embebidos(conn, pedido_id: int) -> list[dict]:
    """Turnos del Estudio EMBEBIDOS en este pedido (#1308 rediseño "turno
    como ítem", Fase 4) — mismo propósito liviano que `_turnos_vinculados`
    (mecanismo VIEJO) para que el front pueda listar "Turnos del Estudio" de
    la misma forma sea cual sea el mecanismo de cada pedido.

    Sin `estado`/`monto_pagado`/`pagos` propios (a diferencia de un
    vinculado): un turno embebido NUNCA fue su propia venta — no tiene
    estado ni cobro aparte, vive el del pedido contenedor. `monto_total` acá
    es la suma de SUS `alquiler_items` (no una columna propia en la tabla —
    `alquiler_turnos_estudio` no tiene `monto_total`), informativo para el
    front; la plata real ya está en `pedido["items"]`, este número no se usa
    para calcular nada."""
    rows = conn.execute(
        """
        SELECT ate.id, ate.fecha_desde, ate.fecha_hasta,
               ate.descuento_pct, ate.descuento_manual_tipo, ate.descuento_manual_monto,
               COALESCE((SELECT SUM(subtotal) FROM alquiler_items
                         WHERE turno_estudio_id = ate.id), 0) AS monto_total
        FROM alquiler_turnos_estudio ate
        WHERE ate.pedido_id = %s
        ORDER BY ate.fecha_desde
        """,
        (pedido_id,),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def _clases_del_taller(conn, edicion_id: int) -> list[dict]:
    """Clases reales (fecha + franja horaria) de la edición de taller que
    generó este pedido — la verdad temporal que `_regenerar_pedidos_taller`
    NO pone en `fecha_desde`/`fecha_hasta` (esas son el mes contable
    completo, ver `services/talleres/commands/economia.py`). El front las usa
    para mostrar "sáb 15 · 10:00-14:00" en vez de "N jornadas" (bug real
    #445). Fuente única `services.talleres.queries.clases.clases_de_edicion`
    — mismo dato que ve el admin en Talleres → la edición."""
    return clases_de_edicion(conn, edicion_id)


def _enriquecer_pedido_con_total(conn, pedido: dict) -> dict:
    """Wrapper de compatibilidad — la lógica real vive en
    `services.finanzas_flujo.pedido.desglose_de_pedido` (fuente única del
    desglose de plata de un pedido: bruto/descuento/neto/IVA por línea,
    `cobro_modo`-aware). Código nuevo debería importar de ahí directo; este
    wrapper solo evita tocar los 6 call-sites existentes en la migración
    (auditoría cruzada de plata, 2026-07-02). Cierra #496.
    """
    from services.finanzas_flujo.pedido import desglose_de_pedido
    return desglose_de_pedido(conn, pedido)
