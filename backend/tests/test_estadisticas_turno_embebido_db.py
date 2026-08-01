"""#1308 rediseño "turno como ítem", Fase 2.2 — `routes/estadisticas.py` no debe
perder ni duplicar la plata de un turno del Estudio EMBEBIDO (`alquiler_turnos_estudio`
+ `alquiler_items.turno_estudio_id`) en un pedido de alquiler normal (`tipo='diaria'`).

Dos bugs distintos que este test cubre, ambos posibles sin el fix:

  1. El pedido mixto (equipo normal + turno embebido) sigue siendo `tipo='diaria'`
     — pasa el filtro `NOT IN TIPOS_DERIVADOS_SQL` de las tarjetas de rental. Sin
     `equipos.es_recurso_interno = FALSE` en `top_equipos`/`por_dueno`, el ítem del
     centinela (`cobro_modo='fijo'`, plata real del turno) se cuela ahí como si
     fuera un equipo más — y sin `_TURNO_NETO_CTE`, `totales`/`por_mes`/
     `top_clientes`/`clientes_recurrentes`/`mejor_peor_mes` inflarían el negocio
     de rental con plata que es del Estudio.
  2. Simétricamente, esa misma plata tiene que APARECER en la sección `estudio`
     (antes solo sumaba pedidos standalone `tipo IN ('estudio','estudio_fijo')`)
     — si no, desaparece de las DOS secciones (doble error, no uno).

El fixture combina un turno EMBEBIDO con uno STANDALONE (`tipo='estudio'`, otro
cliente) en el MISMO mes/bucket para confirmar que `eventos_estudio` (UNION ALL)
los agrega juntos sin duplicar ni perder ninguno — en particular
`COUNT(DISTINCT cliente_id)`, que sería fácil de descuadrar sumando dos conteos
por separado en vez de unir las dos fuentes ANTES de contar.

`por_dueno` (sin `LIMIT`, a diferencia de `top_equipos`) es la asserción exacta
de "cuánto le llegó a rental" — se le da al equipo normal un `dueno` distintivo
para no depender de qué otros dueños ya existan en la base de test.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_estadisticas_turno_embebido_db.py -v -m integration
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

# Ids altos dedicados (bloque 9_483_xxx, sin uso en otros *_db.py).
CLIENTE_MIXTO_ID = 9_483_001
CLIENTE_STANDALONE_ID = 9_483_002
EQUIPO_NORMAL_ID = 9_483_010
PEDIDO_MIXTO_ID = 9_483_020        # tipo='diaria': equipo normal + turno embebido
PEDIDO_STANDALONE_ID = 9_483_021   # tipo='estudio': turno real, otro cliente

DUENO_TEST = "Rental Test 1308-F2.2"
MES = "2031-05"
RENTAL_MONTO = 40_000
TURNO_EMBEBIDO_MONTO = 15_000
STANDALONE_MONTO = 22_000

PEDIDO_DESDE, PEDIDO_HASTA = f"{MES}-10", f"{MES}-13"
TURNO_DESDE, TURNO_HASTA = f"{MES}-10 14:00", f"{MES}-10 16:00"        # 2 horas
STANDALONE_DESDE, STANDALONE_HASTA = f"{MES}-15 10:00", f"{MES}-15 13:00"  # 3 horas


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN (%s, %s)",
        (PEDIDO_MIXTO_ID, PEDIDO_STANDALONE_ID),
    )
    conn.execute("DELETE FROM alquiler_turnos_estudio WHERE pedido_id = %s", (PEDIDO_MIXTO_ID,))
    conn.execute(
        "DELETE FROM alquileres WHERE id IN (%s, %s)", (PEDIDO_MIXTO_ID, PEDIDO_STANDALONE_ID)
    )
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQUIPO_NORMAL_ID,))
    conn.execute(
        "DELETE FROM clientes WHERE id IN (%s, %s)", (CLIENTE_MIXTO_ID, CLIENTE_STANDALONE_ID)
    )


def _insertar(conn):
    conn.execute(
        "INSERT INTO clientes (id, nombre, apellido, email, telefono) VALUES "
        "(%s,'Turno','Mixto','turno-mixto-estadisticas@test.com','+5491100000097'),"
        "(%s,'Turno','Standalone','turno-standalone-estadisticas@test.com','+5491100000096')",
        (CLIENTE_MIXTO_ID, CLIENTE_STANDALONE_ID),
    )
    conn.execute(
        "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s, %s, 1, %s)",
        (EQUIPO_NORMAL_ID, "Equipo rental test #1308-F2.2", DUENO_TEST),
    )
    cid = conn.execute("SELECT equipo_id FROM estudio WHERE id=1").fetchone()["equipo_id"]

    # Pedido mixto: equipo normal (rental) + turno embebido (2hs), mismo pedido.
    conn.execute(
        "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
        "fecha_desde, fecha_hasta, monto_total) "
        "VALUES (%s,%s,'Turno Mixto','finalizado','diaria',%s,%s,%s)",
        (
            PEDIDO_MIXTO_ID,
            CLIENTE_MIXTO_ID,
            PEDIDO_DESDE,
            PEDIDO_HASTA,
            RENTAL_MONTO + TURNO_EMBEBIDO_MONTO,
        ),
    )
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal, cobro_modo) "
        "VALUES (%s,%s,1,%s,'jornada')",
        (PEDIDO_MIXTO_ID, EQUIPO_NORMAL_ID, RENTAL_MONTO),
    )
    turno_id = conn.execute(
        "INSERT INTO alquiler_turnos_estudio (pedido_id, fecha_desde, fecha_hasta) "
        "VALUES (%s,%s,%s) RETURNING id",
        (PEDIDO_MIXTO_ID, TURNO_DESDE, TURNO_HASTA),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO alquiler_items "
        "(pedido_id, equipo_id, cantidad, subtotal, cobro_modo, turno_estudio_id) "
        "VALUES (%s,%s,1,%s,'fijo',%s)",
        (PEDIDO_MIXTO_ID, cid, TURNO_EMBEBIDO_MONTO, turno_id),
    )

    # Pedido standalone: turno real del Estudio (tipo='estudio'), OTRO cliente.
    conn.execute(
        "INSERT INTO alquileres (id, cliente_id, cliente_nombre, estado, tipo, "
        "fecha_desde, fecha_hasta, monto_total) "
        "VALUES (%s,%s,'Turno Standalone','finalizado','estudio',%s,%s,%s)",
        (PEDIDO_STANDALONE_ID, CLIENTE_STANDALONE_ID, STANDALONE_DESDE, STANDALONE_HASTA, STANDALONE_MONTO),
    )
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal, cobro_modo) "
        "VALUES (%s,%s,1,%s,'fijo')",
        (PEDIDO_STANDALONE_ID, cid, STANDALONE_MONTO),
    )


@pytest.fixture
def conn():
    from database import get_db, init_db

    init_db()
    c = get_db()
    try:
        _limpiar(c)
        c.commit()
        yield c
    finally:
        _limpiar(c)
        c.commit()
        c.close()


def test_turno_embebido_no_se_pierde_ni_se_duplica(conn):
    from routes.estadisticas import compute_estadisticas

    antes = compute_estadisticas(conn)
    total_ars_antes = antes["totales"]["total_ars"] or 0
    total_pedidos_antes = antes["totales"]["total_pedidos"] or 0
    dueno_test_antes = next(
        (d["total_ars"] or 0 for d in antes["por_dueno"] if d["dueno"] == DUENO_TEST), 0
    )
    estudio_turnos_antes = antes["estudio"]["totales"]["total_turnos"] or 0
    estudio_ars_antes = antes["estudio"]["totales"]["total_ars"] or 0
    estudio_clientes_antes = antes["estudio"]["totales"]["total_clientes"] or 0
    estudio_horas_antes = float(antes["estudio"]["totales"]["horas_vendidas"] or 0)

    _insertar(conn)
    conn.commit()

    despues = compute_estadisticas(conn)

    # ── Rental: SOLO la porción del equipo normal, nunca la del turno ────────
    assert (despues["totales"]["total_pedidos"] or 0) - total_pedidos_antes == 1
    assert (despues["totales"]["total_ars"] or 0) - total_ars_antes == RENTAL_MONTO

    fila_mes = next((m for m in despues["por_mes"] if m["mes"] == MES), None)
    assert fila_mes is not None, despues["por_mes"]
    assert fila_mes["total_ars"] == RENTAL_MONTO

    # `por_dueno` no tiene LIMIT (a diferencia de `top_equipos`) — asserción
    # exacta, inmune a que otros equipos de la base de test rankeen más alto.
    dueno_test_despues = next(
        (d["total_ars"] or 0 for d in despues["por_dueno"] if d["dueno"] == DUENO_TEST), 0
    )
    assert dueno_test_despues - dueno_test_antes == RENTAL_MONTO

    # El centinela nunca aparece como "equipo" de rental, ni bajo su propio pedido
    # `tipo='diaria'` mixto ni bajo el standalone.
    assert not any(e["equipo"] == "Equipo rental test #1308-F2.2" and e["total_ars"] != RENTAL_MONTO
                   for e in despues["top_equipos"])
    assert not any("centinela" in (e["equipo"] or "").lower() for e in despues["top_equipos"])

    # ── Estudio: la plata del turno embebido SE SUMA (no desaparece) ─────────
    tot_estudio = despues["estudio"]["totales"]
    assert (tot_estudio["total_turnos"] or 0) - estudio_turnos_antes == 2  # embebido + standalone
    assert (tot_estudio["total_ars"] or 0) - estudio_ars_antes == TURNO_EMBEBIDO_MONTO + STANDALONE_MONTO
    # Dos clientes DISTINTOS (uno por turno) — prueba que `eventos_estudio` (UNION
    # ALL antes de contar) no duplica ni pierde al unir standalone + embebido.
    assert (tot_estudio["total_clientes"] or 0) - estudio_clientes_antes == 2

    horas_delta = float(tot_estudio["horas_vendidas"] or 0) - estudio_horas_antes
    assert horas_delta == pytest.approx(5.0)  # 2hs embebido + 3hs standalone

    # ── `estudio.por_mes`: bucket exclusivo del fixture → asserción exacta ───
    fila_estudio_mes = next((m for m in despues["estudio"]["por_mes"] if m["mes"] == MES), None)
    assert fila_estudio_mes is not None, despues["estudio"]["por_mes"]
    assert fila_estudio_mes["turnos"] == 2
    assert fila_estudio_mes["meses_slot_fijo"] == 0
    assert fila_estudio_mes["total_ars"] == TURNO_EMBEBIDO_MONTO + STANDALONE_MONTO
    assert float(fila_estudio_mes["horas_vendidas"]) == pytest.approx(5.0)
