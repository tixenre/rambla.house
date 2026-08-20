"""Sitemap XML (routes/seo.py::sitemap) — candados contra Postgres REAL.

Bug 2026-08-20: el sitemap armaba `/escuelas/{slug}` leyendo `talleres.slug`
(el "concepto") en vez de `ediciones_taller.slug` (lo que resuelve la página
pública, `_get_edicion_row` en routes/talleres.py) — ambas columnas solo
coinciden por construcción para la primera edición de un taller
(`slug_base`). Un taller con una segunda edición nunca aparecía en el
sitemap, y una edición despublicada podía quedar listada para siempre.

OPT-IN y seguro por defecto (RESERVAS_DB_TEST=1 + DATABASE_URL a una base de
prueba).
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

TALLER_ID = 9_861_001
EDICION_1_ID = 9_861_101
EDICION_2_ID = 9_861_102
EDICION_INACTIVA_ID = 9_861_103
SLUG_BASE = "test-sitemap-zzq"
SLUG_ED1 = SLUG_BASE
SLUG_ED2 = SLUG_BASE + "-2"
SLUG_ED_INACTIVA = SLUG_BASE + "-vieja"
INSTITUCION_ID = 9_861_201
SLUG_INSTITUCION = "test-sitemap-institucion-zzq"


def _limpiar(conn):
    conn.execute(
        "DELETE FROM ediciones_taller WHERE id IN (%s, %s, %s)",
        (EDICION_1_ID, EDICION_2_ID, EDICION_INACTIVA_ID),
    )
    conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))
    conn.execute("DELETE FROM instituciones WHERE id = %s", (INSTITUCION_ID,))


@pytest.fixture
def conn():
    from database import get_db, init_db

    init_db()
    c = get_db()
    _limpiar(c)
    c.execute(
        "INSERT INTO talleres (id, slug, slug_base, nombre, activo) VALUES (%s, %s, %s, %s, TRUE)",
        (TALLER_ID, SLUG_BASE, SLUG_BASE, "Taller Test Sitemap"),
    )
    c.execute(
        "INSERT INTO ediciones_taller (id, taller_id, numero_edicion, slug, "
        "fecha_inicio, fecha_fin, activo) VALUES (%s, %s, 1, %s, '2020-01-01', '2020-01-02', TRUE)",
        (EDICION_1_ID, TALLER_ID, SLUG_ED1),
    )
    c.execute(
        "INSERT INTO ediciones_taller (id, taller_id, numero_edicion, slug, "
        "fecha_inicio, fecha_fin, activo) VALUES (%s, %s, 2, %s, '2026-09-01', '2026-10-02', TRUE)",
        (EDICION_2_ID, TALLER_ID, SLUG_ED2),
    )
    c.execute(
        "INSERT INTO ediciones_taller (id, taller_id, numero_edicion, slug, "
        "fecha_inicio, fecha_fin, activo) VALUES (%s, %s, 3, %s, '2019-01-01', '2019-01-02', FALSE)",
        (EDICION_INACTIVA_ID, TALLER_ID, SLUG_ED_INACTIVA),
    )
    c.execute(
        "INSERT INTO instituciones (id, nombre, slug) VALUES (%s, %s, %s)",
        (INSTITUCION_ID, "Institución Test Sitemap", SLUG_INSTITUCION),
    )
    c.commit()
    yield c
    _limpiar(c)
    c.commit()
    c.close()


def test_sitemap_lista_cada_edicion_activa_por_su_propio_slug(conn):
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app)
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    body = resp.text

    assert f"/escuelas/{SLUG_ED1}<" in body, "la primera edición (slug == slug_base) tiene que aparecer"
    assert f"/escuelas/{SLUG_ED2}<" in body, (
        "una SEGUNDA edición del mismo taller tiene su propio slug — "
        "leer talleres.slug (siempre == slug_base) la dejaba afuera"
    )


def test_sitemap_no_lista_una_edicion_despublicada(conn):
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app)
    resp = client.get("/sitemap.xml")
    assert f"/escuelas/{SLUG_ED_INACTIVA}<" not in resp.text


def test_sitemap_lista_el_hub_de_institucion(conn):
    from fastapi.testclient import TestClient
    import main

    client = TestClient(main.app)
    resp = client.get("/sitemap.xml")
    assert f"/escuelas/instituciones/{SLUG_INSTITUCION}<" in resp.text
