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

CLIENTE_ID = 9_475_001
EQ_SUELTO, EQ_SUELTO_UNICO = 9_475_002, 9_475_003
EQ_PROMO_COMP = 9_475_004
PROMO_COMBO_ID = 9_475_005
PED_EXTRA = 9_475_090
OCUPANTE_PROMO_ID = 9_475_091


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE cliente_id = %s OR cliente_nombre LIKE %s "
        "OR id IN (%s,%s))",
        (CLIENTE_ID, "Reserva admin test%", PED_EXTRA, OCUPANTE_PROMO_ID),
    )
    conn.execute(
        "DELETE FROM alquileres WHERE cliente_id = %s OR cliente_nombre LIKE %s "
        "OR id IN (%s,%s)",
        (CLIENTE_ID, "Reserva admin test%", PED_EXTRA, OCUPANTE_PROMO_ID),
    )
    conn.execute("UPDATE estudio SET promo_combo_id = NULL WHERE id = 1")
    conn.execute("DELETE FROM kit_componentes WHERE equipo_id = %s", (PROMO_COMBO_ID,))
    conn.execute(
        "DELETE FROM equipos WHERE id IN (%s,%s,%s,%s)",
        (EQ_SUELTO, EQ_SUELTO_UNICO, EQ_PROMO_COMP, PROMO_COMBO_ID),
    )
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))


def _limpiar_con_retry(conn, intentos: int = 3) -> None:
    """`_limpiar` con reintento ante `DeadlockDetected` transitorio — mismo
    patrón que `test_estudio_disponibilidad_publica_db.py`: el job de CI corre
    ~20 archivos `test_*_db.py` como steps secuenciales contra el MISMO
    contenedor Postgres, y el `init_db()` de un step posterior (`ALTER TABLE
    ... ADD COLUMN`) puede pedir un lock que este `DELETE` de limpieza ya tiene
    tomado — Postgres mata a una de las dos transacciones con
    `DeadlockDetected` (issue #1304, 3 ocurrencias reales en CI con esta
    firma). Reintentar es la respuesta esperada, no una tapa de un bug real."""
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
def setup(monkeypatch):
    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    # NO llama a init_db() acá: `client_con_db` (module-scoped) ya lo hace, y
    # duplicarlo corre en paralelo con el `db_init_thread` que dispara el
    # `startup` de `TestClient(main.app)` — carrera real que rompió CI en un
    # archivo hermano (DuplicateObject en `spec_propuestas_pendientes_tipo_check`,
    # 2026-07-26).
    from database import get_db

    conn = get_db()
    try:
        _limpiar_con_retry(conn)
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
            "VALUES (%s,'Componente promo admin test',5,1000,1,'Rental')",
            (EQ_PROMO_COMP,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, tipo, dueno, visible_catalogo) "
            "VALUES (%s,%s,1,%s,%s,%s)",
            (PROMO_COMBO_ID, "Promo admin test", "combo", "Rental", 0),
        )
        conn.execute(
            "INSERT INTO kit_componentes (equipo_id, componente_id, cantidad, descuento_pct) "
            "VALUES (%s,%s,1,0)",
            (PROMO_COMBO_ID, EQ_PROMO_COMP),
        )
        conn.execute(
            "UPDATE estudio SET precio_hora=10000, promo_combo_id=%s, pack_activo=FALSE, "
            "buffer_horas=0, min_horas=1, open_hour=0, close_hour=24, anticipacion_min_horas=48, "
            "precio_pintura_reciente=1500 "
            "WHERE id=1",
            (PROMO_COMBO_ID,),
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
    """TestClient con Postgres real. Espera a que `main.db_init_thread`
    (spawneado por el propio `startup` de `TestClient`, corre init_db+alembic+
    seed+catalog en background) termine ANTES de yieldear — sin esto, el DML
    de los fixtures de test podía chocar con el ALTER TABLE de ese thread
    todavía en vuelo (deadlock real en CI, issue #1304)."""
    from database import init_db
    from fastapi.testclient import TestClient

    init_db()
    with TestClient(main.app, raise_server_exceptions=True) as c:
        if main.db_init_thread is not None:
            main.db_init_thread.join(timeout=60)
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
    assert data["promo_advertencia"] is None


def test_crear_reserva_admin_con_promo_sin_stock_es_best_effort(client_con_db, setup):
    """La promo es BEST-EFFORT también desde el admin (mismo núcleo
    `_crear_pedido_estudio` que el flujo público) — a diferencia de un suelto
    (ver `test_crear_reserva_admin_sueltos_sin_stock_da_409_y_no_persiste`,
    que sigue siendo stock DURO), si falta stock de un componente de la
    promo la reserva no se bloquea: se crea igual, cobra el precio fijo
    completo y avisa vía `promo_advertencia`."""
    from database import get_db
    from services.estudio.queries.disponibilidad import _franja_estudio
    from services.estudio.queries.estudio import _get_estudio_row

    conn = get_db()
    try:
        estudio = _get_estudio_row(conn)
        fd, fh = _franja_estudio(estudio, "2030-05-09", "10:00", 2)
        # Agota TODO el stock de EQ_PROMO_COMP (cantidad=5) con otro pedido en
        # la MISMA franja — la promo depende de él, así que el combo deja de
        # tener stock disponible.
        conn.execute(
            """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta, monto_total)
               VALUES (%s,'Ocupante promo admin',%s,%s,%s,5000)""",
            (OCUPANTE_PROMO_ID, "confirmado", fd, fh),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal) VALUES (%s,%s,5,5000)",
            (OCUPANTE_PROMO_ID, EQ_PROMO_COMP),
        )
        conn.commit()
    finally:
        conn.close()

    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-05-09", "start": "10:00", "horas": 2,
            "cliente_nombre": "Reserva admin test — promo best-effort",
            "con_promo": True,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["promo_advertencia"] is not None
    assert "Componente promo admin test" in data["promo_advertencia"]
    # 10000/h × 2h (espacio) + 1000 (promo, precio FIJO completo) = 21000.
    assert data["monto_total"] == 21000


