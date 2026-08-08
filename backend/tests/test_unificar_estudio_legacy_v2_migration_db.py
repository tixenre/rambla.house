"""Migración `unifestlgcy2` — corrige el bug de `unifestlegacy`: matchea los
dos equipos legacy del Estudio ("Rambla Estudio" / "Estudio Equipos Promo")
por NOMBRE en vez de id hardcodeado, para que funcione en cualquier ambiente
sin importar qué id tengan esas filas ahí. No crea combo nuevo — reusa
`estudio.promo_combo_id` si ya existe.

Escenario real: en producción, los dos equipos legacy tenían ids distintos
(156/157) a los que `unifestlegacy` tenía hardcodeados (327/266) — la
migración original no los encontró y quedaron vivos (encontrado por el
dueño post-deploy, #1322). Este test usa a propósito ids ARBITRARIOS (ni
327/266, ni 156/157) para probar exactamente ese caso.

Cubre:
- Pedido puro con SOLO el espacio → retagueado, ítem re-apuntado al centinela.
- Pedido puro con SOLO la promo (combo YA existente) → retagueado, ítem
  re-apuntado al combo.
- Pedido puro COMBINADO (los dos legacy juntos) → retagueado, ambos ítems
  re-apuntados (el caso que un chequeo de pureza por-separado no detectaría).
- Pedido MIXTO (legacy + otro equipo real) → NO se retaguea, el ítem legacy
  sí se re-apunta.
- Guarda: legacy componente vivo de otro combo → no se borra (pero el
  historial sí se re-atribuye).
- La promo SIN combo armado (`promo_combo_id IS NULL`) → esa mitad no se
  toca (ni re-apunta ni borra); el espacio sí se procesa normal.
- Sin match (0 filas con esos nombres) → no-op, no rompe.
- Match ambiguo (2+ filas con el mismo nombre) → esa mitad no se toca.

OPT-IN y SEGURO POR DEFECTO (mismo patrón que
test_unificar_estudio_legacy_migration_db.py): se saltea salvo
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

# Ids ARBITRARIOS a propósito — el bug real era justo que los ids no
# coincidían con lo hardcodeado en la migración vieja (327/266). Acá usamos
# otros cualquiera para probar que el match-por-nombre no depende de ids.
LEGACY_ESPACIO_ID = 9_305_001
LEGACY_PROMO_ID = 9_305_002
EQ_OTRO_REAL = 9_305_003
EQ_COMPONENTE_AJENO = 9_305_004
EQ_PACK_1 = 9_305_005
EQ_PACK_2 = 9_305_006

P_SOLO_ESPACIO = 9_305_101
P_SOLO_PROMO = 9_305_102
P_COMBINADO = 9_305_103
P_MIXTO = 9_305_104


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


def _armar_combo(conn):
    """Arma un combo YA EXISTENTE (mismo mecanismo que `unifestlegacy` §1,
    pero acá se corre ANTES de la migración nueva — que ya no lo crea)."""
    _equipo(conn, EQ_PACK_1, "Luz de pack 1", precio_jornada=40_000)
    _equipo(conn, EQ_PACK_2, "Luz de pack 2", precio_jornada=40_000)
    combo_id = conn.execute(
        "INSERT INTO equipos (nombre, tipo, cantidad, dueno, visible_catalogo, es_recurso_interno) "
        "VALUES ('Promo de equipos', 'combo', 9999, 'Rental', 0, FALSE) RETURNING id"
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO kit_componentes (equipo_id, componente_id, cantidad, esencial) VALUES (%s,%s,1,TRUE),(%s,%s,1,TRUE)",
        (combo_id, EQ_PACK_1, combo_id, EQ_PACK_2),
    )
    conn.execute("UPDATE estudio SET promo_combo_id = %s WHERE id = 1", (combo_id,))
    return combo_id


def test_unifica_ambos_por_nombre_con_ids_arbitrarios(clean_db):
    """Caso real completo: los dos legacy tienen ids que no coinciden con
    nada hardcodeado, el combo YA existe. Cubre puro-espacio, puro-promo,
    combinado y mixto."""
    from alembic import command
    from database import init_db, get_db

    init_db()
    conn = get_db()
    try:
        combo_id = _armar_combo(conn)
        _equipo(conn, LEGACY_ESPACIO_ID, "Rambla Estudio", dueno="Rental", precio_jornada=50_000)
        _equipo(conn, LEGACY_PROMO_ID, "Estudio Equipos Promo", dueno="Rental", precio_jornada=100_000)
        _equipo(conn, EQ_OTRO_REAL, "Cámara no relacionada", precio_jornada=30_000)

        _pedido(conn, P_SOLO_ESPACIO, "diaria", 50_000)
        _item(conn, P_SOLO_ESPACIO, LEGACY_ESPACIO_ID, 50_000)

        _pedido(conn, P_SOLO_PROMO, "diaria", 100_000)
        _item(conn, P_SOLO_PROMO, LEGACY_PROMO_ID, 100_000)

        _pedido(conn, P_COMBINADO, "diaria", 150_000)
        _item(conn, P_COMBINADO, LEGACY_ESPACIO_ID, 50_000)
        _item(conn, P_COMBINADO, LEGACY_PROMO_ID, 100_000)

        _pedido(conn, P_MIXTO, "diaria", 80_000)
        _item(conn, P_MIXTO, LEGACY_ESPACIO_ID, 50_000)
        _item(conn, P_MIXTO, EQ_OTRO_REAL, 30_000)

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
        # Los dos legacy ya no existen.
        restantes = conn.execute(
            "SELECT id FROM equipos WHERE id IN (%s,%s)", (LEGACY_ESPACIO_ID, LEGACY_PROMO_ID)
        ).fetchall()
        assert restantes == []

        # Puro espacio.
        assert conn.execute(
            "SELECT tipo FROM alquileres WHERE id = %s", (P_SOLO_ESPACIO,)
        ).fetchone()["tipo"] == "estudio"
        assert conn.execute(
            "SELECT equipo_id FROM alquiler_items WHERE pedido_id = %s", (P_SOLO_ESPACIO,)
        ).fetchone()["equipo_id"] == centinela_id

        # Puro promo → al combo existente.
        assert conn.execute(
            "SELECT tipo FROM alquileres WHERE id = %s", (P_SOLO_PROMO,)
        ).fetchone()["tipo"] == "estudio"
        assert conn.execute(
            "SELECT equipo_id FROM alquiler_items WHERE pedido_id = %s", (P_SOLO_PROMO,)
        ).fetchone()["equipo_id"] == combo_id

        # Combinado → retagueado, ambos re-apuntados.
        assert conn.execute(
            "SELECT tipo FROM alquileres WHERE id = %s", (P_COMBINADO,)
        ).fetchone()["tipo"] == "estudio"
        combinado_equipos = {
            r["equipo_id"] for r in conn.execute(
                "SELECT equipo_id FROM alquiler_items WHERE pedido_id = %s", (P_COMBINADO,)
            ).fetchall()
        }
        assert combinado_equipos == {centinela_id, combo_id}

        # Mixto → NO retagueado, ítem legacy sí re-apuntado.
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

    command.upgrade(_alembic_config(), "head")  # idempotencia


def test_promo_sin_combo_no_se_toca_pero_espacio_si(clean_db):
    """Si no hay combo armado todavía, la mitad de la promo se deja intacta
    (sin destino a dónde re-apuntar) — el espacio, que no depende del combo,
    se procesa normal."""
    from alembic import command
    from database import init_db, get_db

    init_db()
    conn = get_db()
    try:
        _equipo(conn, LEGACY_ESPACIO_ID, "Rambla Estudio", precio_jornada=50_000)
        _equipo(conn, LEGACY_PROMO_ID, "Estudio Equipos Promo", precio_jornada=100_000)
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
            "SELECT id FROM equipos WHERE id = %s", (LEGACY_PROMO_ID,)
        ).fetchone() is not None
        assert conn.execute(
            "SELECT equipo_id FROM alquiler_items WHERE pedido_id = %s", (P_SOLO_PROMO,)
        ).fetchone()["equipo_id"] == LEGACY_PROMO_ID
        assert conn.execute(
            "SELECT tipo FROM alquileres WHERE id = %s", (P_SOLO_PROMO,)
        ).fetchone()["tipo"] == "diaria"

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


def test_respeta_componente_vivo_de_otro_combo(clean_db):
    """Si un legacy es componente de OTRO combo real, no se borra — pero su
    historial sí se re-atribuye igual."""
    from alembic import command
    from database import init_db, get_db

    init_db()
    conn = get_db()
    try:
        combo_id = _armar_combo(conn)
        _equipo(conn, LEGACY_PROMO_ID, "Estudio Equipos Promo", precio_jornada=100_000)
        _pedido(conn, P_SOLO_PROMO, "diaria", 100_000)
        _item(conn, P_SOLO_PROMO, LEGACY_PROMO_ID, 100_000)
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
        assert conn.execute(
            "SELECT id FROM equipos WHERE id = %s", (LEGACY_PROMO_ID,)
        ).fetchone() is not None
        assert conn.execute(
            "SELECT tipo FROM alquileres WHERE id = %s", (P_SOLO_PROMO,)
        ).fetchone()["tipo"] == "estudio"
        assert conn.execute(
            "SELECT equipo_id FROM alquiler_items WHERE pedido_id = %s", (P_SOLO_PROMO,)
        ).fetchone()["equipo_id"] == combo_id
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM kit_componentes WHERE equipo_id = %s AND componente_id = %s",
            (EQ_COMPONENTE_AJENO, LEGACY_PROMO_ID),
        ).fetchone()["n"] == 1
    finally:
        conn.close()


def test_sin_match_no_rompe(clean_db):
    """Sin ningún equipo con esos nombres → no-op limpio."""
    from alembic import command
    from database import init_db

    init_db()
    command.upgrade(_alembic_config(), "head")


def test_match_ambiguo_no_adivina(clean_db):
    """Dos equipos "Rambla Estudio" (dato sucio) → esa mitad no se toca."""
    from alembic import command
    from database import init_db, get_db

    init_db()
    conn = get_db()
    try:
        _equipo(conn, LEGACY_ESPACIO_ID, "Rambla Estudio", precio_jornada=50_000)
        _equipo(conn, LEGACY_ESPACIO_ID + 1, "Rambla Estudio", precio_jornada=50_000)
        conn.commit()
    finally:
        conn.close()

    command.upgrade(_alembic_config(), "head")

    conn = get_db()
    try:
        restantes = conn.execute(
            "SELECT COUNT(*) AS n FROM equipos WHERE nombre = 'Rambla Estudio'"
        ).fetchone()["n"]
        assert restantes == 2
    finally:
        conn.close()
