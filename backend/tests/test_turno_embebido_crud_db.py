"""#1308 rediseño "turno como ítem", Fase 4.1 — las 3 funciones núcleo que
agregan/editan/borran un turno del Estudio EMBEBIDO en un pedido de alquiler
YA EXISTENTE (`services.estudio.commands.reserva.agregar_turno_embebido` /
`editar_turno_embebido` / `eliminar_turno_embebido`).

Contra Postgres REAL — llama a las funciones DIRECTO (no vía HTTP; los
endpoints son la Fase 4.2, con su propio test). Cubre lo que la Fase 1
(motor de reservas item-aware) no cubría: el flujo de alta/edición/baja en
sí, la redistribución del descuento propio del turno entre sus ítems, y el
multi-turno por pedido.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_turno_embebido_crud_db.py -v -m integration
"""
import os
from urllib.parse import urlparse

import pytest

_OPT_IN = os.getenv("RESERVAS_DB_TEST") == "1"
_DB_URL = os.getenv("DATABASE_URL", "")
_DB_NAME = urlparse(_DB_URL).path.lstrip("/") if _DB_URL else ""


def _looks_like_test_db() -> bool:
    return bool(_DB_NAME) and "test" in _DB_NAME.lower()


pytestmark = [
    pytest.mark.integration,
    pytest.mark.golden,  # golden set: toca el core de reservas (overbooking) — scripts/evals/README.md
    pytest.mark.skipif(
        not _OPT_IN,
        reason="opt-in: setear RESERVAS_DB_TEST=1 + DATABASE_URL a una base de prueba",
    ),
    pytest.mark.skipif(
        _OPT_IN and not _looks_like_test_db(),
        reason=f"DATABASE_URL ({_DB_NAME!r}) no parece base de test — abortado por seguridad",
    ),
]

# Ids altos dedicados (bloque 9_488_xxx, sin uso en otros *_db.py).
CLIENTE_ID = 9_488_001
EQ_RENTAL_ID = 9_488_010
EQ_SUELTO_ID = 9_488_011
PEDIDO_ID = 9_488_020          # pedido diaria mixto (contenedor)
PEDIDO_ESTUDIO_ID = 9_488_021  # standalone, para el conflicto de espacio
PEDIDO_TALLER_ID = 9_488_022   # taller con turno embebido por clase (2026-08-13)


@pytest.fixture
def conn():
    from database import get_db, init_db

    init_db()
    c = get_db()
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def _centinela(conn):
    return conn.execute("SELECT * FROM estudio WHERE id=1").fetchone()


def _crear_pedido_contenedor(conn, *, fecha_desde="2032-03-10", fecha_hasta="2032-03-13"):
    conn.execute(
        "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
        "VALUES (%s,'Turno','CRUD','turno-crud-embebido@test.com','+5491100000093') "
        "ON CONFLICT (id) DO NOTHING",
        (CLIENTE_ID,),
    )
    conn.execute(
        "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES "
        "(%s,'Cámara test CRUD turno embebido',1,'Rental'),"
        "(%s,'Micrófono suelto test CRUD turno embebido',2,'Rental') "
        "ON CONFLICT (id) DO NOTHING",
        (EQ_RENTAL_ID, EQ_SUELTO_ID),
    )
    conn.execute(
        "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
        "fecha_desde, fecha_hasta, monto_total) "
        "VALUES (%s,%s,'Turno CRUD','confirmado','diaria',%s,%s,30000)",
        (PEDIDO_ID, CLIENTE_ID, fecha_desde, fecha_hasta),
    )
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
        "VALUES (%s,%s,1,10000,30000,'jornada')",
        (PEDIDO_ID, EQ_RENTAL_ID),
    )


def _get_pedido(conn, id):
    return conn.execute("SELECT * FROM alquileres WHERE id=%s", (id,)).fetchone()


def _items_turno(conn, turno_id):
    return conn.execute(
        "SELECT * FROM alquiler_items WHERE turno_estudio_id=%s ORDER BY id", (turno_id,)
    ).fetchall()


# ── Alta ─────────────────────────────────────────────────────────────────────

