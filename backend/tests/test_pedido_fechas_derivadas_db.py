"""Un pedido cuyo ÚNICO contenido es un turno del Estudio deriva sus fechas del
turno — `services.alquileres.commands.items.sincronizar_fechas_con_turnos`.

Bug real (pedido #454): un pedido cargado a mano SIN equipos, con un solo turno
del Estudio del 24/07, se quedaba con el rango que puso el alta por default
(1-2 de agosto). Las fechas de un pedido son la ventana de retiro/devolución de
los EQUIPOS y el turno guarda las suyas aparte, así que con cero equipos ese
rango no representa nada. Consecuencias medidas: Estadísticas lo contaba en el
mes equivocado (agrupa por `to_char(fecha_desde,'YYYY-MM')`), y el calendario /
"salen hoy" / "devuelven hoy" lo ubicaban en un día en el que no pasa nada.

Lo que estos tests fijan es la ASIMETRÍA, que es la parte fácil de romper:
con equipos manda la ventana de equipos; sin equipos manda el turno.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_pedido_fechas_derivadas_db.py -v -m integration
"""
import os
from datetime import datetime
from urllib.parse import urlparse

import pytest

_OPT_IN = os.getenv("RESERVAS_DB_TEST") == "1"
_DB_URL = os.getenv("DATABASE_URL", "")
_DB_NAME = urlparse(_DB_URL).path.lstrip("/") if _DB_URL else ""


def _looks_like_test_db() -> bool:
    return bool(_DB_NAME) and "test" in _DB_NAME.lower()


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _OPT_IN,
        reason="opt-in: setear RESERVAS_DB_TEST=1 + DATABASE_URL a una base de prueba",
    ),
    pytest.mark.skipif(
        _OPT_IN and not _looks_like_test_db(),
        reason=f"DATABASE_URL ({_DB_NAME!r}) no parece base de test — abortado por seguridad",
    ),
]

# Ids altos dedicados (bloque 9_491_xxx, sin uso en otros *_db.py).
CLIENTE_ID = 9_491_001
EQ_RENTAL_ID = 9_491_010
PEDIDO_ID = 9_491_020

# El rango "basura" que pone el alta manual (hoy → mañana), lejos del turno.
ALTA_DESDE, ALTA_HASTA = "2033-08-01", "2033-08-02"
TURNO_DESDE = datetime(2033, 7, 24, 18, 30)
TURNO_HASTA = datetime(2033, 7, 24, 20, 30)


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


def _crear_pedido(conn, *, con_equipo: bool):
    conn.execute(
        "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
        "VALUES (%s,'Fechas','Derivadas','fechas-derivadas@test.com','+5491100000094') "
        "ON CONFLICT (id) DO NOTHING",
        (CLIENTE_ID,),
    )
    conn.execute(
        "INSERT INTO equipos (id, nombre, cantidad, dueno) "
        "VALUES (%s,'Cámara test fechas derivadas',1,'Rental') ON CONFLICT (id) DO NOTHING",
        (EQ_RENTAL_ID,),
    )
    conn.execute(
        "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
        "fecha_desde, fecha_hasta, monto_total) "
        "VALUES (%s,%s,'Fechas Derivadas','confirmado','diaria',%s,%s,0)",
        (PEDIDO_ID, CLIENTE_ID, ALTA_DESDE, ALTA_HASTA),
    )
    if con_equipo:
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo) VALUES (%s,%s,1,10000,10000,'jornada')",
            (PEDIDO_ID, EQ_RENTAL_ID),
        )


def _fechas(conn):
    r = conn.execute(
        "SELECT fecha_desde, fecha_hasta FROM alquileres WHERE id=%s", (PEDIDO_ID,)
    ).fetchone()
    return r["fecha_desde"], r["fecha_hasta"]


def _agregar_turno(conn, desde=TURNO_DESDE, hasta=TURNO_HASTA):
    from services.estudio.commands.reserva import agregar_turno_embebido

    turno_id, _ = agregar_turno_embebido(
        conn, PEDIDO_ID, estudio=_centinela(conn),
        fecha_desde=desde, fecha_hasta=hasta,
        con_promo=False, sueltos=[], espacio_monto=120000,
    )
    return turno_id


