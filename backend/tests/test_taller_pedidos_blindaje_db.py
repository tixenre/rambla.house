"""Fase 1 (#1308) — mismo espíritu que `test_estudio_pedidos_blindaje_db.py`
pero para `tipo='taller'`: el editor genérico de pedidos NO debe poder pisar
la plata/fechas de un pedido de taller, PERO (a diferencia de estudio) SÍ debe
poder agregar una línea de matrícula a mano — solo se protege el ítem auto
(centinela del Estudio y/o "Uso de equipos", los que genera
`_regenerar_pedidos_taller`).

Bug latente encontrado en esta pasada (no reportado, pero real): antes del
guard, `_recalcular_total_pedido` NO era no-op para `taller` — `bruto_linea`
respeta `cobro_modo='fijo'` así que el SUBTOTAL por línea sobrevivía, pero
`calcular_total` igual podía aplicarle un % de descuento (cliente/jornadas/
manual) a un pedido sin cliente ni jornadas reales. Nunca se disparó en
producción porque esos campos dan 0 por coincidencia (sin `cliente_id`, sin
override cargado) — este archivo prueba el caso con `descuento_pct` cargado a
mano, para que el guard se pruebe de verdad y no por la misma coincidencia.

OPT-IN y SEGURO POR DEFECTO (mismo gating que test_estudio_pedidos_blindaje_db.py):

    DATABASE_URL=postgresql://tincho@localhost/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_taller_pedidos_blindaje_db.py -v -m integration
"""
import os
from urllib.parse import urlparse

import pytest
from fastapi import HTTPException

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

PEDIDO_TALLER_ID = 9_451_101
PEDIDO_TURNO_REAL_ID = 9_451_102  # turno real de estudio, SOLO para el test de _revalidar_stock
PEDIDO_TALLER_TURNOS_ID = 9_451_103  # taller con turnos-embebidos por clase (2026-08-13)
NOMBRE_EQUIPOS = "Uso de equipos — Test blindaje taller"
FD, FH = "2026-09-01T00:00:00", "2026-09-30T23:59:59"
VALOR_ESTUDIO = 30_000
VALOR_EQUIPOS = 20_000


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN (%s,%s)",
        (PEDIDO_TALLER_ID, PEDIDO_TURNO_REAL_ID),
    )
    conn.execute(
        "DELETE FROM alquileres WHERE id IN (%s,%s)",
        (PEDIDO_TALLER_ID, PEDIDO_TURNO_REAL_ID),
    )


@pytest.fixture
def db_setup():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        centinela_id = conn.execute("SELECT equipo_id FROM estudio WHERE id=1").fetchone()["equipo_id"]
        assert centinela_id
        # Pedido de taller TAL COMO lo arma _regenerar_pedidos_taller: sin
        # cliente_id, monto_total = suma de los 2 auto-ítems. `descuento_pct`
        # cargado a mano (15%) — nunca lo setearía el generador real, pero es
        # lo que prueba que el guard cierra la clase de bug, no la coincidencia
        # "cliente_id NULL → descuento 0".
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, "
            "monto_total, descuento_pct) "
            "VALUES (%s,'Taller test blindaje','confirmado','taller',%s,%s,%s,15)",
            (PEDIDO_TALLER_ID, FD, FH, VALOR_ESTUDIO + VALOR_EQUIPOS),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
            "VALUES (%s,%s,1,%s,%s,'fijo')",
            (PEDIDO_TALLER_ID, centinela_id, VALOR_ESTUDIO, VALOR_ESTUDIO),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, nombre_libre, cantidad, "
            "precio_jornada, subtotal, cobro_modo) "
            "VALUES (%s,NULL,%s,1,%s,%s,'fijo')",
            (PEDIDO_TALLER_ID, NOMBRE_EQUIPOS, VALOR_EQUIPOS, VALOR_EQUIPOS),
        )
        # Turno REAL de estudio, un día puntual DENTRO del mes del taller —
        # el centinela tiene cantidad=1: bajo el código viejo (sin el skip),
        # `_revalidar_stock` de un taller caía al `_check_stock` genérico, que
        # contaría este turno como conflicto contra el rango de TODO el mes del
        # taller (0 unidades libres esos días) y rechazaría con 422 una
        # transición que debería pasar sin problema.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total) "
            "VALUES (%s,'Turno real test blindaje','confirmado','estudio','2026-09-15T10:00:00',"
            "'2026-09-15T14:00:00',10000)",
            (PEDIDO_TURNO_REAL_ID,),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
            "VALUES (%s,%s,1,10000,10000,'fijo')",
            (PEDIDO_TURNO_REAL_ID, centinela_id),
        )
        conn.commit()
        yield centinela_id
    finally:
        _limpiar(conn)
        conn.commit()
        conn.close()