def test_agregar_turno_crea_grupo_e_items_y_recalcula_el_total(conn):
    from datetime import datetime
    from services.estudio.commands.reserva import agregar_turno_embebido

    _crear_pedido_contenedor(conn)
    estudio = _centinela(conn)

    turno_id, advertencia = agregar_turno_embebido(
        conn, PEDIDO_ID, estudio=estudio,
        fecha_desde=datetime(2032, 3, 11, 14, 0), fecha_hasta=datetime(2032, 3, 11, 16, 0),
        con_promo=False, sueltos=[], espacio_monto=15000,
    )

    assert advertencia is None
    turno = conn.execute("SELECT * FROM alquiler_turnos_estudio WHERE id=%s", (turno_id,)).fetchone()
    assert turno["pedido_id"] == PEDIDO_ID
    assert turno["fecha_desde"].isoformat() == "2032-03-11T14:00:00"

    items = _items_turno(conn, turno_id)
    assert len(items) == 1
    assert items[0]["equipo_id"] == estudio["equipo_id"]
    assert items[0]["subtotal"] == 15000
    assert items[0]["cobro_modo"] == "fijo"

    pedido = _get_pedido(conn, PEDIDO_ID)
    assert pedido["monto_total"] == 30000 + 15000


def test_agregar_turno_rechaza_pedido_inexistente(conn):
    from datetime import datetime
    from fastapi import HTTPException
    from services.estudio.commands.reserva import agregar_turno_embebido

    estudio = _centinela(conn)
    with pytest.raises(HTTPException) as exc:
        agregar_turno_embebido(
            conn, 9_488_999, estudio=estudio,
            fecha_desde=datetime(2032, 3, 11, 14, 0), fecha_hasta=datetime(2032, 3, 11, 16, 0),
            con_promo=False, sueltos=[], espacio_monto=15000,
        )
    assert exc.value.status_code == 404


def test_agregar_turno_rechaza_pedido_que_no_es_diaria(conn):
    from datetime import datetime
    from fastapi import HTTPException
    from services.estudio.commands.reserva import agregar_turno_embebido

    conn.execute(
        "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, "
        "fecha_desde, fecha_hasta, monto_total) "
        "VALUES (%s,'Standalone test CRUD','confirmado','estudio','2032-03-01 10:00','2032-03-01 12:00',10000)",
        (PEDIDO_ESTUDIO_ID,),
    )
    estudio = _centinela(conn)
    with pytest.raises(HTTPException) as exc:
        agregar_turno_embebido(
            conn, PEDIDO_ESTUDIO_ID, estudio=estudio,
            fecha_desde=datetime(2032, 3, 11, 14, 0), fecha_hasta=datetime(2032, 3, 11, 16, 0),
            con_promo=False, sueltos=[], espacio_monto=15000,
        )
    assert exc.value.status_code == 400


def test_agregar_turno_respeta_conflicto_de_espacio(conn):
    """Otro pedido (standalone) ya ocupa esa franja — 409, nada se inserta."""
    from datetime import datetime
    from fastapi import HTTPException
    from services.estudio.commands.reserva import agregar_turno_embebido

    _crear_pedido_contenedor(conn)
    estudio = _centinela(conn)
    conn.execute(
        "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, "
        "fecha_desde, fecha_hasta, monto_total) "
        "VALUES (%s,'Standalone test CRUD','confirmado','estudio','2032-03-11 14:00','2032-03-11 16:00',10000)",
        (PEDIDO_ESTUDIO_ID,),
    )
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal, cobro_modo) "
        "VALUES (%s,%s,1,10000,'fijo')",
        (PEDIDO_ESTUDIO_ID, estudio["equipo_id"]),
    )

    with pytest.raises(HTTPException) as exc:
        agregar_turno_embebido(
            conn, PEDIDO_ID, estudio=estudio,
            fecha_desde=datetime(2032, 3, 11, 14, 0), fecha_hasta=datetime(2032, 3, 11, 16, 0),
            con_promo=False, sueltos=[], espacio_monto=15000,
        )
    assert exc.value.status_code == 409
    # La función no commitea/rollbackea (contrato: responsabilidad del
    # caller/route) — el turno queda insertado en ESTA transacción hasta que
    # algo la rollbackee, igual que `_crear_pedido_estudio` deja su fila
    # `alquileres` a medio insertar si el centinela falla después. Simula lo
    # que el route real hace en su `except: conn.rollback()`.
    conn.rollback()
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM alquiler_turnos_estudio WHERE pedido_id=%s", (PEDIDO_ID,)
    ).fetchone()["n"] == 0


