"""routes/alquileres/detalle.py — lectura del detalle de un pedido (split de `core.py`).

Las lecturas (`_get_alquiler_detail` + sus piezas) se movieron a
`services.alquileres.queries.detalle` (#1312, Fase 1) — re-exportadas acá TAL
CUAL para no romper `core.py`/`transiciones.py`/tests, que importan de este
módulo directo. `_maybe_finalizar`/`_next_numero_pedido` se quedan acá: parecen
lectura pero mutan (avanzan la secuencia / cambian estado) — van a
`services.alquileres.commands` en la Fase 2.
"""
from services.alquileres.queries.detalle import (
    _clases_del_taller,  # noqa: F401 — re-export, ver docstring arriba
    _enriquecer_pedido_con_total,  # noqa: F401 — re-export, ver docstring arriba
    _es_historico,  # noqa: F401 — re-export, ver docstring arriba
    _get_alquiler_detail,  # noqa: F401 — re-export, ver docstring arriba
    _get_alquiler_items,  # noqa: F401 — re-export, ver docstring arriba
    _get_alquiler_pagos,  # noqa: F401 — re-export, ver docstring arriba
    _get_historial_modificaciones,  # noqa: F401 — re-export, ver docstring arriba
    _pedido_principal_liviano,  # noqa: F401 — re-export, ver docstring arriba
    _turnos_vinculados,  # noqa: F401 — re-export, ver docstring arriba
)


def _maybe_finalizar(conn, pedido_id: int):
    """Si el pedido está 'devuelto' y monto_pagado >= monto_total → 'finalizado'.

    Turno vinculado: no puede finalizar antes que su principal. Sin este
    chequeo, un pago DIRECTO al turno (`POST /alquileres/{turno_id}/pagos`,
    sin pasar por el pago combinado) que lo completara disparaba este UPDATE
    crudo y lo adelantaba en el flujo — el mismo cap que `cambiar_estado()`
    ya aplica a toda transición MANUAL (`_turno_supera_a_principal`,
    `transiciones.py`), pero este camino de auto-finalizar nunca pasaba por
    ahí. Hoy es inalcanzable desde la UI (la página de un turno redirige al
    principal y las listas lo excluyen), pero el endpoint HTTP en sí no tenía
    ninguna defensa."""
    p = conn.execute(
        "SELECT estado, monto_total, monto_pagado, pedido_principal_id "
        "FROM alquileres WHERE id=%s", (pedido_id,)
    ).fetchone()
    if not p:
        return
    if not (p["estado"] == "devuelto"
            and (p["monto_pagado"] or 0) >= (p["monto_total"] or 0)
            and (p["monto_total"] or 0) > 0):
        return
    if p["pedido_principal_id"] is not None:
        principal = conn.execute(
            "SELECT estado FROM alquileres WHERE id=%s", (p["pedido_principal_id"],)
        ).fetchone()
        if not principal or principal["estado"] != "finalizado":
            return
    conn.execute("UPDATE alquileres SET estado='finalizado' WHERE id=%s", (pedido_id,))


def _next_numero_pedido(conn) -> int:
    """Devuelve el próximo número de pedido usando una SEQUENCE de PostgreSQL (race-free)."""
    return conn.execute("SELECT nextval('numero_pedido_seq')").fetchone()[0]
