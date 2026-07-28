"""Regresión Fase B (#1219): la LISTA de pedidos del portal cliente (`GET
/api/cliente/pedidos`) tiene que traer el mismo desglose canónico (bruto/
descuento/neto/IVA) que el DETALLE (`GET /api/cliente/pedidos/{id}`).

Antes de este fix, la lista no seleccionaba `descuento_jornadas_pct` ni
llamaba a `_enriquecer_pedido_con_total` — cuando el descuento GANADOR era el
de jornadas (no el del cliente), la lista podía mostrar 0%/$0 de descuento
donde el detalle mostraba el correcto. Acá se arma un pedido donde gana el
de jornadas (20% > 5% del cliente) y se compara lista vs. detalle byte-a-byte.

Contra Postgres real: `_enriquecer_pedido_con_total` hace un SELECT de
`clientes.perfil_impuestos` — fakearlo sería más frágil que útil.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py): se saltea
salvo RESERVAS_DB_TEST=1 + DATABASE_URL con 'test' en el nombre.
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
        not _OPT_IN, reason="opt-in: setear RESERVAS_DB_TEST=1 + DATABASE_URL a una base de prueba"
    ),
    pytest.mark.skipif(
        _OPT_IN and not _looks_like_test_db(),
        reason=f"DATABASE_URL ({_DB_NAME!r}) no parece base de test — abortado por seguridad",
    ),
]

import main  # noqa: E402
from auth.session import signer  # noqa: E402

CLIENTE_ID = 9_320_001
PEDIDO_ID = 9_320_101
EQ_ID = 9_320_201
FD, FH = "2031-03-01T10:00:00", "2031-03-04T10:00:00"  # 3 jornadas

_COOKIE = f"session={signer.dumps({'email': 'listadet@test.com', 'role': 'cliente', 'cliente_id': CLIENTE_ID, 'jti': 'listadet-cli'})}"


@pytest.fixture(autouse=True)
def _sessions_active(monkeypatch):
    monkeypatch.setattr("auth.queries.sessions.is_active", lambda jti: {"jti": jti})


def _limpiar(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s" % PEDIDO_ID)
    conn.execute("DELETE FROM alquileres WHERE id = %s" % PEDIDO_ID)
    conn.execute("DELETE FROM equipos WHERE id = %s" % EQ_ID)
    conn.execute("DELETE FROM clientes WHERE id = %s" % CLIENTE_ID)


@pytest.fixture
def setup():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, email, descuento) VALUES (%s,%s,%s,%s)",
            (CLIENTE_ID, "Cliente lista-detalle", "listadet-db@test.com", 5),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada, visible_catalogo) "
            "VALUES (%s,'Equipo lista-detalle',5,1000,1)",
            (EQ_ID,),
        )
        # Sin override manual (descuento_pct=0); descuento_cliente_pct=5 (snapshot
        # del cliente) vs descuento_jornadas_pct=20 (jornadas) — gana jornadas
        # (fallback de la jerarquía, Fase C-1 #1219 — el manual está en 0).
        conn.execute(
            "INSERT INTO alquileres "
            "(id, cliente_id, cliente_nombre, estado, fecha_desde, fecha_hasta, "
            " descuento_pct, descuento_cliente_pct, descuento_jornadas_pct) "
            "VALUES (%s,%s,'Cliente lista-detalle','solicitado',%s,%s,0,5,20)",
            (PEDIDO_ID, CLIENTE_ID, FD, FH),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
            "VALUES (%s,%s,1,1000,3000)",
            (PEDIDO_ID, EQ_ID),
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


_CAMPOS_DESGLOSE = (
    "bruto", "descuento_monto", "monto_neto", "iva_pct", "iva_monto",
    "total_con_iva", "con_iva", "cantidad_jornadas",
)


def test_lista_trae_el_mismo_desglose_que_el_detalle(client_con_db, setup):
    r_lista = client_con_db.get("/api/cliente/pedidos", headers={"Cookie": _COOKIE})
    assert r_lista.status_code == 200, r_lista.text
    items = [p for p in r_lista.json() if p["id"] == PEDIDO_ID]
    assert len(items) == 1
    de_lista = items[0]

    r_detalle = client_con_db.get(f"/api/cliente/pedidos/{PEDIDO_ID}", headers={"Cookie": _COOKIE})
    assert r_detalle.status_code == 200, r_detalle.text
    de_detalle = r_detalle.json()

    for campo in _CAMPOS_DESGLOSE:
        assert campo in de_lista, f"falta '{campo}' en la lista"
        assert de_lista[campo] == de_detalle[campo], (
            f"'{campo}' difiere: lista={de_lista[campo]!r} vs. detalle={de_detalle[campo]!r}"
        )


def test_gana_el_descuento_de_jornadas_no_el_del_cliente(client_con_db, setup):
    """20% (jornadas) > 5% (cliente) → bruto 3000, descuento 600, neto 2400."""
    r = client_con_db.get("/api/cliente/pedidos", headers={"Cookie": _COOKIE})
    d = next(p for p in r.json() if p["id"] == PEDIDO_ID)
    assert d["bruto"] == 3000
    assert d["descuento_monto"] == 600
    assert d["monto_neto"] == 2400
    assert d["cantidad_jornadas"] == 3


PRODUCTORA_ID = 9_320_301
PRODUCTORA_CUIT = "30500002235"


def test_detalle_resuelve_iva_de_la_productora_elegida_no_del_default(client_con_db, setup):
    """#1240, hallazgo de revisión: el SELECT de `cliente_pedido_detalle` no
    traía `perfil_fiscal_id`/`productora_id` — a diferencia de la LISTA (que sí
    los resuelve), el DETALLE de un pedido facturado a nombre de una productora
    con OTRA condición de IVA que el default de la cuenta mostraba el `con_iva`
    equivocado. El cliente por defecto (sin perfil_impuestos) no es RI; la
    productora acá SÍ lo es — el detalle tiene que reflejarla."""
    from database import get_db

    conn = get_db()
    try:
        conn.execute("DELETE FROM productoras WHERE id = %s", (PRODUCTORA_ID,))
        conn.execute(
            """INSERT INTO productoras (id, cuit, perfil_impuestos, razon_social)
               VALUES (%s, %s, 'responsable_inscripto', 'Productora Detalle SA')""",
            (PRODUCTORA_ID, PRODUCTORA_CUIT),
        )
        conn.execute(
            "UPDATE alquileres SET productora_id = %s WHERE id = %s",
            (PRODUCTORA_ID, PEDIDO_ID),
        )
        conn.commit()

        r_detalle = client_con_db.get(f"/api/cliente/pedidos/{PEDIDO_ID}", headers={"Cookie": _COOKIE})
        assert r_detalle.status_code == 200, r_detalle.text
        assert r_detalle.json()["con_iva"] is True
    finally:
        conn.execute("UPDATE alquileres SET productora_id = NULL WHERE id = %s", (PEDIDO_ID,))
        conn.execute("DELETE FROM productoras WHERE id = %s", (PRODUCTORA_ID,))
        conn.commit()
        conn.close()
