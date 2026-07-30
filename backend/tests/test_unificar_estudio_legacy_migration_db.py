"""Migración `unifestlegacy` — unifica los equipos legacy pre-centinela del
Estudio (267 "Rambla Estudio" / 266 "Estudio Equipos Promo", ids reales de
producción) con el sistema actual (centinela + combo de promo).

Escenario real (encontrado con el dueño mientras revisaba el buscador de
equipos en staging): antes de que el Estudio tuviera centinela+pack/combo,
"reservar el estudio" y "la promo de equipos" eran dos equipos `tipo='simple'`
comunes, con pedidos reales ya facturados. El dueño pidió: (1) re-atribuir ese
historial al centinela/combo actuales — para que Estadísticas/liquidación los
cuente como Estudio — y (2) borrar los dos equipos legacy del todo.

Cubre:
- Combo creado desde el pack curado (misma fórmula que `crear_promo_desde_pack`).
- Pedido puro con SOLO 327 → retagueado a tipo='estudio', ítem re-apuntado al centinela.
- Pedido puro con SOLO 266 → retagueado a tipo='estudio', ítem re-apuntado al combo.
- Pedido puro con AMBOS 266+327 juntos (reserva combinada) → retagueado igual
  (el caso que un chequeo de pureza por-id-separado NO detectaría).
- Pedido MIXTO (327 + otro equipo real) → NO se retaguea, pero el ítem de 327
  sí se re-apunta al centinela.
- 266/327 quedan borrados de `equipos` al final.
- Idempotencia: correr `upgrade` de nuevo no rompe nada (no-op, ya no existen).

Un segundo test cubre la guarda: si 266 es componente VIVO de otro combo
(`kit_componentes.componente_id`), no se borra (para no arrastrar el kit de
ese otro combo en silencio) — pero sí se re-atribuye su historial igual.

OPT-IN y SEGURO POR DEFECTO (mismo patrón que
test_backfill_estudio_dueno_comisiones_migration_db.py): se saltea salvo
ALEMBIC_DB_TEST=1 + DATABASE_URL a una base de prueba.
"""
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

_OPT_IN = os.getenv("ALEMBIC_DB_TEST") == "1"
_DB_URL = os.getenv("DATABASE_URL", "")
_DB_NAME = urlparse(_DB_URL).path.lstrip("/") if _DB_URL else ""


def _looks_like_test_db() -> bool:
    return bool(_DB_NAME) and "test" in _DB_NAME.lower()


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _OPT_IN,
        reason="opt-in: setear ALEMBIC_DB_TEST=1 + DATABASE_URL a una base de prueba",
    ),
    pytest.mark.skipif(
        _OPT_IN and not _looks_like_test_db(),
        reason=f"DATABASE_URL ({_DB_NAME!r}) no parece base de test — abortado por seguridad",
    ),
]

BACKEND_ROOT = Path(__file__).resolve().parent.parent

LEGACY_ESPACIO_ID = 327   # "Rambla Estudio" — id real de producción
LEGACY_PROMO_ID = 266     # "Estudio Equipos Promo" — id real de producción

# Ids de fixture para lo que NO es legacy (bloque alto, sin colisión — el
# schema se resetea entero para este test así que no comparte datos con
# otros *_db.py, pero se usa un bloque claro igual por prolijidad).
EQ_PACK_1 = 9_303_001
EQ_PACK_2 = 9_303_002
EQ_OTRO_REAL = 9_303_003     # equipo real no relacionado, para el pedido mixto
EQ_COMPONENTE_AJENO = 9_303_004  # combo de otro producto, para el test de la guarda

P_SOLO_ESPACIO = 9_303_101
P_SOLO_PROMO = 9_303_102
P_COMBINADO = 9_303_103
P_MIXTO = 9_303_104


def _alembic_config():
    from alembic.config import Config

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return cfg


def _reset_schema():
    from database import get_db

    conn = get_db()
    try:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def clean_db():
    _reset_schema()
    yield
    _reset_schema()


def _equipo(conn, eid, nombre, tipo="simple", dueno="Rental", precio_jornada=10_000):
    conn.execute(
        "INSERT INTO equipos (id, nombre, tipo, cantidad, dueno, precio_jornada, visible_catalogo) "
        "VALUES (%s,%s,%s,1,%s,%s,1)",
        (eid, nombre, tipo, dueno, precio_jornada),
    )


