"""#1308 — round-trip de dataio para un turno del Estudio EMBEBIDO (backup/restore).

Bug real (auditoría del rediseño "turno como ítem"): `export_alquileres` no
sabía nada de `alquiler_turnos_estudio` ni de `alquiler_items.turno_estudio_id`
— un pedido con un turno embebido, tras un ciclo `dataio export` → `dataio
import` (backup/restore o clonado de ambiente):
  1. perdía la fila de `alquiler_turnos_estudio` entera (franja propia +
     descuento propio del turno);
  2. el centinela volvía como un ítem NORMAL sin marca de turno (indistinguible
     de un equipo de catálogo real);
  3. la línea "Pintura reciente" (`equipo_id IS NULL`, línea personalizada
     #805) directamente DESAPARECÍA — el exportador usaba un INNER JOIN contra
     `equipos`, que nunca matchea un ítem sin equipo.

Este test (mismo patrón que `test_dataio_pagos_anulado_roundtrip_db.py`)
verifica contra Postgres real, con un pedido que tiene los TRES casos a la vez
(ítem normal + turno con centinela + pintura reciente del turno):
  1. El export incluye `turnos_estudio` (franja + descuento) y cada ítem trae
     `turno_index`/`nombre_libre` correctos.
  2. Round-trip completo: export → se borra todo el pedido (simula un
     ambiente fresco) → import → el turno vuelve como grupo propio, el
     centinela queda tageado a ESE turno (no un ítem suelto), y la pintura
     reciente sobrevive.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py): se saltea
salvo `RESERVAS_DB_TEST=1` + `DATABASE_URL` a una base con 'test' en el
nombre. Trabaja sobre ids de prueba (>= 9_710_000) y limpia al terminar.
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

ALQ_ID = 9_710_001
NUMERO_PEDIDO = 9_710_001
E_EQUIPO = 9_710_010
E_CENTINELA = 9_710_011
SLUG_EQUIPO = "equipo-roundtrip-turno-9710010"
SLUG_CENTINELA = "centinela-roundtrip-turno-9710011"
PINTURA_NOMBRE = "Recién pintado"


def _limpiar(conn):
    # Por `numero_pedido`, no por `ALQ_ID`: el import (sin UNIQUE en esa
    # columna) crea una fila NUEVA con un id distinto cuando la original ya
    # no existe — limpiar solo por id hardcodeado dejaba huérfana la fila
    # reimportada y el DELETE de equipos de abajo fallaba por FK.
    # CASCADE en alquiler_items/alquiler_turnos_estudio limpia lo embebido.
    conn.execute("DELETE FROM alquileres WHERE id = %s OR numero_pedido = %s", (ALQ_ID, NUMERO_PEDIDO))
    conn.execute("DELETE FROM equipos WHERE id IN (%s, %s)", (E_EQUIPO, E_CENTINELA))


@pytest.fixture
def pedido_con_turno_embebido():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, slug) VALUES (%s,%s,%s,%s)",
            (E_EQUIPO, "Equipo Roundtrip Turno", 2, SLUG_EQUIPO),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, slug, es_recurso_interno) "
            "VALUES (%s,%s,%s,%s,TRUE)",
            (E_CENTINELA, "Centinela Roundtrip Turno", 1, SLUG_CENTINELA),
        )
        conn.execute(
            """
            INSERT INTO alquileres
                (id, numero_pedido, cliente_nombre, estado,
                 fecha_desde, fecha_hasta, monto_total, monto_pagado)
            VALUES (%s, %s, %s, 'confirmado',
                    '2026-07-01', '2026-07-04', 99000, 0)
            """,
            (ALQ_ID, NUMERO_PEDIDO, "Cliente Roundtrip Turno Test"),
        )
        turno_id = conn.insert_returning(
            """
            INSERT INTO alquiler_turnos_estudio
                (pedido_id, fecha_desde, fecha_hasta, descuento_pct,
                 descuento_manual_tipo, descuento_manual_monto)
            VALUES (%s, '2026-07-01 10:00:00', '2026-07-01 12:00:00', 10.0, 'pct', 0)
            """,
            (ALQ_ID,),
        )
        # Ítem normal del pedido (sin turno).
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo) VALUES (%s,%s,1,10000,30000,'jornada')",
            (ALQ_ID, E_EQUIPO),
        )
        # Centinela del turno (equipo real, tageado).
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo, turno_estudio_id) VALUES (%s,%s,1,62100,62100,'fijo',%s)",
            (ALQ_ID, E_CENTINELA, turno_id),
        )
        # "Pintura reciente" del turno: línea personalizada (equipo_id NULL).
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, "
            "subtotal, cobro_modo, nombre_libre, turno_estudio_id) "
            "VALUES (%s,NULL,1,6900,6900,'fijo',%s,%s)",
            (ALQ_ID, PINTURA_NOMBRE, turno_id),
        )
        conn.commit()
    finally:
        conn.close()

    yield turno_id

    conn = get_db()
    try:
        _limpiar(conn)
        conn.commit()
    finally:
        conn.close()


def test_export_alquileres_incluye_turno_embebido_y_pintura(pedido_con_turno_embebido):
    """El export debe incluir el turno (franja+descuento) y sus 2 ítems, con
    `turno_index` correcto — antes el turno se perdía entero y la pintura
    reciente ni siquiera llegaba a la lista de ítems."""
    from database import get_db
    from dataio.exporters import export_alquileres

    conn = get_db()
    try:
        rows = export_alquileres(conn)
        alq = next(r for r in rows if r["numero_pedido"] == NUMERO_PEDIDO)

        assert len(alq["turnos_estudio"]) == 1, "el turno embebido debe exportarse"
        turno = alq["turnos_estudio"][0]
        assert turno["descuento_pct"] == 10.0

        assert len(alq["items"]) == 3, alq["items"]
        normal = next(it for it in alq["items"] if it["equipo_slug"] == SLUG_EQUIPO)
        assert normal["turno_index"] is None, "el ítem normal no pertenece a ningún turno"

        centinela = next(it for it in alq["items"] if it["equipo_slug"] == SLUG_CENTINELA)
        assert centinela["turno_index"] == 0, "el centinela debe apuntar al turno 0"

        pintura = next(
            it for it in alq["items"]
            if it["equipo_slug"] is None and it["nombre_libre"] == PINTURA_NOMBRE
        )
        assert pintura["turno_index"] == 0, "la pintura reciente debe apuntar al turno 0"
        assert pintura["cobro_modo"] == "fijo"
    finally:
        conn.close()


def test_import_restaura_turno_embebido_y_pintura(pedido_con_turno_embebido):
    """Round-trip completo: export → (simula ambiente fresco) → import → el
    turno vuelve como grupo propio (con su descuento), el centinela queda
    tageado a ESE turno (no un ítem suelto), y la pintura reciente sobrevive
    en vez de desaparecer."""
    from database import get_db
    from dataio.exporters import export_alquileres
    from dataio.importers import import_alquileres
    from dataio.natural_keys import KeyResolver

    conn = get_db()
    try:
        rows = export_alquileres(conn)

        # Simula el escenario real: el pedido no existe todavía en el destino
        # (backup restaurado en un ambiente fresco / clonado). Los equipos
        # SÍ sobreviven (se importan aparte, antes que alquileres).
        conn.execute("DELETE FROM alquileres WHERE id = %s", (ALQ_ID,))
        conn.commit()
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM alquileres WHERE id = %s", (ALQ_ID,)
        ).fetchone()["n"] == 0

        resolver = KeyResolver(conn)
        import_alquileres(conn, rows, resolver)
        conn.commit()
    finally:
        conn.close()

    conn = get_db()
    try:
        pedido = conn.execute(
            "SELECT id FROM alquileres WHERE numero_pedido = %s", (NUMERO_PEDIDO,)
        ).fetchone()
        assert pedido is not None, "el import debe restaurar el pedido"
        nuevo_id = pedido["id"]

        turnos = conn.execute(
            "SELECT id, descuento_pct FROM alquiler_turnos_estudio WHERE pedido_id = %s",
            (nuevo_id,),
        ).fetchall()
        assert len(turnos) == 1, (
            "BUG: el turno embebido no sobrevivió al roundtrip export→import "
            "(el export no sabía que `alquiler_turnos_estudio` existe)"
        )
        assert float(turnos[0]["descuento_pct"]) == 10.0

        nuevo_turno_id = turnos[0]["id"]
        items = conn.execute(
            "SELECT ai.equipo_id, ai.nombre_libre, ai.turno_estudio_id, e.slug "
            "FROM alquiler_items ai LEFT JOIN equipos e ON e.id = ai.equipo_id "
            "WHERE ai.pedido_id = %s",
            (nuevo_id,),
        ).fetchall()
        assert len(items) == 3, items

        normal = next(it for it in items if it["slug"] == SLUG_EQUIPO)
        assert normal["turno_estudio_id"] is None

        centinela = next(it for it in items if it["slug"] == SLUG_CENTINELA)
        assert centinela["turno_estudio_id"] == nuevo_turno_id, (
            "BUG: el centinela volvió como ítem SUELTO en vez de quedar "
            "agrupado bajo el turno restaurado"
        )

        pintura = [it for it in items if it["nombre_libre"] == PINTURA_NOMBRE]
        assert len(pintura) == 1, (
            "BUG: la línea 'Pintura reciente' (línea personalizada, sin "
            "equipo) desapareció en el roundtrip — el exportador viejo usaba "
            "un INNER JOIN contra equipos que nunca la matchea"
        )
        assert pintura[0]["turno_estudio_id"] == nuevo_turno_id
    finally:
        conn.close()