def test_crear_reserva_admin_con_pintura_reciente(client_con_db, setup):
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-05-16", "start": "10:00", "horas": 2,
            "cliente_nombre": "Reserva admin test — pintura",
            "pintura_reciente": True,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    # 10000/h × 2h (espacio) + 1500 (pintura reciente) = 21500.
    assert data["monto_total"] == 21500

    from database import get_db
    conn = get_db()
    try:
        item = conn.execute(
            "SELECT equipo_id, nombre_libre, cobro_modo, subtotal "
            "FROM alquiler_items WHERE pedido_id=%s AND equipo_id IS NULL",
            (data["id"],),
        ).fetchone()
    finally:
        conn.close()
    assert item is not None
    assert item["nombre_libre"] == "Recién pintado"
    assert item["cobro_modo"] == "fijo"
    assert item["subtotal"] == 1500


def test_editar_reserva_agrega_y_luego_quita_pintura_reciente(client_con_db, setup):
    """Bug real encontrado al verificar en vivo (#1300 seguimiento): el
    "reemplazo completo" de `editar_reserva` borraba los ítems no-centinela
    con `equipo_id != %s`, que en SQL NUNCA matchea `equipo_id IS NULL` (la
    fila de pintura reciente) — la línea sobrevivía para siempre a una
    edición que la sacaba, dejando `alquiler_items` desincronizado de
    `monto_total`. Fix: `equipo_id IS DISTINCT FROM %s`."""
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-05-17", "start": "10:00", "horas": 2,
            "cliente_nombre": "Reserva admin test — pintura toggle",
            "pintura_reciente": True,
        },
    )
    assert r.status_code == 201, r.text
    pedido_id = r.json()["id"]
    assert r.json()["monto_total"] == 21500

    r2 = client_con_db.patch(
        f"/api/admin/estudio/reservas/{pedido_id}",
        json={"pintura_reciente": False},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["monto_total"] == 20000  # solo espacio, sin la pintura

    from database import get_db
    conn = get_db()
    try:
        item = conn.execute(
            "SELECT id FROM alquiler_items WHERE pedido_id=%s AND equipo_id IS NULL",
            (pedido_id,),
        ).fetchone()
        suma_items = conn.execute(
            "SELECT COALESCE(SUM(subtotal), 0) AS s FROM alquiler_items WHERE pedido_id=%s",
            (pedido_id,),
        ).fetchone()["s"]
    finally:
        conn.close()
    assert item is None, "la línea de pintura reciente debería haberse borrado al editar"
    assert suma_items == 20000  # coincide con monto_total — sin ítems huérfanos


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

    # `espacio_monto` = la tarifa NEGOCIADA que el admin tipea en la fila
    # "Espacio". Sin esto la cotización devolvía el precio de LISTA aunque el
    # guardado persistiera la negociada → la pantalla mostraba un número
    # distinto al que se iba a cobrar.
    negociada = client_con_db.get(
        "/api/admin/estudio/reservas/cotizar",
        params={
            "fecha": "2030-05-09", "start": "10:00", "horas": 3,
            "con_promo": "true",
            "sueltos_json": f'[{{"equipo_id":{EQ_SUELTO},"cantidad":2}}]',
            "espacio_monto": 99000,
        },
    )
    assert negociada.status_code == 200, negociada.text
    assert negociada.json()["espacio"] == 99000, "la tarifa negociada gana sobre la de lista"
    assert negociada.json()["monto_total"] == 99000 + 1000 + 4000

    conn = get_db()
    try:
        despues = conn.execute("SELECT COUNT(*) AS n FROM alquileres").fetchone()["n"]
        despues_items = conn.execute("SELECT COUNT(*) AS n FROM alquiler_items").fetchone()["n"]
    finally:
        conn.close()
    assert despues == antes
    assert despues_items == antes_items


def test_cotizar_con_pedido_id_se_excluye_a_si_mismo(client_con_db, setup):
    """Bug real encontrado al verificar el editor (#1283 Fase 6): cotizar la
    MISMA franja de un turno ya existente, sin pasar `pedido_id`, lo veía
    "ocupado" por sí mismo — el editor mostraba el aviso de no-disponible
    con solo abrir la reserva, sin cambiar nada."""
    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={"fecha": "2030-05-15", "start": "10:00", "horas": 2, "cliente_id": CLIENTE_ID},
    )
    assert r.status_code == 201, r.text
    pedido_id = r.json()["id"]

    sin_excluir = client_con_db.get(
        "/api/admin/estudio/reservas/cotizar",
        params={"fecha": "2030-05-15", "start": "10:00", "horas": 2},
    )
    assert sin_excluir.status_code == 200, sin_excluir.text
    assert sin_excluir.json()["espacio_disponible"] is False

    con_excluir = client_con_db.get(
        "/api/admin/estudio/reservas/cotizar",
        params={"fecha": "2030-05-15", "start": "10:00", "horas": 2, "pedido_id": pedido_id},
    )
    assert con_excluir.status_code == 200, con_excluir.text
    assert con_excluir.json()["espacio_disponible"] is True


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


