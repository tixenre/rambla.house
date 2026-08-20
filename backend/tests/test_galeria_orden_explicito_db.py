"""Candado contra Postgres REAL: el `orden` explícito que manda el front
(posición de SELECCIÓN del archivo) tiene que ganar sobre el MAX(orden)+1
que el backend infería antes por orden de LLEGADA — bug real reportado por
el dueño ("las galerías de los talleres no se muestran en orden"), causado
por el upload concurrente (`UPLOAD_CONCURRENCY` en PhotoGallery): 3 subidas
en simultáneo, la que termina de procesarse primero (no la que el usuario
eligió primero) se quedaba con el primer lugar.

Mismo patrón en las 4 galerías (edición de taller, institución, estudio,
equipo) — un test por galería, mismo escenario: insertar la foto B con
`orden` EXPLÍCITO menor al de la foto A insertada ANTES, y confirmar que el
orden final refleja lo pedido (B primero), no el orden real de inserción.

OPT-IN y seguro por defecto (RESERVAS_DB_TEST=1 + DATABASE_URL a una base de
prueba). Ids altos + limpieza antes/después.
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

TALLER_ID = 9_850_002
INSTITUCION_ID = 9_850_002
EQUIPO_ID = 9_850_002
SLUG = "test-galeria-orden-zzq"


def test_edicion_fotos_orden_explicito_gana_sobre_orden_de_insercion():
    from database import get_db, init_db
    from routes.talleres import _get_edicion_fotos, _insert_edicion_foto

    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM edicion_fotos WHERE edicion_id = %s", (TALLER_ID,))
        conn.execute("DELETE FROM ediciones_taller WHERE id = %s", (TALLER_ID,))
        conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))
        conn.execute(
            "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
            (TALLER_ID, SLUG, SLUG, "Test Galería Orden"),
        )
        conn.execute(
            "INSERT INTO ediciones_taller (id, taller_id, numero_edicion, slug, "
            "fecha_inicio, fecha_fin) VALUES (%s, %s, 1, %s, '2099-01-01', '2099-01-01')",
            (TALLER_ID, TALLER_ID, SLUG + "-ed1"),
        )
        conn.commit()

        try:
            # Se sube "A" primero (orden real de inserción #1) pero el
            # usuario la había elegido SEGUNDA → orden explícito 1.
            _insert_edicion_foto(conn, TALLER_ID, "https://x/a.jpg", "a.jpg", orden=1)
            # Se sube "B" después (orden real de inserción #2) pero el
            # usuario la había elegido PRIMERA → orden explícito 0.
            _insert_edicion_foto(conn, TALLER_ID, "https://x/b.jpg", "b.jpg", orden=0)
            # "a.jpg" se auto-marcó `es_principal` por ser la primera subida
            # (`is_first`) — desmarcarla acá para que este test mida
            # puramente `orden`, no la prioridad de "principal" (que gana
            # aparte, ver `_get_edicion_fotos`/2026-08-20).
            conn.execute(
                "UPDATE edicion_fotos SET es_principal = FALSE WHERE edicion_id = %s",
                (TALLER_ID,),
            )

            fotos = _get_edicion_fotos(conn, TALLER_ID)
            # Sin el fix: MAX(orden)+1 hubiera dado a "A" orden=0 y a "B"
            # orden=1 (por INSERCIÓN), invirtiendo la selección real.
            assert [f["path"] for f in fotos] == ["b.jpg", "a.jpg"]
        finally:
            conn.execute("DELETE FROM edicion_fotos WHERE edicion_id = %s", (TALLER_ID,))
            conn.execute("DELETE FROM ediciones_taller WHERE id = %s", (TALLER_ID,))
            conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))
            conn.commit()


def test_edicion_fotos_sin_orden_explicito_cae_al_fallback_max_mas_uno():
    """Un caller que no manda `orden` (compat hacia atrás) sigue funcionando
    exactamente como antes — el fallback no rompió el caso sin orden."""
    from database import get_db, init_db
    from routes.talleres import _get_edicion_fotos, _insert_edicion_foto

    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM edicion_fotos WHERE edicion_id = %s", (TALLER_ID,))
        conn.execute("DELETE FROM ediciones_taller WHERE id = %s", (TALLER_ID,))
        conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))
        conn.execute(
            "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
            (TALLER_ID, SLUG, SLUG, "Test Galería Orden"),
        )
        conn.execute(
            "INSERT INTO ediciones_taller (id, taller_id, numero_edicion, slug, "
            "fecha_inicio, fecha_fin) VALUES (%s, %s, 1, %s, '2099-01-01', '2099-01-01')",
            (TALLER_ID, TALLER_ID, SLUG + "-ed1"),
        )
        conn.commit()

        try:
            _insert_edicion_foto(conn, TALLER_ID, "https://x/a.jpg", "a.jpg")
            _insert_edicion_foto(conn, TALLER_ID, "https://x/b.jpg", "b.jpg")
            fotos = _get_edicion_fotos(conn, TALLER_ID)
            assert [f["path"] for f in fotos] == ["a.jpg", "b.jpg"]
        finally:
            conn.execute("DELETE FROM edicion_fotos WHERE edicion_id = %s", (TALLER_ID,))
            conn.execute("DELETE FROM ediciones_taller WHERE id = %s", (TALLER_ID,))
            conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))
            conn.commit()


def test_institucion_fotos_orden_explicito_gana():
    from database import get_db, init_db
    from routes.talleres import _get_institucion_fotos, _insert_institucion_foto

    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM institucion_fotos WHERE institucion_id = %s", (INSTITUCION_ID,))
        conn.execute("DELETE FROM instituciones WHERE id = %s", (INSTITUCION_ID,))
        conn.execute(
            "INSERT INTO instituciones (id, slug, nombre) VALUES (%s, %s, %s)",
            (INSTITUCION_ID, SLUG, "Test Institución Orden"),
        )
        conn.commit()

        try:
            _insert_institucion_foto(conn, INSTITUCION_ID, "https://x/a.jpg", "a.jpg", orden=1)
            _insert_institucion_foto(conn, INSTITUCION_ID, "https://x/b.jpg", "b.jpg", orden=0)
            # Desmarcar "principal" (auto-asignada a la primera subida) — ver
            # comentario gemelo en el test de edición de taller.
            conn.execute(
                "UPDATE institucion_fotos SET es_principal = FALSE WHERE institucion_id = %s",
                (INSTITUCION_ID,),
            )
            fotos = _get_institucion_fotos(conn, INSTITUCION_ID)
            assert [f["path"] for f in fotos] == ["b.jpg", "a.jpg"]
        finally:
            conn.execute("DELETE FROM institucion_fotos WHERE institucion_id = %s", (INSTITUCION_ID,))
            conn.execute("DELETE FROM instituciones WHERE id = %s", (INSTITUCION_ID,))
            conn.commit()


def test_equipo_fotos_orden_explicito_gana():
    from database import get_db, init_db
    from routes.equipos.fotos import _get_equipo_fotos, _insert_equipo_foto

    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM equipo_fotos WHERE equipo_id = %s", (EQUIPO_ID,))
        conn.execute("DELETE FROM equipos WHERE id = %s", (EQUIPO_ID,))
        conn.execute(
            "INSERT INTO equipos (id, nombre, precio_jornada) VALUES (%s, %s, 1000)",
            (EQUIPO_ID, "Test Equipo Orden"),
        )
        conn.commit()

        try:
            _insert_equipo_foto(conn, EQUIPO_ID, "https://x/a.jpg", "a.jpg", orden=1)
            _insert_equipo_foto(conn, EQUIPO_ID, "https://x/b.jpg", "b.jpg", orden=0)
            # Desmarcar "principal" (auto-asignada a la primera subida) — ver
            # comentario gemelo en el test de edición de taller.
            conn.execute(
                "UPDATE equipo_fotos SET es_principal = FALSE WHERE equipo_id = %s",
                (EQUIPO_ID,),
            )
            fotos = _get_equipo_fotos(conn, EQUIPO_ID)
            assert [f["path"] for f in fotos] == ["b.jpg", "a.jpg"]
        finally:
            conn.execute("DELETE FROM equipo_fotos WHERE equipo_id = %s", (EQUIPO_ID,))
            conn.execute("DELETE FROM equipos WHERE id = %s", (EQUIPO_ID,))
            conn.commit()


def test_estudio_fotos_orden_explicito_gana():
    from database import get_db, init_db
    from routes.estudio import _get_fotos, _insert_foto

    init_db()
    with get_db() as conn:
        # Singleton (estudio_id=1) — limpiar solo las filas de prueba por path,
        # no la galería real del Estudio.
        conn.execute("DELETE FROM estudio_fotos WHERE path IN ('a.jpg', 'b.jpg')")
        conn.commit()

        try:
            _insert_foto(conn, "https://x/a.jpg", "a.jpg", orden=1)
            _insert_foto(conn, "https://x/b.jpg", "b.jpg", orden=0)
            # Desmarcar "principal" (auto-asignada a la primera subida) — ver
            # comentario gemelo en el test de edición de taller.
            conn.execute(
                "UPDATE estudio_fotos SET es_principal = FALSE WHERE path IN ('a.jpg', 'b.jpg')"
            )
            fotos = _get_fotos(conn)
            paths_de_prueba = [f["path"] for f in fotos if f["path"] in ("a.jpg", "b.jpg")]
            assert paths_de_prueba == ["b.jpg", "a.jpg"]
        finally:
            conn.execute("DELETE FROM estudio_fotos WHERE path IN ('a.jpg', 'b.jpg')")
            conn.commit()


# ── "Principal" gana sobre `orden` (bug real, 2026-08-20) ────────────────────
#
# El carrusel público (TallerGaleria/hero-photos) siempre pinta la foto
# marcada "principal" primero, sin importar su `orden` — pero el fetch del
# admin devolvía las filas ordenadas SOLO por `orden`, así que la grilla del
# back-office podía mostrar la "Principal" enterrada en el medio mientras el
# público la mostraba primera. Fix: `es_principal DESC` gana en el ORDER BY
# de las 4 galerías, mismo criterio en ambos lados.


def test_edicion_fotos_principal_gana_sobre_orden():
    from database import get_db, init_db
    from routes.talleres import _get_edicion_fotos, _insert_edicion_foto

    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM edicion_fotos WHERE edicion_id = %s", (TALLER_ID,))
        conn.execute("DELETE FROM ediciones_taller WHERE id = %s", (TALLER_ID,))
        conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))
        conn.execute(
            "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
            (TALLER_ID, SLUG, SLUG, "Test Galería Orden"),
        )
        conn.execute(
            "INSERT INTO ediciones_taller (id, taller_id, numero_edicion, slug, "
            "fecha_inicio, fecha_fin) VALUES (%s, %s, 1, %s, '2099-01-01', '2099-01-01')",
            (TALLER_ID, TALLER_ID, SLUG + "-ed1"),
        )
        conn.commit()

        try:
            # "a" primera por `orden` (0), "b" segunda (1) — pero "b" es la
            # marcada principal: tiene que salir primera igual.
            _insert_edicion_foto(conn, TALLER_ID, "https://x/a.jpg", "a.jpg", orden=0)
            _insert_edicion_foto(conn, TALLER_ID, "https://x/b.jpg", "b.jpg", orden=1)
            conn.execute(
                "UPDATE edicion_fotos SET es_principal = (path = 'b.jpg') "
                "WHERE edicion_id = %s",
                (TALLER_ID,),
            )
            fotos = _get_edicion_fotos(conn, TALLER_ID)
            assert [f["path"] for f in fotos] == ["b.jpg", "a.jpg"]
        finally:
            conn.execute("DELETE FROM edicion_fotos WHERE edicion_id = %s", (TALLER_ID,))
            conn.execute("DELETE FROM ediciones_taller WHERE id = %s", (TALLER_ID,))
            conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))
            conn.commit()


def test_institucion_fotos_principal_gana_sobre_orden():
    from database import get_db, init_db
    from routes.talleres import _get_institucion_fotos, _insert_institucion_foto

    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM institucion_fotos WHERE institucion_id = %s", (INSTITUCION_ID,))
        conn.execute("DELETE FROM instituciones WHERE id = %s", (INSTITUCION_ID,))
        conn.execute(
            "INSERT INTO instituciones (id, slug, nombre) VALUES (%s, %s, %s)",
            (INSTITUCION_ID, SLUG, "Test Institución Orden"),
        )
        conn.commit()

        try:
            _insert_institucion_foto(conn, INSTITUCION_ID, "https://x/a.jpg", "a.jpg", orden=0)
            _insert_institucion_foto(conn, INSTITUCION_ID, "https://x/b.jpg", "b.jpg", orden=1)
            conn.execute(
                "UPDATE institucion_fotos SET es_principal = (path = 'b.jpg') "
                "WHERE institucion_id = %s",
                (INSTITUCION_ID,),
            )
            fotos = _get_institucion_fotos(conn, INSTITUCION_ID)
            assert [f["path"] for f in fotos] == ["b.jpg", "a.jpg"]
        finally:
            conn.execute("DELETE FROM institucion_fotos WHERE institucion_id = %s", (INSTITUCION_ID,))
            conn.execute("DELETE FROM instituciones WHERE id = %s", (INSTITUCION_ID,))
            conn.commit()


def test_equipo_fotos_principal_gana_sobre_orden():
    from database import get_db, init_db
    from routes.equipos.fotos import _get_equipo_fotos, _insert_equipo_foto

    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM equipo_fotos WHERE equipo_id = %s", (EQUIPO_ID,))
        conn.execute("DELETE FROM equipos WHERE id = %s", (EQUIPO_ID,))
        conn.execute(
            "INSERT INTO equipos (id, nombre, precio_jornada) VALUES (%s, %s, 1000)",
            (EQUIPO_ID, "Test Equipo Orden"),
        )
        conn.commit()

        try:
            _insert_equipo_foto(conn, EQUIPO_ID, "https://x/a.jpg", "a.jpg", orden=0)
            _insert_equipo_foto(conn, EQUIPO_ID, "https://x/b.jpg", "b.jpg", orden=1)
            conn.execute(
                "UPDATE equipo_fotos SET es_principal = (path = 'b.jpg') WHERE equipo_id = %s",
                (EQUIPO_ID,),
            )
            fotos = _get_equipo_fotos(conn, EQUIPO_ID)
            assert [f["path"] for f in fotos] == ["b.jpg", "a.jpg"]
        finally:
            conn.execute("DELETE FROM equipo_fotos WHERE equipo_id = %s", (EQUIPO_ID,))
            conn.execute("DELETE FROM equipos WHERE id = %s", (EQUIPO_ID,))
            conn.commit()


def test_estudio_fotos_principal_gana_sobre_orden():
    from database import get_db, init_db
    from routes.estudio import _get_fotos, _insert_foto

    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM estudio_fotos WHERE path IN ('a.jpg', 'b.jpg')")
        conn.commit()

        try:
            _insert_foto(conn, "https://x/a.jpg", "a.jpg", orden=0)
            _insert_foto(conn, "https://x/b.jpg", "b.jpg", orden=1)
            conn.execute(
                "UPDATE estudio_fotos SET es_principal = (path = 'b.jpg') "
                "WHERE path IN ('a.jpg', 'b.jpg')"
            )
            fotos = _get_fotos(conn)
            paths_de_prueba = [f["path"] for f in fotos if f["path"] in ("a.jpg", "b.jpg")]
            assert paths_de_prueba == ["b.jpg", "a.jpg"]
        finally:
            conn.execute("DELETE FROM estudio_fotos WHERE path IN ('a.jpg', 'b.jpg')")
            conn.commit()
