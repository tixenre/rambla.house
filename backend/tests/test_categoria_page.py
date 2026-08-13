"""Tests de /categoria/{slug}: OG + JSON-LD (CollectionPage/BreadcrumbList) server-side.

Antes esta ruta dependía 100% de fetches client-side (/api/categorias +
/api/equipos) para título/OG/JSON-LD Y el listado — invisible para bots que no
ejecutan JS. Mismo patrón que /estudio y /workshops/{slug} (test_f5).
"""
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

STATIC_INDEX = """<!doctype html>
<html><head>
<title>Rambla</title>
<meta property="og:title" content="OLD TITLE" />
<meta property="og:description" content="OLD DESC" />
<meta property="og:image" content="OLD IMG" />
<meta property="og:url" content="OLD URL" />
<meta name="twitter:title" content="OLD TITLE" />
<meta name="twitter:description" content="OLD DESC" />
<meta name="twitter:image" content="OLD IMG" />
</head><body></body></html>"""


def _make_app():
    import main
    return TestClient(main.app)


def _conn_con_categoria(categorias, equipos):
    """`conn.execute` se llama 2 veces en orden fijo: categorias (fetchall),
    después equipos de la categoria matcheada (fetchall)."""
    cur_categorias = MagicMock()
    cur_categorias.fetchall.return_value = categorias
    cur_equipos = MagicMock()
    cur_equipos.fetchall.return_value = equipos
    conn = MagicMock()
    conn.execute.side_effect = [cur_categorias, cur_equipos]
    conn.close = MagicMock()
    return conn


def test_categoria_page_inyecta_titulo_og_y_jsonld(tmp_path):
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    categorias = [{"id": 5, "nombre": "Lentes"}]
    equipos = [
        {"id": 47, "marca": "Sony", "nombre": "FX3 Cuerpo", "nombre_publico": "Sony FX3"},
        {"id": 48, "marca": "Canon", "nombre": "24-70mm f/2.8", "nombre_publico": None},
    ]
    conn = _conn_con_categoria(categorias, equipos)

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
        patch("main.SITE_URL", "https://rambla.house"),
    ):
        client = _make_app()
        resp = client.get("/categoria/lentes")

    assert resp.status_code == 200
    body = resp.text
    assert "Alquiler de Lentes" in body
    assert "Más de 2 equipos disponibles" in body
    assert "OLD TITLE" not in body
    # JSON-LD server-injectado lleva el marker que main.tsx usa para barrerlo
    # antes de que la ruta cliente lo vuelva a declarar (evita duplicarlo
    # post-hidratación, ver `_inject_json_ld`).
    assert 'data-ssr-jsonld="1"' in body
    assert '"@type": "BreadcrumbList"' in body
    assert '"@type": "CollectionPage"' in body
    assert "sony-fx3-cuerpo-47" in body  # slug del ítem en el ItemList
    assert "Sony FX3" in body  # nombre_publico gana
    assert "Canon 24-70mm f/2.8" in body  # sin nombre_publico → marca + nombre


def test_categoria_page_query_de_equipos_excluye_soft_deleted(tmp_path):
    """Auditoría (supervisor, previo al PR dev→main): la query de equipos por
    categoría le faltaba `eliminado_at IS NULL` — el mismo filtro que ya usa
    `services/catalogo/proyeccion.py`. Un equipo borrado pero con
    `visible_catalogo=1` colgado podía seguir apareciendo en el JSON-LD que
    ve un crawler para esa categoría (nadie real lo ve, la query oficial del
    catálogo sí filtra bien — es otro camino)."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    conn = _conn_con_categoria([{"id": 5, "nombre": "Lentes"}], [])

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
    ):
        client = _make_app()
        client.get("/categoria/lentes")

    sql_equipos = conn.execute.call_args_list[1].args[0]
    assert "e.eliminado_at IS NULL" in sql_equipos


def test_categoria_page_slug_inexistente_cae_a_index_plano(tmp_path):
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    conn = _conn_con_categoria([{"id": 5, "nombre": "Lentes"}], [])

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
    ):
        client = _make_app()
        resp = client.get("/categoria/no-existe")

    assert resp.status_code == 200
    assert "OLD TITLE" in resp.text  # no tocado — el fallback es el index crudo
    assert "CollectionPage" not in resp.text


def test_categoria_page_fallback_ante_error_bd(tmp_path):
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    conn = MagicMock()
    conn.execute.side_effect = RuntimeError("boom")
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
    ):
        client = _make_app()
        resp = client.get("/categoria/lentes")

    assert resp.status_code == 200
    assert "OLD TITLE" in resp.text


def test_categoria_page_fallback_sin_index(tmp_path):
    with patch("main.FRONT_NEW", tmp_path):
        client = _make_app()
        resp = client.get("/categoria/lentes")
    assert resp.status_code in (200, 404, 503)
