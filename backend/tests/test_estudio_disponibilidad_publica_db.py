"""Integración real (Postgres) de la disponibilidad + reserva PÚBLICA del
Estudio (GET /api/estudio/disponibilidad + POST /api/estudio/reservas) —
cierra un gap encontrado al extraer `services/estudio/` (CQRS-lite): ya
existía cobertura de integración real para el alta ADMIN
(`test_estudio_admin_reservas_db.py`, incluida su concurrencia) y para la
promo/ítems veraces, pero ninguna ejercitaba el flujo PÚBLICO end-to-end
contra Postgres real, ni el bloqueo por taller publicado visto DESDE el lado
del Estudio (`test_talleres_f2_db.py` verifica el gate desde el lado
talleres — que publicar no choque con el Estudio —, no que el propio
Estudio rebote correctamente al intentar reservar esa franja).

Ejercita, contra Postgres real:
1. GET disponibilidad(libre) → POST reserva (201) → GET disponibilidad de la
   MISMA franja (libre=False) → segunda reserva de la misma franja (409, sin
   dejar fila huérfana). La garantía dura es el re-chequeo de
   `_centinela_libre` bajo `FOR UPDATE` dentro de
   `services.estudio.commands.reserva._crear_pedido_estudio` — el fail del
   409 debe venir de un rollback limpio, no de una fila a medio commitear.
2. Un taller publicado en la franja bloquea tanto el GET como el POST del
   Estudio (`_taller_bloqueante`, dentro de `_estudio_disponible`).

OPT-IN y seguro por defecto (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://tincho@localhost/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_estudio_disponibilidad_publica_db.py -v -m integration
"""
import os
import time
from urllib.parse import urlparse

import psycopg.errors
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
from auth.session import signer  # noqa: E402

CLIENTE_ID = 9_380_001
TALLER_ID = 9_380_101
TALLER_SLUG = "test-estudio-disp-publica-zzq"
_COOKIE = (
    "session="
    + signer.dumps({
        "email": "estudiopublico@test.com", "role": "cliente",
        "cliente_id": CLIENTE_ID, "jti": "estudio-disp-publica",
    })
)


@pytest.fixture(autouse=True)
def _sessions_active(monkeypatch):
    """jti obligatorio: la cookie de test no está en la allowlist real →
    stubbeamos is_active (mismo patrón que test_estudio_items_veraces_db.py)."""
    monkeypatch.setattr("auth.queries.sessions.is_active", lambda jti: {"jti": jti})


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE cliente_id = %s)",
        (CLIENTE_ID,),
    )
    conn.execute("DELETE FROM alquileres WHERE cliente_id = %s", (CLIENTE_ID,))
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))
    # `admin_create_edicion` dispara `_regenerar_pedidos_taller`, que crea un
    # pedido `tipo='taller'` de resumen económico aunque la edición no use
    # estudio/equipos (ítem placeholder) — hay que limpiarlo ANTES de borrar
    # `ediciones_taller` (la FK `taller_edicion_id` de `alquileres` es
    # `ON DELETE SET NULL`, no CASCADE: sin este DELETE explícito la fila
    # queda huérfana, sin `cliente_id` que la haga elegible al DELETE de arriba).
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE taller_edicion_id IN "
        "(SELECT id FROM ediciones_taller WHERE taller_id = %s))",
        (TALLER_ID,),
    )
    conn.execute(
        "DELETE FROM alquileres WHERE taller_edicion_id IN "
        "(SELECT id FROM ediciones_taller WHERE taller_id = %s)",
        (TALLER_ID,),
    )
    conn.execute(
        "DELETE FROM clases_taller WHERE edicion_id IN "
        "(SELECT id FROM ediciones_taller WHERE taller_id = %s)",
        (TALLER_ID,),
    )
    conn.execute("DELETE FROM ediciones_taller WHERE taller_id = %s", (TALLER_ID,))
    conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))


def _limpiar_con_retry(conn, intentos: int = 3) -> None:
    """`_limpiar` con reintento ante `DeadlockDetected` transitorio (mismo
    patrón de `routes/alquileres/core.py`): FastAPI corre los endpoints sync
    en threads del pool de Starlette — una limpieza que corre justo cuando un
    request anterior todavía está liberando su conexión puede pisarse en el
    orden de locks. Postgres aborta una de las dos transacciones y lo
    señaliza con esta excepción — reintentar es la respuesta esperada, no
    una tapa de un bug real."""
    for intento in range(intentos):
        try:
            _limpiar(conn)
            return
        except psycopg.errors.DeadlockDetected:
            conn.rollback()
            if intento == intentos - 1:
                raise
            time.sleep(0.2 * (intento + 1))


@pytest.fixture
def setup():
    from database import get_db

    conn = get_db()
    try:
        _limpiar_con_retry(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, dni_validado_at) "
            "VALUES (%s,'Cliente','Disp Publica','estudiopublico@test.com', now())",
            (CLIENTE_ID,),
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
        _limpiar_con_retry(conn)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def client_con_db():
    from database import init_db
    from fastapi.testclient import TestClient

    init_db()
    with TestClient(main.app, raise_server_exceptions=True) as c:
        yield c


def _disponibilidad(client, *, fecha, start, horas):
    return client.get(
        "/api/estudio/disponibilidad",
        params={"fecha": fecha, "start": start, "horas": horas},
    )


