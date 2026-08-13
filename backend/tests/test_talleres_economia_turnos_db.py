"""Economía del taller — turno embebido POR CLASE real, contra Postgres REAL
(candados que el fake conn de `test_talleres.py` no puede dar: `_centinela_libre`
real, `FOR UPDATE`, filas reales en `alquiler_turnos_estudio`/`alquiler_items`).

Pedido explícito del dueño (2026-08-13, tras confirmar el riesgo de tocar el
sistema de turnos-embebidos): en vez de una línea "Estudio (espacio)" plana
para todo el mes, cada clase real de `clases_taller` se ve como su propio
turno del Estudio — reusa "Turnos del Estudio" (#1308) con fecha/hora reales,
sin inventar UI nueva. El monto configurado en Economía se reparte en partes
iguales entre las clases del mes.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_talleres_economia_turnos_db.py -v -m integration
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

TALLER_ID = 9_495_001
SLUG = "test-economia-turnos-zzq"


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_turnos_estudio WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE taller_edicion_id IN "
        "(SELECT id FROM ediciones_taller WHERE taller_id = %s))",
        (TALLER_ID,),
    )
    conn.execute(
        "DELETE FROM alquileres WHERE taller_edicion_id IN "
        "(SELECT id FROM ediciones_taller WHERE taller_id = %s)",
        (TALLER_ID,),
    )
    conn.execute(
        "DELETE FROM clases_taller WHERE edicion_id IN "
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
            (TALLER_ID, SLUG, SLUG, "Taller turnos"),
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


def _insertar_edicion(conn, *, fecha_inicio, fecha_fin, valor_estudio=90_000, valor_estudio_modo="mensual") -> int:
    return conn.execute(
        """
        INSERT INTO ediciones_taller
            (taller_id, numero_edicion, slug, fecha_inicio, fecha_fin, activo,
             usa_estudio, valor_estudio, valor_estudio_modo)
        VALUES (%s, 1, %s, %s, %s, TRUE, TRUE, %s, %s)
        RETURNING id
        """,
        (TALLER_ID, SLUG + "-ed1", fecha_inicio, fecha_fin, valor_estudio, valor_estudio_modo),
    ).fetchone()["id"]


def _insertar_clase(conn, edicion_id, fecha, hora_inicio_min, hora_fin_min, orden=0):
    conn.execute(
        "INSERT INTO clases_taller (edicion_id, fecha, hora_inicio_min, hora_fin_min, titulo, orden) "
        "VALUES (%s,%s,%s,%s,'Clase',%s)",
        (edicion_id, fecha, hora_inicio_min, hora_fin_min, orden),
    )


def _taller_nombre(conn) -> str:
    return conn.execute("SELECT nombre FROM talleres WHERE id = %s", (TALLER_ID,)).fetchone()["nombre"]


def _next_numero_pedido(conn) -> int:
    return conn.execute("SELECT nextval('numero_pedido_seq')").fetchone()[0]


def _pedidos_de(conn, edicion_id):
    return conn.execute(
        "SELECT id, monto_total, fecha_desde FROM alquileres WHERE taller_edicion_id = %s", (edicion_id,)
    ).fetchall()


def _turnos_de(conn, pedido_id):
    return conn.execute(
        "SELECT id, fecha_desde, fecha_hasta FROM alquiler_turnos_estudio WHERE pedido_id = %s ORDER BY fecha_desde",
        (pedido_id,),
    ).fetchall()


def _items_de(conn, pedido_id):
    return conn.execute(
        "SELECT id, equipo_id, subtotal, turno_estudio_id FROM alquiler_items WHERE pedido_id = %s ORDER BY id",
        (pedido_id,),
    ).fetchall()


def test_un_turno_por_clase_real_del_mes(conn):
    """Caso central: 3 clases reales este mes → 3 turnos embebidos, cada uno
    con fecha/hora real (no el mes contable) y su parte del monto total."""
    from services.talleres.commands.economia import _regenerar_pedidos_taller

    y, m = _mes_actual_ar()
    edicion_id = _insertar_edicion(
        conn, fecha_inicio=f"{y:04d}-{m:02d}-01", fecha_fin=f"{y:04d}-{m:02d}-28", valor_estudio=90_000,
    )
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-03", 19 * 60, 21 * 60, orden=0)
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-10", 19 * 60, 21 * 60, orden=1)
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-17", 19 * 60, 21 * 60, orden=2)
    conn.commit()

    edicion = conn.execute("SELECT * FROM ediciones_taller WHERE id = %s", (edicion_id,)).fetchone()
    _regenerar_pedidos_taller(conn, edicion, _taller_nombre(conn), numero_pedido_fn=_next_numero_pedido)
    conn.commit()

    pedidos = _pedidos_de(conn, edicion_id)
    assert len(pedidos) == 1
    pedido = pedidos[0]
    assert pedido["monto_total"] == 90_000, "la suma de los 3 turnos tiene que dar el total configurado"

    turnos = _turnos_de(conn, pedido["id"])
    assert len(turnos) == 3, "un turno POR CLASE, no una línea plana"
    from database import to_datetime

    fechas = [to_datetime(t["fecha_desde"]) for t in turnos]
    assert [f.day for f in fechas] == [3, 10, 17], "fechas reales de las clases, no el mes contable"
    assert all(f.hour == 19 for f in fechas), "hora real de la clase"
    assert all(to_datetime(t["fecha_hasta"]).hour == 21 for t in turnos), "duración real de la clase"

    items = _items_de(conn, pedido["id"])
    assert len(items) == 3
    assert {i["turno_estudio_id"] for i in items} == {t["id"] for t in turnos}, (
        "cada ítem cuelga de SU turno"
    )
    montos = sorted(i["subtotal"] for i in items)
    assert montos == [30_000, 30_000, 30_000], "90.000 / 3 clases, reparto exacto"


def test_remanente_de_redondeo_va_a_la_ultima_clase(conn):
    """100.000 / 3 no da exacto — el resto va a la ÚLTIMA clase (mismo
    criterio que `_partes` para meses)."""
    from services.talleres.commands.economia import _regenerar_pedidos_taller

    y, m = _mes_actual_ar()
    edicion_id = _insertar_edicion(
        conn, fecha_inicio=f"{y:04d}-{m:02d}-01", fecha_fin=f"{y:04d}-{m:02d}-28", valor_estudio=100_000,
    )
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-03", 600, 720, orden=0)
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-10", 600, 720, orden=1)
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-17", 600, 720, orden=2)
    conn.commit()

    edicion = conn.execute("SELECT * FROM ediciones_taller WHERE id = %s", (edicion_id,)).fetchone()
    _regenerar_pedidos_taller(conn, edicion, _taller_nombre(conn), numero_pedido_fn=_next_numero_pedido)
    conn.commit()

    pedido = _pedidos_de(conn, edicion_id)[0]
    from database import to_datetime

    items_por_dia = {
        to_datetime(t["fecha_desde"]).day: i["subtotal"]
        for t, i in zip(_turnos_de(conn, pedido["id"]), _items_de(conn, pedido["id"]))
    }
    assert items_por_dia[3] == 33_333
    assert items_por_dia[10] == 33_333
    assert items_por_dia[17] == 33_334, "el remanente (1 peso) cae en la última clase (día 17)"
    assert sum(items_por_dia.values()) == 100_000


def test_sin_clases_este_mes_cae_al_item_plano_de_siempre(conn):
    """Fallback: `usa_estudio=True` pero el mes actual no tiene clases
    cargadas todavía (el admin no terminó de armar la edición) — no se puede
    repartir entre clases que no existen, así que sigue el comportamiento
    viejo (1 ítem plano) en vez de perder la plata."""
    from services.talleres.commands.economia import _regenerar_pedidos_taller

    y, m = _mes_actual_ar()
    edicion_id = _insertar_edicion(
        conn, fecha_inicio=f"{y:04d}-{m:02d}-01", fecha_fin=f"{y:04d}-{m:02d}-28", valor_estudio=50_000,
    )
    conn.commit()

    edicion = conn.execute("SELECT * FROM ediciones_taller WHERE id = %s", (edicion_id,)).fetchone()
    _regenerar_pedidos_taller(conn, edicion, _taller_nombre(conn), numero_pedido_fn=_next_numero_pedido)
    conn.commit()

    pedido = _pedidos_de(conn, edicion_id)[0]
    assert pedido["monto_total"] == 50_000
    assert _turnos_de(conn, pedido["id"]) == [], "sin clases no hay turnos que crear"
    items = _items_de(conn, pedido["id"])
    assert len(items) == 1
    assert items[0]["turno_estudio_id"] is None
    assert items[0]["subtotal"] == 50_000


def test_regenerar_dos_veces_no_confunde_los_turnos_con_items_extra(conn):
    """Bug que este test existe para prevenir: si `_n_items_auto` quedara mal
    contado (ej. la vieja constante fija en vez de contar clases reales), el
    steady-state (3 turnos, nada manual agregado) se leería como "3 > 1 →
    tiene algo extra" y quedaría conservado PARA SIEMPRE — el barrido de
    limpieza nunca podría recalcular nada. Correr 2 veces seguidas tiene que
    seguir borrando y recreando limpio (0 basura, mismos 3 turnos)."""
    from services.talleres.commands.economia import _regenerar_pedidos_taller

    y, m = _mes_actual_ar()
    edicion_id = _insertar_edicion(
        conn, fecha_inicio=f"{y:04d}-{m:02d}-01", fecha_fin=f"{y:04d}-{m:02d}-28", valor_estudio=90_000,
    )
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-03", 600, 720, orden=0)
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-10", 600, 720, orden=1)
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-17", 600, 720, orden=2)
    conn.commit()
    edicion = conn.execute("SELECT * FROM ediciones_taller WHERE id = %s", (edicion_id,)).fetchone()

    _regenerar_pedidos_taller(conn, edicion, _taller_nombre(conn), numero_pedido_fn=_next_numero_pedido)
    conn.commit()
    _regenerar_pedidos_taller(conn, edicion, _taller_nombre(conn), numero_pedido_fn=_next_numero_pedido)
    conn.commit()

    pedidos = _pedidos_de(conn, edicion_id)
    assert len(pedidos) == 1, "una sola vez recreado, no acumulado"
    turnos = _turnos_de(conn, pedidos[0]["id"])
    assert len(turnos) == 3, "los 3 de siempre, ni más ni menos"


def test_linea_manual_extra_se_conserva_encima_de_los_turnos(conn):
    """La protección de "ítems extra" (línea de matrícula tipeada a mano)
    tiene que seguir funcionando con el conteo nuevo: 3 turnos + 1 línea
    manual = 4 ítems > 3 auto-generados → CONSERVADO (no se borra nada,
    ni la línea manual ni los turnos)."""
    from services.talleres.commands.economia import _regenerar_pedidos_taller

    y, m = _mes_actual_ar()
    edicion_id = _insertar_edicion(
        conn, fecha_inicio=f"{y:04d}-{m:02d}-01", fecha_fin=f"{y:04d}-{m:02d}-28", valor_estudio=90_000,
    )
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-03", 600, 720, orden=0)
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-10", 600, 720, orden=1)
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-17", 600, 720, orden=2)
    conn.commit()
    edicion = conn.execute("SELECT * FROM ediciones_taller WHERE id = %s", (edicion_id,)).fetchone()

    _regenerar_pedidos_taller(conn, edicion, _taller_nombre(conn), numero_pedido_fn=_next_numero_pedido)
    conn.commit()
    pedido_id = _pedidos_de(conn, edicion_id)[0]["id"]

    # El admin tipea a mano una línea de matrícula.
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, nombre_libre, cantidad, "
        "precio_jornada, subtotal, cobro_modo) VALUES (%s,NULL,'Matrícula',1,15000,15000,'fijo')",
        (pedido_id,),
    )
    conn.commit()

    _regenerar_pedidos_taller(conn, edicion, _taller_nombre(conn), numero_pedido_fn=_next_numero_pedido)
    conn.commit()

    pedidos = _pedidos_de(conn, edicion_id)
    assert len(pedidos) == 1
    assert pedidos[0]["id"] == pedido_id, "mismo pedido — conservado, no recreado"
    items = _items_de(conn, pedido_id)
    assert len(items) == 4, "los 3 turnos + la matrícula, todos intactos"


def test_conflicto_real_del_centinela_lanza_409(conn):
    """`_centinela_libre` es un chequeo REAL, no cosmético: una clase que se
    pisa con OTRA reserva real del Estudio (ej. un turno standalone ya
    confirmado a esa hora) hace que la generación falle con 409 en vez de
    doble-reservar el espacio en silencio."""
    from fastapi import HTTPException

    from services.talleres.commands.economia import _regenerar_pedidos_taller

    y, m = _mes_actual_ar()
    dia = 3
    estudio = conn.execute("SELECT equipo_id FROM estudio WHERE id = 1").fetchone()

    # Reserva real preexistente del Estudio, mismo horario que la clase.
    pedido_previo_id = conn.execute(
        "INSERT INTO alquileres (cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total) "
        "VALUES ('Turno preexistente','confirmado','diaria',%s,%s,50000) RETURNING id",
        (f"{y:04d}-{m:02d}-{dia:02d}T10:00:00", f"{y:04d}-{m:02d}-{dia:02d}T12:00:00"),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
        "VALUES (%s,%s,1,50000,50000,'fijo')",
        (pedido_previo_id, estudio["equipo_id"]),
    )

    edicion_id = _insertar_edicion(
        conn, fecha_inicio=f"{y:04d}-{m:02d}-01", fecha_fin=f"{y:04d}-{m:02d}-28", valor_estudio=30_000,
    )
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-{dia:02d}", 10 * 60 + 30, 11 * 60 + 30, orden=0)
    conn.commit()

    edicion = conn.execute("SELECT * FROM ediciones_taller WHERE id = %s", (edicion_id,)).fetchone()
    try:
        with pytest.raises(HTTPException) as exc:
            _regenerar_pedidos_taller(conn, edicion, _taller_nombre(conn), numero_pedido_fn=_next_numero_pedido)
        assert exc.value.status_code == 409
    finally:
        # "Turno preexistente" no cuelga de taller_edicion_id — el _limpiar()
        # genérico del fixture no lo alcanza, hay que sacarlo a mano. Ya está
        # COMMITTED (se insertó antes del commit de la edición/clase), así
        # que un rollback no lo saca solo.
        conn.rollback()
        conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (pedido_previo_id,))
        conn.execute("DELETE FROM alquileres WHERE id = %s", (pedido_previo_id,))
        conn.commit()


def test_turnos_embebidos_visibles_en_el_detalle_del_pedido(conn):
    """El detalle del pedido (`_get_alquiler_detail`, lo que consume el
    front) ve los turnos generados vía `turnos_estudio_embebidos` — misma
    pieza que ya usa un pedido `tipo='diaria'`, sin código nuevo del lado de
    lectura (`_turnos_embebidos` no filtra por tipo)."""
    from routes.alquileres.detalle import _get_alquiler_detail
    from services.talleres.commands.economia import _regenerar_pedidos_taller

    y, m = _mes_actual_ar()
    edicion_id = _insertar_edicion(
        conn, fecha_inicio=f"{y:04d}-{m:02d}-01", fecha_fin=f"{y:04d}-{m:02d}-28", valor_estudio=60_000,
    )
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-03", 600, 720, orden=0)
    _insertar_clase(conn, edicion_id, f"{y:04d}-{m:02d}-10", 600, 720, orden=1)
    conn.commit()
    edicion = conn.execute("SELECT * FROM ediciones_taller WHERE id = %s", (edicion_id,)).fetchone()

    _regenerar_pedidos_taller(conn, edicion, _taller_nombre(conn), numero_pedido_fn=_next_numero_pedido)
    conn.commit()
    pedido_id = _pedidos_de(conn, edicion_id)[0]["id"]

    detalle = _get_alquiler_detail(conn, pedido_id)
    assert len(detalle["turnos_estudio_embebidos"]) == 2
    assert len(detalle["items"]) == 2
    assert all(it["turno_estudio_id"] is not None for it in detalle["items"])
