"""Tests de F5: OG dinámico para /estudio y /workshops/{slug}.

- /estudio inyecta og:title, og:description, og:image desde la BD
- /workshops/{slug} inyecta OG con nombre + instructor + foto
- Fallback a index plano ante errores de BD o taller inexistente
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


# ── Estudio ───────────────────────────────────────────────────────────────────

def test_estudio_og_inyecta_titulo_y_desc(tmp_path, monkeypatch):
    """GET /estudio → OG con el nombre y descripción del estudio."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    fake_cfg = {"nombre": "El Estudio", "tagline": "", "descripcion": "Estudio profesional en MdP"}
    fake_foto = {"img_url": "https://cdn.example/foto.jpg"}

    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = [fake_cfg, fake_foto]
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
        patch("main.SITE_URL", "https://rambla.house"),
    ):
        client = _make_app()
        resp = client.get("/estudio")

    assert resp.status_code == 200
    body = resp.text
    assert "El Estudio" in body
    assert "Estudio profesional en MdP" in body
    assert "https://cdn.example/foto.jpg" in body


def test_estudio_og_fallback_sin_descripcion(tmp_path, monkeypatch):
    """Si descripcion está vacía, cae al texto por defecto de Rambla."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = [
        {"nombre": "El Estudio", "tagline": "", "descripcion": ""},
        {"img_url": "https://cdn.example/foto.jpg"},
    ]
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
        patch("main.SITE_URL", "https://rambla.house"),
    ):
        client = _make_app()
        resp = client.get("/estudio")

    assert resp.status_code == 200
    assert "Mar del Plata" in resp.text


def test_estudio_og_fallback_sin_index(tmp_path):
    """Si no existe index.html, devuelve algo (no 500)."""
    with patch("main.FRONT_NEW", tmp_path):
        client = _make_app()
        resp = client.get("/estudio")
    assert resp.status_code in (200, 404, 503)


# ── Talleres ──────────────────────────────────────────────────────────────────

def test_workshop_og_inyecta_nombre_e_instructor(tmp_path):
    """GET /workshops/{slug} → OG con nombre del taller e instructor."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    fake_taller = {
        "nombre": "Dirección de Arte",
        "descripcion": "El taller más copado del mundo",
        "taller_id": 1,
        "fecha_inicio": None,
        "fecha_fin": None,
        "precio_total": None,
    }
    fake_instructor = {
        "nombre": "Juana García",
        "foto_url": "https://cdn.example/instructor.jpg",
        "foto_media_id": None,
    }

    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = [fake_taller, fake_instructor]
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
        patch("main.SITE_URL", "https://rambla.house"),
    ):
        client = _make_app()
        resp = client.get("/workshops/direccion-de-arte")

    assert resp.status_code == 200
    body = resp.text
    assert "Dirección de Arte" in body
    assert "Juana García" in body
    assert "https://cdn.example/instructor.jpg" in body


def test_workshop_og_taller_inexistente(tmp_path):
    """Si el slug no existe, sirve index.html (no 404 ni 500)."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
        patch("main.SITE_URL", "https://rambla.house"),
    ):
        client = _make_app()
        resp = client.get("/workshops/taller-inexistente")

    assert resp.status_code == 200


def test_workshop_og_usa_media_variant_si_tiene_media_id(tmp_path):
    """Si instructor_media_id existe, usa la variante OG de media_variants."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    fake_taller = {
        "nombre": "Taller de Foto",
        "descripcion": "Aprende fotografía",
        "taller_id": 2,
        "fecha_inicio": None,
        "fecha_fin": None,
        "precio_total": None,
    }
    fake_instructor = {
        "nombre": "Pedro López",
        "foto_url": "https://cdn.example/fallback.jpg",
        "foto_media_id": 99,
    }
    fake_mv = {"url": "https://cdn.example/og-variant.jpg"}

    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = [fake_taller, fake_instructor, fake_mv]
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
        patch("main.SITE_URL", "https://rambla.house"),
    ):
        client = _make_app()
        resp = client.get("/workshops/taller-de-foto")

    assert resp.status_code == 200
    assert "https://cdn.example/og-variant.jpg" in resp.text


def test_workshop_og_fallback_ante_error_bd(tmp_path):
    """Si la BD falla, sirve index plano sin 500."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    conn = MagicMock()
    conn.execute.side_effect = RuntimeError("BD caída")
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
        patch("main.SITE_URL", "https://rambla.house"),
    ):
        client = _make_app()
        resp = client.get("/workshops/cualquier-slug")

    assert resp.status_code == 200