def test_agregar_turno_con_suelto_autoconflicto_con_item_normal_del_mismo_pedido(conn):
    """Edge case de la Fase 1: el MISMO equipo (`EQ_SUELTO_ID`, stock=2) usado
    a la vez como ítem normal del pedido contenedor (cantidad=2, cubriendo
    2032-03-10..13 — incluye la ventana del turno) y como suelto del turno
    embebido del MISMO pedido (cantidad=1 más). Demanda real durante la
    ventana solapada: 2 (ya reservadas por el pedido) + 1 (el suelto nuevo) =
    3 > stock=2 → tiene que rechazar. Si el sentinel `excl_pedido_id=0` no
    existiera (o se usara el `pedido_id` real), la demanda del pedido
    contenedor quedaría excluida de su propio chequeo y esto pasaría sin
    stock real — el bug que la Fase 1 previno."""
    from datetime import datetime
    from fastapi import HTTPException
    from services.estudio.commands.reserva import SueltoItem, agregar_turno_embebido

    _crear_pedido_contenedor(conn, fecha_desde="2032-03-10", fecha_hasta="2032-03-13")
    # El pedido contenedor YA usa las 2 unidades del suelto en su ventana.
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
        "VALUES (%s,%s,2,1000,3000,'jornada')",
        (PEDIDO_ID, EQ_SUELTO_ID),
    )
    estudio = _centinela(conn)

    with pytest.raises(HTTPException) as exc:
        agregar_turno_embebido(
            conn, PEDIDO_ID, estudio=estudio,
            fecha_desde=datetime(2032, 3, 11, 14, 0), fecha_hasta=datetime(2032, 3, 11, 16, 0),
            con_promo=False, sueltos=[SueltoItem(equipo_id=EQ_SUELTO_ID, cantidad=1)],
            espacio_monto=15000,
        )
    assert exc.value.status_code == 409
    # Ver el comentario de `test_agregar_turno_respeta_conflicto_de_espacio`
    # sobre por qué hace falta rollbackear acá antes de verificar.
    conn.rollback()
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM alquiler_turnos_estudio WHERE pedido_id=%s", (PEDIDO_ID,)
    ).fetchone()["n"] == 0


# ── Edición ──────────────────────────────────────────────────────────────────

def test_editar_turno_reprograma_y_no_choca_consigo_mismo(conn):
    from datetime import datetime
    from services.estudio.commands.reserva import agregar_turno_embebido, editar_turno_embebido

    _crear_pedido_contenedor(conn)
    estudio = _centinela(conn)
    turno_id, _ = agregar_turno_embebido(
        conn, PEDIDO_ID, estudio=estudio,
        fecha_desde=datetime(2032, 3, 11, 14, 0), fecha_hasta=datetime(2032, 3, 11, 16, 0),
        con_promo=False, sueltos=[], espacio_monto=15000,
    )

    editar_turno_embebido(conn, turno_id, fecha="2032-03-11", start="15:00", horas=2)

    turno = conn.execute("SELECT * FROM alquiler_turnos_estudio WHERE id=%s", (turno_id,)).fetchone()
    assert turno["fecha_desde"].strftime("%H:%M") == "15:00"
    assert turno["fecha_hasta"].strftime("%H:%M") == "17:00"


