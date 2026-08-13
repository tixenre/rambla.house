"""Job diario `jobs/regenerar_pedidos_talleres.py`: genera el pedido del mes
actual de un taller recién cuando hace falta — y el guard anti-churn central
(una edición que YA tiene el pedido del mes no se vuelve a tocar, así el
`id`/`numero_pedido` no cambia solo porque el job corrió de nuevo el mismo
día). Pedido explícito del dueño (2026-08-13).

Las ediciones se insertan DIRECTO por SQL (no vía `admin_create_edicion`): el
alta real dispara `_regenerar_pedidos_taller` reactivamente (crea el pedido
del mes actual al toque, como siempre hizo) — insertar directo es la única
forma de dejar una edición activa SIN su pedido del mes, el punto de partida
que este job existe para resolver (mismo patrón que
`test_talleres_pedidos_generados_db.py`).

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_regenerar_pedidos_talleres_job_db.py -v -m integration
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

TALLER_ID = 9_830_004
SLUG = "test-regen-job-zzq"


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquileres WHERE taller_edicion_id IN "
        "(SELECT id FROM ediciones_taller WHERE taller_id = %s)",
        (TALLER_ID,),
    )
    conn.execute("DELETE FROM ediciones_taller WHERE taller_id = %s", (TALLER_ID,))
    conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))


@pytest.fixture
def conn():
    from database import get_db, init_db

    init_db()
    c = get_db()
    try:
        _limpiar(c)
        c.execute(
            "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
            (TALLER_ID, SLUG, SLUG, "Taller job de regeneración"),
        )
        c.commit()
        yield c
    finally:
        _limpiar(c)
        c.commit()
        c.close()


def _mes_actual_ar() -> tuple[int, int]:
    from services.fechas import mes_actual_ar

    y, m = mes_actual_ar().split("-")
    return int(y), int(m)


def _insertar_edicion(
    conn, numero_edicion, *, fecha_inicio, fecha_fin, activo=True,
    usa_equipos=True, valor_equipos=30_000, valor_equipos_modo="mensual",
) -> int:
    """Insert directo (no reactivo) — ver docstring del módulo."""
    slug = f"{SLUG}-{numero_edicion}"
    return conn.execute(
        """
        INSERT INTO ediciones_taller
            (taller_id, numero_edicion, slug, fecha_inicio, fecha_fin, activo,
             usa_equipos, valor_equipos, valor_equipos_modo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (TALLER_ID, numero_edicion, slug, fecha_inicio, fecha_fin, activo,
         usa_equipos, valor_equipos, valor_equipos_modo),
    ).fetchone()["id"]


def _pedidos_de(conn, edicion_id):
    return conn.execute(
        "SELECT id, monto_total, numero_pedido, fecha_desde FROM alquileres WHERE taller_edicion_id = %s",
        (edicion_id,),
    ).fetchall()


def test_genera_el_pedido_del_mes_para_edicion_sin_pedido_aun(conn):
    from jobs.regenerar_pedidos_talleres import regenerar_pedidos_talleres_del_mes

    y, m = _mes_actual_ar()
    edicion_id = _insertar_edicion(conn, 1, fecha_inicio=f"{y:04d}-{m:02d}-01", fecha_fin=f"{y:04d}-{m:02d}-28")
    conn.commit()
    assert _pedidos_de(conn, edicion_id) == []

    generadas = regenerar_pedidos_talleres_del_mes()
    assert generadas == 1

    pedidos = _pedidos_de(conn, edicion_id)
    assert len(pedidos) == 1
    assert pedidos[0]["monto_total"] == 30_000