def test_editar_notas_no_pisa_monto_pedido_taller_con_descuento_cargado(db_setup):
    """Candado del bug latente: sin el no-op, `_recalcular_total_pedido`
    aplicaría el 15% de `descuento_pct` sobre el bruto ($50.000 → $42.500)."""
    from database import get_db
    from routes.alquileres.core import _apply_pedido_datos
    from routes.alquileres.modelos import PedidoDatos

    conn = get_db()
    try:
        pedido = _apply_pedido_datos(
            conn, PEDIDO_TALLER_ID,
            PedidoDatos(notas="probando blindaje taller", fecha_desde=FD, fecha_hasta=FH),
            es_admin=True,
        )
        conn.commit()
    finally:
        conn.close()

    assert pedido["notas"] == "probando blindaje taller"
    assert pedido["monto_total"] == VALOR_ESTUDIO + VALOR_EQUIPOS, (
        f"el no-op debería dejar monto_total intacto ({VALOR_ESTUDIO + VALOR_EQUIPOS}); fue "
        f"{pedido['monto_total']} — ¿se le aplicó el descuento_pct cargado a mano?"
    )


def test_editar_fechas_pedido_taller_rechazado(db_setup):
    """Las fechas de un taller las gobierna la edición — el editor genérico
    las rechaza (409), mismo criterio que estudio."""
    from database import get_db, to_datetime
    from routes.alquileres.core import _apply_pedido_datos
    from routes.alquileres.modelos import PedidoDatos

    nueva_fh = "2026-10-05T23:59:59"
    conn = get_db()
    try:
        with pytest.raises(HTTPException) as exc_info:
            _apply_pedido_datos(
                conn, PEDIDO_TALLER_ID,
                PedidoDatos(fecha_desde=FD, fecha_hasta=nueva_fh),
                es_admin=True,
            )
        assert exc_info.value.status_code == 409
        conn.rollback()
    finally:
        conn.close()

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT fecha_hasta FROM alquileres WHERE id=%s", (PEDIDO_TALLER_ID,)
        ).fetchone()
        assert to_datetime(row["fecha_hasta"]) == to_datetime(FH)
    finally:
        conn.close()


def test_put_items_taller_rechaza_perder_el_centinela(db_setup):
    """Reemplazar los ítems SIN el centinela (espacio) se rechaza — perdería
    la atribución de esa plata a la economía del Estudio en silencio."""
    from database import get_db
    from routes.alquileres.core import _apply_pedido_items
    from routes.alquileres.modelos import PedidoItem

    centinela_id = db_setup
    conn = get_db()
    try:
        with pytest.raises(HTTPException) as exc_info:
            _apply_pedido_items(
                conn, PEDIDO_TALLER_ID,
                [PedidoItem(
                    equipo_id=None, nombre_libre=NOMBRE_EQUIPOS, cantidad=1,
                    precio_jornada=VALOR_EQUIPOS, cobro_modo="fijo",
                )],
            )
        assert exc_info.value.status_code == 409
        conn.rollback()
    finally:
        conn.close()

    conn = get_db()
    try:
        items = conn.execute(
            "SELECT equipo_id FROM alquiler_items WHERE pedido_id=%s", (PEDIDO_TALLER_ID,)
        ).fetchall()
        assert any(it["equipo_id"] == centinela_id for it in items), (
            "no debería haber tocado nada al rechazar"
        )
    finally:
        conn.close()