def test_editar_turno_no_choca_con_un_turno_hermano_del_mismo_pedido(conn):
    """`exclude_turno_estudio_id`, no `exclude_pedido_id` (Fase 1): dos turnos
    del MISMO pedido no deben poder pisarse entre sí solo porque comparten
    contenedor."""
    from datetime import datetime
    from fastapi import HTTPException
    from services.estudio.commands.reserva import agregar_turno_embebido, editar_turno_embebido

    _crear_pedido_contenedor(conn)
    estudio = _centinela(conn)
    turno_a, _ = agregar_turno_embebido(
        conn, PEDIDO_ID, estudio=estudio,
        fecha_desde=datetime(2032, 3, 11, 10, 0), fecha_hasta=datetime(2032, 3, 11, 12, 0),
        con_promo=False, sueltos=[], espacio_monto=10000,
    )
    turno_b, _ = agregar_turno_embebido(
        conn, PEDIDO_ID, estudio=estudio,
        fecha_desde=datetime(2032, 3, 12, 10, 0), fecha_hasta=datetime(2032, 3, 12, 12, 0),
        con_promo=False, sueltos=[], espacio_monto=10000,
    )

    # Reprogramar B a la MISMA franja de A — debe chocar (no auto-excluirse
    # por compartir pedido).
    with pytest.raises(HTTPException) as exc:
        editar_turno_embebido(conn, turno_b, fecha="2032-03-11", start="10:00", horas=2)
    assert exc.value.status_code == 409

    # Pero A sigue intacto y "editar A a su propia franja" (no-op real) no
    # debe chocar contra sí mismo.
    editar_turno_embebido(conn, turno_a, fecha="2032-03-11", start="10:00", horas=2)
    turno = conn.execute("SELECT * FROM alquiler_turnos_estudio WHERE id=%s", (turno_a,)).fetchone()
    assert turno["fecha_desde"].strftime("%H:%M") == "10:00"


def test_editar_turno_espacio_monto_none_vuelve_a_precio_de_lista(conn):
    from datetime import datetime
    from services.estudio.commands.reserva import agregar_turno_embebido, editar_turno_embebido

    _crear_pedido_contenedor(conn)
    conn.execute("UPDATE estudio SET precio_hora = 5000 WHERE id = 1")
    estudio = _centinela(conn)
    turno_id, _ = agregar_turno_embebido(
        conn, PEDIDO_ID, estudio=estudio,
        fecha_desde=datetime(2032, 3, 11, 14, 0), fecha_hasta=datetime(2032, 3, 11, 16, 0),
        con_promo=False, sueltos=[], espacio_monto=99999,  # tarifa negociada
    )
    editar_turno_embebido(conn, turno_id, espacio_monto=None)  # vuelve a lista

    items = _items_turno(conn, turno_id)
    assert items[0]["subtotal"] == 5000 * 2  # precio_hora × 2hs


def test_editar_turno_aplica_descuento_repartido_entre_items(conn):
    """El descuento del turno se reparte entre sus ítems (no en una columna
    aparte) — el centinela absorbe el remanente de redondeo."""
    from datetime import datetime
    from services.estudio.commands.reserva import (
        SueltoItem, agregar_turno_embebido, editar_turno_embebido,
    )

    _crear_pedido_contenedor(conn)
    estudio = _centinela(conn)
    turno_id, _ = agregar_turno_embebido(
        conn, PEDIDO_ID, estudio=estudio,
        fecha_desde=datetime(2032, 3, 11, 14, 0), fecha_hasta=datetime(2032, 3, 11, 16, 0),
        con_promo=False, sueltos=[SueltoItem(equipo_id=EQ_SUELTO_ID, cantidad=1)],
        espacio_monto=15000,
    )
    # bruto = 15000 (espacio) + precio de lista del suelto (lo que sea que
    # tenga seedeado `equipos.precio_jornada` para EQ_SUELTO_ID — puede ser 0
    # si no está seedeado; no importa para el test, se mide el DELTA).
    items_antes = _items_turno(conn, turno_id)
    bruto_antes = sum(it["subtotal"] for it in items_antes)

    # `espacio_monto` explícito de nuevo — su contrato es "None vuelve a
    # precio de lista" (igual que `editar_reserva`), así que omitirlo acá
    # recalcularía la tarifa negociada de $15.000 a la de lista, cambiando
    # `bruto_antes` de abajo del piso.
    editar_turno_embebido(
        conn, turno_id, espacio_monto=15000,
        descuento_manual_tipo="pct", descuento_manual_monto=0, descuento_pct=10.0,
    )

    items_despues = _items_turno(conn, turno_id)
    neto_despues = sum(it["subtotal"] for it in items_despues)
    assert neto_despues == pytest.approx(bruto_antes * 0.9, abs=1)

    turno = conn.execute("SELECT * FROM alquiler_turnos_estudio WHERE id=%s", (turno_id,)).fetchone()
    assert float(turno["descuento_pct"]) == 10.0

    pedido = _get_pedido(conn, PEDIDO_ID)
    assert pedido["monto_total"] == 30000 + neto_despues


