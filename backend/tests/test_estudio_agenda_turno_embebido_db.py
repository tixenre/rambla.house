"""Fase 2 (#1308 rediseño "turno como ítem") — un turno del Estudio EMBEBIDO
en un pedido de alquiler normal sigue apareciendo en las dos superficies del
back-office que muestran la agenda del espacio: `/admin/estudio/reservas` y
`/admin/estudio/agenda`. Sin esto, el turno desaparecería de la agenda del
Estudio en cuanto dejara de vivir en su propia fila `alquileres` — reabriendo
del otro lado la confusión que motivó el rediseño.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_estudio_agenda_turno_embebido_db.py -v -m integration
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

CLIENTE_ID = 9_482_001
PEDIDO_ID = 9_482_010
NUMERO_PEDIDO = 948210
# Turno STANDALONE (su propia fila `alquileres`, `tipo='estudio'`) — el caso que
# el dueño vio vacío en pantalla. Ids propios para no chocar con el embebido.
PEDIDO_STANDALONE = 9_482_011
NUMERO_STANDALONE = 948211


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    from database import get_db

    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'Agenda','Embebida','agenda-embebida@test.com','+5491100000098')",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, "
            "fecha_desde, fecha_hasta, numero_pedido) "
            "VALUES (%s,%s,'Agenda Embebida','confirmado','2030-03-10','2030-03-13',%s)",
            (PEDIDO_ID, CLIENTE_ID, NUMERO_PEDIDO),
        )
        cid = conn.execute("SELECT equipo_id FROM estudio WHERE id=1").fetchone()["equipo_id"]
        turno_id = conn.execute(
            "INSERT INTO alquiler_turnos_estudio (pedido_id, fecha_desde, fecha_hasta) "
            "VALUES (%s,'2030-03-10 14:00','2030-03-10 16:00') RETURNING id",
            (PEDIDO_ID,),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO alquiler_items "
            "(pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo, turno_estudio_id) "
            "VALUES (%s,%s,1,20000,20000,'fijo',%s)",
            (PEDIDO_ID, cid, turno_id),
        )
        conn.commit()
    finally:
        conn.close()

    yield turno_id

    conn = get_db()
    try:
        _limpiar(conn)
        conn.commit()
    finally:
        conn.close()


def _limpiar(conn):
    ids = (PEDIDO_ID, PEDIDO_STANDALONE)
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id IN (%s,%s)", ids)
    conn.execute("DELETE FROM alquiler_turnos_estudio WHERE pedido_id IN (%s,%s)", ids)
    conn.execute("DELETE FROM alquileres WHERE id IN (%s,%s)", ids)
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))


@pytest.fixture(scope="module")
def client_con_db():
    from database import init_db
    from fastapi.testclient import TestClient

    init_db()
    with TestClient(main.app, raise_server_exceptions=True) as c:
        if main.db_init_thread is not None:
            main.db_init_thread.join(timeout=60)
        yield c


def test_turno_embebido_aparece_en_listar_reservas_estudio(client_con_db, setup):
    turno_id = setup
    r = client_con_db.get(
        "/api/admin/estudio/reservas", params={"desde": "2030-03-01", "hasta": "2030-03-31"}
    )
    assert r.status_code == 200
    reservas = r.json()["reservas"]
    fila = next((x for x in reservas if x.get("turno_estudio_id") == turno_id), None)
    assert fila is not None, f"el turno embebido no apareció en la lista: {reservas}"
    assert fila["id"] == PEDIDO_ID
    assert fila["numero_pedido"] == NUMERO_PEDIDO
    assert fila["cliente_nombre"] == "Agenda Embebida"
    assert fila["monto_total"] == 20000


def test_turno_embebido_aparece_en_agenda_estudio(client_con_db, setup):
    r = client_con_db.get(
        "/api/admin/estudio/agenda", params={"desde": "2030-03-01", "hasta": "2030-03-31"}
    )
    assert r.status_code == 200
    bloques = r.json()["bloques"]
    fila = next(
        (b for b in bloques if b.get("id") == PEDIDO_ID and b.get("embebido") is True), None
    )
    assert fila is not None, f"el turno embebido no apareció en la agenda: {bloques}"
    assert fila["numero_pedido"] == NUMERO_PEDIDO
    assert fila["fecha_desde"].startswith("2030-03-10T14:00")
    assert fila["fecha_hasta"].startswith("2030-03-10T16:00")


@pytest.mark.parametrize("estado", ["devuelto", "finalizado"])
def test_un_turno_ya_terminado_sigue_en_la_agenda(client_con_db, setup, estado):
    """Bug real 2026-08-02 (reportado por el dueño): la agenda del Estudio
    filtraba por `ESTADOS_RESERVADO`, así que un mes ya pasado se veía VACÍO —
    sus turnos estaban `devuelto`/`finalizado` y desaparecían—, mientras el
    calendario general del Dashboard sí los mostraba. Un turno que YA OCURRIÓ
    ocupó el espacio y tiene que seguir viéndose en las dos vistas."""
    from database import get_db

    conn = get_db()
    try:
        conn.execute("UPDATE alquileres SET estado=%s WHERE id=%s", (estado, PEDIDO_ID))
        conn.commit()
    finally:
        conn.close()

    r = client_con_db.get(
        "/api/admin/estudio/agenda", params={"desde": "2030-03-01", "hasta": "2030-03-31"}
    )
    assert r.status_code == 200
    bloques = r.json()["bloques"]
    fila = next((b for b in bloques if b.get("id") == PEDIDO_ID), None)
    assert fila is not None, f"un turno {estado} desapareció de la agenda: {bloques}"
    assert fila["estado"] == estado

    # La lista (`/reservas`) nunca filtró por estado — se verifica igual, para
    # que las dos superficies queden fijadas juntas y no vuelvan a divergir.
    r2 = client_con_db.get(
        "/api/admin/estudio/reservas", params={"desde": "2030-03-01", "hasta": "2030-03-31"}
    )
    assert r2.status_code == 200
    assert any(x["id"] == PEDIDO_ID for x in r2.json()["reservas"])


@pytest.mark.parametrize("estado", ["devuelto", "finalizado"])
def test_un_turno_standalone_ya_terminado_sigue_en_la_agenda(client_con_db, setup, estado):
    """Gemelo del anterior para un turno STANDALONE (`tipo='estudio'`, su propia
    fila en `alquileres`) — es el caso que el dueño vio en pantalla: julio 2026
    aparecía con solo los talleres. Las dos queries de la agenda (standalone y
    embebida) tienen que filtrar igual; sin este test, arreglar una y olvidar la
    otra pasaba el CI."""
    from database import get_db

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, numero_pedido) "
            "VALUES (%s,%s,'Turno Standalone',%s,'estudio',"
            "'2030-03-20 10:00','2030-03-20 13:00',%s)",
            (PEDIDO_STANDALONE, CLIENTE_ID, estado, NUMERO_STANDALONE),
        )
        conn.commit()
    finally:
        conn.close()

    r = client_con_db.get(
        "/api/admin/estudio/agenda", params={"desde": "2030-03-01", "hasta": "2030-03-31"}
    )
    assert r.status_code == 200
    fila = next((b for b in r.json()["bloques"] if b.get("id") == PEDIDO_STANDALONE), None)
    assert fila is not None, f"un turno standalone {estado} desapareció de la agenda"
    assert fila["estado"] == estado
    assert not fila.get("embebido")


@pytest.mark.parametrize("estado", ["cancelado", "borrador"])
def test_un_turno_cancelado_o_borrador_no_ocupa_la_agenda(client_con_db, setup, estado):
    """La otra mitad del criterio: un turno que NO ocurrió (cancelado) o que
    todavía no es una reserva (borrador) no se muestra como ocupación — sin
    esto, "mostrar lo terminado" se habría vuelto "mostrar todo"."""
    from database import get_db

    conn = get_db()
    try:
        conn.execute("UPDATE alquileres SET estado=%s WHERE id=%s", (estado, PEDIDO_ID))
        conn.commit()
    finally:
        conn.close()

    r = client_con_db.get(
        "/api/admin/estudio/agenda", params={"desde": "2030-03-01", "hasta": "2030-03-31"}
    )
    assert r.status_code == 200
    assert all(b.get("id") != PEDIDO_ID for b in r.json()["bloques"])


def test_sin_turno_embebido_no_aparece_nada_extra(client_con_db, setup):
    """Control: consultando una ventana SIN el turno embebido del fixture
    (que vive en marzo 2030), ninguna de las dos superficies lo trae de
    rebote — confirma que la ventana de fechas se respeta, no solo que
    "no hay nada en una base vacía"."""
    r = client_con_db.get(
        "/api/admin/estudio/reservas", params={"desde": "2031-01-01", "hasta": "2031-01-31"}
    )
    assert r.status_code == 200
    assert all(x.get("turno_estudio_id") is None for x in r.json()["reservas"])

    r2 = client_con_db.get(
        "/api/admin/estudio/agenda", params={"desde": "2031-01-01", "hasta": "2031-01-31"}
    )
    assert r2.status_code == 200
    assert all(not b.get("embebido") for b in r2.json()["bloques"])
