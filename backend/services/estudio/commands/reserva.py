"""Única puerta de mutación de una reserva de El Estudio (#1283 Fase 6).

`_crear_pedido_estudio` es el núcleo compartido entre el flujo público
(`crear_reserva_estudio`, sesión+Didit+anticipación) y el admin
(`crear_reserva_estudio_admin`, sin esos gates) — ambos endpoints viven en
`routes/estudio.py` (transporte) y llaman a esta única implementación del
lock/gate. `editar_reserva` es su equivalente para reprogramar/editar un turno
ya existente (`PATCH /admin/estudio/reservas/{id}`).

No commitea — la transacción la maneja el caller (route). No valida identidad
ni anticipación — son gates del caller, distintos entre público y admin.
"""
from collections import namedtuple
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from database import to_datetime
from reservas import validar_stock_hipotetico
from services.precios import precio_jornada_efectivo

from services.estudio.queries.estudio import _get_estudio_row
from services.estudio.queries.disponibilidad import (
    _centinela_libre,
    _estudio_disponible,
    _franja_estudio,
    _slot_bloqueante,
    _taller_bloqueante,
)

_Item = namedtuple("_Item", ["equipo_id", "cantidad"])

# Estados con los que se puede CREAR una reserva desde el back-office (mismo
# universo que reserva stock — `reservas.ESTADOS_RESERVADO`, acá como tupla
# Python para validar el body; 'cancelado' no aplica a una alta).
_ESTADOS_ADMIN_CREACION = ("solicitado", "confirmado", "retirado")

# Nombre canónico del ítem "recién pintado" (add-on independiente, #1300
# seguimiento) — línea libre (equipo_id=NULL, como el flete/#805), NUNCA
# equipo real: no es un recurso con stock, es un cargo fijo opcional. Se
# distingue de la línea del pack ⏰ LEGACY (mismo `equipo_id IS NULL`, ver
# `editar_reserva`) por este nombre exacto — no cambiarlo sin actualizar
# ese chequeo.
NOMBRE_ITEM_PINTURA_RECIENTE = "Recién pintado"


class SueltoItem(BaseModel):
    """Equipo suelto agregado a mano a una reserva del Estudio — solo desde el
    back-office (#1283 Fase 6): el flujo público no ofrece sueltos arbitrarios,
    solo la promo. Mismo tratamiento de plata que la promo: cargo FIJO
    (no por jornada) — la reserva se mide en horas, no en días."""
    equipo_id: int
    cantidad: int = Field(default=1, ge=1, le=9999)


def _precio_promo_y_sueltos(
    conn, estudio, con_promo: bool, sueltos: list,
) -> tuple[int, int, dict[int, int]]:
    """Resuelve el precio de la promo + de cada suelto vía la fuente única
    `precio_jornada_efectivo` (MEMORIA 2026-06-29 — el front no calcula
    plata; esto tampoco calcula nada propio, solo suma lo que esa fuente
    devuelve). Puro cálculo de lectura, sin validar stock ni insertar nada —
    compartido por `_crear_pedido_estudio` (necesita el total ANTES de
    insertar el pedido), `editar_reserva` y `cotizar_reserva_estudio`
    (`routes/estudio.py`, preview sin pedido_id). Devuelve `(promo_precio,
    monto_extra, precios_sueltos)`: `monto_extra` ya suma promo + sueltos×cantidad."""
    promo_precio = precio_jornada_efectivo(conn, estudio["promo_combo_id"]) or 0 if con_promo else 0
    monto_extra = promo_precio
    precios_sueltos: dict[int, int] = {}
    for s in sueltos:
        precio = precio_jornada_efectivo(conn, s.equipo_id) or 0
        precios_sueltos[s.equipo_id] = precio
        monto_extra += precio * s.cantidad
    return promo_precio, monto_extra, precios_sueltos


