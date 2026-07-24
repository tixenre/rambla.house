"""Alta/gestión admin de reservas del Estudio + agenda (#1283 Fase 6) contra
Postgres REAL.

El admin puede cargar/reprogramar un turno sin el flujo público (sin sesión de
cliente, sin Didit, sin anticipación mínima — "el admin carga urgencias a
mano"), con equipos sueltos además de pack/promo. Reusa el mismo núcleo
(`_crear_pedido_estudio`) que el flujo público: la disponibilidad/stock no se
revalida distinto según quién crea el pedido.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_estudio_admin_reservas_db.py -v -m integration
"""
import os
import threading
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

CLIENTE_ID = 9_475_001
EQ_SUELTO, EQ_SUELTO_UNICO = 9_475_002, 9_475_003
EQ_PROMO_COMP = 9_475_004
PROMO_COMBO_ID = 9_475_005
PED_EXTRA = 9_475_090


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE cliente_id = %s OR cliente_nombre LIKE %s OR id = %s)",
        (CLIENTE_ID, "Reserva admin test%", PED_EXTRA),
    )
    conn.execute(
        "DELETE FROM alquileres WHERE cliente_id = %s OR cliente_nombre LIKE %s OR id = %s",
        (CLIENTE_ID, "Reserva admin test%", PED_EXTRA),
    )
    conn.execute("UPDATE estudio SET promo_combo_id = NULL WHERE id = 1")
    conn.execute("DELETE FROM kit_componentes WHERE equipo_id = %s", (PROMO_COMBO_ID,))
    conn.execute(
        "DELETE FROM equipos WHERE id IN (%s,%s,%s,%s)",
        (EQ_SUELTO, EQ_SUELTO_UNICO, EQ_PROMO_COMP, PROMO_COMBO_ID),
    )
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'Cliente','Admin Estudio','adminestudio@test.com','+5491100000000')",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada, visible_catalogo, dueno) "
            "VALUES (%s,'Suelto admin test',3,2000,1,'Pablo')",
            (EQ_SUELTO,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada, visible_catalogo, dueno) "
            "VALUES (%s,'Suelto único admin test',1,1000,1,'Tincho')",
            (EQ_SUELTO_UNICO,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada, visible_catalogo, dueno) "
            "VALUES (%s,'Componente promo admin test',5,1000,1,'Rambla')",
            (EQ_PROMO_COMP,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, tipo, dueno, visible_catalogo) "
            "VALUES (%s,%s,1,%s,%s,%s)",
            (PROMO_COMBO_ID, "Promo admin test", "combo", "Rambla", 0),
        )
        conn.execute(
            "INSERT INTO kit_componentes (equipo_id, componente_id, cantidad, descuento_pct) "
            "VALUES (%s,%s,1,0)",
            (PROMO_COMBO_ID, EQ_PROMO_COMP),
        )
        conn.execute(
            "UPDATE estudio SET precio_hora=10000, promo_combo_id=%s, pack_activo=FALSE, "
            "buffer_horas=0, min_horas=1, open_hour=0, close_hour=24, anticipacion_min_horas=48 "
            "WHERE id=1",
            (PROMO_COMBO_ID,),
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
        yield c


def test_guard_admin_rechaza_sin_bypass(client_con_db, setup, monkeypatch):
    monkeypatch.delenv("ADMIN_BYPASS_AUTH", raising=False)
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={"fecha": "2030-05-01", "start": "10:00", "horas": 2, "cliente_nombre": "X"},
    )
    assert r.status_code == 401


def test_crear_reserva_admin_con_cliente_id_y_suelto(client_con_db, setup):
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-05-02", "start": "10:00", "horas": 2,
            "cliente_id": CLIENTE_ID,
            "sueltos": [{"equipo_id": EQ_SUELTO, "cantidad": 1}],
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["estado"] == "confirmado"  # default

    from database import get_db
    conn = get_db()
    try:
        pedido = conn.execute(
            "SELECT monto_total, cliente_id, cliente_nombre, fuente, tipo "
            "FROM alquileres WHERE id=%s", (data["id"],),
        ).fetchone()
        items = conn.execute(
            "SELECT equipo_id, cantidad, subtotal FROM alquiler_items WHERE pedido_id=%s ORDER BY id",
            (data["id"],),
        ).fetchall()
    finally:
        conn.close()

    # 10000/h × 2h + 2000 (suelto) = 22000. Sin gate de identidad (sin Didit).
    assert pedido["monto_total"] == 22000
    assert pedido["cliente_id"] == CLIENTE_ID
    assert pedido["cliente_nombre"] == "Cliente Admin Estudio"
    assert pedido["tipo"] == "estudio"
    assert sum(it["subtotal"] for it in items) == 22000
    suelto = next(it for it in items if it["equipo_id"] == EQ_SUELTO)
    assert suelto["cantidad"] == 1
    assert suelto["subtotal"] == 2000


