"""#1308 rediseño "turno como ítem" — hallazgo de auditoría: varias superficies
de analítica de equipos/clientes eran ciegas a `turno_estudio_id`, con dos
distorsiones distintas:

1. **Revenue inflado por el día del PEDIDO contenedor.** Varias queries
   recalculan `precio_jornada * cantidad * (fecha_hasta - fecha_desde)` del
   PEDIDO en vez de leer el `subtotal` ya resuelto — para una línea
   `cobro_modo='fijo'` (el centinela/sueltos/pintura de un turno embebido, que
   cobran una vez, sin importar cuántos días dure el pedido que los contiene)
   esto multiplica por los días del contenedor un monto que NUNCA debía
   multiplicarse. Afecta: `services/ranking_service.py` (popularidad de
   equipo/categoría/marca), `routes/equipos/dashboard.py` (`top_alquilados`/
   `totales`/`por_categoria`), `routes/equipos/core.py::get_equipo_historial`.
2. **El centinela ("Estudio (espacio)") contado como equipo real.**
   `routes/equipos/dashboard.py::por_categoria` no filtraba
   `es_recurso_interno`; `routes/equipos/core.py::equipos_kpis::en_uso_hoy`
   tampoco; `routes/calendar.py::_items_por_pedido` (feed iCal) listaba el
   centinela/sueltos como si fueran equipo que sale con el cliente;
   `clientes/queries/historial.py::resumen` los incluía en el string
   "equipos" de la ficha del cliente, y además su conteo de `turnos_estudio`
   solo miraba turnos VINCULADOS (mecanismo viejo), mostrando 0 para un
   pedido cuyo turno es embebido.

Un solo pedido MIXTO (equipo normal de 5 jornadas + turno embebido de 2hs con
centinela + 1 suelto) alcanza para ejercitar los 6 consumidores.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_equipos_analytics_turno_embebido_db.py -v -m integration
"""
import os
from datetime import timedelta
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

# Ids altos dedicados (bloque 9_512_xxx, sin uso en otros *_db.py).
CLIENTE_ID = 9_512_001
EQ_NORMAL_ID = 9_512_010     # alquilado directo, 5 jornadas — control, NO debe cambiar
EQ_SUELTO_ID = 9_512_011    # SOLO usado como suelto de un turno embebido
CATEGORIA_ID = 9_512_020
PEDIDO_MIXTO_ID = 9_512_030

TURNO_DESDE = "2032-01-02 10:00"
TURNO_HASTA = "2032-01-02 12:00"  # 2 horas

MONTO_NORMAL = 5 * 1000       # EQ_NORMAL: 1000/día × 5 jornadas
MONTO_CENTINELA = 15_000       # centinela: cobro_modo='fijo', monto único
MONTO_SUELTO = 2_000           # EQ_SUELTO: cobro_modo='fijo', monto único (NO × 5)