def _validar_e_insertar_promo_sueltos(
    conn, pedido_id: int, fecha_desde, fecha_hasta, *,
    estudio, con_promo: bool, sueltos: list,
    promo_precio: int, precios_sueltos: dict[int, int],
) -> Optional[str]:
    """Valida stock e inserta los `alquiler_items` de promo/sueltos de una
    reserva del Estudio YA con `pedido_id` (fila de `alquileres` insertada) —
    compartido por `_crear_pedido_estudio` (alta) y `editar_reserva` (edición),
    antes duplicado byte a byte entre ambos.

    Promo (combo): BEST-EFFORT, nunca bloquea — mismo criterio que tenía el
    pack ⏰ retirado: lo que no hay no frena la reserva, se cobra el precio
    fijo igual (ya sumado al `monto_total` del caller vía
    `_precio_promo_y_sueltos`) y se devuelve qué faltó. Sueltos: requisito
    DURO — un equipo elegido por su nombre, ya comprometido con el cliente;
    si no hay stock, 409 y nada se inserta.

    Se valida ANTES de insertar (`validar_stock_hipotetico` toma sus propios
    `FOR UPDATE`, expandiendo combos con `_expandir_mult`): si el INSERT fuera
    antes, el lock implícito FOR KEY SHARE del propio insert quedaría en el
    camino del FOR UPDATE del gate — mismo motivo que el orden lock-antes-de-
    insertar del centinela (ver `_crear_pedido_estudio`). Devuelve
    `promo_advertencia` (o `None`); no commitea (responsabilidad del caller)."""
    promo_advertencia: Optional[str] = None
    if con_promo:
        errores_promo = validar_stock_hipotetico(
            conn, pedido_id, fecha_desde.isoformat(), fecha_hasta.isoformat(),
            [_Item(estudio["promo_combo_id"], 1)],
        )
        if errores_promo:
            promo_advertencia = (
                f"La promo se reservó igual, pero sin stock de: {'; '.join(errores_promo)}"
            )

    if sueltos:
        errores_sueltos = validar_stock_hipotetico(
            conn, pedido_id, fecha_desde.isoformat(), fecha_hasta.isoformat(),
            [_Item(s.equipo_id, s.cantidad) for s in sueltos],
        )
        if errores_sueltos:
            raise HTTPException(409, f"Sin stock suficiente: {'; '.join(errores_sueltos)}")

    if con_promo:
        conn.execute(
            """
            INSERT INTO alquiler_items
                (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo)
            VALUES (%s,%s,1,%s,%s,'fijo')
            """,
            (pedido_id, estudio["promo_combo_id"], promo_precio, promo_precio),
        )
    for s in sueltos:
        precio = precios_sueltos[s.equipo_id]
        conn.execute(
            """
            INSERT INTO alquiler_items
                (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo)
            VALUES (%s,%s,%s,%s,%s,'fijo')
            """,
            (pedido_id, s.equipo_id, s.cantidad, precio, precio * s.cantidad),
        )

    return promo_advertencia


def _insertar_item_pintura(conn, pedido_id: int, precio: int) -> None:
    """Inserta la línea libre del add-on "recién pintado" (#1300 seguimiento) —
    mismo patrón que el flete/#805: `equipo_id=NULL` + `nombre_libre`, NUNCA
    un equipo real (no es un recurso con stock, es un cargo fijo opcional).
    El caller decide si corresponde llamarla (`pintura_reciente=True`);
    inserta aunque `precio` sea 0 (el dueño todavía no cargó un valor en
    `estudio.precio_pintura_reciente`) — deja registro de que se pidió,
    mismo criterio "ítems veraces" que el resto del paquete."""
    conn.execute(
        """
        INSERT INTO alquiler_items
            (pedido_id, equipo_id, nombre_libre, cantidad, precio_jornada, subtotal, cobro_modo)
        VALUES (%s, NULL, %s, 1, %s, %s, 'fijo')
        """,
        (pedido_id, NOMBRE_ITEM_PINTURA_RECIENTE, precio, precio),
    )


