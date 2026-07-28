"""Regresión M6 (#1209) contra Postgres REAL: `cliente_modificar_pedido`
(`routes/cliente_portal/solicitudes.py`, `POST /api/cliente/pedidos/{id}/modificacion`)
debe aplicar el MISMO gate de catálogo que la creación de pedido.

Antes de este fix, el gate `equipo_visible_catalogo` (`services/carrito/readiness.py`
— vivo + `visible_catalogo=1` + NO `es_recurso_interno` + precio definido) solo lo
aplicaba `precios_catalogo_para_reserva` en la CREACIÓN (`cliente_crear_pedido`). Un
cliente podía, vía `POST .../modificacion`, agregar a un presupuesto un equipo
oculto o el recurso interno del Estudio — cosa que la creación sí rechaza —
reservando stock de un recurso que el negocio nunca ofreció públicamente.

Los ítems YA presentes en el pedido (frozen) NO se re-gatean: pueden haberse
ocultado después sin que eso invalide lo ya reservado. Solo los ítems NUEVOS de
la propuesta pasan por el gate.

Contra Postgres real (no un FakeConn): el endpoint hace ~6 SELECTs distintos antes
de llegar al gate (pedido, ventana, solicitud pendiente, precios actuales, ...) —
fakearlos todos sería más frágil que útil. Mismo criterio que los demás `*_db.py`.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py): se saltea salvo
RESERVAS_DB_TEST=1 + DATABASE_URL con 'test' en el nombre.
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
from auth.session import signer  # noqa: E402

# IDs altos (rango 9_31x) para no colisionar con datos reales ni con otros *_db.py.
CLIENTE_ID = 9_310_001
PEDIDO_ID = 9_310_101
EQ_VISIBLE = 9_310_201       # ya está en el pedido (frozen)
EQ_VISIBLE_NUEVO = 9_310_202  # NO está en el pedido — visible, se debe poder agregar
EQ_OCULTO = 9_310_203         # visible_catalogo=0 — el bug M6
EQ_INTERNO = 9_310_204        # es_recurso_interno=TRUE (centinela del Estudio) — el bug M6
FD, FH = "2030-01-01T10:00:00", "2030-01-02T10:00:00"

_COOKIE = f"session={signer.dumps({'email': 'gatecli@test.com', 'role': 'cliente', 'cliente_id': CLIENTE_ID, 'jti': 'modgate-cli'})}"

_TODOS_EQ = (EQ_VISIBLE, EQ_VISIBLE_NUEVO, EQ_OCULTO, EQ_INTERNO)


@pytest.fixture(autouse=True)
def _sessions_active(monkeypatch):
    """jti obligatorio: la cookie de test lleva jti pero no está en la allowlist →
    stubbeamos is_active para darla por activa (mismo patrón que los otros *_db.py
    que autentican con una cookie firmada a mano)."""
    monkeypatch.setattr("auth.queries.sessions.is_active", lambda jti: {"jti": jti})


def _limpiar(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s" % PEDIDO_ID)
    conn.execute("DELETE FROM alquileres WHERE id = %s" % PEDIDO_ID)
    conn.execute("DELETE FROM equipos WHERE id IN %s" % (_TODOS_EQ,))
    conn.execute("DELETE FROM clientes WHERE id = %s" % CLIENTE_ID)


@pytest.fixture
def setup():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, email) VALUES (%s,%s,%s)",
            (CLIENTE_ID, "Cliente gate-test M6", "gatecli-m6-db@test.com"),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada, visible_catalogo) "
            "VALUES (%s,'Visible gate-test (frozen)',5,1000,1)",
            (EQ_VISIBLE,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada, visible_catalogo) "
            "VALUES (%s,'Visible gate-test (nuevo)',5,1500,1)",
            (EQ_VISIBLE_NUEVO,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada, visible_catalogo) "
            "VALUES (%s,'Oculto gate-test',5,1000,0)",
            (EQ_OCULTO,),
        )
        conn.execute(
            "INSERT INTO equipos "
            "(id, nombre, cantidad, precio_jornada, visible_catalogo, es_recurso_interno) "
            "VALUES (%s,'Interno gate-test',1,1000,0,TRUE)",
            (EQ_INTERNO,),
        )
        conn.execute(
            "INSERT INTO alquileres "
            "(id, cliente_id, cliente_nombre, estado, fecha_desde, fecha_hasta) "
            "VALUES (%s,%s,'Cliente gate-test M6','solicitado',%s,%s)",
            (PEDIDO_ID, CLIENTE_ID, FD, FH),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
            "VALUES (%s,%s,1,1000,1000)",
            (PEDIDO_ID, EQ_VISIBLE),
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
    """TestClient con Postgres real. `init_db()` explícito por si el thread de
    arranque de main.py no terminó antes de la primera request del test (mismo
    patrón que `test_routes_admin_guard_db.py`). Además se espera a que
    `main.db_init_thread` (spawneado por el propio `startup` de `TestClient`,
    corre init_db+alembic+seed+catalog en background) termine ANTES de yieldear
    — sin esto, el DML de los fixtures de test podía chocar con el ALTER TABLE
    de ese thread todavía en vuelo (deadlock real en CI, issue #1304)."""
    from database import init_db
    from fastapi.testclient import TestClient

    init_db()
    with TestClient(main.app, raise_server_exceptions=True) as c:
        if main.db_init_thread is not None:
            main.db_init_thread.join(timeout=60)
        yield c


def _modificar(client, items):
    return client.post(
        f"/api/cliente/pedidos/{PEDIDO_ID}/modificacion",
        json={"items": items},
        headers={"Cookie": _COOKIE},
    )


def test_modificar_rechaza_equipo_oculto_nuevo(client_con_db, setup):
    """El caso del bug M6: agregar por modificación un equipo con
    `visible_catalogo=0` debe rechazarse igual que en la creación."""
    res = _modificar(
        client_con_db,
        [
            {"equipo_id": EQ_VISIBLE, "cantidad": 1},   # ya estaba (frozen)
            {"equipo_id": EQ_OCULTO, "cantidad": 1},    # NUEVO + oculto → debe rechazar
        ],
    )
    assert res.status_code == 404, (
        f"Se esperaba 404 al agregar un equipo oculto por modificación, "
        f"se obtuvo {res.status_code}: {res.text}"
    )
    assert str(EQ_OCULTO) in res.json()["detail"]


def test_modificar_rechaza_recurso_interno_nuevo(client_con_db, setup):
    """El recurso interno del Estudio (`es_recurso_interno=TRUE`, el "centinela"
    que modela el espacio físico) tampoco se puede agregar vía modificación,
    aunque tenga `visible_catalogo=1` puesto por error."""
    res = _modificar(
        client_con_db,
        [
            {"equipo_id": EQ_VISIBLE, "cantidad": 1},
            {"equipo_id": EQ_INTERNO, "cantidad": 1},
        ],
    )
    assert res.status_code == 404, (
        f"Se esperaba 404 al agregar el recurso interno por modificación, "
        f"se obtuvo {res.status_code}: {res.text}"
    )
    assert str(EQ_INTERNO) in res.json()["detail"]


def test_modificar_acepta_equipo_visible_nuevo(client_con_db, setup):
    """Control: agregar un equipo NUEVO pero público/visible sí debe aplicarse —
    el gate no debe romper el uso legítimo del portal."""
    res = _modificar(
        client_con_db,
        [
            {"equipo_id": EQ_VISIBLE, "cantidad": 1},
            {"equipo_id": EQ_VISIBLE_NUEVO, "cantidad": 2},
        ],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["tipo"] == "directo"
    equipos_en_pedido = {it["equipo_id"] for it in body["pedido"]["items"]}
    assert EQ_VISIBLE_NUEVO in equipos_en_pedido


def test_modificar_no_re_gatea_item_ya_frozen(client_con_db, setup, monkeypatch):
    """Un ítem YA presente en el pedido no vuelve a pasar por el gate — si se
    ocultó después de reservado, la modificación que NO lo toca no debe fallar."""
    import database as database_mod

    conn = database_mod.get_db()
    try:
        conn.execute(
            "UPDATE equipos SET visible_catalogo = 0 WHERE id = %s", (EQ_VISIBLE,)
        )
        conn.commit()
    finally:
        conn.close()

    res = _modificar(client_con_db, [{"equipo_id": EQ_VISIBLE, "cantidad": 3}])
    assert res.status_code == 200, (
        f"Un ítem ya presente en el pedido no debería re-gatearse por "
        f"visibilidad — se obtuvo {res.status_code}: {res.text}"
    )
