"""#1308 rediseño "turno como ítem", Fase 2.3 — un turno del Estudio EMBEBIDO
(`alquiler_turnos_estudio`) en un pedido de alquiler normal (`tipo='diaria'`)
tiene que seguir apareciendo en el dashboard/calendario admin, en SU PROPIO
día — que puede no coincidir con el retiro/devolución de los equipos del
pedido contenedor.

Ambos pedidos de este fixture tienen su equipo propio con fecha MUY lejos de
hoy/mañana (+30/+31 días) — si el turno embebido apareciera solo porque el
pedido contenedor "ya estaba ahí", el test no probaría nada; acá el pedido
contenedor NO tiene ninguna razón propia para aparecer hoy/mañana, así que
si aparece es exclusivamente por su turno embebido.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_dashboard_turno_embebido_db.py -v -m integration
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
    pytest.mark.skipif(
        not _OPT_IN,
        reason="opt-in: setear RESERVAS_DB_TEST=1 + DATABASE_URL a una base de prueba",
    ),
    pytest.mark.skipif(
        _OPT_IN and not _looks_like_test_db(),
        reason=f"DATABASE_URL ({_DB_NAME!r}) no parece base de test — abortado por seguridad",
    ),
]

import main  # noqa: E402 — importado después del gating, mismo patrón que los otros *_db.py

# Ids altos dedicados (bloque 9_484_xxx, sin uso en otros *_db.py).
PEDIDO_A_ID = 9_484_101   # turno embebido HOY
PEDIDO_B_ID = 9_484_102   # turno embebido MAÑANA
PEDIDO_TALLER_ID = 9_484_103  # taller con turno embebido por clase HOY (2026-08-13)
EQ_RENTAL_A = 9_484_201
EQ_RENTAL_B = 9_484_202


def _limpiar(conn):
    ids = (PEDIDO_A_ID, PEDIDO_B_ID, PEDIDO_TALLER_ID)
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id IN (%s,%s,%s)", ids)
    conn.execute("DELETE FROM alquiler_turnos_estudio WHERE pedido_id IN (%s,%s,%s)", ids)
    conn.execute("DELETE FROM alquileres WHERE id IN (%s,%s,%s)", ids)
    conn.execute("DELETE FROM equipos WHERE id IN (%s,%s)", (EQ_RENTAL_A, EQ_RENTAL_B))


@pytest.fixture(scope="module")
def client_con_db():
    from database import init_db
    from fastapi.testclient import TestClient

    init_db()
    with TestClient(main.app, raise_server_exceptions=True) as c:
        if main.db_init_thread is not None:
            main.db_init_thread.join(timeout=60)
        yield c


@pytest.fixture
def setup(monkeypatch):
    from database import get_db, now_ar
    from datetime import timedelta

    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    conn = get_db()
    try:
        _limpiar(conn)
        centinela_id = conn.execute("SELECT equipo_id FROM estudio WHERE id=1").fetchone()["equipo_id"]
        assert centinela_id
        centinela_nombre = conn.execute(
            "SELECT nombre FROM equipos WHERE id=%s", (centinela_id,)
        ).fetchone()["nombre"]

        hoy = now_ar()
        lejos_desde = (hoy + timedelta(days=30)).isoformat()
        lejos_hasta = (hoy + timedelta(days=33)).isoformat()

        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES "
            "(%s,'Cámara test dashboard turno A',1,'Rental'),"
            "(%s,'Cámara test dashboard turno B',1,'Rental')",
            (EQ_RENTAL_A, EQ_RENTAL_B),
        )

        # Pedido A: equipo se retira/devuelve MUY lejos (+30/+33 días) — su
        # turno embebido es HOY.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,'Cliente turno embebido A','confirmado','diaria',%s,%s,45000)",
            (PEDIDO_A_ID, lejos_desde, lejos_hasta),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo) VALUES (%s,%s,1,10000,30000,'jornada')",
            (PEDIDO_A_ID, EQ_RENTAL_A),
        )
        turno_a_id = conn.execute(
            "INSERT INTO alquiler_turnos_estudio (pedido_id, fecha_desde, fecha_hasta) "
            "VALUES (%s,%s,%s) RETURNING id",
            (PEDIDO_A_ID, hoy.replace(hour=14, minute=0, second=0, microsecond=0).isoformat(),
             hoy.replace(hour=16, minute=0, second=0, microsecond=0).isoformat()),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal, "
            "cobro_modo, turno_estudio_id) VALUES (%s,%s,1,15000,'fijo',%s)",
            (PEDIDO_A_ID, centinela_id, turno_a_id),
        )

        # Pedido B: equipo también lejos — su turno embebido es MAÑANA.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,'Cliente turno embebido B','confirmado','diaria',%s,%s,42000)",
            (PEDIDO_B_ID, lejos_desde, lejos_hasta),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo) VALUES (%s,%s,1,10000,30000,'jornada')",
            (PEDIDO_B_ID, EQ_RENTAL_B),
        )
        manana = hoy + timedelta(days=1)
        turno_b_id = conn.execute(
            "INSERT INTO alquiler_turnos_estudio (pedido_id, fecha_desde, fecha_hasta) "
            "VALUES (%s,%s,%s) RETURNING id",
            (PEDIDO_B_ID, manana.replace(hour=10, minute=0, second=0, microsecond=0).isoformat(),
             manana.replace(hour=12, minute=0, second=0, microsecond=0).isoformat()),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal, "
            "cobro_modo, turno_estudio_id) VALUES (%s,%s,1,12000,'fijo',%s)",
            (PEDIDO_B_ID, centinela_id, turno_b_id),
        )

        # Pedido TALLER: turno embebido por clase (2026-08-13) también HOY —
        # mismo día que el pedido A, para probar que NO se cuela en ninguna de
        # las listas junto a él (bug real: las queries de arriba joineaban
        # `alquiler_turnos_estudio` → `alquileres` sin filtrar `a.tipo`).
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,'Taller test dashboard turno','confirmado','taller',%s,%s,18000)",
            (PEDIDO_TALLER_ID, hoy.date().replace(day=1).isoformat(), lejos_hasta),
        )
        turno_taller_id = conn.execute(
            "INSERT INTO alquiler_turnos_estudio (pedido_id, fecha_desde, fecha_hasta) "
            "VALUES (%s,%s,%s) RETURNING id",
            (PEDIDO_TALLER_ID, hoy.replace(hour=9, minute=0, second=0, microsecond=0).isoformat(),
             hoy.replace(hour=12, minute=0, second=0, microsecond=0).isoformat()),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal, "
            "cobro_modo, turno_estudio_id) VALUES (%s,%s,1,18000,'fijo',%s)",
            (PEDIDO_TALLER_ID, centinela_id, turno_taller_id),
        )

        conn.commit()
        yield {"hoy": hoy, "centinela_nombre": centinela_nombre}
    finally:
        _limpiar(conn)
        conn.commit()
        conn.close()


def test_turno_embebido_hoy_aparece_en_salen_y_devuelven_hoy(client_con_db, setup):
    r = client_con_db.get("/api/dashboard")
    assert r.status_code == 200, r.text
    data = r.json()

    # El pedido contenedor A no tiene ninguna razón PROPIA para salir/volver
    # hoy (su equipo está a +30/+33 días) — si aparece, es por el turno.
    fila_sale = next((p for p in data["salen_hoy"] if p["id"] == PEDIDO_A_ID), None)
    assert fila_sale is not None, data["salen_hoy"]
    assert fila_sale["monto_total"] == 15000  # el monto del TURNO, no el del pedido (45000)

    fila_devuelve = next((p for p in data["devuelven_hoy"] if p["id"] == PEDIDO_A_ID), None)
    assert fila_devuelve is not None, data["devuelven_hoy"]
    assert fila_devuelve["monto_total"] == 15000

    # El pedido B (turno mañana, no hoy) NO debe aparecer hoy.
    assert not any(p["id"] == PEDIDO_B_ID for p in data["salen_hoy"])
    assert not any(p["id"] == PEDIDO_B_ID for p in data["devuelven_hoy"])

    # El taller (turno embebido por clase, también HOY) NO debe aparecer acá
    # — taller vive en Talleres, no en este dashboard de rental/Estudio (bug
    # real 2026-08-13: la query no filtraba `a.tipo`).
    assert not any(p["id"] == PEDIDO_TALLER_ID for p in data["salen_hoy"])
    assert not any(p["id"] == PEDIDO_TALLER_ID for p in data["devuelven_hoy"])


def test_turno_embebido_manana_aparece_en_devuelven_manana(client_con_db, setup):
    r = client_con_db.get("/api/dashboard")
    assert r.status_code == 200, r.text
    data = r.json()

    fila = next((p for p in data["devuelven_manana"] if p["id"] == PEDIDO_B_ID), None)
    assert fila is not None, data["devuelven_manana"]
    assert fila["monto_total"] == 12000

    assert not any(p["id"] == PEDIDO_A_ID for p in data["devuelven_manana"])


def test_calendario_muestra_equipo_y_turno_como_filas_separadas(client_con_db, setup):
    from datetime import timedelta

    hoy = setup["hoy"]
    centinela_nombre = setup["centinela_nombre"]
    r = client_con_db.get(
        "/api/calendario",
        params={
            "desde": (hoy - timedelta(days=2)).date().isoformat(),
            "hasta": (hoy + timedelta(days=40)).date().isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    eventos = r.json()

    # Fila de EQUIPO del pedido A (rango lejano, tipo='diaria'): no debe
    # incluir al centinela en "equipos" — el turno tiene su propia fila.
    fila_equipo_a = next(
        (e for e in eventos if e["id"] == PEDIDO_A_ID and e["tipo"] == "diaria"), None
    )
    assert fila_equipo_a is not None, eventos
    assert fila_equipo_a["equipos"] == "Cámara test dashboard turno A"
    assert centinela_nombre not in (fila_equipo_a["equipos"] or "")

    # Fila de TURNO del pedido A: tipo sintético 'estudio', fecha propia (HOY,
    # no el rango lejano del pedido), monto propio, equipos = el centinela.
    fila_turno_a = next(
        (e for e in eventos if e["id"] == PEDIDO_A_ID and e["tipo"] == "estudio"), None
    )
    assert fila_turno_a is not None, eventos
    assert fila_turno_a["fecha_desde"].startswith(hoy.date().isoformat())
    assert fila_turno_a["monto_total"] == 15000
    assert fila_turno_a["equipos"] == centinela_nombre

    # Mismo patrón para el pedido B.
    fila_equipo_b = next(
        (e for e in eventos if e["id"] == PEDIDO_B_ID and e["tipo"] == "diaria"), None
    )
    assert fila_equipo_b is not None, eventos
    assert fila_equipo_b["equipos"] == "Cámara test dashboard turno B"

    fila_turno_b = next(
        (e for e in eventos if e["id"] == PEDIDO_B_ID and e["tipo"] == "estudio"), None
    )
    assert fila_turno_b is not None, eventos
    assert fila_turno_b["monto_total"] == 12000

    # El taller NO debe aparecer en ninguna forma — ni como fila de equipo
    # (`TIPOS_SIN_RETIRO_SQL` ya lo excluye, control preexistente) ni,
    # sobre todo, como fila de turno sintético 'estudio' (bug real
    # 2026-08-13: `rows_turnos` no filtraba `a.tipo`, así que la clase del
    # taller se coloreaba/contaba como un turno real del Estudio acá).
    assert not any(e["id"] == PEDIDO_TALLER_ID for e in eventos)