def _crear_pedido_estudio(
    conn, *, estudio, fecha_desde, fecha_hasta,
    cliente_id, cliente_nombre, cliente_email, cliente_telefono,
    con_promo: bool, sueltos: list | None, pintura_reciente: bool = False,
    espacio_monto: int | None, estado: str, numero_pedido: int,
    pedido_principal_id: int | None = None,
) -> tuple[int, Optional[str]]:
    """Núcleo de creación de un pedido del Estudio (#1283 Fase 6 — extraído de
    `crear_reserva_estudio`, que ahora es un wrapper: sesión+Didit+anticipación
    +'solicitado'). Arma los ítems (promo BEST-EFFORT / sueltos DUROS /
    centinela DURO / pintura reciente sin stock, ver `_insertar_item_pintura`)
    y el pedido, todo en la transacción del `conn` del caller (no commitea —
    eso es responsabilidad del caller). Devuelve `(pedido_id,
    promo_advertencia)` — el segundo es `None` salvo que la promo se haya
    reservado con algún componente sin stock (ver abajo). El pack (⏰
    mecanismo legacy anterior a la promo) se retiró en la Fase 8, #1283.

    NO valida identidad ni anticipación — son gates del CALLER, distintos entre
    el flujo público y el admin. SÍ valida slot/taller (conflicto estructural,
    aplica a cualquier origen) y todo el stock/disponibilidad.

    `espacio_monto`: si es `None`, se calcula `precio_hora × horas` como
    siempre; si viene, es un override manual del admin (ej. tarifa
    negociada) — el pedido lo persiste tal cual, sin recalcularlo.

    `pedido_principal_id`: si viene, vincula este turno a un pedido de
    alquiler normal (#1308, "Reserva del Estudio" desde la página del
    pedido) — el CALLER es responsable de resolver `cliente_id`/
    `cliente_nombre`/etc. DEL PEDIDO PRINCIPAL antes de llamar (no de lo que
    mande el request), así el turno y su pedido nunca muestran clientes
    distintos.
    """
    slot_cliente = _slot_bloqueante(conn, fecha_desde, fecha_hasta)
    if slot_cliente:
        raise HTTPException(409, f"Esa franja está reservada de forma fija ({slot_cliente})")

    taller_nombre = _taller_bloqueante(conn, fecha_desde, fecha_hasta)
    if taller_nombre:
        raise HTTPException(409, f"Esa franja está reservada para el taller «{taller_nombre}»")

    con_promo = bool(con_promo) and bool(estudio["promo_combo_id"])
    sueltos = sueltos or []

    # `espacio_monto` es la plata REAL del espacio (va al ítem centinela,
    # Fase 2 — ítems veraces); `monto_total` sigue siendo espacio + promo/
    # sueltos, como siempre. El precio de la promo/sueltos se resuelve UNA vez
    # acá y queda congelado en el ítem (como cualquier otra plata de pedido) —
    # si el combo/equipo cambia de precio después, este pedido ya cobrado no
    # se mueve.
    horas = int(round((fecha_hasta - fecha_desde).total_seconds() / 3600))
    espacio_monto_final = (
        espacio_monto if espacio_monto is not None else (estudio["precio_hora"] or 0) * horas
    )
    promo_precio, monto_extra, precios_sueltos = _precio_promo_y_sueltos(
        conn, estudio, con_promo, sueltos,
    )
    pintura_precio = (estudio["precio_pintura_reciente"] or 0) if pintura_reciente else 0
    monto_total = espacio_monto_final + monto_extra + pintura_precio

    pedido_id = conn.insert_returning(
        """
        INSERT INTO alquileres (cliente_id, cliente_nombre, cliente_email, cliente_telefono,
                                fecha_desde, fecha_hasta, monto_total, estado,
                                fuente, tipo, estudio_con_pack, numero_pedido,
                                pedido_principal_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            cliente_id, cliente_nombre, cliente_email, cliente_telefono,
            fecha_desde, fecha_hasta, monto_total, estado,
            "estudio", "estudio", False, numero_pedido,
            pedido_principal_id,
        ),
    )

    # Promo (BEST-EFFORT, nunca bloquea) + sueltos (DURO, 409 si falta stock):
    # valida e inserta sus `alquiler_items` — ver el docstring de
    # `_validar_e_insertar_promo_sueltos` para el porqué del orden
    # validar-antes-de-insertar (mismo motivo que el centinela, abajo).
    promo_advertencia = _validar_e_insertar_promo_sueltos(
        conn, pedido_id, fecha_desde, fecha_hasta,
        estudio=estudio, con_promo=con_promo, sueltos=sueltos,
        promo_precio=promo_precio, precios_sueltos=precios_sueltos,
    )

    # Pintura reciente: add-on independiente, sin stock que validar — se
    # inserta directo, no pasa por `_validar_e_insertar_promo_sueltos`.
    if pintura_reciente:
        _insertar_item_pintura(conn, pedido_id, pintura_precio)

    # ── Espacio (centinela): requisito DURO ─────────────────────────────────
    # Lock PRIMERO, INSERT después — a propósito, en ese orden. Un INSERT que
    # referencia `equipo_id` (FK) toma un lock implícito FOR KEY SHARE sobre esa
    # fila; si esto insertara ANTES de pedir el FOR UPDATE, dos altas
    # concurrentes de la MISMA franja quedarían cada una con FOR KEY SHARE de
    # su propio insert (compatibles entre sí) y las dos bloqueadas pidiendo
    # FOR UPDATE sobre la fila del otro — deadlock simétrico (encontrado con
    # `test_concurrencia_admin_dos_altas_misma_franja_solo_una_pasa`). Lockeando
    # ANTES de insertar, la 2da transacción espera acá, nunca llega a insertar
    # su propia fila en conflicto.
    conn.execute("SELECT id FROM equipos WHERE id = %s FOR UPDATE", (estudio["equipo_id"],))
    if not _centinela_libre(conn, estudio["equipo_id"], fecha_desde, fecha_hasta,
                            estudio["buffer_horas"], exclude_pedido_id=pedido_id):
        raise HTTPException(409, "El estudio no está disponible en esa franja")
    # `cobro_modo='fijo'` con el monto real (Fase 2, ítems veraces): antes
    # este ítem iba a $0 (la plata vivía solo en el header) — sin esto,
    # cualquier recálculo/desglose/reconciliación que sume por ítem daba
    # $0 en vez del total real (bugs vivos arreglados en la Fase 1/2).
    conn.execute(
        """
        INSERT INTO alquiler_items
            (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo)
        VALUES (%s,%s,1,%s,%s,'fijo')
        """,
        (pedido_id, estudio["equipo_id"], espacio_monto_final, espacio_monto_final),
    )

    return pedido_id, promo_advertencia


def editar_reserva(
    conn, pedido_id: int, *,
    fecha: str | None = None, start: str | None = None, horas: int | None = None,
    con_promo: bool | None = None, sueltos: list | None = None,
    pintura_reciente: bool | None = None,
    espacio_monto: int | None = None,
) -> Optional[str]:
    """Reprograma/edita una reserva del estudio YA EXISTENTE (extraído de
    `PATCH /admin/estudio/reservas/{id}`, #1283 Fase 6). Reemplaza TODOS los
    ítems no-centinela (promo/sueltos/pintura reciente) según el payload —
    mismo criterio "reemplazo completo" que el PUT de ítems del editor
    genérico, adaptado al Estudio (que el editor genérico bloquea, Fase 1:
    #1283). Un `estudio_fijo` no se edita acá — lo gobierna su slot (editar
    el slot regenera sus pedidos, `routes/estudio.py::_regenerar_pedidos_slot`).

    Toma `FOR UPDATE` sobre el pedido (lock de fila, mismo mecanismo que
    `_crear_pedido_estudio` usa sobre el centinela). No commitea — eso es
    responsabilidad del caller (route). Devuelve `promo_advertencia` (o
    `None`)."""
    pedido = conn.execute(
        "SELECT * FROM alquileres WHERE id = %s FOR UPDATE", (pedido_id,)
    ).fetchone()
    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")
    if pedido["tipo"] == "estudio_fijo":
        raise HTTPException(
            409, "Los turnos de un slot fijo se editan desde el slot, no acá"
        )
    if pedido["tipo"] != "estudio":
        raise HTTPException(400, "Este pedido no es del Estudio")

    estudio = _get_estudio_row(conn)

    fecha_desde = to_datetime(pedido["fecha_desde"])
    fecha_hasta = to_datetime(pedido["fecha_hasta"])
    reprograma = fecha is not None or start is not None or horas is not None
    if reprograma:
        horas_actuales = int(round((fecha_hasta - fecha_desde).total_seconds() / 3600))
        fecha_desde, fecha_hasta = _franja_estudio(
            estudio,
            fecha or fecha_desde.strftime("%Y-%m-%d"),
            start or fecha_desde.strftime("%H:%M"),
            horas if horas is not None else horas_actuales,
        )

    libre, motivo = _estudio_disponible(
        conn, estudio, fecha_desde, fecha_hasta, exclude_pedido_id=pedido_id,
    )
    if not libre:
        raise HTTPException(409, f"El espacio no está disponible: {motivo}")

    # `IS DISTINCT FROM` (no `!=`): un ítem libre (pintura reciente, o el pack
    # legacy) tiene `equipo_id IS NULL` — `NULL != %s` es NULL (ni true ni
    # false) en SQL, así que `!=` los excluye EN SILENCIO de este SELECT (y
    # del DELETE de abajo). Bug real encontrado en vivo: el ítem de pintura
    # sobrevivía para siempre a un "reemplazo completo" de la edición.
    items_actuales = conn.execute(
        "SELECT equipo_id, cantidad, precio_jornada, subtotal, nombre_libre, cobro_modo "
        "FROM alquiler_items WHERE pedido_id = %s AND equipo_id IS DISTINCT FROM %s",
        (pedido_id, estudio["equipo_id"]),
    ).fetchall()
    # El pack ⏰ se retiró (Fase 8, #1283): ya no hay forma de RE-crear su
    # línea si este endpoint la borrara y recalculara sin ella (el
    # reemplazo completo de abajo es incondicional) — fail-loud en vez de
    # perder plata en silencio. Vacío en la práctica desde que existe la
    # promo (`crear_promo_desde_pack` apaga `pack_activo`); solo puede
    # dispararse en un turno viejo creado ANTES de esta migración.
    #
    # Distinguir de la línea NUEVA de pintura reciente (#1300 seguimiento,
    # `NOMBRE_ITEM_PINTURA_RECIENTE`) — también `equipo_id IS NULL` pero NO
    # es el pack: sin este exclude, cualquier turno con pintura reciente
    # rebotaría acá con el mensaje equivocado.
    if any(
        it["equipo_id"] is None and it["nombre_libre"] != NOMBRE_ITEM_PINTURA_RECIENTE
        for it in items_actuales
    ):
        raise HTTPException(
            409,
            "Este turno todavía usa el pack (mecanismo retirado) — no se puede "
            "editar desde acá. Contactá a soporte para migrarlo a la promo.",
        )
    promo_actual = any(it["equipo_id"] == estudio["promo_combo_id"] for it in items_actuales)
    pintura_actual = any(
        it["equipo_id"] is None and it["nombre_libre"] == NOMBRE_ITEM_PINTURA_RECIENTE
        for it in items_actuales
    )

    con_promo = con_promo if con_promo is not None else promo_actual
    pintura_reciente = pintura_reciente if pintura_reciente is not None else pintura_actual
    if sueltos is not None:
        sueltos_finales = sueltos
    else:
        ids_conocidos = {estudio["promo_combo_id"]}
        sueltos_finales = [
            SueltoItem(equipo_id=it["equipo_id"], cantidad=it["cantidad"])
            for it in items_actuales
            if it["equipo_id"] is not None and it["equipo_id"] not in ids_conocidos
        ]
    # Contrato de `espacio_monto` (gotcha real, pedido #445, 2026-07-28): acá
    # `None` SIEMPRE recalcula a precio de lista — no "conserva lo que había".
    # Cualquier caller que quiera preservar una tarifa negociada tiene que
    # RESOLVER y reenviar el monto actual él mismo (así lo hace `ReservaDialog`
    # vía `espacioOverrideInicial`, `frontend/src/lib/estudio-slots.ts`); este
    # módulo no tiene forma de distinguir "el admin no tocó el campo" de "el
    # admin quiere volver a lista" — esa decisión es del caller, no de acá.
    espacio_monto_final = (
        espacio_monto if espacio_monto is not None
        else (estudio["precio_hora"] or 0)
        * int(round((fecha_hasta - fecha_desde).total_seconds() / 3600))
    )

    # Reemplazo completo de los ítems no-centinela: se recalcula todo
    # desde cero contra la franja (nueva o la misma) en vez de parchear
    # fila por fila — más simple y sin estado intermedio inconsistente.
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id = %s AND equipo_id IS DISTINCT FROM %s",
        (pedido_id, estudio["equipo_id"]),
    )

    con_promo = bool(con_promo) and bool(estudio["promo_combo_id"])

    # Promo (BEST-EFFORT, nunca bloquea) + sueltos (DURO, 409 si falta stock):
    # mismos dos helpers que `_crear_pedido_estudio` — ver
    # `_validar_e_insertar_promo_sueltos` para el porqué del orden
    # validar-antes-de-insertar.
    promo_precio, monto_extra, precios_sueltos = _precio_promo_y_sueltos(
        conn, estudio, con_promo, sueltos_finales,
    )
    pintura_precio = (estudio["precio_pintura_reciente"] or 0) if pintura_reciente else 0
    monto_total = espacio_monto_final + monto_extra + pintura_precio
    promo_advertencia = _validar_e_insertar_promo_sueltos(
        conn, pedido_id, fecha_desde, fecha_hasta,
        estudio=estudio, con_promo=con_promo, sueltos=sueltos_finales,
        promo_precio=promo_precio, precios_sueltos=precios_sueltos,
    )
    if pintura_reciente:
        _insertar_item_pintura(conn, pedido_id, pintura_precio)

    conn.execute(
        "UPDATE alquiler_items SET precio_jornada = %s, subtotal = %s "
        "WHERE pedido_id = %s AND equipo_id = %s",
        (espacio_monto_final, espacio_monto_final, pedido_id, estudio["equipo_id"]),
    )
    conn.execute(
        "UPDATE alquileres SET fecha_desde = %s, fecha_hasta = %s, monto_total = %s, "
        "estudio_con_pack = FALSE, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
        (fecha_desde, fecha_hasta, monto_total, pedido_id),
    )

    return promo_advertencia
