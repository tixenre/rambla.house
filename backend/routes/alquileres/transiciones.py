"""routes/alquileres/transiciones.py — motor único de transición de estado del pedido.

Antes de esto, la lógica de "a qué estado puede pasar un pedido y qué guards
corren" estaba desparramada en 3 lugares (`update_pedido` en `pedidos.py`,
`cliente_cancelar_pedido` en `cliente_portal/pedidos.py`, más el auto-finalizar
en `detalle.py`/`pagos.py`) — cada uno con su propia validación parcial, sin
una tabla explícita de qué transiciones son legales. `cambiar_estado()` es
ahora la ÚNICA puerta: admin y cliente (portal) pasan por acá.

Diseño (a pedido del dueño, sesión 2026-07-06): `ESTADOS_VALIDOS` =
borrador/solicitado/confirmado/retirado/devuelto/finalizado/cancelado (el
estado inicial se renombró presupuesto→solicitado el 2026-07-15). El admin
puede moverse LIBREMENTE hacia adelante y hacia atrás entre los estados
operativos (necesita poder volver
a corregir un pedido — pasa seguido), con dos excepciones:

1. `finalizado` es "estilo Magento": normalmente se prende SOLO (devuelto +
   pagado completo, vía `_maybe_finalizar` en `detalle.py` — se sigue
   llamando acá al final de cada `cambiar_estado`) y se apaga solo si se
   anula el pago que lo completaba (`pagos.py`). Pero SÍ sigue siendo un
   destino manual válido, un solo paso desde/hacia `devuelto` — es el
   escape hatch real que ya existe (botón "Finalizar" del admin) para un
   pedido con `monto_total=0` (comp/cortesía), que nunca cumple la condición
   de `_maybe_finalizar` y quedaría trabado en `devuelto` para siempre sin
   esto. Esto deja los 7 consumidores de `estado='finalizado'` en
   reportes/liquidación (MEMORIA 2026-07-03) totalmente intactos — la
   columna sigue significando exactamente lo mismo, cero migración de
   queries.
2. Volver a `borrador` está bloqueado si el pedido ya tiene plata cobrada
   (`monto_pagado > 0`) o una factura activa — un pedido con plata/factura
   real no puede retroceder a un estado que ni siquiera exige fechas/ítems.

`cancelado` es alcanzable desde cualquier estado PRE-retirado (para admin Y
cliente) pero es terminal — no hay transición definida hacia afuera. El
cliente (portal) solo puede disparar la transición A `cancelado` — cualquier
otro destino vía `cambiar_estado(es_admin=False)` es 400.
"""
from fastapi import HTTPException

from database import to_datetime
from reservas import validar_stock as _check_stock
from tipos_pedido import es_pedido_estudio

# Estados que reservan stock activamente — entrar a uno de estos desde uno que
# NO reserva exige re-validar stock (ver `_requiere_revalidar_stock`).
ESTADOS_QUE_RESERVAN = {"solicitado", "confirmado", "retirado"}

# Estados que exigen fechas + ítems + stock ya cargados para poder entrar.
# `finalizado` incluido por paridad con el comportamiento de siempre — llega
# solo desde `devuelto` (que ya validó lo mismo), así que es redundante pero
# inofensivo, no un chequeo nuevo.
ESTADOS_REQUIEREN_FECHAS = {"confirmado", "retirado", "devuelto", "finalizado"}

# Grafo de transiciones MANUALES legales (admin salvo que se indique
# "cliente" — ver `_DESTINO_CLIENTE`). `finalizado` solo conecta con
# `devuelto` (un paso, en cualquier dirección) — ver punto 1 del docstring.
# `cancelado` no tiene salida — terminal.
TRANSICIONES: dict[str, set[str]] = {
    "borrador":    {"solicitado", "confirmado", "retirado", "devuelto", "cancelado"},
    "solicitado": {"borrador", "confirmado", "retirado", "devuelto", "cancelado"},
    "confirmado":  {"borrador", "solicitado", "retirado", "devuelto", "cancelado"},
    "retirado":    {"borrador", "solicitado", "confirmado", "devuelto"},
    "devuelto":    {"borrador", "solicitado", "confirmado", "retirado", "finalizado"},
    "finalizado":  {"devuelto"},
    "cancelado":   set(),
}

# Único destino legal para el cliente (portal) — todo lo demás es admin-only.
_DESTINO_CLIENTE = "cancelado"


def _tiene_factura_activa(conn, pedido_id: int) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM facturas WHERE pedido_id=%s AND estado IN ('pendiente','emitida')",
        (pedido_id,),
    ).fetchone())


def _requiere_revalidar_stock(estado_actual: str, estado_nuevo: str) -> bool:
    """Solo hace falta re-validar stock cuando se ENTRA a un estado que
    reserva desde uno que no reservaba — si ya reservaba, el stock del pedido
    ya está contado en la disponibilidad; re-chequear en cada lateral (ej.
    confirmado→retirado) sería redundante."""
    return estado_nuevo in ESTADOS_QUE_RESERVAN and estado_actual not in ESTADOS_QUE_RESERVAN


