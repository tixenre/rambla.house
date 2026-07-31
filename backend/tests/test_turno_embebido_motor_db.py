"""#1308 rediseño "turno como ítem", Fase 1 — el turno del Estudio EMBEBIDO
(`alquiler_turnos_estudio` + `alquiler_items.turno_estudio_id`) contra Postgres
REAL (no el fake in-memory de `test_gate_turno_embebido_c5.py`).

Verifica:
  1. El escenario que motivó todo el rediseño: un equipo de 3 días + un turno
     embebido de 2hs en el MISMO pedido — el espacio queda ocupado SOLO esas
     2hs (COALESCE en `_centinela_libre`), no los 3 días del pedido contenedor.
  2. El edge case de auto-conflicto: el MISMO equipo_id usado como ítem normal
     del pedido y como suelto de un turno embebido del MISMO pedido, con
     ventanas que se pisan y stock=1 — el gate genérico (`validar_stock`)
     rechaza (no lo esconde la exclusión de `turno_estudio_id`).
  3. `_apply_pedido_items` preserva un turno embebido intacto (ítems + su
     aporte a `monto_total`, excluido del descuento automático) al reemplazar
     la lista de equipos del pedido.
  4. `_revalidar_turnos_embebidos`/`_revalidar_stock` detecta cuando OTRO
     pedido le ganó el espacio al turno embebido entre su creación y una
     transición de estado posterior.

La CREACIÓN real de un turno embebido (lock-antes-de-insertar, el endpoint) es
Fase 4 — acá los datos del turno se siembran con INSERT directo, simulando lo
que esa fase va a hacer, para poder probar el MOTOR ya construido en la Fase 1
sin esperar a que exista la UI/el endpoint.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_turno_embebido_motor_db.py -v -m integration
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

# IDs altos y reservados para este archivo, para no chocar con datos existentes
# ni con otros *_db.py (9_000_xxx y 9_476_xxx ya están tomados por otros).
CLIENTE_ID = 9_481_001
EQUIPO_NORMAL_ID = 9_481_010  # equipo real de catálogo, stock=1 (fuerza el conflicto)
PEDIDO_MIXTO_ID = 9_481_020   # equipo 3 días + turno embebido 2hs
PEDIDO_OTRO_ID = 9_481_021    # otro pedido, para el escenario "3 días + 2hs"
TURNO_A_ID = 9_481_030
TURNO_B_ID = 9_481_031


@pytest.fixture
def db():
    from database import get_db, init_db

    init_db()  # idempotente
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'Turno','Embebido','turno-embebido@test.com','+5491100000099')",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad) VALUES (%s, %s, 1)",
            (EQUIPO_NORMAL_ID, "Micrófono de test (turno embebido)"),
        )
        conn.commit()
    finally:
        conn.close()

    yield

    conn = get_db()
    try:
        _limpiar(conn)
        conn.commit()
    finally:
        conn.close()


def _limpiar(conn):
    pedidos = (PEDIDO_MIXTO_ID, PEDIDO_OTRO_ID)
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN (%s,%s) OR equipo_id = %s",
        (*pedidos, EQUIPO_NORMAL_ID),
    )
    conn.execute(
        "DELETE FROM alquiler_turnos_estudio WHERE pedido_id IN (%s,%s)", pedidos
    )
    conn.execute("DELETE FROM alquileres WHERE id IN (%s,%s)", pedidos)
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQUIPO_NORMAL_ID,))
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))


def _centinela_id(conn) -> int:
    return conn.execute("SELECT equipo_id FROM estudio WHERE id = 1").fetchone()["equipo_id"]


def _crear_pedido_mixto(conn, *, equipo_fd="2030-01-10", equipo_fh="2030-01-13"):
    """Pedido `tipo='diaria'` con UN ítem de equipo (rango de días) + UN turno
    embebido (`alquiler_turnos_estudio`) de 2hs el mismo `equipo_fd` — el
    escenario exacto que motivó el rediseño (3 días de equipo + 2hs de
    estudio en el mismo pedido)."""
    conn.execute(
        "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, "
        "fecha_desde, fecha_hasta, numero_pedido) "
        "VALUES (%s,%s,'Turno Embebido','confirmado',%s,%s,948102)",
        (PEDIDO_MIXTO_ID, CLIENTE_ID, equipo_fd, equipo_fh),
    )
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
        "VALUES (%s,%s,1,5000,15000)",
        (PEDIDO_MIXTO_ID, EQUIPO_NORMAL_ID),
    )
    turno_fd, turno_fh = f"{equipo_fd} 14:00", f"{equipo_fd} 16:00"
    turno_id = conn.execute(
        "INSERT INTO alquiler_turnos_estudio (pedido_id, fecha_desde, fecha_hasta) "
        "VALUES (%s,%s,%s) RETURNING id",
        (PEDIDO_MIXTO_ID, turno_fd, turno_fh),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO alquiler_items "
        "(pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo, turno_estudio_id) "
        "VALUES (%s,%s,1,20000,20000,'fijo',%s)",
        (PEDIDO_MIXTO_ID, _centinela_id(conn), turno_id),
    )
    # monto_total = 15000 (equipo, 3 jornadas × 5000) + 20000 (turno, 'fijo') —
    # un INSERT directo no pasa por _recalcular_total_pedido, así que se fija
    # a mano para que el "antes" del test represente un pedido real.
    conn.execute(
        "UPDATE alquileres SET monto_total = 35000 WHERE id = %s", (PEDIDO_MIXTO_ID,)
    )
    return turno_id, turno_fd, turno_fh


class TestEscenarioOriginal:
    """3 días de equipo + 2hs de turno embebido, mismo pedido — el espacio se
    ocupa SOLO esas 2hs."""

    def test_el_espacio_se_bloquea_solo_las_2hs_no_los_3_dias(self, db):
        from database import get_db
        from services.estudio.queries.disponibilidad import _centinela_libre

        conn = get_db()
        try:
            turno_id, turno_fd, turno_fh = _crear_pedido_mixto(conn)
            conn.commit()

            from database import to_datetime
            fd, fh = to_datetime(turno_fd), to_datetime(turno_fh)
            cid = _centinela_id(conn)

            # Dentro de la franja del turno (14-16hs del mismo día): OCUPADO.
            assert _centinela_libre(conn, cid, fd, fh, buffer_horas=0) is False

            # Una hora ANTES o DESPUÉS, el mismo día: LIBRE — si el bug
            # original existiera (bloquear los 3 días del pedido), esto
            # fallaría (reportaría ocupado igual).
            manana_misma_hora = to_datetime(f"{turno_fd.split()[0]} 09:00"), \
                to_datetime(f"{turno_fd.split()[0]} 11:00")
            assert _centinela_libre(conn, cid, *manana_misma_hora, buffer_horas=0) is True

            tarde_misma_hora = to_datetime(f"{turno_fd.split()[0]} 18:00"), \
                to_datetime(f"{turno_fd.split()[0]} 20:00")
            assert _centinela_libre(conn, cid, *tarde_misma_hora, buffer_horas=0) is True

            # El día SIGUIENTE (todavía dentro del rango de 3 días del equipo,
            # fuera de la franja del turno): LIBRE.
            dia_siguiente = to_datetime("2030-01-11 14:00"), to_datetime("2030-01-11 16:00")
            assert _centinela_libre(conn, cid, *dia_siguiente, buffer_horas=0) is True
        finally:
            conn.close()

    def test_otro_turno_standalone_choca_en_la_franja_del_embebido(self, db):
        """Un turno standalone (o cualquier otro pedido con un ítem del
        centinela) que pise exactamente la franja del turno embebido debe
        rechazarse — confirma que el embebido SÍ compite normalmente, no que
        quedó invisible por accidente."""
        from database import get_db
        from services.estudio.queries.disponibilidad import _centinela_libre

        conn = get_db()
        try:
            _turno_id, turno_fd, turno_fh = _crear_pedido_mixto(conn)
            conn.commit()
            from database import to_datetime
            cid = _centinela_id(conn)
            assert _centinela_libre(
                conn, cid, to_datetime(turno_fd), to_datetime(turno_fh), buffer_horas=0
            ) is False
        finally:
            conn.close()


class TestAutoConflicto:
    """El mismo equipo_id usado como ítem normal del pedido Y como suelto de
    un turno embebido del MISMO pedido, stock=1, ventanas superpuestas."""

    def test_gate_generico_rechaza_el_auto_conflicto(self, db):
        """`validar_stock_hipotetico` (sin excluir el pedido contenedor —
        sentinel `0`, el criterio de creación de la Fase 4) debe VER la
        demanda del ítem normal del pedido y rechazar el suelto del turno si
        se solapan y no hay 2 unidades."""
        from collections import namedtuple

        from database import get_db
        from reservas import validar_stock_hipotetico

        conn = get_db()
        try:
            equipo_fd, equipo_fh = "2030-01-10", "2030-01-13"
            conn.execute(
                "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, "
                "fecha_desde, fecha_hasta, numero_pedido) "
                "VALUES (%s,%s,'Auto Conflicto','confirmado',%s,%s,948103)",
                (PEDIDO_MIXTO_ID, CLIENTE_ID, equipo_fd, equipo_fh),
            )
            # Ítem NORMAL del pedido: el equipo compartido, para TODO el rango.
            conn.execute(
                "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
                "VALUES (%s,%s,1,5000,15000)",
                (PEDIDO_MIXTO_ID, EQUIPO_NORMAL_ID),
            )
            conn.commit()

            Item = namedtuple("Item", ["equipo_id", "cantidad"])
            turno_fd, turno_fh = f"{equipo_fd} 14:00", f"{equipo_fd} 16:00"
            # Sentinel 0 (Fase 4, creación): no excluye NADA — debe ver la
            # demanda del ítem normal ya persistido del mismo pedido.
            problemas = validar_stock_hipotetico(
                conn, 0, turno_fd, turno_fh, [Item(EQUIPO_NORMAL_ID, 1)]
            )
            assert problemas, (
                "el suelto del turno embebido debería chocar contra el ítem "
                "normal del MISMO pedido para el mismo equipo (stock=1) — "
                "el auto-conflicto no se cazó"
            )
        finally:
            conn.close()

    def test_sin_solapar_ventanas_no_hay_conflicto(self, db):
        """Control: si las ventanas NO se solapan (el suelto pide una franja
        fuera del rango de días del ítem normal), no debería haber conflicto
        — confirma que el test anterior discrimina por fecha, no por
        equipo_id a secas."""
        from collections import namedtuple

        from database import get_db
        from reservas import validar_stock_hipotetico

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, "
                "fecha_desde, fecha_hasta, numero_pedido) "
                "VALUES (%s,%s,'Sin Solape','confirmado','2030-01-10','2030-01-13',948104)",
                (PEDIDO_MIXTO_ID, CLIENTE_ID),
            )
            conn.execute(
                "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
                "VALUES (%s,%s,1,5000,15000)",
                (PEDIDO_MIXTO_ID, EQUIPO_NORMAL_ID),
            )
            conn.commit()

            Item = namedtuple("Item", ["equipo_id", "cantidad"])
            problemas = validar_stock_hipotetico(
                conn, 0, "2030-02-01 14:00", "2030-02-01 16:00", [Item(EQUIPO_NORMAL_ID, 1)]
            )
            assert not problemas, f"no debería haber conflicto sin solape de fechas: {problemas}"
        finally:
            conn.close()


class TestApplyPedidoItemsPreservaElTurno:
    def test_reemplazar_equipos_no_borra_el_turno_ni_su_plata(self, db):
        from database import get_db
        from services.alquileres.commands.items import _apply_pedido_items

        conn = get_db()
        try:
            turno_id, _fd, _fh = _crear_pedido_mixto(conn)
            conn.commit()

            monto_antes = conn.execute(
                "SELECT monto_total FROM alquileres WHERE id=%s", (PEDIDO_MIXTO_ID,)
            ).fetchone()["monto_total"]
            assert monto_antes == 35000  # 15000 (equipo) + 20000 (turno)

            class _Item:
                def __init__(self, equipo_id, cantidad, precio_jornada, cobro_modo="jornada", nombre_libre=None):
                    self.equipo_id = equipo_id
                    self.cantidad = cantidad
                    self.precio_jornada = precio_jornada
                    self.cobro_modo = cobro_modo
                    self.nombre_libre = nombre_libre

            # El front reenvía SOLO la lista de equipos (nunca sabe del turno
            # embebido) — el mismo equipo, otra cantidad.
            _apply_pedido_items(conn, PEDIDO_MIXTO_ID, [_Item(EQUIPO_NORMAL_ID, 2, 5000)])
            conn.commit()

            items_turno = conn.execute(
                "SELECT id FROM alquiler_items WHERE turno_estudio_id = %s", (turno_id,)
            ).fetchall()
            assert len(items_turno) == 1, "el ítem del turno embebido no sobrevivió al reemplazo"

            turno_row = conn.execute(
                "SELECT id FROM alquiler_turnos_estudio WHERE id = %s", (turno_id,)
            ).fetchone()
            assert turno_row is not None, "el grupo alquiler_turnos_estudio se perdió"

            monto_despues = conn.execute(
                "SELECT monto_total FROM alquileres WHERE id=%s", (PEDIDO_MIXTO_ID,)
            ).fetchone()["monto_total"]
            # 2 × 5000 × 3 jornadas (10/1 a 13/1) = 30000 (equipo) + 20000 (turno).
            assert monto_despues == 50000, (
                f"monto_total debería incluir el equipo NUEVO + el turno preservado, "
                f"dio {monto_despues}"
            )
        finally:
            conn.close()


class TestRevalidarTurnosEmbebidos:
    def test_detecta_cuando_otro_pedido_le_gano_el_espacio(self, db):
        """Simula: el turno embebido se creó libre; DESPUÉS, otro pedido
        (standalone o embebido en otro pedido) tomó esa misma franja del
        centinela por fuera — `_revalidar_turnos_embebidos` tiene que
        detectarlo al transicionar de estado."""
        from database import get_db
        from services.estudio.queries.disponibilidad import _revalidar_turnos_embebidos

        conn = get_db()
        try:
            turno_id, turno_fd, turno_fh = _crear_pedido_mixto(conn)
            # Otro pedido standalone del Estudio que ocupa EXACTAMENTE la
            # misma franja del centinela — simula "alguien más lo tomó".
            conn.execute(
                "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, "
                "fecha_desde, fecha_hasta, numero_pedido, tipo) "
                "VALUES (%s,%s,'Otro Turno','confirmado',%s,%s,948105,'estudio')",
                (PEDIDO_OTRO_ID, CLIENTE_ID, turno_fd, turno_fh),
            )
            conn.execute(
                "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
                "VALUES (%s,%s,1,20000,20000,'fijo')",
                (PEDIDO_OTRO_ID, _centinela_id(conn)),
            )
            conn.commit()

            errores = _revalidar_turnos_embebidos(conn, PEDIDO_MIXTO_ID)
            assert errores, "debería reportar que el espacio ya no está libre para el turno embebido"
        finally:
            conn.close()

    def test_sin_competencia_no_reporta_error(self, db):
        from database import get_db
        from services.estudio.queries.disponibilidad import _revalidar_turnos_embebidos

        conn = get_db()
        try:
            _crear_pedido_mixto(conn)
            conn.commit()
            errores = _revalidar_turnos_embebidos(conn, PEDIDO_MIXTO_ID)
            assert errores == []
        finally:
            conn.close()

    def test_pedido_sin_turnos_embebidos_es_no_op(self, db):
        from database import get_db
        from services.estudio.queries.disponibilidad import _revalidar_turnos_embebidos

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, "
                "fecha_desde, fecha_hasta, numero_pedido) "
                "VALUES (%s,%s,'Sin Turno','confirmado','2030-01-10','2030-01-13',948106)",
                (PEDIDO_MIXTO_ID, CLIENTE_ID),
            )
            conn.commit()
            assert _revalidar_turnos_embebidos(conn, PEDIDO_MIXTO_ID) == []
        finally:
            conn.close()
