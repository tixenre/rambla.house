"""services/alquileres/commands/transiciones.py — motor único de transición de
estado del pedido. Move-verbatim desde `routes/alquileres/transiciones.py`
(#1312, Fase 4) — `routes/alquileres/transiciones.py` queda como puro
re-export para no romper `pedidos.py`/tests que importan de ese módulo directo.

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
   anula el pago que lo completaba (`pagos.py`). SÍ sigue siendo un destino
   manual válido, un solo paso desde/hacia `devuelto` — es el escape hatch
   real que ya existe (botón "Finalizar" del admin) para un pedido con
   `monto_total=0` (comp/cortesía), que nunca cumple la condición de
   `_maybe_finalizar` y quedaría trabado en `devuelto` para siempre sin
   esto. El escape hatch está GATEADO (`_tiene_saldo_pendiente`, ver más
   abajo): solo puede saltear `_maybe_finalizar` cuando de verdad no hay
   nada por cobrar (`monto_total=0`, o `monto_pagado >= monto_total`) — no
   es una forma de marcar "Finalizado" un pedido real sin cobrarlo (hallazgo
   del dueño, 2026-07-30: el botón "Cobrar saldo y finalizar" lo permitía con
   $120.000 sin cobrar). Esto deja los 7 consumidores de `estado='finalizado'`
   en reportes/liquidación (MEMORIA 2026-07-03) totalmente intactos — la
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
from tipos_pedido import es_pedido_estudio, es_pedido_taller
from services.alquileres.commands.items import _lock_equipos_por_id
from services.alquileres.queries.detalle import _tiene_turno_estudio_activo, _tiene_saldo_pendiente

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

# Secuencia del "camino feliz" — espejo de
# `frontend/src/lib/pedido-estados.ts::FLOW`. Se usa SOLO para la cascada de
# turnos del Estudio vinculados (#1308, "avanzan juntos") — no reemplaza ni
# participa de `TRANSICIONES` (la única fuente de qué transición es legal).
FLOW: tuple[str, ...] = ("solicitado", "confirmado", "retirado", "devuelto", "finalizado")


def _cascada_turnos_vinculados(conn, pedido_id: int, estado_nuevo: str, actor: str) -> list[dict]:
    """`pedido_id` acaba de pasar a `estado_nuevo`: si es uno de los 5 pasos
    de `FLOW`, empuja cada turno del Estudio vinculado (`pedido_principal_id`)
    al MISMO estado — salvo el que ya esté en un paso IGUAL o POSTERIOR (nunca
    retrocede). `cancelado`/`borrador` quedan fuera de la cascada (no están en
    `FLOW`): cancelar/cerrar un turno vinculado sigue siendo manual, y como el
    portal cliente solo puede pedir `cancelado` (`_DESTINO_CLIENTE`), esto
    también implica que la cascada nunca se dispara desde el portal.

    Cada turno pasa por `cambiar_estado()` COMPLETO (mismo `FOR UPDATE`,
    misma revalidación de stock/fechas, mismo `_maybe_finalizar`) — no un
    UPDATE crudo. Si un turno puntual falla, se acumula como advertencia y se
    sigue con el resto — la transición de `pedido_id` (que sí se pidió y sí es
    válida) NUNCA se revierte por esto."""
    if estado_nuevo not in FLOW:
        return []
    idx_destino = FLOW.index(estado_nuevo)
    turnos = conn.execute(
        "SELECT id, numero_pedido, estado FROM alquileres WHERE pedido_principal_id = %s "
        "ORDER BY fecha_desde, id",
        (pedido_id,),
    ).fetchall()
    advertencias = []
    for t in turnos:
        idx_actual = FLOW.index(t["estado"]) if t["estado"] in FLOW else -1
        if idx_actual >= idx_destino:
            continue
        try:
            cambiar_estado(conn, t["id"], estado_nuevo, es_admin=True, actor=actor)
        except HTTPException as e:
            advertencias.append({
                "turno_id": t["id"],
                "numero_pedido": t["numero_pedido"],
                "error": e.detail if isinstance(e.detail, str) else str(e.detail),
            })
    return advertencias


def _turno_supera_a_principal(conn, p, estado_nuevo: str) -> str | None:
    """Un turno vinculado no puede transicionar por su cuenta a un paso de
    `FLOW` más avanzado que el de su pedido principal ACTUAL — mismo criterio
    que el stock de equipos, que no se reserva en firme hasta que el pedido
    confirma (pedido del dueño): si el principal no llegó a `estado_nuevo`,
    el turno tampoco puede. Puede igualar al principal (ej. re-confirmarse
    tras la cascada) pero no superarlo. `cancelado`/`borrador` (fuera de
    `FLOW`) no se gatean acá — siguen siendo manuales e independientes
    (D6, mismo criterio que `_cascada_turnos_vinculados`).

    Devuelve el mensaje de error, o None si la transición es válida."""
    principal_id = p["pedido_principal_id"]
    if principal_id is None or estado_nuevo not in FLOW:
        return None
    principal = conn.execute(
        "SELECT estado FROM alquileres WHERE id=%s", (principal_id,)
    ).fetchone()
    if not principal:
        return None
    idx_destino = FLOW.index(estado_nuevo)
    idx_principal = FLOW.index(principal["estado"]) if principal["estado"] in FLOW else -1
    if idx_destino > idx_principal:
        return (
            f"El turno no puede pasar a '{estado_nuevo}' antes que su pedido "
            f"principal (que sigue en '{principal['estado']}')."
        )
    return None


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
    transicionar el pedido `p` a un estado que reserva. Solo se llama cuando
    `p["fecha_desde"]`/`p["fecha_hasta"]` están cargadas (ver `cambiar_estado`)
    — para un pedido DERIVADO ese rango no es una franja/evento real, así que
    los 3 tipos branchean distinto acá (no es un simple `es_pedido_derivado`):

    - Pedidos del Estudio (`tipo` en `TIPOS_ESTUDIO`) van por su propio
      revalidador (`routes.estudio.revalidar_disponibilidad_estudio`: espacio
      con SU buffer propio + equipos reales por el motor) — el `_check_stock`
      genérico leería el ítem centinela como un equipo más y lo validaría con
      el buffer GLOBAL, no el propio del espacio (bug encontrado auditando la
      economía del Estudio: confirmar/transicionar un pedido de estudio no
      revalidaba con el buffer correcto).
    - Un pedido de `taller` SE SALTEA por completo (sin errores): su rango es
      el mes contable de la edición, no una franja real — ni el motor
      genérico (que contaría el centinela contra el buffer global de un mes
      entero) ni el revalidador del Estudio (que preguntaría "¿está libre el
      espacio ese mes completo?", casi siempre no por las reservas reales que
      ese mes sí contiene) dan un resultado con sentido. El bloqueo real de
      las clases puntuales ya lo hace `_taller_bloqueante`/el gate de la
      edición (`services/talleres/commands/ediciones.py`), no este endpoint.
    - Un pedido `diaria` (la rama genérica de abajo) SUMA además la
      revalidación de sus turnos del Estudio EMBEBIDOS, si tiene alguno
      (`_revalidar_turnos_embebidos`, #1308 rediseño "turno como ítem") — un
      pedido de equipos y un turno embebido conviven en la MISMA fila, así que
      ambas validaciones corren, no una en lugar de la otra. No-op barato si el
      pedido no tiene ningún turno embebido (100% de los pedidos hasta la Fase
      4). Un pedido `estudio`/`estudio_fijo`/`taller` nunca tiene turnos
      embebidos propios (son ellos mismos el turno/la clase) — no hace falta
      sumar la llamada en esas dos ramas de arriba.

    Import diferido de `services.estudio` — mismo estilo que el resto de los
    imports diferidos de este archivo, ver `cambiar_estado`."""
    if es_pedido_estudio(p):
        from services.estudio.queries.disponibilidad import revalidar_disponibilidad_estudio
        return revalidar_disponibilidad_estudio(conn, p)
    if es_pedido_taller(p):
        return []
    from services.estudio.queries.disponibilidad import _revalidar_turnos_embebidos
    # `_revalidar_turnos_embebidos` ya devuelve mensajes completos y legibles (no
    # fragmentos crudos como `_check_stock`) — no se re-envuelven con un prefijo.
    errores = list(_revalidar_turnos_embebidos(conn, p["id"]))
    # Mismo advisory lock por equipo que `create_pedido`/`_apply_pedido_items`
    # (namespace 5390412, `_lock_equipos_por_id`) — sin esto, este `FOR UPDATE`
    # genérico contra `equipos` no participaba de la misma serialización y
    # podía deadlockear contra un `create_pedido` concurrente del mismo equipo
    # (hallazgo de auditoría, #1313/#1314).
    equipo_ids = [
        r["equipo_id"] for r in conn.execute(
            "SELECT DISTINCT equipo_id FROM alquiler_items "
            "WHERE pedido_id = %s AND equipo_id IS NOT NULL AND turno_estudio_id IS NULL",
            (p["id"],),
        ).fetchall()
    ]
    _lock_equipos_por_id(conn, equipo_ids)
    errores.extend(
        f"Sin stock suficiente: {s}"
        for s in _check_stock(conn, p["id"], p["fecha_desde"], p["fecha_hasta"])
    )
    return errores


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

    error_principal = _turno_supera_a_principal(conn, p, estado_nuevo)
    if error_principal:
        raise HTTPException(400, error_principal)

    if estado_nuevo == "borrador" and estado_actual != "borrador":
        if (p["monto_pagado"] or 0) > 0:
            raise HTTPException(400, "No se puede volver a borrador: el pedido ya tiene plata cobrada.")
        if _tiene_factura_activa(conn, pedido_id):
            raise HTTPException(400, "No se puede volver a borrador: el pedido ya tiene una factura activa.")

    # Salir de BORRADOR = el presupuesto rápido se vuelve un pedido real: saca
    # número, entra en la cola de Solicitados, se puede confirmar/cobrar/
    # facturar. Para eso hace falta tener algo y alguien (criterio del dueño,
    # 2026-07-29 — vio un pedido pasado a solicitud sin ninguna de las dos:
    # "no sé si debería poderse"). Sin cliente no hay a quién llamar ni a quién
    # facturarle; sin contenido (equipos O un turno del Estudio vinculado) no
    # hay nada que entregar.
    #
    # SOLO en esta transición, a propósito: los pedidos que nacen ya reales
    # (Estudio, taller, importados históricos) nunca pasan por acá, así que
    # este gate no puede romperlos. `cancelado` queda afuera (no está en FLOW):
    # descartar un presupuesto que no llegó a nada siempre tiene que poder.
    if estado_actual == "borrador" and estado_nuevo != "borrador" and estado_nuevo in FLOW:
        if not (p["cliente_id"] or (p["cliente_nombre"] or "").strip()):
            raise HTTPException(
                400,
                "Elegí un cliente (o cargá un nombre a mano) antes de sacarlo de borrador.",
            )
        tiene_items = conn.execute(
            "SELECT 1 FROM alquiler_items WHERE pedido_id = %s LIMIT 1", (pedido_id,)
        ).fetchone()
        # Un turno del Estudio vinculado (#1308) también es contenido válido
        # ("2 horas de estudio y nada más") — antes esta gate solo miraba
        # `alquiler_items` y bloqueaba para siempre un pedido sin equipos
        # propios, sin importar el turno (hallazgo de auditoría, #1313/#1314;
        # mismo criterio que `_puede_quedar_sin_items`, commands/items.py).
        if not tiene_items and not _tiene_turno_estudio_activo(conn, pedido_id):
            raise HTTPException(
                400,
                "Agregá al menos un equipo (o un turno del Estudio) antes de sacarlo de borrador.",
            )

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

        # Mismo criterio que la gate de salida de borrador, arriba: un turno
        # del Estudio vinculado también cuenta como contenido (#1313/#1314).
        tiene_items = conn.execute(
            "SELECT 1 FROM alquiler_items WHERE pedido_id=%s", (pedido_id,)
        ).fetchone()
        if not tiene_items and not _tiene_turno_estudio_activo(conn, pedido_id):
            errores.append("El pedido no tiene equipos cargados ni un turno del Estudio.")
        # El escape hatch manual de `finalizado` (punto 1 del docstring) es
        # SOLO para un pedido sin nada por cobrar — `_maybe_finalizar` ya
        # cubre el caso normal (devuelto + pagado). Sin este chequeo, el botón
        # "Finalizar" del admin marcaba como cerrado-y-cobrado un pedido real
        # sin haber cobrado un peso (hallazgo del dueño, 2026-07-30).
        if (
            estado_nuevo == "finalizado" and estado_actual != "finalizado"
            and _tiene_saldo_pendiente(p["monto_total"], p["monto_pagado"])
        ):
            errores.append("Falta cobrar el saldo antes de poder finalizar el pedido.")
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
    # El número se asigna al entrar a CUALQUIER estado real del camino feliz, no
    # solo a `confirmado`: un borrador nace sin número (es un presupuesto rápido,
    # no una venta — ver `create_pedido`), así que el momento en que deja de ser
    # borrador es cuando pasa a ser un pedido de verdad y necesita su número.
    # `cancelado`/`borrador` quedan afuera (no están en `FLOW`): un borrador
    # descartado no consume un número de la secuencia.
    if estado_nuevo in FLOW and not p["numero_pedido"]:
        from services.alquileres.commands.pedido import _next_numero_pedido
        updates["numero_pedido"] = _next_numero_pedido(conn)
        numero_asignado = True

    set_clause = ", ".join(f"{k}=%s" for k in updates)
    conn.execute(f"UPDATE alquileres SET {set_clause} WHERE id=%s", (*updates.values(), pedido_id))

    from services.alquileres.commands.pedido import _maybe_finalizar
    _maybe_finalizar(conn, pedido_id)

    # Cascada a los turnos del Estudio vinculados (#1308) — SOLO si `pedido_id`
    # es un pedido PRINCIPAL (no un turno): un turno nunca puede ser principal
    # de otro (`_resolver_pedido_principal` exige `tipo='diaria'` para
    # vincularse), así que este guard también corta cualquier riesgo de
    # recursión — al procesar el turno más abajo, su propio
    # `pedido_principal_id` no es `None` y el guard frena ahí.
    turnos_sin_avanzar = (
        _cascada_turnos_vinculados(conn, pedido_id, estado_nuevo, actor)
        if p["pedido_principal_id"] is None
        else []
    )

    return {
        "estado_anterior": estado_actual,
        "estado_nuevo": estado_nuevo,
        "numero_pedido_asignado": numero_asignado,
        "turnos_vinculados_sin_avanzar": turnos_sin_avanzar,
    }