def _pedido(conn, pid, tipo, monto_total):
    conn.execute(
        """INSERT INTO alquileres (id, cliente_nombre, estado, tipo, fecha_desde, fecha_hasta, monto_total)
           VALUES (%s,'Cliente legacy test','finalizado',%s,'2026-01-05T09:00:00','2026-01-05T18:00:00',%s)""",
        (pid, tipo, monto_total),
    )


def _item(conn, pid, eid, subtotal):
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal) VALUES (%s,%s,1,%s)",
        (pid, eid, subtotal),
    )


def _setup_comun(conn):
    """Arma el escenario real: 266/327 con historial, pack curado con 2
    componentes con precio, `estudio.pack_precio` fijado a un objetivo que
    exige descuento (para probar `resolver_descuento_uniforme` de verdad)."""
    _equipo(conn, LEGACY_ESPACIO_ID, "Rambla Estudio", precio_jornada=50_000)
    _equipo(conn, LEGACY_PROMO_ID, "Estudio Equipos Promo", precio_jornada=100_000)
    _equipo(conn, EQ_PACK_1, "Luz de pack 1", precio_jornada=40_000)
    _equipo(conn, EQ_PACK_2, "Luz de pack 2", precio_jornada=40_000)
    _equipo(conn, EQ_OTRO_REAL, "Cámara no relacionada", precio_jornada=30_000)
    conn.execute(
        "INSERT INTO estudio_pack_equipos (estudio_id, equipo_id) VALUES (1,%s), (1,%s)",
        (EQ_PACK_1, EQ_PACK_2),
    )
    # bruto = 40k + 40k = 80k; objetivo 60k → 25% de descuento uniforme.
    conn.execute(
        "UPDATE estudio SET pack_nombre = 'Promo legacy test', pack_precio = 60000 WHERE id = 1"
    )

    # Pedido puro: SOLO el espacio (327).
    _pedido(conn, P_SOLO_ESPACIO, "diaria", 50_000)
    _item(conn, P_SOLO_ESPACIO, LEGACY_ESPACIO_ID, 50_000)

    # Pedido puro: SOLO la promo (266).
    _pedido(conn, P_SOLO_PROMO, "diaria", 100_000)
    _item(conn, P_SOLO_PROMO, LEGACY_PROMO_ID, 100_000)

    # Pedido puro COMBINADO: espacio + promo juntos, nada más (el caso que un
    # chequeo de pureza mal diseñado no detectaría).
    _pedido(conn, P_COMBINADO, "diaria", 150_000)
    _item(conn, P_COMBINADO, LEGACY_ESPACIO_ID, 50_000)
    _item(conn, P_COMBINADO, LEGACY_PROMO_ID, 100_000)

    # Pedido MIXTO: espacio + un equipo real no relacionado → NO se retaguea.
    _pedido(conn, P_MIXTO, "diaria", 80_000)
    _item(conn, P_MIXTO, LEGACY_ESPACIO_ID, 50_000)
    _item(conn, P_MIXTO, EQ_OTRO_REAL, 30_000)