def test_editar_turno_descuento_none_no_toca_lo_persistido(conn):
    from datetime import datetime
    from services.estudio.commands.reserva import agregar_turno_embebido, editar_turno_embebido

    _crear_pedido_contenedor(conn)
    estudio = _centinela(conn)
    turno_id, _ = agregar_turno_embebido(
        conn, PEDIDO_ID, estudio=estudio,
        fecha_desde=datetime(2032, 3, 11, 14, 0), fecha_hasta=datetime(2032, 3, 11, 16, 0),
        con_promo=False, sueltos=[], espacio_monto=15000,
    )
    editar_turno_embebido(
        conn, turno_id, espacio_monto=15000, descuento_pct=20.0, descuento_manual_tipo="pct",
    )

    # Otra edición que NO menciona el descuento (reprograma solamente) —
    # el 20% tiene que sobrevivir. `espacio_monto` explícito de nuevo, mismo
    # motivo que en `test_editar_turno_aplica_descuento_repartido_entre_items`.
    editar_turno_embebido(
        conn, turno_id, espacio_monto=15000, fecha="2032-03-11", start="16:00", horas=2,
    )

    turno = conn.execute("SELECT * FROM alquiler_turnos_estudio WHERE id=%s", (turno_id,)).fetchone()
    assert float(turno["descuento_pct"]) == 20.0
    items = _items_turno(conn, turno_id)
    assert sum(it["subtotal"] for it in items) == pytest.approx(15000 * 0.8, abs=1)


# ── Baja ─────────────────────────────────────────────────────────────────────

def test_eliminar_turno_borra_items_y_recalcula_el_total(conn):
    from datetime import datetime
    from services.estudio.commands.reserva import agregar_turno_embebido, eliminar_turno_embebido

    _crear_pedido_contenedor(conn)
    estudio = _centinela(conn)
    turno_id, _ = agregar_turno_embebido(
        conn, PEDIDO_ID, estudio=estudio,
        fecha_desde=datetime(2032, 3, 11, 14, 0), fecha_hasta=datetime(2032, 3, 11, 16, 0),
        con_promo=False, sueltos=[], espacio_monto=15000,
    )
    assert _get_pedido(conn, PEDIDO_ID)["monto_total"] == 30000 + 15000

    eliminar_turno_embebido(conn, turno_id)

    assert conn.execute(
        "SELECT COUNT(*) AS n FROM alquiler_turnos_estudio WHERE id=%s", (turno_id,)
    ).fetchone()["n"] == 0
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM alquiler_items WHERE turno_estudio_id=%s", (turno_id,)
    ).fetchone()["n"] == 0
    assert _get_pedido(conn, PEDIDO_ID)["monto_total"] == 30000


def test_eliminar_turno_inexistente_404(conn):
    from fastapi import HTTPException
    from services.estudio.commands.reserva import eliminar_turno_embebido

    with pytest.raises(HTTPException) as exc:
        eliminar_turno_embebido(conn, 9_488_998)
    assert exc.value.status_code == 404


def test_eliminar_un_turno_deja_intacto_a_su_hermano(conn):
    """Multi-turno por pedido: borrar uno no toca al otro."""
    from datetime import datetime
    from services.estudio.commands.reserva import agregar_turno_embebido, eliminar_turno_embebido

    _crear_pedido_contenedor(conn)
    estudio = _centinela(conn)
    turno_a, _ = agregar_turno_embebido(
        conn, PEDIDO_ID, estudio=estudio,
        fecha_desde=datetime(2032, 3, 11, 10, 0), fecha_hasta=datetime(2032, 3, 11, 12, 0),
        con_promo=False, sueltos=[], espacio_monto=10000,
    )
    turno_b, _ = agregar_turno_embebido(
        conn, PEDIDO_ID, estudio=estudio,
        fecha_desde=datetime(2032, 3, 12, 10, 0), fecha_hasta=datetime(2032, 3, 12, 12, 0),
        con_promo=False, sueltos=[], espacio_monto=20000,
    )
    assert _get_pedido(conn, PEDIDO_ID)["monto_total"] == 30000 + 10000 + 20000

    eliminar_turno_embebido(conn, turno_a)

    assert _get_pedido(conn, PEDIDO_ID)["monto_total"] == 30000 + 20000
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM alquiler_turnos_estudio WHERE id=%s", (turno_b,)
    ).fetchone()["n"] == 1