def _reservar(client, *, fecha, start, horas):
    return client.post(
        "/api/estudio/reservas",
        json={"fecha": fecha, "start": start, "horas": horas},
        headers={"Cookie": _COOKIE},
    )


def test_segunda_reserva_misma_franja_rebota_409_sin_fila_huerfana(client_con_db, setup):
    """Ciclo completo: libre → reservar → deja de estar libre → una segunda
    reserva de la MISMA franja rebota con 409 y no deja una fila huérfana en
    `alquileres` — la garantía dura es el re-chequeo de `_centinela_libre`
    bajo `FOR UPDATE` en `_crear_pedido_estudio` (rollback correcto)."""
    from database import get_db

    fecha, start, horas = "2030-04-10", "14:00", 2

    r0 = _disponibilidad(client_con_db, fecha=fecha, start=start, horas=horas)
    assert r0.status_code == 200, r0.text
    assert r0.json()["libre"] is True

    r1 = _reservar(client_con_db, fecha=fecha, start=start, horas=horas)
    assert r1.status_code == 201, r1.text
    pedido_id = r1.json()["id"]

    r2 = _disponibilidad(client_con_db, fecha=fecha, start=start, horas=horas)
    assert r2.status_code == 200, r2.text
    assert r2.json()["libre"] is False
    assert "reservado" in r2.json()["motivo"]

    r3 = _reservar(client_con_db, fecha=fecha, start=start, horas=horas)
    assert r3.status_code == 409, r3.text

    conn = get_db()
    try:
        pedidos = conn.execute(
            "SELECT id FROM alquileres WHERE cliente_id = %s", (CLIENTE_ID,)
        ).fetchall()
    finally:
        conn.close()
    assert [p["id"] for p in pedidos] == [pedido_id], (
        "el 409 no debe dejar una segunda fila en alquileres (rollback correcto)"
    )


def test_pintura_reciente_anticipacion_propia_bloquea_get_y_post(client_con_db, setup):
    """El add-on "recién pintado" exige su PROPIA anticipación
    (`anticipacion_pintura_horas`), independiente de `anticipacion_min_horas`
    (el `setup` la deja en 0): sin tildar el add-on la franja está libre; con
    el add-on tildado, la MISMA franja rebota tanto en el GET (preview) como
    en el POST (creación) — end-to-end contra Postgres real."""
    from datetime import timedelta

    from database import get_db, now_ar

    conn = get_db()
    try:
        conn.execute("UPDATE estudio SET anticipacion_pintura_horas=48 WHERE id=1")
        conn.commit()
    finally:
        conn.close()

    pronto = now_ar() + timedelta(hours=2)
    fecha, start, horas = pronto.strftime("%Y-%m-%d"), pronto.strftime("%H:00"), 1

    r0 = _disponibilidad(client_con_db, fecha=fecha, start=start, horas=horas)
    assert r0.status_code == 200, r0.text
    assert r0.json()["libre"] is True

    r1 = client_con_db.get(
        "/api/estudio/disponibilidad",
        params={"fecha": fecha, "start": start, "horas": horas, "pintura_reciente": "true"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["libre"] is False
    assert "recién pintado" in r1.json()["motivo"]

    r2 = client_con_db.post(
        "/api/estudio/reservas",
        json={"fecha": fecha, "start": start, "horas": horas, "pintura_reciente": True},
        headers={"Cookie": _COOKIE},
    )
    assert r2.status_code == 400, r2.text
    assert "recién pintado" in r2.json()["detail"]


def test_taller_publicado_bloquea_get_y_post(client_con_db, setup, monkeypatch):
    """Un taller publicado en la franja bloquea tanto GET disponibilidad como
    POST reservas del Estudio — ejercita `_taller_bloqueante` end-to-end
    contra Postgres real desde el LADO del Estudio (los tests de
    `test_talleres_f2_db.py` solo verifican el gate desde el lado talleres)."""
    import routes.talleres as t
    from database import get_db

    monkeypatch.setattr(t, "require_admin", lambda r: None)
    monkeypatch.setattr(t, "send_email", lambda *a, **k: None)
    monkeypatch.setattr(t, "get_admin_to", lambda: "admin@example.com")

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
            (TALLER_ID, TALLER_SLUG, TALLER_SLUG, "Taller Disp Pública"),
        )
        conn.commit()
    finally:
        conn.close()

    fecha = "2030-04-11"
    body = t.EdicionCreateBody(
        clases=[
            t.ClaseBody(fecha=fecha, hora_inicio_min=600, hora_fin_min=720,
                        titulo="Clase única", descripcion="Temario"),
        ],
        numero_edicion=1,
        activo=True,
    )
    d = t.admin_create_edicion(TALLER_ID, body, None)
    assert d["activo"] is True

    # La clase ocupa 10:00-12:00; pedir 10:30-11:30 solapa.
    r0 = _disponibilidad(client_con_db, fecha=fecha, start="10:30", horas=1)
    assert r0.status_code == 200, r0.text
    assert r0.json()["libre"] is False
    assert "taller" in r0.json()["motivo"]

    r1 = _reservar(client_con_db, fecha=fecha, start="10:30", horas=1)
    assert r1.status_code == 409, r1.text
    assert "taller" in r1.json()["detail"]