def test_unificar_legacy_happy_path(clean_db):
    from alembic import command
    from database import init_db, get_db

    init_db()
    conn = get_db()
    try:
        _setup_comun(conn)
        centinela_id = conn.execute(
            "SELECT equipo_id FROM estudio WHERE id = 1"
        ).fetchone()["equipo_id"]
        conn.commit()
    finally:
        conn.close()

    command.upgrade(_alembic_config(), "head")

    import migration_state
    cfg = _alembic_config()
    assert migration_state._current_revision() == migration_state._head_revision(cfg)

    conn = get_db()
    try:
        estudio = conn.execute("SELECT promo_combo_id, pack_activo FROM estudio WHERE id = 1").fetchone()
        combo_id = estudio["promo_combo_id"]
        assert combo_id is not None, "el combo tendría que haberse creado"
        assert estudio["pack_activo"] is False

        combo = conn.execute(
            "SELECT nombre, tipo, dueno, visible_catalogo, es_recurso_interno FROM equipos WHERE id = %s",
            (combo_id,),
        ).fetchone()
        assert combo["nombre"] == "Promo legacy test"
        assert combo["tipo"] == "combo"
        # La migración histórica crea el combo con dueno='Rambla' (su valor de
        # ese momento) pero "head" también incluye el rename 23aa6949d4df, que
        # lo reescribe a 'Rental' antes de que este assert corra.
        assert combo["dueno"] == "Rental"
        assert combo["visible_catalogo"] == 0
        assert combo["es_recurso_interno"] is False

        # Descuento uniforme: bruto 80k, objetivo 60k → 25%.
        descuentos = [
            r["descuento_pct"] for r in conn.execute(
                "SELECT descuento_pct FROM kit_componentes WHERE equipo_id = %s", (combo_id,)
            ).fetchall()
        ]
        assert len(descuentos) == 2
        assert all(abs(d - 25.0) < 0.01 for d in descuentos)

        # 266/327 ya NO existen.
        restantes = conn.execute(
            "SELECT id FROM equipos WHERE id IN (%s,%s)", (LEGACY_ESPACIO_ID, LEGACY_PROMO_ID)
        ).fetchall()
        assert restantes == []

        # Pedido puro SOLO espacio → retagueado + ítem re-apuntado al centinela.
        assert conn.execute(
            "SELECT tipo FROM alquileres WHERE id = %s", (P_SOLO_ESPACIO,)
        ).fetchone()["tipo"] == "estudio"
        assert conn.execute(
            "SELECT equipo_id FROM alquiler_items WHERE pedido_id = %s", (P_SOLO_ESPACIO,)
        ).fetchone()["equipo_id"] == centinela_id

        # Pedido puro SOLO promo → retagueado + ítem re-apuntado al combo.
        assert conn.execute(
            "SELECT tipo FROM alquileres WHERE id = %s", (P_SOLO_PROMO,)
        ).fetchone()["tipo"] == "estudio"
        assert conn.execute(
            "SELECT equipo_id FROM alquiler_items WHERE pedido_id = %s", (P_SOLO_PROMO,)
        ).fetchone()["equipo_id"] == combo_id

        # Pedido puro COMBINADO (327+266 juntos) → retagueado, AMBOS ítems re-apuntados.
        combinado_tipo = conn.execute(
            "SELECT tipo FROM alquileres WHERE id = %s", (P_COMBINADO,)
        ).fetchone()["tipo"]
        assert combinado_tipo == "estudio"
        combinado_equipos = {
            r["equipo_id"] for r in conn.execute(
                "SELECT equipo_id FROM alquiler_items WHERE pedido_id = %s", (P_COMBINADO,)
            ).fetchall()
        }
        assert combinado_equipos == {centinela_id, combo_id}

        # Pedido MIXTO → sigue 'diaria' (NO se retaguea), pero el ítem legacy
        # se re-apunta igual al centinela real.
        assert conn.execute(
            "SELECT tipo FROM alquileres WHERE id = %s", (P_MIXTO,)
        ).fetchone()["tipo"] == "diaria"
        mixto_equipos = {
            r["equipo_id"] for r in conn.execute(
                "SELECT equipo_id FROM alquiler_items WHERE pedido_id = %s", (P_MIXTO,)
            ).fetchall()
        }
        assert mixto_equipos == {centinela_id, EQ_OTRO_REAL}
    finally:
        conn.close()

    # Idempotencia: correr upgrade de nuevo (ya no existen 266/327 → no-op
    # inmediato por la guarda `if not existe: return`) no rompe nada.
    command.upgrade(_alembic_config(), "head")


def test_unificar_legacy_respeta_componente_vivo_de_otro_combo(clean_db):
    """Si 266 es componente de OTRO combo real (kit_componentes.componente_id),
    no se borra — se deja la fila para no arrastrar en silencio el kit de ese
    otro producto. 327 (sin ese conflicto) sí se borra normalmente."""
    from alembic import command
    from database import init_db, get_db

    init_db()
    conn = get_db()
    try:
        _setup_comun(conn)
        # Otro combo real que usa 266 como uno de sus componentes.
        conn.execute(
            "INSERT INTO equipos (id, nombre, tipo, cantidad, dueno) VALUES (%s,'Combo ajeno','combo',1,'Rental')",
            (EQ_COMPONENTE_AJENO,),
        )
        conn.execute(
            "INSERT INTO kit_componentes (equipo_id, componente_id, cantidad, esencial) VALUES (%s,%s,1,TRUE)",
            (EQ_COMPONENTE_AJENO, LEGACY_PROMO_ID),
        )
        conn.commit()
    finally:
        conn.close()

    command.upgrade(_alembic_config(), "head")

    conn = get_db()
    try:
        # 266 sigue vivo (es componente de otro combo) — pero su historial YA
        # se re-atribuyó igual (el guard solo afecta el DELETE, no el paso 2).
        assert conn.execute(
            "SELECT id FROM equipos WHERE id = %s", (LEGACY_PROMO_ID,)
        ).fetchone() is not None
        assert conn.execute(
            "SELECT tipo FROM alquileres WHERE id = %s", (P_SOLO_PROMO,)
        ).fetchone()["tipo"] == "estudio"
        combo_id = conn.execute(
            "SELECT promo_combo_id FROM estudio WHERE id = 1"
        ).fetchone()["promo_combo_id"]
        assert conn.execute(
            "SELECT equipo_id FROM alquiler_items WHERE pedido_id = %s", (P_SOLO_PROMO,)
        ).fetchone()["equipo_id"] == combo_id
        # El combo ajeno sigue teniendo su componente intacto.
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM kit_componentes WHERE equipo_id = %s AND componente_id = %s",
            (EQ_COMPONENTE_AJENO, LEGACY_PROMO_ID),
        ).fetchone()["n"] == 1

        # 327 (sin ese conflicto) sí se borró normalmente.
        assert conn.execute(
            "SELECT id FROM equipos WHERE id = %s", (LEGACY_ESPACIO_ID,)
        ).fetchone() is None
    finally:
        conn.close()


