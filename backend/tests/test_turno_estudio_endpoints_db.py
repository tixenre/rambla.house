"""#1308 rediseño "turno como ítem", Fase 4.2 — los endpoints HTTP que agregan/
editan/borran un turno del Estudio EMBEBIDO en un pedido existente
(`POST/PATCH/DELETE /alquileres/{id}/turnos-estudio[/{turno_id}]`,
`routes/alquileres/turnos_estudio.py`).

Contra Postgres REAL vía `TestClient` — el camino completo HTTP → franja
resuelta (`_franja_estudio`) → `services.estudio.commands.reserva` → commit →
`GET`-equivalente (`_get_alquiler_detail`) en la respuesta. La Fase 4.1 ya
cubre las funciones núcleo en detalle (llamadas directo); acá se confirma que
el transporte las conecta bien: auth, resolución del body, forma de la
respuesta, y el guard cross-pedido (`turno_id` que no pertenece a `id`).

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_turno_estudio_endpoints_db.py -v -m integration
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

# Ids altos dedicados (bloque 9_489_xxx, sin uso en otros *_db.py).
CLIENTE_ID = 9_489_001
EQ_RENTAL_ID = 9_489_010
PEDIDO_ID = 9_489_020
PEDIDO_ESTUDIO_ID = 9_489_021   # standalone, tipo equivocado para el 400
OTRO_PEDIDO_ID = 9_489_022      # segundo contenedor, para el guard cross-pedido


def _limpiar(conn):
    ids = (PEDIDO_ID, PEDIDO_ESTUDIO_ID, OTRO_PEDIDO_ID)
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id = ANY(%s)", (list(ids),))
    conn.execute("DELETE FROM alquiler_turnos_estudio WHERE pedido_id = ANY(%s)", (list(ids),))
    conn.execute("DELETE FROM alquileres WHERE id = ANY(%s)", (list(ids),))
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQ_RENTAL_ID,))
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


@pytest.fixture
def setup(monkeypatch):
    from database import get_db

    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'Turno','Endpoint','turno-endpoint-embebido@test.com','+5491100000092')",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno) "
            "VALUES (%s,'Cámara test endpoint turno embebido',1,'Rental')",
            (EQ_RENTAL_ID,),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'Turno Endpoint','confirmado','diaria','2033-04-10','2033-04-13',30000)",
            (PEDIDO_ID, CLIENTE_ID),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
            "VALUES (%s,%s,1,10000,30000,'jornada')",
            (PEDIDO_ID, EQ_RENTAL_ID),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'Standalone test endpoint','confirmado','estudio','2033-04-01 10:00','2033-04-01 12:00',10000)",
            (PEDIDO_ESTUDIO_ID, CLIENTE_ID),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'Otro contenedor test endpoint','confirmado','diaria','2033-04-20','2033-04-22',10000)",
            (OTRO_PEDIDO_ID, CLIENTE_ID),
        )
        conn.commit()
        yield
    finally:
        _limpiar(conn)
        conn.commit()
        conn.close()


def test_guard_admin_rechaza_sin_bypass(client_con_db, setup, monkeypatch):
    monkeypatch.delenv("ADMIN_BYPASS_AUTH", raising=False)
    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ID}/turnos-estudio",
        json={"fecha": "2033-04-11", "start": "14:00", "horas": 2},
    )
    assert r.status_code == 401


def test_post_agrega_turno_y_devuelve_el_pedido_completo(client_con_db, setup):
    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ID}/turnos-estudio",
        json={"fecha": "2033-04-11", "start": "14:00", "horas": 2, "espacio_monto": 15000},
    )
    assert r.status_code == 201, r.text
    pedido = r.json()

    assert pedido["id"] == PEDIDO_ID
    assert pedido["monto_total"] == 30000 + 15000
    assert len(pedido["turnos_estudio_embebidos"]) == 1
    turno = pedido["turnos_estudio_embebidos"][0]
    assert turno["monto_total"] == 15000
    assert turno["fecha_desde"].startswith("2033-04-11T14:00")
    assert pedido.get("promo_advertencia") is None

    item_turno = next(it for it in pedido["items"] if it.get("turno_estudio_id") == turno["id"])
    assert item_turno["subtotal"] == 15000


def test_post_404_si_el_pedido_no_existe(client_con_db, setup):
    r = client_con_db.post(
        "/api/alquileres/9489999/turnos-estudio",
        json={"fecha": "2033-04-11", "start": "14:00", "horas": 2},
    )
    assert r.status_code == 404


def test_post_400_si_el_pedido_no_es_diaria(client_con_db, setup):
    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ESTUDIO_ID}/turnos-estudio",
        json={"fecha": "2033-04-11", "start": "14:00", "horas": 2},
    )
    assert r.status_code == 400


def test_post_422_si_espacio_monto_es_negativo(client_con_db, setup):
    """Hallazgo de auditoría: un `espacio_monto` negativo no se chequeaba —
    restaría del `monto_total` del pedido contenedor en vez de sumar. Mismo
    validador (`_validar_espacio_monto`) que el turno STANDALONE
    (`test_estudio_admin_reservas_db.py::test_crear_reserva_admin_rechaza_espacio_monto_negativo`)."""
    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ID}/turnos-estudio",
        json={"fecha": "2033-04-11", "start": "14:00", "horas": 2, "espacio_monto": -1},
    )
    assert r.status_code == 422, r.text


def test_patch_reprograma_y_aplica_descuento(client_con_db, setup):
    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ID}/turnos-estudio",
        json={"fecha": "2033-04-11", "start": "14:00", "horas": 2, "espacio_monto": 20000},
    )
    turno_id = r.json()["turnos_estudio_embebidos"][0]["id"]

    r2 = client_con_db.patch(
        f"/api/alquileres/{PEDIDO_ID}/turnos-estudio/{turno_id}",
        json={
            "start": "16:00", "horas": 2, "espacio_monto": 20000,
            "descuento_pct": 10.0, "descuento_manual_tipo": "pct",
        },
    )
    assert r2.status_code == 200, r2.text
    pedido = r2.json()
    turno = pedido["turnos_estudio_embebidos"][0]
    assert turno["fecha_desde"].endswith("T16:00:00")
    assert float(turno["descuento_pct"]) == 10.0
    assert turno["monto_total"] == pytest.approx(18000, abs=1)  # 20000 × 0.9
    assert pedido["monto_total"] == pytest.approx(30000 + 18000, abs=1)


def test_patch_422_si_espacio_monto_es_negativo(client_con_db, setup):
    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ID}/turnos-estudio",
        json={"fecha": "2033-04-11", "start": "14:00", "horas": 2, "espacio_monto": 20000},
    )
    turno_id = r.json()["turnos_estudio_embebidos"][0]["id"]

    r2 = client_con_db.patch(
        f"/api/alquileres/{PEDIDO_ID}/turnos-estudio/{turno_id}",
        json={"espacio_monto": -500},
    )
    assert r2.status_code == 422, r2.text


def test_patch_404_si_el_turno_no_pertenece_a_ese_pedido(client_con_db, setup):
    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ID}/turnos-estudio",
        json={"fecha": "2033-04-11", "start": "10:00", "horas": 2, "espacio_monto": 10000},
    )
    turno_id = r.json()["turnos_estudio_embebidos"][0]["id"]

    r2 = client_con_db.patch(
        f"/api/alquileres/{OTRO_PEDIDO_ID}/turnos-estudio/{turno_id}",
        json={"espacio_monto": 5000},
    )
    assert r2.status_code == 404


def test_delete_saca_el_turno_y_devuelve_el_pedido_actualizado(client_con_db, setup):
    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ID}/turnos-estudio",
        json={"fecha": "2033-04-11", "start": "14:00", "horas": 2, "espacio_monto": 15000},
    )
    turno_id = r.json()["turnos_estudio_embebidos"][0]["id"]
    assert r.json()["monto_total"] == 30000 + 15000

    r2 = client_con_db.delete(f"/api/alquileres/{PEDIDO_ID}/turnos-estudio/{turno_id}")
    assert r2.status_code == 200, r2.text
    pedido = r2.json()
    assert pedido["turnos_estudio_embebidos"] == []
    assert pedido["monto_total"] == 30000
    assert not any(it.get("turno_estudio_id") == turno_id for it in pedido["items"])


def test_delete_404_si_el_turno_no_pertenece_a_ese_pedido(client_con_db, setup):
    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ID}/turnos-estudio",
        json={"fecha": "2033-04-11", "start": "10:00", "horas": 2, "espacio_monto": 10000},
    )
    turno_id = r.json()["turnos_estudio_embebidos"][0]["id"]

    r2 = client_con_db.delete(f"/api/alquileres/{OTRO_PEDIDO_ID}/turnos-estudio/{turno_id}")
    assert r2.status_code == 404
    # Sigue existiendo — el guard rechazó ANTES de borrar.
    r3 = client_con_db.get(f"/api/alquileres/{PEDIDO_ID}")
    assert len(r3.json()["turnos_estudio_embebidos"]) == 1


def test_delete_409_si_dejaria_el_pedido_sobrepagado(client_con_db, setup):
    """Hallazgo de auditoría: `eliminar_turno_embebido` borraba el turno sin
    mirar si el pedido ya tenía plata cobrada por encima de lo que quedaría —
    mismo espíritu que el gate de "plata cobrada" del mecanismo VIEJO
    (turno vinculado), adaptado (acá no hay `monto_pagado` propio del turno)."""
    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ID}/turnos-estudio",
        json={"fecha": "2033-04-11", "start": "14:00", "horas": 2, "espacio_monto": 15000},
    )
    turno_id = r.json()["turnos_estudio_embebidos"][0]["id"]
    assert r.json()["monto_total"] == 30000 + 15000

    # Se cobran 40000: más que los 30000 que quedarían al sacar el turno
    # (30000 + 15000 − 15000), pero menos que el total actual (45000).
    rp = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ID}/pagos",
        json={"monto": 40000},
    )
    assert rp.status_code == 201, rp.text

    r2 = client_con_db.delete(f"/api/alquileres/{PEDIDO_ID}/turnos-estudio/{turno_id}")
    assert r2.status_code == 409, r2.text

    # No se borró nada: ni el turno ni sus ítems.
    r3 = client_con_db.get(f"/api/alquileres/{PEDIDO_ID}")
    assert len(r3.json()["turnos_estudio_embebidos"]) == 1


def test_delete_permite_si_el_pago_no_supera_el_nuevo_total(client_con_db, setup):
    """Control: el mismo escenario, pero con un pago que SÍ entra dentro de lo
    que quedaría tras sacar el turno — no debe bloquearse."""
    r = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ID}/turnos-estudio",
        json={"fecha": "2033-04-11", "start": "14:00", "horas": 2, "espacio_monto": 15000},
    )
    turno_id = r.json()["turnos_estudio_embebidos"][0]["id"]

    # Se cobran 20000: entra sin problema en los 30000 que quedarían.
    rp = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ID}/pagos",
        json={"monto": 20000},
    )
    assert rp.status_code == 201, rp.text

    r2 = client_con_db.delete(f"/api/alquileres/{PEDIDO_ID}/turnos-estudio/{turno_id}")
    assert r2.status_code == 200, r2.text
    assert r2.json()["monto_total"] == 30000


def test_multi_turno_en_el_mismo_pedido(client_con_db, setup):
    """El schema soporta N turnos por pedido — el endpoint no está limitado a
    uno solo (#1308 Fase 4, "+ Agregar otro turno")."""
    r1 = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ID}/turnos-estudio",
        json={"fecha": "2033-04-11", "start": "10:00", "horas": 2, "espacio_monto": 10000},
    )
    assert r1.status_code == 201, r1.text
    r2 = client_con_db.post(
        f"/api/alquileres/{PEDIDO_ID}/turnos-estudio",
        json={"fecha": "2033-04-12", "start": "10:00", "horas": 2, "espacio_monto": 20000},
    )
    assert r2.status_code == 201, r2.text
    pedido = r2.json()
    assert len(pedido["turnos_estudio_embebidos"]) == 2
    assert pedido["monto_total"] == 30000 + 10000 + 20000
