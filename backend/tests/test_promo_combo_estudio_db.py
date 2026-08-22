"""Promo combo del Estudio (#1283 Fase 5) contra Postgres REAL.

La promo reemplaza al pack curado: un equipo real `tipo='combo'` (dueno=
'Rental', oculto del catálogo), creado desde `POST /admin/estudio/promo/
crear-desde-pack` a partir de `estudio_pack_equipos`, con su precio clavado
vía un descuento % uniforme (`resolver_descuento_uniforme`). Reservar CON
promo agrega una línea del combo a precio fijo (ítems veraces) — BEST-EFFORT
(2026-07-24): si falta stock de algún componente no bloquea la reserva, cobra
el precio fijo completo igual y avisa vía `promo_advertencia` (mismo criterio
que tenía el pack ⏰ retirado). Los sueltos (equipos elegidos aparte, no acá)
siguen siendo stock DURO — ver `test_estudio_admin_reservas_db.py`.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_promo_combo_estudio_db.py -v -m integration
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

CLIENTE_ID = 9_470_001
EQ_A, EQ_B = 9_470_002, 9_470_003
OCUPANTE_ID = 9_470_099
_COOKIE = f"session={signer.dumps({'email': 'promoestudio@test.com', 'role': 'cliente', 'cliente_id': CLIENTE_ID, 'jti': 'promo-estudio'})}"


@pytest.fixture(autouse=True)
def _sessions_active(monkeypatch):
    monkeypatch.setattr("auth.queries.sessions.is_active", lambda jti: {"jti": jti})


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE cliente_id = %s OR id = %s)",
        (CLIENTE_ID, OCUPANTE_ID),
    )
    conn.execute(
        "DELETE FROM alquileres WHERE cliente_id = %s OR id = %s", (CLIENTE_ID, OCUPANTE_ID)
    )
    row = conn.execute("SELECT promo_combo_id FROM estudio WHERE id=1").fetchone()
    if row and row["promo_combo_id"]:
        conn.execute("DELETE FROM kit_componentes WHERE equipo_id = %s", (row["promo_combo_id"],))
        conn.execute("DELETE FROM equipos WHERE id = %s", (row["promo_combo_id"],))
    conn.execute("UPDATE estudio SET promo_combo_id = NULL WHERE id = 1")
    conn.execute("DELETE FROM estudio_pack_equipos WHERE equipo_id IN (%s,%s)", (EQ_A, EQ_B))
    conn.execute("DELETE FROM equipos WHERE id IN (%s,%s)", (EQ_A, EQ_B))
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))


@pytest.fixture
def setup():
    # NO llama a init_db() acá: `client_con_db` (module-scoped) ya lo hace, y
    # duplicarlo corre en paralelo con el `db_init_thread` que dispara el
    # `startup` de `TestClient(main.app)` — mismo `ALTER TABLE ... ADD
    # CONSTRAINT` sin lock, carrera real que rompió CI (DuplicateObject en
    # `spec_propuestas_pendientes_tipo_check`, 2026-07-26).
    from database import get_db

    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, dni_validado_at) "
            "VALUES (%s,'Cliente','Promo Estudio','promoestudio@test.com', now())",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada, visible_catalogo, dueno) "
            "VALUES (%s,'Equipo promo A',2,1000,1,'Pablo')",
            (EQ_A,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada, visible_catalogo, dueno) "
            "VALUES (%s,'Equipo promo B',1,500,1,'Tincho')",
            (EQ_B,),
        )
        conn.execute(
            "INSERT INTO estudio_pack_equipos (estudio_id, equipo_id, orden) VALUES (1,%s,0),(1,%s,1)",
            (EQ_A, EQ_B),
        )
        conn.execute(
            "UPDATE estudio SET precio_hora=10000, pack_activo=TRUE, pack_precio=2000, "
            "pack_nombre='Pack viejo', pack_descripcion='Descripción de la promo', "
            "promo_combo_id=NULL, buffer_horas=0, min_horas=1, "
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


def _crear_promo(client, **body):
    # ADMIN_BYPASS_AUTH=1 (fixture _admin_bypass) hace que require_admin pase
    # sin cookie — no hace falta autenticar como admin acá.
    return client.post("/api/admin/estudio/promo/crear-desde-pack", json=body)


@pytest.fixture(autouse=True)
def _admin_bypass(monkeypatch):
    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")


def test_crear_promo_desde_pack_reemplaza_pack(client_con_db, setup):
    # bruto = 1000×2 (EQ_A cantidad=2 en equipos, pero kit_componentes.cantidad=1
    # cada uno) → bruto real = 1000×1 + 500×1 = 1500. Objetivo 1200 → 20% uniforme.
    r = _crear_promo(client_con_db, precio_objetivo=1200)
    assert r.status_code == 201, r.text
    data = r.json()

    combo_id = data["promo_combo_id"]
    assert combo_id

    from database import get_db
    conn = get_db()
    try:
        # pack_activo se apaga (columna todavía viva, pero el campo ya no viaja
        # en la respuesta — el pack ⏰ se retiró de la API en la Fase 8, #1283).
        estudio_row = conn.execute("SELECT pack_activo FROM estudio WHERE id=1").fetchone()
        assert estudio_row["pack_activo"] is False

        combo = conn.execute(
            "SELECT tipo, dueno, visible_catalogo, cantidad, eliminado_at "
            "FROM equipos WHERE id=%s", (combo_id,),
        ).fetchone()
        assert combo["tipo"] == "combo"
        assert combo["dueno"] == "Rental"
        assert combo["visible_catalogo"] == 0
        assert combo["eliminado_at"] is None

        comps = conn.execute(
            "SELECT componente_id, cantidad, descuento_pct FROM kit_componentes "
            "WHERE equipo_id=%s ORDER BY componente_id", (combo_id,),
        ).fetchall()
        assert {c["componente_id"] for c in comps} == {EQ_A, EQ_B}
        assert all(c["cantidad"] == 1 for c in comps)
        # Mismo % uniforme en ambas líneas.
        pcts = {round(c["descuento_pct"], 4) for c in comps}
        assert len(pcts) == 1

        from services.precios import precio_combo
        assert precio_combo(conn, combo_id) == 1200
    finally:
        conn.close()

    assert data["promo"]["precio"] == 1200
    assert data["promo"]["nombre"]
    assert data["promo"]["descripcion"] == "Descripción de la promo"


def test_crear_promo_ya_existente_da_409(client_con_db, setup):
    assert _crear_promo(client_con_db, precio_objetivo=1200).status_code == 201
    r2 = _crear_promo(client_con_db, precio_objetivo=1200)
    assert r2.status_code == 409


def test_crear_promo_sin_pack_da_400(client_con_db, setup):
    from database import get_db
    conn = get_db()
    try:
        conn.execute("DELETE FROM estudio_pack_equipos WHERE estudio_id=1")
        conn.commit()
    finally:
        conn.close()
    r = _crear_promo(client_con_db, precio_objetivo=1200)
    assert r.status_code == 400


def test_get_estudio_expone_promo(client_con_db, setup):
    assert _crear_promo(client_con_db, precio_objetivo=1200).status_code == 201
    r = client_con_db.get("/api/estudio")
    assert r.status_code == 200
    promo = r.json()["promo"]
    assert promo is not None
    assert promo["precio"] == 1200
    # Listado público "qué incluye" — misma fuente que el catálogo
    # (services.contenido), nunca desincronizado de lo que la promo reserva.
    assert {c["nombre"] for c in promo["componentes"]} == {"Equipo promo A", "Equipo promo B"}
    assert all(c["cantidad"] == 1 for c in promo["componentes"])


def test_disponibilidad_expone_promo_disponible(client_con_db, setup):
    assert _crear_promo(client_con_db, precio_objetivo=1200).status_code == 201
    r = client_con_db.get(
        "/api/estudio/disponibilidad",
        params={"fecha": "2030-04-01", "start": "14:00", "horas": 2},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["libre"] is True
    assert data["promo"]["disponible"] is True


def _reservar(client, *, fecha, start, horas, con_promo):
    return client.post(
        "/api/estudio/reservas",
        json={"fecha": fecha, "start": start, "horas": horas, "con_promo": con_promo},
        headers={"Cookie": _COOKIE},
    )


def test_reserva_con_promo_items_veraces_y_atribucion_rental(client_con_db, setup):
    assert _crear_promo(client_con_db, precio_objetivo=1200).status_code == 201

    r = _reservar(client_con_db, fecha="2030-04-02", start="14:00", horas=3, con_promo=True)
    assert r.status_code == 201, r.text
    pedido_id = r.json()["id"]

    from database import get_db
    conn = get_db()
    try:
        pedido = conn.execute(
            "SELECT monto_total FROM alquileres WHERE id=%s", (pedido_id,)
        ).fetchone()
        items = conn.execute(
            "SELECT ai.equipo_id, ai.subtotal, ai.cobro_modo, e.dueno "
            "FROM alquiler_items ai JOIN equipos e ON e.id = ai.equipo_id "
            "WHERE ai.pedido_id=%s ORDER BY ai.id",
            (pedido_id,),
        ).fetchall()
    finally:
        conn.close()

    # 10000/h × 3h (espacio) + 1200 (promo) = 31200.
    assert pedido["monto_total"] == 31200
    assert sum(it["subtotal"] for it in items) == pedido["monto_total"]
    promo_item = next(it for it in items if it["subtotal"] == 1200)
    assert promo_item["cobro_modo"] == "fijo"
    assert promo_item["dueno"] == "Rental"  # NO los dueños tradicionales de EQ_A/EQ_B


def test_promo_precio_fijo_no_seguido_por_cambio_de_componente(client_con_db, setup):
    """El precio de la promo es FIJO (`pack_precio`), no derivado en vivo de
    sus componentes — si un componente cambia de precio en el catálogo
    DESPUÉS de crear la promo, `_promo_info` y una reserva nueva siguen
    cobrando el objetivo original, no un número corrido."""
    assert _crear_promo(client_con_db, precio_objetivo=1200).status_code == 201

    from database import get_db
    conn = get_db()
    try:
        conn.execute("UPDATE equipos SET precio_jornada = 9000 WHERE id = %s", (EQ_A,))
        conn.commit()
    finally:
        conn.close()

    r = client_con_db.get("/api/estudio")
    assert r.json()["promo"]["precio"] == 1200

    r = _reservar(client_con_db, fecha="2030-04-06", start="14:00", horas=2, con_promo=True)
    assert r.status_code == 201, r.text
    pedido_id = r.json()["id"]

    conn = get_db()
    try:
        pedido = conn.execute(
            "SELECT monto_total FROM alquileres WHERE id=%s", (pedido_id,)
        ).fetchone()
    finally:
        conn.close()
    # 10000/h × 2h (espacio) + 1200 (promo, sigue fija pese al componente
    # que ahora vale 9000×1 = 9000 solo — el derivado hubiera sido >1200).
    assert pedido["monto_total"] == 21200


def test_patch_estudio_actualiza_precio_fijo_de_la_promo(client_con_db, setup):
    """`PATCH /admin/estudio {pack_precio}` es el único lugar para cambiar el
    precio fijo de la promo YA creada — se refleja de inmediato en `_promo_info`."""
    assert _crear_promo(client_con_db, precio_objetivo=1200).status_code == 201

    r = client_con_db.patch("/api/admin/estudio", json={"pack_precio": 1500})
    assert r.status_code == 200, r.text
    assert r.json()["pack_precio"] == 1500

    r = client_con_db.get("/api/estudio")
    assert r.json()["promo"]["precio"] == 1500


def test_reserva_con_promo_sin_stock_es_best_effort_no_bloquea(client_con_db, setup):
    """La promo es BEST-EFFORT (mismo criterio que tenía el pack ⏰ retirado,
    2026-07-24): si un componente no tiene stock, la reserva NO se bloquea —
    se crea igual, cobra el precio fijo completo de la promo (una sola línea,
    ítems veraces) y avisa qué faltó vía `promo_advertencia`."""
    assert _crear_promo(client_con_db, precio_objetivo=1200).status_code == 201

    from database import get_db
    from services.estudio.queries.disponibilidad import _franja_estudio
    from services.estudio.queries.estudio import _get_estudio_row

    conn = get_db()
    try:
        estudio = _get_estudio_row(conn)
        fd, fh = _franja_estudio(estudio, "2030-04-05", "14:00", 2)
        # Agota TODO el stock de EQ_B (cantidad=1) con otro pedido "confirmado"
        # en la MISMA franja — la promo depende de EQ_B, así que su combo deja
        # de tener stock disponible.
        conn.execute(
            """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta, monto_total)
               VALUES (%s,'Ocupante',%s,%s,%s,500)""",
            (OCUPANTE_ID, "confirmado", fd, fh),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal) VALUES (%s,%s,1,500)",
            (OCUPANTE_ID, EQ_B),
        )
        conn.commit()
    finally:
        conn.close()

    r = _reservar(client_con_db, fecha="2030-04-05", start="14:00", horas=2, con_promo=True)
    assert r.status_code == 201, r.text
    data = r.json()
    pedido_id = data["id"]
    assert data["promo_advertencia"] is not None
    assert "Equipo promo B" in data["promo_advertencia"]

    conn = get_db()
    try:
        pedido = conn.execute(
            "SELECT monto_total FROM alquileres WHERE id=%s", (pedido_id,)
        ).fetchone()
        items = conn.execute(
            "SELECT ai.equipo_id, ai.subtotal, ai.cobro_modo "
            "FROM alquiler_items ai WHERE ai.pedido_id=%s ORDER BY ai.id",
            (pedido_id,),
        ).fetchall()
    finally:
        conn.close()

    # 10000/h × 2h (espacio) + 1200 (promo, precio FIJO completo pese al
    # faltante — best-effort no descuenta nada, solo avisa).
    assert pedido["monto_total"] == 21200
    promo_item = next(it for it in items if it["subtotal"] == 1200)
    assert promo_item["cobro_modo"] == "fijo"