# ── Listado (services/alquileres/queries/detalle.py::_turnos_embebidos) ──────

# ── Taller: editar/eliminar rechazan el contenedor (2026-08-13) ──────────────
# `_crear_turnos_taller_del_mes` (services/talleres/commands/economia.py) crea
# turnos embebidos por clase para un pedido `tipo='taller'` sin pasar por
# `agregar_turno_embebido` (que los rechazaría) — la fuente de verdad de esas
# clases/franjas es Talleres (`clases_taller`), no este pedido. Editar/borrar
# un turno de taller por esta vía (defensa en profundidad — el front tampoco
# lo expone, ver `TurnosEstudioSection`) desincronizaría la fila del
# `alquiler_turnos_estudio` de la clase real sin que nada lo note.


def _crear_pedido_taller_con_turno(conn):
    estudio = _centinela(conn)
    conn.execute(
        "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, "
        "fecha_desde, fecha_hasta, monto_total) "
        "VALUES (%s,'Taller CRUD turno','confirmado','taller','2032-04-01','2032-04-30',15000)",
        (PEDIDO_TALLER_ID,),
    )
    turno_id = conn.execute(
        "INSERT INTO alquiler_turnos_estudio (pedido_id, fecha_desde, fecha_hasta) "
        "VALUES (%s,'2032-04-11 10:00','2032-04-11 13:00') RETURNING id",
        (PEDIDO_TALLER_ID,),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, "
        "cobro_modo, turno_estudio_id) VALUES (%s,%s,1,15000,15000,'fijo',%s)",
        (PEDIDO_TALLER_ID, estudio["equipo_id"], turno_id),
    )
    return turno_id


def test_editar_turno_rechaza_pedido_taller(conn):
    from fastapi import HTTPException
    from services.estudio.commands.reserva import editar_turno_embebido

    turno_id = _crear_pedido_taller_con_turno(conn)
    with pytest.raises(HTTPException) as exc:
        editar_turno_embebido(conn, turno_id, fecha="2032-04-11", start="15:00", horas=2)
    assert exc.value.status_code == 409

    # No se tocó nada: la franja original sigue igual.
    turno = conn.execute(
        "SELECT * FROM alquiler_turnos_estudio WHERE id=%s", (turno_id,)
    ).fetchone()
    assert turno["fecha_desde"].strftime("%H:%M") == "10:00"


def test_eliminar_turno_rechaza_pedido_taller(conn):
    from fastapi import HTTPException
    from services.estudio.commands.reserva import eliminar_turno_embebido

    turno_id = _crear_pedido_taller_con_turno(conn)
    with pytest.raises(HTTPException) as exc:
        eliminar_turno_embebido(conn, turno_id)
    assert exc.value.status_code == 409

    assert conn.execute(
        "SELECT COUNT(*) AS n FROM alquiler_turnos_estudio WHERE id=%s", (turno_id,)
    ).fetchone()["n"] == 1


def test_get_alquiler_detail_incluye_turnos_embebidos(conn):
    from datetime import datetime
    from services.alquileres.queries.detalle import _get_alquiler_detail
    from services.estudio.commands.reserva import agregar_turno_embebido

    _crear_pedido_contenedor(conn)
    estudio = _centinela(conn)
    turno_id, _ = agregar_turno_embebido(
        conn, PEDIDO_ID, estudio=estudio,
        fecha_desde=datetime(2032, 3, 11, 14, 0), fecha_hasta=datetime(2032, 3, 11, 16, 0),
        con_promo=False, sueltos=[], espacio_monto=15000,
    )

    pedido = _get_alquiler_detail(conn, PEDIDO_ID)

    assert len(pedido["turnos_estudio_embebidos"]) == 1
    t = pedido["turnos_estudio_embebidos"][0]
    assert t["id"] == turno_id
    assert t["monto_total"] == 15000
    # El ítem del turno también sale en `items`, con su propio turno_estudio_id.
    item_turno = next(it for it in pedido["items"] if it.get("turno_estudio_id") == turno_id)
    assert item_turno["subtotal"] == 15000