def test_editar_reserva_agrega_promo_sin_stock_es_best_effort(client_con_db, setup):
    """Mismo criterio best-effort que la creación (ver
    `test_crear_reserva_admin_con_promo_sin_stock_es_best_effort`) — editar un
    turno para sumarle la promo cuando su componente no tiene stock tampoco
    bloquea, cobra el precio fijo completo y avisa."""
    from database import get_db
    from services.estudio.queries.disponibilidad import _franja_estudio
    from services.estudio.queries.estudio import _get_estudio_row

    r = client_con_db.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": "2030-05-14", "start": "10:00", "horas": 2,
            "cliente_nombre": "Reserva admin test — editar promo best-effort",
        },
    )
    assert r.status_code == 201, r.text
    pedido_id = r.json()["id"]

    conn = get_db()
    try:
        estudio = _get_estudio_row(conn)
        fd, fh = _franja_estudio(estudio, "2030-05-14", "10:00", 2)
        conn.execute(
            """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta, monto_total)
               VALUES (%s,'Ocupante promo admin edit',%s,%s,%s,5000)""",
            (OCUPANTE_PROMO_ID, "confirmado", fd, fh),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal) VALUES (%s,%s,5,5000)",
            (OCUPANTE_PROMO_ID, EQ_PROMO_COMP),
        )
        conn.commit()
    finally:
        conn.close()

    r2 = client_con_db.patch(
        f"/api/admin/estudio/reservas/{pedido_id}",
        json={"con_promo": True},
    )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["promo_advertencia"] is not None
    assert "Componente promo admin test" in data["promo_advertencia"]
    assert data["monto_total"] == 21000  # 20000 (espacio) + 1000 (promo completo)


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
