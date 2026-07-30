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
    rows = conn.execute(f"""
        SELECT pi.*, COALESCE(e.nombre, pi.nombre_libre) AS nombre,
               {MARCA_SUBQUERY},
               e.modelo, e.serie, e.valor_reposicion,
               e.foto_url, e.foto_url_sm, e.foto_url_thumb, e.cantidad AS stock_total,
               e.nombre_publico, e.nombre_publico_largo, e.tipo AS equipo_tipo,
               ef.contenido_incluido_json
        FROM alquiler_items pi
        LEFT JOIN equipos e ON e.id = pi.equipo_id
        LEFT JOIN equipo_fichas ef ON ef.equipo_id = e.id
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
    pedido["historial_modificaciones"] = _get_historial_modificaciones(conn, id)
    pedido["clases_taller"] = (
        _clases_del_taller(conn, pedido["taller_edicion_id"])
        if pedido.get("taller_edicion_id") else []
    )
    pedido["pedido_principal"] = (
        _pedido_principal_liviano(conn, pedido["pedido_principal_id"])
        if pedido.get("pedido_principal_id") else None
    )
    pedido["turnos_estudio_vinculados"] = _turnos_vinculados(conn, id)
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


def _get_historial_modificaciones(conn, pedido_id: int) -> list[dict]:
    """Timeline de cambios solicitados por el cliente sobre el pedido.

    Incluye tanto solicitudes de aprobación como cambios directos
    (autosave en `presupuesto`) — el admin se beneficia de ver todo.
    `cambios_aplicados` puede diferir de `cambios_json` cuando el admin
    aprobó con contrapropuesta.
    """
    rows = conn.execute("""
        SELECT id, mensaje, estado, respuesta, cambios_json, cambios_aplicados,
               tipo, resolved_at, resolved_by, created_at
        FROM solicitudes_modificacion
        WHERE pedido_id = %s
        ORDER BY created_at DESC
    """, (pedido_id,)).fetchall()
    return [row_to_dict(r) for r in rows]