def test_unificar_legacy_sin_pack_no_rompe_ni_borra_promo_sin_re_atribuir(clean_db):
    """Si el pack curado está vacío o sin precio, el combo NUNCA se crea →
    `alquiler_items` de 266 no tiene a dónde re-apuntar y se queda como está.
    El DELETE de 266 tiene que SALTEARSE (si no, `alquiler_items.equipo_id`
    — la única FK sin ON DELETE — reventaría el deploy entero). 327 (el
    espacio, que no depende del pack) sí se re-atribuye y se borra normal."""
    from alembic import command
    from database import init_db, get_db

    init_db()
    conn = get_db()
    try:
        _equipo(conn, LEGACY_ESPACIO_ID, "Rambla Estudio", precio_jornada=50_000)
        _equipo(conn, LEGACY_PROMO_ID, "Estudio Equipos Promo", precio_jornada=100_000)
        # Sin estudio_pack_equipos, sin pack_precio → no hay con qué crear el combo.
        _pedido(conn, P_SOLO_ESPACIO, "diaria", 50_000)
        _item(conn, P_SOLO_ESPACIO, LEGACY_ESPACIO_ID, 50_000)
        _pedido(conn, P_SOLO_PROMO, "diaria", 100_000)
        _item(conn, P_SOLO_PROMO, LEGACY_PROMO_ID, 100_000)
        centinela_id = conn.execute(
            "SELECT equipo_id FROM estudio WHERE id = 1"
        ).fetchone()["equipo_id"]
        conn.commit()
    finally:
        conn.close()

    command.upgrade(_alembic_config(), "head")

    conn = get_db()
    try:
        assert conn.execute(
            "SELECT promo_combo_id FROM estudio WHERE id = 1"
        ).fetchone()["promo_combo_id"] is None

        # 266 sigue vivo, su ítem SIGUE apuntándole a él (no había a dónde
        # re-apuntar) y su pedido sigue 'diaria' (no se retagueó sin combo).
        assert conn.execute(
            "SELECT id FROM equipos WHERE id = %s", (LEGACY_PROMO_ID,)
        ).fetchone() is not None
        assert conn.execute(
            "SELECT equipo_id FROM alquiler_items WHERE pedido_id = %s", (P_SOLO_PROMO,)
        ).fetchone()["equipo_id"] == LEGACY_PROMO_ID
        assert conn.execute(
            "SELECT tipo FROM alquileres WHERE id = %s", (P_SOLO_PROMO,)
        ).fetchone()["tipo"] == "diaria"

        # 327 (el espacio) no depende del pack — se re-atribuye y se borra normal.
        assert conn.execute(
            "SELECT id FROM equipos WHERE id = %s", (LEGACY_ESPACIO_ID,)
        ).fetchone() is None
        assert conn.execute(
            "SELECT equipo_id FROM alquiler_items WHERE pedido_id = %s", (P_SOLO_ESPACIO,)
        ).fetchone()["equipo_id"] == centinela_id
        assert conn.execute(
            "SELECT tipo FROM alquileres WHERE id = %s", (P_SOLO_ESPACIO,)
        ).fetchone()["tipo"] == "estudio"
    finally:
        conn.close()
