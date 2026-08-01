"""`pedido_principal_id` — turno del Estudio vinculado a un pedido de alquiler
normal (#1308, "Reserva del Estudio" desde la página del pedido) contra
Postgres REAL.

El dueño pidió poder agregar horas de Estudio a un pedido de alquiler común
sin que las dos cosas "se desincronicen" — la garantía real es el CLIENTE:
el turno SIEMPRE hereda cliente_id/nombre/email/teléfono del pedido
principal, ignorando lo que mande el request (`_resolver_pedido_principal`,
`routes/estudio.py`). Esto se prueba con un body que manda un cliente
DISTINTO al del pedido principal — el turno persistido tiene que quedar con
el del pedido principal, no con el del body (si no discriminara, cualquier
cliente_id/nombre pasaría tal cual).

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_pedido_estudio_vinculado_db.py -v -m integration
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

CLIENTE_PRINCIPAL_ID = 9_476_001
CLIENTE_OTRO_ID = 9_476_002
CLIENTE_TARDIO_ID = 9_476_003
PEDIDO_PRINCIPAL_ID = 9_476_010
PEDIDO_ESTUDIO_AJENO_ID = 9_476_011
PEDIDO_PRINCIPAL_SIN_CLIENTE_ID = 9_476_012


_PRINCIPAL_IDS = (PEDIDO_PRINCIPAL_ID, PEDIDO_ESTUDIO_AJENO_ID, PEDIDO_PRINCIPAL_SIN_CLIENTE_ID)


def _limpiar(conn):
    # `pedido_principal_id IN (...)` es necesario ADEMÁS de `cliente_id`/`id`:
    # un turno vinculado a `PEDIDO_PRINCIPAL_SIN_CLIENTE_ID` nace con
    # `cliente_id=NULL` (esa es la reproducción del bug) y un `id` propio
    # nuevo — sin este filtro, ese turno no matchea ningún otro criterio y
    # queda huérfano en la base de test para siempre, chocando con la franja
    # de un test futuro (409 falso "El estudio no está disponible").
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE cliente_id IN (%s,%s,%s) OR id IN (%s,%s,%s) "
        "OR pedido_principal_id IN (%s,%s,%s))",
        (CLIENTE_PRINCIPAL_ID, CLIENTE_OTRO_ID, CLIENTE_TARDIO_ID,
         *_PRINCIPAL_IDS, *_PRINCIPAL_IDS),
    )
    conn.execute(
        "DELETE FROM alquileres WHERE cliente_id IN (%s,%s,%s) OR id IN (%s,%s,%s) "
        "OR pedido_principal_id IN (%s,%s,%s)",
        (CLIENTE_PRINCIPAL_ID, CLIENTE_OTRO_ID, CLIENTE_TARDIO_ID,
         *_PRINCIPAL_IDS, *_PRINCIPAL_IDS),
    )
    conn.execute(
        "DELETE FROM clientes WHERE id IN (%s,%s,%s)",
        (CLIENTE_PRINCIPAL_ID, CLIENTE_OTRO_ID, CLIENTE_TARDIO_ID),
    )


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    from database import get_db

    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'Principal','Vinculado','principal@test.com','+5491100000001')",
            (CLIENTE_PRINCIPAL_ID,),
        )
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'Otro','Cliente','otro@test.com','+5491100000002')",
            (CLIENTE_OTRO_ID,),
        )
        # El pedido PRINCIPAL: alquiler normal (tipo='diaria', default).
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_email, "
            "cliente_telefono, estado, fecha_desde, fecha_hasta, numero_pedido) "
            "VALUES (%s,%s,'Principal Vinculado','principal@test.com','+5491100000001',"
            "'confirmado','2030-06-01','2030-06-05',947601)",
            (PEDIDO_PRINCIPAL_ID, CLIENTE_PRINCIPAL_ID),
        )
        # Un pedido de Estudio AJENO — para probar que no se puede vincular un
        # turno a otro turno (solo a un pedido tipo='diaria').
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, "
            "fecha_desde, fecha_hasta, numero_pedido, tipo) "
            "VALUES (%s,%s,'Ajeno Estudio','confirmado',"
            "'2030-06-01 10:00','2030-06-01 12:00',947602,'estudio')",
            (PEDIDO_ESTUDIO_AJENO_ID, CLIENTE_OTRO_ID),
        )
        # Un pedido PRINCIPAL sin cliente todavía asignado (carga manual) — para
        # probar que el turno vinculado a él no queda "Sin cliente" para
        # siempre si el principal consigue cliente DESPUÉS.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, "
            "fecha_desde, fecha_hasta, numero_pedido) "
            "VALUES (%s,NULL,'','confirmado','2030-06-07','2030-06-09',947603)",
            (PEDIDO_PRINCIPAL_SIN_CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'Tardio','Asignado','tardio@test.com','+5491100000003')",
            (CLIENTE_TARDIO_ID,),
        )
        conn.execute(
            "UPDATE estudio SET precio_hora=10000, buffer_horas=0, min_horas=1, "
            "open_hour=0, close_hour=24, anticipacion_min_horas=0 WHERE id=1"
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


@pytest.fixture(scope="module")
def client_con_db():
    from database import init_db
    from fastapi.testclient import TestClient

    init_db()
    with TestClient(main.app, raise_server_exceptions=True) as c:
        if main.db_init_thread is not None:
            main.db_init_thread.join(timeout=60)
        yield c


def test_turno_hereda_cliente_del_pedido_principal_no_del_body(client_con_db, setup):
    """El body manda un cliente DISTINTO (`CLIENTE_OTRO_ID`) — el turno
    persistido tiene que quedar con el del pedido PRINCIPAL, no con el del
    body. Discrimina: sin `_resolver_pedido_principal` ignorando el body,
    este assert falla (quedaría con CLIENTE_OTRO_ID)."""
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-06-02", "start": "10:00", "horas": 2,
            "cliente_id": CLIENTE_OTRO_ID,  # a propósito, distinto al principal
            "pedido_principal_id": PEDIDO_PRINCIPAL_ID,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["cliente_id"] == CLIENTE_PRINCIPAL_ID
    assert data["cliente_nombre"] == "Principal Vinculado"

    from database import get_db

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT cliente_id, cliente_nombre, cliente_email, cliente_telefono, "
            "pedido_principal_id, tipo FROM alquileres WHERE id=%s",
            (data["id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row["cliente_id"] == CLIENTE_PRINCIPAL_ID
    assert row["cliente_nombre"] == "Principal Vinculado"
    assert row["cliente_email"] == "principal@test.com"
    assert row["cliente_telefono"] == "+5491100000001"
    assert row["pedido_principal_id"] == PEDIDO_PRINCIPAL_ID
    assert row["tipo"] == "estudio"


def test_no_se_puede_vincular_a_otro_turno_del_estudio(client_con_db, setup):
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-06-03", "start": "10:00", "horas": 2,
            "pedido_principal_id": PEDIDO_ESTUDIO_AJENO_ID,
        },
    )
    assert r.status_code == 400
    assert "alquiler normal" in r.json()["detail"]


def test_pedido_principal_inexistente_404(client_con_db, setup):
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-06-04", "start": "10:00", "horas": 2,
            "pedido_principal_id": 999_999_999,
        },
    )
    assert r.status_code == 404


def test_detalle_del_principal_lista_el_turno_vinculado(client_con_db, setup):
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-06-05", "start": "14:00", "horas": 3,
            "pedido_principal_id": PEDIDO_PRINCIPAL_ID,
        },
    )
    assert r.status_code == 201, r.text
    turno_id = r.json()["id"]

    detalle = client_con_db.get(f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}").json()
    vinculados = detalle["turnos_estudio_vinculados"]
    assert len(vinculados) == 1
    assert vinculados[0]["id"] == turno_id
    assert vinculados[0]["monto_total"] == 30000  # 3h × 10000

    detalle_turno = client_con_db.get(f"/api/alquileres/{turno_id}").json()
    assert detalle_turno["pedido_principal"]["id"] == PEDIDO_PRINCIPAL_ID
    assert detalle_turno["pedido_principal"]["cliente_nombre"] == "Principal Vinculado"


def test_borrar_el_principal_se_lleva_el_turno(client_con_db, setup):
    """CAMBIO DE CONDUCTA (2026-07-29). Este test afirmaba lo contrario: que
    borrar el pedido solo DESVINCULABA el turno (el `ON DELETE SET NULL` de la
    FK) y lo dejaba vivo. En la práctica eso resucitaba el doble pedido
    fantasma: el turno sobrevivía con su propio número, su propio estado y su
    "RETIRA HOY", y volvía a la lista como un pedido más — el dueño lo reportó
    viendo dos filas, "uno con número y otro no".

    Un turno vinculado no es una venta aparte: es contenido del pedido, como un
    ítem. Si se borra el pedido, se borra su contenido. El turno del Estudio
    SUELTO (sin principal) no cambia — sigue siendo un pedido de primera clase.
    """
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-06-06", "start": "10:00", "horas": 2,
            "pedido_principal_id": PEDIDO_PRINCIPAL_ID,
        },
    )
    assert r.status_code == 201, r.text
    turno_id = r.json()["id"]

    r_del = client_con_db.delete(f"/api/alquileres/{PEDIDO_PRINCIPAL_ID}")
    assert r_del.status_code == 204

    assert client_con_db.get(f"/api/alquileres/{turno_id}").status_code == 404

    from database import get_db

    conn = get_db()
    try:
        row = conn.execute("SELECT 1 FROM alquileres WHERE id=%s", (turno_id,)).fetchone()
    finally:
        conn.close()
    assert row is None, "el turno vinculado tiene que irse con su pedido, no quedar huérfano"


def test_lista_de_reservas_no_queda_sin_cliente_si_el_principal_lo_consigue_despues(
    client_con_db, setup,
):
    """Bug real reportado por el dueño en vivo: un turno se creó cuando su
    pedido principal TODAVÍA no tenía cliente asignado (carga manual, orden
    normal de trabajo) — `_resolver_pedido_principal` congela esa foto vacía
    en el turno al crearlo. El principal consigue cliente DESPUÉS y el turno
    se quedaba mostrando "Sin cliente" en `/admin/estudio/reservas` para
    siempre, aunque su principal ya tuviera uno — la lista del Estudio no
    resolvía el contacto en vivo vía el eje `pedido_principal_id` (solo lo
    hacía para el `cliente_id` propio del pedido)."""
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-06-08", "start": "18:30", "horas": 2,
            "pedido_principal_id": PEDIDO_PRINCIPAL_SIN_CLIENTE_ID,
        },
    )
    assert r.status_code == 201, r.text
    turno_id = r.json()["id"]
    assert r.json()["cliente_id"] is None  # foto congelada: el principal no tenía cliente

    from database import get_db

    conn = get_db()
    try:
        conn.execute(
            "UPDATE alquileres SET cliente_id = %s, cliente_nombre = 'Tardio Asignado' "
            "WHERE id = %s",
            (CLIENTE_TARDIO_ID, PEDIDO_PRINCIPAL_SIN_CLIENTE_ID),
        )
        conn.commit()
    finally:
        conn.close()

    r2 = client_con_db.get(
        "/api/admin/estudio/reservas", params={"desde": "2030-06-08", "hasta": "2030-06-08"}
    )
    assert r2.status_code == 200
    reservas = [x for x in r2.json()["reservas"] if x["id"] == turno_id]
    assert len(reservas) == 1
    assert reservas[0]["cliente_nombre"] == "Tardio Asignado"
