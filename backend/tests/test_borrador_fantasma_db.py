"""Un BORRADOR es un presupuesto rápido, no una venta (decisión del dueño:
"los borradores me gustaría que sean más fantasmas... son presupuestos rápidos,
así no contabilizan en los pedidos totales").

En concreto:
  1. Nace SIN `numero_pedido` — no consume un número de la secuencia ni parece
     un pedido real en pantalla.
  2. Recibe su número recién cuando pasa a un estado REAL del camino feliz
     (`FLOW`), que es cuando deja de ser un borrador. Un borrador descartado
     (→ `cancelado`) no gasta un número.
  3. No necesita cliente (ya cubierto por `test_pedido_sin_cliente_guarda_db.py`).
  4. Se cuenta APARTE del "N pedidos" de la lista (sigue listándose, no suma).
  5. Se borra de verdad (hard delete) — no es soft delete.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_borrador_fantasma_db.py -v -m integration
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

EQ_ID = 9_499_301
MARCA_Q = "borradorfantasma"


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE cliente_nombre LIKE %s)",
        (f"%{MARCA_Q}%",),
    )
    conn.execute("DELETE FROM alquileres WHERE cliente_nombre LIKE %s", (f"%{MARCA_Q}%",))
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQ_ID,))


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    from database import get_db

    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada) VALUES (%s,%s,4,10000)",
            (EQ_ID, "Equipo test (borrador fantasma)"),
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


def _crear(client, estado):
    r = client.post(
        "/api/alquileres",
        json={
            "cliente_nombre": f"{MARCA_Q} {estado}",
            "estado": estado,
            "fecha_desde": "2034-10-01",
            "fecha_hasta": "2034-10-03",
            "items": [{"equipo_id": EQ_ID, "cantidad": 1, "precio_jornada": 10000}],
        },
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_un_borrador_nace_sin_numero_de_pedido(client_con_db, setup):
    """Discrimina: antes `create_pedido` sacaba un número de la secuencia SIEMPRE,
    así que un borrador se veía como "#425" — un pedido real que no era."""
    p = _crear(client_con_db, "borrador")
    assert p["estado"] == "borrador"
    assert p["numero_pedido"] is None


def test_un_pedido_no_borrador_sigue_naciendo_con_numero(client_con_db, setup):
    p = _crear(client_con_db, "solicitado")
    assert p["numero_pedido"] is not None


def test_el_numero_se_asigna_al_dejar_de_ser_borrador(client_con_db, setup):
    """Pasar a `solicitado` (no solo a `confirmado`) ya lo convierte en un pedido
    real → ahí recibe su número."""
    p = _crear(client_con_db, "borrador")
    assert p["numero_pedido"] is None

    r = client_con_db.patch(f"/api/alquileres/{p['id']}", json={"estado": "solicitado"})
    assert r.status_code == 200, r.text
    assert r.json()["numero_pedido"] is not None


def test_un_borrador_descartado_no_gasta_un_numero(client_con_db, setup):
    """`cancelado` está fuera de `FLOW`: descartar un presupuesto rápido no
    consume un número de la secuencia."""
    p = _crear(client_con_db, "borrador")
    r = client_con_db.patch(f"/api/alquileres/{p['id']}", json={"estado": "cancelado"})
    assert r.status_code == 200, r.text
    assert r.json()["numero_pedido"] is None


def test_la_lista_cuenta_los_borradores_aparte(client_con_db, setup):
    """Siguen apareciendo en la lista (el dueño los quiere a mano), pero el
    "N pedidos" del header no los suma."""
    _crear(client_con_db, "borrador")
    _crear(client_con_db, "borrador")
    _crear(client_con_db, "solicitado")

    r = client_con_db.get("/api/alquileres", params={"q": MARCA_Q})
    assert r.status_code == 200, r.text
    d = r.json()

    assert d["total"] == 3, "los 3 siguen listándose"
    assert d["borradores"] == 2
    assert d["total"] - d["borradores"] == 1, "solo 1 es un pedido de verdad"
    assert len(d["items"]) == 3


def test_borrar_un_borrador_lo_borra_de_verdad(client_con_db, setup):
    """Hard delete, no soft delete: la fila desaparece de la base."""
    from database import get_db

    p = _crear(client_con_db, "borrador")
    r = client_con_db.delete(f"/api/alquileres/{p['id']}")
    assert r.status_code == 204, r.text

    conn = get_db()
    try:
        assert conn.execute(
            "SELECT id FROM alquileres WHERE id = %s", (p["id"],)
        ).fetchone() is None
        assert conn.execute(
            "SELECT id FROM alquiler_items WHERE pedido_id = %s", (p["id"],)
        ).fetchone() is None
    finally:
        conn.close()


def test_los_borradores_van_PRIMERO_en_la_lista(client_con_db, setup):
    """Discrimina: con el orden viejo ("sin número al final") un borrador caía
    detrás de TODOS los pedidos numerados — o sea, fuera de la primera página
    con volumen real. El dueño no los encontraba ("este borrador no me aparece
    en el listado")."""
    _crear(client_con_db, "solicitado")
    _crear(client_con_db, "solicitado")
    b = _crear(client_con_db, "borrador")

    d = client_con_db.get("/api/alquileres", params={"q": MARCA_Q}).json()
    ids = [x["id"] for x in d["items"]]
    assert ids[0] == b["id"], f"el borrador tiene que abrir la lista, quedó en {ids.index(b['id'])}"
    # y los numerados siguen ordenados entre ellos como siempre (desc)
    numerados = [x["numero_pedido"] for x in d["items"] if x["numero_pedido"] is not None]
    assert numerados == sorted(numerados, reverse=True)


def test_el_mas_nuevo_de_los_borradores_va_arriba(client_con_db, setup):
    """Sin número no hay con qué desempatar: manda la fecha de creación."""
    from database import get_db

    b1 = _crear(client_con_db, "borrador")
    b2 = _crear(client_con_db, "borrador")
    # `created_at` tiene resolución de microsegundos pero los dos se crean en el
    # mismo instante de test — se separa a mano para que el orden sea inequívoco.
    conn = get_db()
    try:
        conn.execute(
            "UPDATE alquileres SET created_at = created_at - INTERVAL '1 hour' WHERE id = %s",
            (b1["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    d = client_con_db.get("/api/alquileres", params={"q": MARCA_Q}).json()
    ids = [x["id"] for x in d["items"]]
    assert ids[0] == b2["id"] and ids[1] == b1["id"], ids


def test_se_pueden_pedir_SOLO_los_borradores(client_con_db, setup):
    """El filtro de la pestaña "Borradores" del listado."""
    _crear(client_con_db, "borrador")
    _crear(client_con_db, "solicitado")

    d = client_con_db.get(
        "/api/alquileres", params={"q": MARCA_Q, "estado": "borrador"}
    ).json()
    assert d["total"] == 1
    assert [x["estado"] for x in d["items"]] == ["borrador"]