def _limpiar(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (PEDIDO_MIXTO_ID,))
    conn.execute("DELETE FROM alquiler_turnos_estudio WHERE pedido_id = %s", (PEDIDO_MIXTO_ID,))
    conn.execute("DELETE FROM alquileres WHERE id = %s", (PEDIDO_MIXTO_ID,))
    conn.execute("DELETE FROM equipo_categorias WHERE categoria_id = %s", (CATEGORIA_ID,))
    conn.execute("DELETE FROM categorias WHERE id = %s", (CATEGORIA_ID,))
    conn.execute("DELETE FROM equipos WHERE id IN (%s,%s)", (EQ_NORMAL_ID, EQ_SUELTO_ID))
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
        centinela_id = conn.execute("SELECT equipo_id FROM estudio WHERE id=1").fetchone()["equipo_id"]

        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'Analytics','Turno','analytics-turno-embebido@test.com','+5491100000096')",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada, visible_catalogo, dueno) "
            "VALUES (%s,'Equipo normal test analytics',5,1000,1,'Rental')",
            (EQ_NORMAL_ID,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada, visible_catalogo, dueno) "
            "VALUES (%s,'Suelto test analytics',5,2000,1,'Rental')",
            (EQ_SUELTO_ID,),
        )
        # Categoría de prueba, con AMBOS equipos reales (no el centinela) — así
        # `por_categoria` tiene algo real que sumar para comparar contra.
        conn.execute(
            "INSERT INTO categorias (id, nombre, prioridad) VALUES (%s,'Categoría test analytics',999)",
            (CATEGORIA_ID,),
        )
        conn.execute(
            "INSERT INTO equipo_categorias (equipo_id, categoria_id, orden) VALUES (%s,%s,0), (%s,%s,0)",
            (EQ_NORMAL_ID, CATEGORIA_ID, EQ_SUELTO_ID, CATEGORIA_ID),
        )

        # Pedido mixto: equipo normal (5 jornadas) + turno embebido (2hs, centinela + 1 suelto).
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_email, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'Analytics Turno','analytics-turno-embebido@test.com','confirmado','diaria',"
            "'2032-01-01','2032-01-06',%s)",
            (PEDIDO_MIXTO_ID, CLIENTE_ID, MONTO_NORMAL + MONTO_CENTINELA + MONTO_SUELTO),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
            "VALUES (%s,%s,1,1000,%s,'jornada')",
            (PEDIDO_MIXTO_ID, EQ_NORMAL_ID, MONTO_NORMAL),
        )
        turno_id = conn.execute(
            "INSERT INTO alquiler_turnos_estudio (pedido_id, fecha_desde, fecha_hasta) "
            "VALUES (%s,%s,%s) RETURNING id",
            (PEDIDO_MIXTO_ID, TURNO_DESDE, TURNO_HASTA),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, "
            "cobro_modo, turno_estudio_id) VALUES (%s,%s,1,%s,%s,'fijo',%s)",
            (PEDIDO_MIXTO_ID, centinela_id, MONTO_CENTINELA, MONTO_CENTINELA, turno_id),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, "
            "cobro_modo, turno_estudio_id) VALUES (%s,%s,1,%s,%s,'fijo',%s)",
            (PEDIDO_MIXTO_ID, EQ_SUELTO_ID, MONTO_SUELTO, MONTO_SUELTO, turno_id),
        )
        conn.commit()
        yield {"centinela_id": centinela_id, "turno_id": turno_id}
    finally:
        _limpiar(conn)
        conn.commit()
        conn.close()


# ── 1. ranking_service: no infla el ingreso de un suelto de turno embebido ──

def test_ranking_no_infla_ingreso_de_suelto_de_turno_embebido(setup):
    from database import get_db
    from services.ranking_service import calcular_estadisticas_equipo

    conn = get_db()
    try:
        stats_suelto = calcular_estadisticas_equipo(conn, EQ_SUELTO_ID, ventana_dias=36500)
        stats_normal = calcular_estadisticas_equipo(conn, EQ_NORMAL_ID, ventana_dias=36500)
    finally:
        conn.close()

    assert stats_suelto["ingreso_total_ars"] == MONTO_SUELTO, (
        "el suelto de un turno embebido (cobro_modo='fijo') no debe multiplicarse "
        "por los 5 días del pedido contenedor"
    )
    assert stats_normal["ingreso_total_ars"] == MONTO_NORMAL, (
        "control: un ítem jornada normal sigue multiplicándose por sus días, sin cambios"
    )


# ── 2. historial del cliente: excluye el turno del string de equipos, cuenta el embebido ──

def test_historial_cliente_excluye_turno_del_string_y_cuenta_embebido(setup):
    from clientes.queries.historial import resumen
    from database import get_db

    conn = get_db()
    try:
        filas = resumen(conn, CLIENTE_ID)
    finally:
        conn.close()

    por_id = {f["id"]: f for f in filas}
    fila = por_id[PEDIDO_MIXTO_ID]
    assert "Equipo normal test analytics" in fila["equipos"]
    assert "Estudio (espacio)" not in fila["equipos"]
    assert "Suelto test analytics" not in fila["equipos"]
    assert fila["turnos_estudio"] == 1, (
        "antes solo contaba turnos VINCULADOS (pedido_principal_id) — un turno "
        "EMBEBIDO mostraba 0 pese a existir"
    )
    # El monto NO se duplica: ya viene incluido en monto_total del pedido.
    assert fila["monto_total"] == MONTO_NORMAL + MONTO_CENTINELA + MONTO_SUELTO


