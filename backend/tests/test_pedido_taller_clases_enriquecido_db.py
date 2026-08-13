"""Fase 1 (#1308): el detalle de un pedido de taller (`GET /alquileres/{id}`)
se enriquece con `clases_taller` — las clases REALES (fecha + franja horaria)
de la edición que lo generó, no solo el rango contable de
`fecha_desde`/`fecha_hasta` (el mes completo). Bug real #445: el pedido
mostraba "sáb 15 → sáb 22 ago · 7 jornadas" cuando el taller real eran 2
clases puntuales — esta es la pieza de datos que le permite al front mostrar
la verdad en vez del rango contable.

Fuente única: `services.talleres.queries.clases.clases_de_edicion` — el MISMO
dato que ve el admin en Talleres → la edición (move-verbatim desde
`routes/talleres.py::_get_clases`, ahora compartido para evitar un ciclo de
import: `routes.talleres` ya importa de `routes.alquileres`, así que el
sentido inverso no puede vivir ahí).

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):

    DATABASE_URL=postgresql://tincho@localhost/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_pedido_taller_clases_enriquecido_db.py -v -m integration
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

TALLER_ID = 9_452_001
EDICION_ID = 9_452_101
PEDIDO_TALLER_ID = 9_452_201
PEDIDO_RENTAL_ID = 9_452_202
SLUG = "test-clases-enriquecido-f1308"


def _limpiar(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id IN (%s,%s)", (PEDIDO_TALLER_ID, PEDIDO_RENTAL_ID))
    conn.execute("DELETE FROM alquileres WHERE id IN (%s,%s)", (PEDIDO_TALLER_ID, PEDIDO_RENTAL_ID))
    conn.execute("DELETE FROM clases_taller WHERE edicion_id = %s", (EDICION_ID,))
    conn.execute("DELETE FROM ediciones_taller WHERE id = %s", (EDICION_ID,))
    conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))


@pytest.fixture
def db_setup():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO talleres (id, slug, nombre) VALUES (%s,%s,'Taller test clases')",
            (TALLER_ID, SLUG),
        )
        conn.execute(
            "INSERT INTO ediciones_taller (id, taller_id, numero_edicion, slug, fecha_inicio, fecha_fin) "
            "VALUES (%s,%s,1,%s,'2026-08-01','2026-08-31')",
            (EDICION_ID, TALLER_ID, SLUG + "-ed1"),
        )
        # 2 clases reales (2 sábados, franja horaria) — el caso exacto del
        # pedido #445: "el taller real son 2 clases (2 sábados, franja horaria)".
        conn.execute(
            "INSERT INTO clases_taller (edicion_id, fecha, hora_inicio_min, hora_fin_min, titulo, orden) "
            "VALUES (%s,'2026-08-15',600,840,'Clase 1: introducción',0)",
            (EDICION_ID,),
        )
        conn.execute(
            "INSERT INTO clases_taller (edicion_id, fecha, hora_inicio_min, hora_fin_min, titulo, orden) "
            "VALUES (%s,'2026-08-22',600,840,'Clase 2: práctica',1)",
            (EDICION_ID,),
        )
        # Pedido de taller (mes contable completo, tal como lo arma
        # _regenerar_pedidos_taller) apuntando a esta edición.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, "
            "monto_total, taller_edicion_id) "
            "VALUES (%s,'Taller test clases','confirmado','taller','2026-08-01T00:00:00',"
            "'2026-08-31T23:59:59',50000,%s)",
            (PEDIDO_TALLER_ID, EDICION_ID),
        )
        # Pedido de rental normal, de control — NO debería llevar clases_taller.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,'Cliente control','confirmado','diaria','2026-08-05T10:00:00',"
            "'2026-08-06T10:00:00',5000)",
            (PEDIDO_RENTAL_ID,),
        )
        conn.commit()
        yield
    finally:
        _limpiar(conn)
        conn.commit()
        conn.close()


def test_detalle_pedido_taller_trae_las_clases_reales_de_la_edicion(db_setup):
    from database import get_db
    from routes.alquileres.detalle import _get_alquiler_detail

    conn = get_db()
    try:
        pedido = _get_alquiler_detail(conn, PEDIDO_TALLER_ID)
    finally:
        conn.close()

    assert len(pedido["clases_taller"]) == 2
    fechas = [c["fecha"] for c in pedido["clases_taller"]]
    assert fechas == ["2026-08-15", "2026-08-22"], (
        "las 2 clases reales tienen que venir en orden, no el rango contable del pedido"
    )
    assert pedido["clases_taller"][0]["hora_inicio_str"] == "10:00"
    assert pedido["clases_taller"][0]["hora_fin_str"] == "14:00"
    assert pedido["clases_taller"][0]["titulo"] == "Clase 1: introducción"


def test_detalle_pedido_rental_normal_no_trae_clases(db_setup):
    from database import get_db
    from routes.alquileres.detalle import _get_alquiler_detail

    conn = get_db()
    try:
        pedido = _get_alquiler_detail(conn, PEDIDO_RENTAL_ID)
    finally:
        conn.close()

    assert pedido["clases_taller"] == []


EDICION_MULTIMES_ID = 9_452_102
PEDIDO_SEP_ID = 9_452_203
PEDIDO_DIC_ID = 9_452_204


def _limpiar_multimes(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id IN (%s,%s)", (PEDIDO_SEP_ID, PEDIDO_DIC_ID))
    conn.execute("DELETE FROM alquileres WHERE id IN (%s,%s)", (PEDIDO_SEP_ID, PEDIDO_DIC_ID))
    conn.execute("DELETE FROM clases_taller WHERE edicion_id = %s", (EDICION_MULTIMES_ID,))
    conn.execute("DELETE FROM ediciones_taller WHERE id = %s", (EDICION_MULTIMES_ID,))


@pytest.fixture
def db_setup_multimes(db_setup):
    """Reusa la limpieza/taller de `db_setup` (mismo TALLER_ID) y agrega una
    SEGUNDA edición que abarca varios meses — el escenario real reportado por
    el dueño: 16 clases semanales de sep a dic, con un pedido de sep y otro de
    dic apuntando a la MISMA edición (2026-08-13, un pedido por mes)."""
    from database import get_db

    conn = get_db()
    try:
        _limpiar_multimes(conn)
        conn.execute(
            "INSERT INTO ediciones_taller (id, taller_id, numero_edicion, slug, fecha_inicio, fecha_fin) "
            "VALUES (%s,%s,2,%s,'2026-09-01','2026-12-31')",
            (EDICION_MULTIMES_ID, TALLER_ID, SLUG + "-ed2"),
        )
        # 2 clases en septiembre, 2 en diciembre — mismo patrón semanal real.
        for i, fecha in enumerate(["2026-09-03", "2026-09-10"]):
            conn.execute(
                "INSERT INTO clases_taller (edicion_id, fecha, hora_inicio_min, hora_fin_min, titulo, orden) "
                "VALUES (%s,%s,1140,1260,%s,%s)",
                (EDICION_MULTIMES_ID, fecha, f"Clase sep {i + 1}", i),
            )
        for i, fecha in enumerate(["2026-12-03", "2026-12-10"]):
            conn.execute(
                "INSERT INTO clases_taller (edicion_id, fecha, hora_inicio_min, hora_fin_min, titulo, orden) "
                "VALUES (%s,%s,1140,1260,%s,%s)",
                (EDICION_MULTIMES_ID, fecha, f"Clase dic {i + 1}", i + 10),
            )
        # 2 pedidos mensuales apuntando a la MISMA edición (_regenerar_pedidos_taller
        # nunca los crea juntos, pero un mes ya generado + el mes actual conviven).
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, "
            "monto_total, taller_edicion_id) "
            "VALUES (%s,'Taller test multimes','confirmado','taller','2026-09-01T00:00:00',"
            "'2026-09-30T23:59:59',30000,%s)",
            (PEDIDO_SEP_ID, EDICION_MULTIMES_ID),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, "
            "monto_total, taller_edicion_id) "
            "VALUES (%s,'Taller test multimes','confirmado','taller','2026-12-01T00:00:00',"
            "'2026-12-31T23:59:59',30000,%s)",
            (PEDIDO_DIC_ID, EDICION_MULTIMES_ID),
        )
        conn.commit()
        yield
    finally:
        _limpiar_multimes(conn)
        conn.commit()
        conn.close()


def test_pedido_de_un_mes_no_trae_las_clases_de_otros_meses_de_la_misma_edicion(db_setup_multimes):
    """Caso real reportado por el dueño: una edición de varios meses (2026-08-13,
    un pedido por mes) tiene VARIOS pedidos apuntando a la misma edición_id — el
    pedido de diciembre mostraba las 16 clases de TODA la edición (sep a dic) en
    vez de solo las 2-3 de diciembre. Cada pedido tiene que traer solo SUS
    propias clases, filtradas por su `fecha_desde`/`fecha_hasta`."""
    from database import get_db
    from routes.alquileres.detalle import _get_alquiler_detail

    conn = get_db()
    try:
        pedido_sep = _get_alquiler_detail(conn, PEDIDO_SEP_ID)
        pedido_dic = _get_alquiler_detail(conn, PEDIDO_DIC_ID)
    finally:
        conn.close()

    assert [c["fecha"] for c in pedido_sep["clases_taller"]] == ["2026-09-03", "2026-09-10"], (
        "el pedido de septiembre no debe traer las clases de diciembre"
    )
    assert [c["fecha"] for c in pedido_dic["clases_taller"]] == ["2026-12-03", "2026-12-10"], (
        "el pedido de diciembre no debe traer las clases de septiembre"
    )


def test_progreso_taller_none_si_edicion_de_un_solo_mes(db_setup):
    """Una edición de 1 solo mes (el caso viejo, #445) no aporta información
    de "N/M" — un único pedido cubre toda la edición, mostrarlo sería ruido."""
    from database import get_db
    from routes.alquileres.detalle import _get_alquiler_detail

    conn = get_db()
    try:
        pedido = _get_alquiler_detail(conn, PEDIDO_TALLER_ID)
    finally:
        conn.close()

    assert pedido["progreso_taller"] is None


def test_progreso_taller_indice_y_total_en_edicion_multimes(db_setup_multimes):
    """Pedido a la vista del dueño (2026-08-13): con un solo pedido visible a
    la vez, "Mes 1/4"/"Mes 4/4" da la foto de conjunto que antes daba ver los
    4 pedidos juntos en la lista."""
    from database import get_db
    from routes.alquileres.detalle import _get_alquiler_detail

    conn = get_db()
    try:
        pedido_sep = _get_alquiler_detail(conn, PEDIDO_SEP_ID)
        pedido_dic = _get_alquiler_detail(conn, PEDIDO_DIC_ID)
    finally:
        conn.close()

    assert pedido_sep["progreso_taller"] == {"indice": 1, "total": 4}
    assert pedido_dic["progreso_taller"] == {"indice": 4, "total": 4}