def _revalidar_stock(conn, p) -> list[str]:
    """Errores de stock/disponibilidad (YA formateados como mensaje) al
    transicionar el pedido `p` a un estado que reserva.

    Pedidos del Estudio (`tipo` en `TIPOS_ESTUDIO`) van por su propio
    revalidador (`routes.estudio.revalidar_disponibilidad_estudio`: espacio
    con SU buffer propio + equipos reales por el motor) — el `_check_stock`
    genérico leería el ítem centinela como un equipo más y lo validaría con
    el buffer GLOBAL, no el propio del espacio (bug encontrado auditando la
    economía del Estudio: confirmar/transicionar un pedido de estudio no
    revalidaba con el buffer correcto).

    Import diferido de `routes.estudio` — ese módulo ya importa de
    `routes.alquileres` (mismo motivo que el resto de los imports diferidos
    de este archivo, ver `cambiar_estado`)."""
    if es_pedido_estudio(p):
        from routes.estudio import revalidar_disponibilidad_estudio
        return revalidar_disponibilidad_estudio(conn, p)
    return [
        f"Sin stock suficiente: {s}"
        for s in _check_stock(conn, p["id"], p["fecha_desde"], p["fecha_hasta"])
    ]


def cambiar_estado(conn, pedido_id: int, estado_nuevo: str, *, es_admin: bool, actor: str) -> dict:
    """Único punto de entrada para mover el `estado` de un pedido.

    No commitea — el caller (el endpoint) hace commit/rollback, igual que
    `_apply_pedido_*`. Devuelve `{"estado_anterior": ..., "estado_nuevo": ...,
    "numero_pedido_asignado": bool}` para que el caller decida side-effects de
    transporte (mandar mail, etc. — esta función no depende de `BackgroundTasks`
    ni de nada específico de FastAPI, para poder llamarse igual desde el
    admin y desde el portal cliente).
    """
    if estado_nuevo not in TRANSICIONES:
        raise HTTPException(400, f"Estado inválido. Usar: {', '.join(sorted(TRANSICIONES))}")

    if not es_admin and estado_nuevo != _DESTINO_CLIENTE:
        raise HTTPException(400, "El cliente solo puede cancelar un pedido, no cambiar a otro estado.")

    p = conn.execute("SELECT * FROM alquileres WHERE id=%s FOR UPDATE", (pedido_id,)).fetchone()
    if not p:
        raise HTTPException(404, "Pedido no encontrado")

    estado_actual = p["estado"]

    if estado_actual != estado_nuevo and estado_nuevo not in TRANSICIONES.get(estado_actual, set()):
        raise HTTPException(
            400,
            f"No se puede pasar de '{estado_actual}' a '{estado_nuevo}'.",
        )

    if estado_nuevo == "borrador" and estado_actual != "borrador":
        if (p["monto_pagado"] or 0) > 0:
            raise HTTPException(400, "No se puede volver a borrador: el pedido ya tiene plata cobrada.")
        if _tiene_factura_activa(conn, pedido_id):
            raise HTTPException(400, "No se puede volver a borrador: el pedido ya tiene una factura activa.")

    fuente_es_historica = bool(p["fuente"]) and p["fuente"].endswith("historico")

    if estado_nuevo in ESTADOS_REQUIEREN_FECHAS and not fuente_es_historica:
        errores = []
        if not p["fecha_desde"] or not p["fecha_hasta"]:
            errores.append("El pedido no tiene fechas de inicio y fin.")
        else:
            try:
                d0 = to_datetime(p["fecha_desde"])
                d1 = to_datetime(p["fecha_hasta"])
                if d0 >= d1:
                    errores.append("fecha_hasta debe ser posterior a fecha_desde")
                # Admin-only más abajo si es_admin=False ya cortó arriba: el
                # admin puede avanzar con fecha de retiro pasada (carga
                # retroactiva), no se rechaza el pasado acá.
            except ValueError:
                errores.append("Las fechas tienen formato inválido")

        if not conn.execute("SELECT 1 FROM alquiler_items WHERE pedido_id=%s", (pedido_id,)).fetchone():
            errores.append("El pedido no tiene equipos cargados.")
        if p["fecha_desde"] and p["fecha_hasta"] and not errores:
            errores.extend(_revalidar_stock(conn, p))
        if errores:
            raise HTTPException(422, {"errores": errores})

    elif (
        _requiere_revalidar_stock(estado_actual, estado_nuevo)
        and not fuente_es_historica
        and p["fecha_desde"] and p["fecha_hasta"]
    ):
        sin_stock = _revalidar_stock(conn, p)
        if sin_stock:
            raise HTTPException(422, {"errores": sin_stock})

    updates: dict = {"estado": estado_nuevo}
    numero_asignado = False
    if estado_nuevo == "confirmado" and not p["numero_pedido"]:
        from routes.alquileres.detalle import _next_numero_pedido
        updates["numero_pedido"] = _next_numero_pedido(conn)
        numero_asignado = True

    set_clause = ", ".join(f"{k}=%s" for k in updates)
    conn.execute(f"UPDATE alquileres SET {set_clause} WHERE id=%s", (*updates.values(), pedido_id))

    # Import diferido — evita el ciclo alquileres↔cliente_portal (mismo
    # workaround que ya usaba `update_pedido`).
    from routes.cliente_portal import ESTADOS_MODIFICABLES, _cancelar_solicitudes_pendientes
    if estado_nuevo not in ESTADOS_MODIFICABLES:
        _cancelar_solicitudes_pendientes(
            conn, pedido_id,
            motivo=f"El pedido pasó a estado '{estado_nuevo}'.",
            actor=actor,
        )

    from routes.alquileres.detalle import _maybe_finalizar
    _maybe_finalizar(conn, pedido_id)

    return {
        "estado_anterior": estado_actual,
        "estado_nuevo": estado_nuevo,
        "numero_pedido_asignado": numero_asignado,
    }