# ── 3. dashboard de uso: top_alquilados/totales/por_categoria no inflan ni cuentan el centinela ──

def test_dashboard_uso_no_infla_revenue_ni_cuenta_centinela(client_con_db, setup):
    r = client_con_db.get("/api/admin/dashboard/uso")
    assert r.status_code == 200, r.text
    data = r.json()

    top_por_id = {row["id"]: row for row in data["top_alquilados"]}
    assert top_por_id[EQ_SUELTO_ID]["revenue_total"] == MONTO_SUELTO
    assert top_por_id[EQ_NORMAL_ID]["revenue_total"] == MONTO_NORMAL
    assert setup["centinela_id"] not in top_por_id, "el centinela nunca es un equipo alquilable"

    cat = next(c for c in data["por_categoria"] if c["id"] == CATEGORIA_ID)
    assert cat["revenue_total"] == MONTO_NORMAL + MONTO_SUELTO, (
        "por_categoria no filtraba es_recurso_interno NI era turno-aware — cualquiera "
        "de los dos gaps podía inflar/contaminar la categoría"
    )


# ── 4. equipos/kpis: en_uso_hoy no cuenta el centinela como unidad física ──

def test_kpis_en_uso_hoy_excluye_centinela(client_con_db, setup):
    """No podemos aislar el total exacto (comparte DB con otros equipos reales),
    pero sí confirmar que la unidad del centinela específicamente no cuenta:
    medir, borrar SOLO el ítem del centinela, volver a medir — no debe cambiar."""
    from database import get_db

    conn = get_db()
    pedido_hoy_id = PEDIDO_MIXTO_ID + 1
    try:
        hoy = conn.execute("SELECT CURRENT_DATE AS hoy").fetchone()["hoy"]
        conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (pedido_hoy_id,))
        conn.execute("DELETE FROM alquileres WHERE id = %s", (pedido_hoy_id,))
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
            "fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,%s,'Analytics Turno retirado','retirado','estudio',%s,%s,15000)",
            (pedido_hoy_id, CLIENTE_ID, hoy - timedelta(days=1), hoy + timedelta(days=1)),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
            "VALUES (%s,%s,1,15000,15000,'fijo')",
            (pedido_hoy_id, setup["centinela_id"]),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
            "VALUES (%s,%s,1,1000,5000,'jornada')",
            (pedido_hoy_id, EQ_NORMAL_ID),
        )
        conn.commit()

        r = client_con_db.get("/api/equipos/kpis")
        assert r.status_code == 200, r.text
        antes = r.json()["en_uso_hoy"]

        conn.execute(
            "DELETE FROM alquiler_items WHERE pedido_id = %s AND equipo_id = %s",
            (pedido_hoy_id, setup["centinela_id"]),
        )
        conn.commit()

        r2 = client_con_db.get("/api/equipos/kpis")
        assert r2.json()["en_uso_hoy"] == antes, (
            "en_uso_hoy no debe cambiar al sacar el centinela — nunca debió contarlo"
        )
    finally:
        conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (pedido_hoy_id,))
        conn.execute("DELETE FROM alquileres WHERE id = %s", (pedido_hoy_id,))
        conn.commit()
        conn.close()


# ── 5. historial del EQUIPO: no infla revenue del suelto embebido ──

def test_equipo_historial_no_infla_revenue_de_suelto_embebido(client_con_db, setup):
    r = client_con_db.get(f"/api/equipos/{EQ_SUELTO_ID}/historial")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["stats"]["total_revenue"] == MONTO_SUELTO
    assert data["historial"][0]["dias"] == 1


# ── 6. feed iCal: los ítems del pedido excluyen el turno embebido ──

def test_calendar_items_por_pedido_excluye_turno_embebido(setup):
    from database import get_db
    from routes.calendar import _items_por_pedido

    conn = get_db()
    try:
        items = _items_por_pedido(conn, [PEDIDO_MIXTO_ID])
    finally:
        conn.close()

    nombres = {it["nombre"] for it in items.get(PEDIDO_MIXTO_ID, [])}
    assert nombres == {"Equipo normal test analytics"}
