"""Fase 7 (#1283) contra Postgres REAL — Estadísticas separa la economía del
Estudio de la del rental.

Antes de esta fase, un pedido de Estudio (`tipo IN ('estudio','estudio_fijo')`)
se mezclaba con el rental en TODAS las agregaciones de `compute_estadisticas`:
el centinela (`equipos.dueno='Estudio'`, un recurso interno — no un equipo
real) inflaba "Top equipos"/"por dueño", y el cliente/turno aparecía en
"Top clientes"/"Clientes recurrentes"/"Mejor y peor mes" del negocio de
rental. Ahora esas tarjetas EXCLUYEN `tipo IN ('estudio','estudio_fijo')` y
una sección nueva `estudio` agrega esos pedidos aparte.

`horas_vendidas` es el punto fino: se computa SOLO de `tipo='estudio'` (turnos
reales) vía `FILTER` — un `estudio_fijo` guarda en `fecha_desde/fecha_hasta`
únicamente la PRIMERA ocurrencia semanal del mes (`_regenerar_pedidos_slot`),
no el total de horas de todas las recurrencias, así que sumarlo ahí
subestimaría las horas. El fixture le da al slot fijo una franja de duración
DISTINTA a la del turno real para que el test detecte si `horas_vendidas`
accidentalmente incluye ambos tipos.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`). Mes de
fixture (2026-03) sin uso en otros `*_db.py` — bucket exclusivo para
asserciones exactas en `por_mes`/`estudio.por_mes`.

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_estadisticas_estudio_db.py -v -m integration
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

# Ids altos dedicados (bloque 9_302_xxx, sin uso en otros *_db.py).
EQ_CENTINELA = 9_302_001
P_TURNO = 9_302_101
P_SLOT_FIJO = 9_302_102

MES = "2026-03"
TURNO_MONTO = 30_000
SLOT_FIJO_MONTO = 50_000
# Turno real: 3 horas. Slot fijo: 5 horas de franja (la primera ocurrencia del
# mes) que NO debe contarse en horas_vendidas — si el test la contara, la
# horas_vendidas del turno (3.0) se leería como 8.0.
TURNO_DESDE, TURNO_HASTA = f"{MES}-05T08:00:00", f"{MES}-05T11:00:00"
SLOT_DESDE, SLOT_HASTA = f"{MES}-01T08:00:00", f"{MES}-01T13:00:00"


def _limpiar(conn):
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id IN (%s, %s)", (P_TURNO, P_SLOT_FIJO))
    conn.execute("DELETE FROM alquileres WHERE id IN (%s, %s)", (P_TURNO, P_SLOT_FIJO))
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQ_CENTINELA,))


def _insertar(conn):
    conn.execute(
        "INSERT INTO equipos (id, nombre, cantidad, dueno, es_recurso_interno) "
        "VALUES (%s, %s, 1, 'Estudio', TRUE)",
        (EQ_CENTINELA, "Estudio (centinela) test #1283-F7"),
    )
    conn.execute(
        """INSERT INTO alquileres
               (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total)
           VALUES (%s, %s, 'finalizado', 'estudio', %s, %s, %s)""",
        (P_TURNO, "Cliente turno estudio #1283-F7", TURNO_DESDE, TURNO_HASTA, TURNO_MONTO),
    )
    conn.execute(
        """INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal, cobro_modo)
           VALUES (%s, %s, 1, %s, 'fijo')""",
        (P_TURNO, EQ_CENTINELA, TURNO_MONTO),
    )
    conn.execute(
        """INSERT INTO alquileres
               (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total)
           VALUES (%s, %s, 'finalizado', 'estudio_fijo', %s, %s, %s)""",
        (P_SLOT_FIJO, "Cliente slot fijo estudio #1283-F7", SLOT_DESDE, SLOT_HASTA, SLOT_FIJO_MONTO),
    )
    conn.execute(
        """INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal, cobro_modo)
           VALUES (%s, %s, 1, %s, 'fijo')""",
        (P_SLOT_FIJO, EQ_CENTINELA, SLOT_FIJO_MONTO),
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


def test_estadisticas_separa_estudio(conn):
    """Un turno (`tipo='estudio'`) y un mes de slot fijo (`tipo='estudio_fijo'`)
    no deben aparecer en NINGUNA tarjeta de rental (totales/por_mes/top_equipos/
    top_clientes/clientes_recurrentes/por_dueno/mejor_peor_mes), y la sección
    `estudio` nueva los agrega aparte — con `horas_vendidas` SOLO del turno
    real, nunca del slot fijo."""
    from routes.estadisticas import compute_estadisticas

    antes = compute_estadisticas(conn)
    total_pedidos_antes = antes["totales"]["total_pedidos"] or 0
    total_ars_antes = antes["totales"]["total_ars"] or 0
    dueno_estudio_antes = next(
        (d["total_ars"] or 0 for d in antes["por_dueno"] if d["dueno"] == "Estudio"), 0
    )
    estudio_turnos_antes = antes["estudio"]["totales"]["total_turnos"] or 0
    estudio_slots_antes = antes["estudio"]["totales"]["total_meses_slot_fijo"] or 0
    estudio_ars_antes = antes["estudio"]["totales"]["total_ars"] or 0
    estudio_horas_antes = float(antes["estudio"]["totales"]["horas_vendidas"] or 0)

    _insertar(conn)
    conn.commit()

    despues = compute_estadisticas(conn)

    # ── Tarjetas de rental: CERO impacto ──────────────────────────────────────
    assert (despues["totales"]["total_pedidos"] or 0) == total_pedidos_antes
    assert (despues["totales"]["total_ars"] or 0) == total_ars_antes

    assert not any(m["mes"] == MES for m in despues["por_mes"])
    assert not any(e["equipo"] == "Estudio (centinela) test #1283-F7" for e in despues["top_equipos"])
    assert not any("estudio" in (c["cliente"] or "").lower() and "#1283-F7" in (c["cliente"] or "")
                   for c in despues["top_clientes"])
    assert not any("#1283-F7" in (c["cliente"] or "") for c in despues["clientes_recurrentes"])

    # `por_dueno` ya listaba 'Estudio' (el centinela pertenece a ese dueño) —
    # el punto es que estos DOS pedidos no le sumen nada ahí (viven en la
    # sección `estudio` aparte, no en la fragmentación de rental).
    dueno_estudio_despues = next(
        (d["total_ars"] or 0 for d in despues["por_dueno"] if d["dueno"] == "Estudio"), 0
    )
    assert dueno_estudio_despues == dueno_estudio_antes

    # ── Sección `estudio`: agrega ambos pedidos, cada uno en su columna ──────
    tot_estudio = despues["estudio"]["totales"]
    assert (tot_estudio["total_turnos"] or 0) - estudio_turnos_antes == 1
    assert (tot_estudio["total_meses_slot_fijo"] or 0) - estudio_slots_antes == 1
    assert (tot_estudio["total_ars"] or 0) - estudio_ars_antes == TURNO_MONTO + SLOT_FIJO_MONTO

    # `horas_vendidas` SOLO del turno real (3h) — el slot fijo (5h de franja)
    # NO debe sumar acá, si no el delta sería 8.0 en vez de 3.0.
    horas_delta = float(tot_estudio["horas_vendidas"] or 0) - estudio_horas_antes
    assert horas_delta == pytest.approx(3.0)

    # ── `estudio.por_mes`: bucket exclusivo del fixture → asserción exacta ───
    fila_mes = next((m for m in despues["estudio"]["por_mes"] if m["mes"] == MES), None)
    assert fila_mes is not None, despues["estudio"]["por_mes"]
    assert fila_mes["turnos"] == 1
    assert fila_mes["meses_slot_fijo"] == 1
    assert fila_mes["total_ars"] == TURNO_MONTO + SLOT_FIJO_MONTO
    assert float(fila_mes["horas_vendidas"]) == pytest.approx(3.0)

    # ── Mejor/peor mes: nuestro mes exclusivo no puede ganar/perder con plata
    #    que en realidad es del Estudio (ya excluida de por_mes/mejor_peor).
    assert despues["mejor_peor_mes"]["mejor_mes"] != MES
    assert despues["mejor_peor_mes"]["peor_mes"] != MES
