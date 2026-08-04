"""Integración real (Postgres) de `GET /api/estudio/ocupacion-publica` — la
vista pública y anónima de ocupación que alimenta la grilla semanal del
selector de fechas de `/estudio` (paso "¿Cuándo?").

Ejercita, contra Postgres real, que el endpoint combina los 3 tipos de
bloque (slot fijo, taller publicado, reserva real del centinela) en un
único array, y que la respuesta NUNCA incluye datos no-anónimos (cliente,
nombre de taller, número de pedido) — el filtrado por `activo`/`estado` de
cada tipo ya está cubierto por los tests existentes de
`_slot_bloqueante`/`_taller_bloqueante`/`_ocupacion_estudio_rango` (misma
SQL, reusada verbatim acá); este test cubre lo nuevo: la combinación de los
3 tipos + el contrato de anonimato de principio a fin (HTTP incluido, no
solo la función Python).

OPT-IN y seguro por defecto (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://tincho@localhost/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_estudio_ocupacion_publica_db.py -v -m integration
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

CLIENTE_ID = 9_390_001
TALLER_ID = 9_390_101
TALLER_SLUG = "test-ocupacion-publica-zzq"
_COOKIE = (
    "session="
    + signer.dumps({
        "email": "ocupacionpublica@test.com", "role": "cliente",
        "cliente_id": CLIENTE_ID, "jti": "ocupacion-publica",
    })
)


@pytest.fixture(autouse=True)
def _sessions_active(monkeypatch):
    monkeypatch.setattr("auth.queries.sessions.is_active", lambda jti: {"jti": jti})


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE cliente_id = %s)",
        (CLIENTE_ID,),
    )
    conn.execute("DELETE FROM alquileres WHERE cliente_id = %s", (CLIENTE_ID,))
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))
    conn.execute(
        "DELETE FROM clases_taller WHERE edicion_id IN "
        "(SELECT id FROM ediciones_taller WHERE taller_id = %s)",
        (TALLER_ID,),
    )
    conn.execute(
        "DELETE FROM alquileres WHERE taller_edicion_id IN "
        "(SELECT id FROM ediciones_taller WHERE taller_id = %s)",
        (TALLER_ID,),
    )
    conn.execute("DELETE FROM ediciones_taller WHERE taller_id = %s", (TALLER_ID,))
    conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))
    conn.execute("DELETE FROM estudio_slots_fijos WHERE cliente = 'Test Ocupacion Publica'")


@pytest.fixture
def setup():
    from database import get_db

    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, dni_validado_at) "
            "VALUES (%s,'Cliente','Ocupacion Publica','ocupacionpublica@test.com', now())",
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


def test_combina_slot_taller_y_centinela_sin_datos_no_anonimos(client_con_db, setup):
    """Sembrar un slot fijo + una clase de taller publicada + una reserva
    real del centinela en la misma semana, y verificar que el endpoint
    público los devuelve combinados y sin ningún dato no-anónimo."""
    import routes.talleres as t
    from datetime import date
    from database import get_db

    # Slot fijo — el lunes de esa semana, 08-10.
    lunes = date(2030, 5, 6)
    assert lunes.weekday() == 0, "sanity: 2030-05-06 debe ser lunes"
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO estudio_slots_fijos
                (cliente, dia_semana, hora_desde, hora_hasta, valor_mensual,
                 mes_desde, mes_hasta, activo)
            VALUES ('Test Ocupacion Publica', 0, 8, 10, 50000, '2030-05', '2030-05', TRUE)
            """
        )
        conn.commit()
    finally:
        conn.close()

    # Taller publicado — martes de esa semana, 10:00-12:00.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(t, "require_admin", lambda r: None)
        mp.setattr(t, "send_email", lambda *a, **k: None)
        mp.setattr(t, "get_admin_tos", lambda: ["admin@example.com"])

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
                (TALLER_ID, TALLER_SLUG, TALLER_SLUG, "Taller Ocupacion Publica"),
            )
            conn.commit()
        finally:
            conn.close()

        martes = date(2030, 5, 7)
        body = t.EdicionCreateBody(
            clases=[
                t.ClaseBody(fecha=martes.isoformat(), hora_inicio_min=600, hora_fin_min=720,
                            titulo="Clase única", descripcion="Temario"),
            ],
            numero_edicion=1,
            activo=True,
        )
        d = t.admin_create_edicion(TALLER_ID, body, None)
        assert d["activo"] is True

    # Reserva real del centinela — miércoles de esa semana, 14:00-15:00.
    r = client_con_db.post(
        "/api/estudio/reservas",
        json={"fecha": "2030-05-08", "start": "14:00", "horas": 1},
        headers={"Cookie": _COOKIE},
    )
    assert r.status_code == 201, r.text

    resp = client_con_db.get(
        "/api/estudio/ocupacion-publica",
        params={"desde": "2030-05-06", "hasta": "2030-05-12"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    bloques = data["bloques"]
    assert len(bloques) == 3, bloques

    for b in bloques:
        assert set(b.keys()) == {"fecha_desde", "fecha_hasta"}, (
            f"leak de dato no-anónimo en la respuesta HTTP pública: {b}"
        )

    raw = resp.text
    for termino_prohibido in (
        "Test Ocupacion Publica", "Taller Ocupacion Publica", "cliente", "numero_pedido", "label", "tipo",
    ):
        assert termino_prohibido not in raw, f"'{termino_prohibido}' filtrado en la respuesta pública"

    desdes = sorted(b["fecha_desde"] for b in bloques)
    assert desdes[0].startswith("2030-05-06T08:00")
    assert desdes[1].startswith("2030-05-07T10:00")
    assert desdes[2].startswith("2030-05-08T14:00")