def test_no_toca_edicion_que_ya_tiene_el_pedido_del_mes(conn):
    """El guard anti-churn central: si ya existe un pedido con `fecha_desde`
    dentro del mes actual para esa edición, el job no llama al motor —
    mismo id/numero_pedido, cero churn."""
    from jobs.regenerar_pedidos_talleres import regenerar_pedidos_talleres_del_mes

    y, m = _mes_actual_ar()
    edicion_id = _insertar_edicion(conn, 1, fecha_inicio=f"{y:04d}-{m:02d}-01", fecha_fin=f"{y:04d}-{m:02d}-28")
    pedido_id = conn.execute(
        """
        INSERT INTO alquileres
            (cliente_nombre, fecha_desde, fecha_hasta, monto_total, estado, fuente, tipo,
             numero_pedido, taller_edicion_id)
        VALUES ('Taller test — ya generado', %s, %s, 30000, 'confirmado', 'taller', 'taller', 999001, %s)
        RETURNING id
        """,
        (f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-28", edicion_id),
    ).fetchone()["id"]
    conn.commit()

    generadas = regenerar_pedidos_talleres_del_mes()
    assert generadas == 0, "ya tiene el pedido del mes -> el job no debe generar (ni tocar) nada"

    pedidos = _pedidos_de(conn, edicion_id)
    assert len(pedidos) == 1
    assert pedidos[0]["id"] == pedido_id, "mismo id — cero churn"
    assert pedidos[0]["numero_pedido"] == 999001, "mismo numero_pedido — cero churn"


def test_limpia_pedidos_futuros_aunque_ya_tenga_el_del_mes_actual(conn):
    """Caso real que motivó este test: una edición con pedidos futuros
    dejados de ANTES de este cambio (o de cualquier causa rara) — aunque YA
    tenga el pedido del mes actual, el job tiene que engancharla igual para
    que el motor limpie los futuros que sobran (si no, quedan ahí para
    siempre: el guard anti-churn los tapaba)."""
    from jobs.regenerar_pedidos_talleres import regenerar_pedidos_talleres_del_mes

    y, m = _mes_actual_ar()
    # Rango de 4 meses (actual + 3 futuros) para poder dejar pedidos "de más"
    # en meses que el motor ya no debería generar de antemano.
    fin_rango_y, fin_rango_m = y, m + 3
    if fin_rango_m > 12:
        fin_rango_y += 1
        fin_rango_m -= 12
    edicion_id = _insertar_edicion(
        conn, 1,
        fecha_inicio=f"{y:04d}-{m:02d}-01",
        fecha_fin=f"{fin_rango_y:04d}-{fin_rango_m:02d}-28",
    )
    # El mes actual YA tiene su pedido (dispararía el guard anti-churn solo).
    conn.execute(
        """
        INSERT INTO alquileres
            (cliente_nombre, fecha_desde, fecha_hasta, monto_total, estado, fuente, tipo,
             numero_pedido, taller_edicion_id)
        VALUES ('Taller test — mes actual', %s, %s, 30000, 'confirmado', 'taller', 'taller', 999002, %s)
        """,
        (f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-28", edicion_id),
    )
    # 2 meses futuros con pedido "de más" (el escenario real que se vio en
    # producción: quedaron de antes de este cambio).
    mes_futuro_y, mes_futuro_m = y, m + 1
    if mes_futuro_m > 12:
        mes_futuro_y += 1
        mes_futuro_m -= 12
    conn.execute(
        """
        INSERT INTO alquileres
            (cliente_nombre, fecha_desde, fecha_hasta, monto_total, estado, fuente, tipo,
             numero_pedido, taller_edicion_id)
        VALUES ('Taller test — mes futuro de más', %s, %s, 30000, 'confirmado', 'taller', 'taller', 999003, %s)
        """,
        (f"{mes_futuro_y:04d}-{mes_futuro_m:02d}-01", f"{mes_futuro_y:04d}-{mes_futuro_m:02d}-28", edicion_id),
    )
    conn.commit()
    assert len(_pedidos_de(conn, edicion_id)) == 2, "sanity: arrancamos con el actual + 1 futuro de más"

    generadas = regenerar_pedidos_talleres_del_mes()
    assert generadas == 1, "la edición SÍ se engancha (tiene un futuro que limpiar), aunque ya tenga el actual"

    pedidos = _pedidos_de(conn, edicion_id)
    assert len(pedidos) == 1, "el futuro de más desapareció; el mes actual sigue existiendo (recreado)"
    from database import to_datetime
    fd = to_datetime(pedidos[0]["fecha_desde"])
    assert (fd.year, fd.month) == (y, m), "el sobreviviente es el mes ACTUAL, no el futuro que se limpió"


def test_no_genera_para_edicion_inactiva(conn):
    from jobs.regenerar_pedidos_talleres import regenerar_pedidos_talleres_del_mes

    y, m = _mes_actual_ar()
    edicion_id = _insertar_edicion(
        conn, 1, fecha_inicio=f"{y:04d}-{m:02d}-01", fecha_fin=f"{y:04d}-{m:02d}-28", activo=False,
    )
    conn.commit()

    generadas = regenerar_pedidos_talleres_del_mes()
    assert generadas == 0
    assert _pedidos_de(conn, edicion_id) == []


def test_no_genera_para_edicion_fuera_del_mes_actual(conn):
    """Una edición que ya terminó (o que arranca en el futuro lejano) no
    genera nada — el pre-filtro del job la descarta antes de tocar el motor."""
    from jobs.regenerar_pedidos_talleres import regenerar_pedidos_talleres_del_mes

    edicion_id = _insertar_edicion(conn, 1, fecha_inicio="2099-03-01", fecha_fin="2099-03-31")
    conn.commit()

    generadas = regenerar_pedidos_talleres_del_mes()
    assert generadas == 0
    assert _pedidos_de(conn, edicion_id) == []


def test_dos_ediciones_activas_generan_cada_una_su_pedido(conn):
    from jobs.regenerar_pedidos_talleres import regenerar_pedidos_talleres_del_mes

    y, m = _mes_actual_ar()
    ed1 = _insertar_edicion(conn, 1, fecha_inicio=f"{y:04d}-{m:02d}-01", fecha_fin=f"{y:04d}-{m:02d}-28")
    ed2 = _insertar_edicion(
        conn, 2, fecha_inicio=f"{y:04d}-{m:02d}-01", fecha_fin=f"{y:04d}-{m:02d}-28", valor_equipos=15_000,
    )
    conn.commit()

    generadas = regenerar_pedidos_talleres_del_mes()
    assert generadas == 2
    assert len(_pedidos_de(conn, ed1)) == 1
    assert len(_pedidos_de(conn, ed2)) == 1