def test_put_items_taller_rechaza_perder_la_linea_de_equipos(db_setup):
    """Reemplazar los ítems SIN la línea "Uso de equipos — …" se rechaza,
    aunque el centinela se mantenga."""
    from database import get_db
    from routes.alquileres.core import _apply_pedido_items
    from routes.alquileres.modelos import PedidoItem

    centinela_id = db_setup
    conn = get_db()
    try:
        with pytest.raises(HTTPException) as exc_info:
            _apply_pedido_items(
                conn, PEDIDO_TALLER_ID,
                [PedidoItem(
                    equipo_id=centinela_id, cantidad=1,
                    precio_jornada=VALOR_ESTUDIO, cobro_modo="fijo",
                )],
            )
        assert exc_info.value.status_code == 409
        conn.rollback()
    finally:
        conn.close()


def test_put_items_taller_permite_agregar_matricula_conservando_el_auto(db_setup):
    """El caso que taller SÍ tiene que permitir (a diferencia de estudio): una
    línea nueva de matrícula, agregada a mano, sumada a los 2 ítems auto sin
    tocarlos."""
    from database import get_db
    from routes.alquileres.core import _apply_pedido_items
    from routes.alquileres.modelos import PedidoItem

    centinela_id = db_setup
    conn = get_db()
    try:
        pedido = _apply_pedido_items(
            conn, PEDIDO_TALLER_ID,
            [
                PedidoItem(
                    equipo_id=centinela_id, cantidad=1,
                    precio_jornada=VALOR_ESTUDIO, cobro_modo="fijo",
                ),
                PedidoItem(
                    equipo_id=None, nombre_libre=NOMBRE_EQUIPOS, cantidad=1,
                    precio_jornada=VALOR_EQUIPOS, cobro_modo="fijo",
                ),
                PedidoItem(
                    equipo_id=None, nombre_libre="Matrícula Juan Pérez", cantidad=1,
                    precio_jornada=15_000, cobro_modo="fijo",
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    nombres = {it["nombre_libre"] for it in pedido["items"] if it["equipo_id"] is None}
    assert "Matrícula Juan Pérez" in nombres
    assert NOMBRE_EQUIPOS in nombres
    assert any(it["equipo_id"] == centinela_id for it in pedido["items"])
    assert pedido["monto_total"] == VALOR_ESTUDIO + VALOR_EQUIPOS + 15_000


def test_put_items_taller_con_turnos_por_clase_permite_agregar_matricula(db_setup):
    """Bug real encontrado en la auditoría de consumidores del turno-embebido-
    por-clase (2026-08-13, `_crear_turnos_taller_del_mes`): con el modelo
    NUEVO (N turnos embebidos, uno por clase real, `turno_estudio_id IS NOT
    NULL`) — a diferencia del fixture plano de `db_setup` arriba (un único
    ítem con `turno_estudio_id IS NULL`) — el front (`pedidoToItems`) NUNCA
    manda de vuelta esas filas: viven en su propia sección, no en el array
    genérico de ítems. Antes del fix, `_validar_reemplazo_items_taller`
    contaba esas filas igual en `actuales` (sin filtrar `turno_estudio_id`) y
    exigía que el centinela reapareciera en `items_nuevos` — algo que este
    endpoint NUNCA recibe para una fila de turno — así que CUALQUIER
    guardado de ítems (incluida la única vía real de agregar una matrícula)
    rechazaba con 409 en un taller con clases cargadas."""
    from database import get_db
    from routes.alquileres.core import _apply_pedido_items
    from routes.alquileres.modelos import PedidoItem

    centinela_id = db_setup
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, "
            "monto_total) VALUES (%s,'Taller test turnos por clase','confirmado','taller',%s,%s,%s)",
            (PEDIDO_TALLER_TURNOS_ID, FD, FH, VALOR_ESTUDIO + VALOR_EQUIPOS),
        )
        for desde, hasta in [
            ("2026-09-06 10:00", "2026-09-06 13:00"),
            ("2026-09-13 10:00", "2026-09-13 13:00"),
        ]:
            turno_id = conn.execute(
                "INSERT INTO alquiler_turnos_estudio (pedido_id, fecha_desde, fecha_hasta) "
                "VALUES (%s,%s,%s) RETURNING id",
                (PEDIDO_TALLER_TURNOS_ID, desde, hasta),
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
                "subtotal, cobro_modo, turno_estudio_id) VALUES (%s,%s,1,%s,%s,'fijo',%s)",
                (
                    PEDIDO_TALLER_TURNOS_ID, centinela_id,
                    VALOR_ESTUDIO // 2, VALOR_ESTUDIO // 2, turno_id,
                ),
            )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, nombre_libre, cantidad, "
            "precio_jornada, subtotal, cobro_modo) "
            "VALUES (%s,NULL,%s,1,%s,%s,'fijo')",
            (PEDIDO_TALLER_TURNOS_ID, NOMBRE_EQUIPOS, VALOR_EQUIPOS, VALOR_EQUIPOS),
        )
        conn.commit()

        # Mismo shape que `pedidoToItems` (front) manda de vuelta: SIN las
        # filas de turno, la línea "Uso de equipos" tal cual estaba, más una
        # matrícula nueva — no debe rechazar.
        pedido = _apply_pedido_items(
            conn, PEDIDO_TALLER_TURNOS_ID,
            [
                PedidoItem(
                    equipo_id=None, nombre_libre=NOMBRE_EQUIPOS, cantidad=1,
                    precio_jornada=VALOR_EQUIPOS, cobro_modo="fijo",
                ),
                PedidoItem(
                    equipo_id=None, nombre_libre="Matrícula Juan Pérez", cantidad=1,
                    precio_jornada=15_000, cobro_modo="fijo",
                ),
            ],
        )
        conn.commit()

        nombres = {it["nombre_libre"] for it in pedido["items"] if it["equipo_id"] is None}
        assert "Matrícula Juan Pérez" in nombres
        assert NOMBRE_EQUIPOS in nombres

        # Las 2 filas de turno sobreviven intactas — este endpoint no las toca.
        n_turnos = conn.execute(
            "SELECT COUNT(*) AS n FROM alquiler_items "
            "WHERE pedido_id=%s AND turno_estudio_id IS NOT NULL",
            (PEDIDO_TALLER_TURNOS_ID,),
        ).fetchone()["n"]
        assert n_turnos == 2
    finally:
        conn.execute("DELETE FROM alquiler_items WHERE pedido_id=%s", (PEDIDO_TALLER_TURNOS_ID,))
        conn.execute(
            "DELETE FROM alquiler_turnos_estudio WHERE pedido_id=%s", (PEDIDO_TALLER_TURNOS_ID,)
        )
        conn.execute("DELETE FROM alquileres WHERE id=%s", (PEDIDO_TALLER_TURNOS_ID,))
        conn.commit()
        conn.close()


def test_revalidar_stock_taller_se_saltea(db_setup):
    """Transicionar un pedido de taller desde un estado no-reservante hasta uno
    reservante no debe disparar el motor genérico (contaría el centinela
    contra el mes entero) ni el revalidador de estudio (preguntaría por el mes
    entero, casi siempre "no libre") — tiene que pasar directo."""
    from database import get_db
    from routes.alquileres.transiciones import cambiar_estado

    conn = get_db()
    try:
        # confirmado → borrador (no reserva) → confirmado (reserva): dispara
        # _requiere_revalidar_stock, que es donde vivía el riesgo.
        cambiar_estado(conn, PEDIDO_TALLER_ID, "borrador", es_admin=True, actor="test")
        res = cambiar_estado(conn, PEDIDO_TALLER_ID, "confirmado", es_admin=True, actor="test")
        conn.commit()
    finally:
        conn.close()

    assert res["estado_nuevo"] == "confirmado"
