"""Comandos genéricos del ciclo de vida de un pedido — Fase 2 del split
CQRS-lite de `routes/alquileres/` (#1312).

Move-verbatim: `_maybe_finalizar`/`_next_numero_pedido` venían de
`routes/alquileres/detalle.py` (parecen lectura por su forma — un SELECT, un
`nextval()` — pero mutan: cambian `estado` / avanzan una secuencia). `_delete_pedido`
venía de `routes/alquileres/pedidos.py`, donde era SQL inline sin helper propio —
se extrae acá SIN agregarle ningún gate nuevo: la decisión de si "Eliminar
pedido" necesita bloquear contra `monto_pagado`/stock real sigue abierta
(issue #1311, charla aparte); esta fase solo le da un lugar limpio.
"""
from fastapi import HTTPException


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


def _delete_pedido(conn, id: int) -> None:
    """Lógica de `delete_pedido`, sin FastAPI/decorators — testable directo
    (sin necesitar un `Request` real), mismo patrón que `_agregar_pago`. El
    caller (el endpoint) hace commit/rollback.

    `FOR UPDATE` en ambos SELECT: sin esto, un pago concurrente
    (`_agregar_pago`/`_agregar_pago_combinado`, que sí toman el lock) podía
    commitear ENTRE este chequeo de "sin plata cobrada" y los DELETE de abajo
    — el 409 nunca disparaba y la plata recién cobrada desaparecía en
    silencio junto con la fila. Con el lock, cualquier pago en vuelo sobre
    estas filas bloquea acá hasta commitear/abortar, y este SELECT ve su
    resultado ya definitivo."""
    p = conn.execute(
        "SELECT id, pedido_principal_id, monto_pagado FROM alquileres "
        "WHERE id=%s FOR UPDATE", (id,)
    ).fetchone()
    if not p:
        raise HTTPException(404, "Pedido no encontrado")
    # Un turno del Estudio vinculado se saca del pedido con la ✕, y eso
    # lo BORRA (no lo cancela) — igual que sacar un equipo (#1308). Pero
    # el pago combinado escribe las filas de `alquiler_pagos` con el
    # `pedido_id` del turno, así que borrarlo con plata encima haría
    # desaparecer un cobro real de los libros. Ahí se frena: primero se
    # anula el pago. (Guard SOLO para turnos vinculados — el borrado de
    # un pedido normal no cambia.)
    if p["pedido_principal_id"] and (p["monto_pagado"] or 0) > 0:
        raise HTTPException(
            409,
            "Este turno ya tiene plata cobrada. Anulá el pago antes de sacarlo del pedido.",
        )
    # Los turnos del Estudio vinculados se van CON el pedido (#1308). La
    # FK es `ON DELETE SET NULL`, así que sin esto el turno sobrevivía
    # solo, con su propio número y su propio estado → volvía a aparecer
    # en la lista como un pedido más: el "doble pedido fantasma" que toda
    # esta iniciativa vino a matar (el dueño lo reportó viendo uno con
    # número y otro sin, después de borrar el pedido que los unía).
    # Un turno vinculado no es una venta aparte: es contenido del pedido,
    # como un ítem — si se borra el pedido, se borra su contenido.
    turnos = conn.execute(
        "SELECT id, numero_pedido, monto_pagado FROM alquileres "
        "WHERE pedido_principal_id = %s FOR UPDATE",
        (id,),
    ).fetchall()
    # Misma línea roja que la ✕ de un turno suelto: la plata cobrada no
    # se borra en silencio. Si algún turno tiene cobros, se frena TODO el
    # borrado (no se borra el pedido a medias).
    if any((t["monto_pagado"] or 0) > 0 for t in turnos):
        raise HTTPException(
            409,
            "El turno del Estudio de este pedido ya tiene plata cobrada. "
            "Anulá el pago antes de borrar el pedido.",
        )
    for t in turnos:
        conn.execute("DELETE FROM alquiler_items WHERE pedido_id=%s", (t["id"],))
        conn.execute("DELETE FROM alquiler_pagos WHERE pedido_id=%s", (t["id"],))
        conn.execute("DELETE FROM alquileres     WHERE id=%s", (t["id"],))
    # Borrar ítems, pagos e historicos asociados (FK cascade si está activada, pero por las dudas)
    conn.execute("DELETE FROM alquiler_items  WHERE pedido_id=%s", (id,))
    conn.execute("DELETE FROM alquiler_pagos  WHERE pedido_id=%s", (id,))
    conn.execute("DELETE FROM alquileres       WHERE id=%s",        (id,))
