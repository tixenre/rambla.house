"""services/carrito/readiness.py — "el carrito listo para reservar" (lado plata).

Puerta del carrito **previa** a crear la reserva: resuelve el precio de cada ítem
con el gate de seguridad —solo equipos de `visible_catalogo`, el cliente NUNCA
decide el precio— apoyándose en la fuente única de plata
`services.precios.precio_jornada_efectivo` (combo → derivado de componentes;
kit/simple → su precio propio).

**No crea la reserva.** La creación real (con advisory-lock, motor sagrado) sigue
siendo `create_pedido_retry` (`routes/alquileres/core.py`): el route hace el
*handoff* con los precios que devuelve esta función. Así el carrito **pide** plata y
**delega** la creación; no se come ninguna de las dos. Ver `docs/SISTEMA_CARRITO.md`
(invariante "carrito = intención, gate = verdad").
"""
from fastapi import HTTPException

from services.precios import precios_efectivos_batch

# Gate de seguridad único (fragmento SQL compartido por la versión de un solo
# equipo y la versión en lote — una sola forma del predicado, no dos copias que
# puedan divergir). Ver `equipo_visible_catalogo` para el detalle de cada condición.
_GATE_CATALOGO_WHERE = (
    "eliminado_at IS NULL AND visible_catalogo = 1 "
    "AND es_recurso_interno = FALSE AND precio_jornada IS NOT NULL"
)


def equipo_visible_catalogo(conn, equipo_id: int) -> None:
    """Gate de seguridad único: valida que `equipo_id` sea un producto real y
    público del catálogo — vivo (`eliminado_at IS NULL`), `visible_catalogo = 1`,
    NO el recurso interno del Estudio (`es_recurso_interno = FALSE`, el
    "centinela" que modela el espacio físico — ver MEMORIA 2026-05-27/05-31) y
    con precio definido.

    Extraído (#1209) para que la creación de pedido del cliente
    (`precios_catalogo_para_reserva`, abajo) aplique el mismo chequeo que ya
    exigía el resto del catálogo — un cliente no puede reservar stock de un
    equipo oculto/interno (o inexistente/soft-deleted) que el negocio nunca
    ofreció públicamente.

    Lanza ``HTTPException(404)`` si el equipo no existe, está soft-deleted, no
    está visible, es el recurso interno, o no tiene precio definido (no se
    crean/agregan líneas de pedido con equipos fantasma).
    """
    row = conn.execute(
        f"SELECT 1 FROM equipos WHERE id = %s AND {_GATE_CATALOGO_WHERE}",
        (equipo_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Equipo {equipo_id} no encontrado en el catálogo")


def _equipos_visibles_catalogo(conn, equipo_ids) -> set[int]:
    """Mismo gate que `equipo_visible_catalogo`, para varios ids en UNA query —
    lo usa `precios_catalogo_para_reserva` para no pagar una query por ítem del
    carrito en la creación real del pedido (N+1 documentado en
    `docs/SISTEMA_FINANZAS_FLUJO.md`, hallazgo #12)."""
    ids = list(equipo_ids)
    if not ids:
        return set()
    rows = conn.execute(
        f"SELECT id FROM equipos WHERE id = ANY(%s) AND {_GATE_CATALOGO_WHERE}",
        (ids,),
    ).fetchall()
    return {r["id"] for r in rows}


def precios_catalogo_para_reserva(conn, items) -> dict[int, int]:
    """Mapa `equipo_id → precio efectivo por jornada` para los ítems de un carrito
    que va a convertirse en pedido del cliente.

    **Gate de seguridad** (defensa en profundidad, mismo predicado que
    `equipo_visible_catalogo` pero en lote — `_equipos_visibles_catalogo`):
    solo equipos vivos y visibles del catálogo, con precio definido — sin esto
    un cliente podía reservar por API un equipo oculto/interno enumerando ids →
    pedido $0. El cliente **nunca** decide el precio: se descarta el
    `precio_jornada` del body y se toma el del catálogo, resuelto por la fuente
    única (`precios_efectivos_batch`) → lo que el carrito cotiza es lo que se
    persiste (sin drift de combos).

    Dos queries totales sin importar cuántos ítems tenga el carrito (antes: 1-2
    por ítem) — usa `= ANY(%s)`, no un `IN (...)` armado a mano (ese patrón fue
    el que #643 revirtió en `/api/cotizar`).

    Lanza ``HTTPException(404)`` si un ítem no está en el catálogo público (no se
    crean pedidos con equipos fantasma) — mismo ítem que fallaría antes, en el
    mismo orden de iteración. ``items``: iterable con ``.equipo_id``.
    """
    ids: list[int] = []
    vistos: set[int] = set()
    for it in items:
        if it.equipo_id not in vistos:
            vistos.add(it.equipo_id)
            ids.append(it.equipo_id)
    if not ids:
        return {}

    visibles = _equipos_visibles_catalogo(conn, ids)
    for eid in ids:
        if eid not in visibles:
            raise HTTPException(404, f"Equipo {eid} no encontrado en el catálogo")

    return precios_efectivos_batch(conn, ids)