def test_crear_reserva_admin_con_cliente_nombre_libre(client_con_db, setup):
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-05-03", "start": "10:00", "horas": 2,
            "cliente_nombre": "Reserva admin test — Juan Walk-in",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["cliente_id"] is None
    assert r.json()["cliente_nombre"] == "Reserva admin test — Juan Walk-in"


def test_crear_reserva_admin_rechaza_ambos_cliente(client_con_db, setup):
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-05-04", "start": "10:00", "horas": 2,
            "cliente_id": CLIENTE_ID, "cliente_nombre": "Reserva admin test — X",
        },
    )
    assert r.status_code == 400


def test_crear_reserva_admin_rechaza_sin_cliente(client_con_db, setup):
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={"fecha": "2030-05-05", "start": "10:00", "horas": 2},
    )
    assert r.status_code == 400


def test_crear_reserva_admin_con_promo_y_espacio_override(client_con_db, setup):
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-05-06", "start": "10:00", "horas": 2,
            "cliente_nombre": "Reserva admin test — con promo",
            "con_promo": True, "espacio_monto": 5000,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    # espacio override (5000, no 20000) + promo (1000, sin descuento) = 6000.
    assert data["monto_total"] == 6000


def test_crear_reserva_admin_sueltos_sin_stock_da_409_y_no_persiste(client_con_db, setup):
    # EQ_SUELTO_UNICO tiene cantidad=1 — pedir 2 no puede cumplirse.
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-05-07", "start": "10:00", "horas": 2,
            "cliente_nombre": "Reserva admin test — sin stock",
            "sueltos": [{"equipo_id": EQ_SUELTO_UNICO, "cantidad": 2}],
        },
    )
    assert r.status_code == 409

    from database import get_db
    conn = get_db()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM alquileres WHERE cliente_nombre LIKE %s",
            ("Reserva admin test — sin stock%",),
        ).fetchone()["n"]
    finally:
        conn.close()
    assert n == 0


def test_listar_reservas_admin_incluye_contacto_en_vivo(client_con_db, setup):
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={"fecha": "2030-05-08", "start": "10:00", "horas": 2, "cliente_id": CLIENTE_ID},
    )
    assert r.status_code == 201, r.text

    # Cambiar el nombre del cliente DESPUÉS de crear la reserva.
    from database import get_db
    conn = get_db()
    try:
        conn.execute("UPDATE clientes SET nombre = 'Nombre Actualizado' WHERE id = %s", (CLIENTE_ID,))
        conn.commit()
    finally:
        conn.close()

    r2 = client_con_db.get("/api/admin/estudio/reservas", params={"desde": "2030-05-08", "hasta": "2030-05-08"})
    assert r2.status_code == 200
    reservas = r2.json()["reservas"]
    assert len(reservas) == 1
    # Contacto en vivo (MEMORIA 2026-06-06): el nombre mostrado es el ACTUAL, no
    # la foto congelada al crear.
    assert "Nombre Actualizado" in reservas[0]["cliente_nombre"]


def test_cotizar_no_muta_nada(client_con_db, setup):
    from database import get_db
    conn = get_db()
    try:
        antes = conn.execute("SELECT COUNT(*) AS n FROM alquileres").fetchone()["n"]
        antes_items = conn.execute("SELECT COUNT(*) AS n FROM alquiler_items").fetchone()["n"]
    finally:
        conn.close()

    r = client_con_db.get(
        "/api/admin/estudio/reservas/cotizar",
        params={
            "fecha": "2030-05-09", "start": "10:00", "horas": 3,
            "con_promo": "true",
            "sueltos_json": f'[{{"equipo_id":{EQ_SUELTO},"cantidad":2}}]',
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["espacio"] == 30000
    assert data["promo"] == 1000
    assert data["sueltos"] == [
        {"equipo_id": EQ_SUELTO, "cantidad": 2, "precio_jornada": 2000, "subtotal": 4000}
    ]
    assert data["monto_total"] == 35000
    assert data["espacio_disponible"] is True

    conn = get_db()
    try:
        despues = conn.execute("SELECT COUNT(*) AS n FROM alquileres").fetchone()["n"]
        despues_items = conn.execute("SELECT COUNT(*) AS n FROM alquiler_items").fetchone()["n"]
    finally:
        conn.close()
    assert despues == antes
    assert despues_items == antes_items


def test_editar_reserva_reprograma_y_revalida(client_con_db, setup):
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-05-10", "start": "10:00", "horas": 2,
            "cliente_nombre": "Reserva admin test — editar",
        },
    )
    assert r.status_code == 201, r.text
    pedido_id = r.json()["id"]

    r2 = client_con_db.patch(
        f"/api/admin/estudio/reservas/{pedido_id}",
        json={"fecha": "2030-05-11", "start": "14:00", "horas": 3},
    )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["monto_total"] == 30000  # 10000 × 3h

    from database import get_db
    conn = get_db()
    try:
        pedido = conn.execute(
            "SELECT fecha_desde, fecha_hasta FROM alquileres WHERE id=%s", (pedido_id,)
        ).fetchone()
    finally:
        conn.close()
    assert pedido["fecha_desde"].isoformat().startswith("2030-05-11T14:00")