def test_pedido_sin_equipos_toma_las_fechas_del_turno(conn):
    """El caso del pedido #454, de punta a punta."""
    _crear_pedido(conn, con_equipo=False)
    assert _fechas(conn)[0].strftime("%Y-%m-%d") == "2033-08-01"  # el default del alta

    _agregar_turno(conn)

    desde, hasta = _fechas(conn)
    assert desde == TURNO_DESDE, "el pedido tiene que caer el día del turno, no el del alta"
    assert hasta == TURNO_HASTA
    # Lo que de verdad importaba: el mes con el que lo agrupa Estadísticas.
    assert desde.strftime("%Y-%m") == "2033-07"


def test_pedido_CON_equipos_conserva_su_ventana_de_retiro(conn):
    """La otra mitad de la asimetría: un equipo se retira y se devuelve en fechas
    reales, un turno no. Con equipos, la ventana de retiro MANDA — el turno se
    muestra aparte, con su propia franja."""
    _crear_pedido(conn, con_equipo=True)
    _agregar_turno(conn)

    desde, hasta = _fechas(conn)
    assert desde.strftime("%Y-%m-%d") == "2033-08-01", "no debe pisar la ventana de equipos"
    assert hasta.strftime("%Y-%m-%d") == "2033-08-02"


def test_editar_el_turno_arrastra_las_fechas_del_pedido(conn):
    from services.estudio.commands.reserva import editar_turno_embebido

    _crear_pedido(conn, con_equipo=False)
    turno_id = _agregar_turno(conn)

    editar_turno_embebido(conn, turno_id, fecha="2033-07-30", start="10:00", horas=3)

    desde, hasta = _fechas(conn)
    assert desde == datetime(2033, 7, 30, 10, 0)
    assert hasta == datetime(2033, 7, 30, 13, 0)


def test_con_dos_turnos_el_pedido_cubre_de_la_primera_a_la_ultima(conn):
    _crear_pedido(conn, con_equipo=False)
    _agregar_turno(conn)  # 24/07 18:30-20:30
    _agregar_turno(conn, desde=datetime(2033, 7, 28, 9, 0), hasta=datetime(2033, 7, 28, 11, 0))

    desde, hasta = _fechas(conn)
    assert desde == TURNO_DESDE
    assert hasta == datetime(2033, 7, 28, 11, 0)


def test_borrar_el_ultimo_turno_no_deja_al_pedido_sin_fechas(conn):
    """Sin turnos no hay de dónde derivar. Vaciar las fechas sería peor que
    dejarlas viejas: `ESTADOS_REQUIEREN_FECHAS` las necesita."""
    from services.estudio.commands.reserva import eliminar_turno_embebido

    _crear_pedido(conn, con_equipo=False)
    turno_id = _agregar_turno(conn)
    assert _fechas(conn)[0] == TURNO_DESDE

    eliminar_turno_embebido(conn, turno_id)

    desde, hasta = _fechas(conn)
    assert desde is not None and hasta is not None


def test_sacar_el_ultimo_equipo_hace_que_el_pedido_caiga_en_el_turno(conn):
    """Caso simétrico, vía el editor genérico de ítems: mientras hubo equipo la
    ventana era la del retiro; al quedarse sin ninguno, pasa a mandar el turno."""
    from services.alquileres.commands.items import _apply_pedido_items

    _crear_pedido(conn, con_equipo=True)
    _agregar_turno(conn)
    assert _fechas(conn)[0].strftime("%Y-%m-%d") == "2033-08-01"

    _apply_pedido_items(conn, PEDIDO_ID, [])  # el admin borra el único equipo

    assert _fechas(conn)[0] == TURNO_DESDE


def test_un_turno_EMBEBIDO_cuenta_como_contenido_del_pedido(conn):
    """Segundo bug, encontrado arreglando el primero: `_tiene_turno_estudio_activo`
    solo miraba el mecanismo VIEJO (`pedido_principal_id`, turno vinculado) y era
    ciego al actual (`alquiler_turnos_estudio`, turno embebido — #1308 Fase 4).

    Efecto: sacar el último equipo de un pedido NO-borrador cuyo contenido real
    era un turno embebido se rechazaba con "Debe tener al menos un ítem", aunque
    el pedido sí tenía contenido. Es la misma clase de bug que ese helper ya
    había arreglado para el mecanismo viejo — el rediseño no lo arrastró."""
    from services.alquileres.queries.detalle import _tiene_turno_estudio_activo

    _crear_pedido(conn, con_equipo=True)
    assert _tiene_turno_estudio_activo(conn, PEDIDO_ID) is False

    _agregar_turno(conn)
    assert _tiene_turno_estudio_activo(conn, PEDIDO_ID) is True
