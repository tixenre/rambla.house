"""Fase 2 de la economía del Estudio (ítems veraces), contra Postgres REAL.

Antes de este cambio, los pedidos del Estudio insertaban sus ítems con
`precio_jornada=subtotal=0` (o, para `estudio_fijo`, sin ítem alguno) — la
plata real vivía SOLO en `alquileres.monto_total`. Ahora cada ítem lleva su
plata real (`cobro_modo='fijo'`): el centinela el monto del espacio, y —si
hay pack— una línea personalizada con el precio fijo del pack. Esto es lo
que hace que `Σ subtotal(ítems) == monto_total` (candado central de esta
fase: liquidación/desglose/PDF cierran por construcción, sin excepciones).

También verifica que revalidar la disponibilidad de un slot fijo (editarlo)
no choque contra los ítems centinela de sus PROPIOS pedidos ya generados
(`_centinela_libre(..., exclude_slot_id=...)`).

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://tincho@localhost/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_estudio_items_veraces_db.py -v -m integration
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

CLIENTE_ID = 9_490_001
EQ_PACK_ID = 9_490_002
_COOKIE = f"session={signer.dumps({'email': 'estudioveraz@test.com', 'role': 'cliente', 'cliente_id': CLIENTE_ID, 'jti': 'estudio-veraz'})}"


@pytest.fixture(autouse=True)
def _sessions_active(monkeypatch):
    """jti obligatorio: la cookie de test no está en la allowlist real →
    stubbeamos is_active (mismo patrón que test_cliente_modificar_pedido_gate_db.py)."""
    monkeypatch.setattr("auth.queries.sessions.is_active", lambda jti: {"jti": jti})


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE cliente_id = %s OR tipo = 'estudio_fijo')",
        (CLIENTE_ID,),
    )
    conn.execute(
        "DELETE FROM alquileres WHERE cliente_id = %s OR tipo = 'estudio_fijo'", (CLIENTE_ID,)
    )
    conn.execute("DELETE FROM estudio_slots_fijos")
    conn.execute("DELETE FROM estudio_pack_equipos WHERE equipo_id = %s", (EQ_PACK_ID,))
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQ_PACK_ID,))
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))


@pytest.fixture
def setup():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, dni_validado_at) "
            "VALUES (%s,'Cliente','Estudio Veraz','estudioveraz@test.com', now())",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada, visible_catalogo) "
            "VALUES (%s,'Equipo pack (items veraces)',3,5000,1)",
            (EQ_PACK_ID,),
        )
        conn.execute(
            "INSERT INTO estudio_pack_equipos (estudio_id, equipo_id, orden) VALUES (1,%s,0)",
            (EQ_PACK_ID,),
        )
        conn.execute(
            "UPDATE estudio SET precio_hora=10000, pack_activo=TRUE, pack_precio=30000, "
            "pack_nombre='Pack Todo Incluido', buffer_horas=0, min_horas=1, "
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
        yield c


def _reservar(client, *, fecha, start, horas, con_pack):
    return client.post(
        "/api/estudio/reservas",
        json={"fecha": fecha, "start": start, "horas": horas, "con_pack": con_pack},
        headers={"Cookie": _COOKIE},
    )


def _items_y_pedido(conn, pedido_id):
    pedido = conn.execute(
        "SELECT monto_total FROM alquileres WHERE id=%s", (pedido_id,)
    ).fetchone()
    items = conn.execute(
        "SELECT equipo_id, precio_jornada, subtotal, nombre_libre, cobro_modo "
        "FROM alquiler_items WHERE pedido_id=%s",
        (pedido_id,),
    ).fetchall()
    return pedido, items


def test_reserva_sin_pack_items_veraces(client_con_db, setup):
    """El centinela lleva el monto REAL del espacio (no $0) — Σ subtotal ==
    monto_total, sin necesitar excepciones en desglose/reconciliación."""
    from database import get_db

    r = _reservar(client_con_db, fecha="2030-03-01", start="14:00", horas=3, con_pack=False)
    assert r.status_code == 201, r.text
    pedido_id = r.json()["id"]

    conn = get_db()
    try:
        pedido, items = _items_y_pedido(conn, pedido_id)
    finally:
        conn.close()

    assert pedido["monto_total"] == 30000  # 10000/h × 3h
    assert len(items) == 1
    assert items[0]["precio_jornada"] == 30000
    assert items[0]["subtotal"] == 30000
    assert items[0]["cobro_modo"] == "fijo"
    assert sum(it["subtotal"] for it in items) == pedido["monto_total"]


def test_reserva_con_pack_items_veraces(client_con_db, setup):
    """Con pack: el centinela lleva el espacio, una línea personalizada nueva
    lleva el precio FIJO del pack (dueño Rambla por default vía
    `equipo_id=NULL`) — el equipo del pack en sí sigue informativo a $0."""
    from database import get_db

    r = _reservar(client_con_db, fecha="2030-03-02", start="10:00", horas=2, con_pack=True)
    assert r.status_code == 201, r.text
    pedido_id = r.json()["id"]

    conn = get_db()
    try:
        pedido, items = _items_y_pedido(conn, pedido_id)
    finally:
        conn.close()

    assert pedido["monto_total"] == 20000 + 30000  # espacio(2h×10000) + pack fijo
    assert len(items) == 3  # centinela + equipo del pack ($0) + línea fija del pack
    linea_pack = next(it for it in items if it["equipo_id"] is None)
    assert linea_pack["subtotal"] == 30000
    assert linea_pack["cobro_modo"] == "fijo"
    assert linea_pack["nombre_libre"] == "Pack Todo Incluido"
    equipo_pack = next(it for it in items if it["equipo_id"] == EQ_PACK_ID)
    assert equipo_pack["subtotal"] == 0  # informativo
    centinela = next(it for it in items if it["equipo_id"] not in (None, EQ_PACK_ID))
    assert centinela["subtotal"] == 20000
    assert centinela["cobro_modo"] == "fijo"
    assert sum(it["subtotal"] for it in items) == pedido["monto_total"]


def test_slot_items_veraces_y_edicion_no_se_autobloquea(client_con_db, setup, monkeypatch):
    """El slot fijo genera pedidos con su ítem centinela a valor_mensual real
    (antes: sin ítem, invisible para la liquidación). Editar el slot
    (revalida disponibilidad ANTES de regenerar sus pedidos) no debe
    chocar contra los ítems centinela de sus propios pedidos ya generados —
    `exclude_slot_id` en `_centinela_libre`."""
    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    from database import get_db
    from routes.estudio import _mes_actual_ar

    mes = _mes_actual_ar()
    y, m = (int(x) for x in mes.split("-"))
    mes_hasta = f"{y:04d}-{(m % 12) + 1:02d}" if m < 12 else f"{y + 1:04d}-01"

    r = client_con_db.post(
        "/api/admin/estudio/slots",
        json={
            "cliente": "Filmar (items veraces)", "dia_semana": 2,
            "hora_desde": 8, "hora_hasta": 12, "valor_mensual": 50000,
            "mes_desde": mes, "mes_hasta": mes_hasta, "activo": True,
        },
    )
    assert r.status_code == 201, r.text
    slot_id = r.json()["id"]

    conn = get_db()
    try:
        pedidos = conn.execute(
            "SELECT id, monto_total FROM alquileres WHERE estudio_slot_id=%s", (slot_id,)
        ).fetchall()
        assert pedidos, "el slot debería haber generado al menos un pedido"
        for p in pedidos:
            items = conn.execute(
                "SELECT precio_jornada, subtotal, cobro_modo FROM alquiler_items WHERE pedido_id=%s",
                (p["id"],),
            ).fetchall()
            assert len(items) == 1, "cada pedido del slot debe llevar su ítem centinela"
            assert items[0]["subtotal"] == 50000 == p["monto_total"]
            assert items[0]["cobro_modo"] == "fijo"
    finally:
        conn.close()

    # Editar el slot (mismo día/rango, cambia la hora) revalida disponibilidad
    # ANTES de regenerar — sin exclude_slot_id, chocaría contra el propio
    # centinela de estos pedidos recién verificados.
    r2 = client_con_db.patch(f"/api/admin/estudio/slots/{slot_id}", json={"hora_desde": 9})
    assert r2.status_code == 200, r2.text

    conn = get_db()
    try:
        pedidos2 = conn.execute(
            "SELECT id, fecha_desde FROM alquileres WHERE estudio_slot_id=%s", (slot_id,)
        ).fetchall()
        assert pedidos2
        for p in pedidos2:
            assert p["fecha_desde"].hour == 9, "la regeneración debería reflejar la nueva hora"
            items = conn.execute(
                "SELECT subtotal FROM alquiler_items WHERE pedido_id=%s", (p["id"],)
            ).fetchall()
            assert len(items) == 1 and items[0]["subtotal"] == 50000
    finally:
        conn.close()