def test_editar_reserva_agrega_suelto(client_con_db, setup):
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-05-12", "start": "10:00", "horas": 2,
            "cliente_nombre": "Reserva admin test — agregar suelto",
        },
    )
    pedido_id = r.json()["id"]

    r2 = client_con_db.patch(
        f"/api/admin/estudio/reservas/{pedido_id}",
        json={"sueltos": [{"equipo_id": EQ_SUELTO, "cantidad": 1}]},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["monto_total"] == 22000  # 20000 (espacio sin cambios) + 2000


def test_editar_reserva_bloquea_estudio_fijo(client_con_db, setup):
    from database import get_db
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,'Slot fijo test','confirmado','estudio_fijo','2030-05-13T10:00:00','2030-05-13T12:00:00',5000)",
            (PED_EXTRA,),
        )
        conn.commit()
    finally:
        conn.close()

    r = client_con_db.patch(
        f"/api/admin/estudio/reservas/{PED_EXTRA}",
        json={"horas": 3},
    )
    assert r.status_code == 409


def test_agenda_muestra_turno_slot_y_taller(client_con_db, setup):
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-05-20", "start": "10:00", "horas": 2,
            "cliente_nombre": "Reserva admin test — agenda",
        },
    )
    assert r.status_code == 201, r.text

    from database import get_db
    conn = get_db()
    slot_id = None
    try:
        slot_id = conn.execute(
            "INSERT INTO estudio_slots_fijos (cliente, dia_semana, hora_desde, hora_hasta, "
            "valor_mensual, mes_desde, mes_hasta, activo) "
            "VALUES ('Cliente agenda test', 0, 8, 10, 50000, '2030-05', '2030-05', TRUE) "
            "RETURNING id"
        ).fetchone()["id"]
        conn.commit()
    finally:
        conn.close()

    try:
        r2 = client_con_db.get(
            "/api/admin/estudio/agenda", params={"desde": "2030-05-01", "hasta": "2030-05-31"}
        )
        assert r2.status_code == 200
        bloques = r2.json()["bloques"]
        tipos = {b["tipo"] for b in bloques}
        assert "turno" in tipos
        titulos_turno = [b["titulo"] for b in bloques if b["tipo"] == "turno"]
        assert any("agenda" in t for t in titulos_turno)
        if slot_id:
            assert "slot" in tipos
    finally:
        conn2 = get_db()
        try:
            conn2.execute("DELETE FROM estudio_slots_fijos WHERE cliente = 'Cliente agenda test'")
            conn2.commit()
        finally:
            conn2.close()


def _crear_admin(idx, resultados, errores, fecha, start, horas):
    from starlette.requests import Request
    from routes.estudio import crear_reserva_estudio_admin, EstudioReservaAdminCreate

    req = Request(
        {"type": "http", "method": "POST", "path": "/api/admin/estudio/reservas",
         "headers": [], "client": ("127.0.0.1", 0)}
    )
    try:
        body = EstudioReservaAdminCreate(
            fecha=fecha, start=start, horas=horas,
            cliente_nombre=f"Reserva admin test — concurrencia {idx}",
        )
        pedido = crear_reserva_estudio_admin(body, req)
        resultados[idx] = ("ok", pedido["id"])
    except Exception as e:  # noqa: BLE001 — clasificamos abajo
        from fastapi import HTTPException
        if isinstance(e, HTTPException):
            resultados[idx] = ("http", e.status_code)
        else:
            errores[idx] = repr(e)


def test_concurrencia_admin_dos_altas_misma_franja_solo_una_pasa(setup, monkeypatch):
    """Dos altas admin concurrentes para la MISMA franja exacta del espacio:
    el lock del centinela (FOR UPDATE, sin tocar el motor) tiene que serializar
    — nunca las dos deben pasar (overbooking del espacio)."""
    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    resultados: dict[int, object] = {}
    errores: dict[int, str] = {}
    barrera = threading.Barrier(2)

    def _run(idx):
        barrera.wait(timeout=5)
        _crear_admin(idx, resultados, errores, "2030-06-01", "10:00", 2)

    threads = [threading.Thread(target=_run, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert all(not t.is_alive() for t in threads), "deadlock: algún hilo no terminó"
    assert not errores, f"excepciones no controladas: {errores}"

    oks = [v for v in resultados.values() if v[0] == "ok"]
    fails = [v for v in resultados.values() if v[0] == "http"]
    assert len(oks) == 1, f"esperaba exactamente 1 alta exitosa, hubo {len(oks)}: {resultados}"
    assert all(c == 409 for _, c in fails)

    from database import get_db
    conn = get_db()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM alquileres WHERE cliente_nombre LIKE %s",
            ("Reserva admin test — concurrencia%",),
        ).fetchone()["n"]
    finally:
        conn.close()
    assert n == 1
