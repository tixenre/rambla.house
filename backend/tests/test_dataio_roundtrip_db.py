"""#862 — round-trip de dataio (export → import → export) contra Postgres real.

El sistema dataio es bidireccional: `export_all` vuelca la DB a JSONs por clave
natural y `import_all` los reimporta por upsert. Este test verifica la propiedad
de inverso sobre la cadena marca → equipo:
  1. Se arma un equipo (con su marca) y se EXPORTA a un dir temporal.
  2. Se BORRA el equipo y se vuelve a IMPORTAR desde el JSON.
  3. El equipo queda restaurado y un segundo EXPORT es BYTE-IDÉNTICO al primero
     (export/import son inversos; el slug —clave natural, #922— sobrevive el
     viaje sin que el export tenga que auto-curarlo).

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py): se saltea
salvo `RESERVAS_DB_TEST=1` + `DATABASE_URL` a una base con 'test' en el nombre.
Trabaja sobre ids/nombres de prueba y limpia al terminar.
"""
import os
import tempfile
from pathlib import Path
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

EID = 9_600_001
MARCA = "MarcaRoundtripTest"
SLUG = "marcaroundtriptest-rt900"
COSTO_COMPRA = 850_000


def _limpiar(conn):
    conn.execute("DELETE FROM equipos WHERE id = %s OR slug = %s", (EID, SLUG))
    conn.execute("DELETE FROM marcas WHERE nombre = %s", (MARCA,))


@pytest.fixture
def equipo_con_marca():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        brand_id = conn.insert_returning("INSERT INTO marcas (nombre) VALUES (%s)", (MARCA,))
        conn.execute(
            "INSERT INTO equipos (id, nombre, brand_id, modelo, cantidad, slug, costo_compra) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (EID, "Equipo Roundtrip", brand_id, "RT900", 2, SLUG, COSTO_COMPRA),
        )
        conn.commit()
    finally:
        conn.close()

    yield

    conn = get_db()
    try:
        _limpiar(conn)
        conn.commit()
    finally:
        conn.close()


def _export_equipos_json(conn, out_dir: Path) -> str:
    from dataio import orchestrator
    from dataio.paths import entity_path

    orchestrator.export_all(conn, out_dir, only=["marcas", "equipos"])
    return entity_path("equipos", out_dir).read_text(encoding="utf-8")


def test_export_import_export_es_estable(equipo_con_marca):
    from database import get_db
    from dataio import orchestrator

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)

        conn = get_db()
        try:
            primero = _export_equipos_json(conn, out)
            assert SLUG in primero, "el equipo de prueba debe estar en el export"

            # Borrar el equipo y reimportar desde el JSON exportado.
            conn.execute("DELETE FROM equipos WHERE id = %s", (EID,))
            conn.commit()
            assert conn.execute(
                "SELECT COUNT(*) AS n FROM equipos WHERE slug = %s", (SLUG,)
            ).fetchone()["n"] == 0

            orchestrator.import_all(conn, out, only=["marcas", "equipos"])
            conn.commit()
        finally:
            conn.close()

        # El equipo volvió, con sus campos.
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT nombre, modelo, cantidad, costo_compra FROM equipos WHERE slug = %s", (SLUG,)
            ).fetchone()
            assert row is not None, "el import debe restaurar el equipo"
            assert row["nombre"] == "Equipo Roundtrip"
            assert row["modelo"] == "RT900"
            assert row["cantidad"] == 2
            # costo_compra (rentabilidad neta de Estadísticas) tiene que
            # sobrevivir el viaje export→import — no es obvio si no se prueba
            # explícito (a diferencia de nombre/modelo/cantidad, es un campo
            # nuevo que se puede perder en silencio si dataio no lo conoce).
            assert row["costo_compra"] == COSTO_COMPRA

            # Segundo export idéntico al primero (export/import = inversos).
            with tempfile.TemporaryDirectory() as tmp2:
                segundo = _export_equipos_json(conn, Path(tmp2))
            assert segundo == primero, "el round-trip debe ser estable (byte-idéntico)"
        finally:
            conn.close()
