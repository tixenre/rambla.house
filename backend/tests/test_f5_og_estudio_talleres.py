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

    fake_cfg = {
        "nombre": "El Estudio",
        "tagline": "",
        "descripcion": "Estudio profesional en MdP",
        "faq_json": None,
    }
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
        {"nombre": "El Estudio", "tagline": "", "descripcion": "", "faq_json": None},
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


def test_estudio_faqpage_inyectada_si_hay_faq_json(tmp_path):
    """Si `estudio.faq_json` tiene contenido, se inyecta un FAQPage server-side
    (mismas FAQ que ya muestra la página, editables desde el admin)."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    fake_cfg = {
        "nombre": "El Estudio",
        "tagline": "",
        "descripcion": "Estudio profesional en MdP",
        "faq_json": '[{"q": "¿Cuál es el mínimo?", "a": "3 horas."}]',
    }
    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = [
        fake_cfg,
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
    body = resp.text
    assert '"@type": "FAQPage"' in body
    assert "¿Cuál es el mínimo?" in body
    assert 'data-ssr-jsonld="1"' in body


def test_estudio_sin_faqpage_si_no_hay_faq_json(tmp_path):
    """Sin `faq_json` (o vacío), no se inyecta FAQPage — nada que estructurar."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    fake_cfg = {"nombre": "El Estudio", "tagline": "", "descripcion": "x", "faq_json": None}
    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = [fake_cfg, None]
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
        patch("main.SITE_URL", "https://rambla.house"),
    ):
        client = _make_app()
        resp = client.get("/estudio")

    assert resp.status_code == 200
    assert "FAQPage" not in resp.text


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
        "id": 1,
        "nombre": "Dirección de Arte",
        "descripcion": "El taller más copado del mundo",
        "taller_id": 1,
        "fecha_inicio": None,
        "fecha_fin": None,
        "precio_total": None,
        "direccion": "",
        "faqs": [],
    }
    fake_instructor = {
        "nombre": "Juana García",
        "foto_url": "https://cdn.example/instructor.jpg",
        "foto_media_id": None,
    }

    conn = MagicMock()
    # 3er valor = institucion_row (sin institución vinculada, cae al
    # instructor) — 4to = hero_row (fotos de la edición, sin fotos subidas
    # todavía, el preload se saltea — mismo caso real que un taller recién creado).
    conn.execute.return_value.fetchone.side_effect = [fake_taller, fake_instructor, None, None]
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


def test_workshop_og_institucion_gana_sobre_instructor(tmp_path):
    """Bug real reportado por el dueño: compartir el link de un taller
    co-presentado por una institución (ej. Filmar) mostraba "Taller X con
    Mila" (el instructor) — raro para un taller que, de hecho, es de la
    institución. Con una institución vinculada, el título/imagen del OG
    tienen que reflejarla a ELLA, no al instructor."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    fake_taller = {
        "id": 6,
        "nombre": "Taller de Rodaje",
        "descripcion": "",
        "taller_id": 6,
        "fecha_inicio": None,
        "fecha_fin": None,
        "precio_total": None,
        "direccion": "",
        "faqs": [],
    }
    fake_instructor = {
        "nombre": "Mila",
        "foto_url": "https://cdn.example/mila.jpg",
        "foto_media_id": None,
    }
    fake_institucion = {
        "id": 1,
        "nombre": "Filmar Escuela",
        "logo_url": "https://cdn.example/filmar-logo.svg",
    }
    fake_ins_foto = {"url": "https://cdn.example/filmar-destacada.jpg"}

    conn = MagicMock()
    # taller, instructor, institución, foto destacada de la institución, hero_row.
    conn.execute.return_value.fetchone.side_effect = [
        fake_taller, fake_instructor, fake_institucion, fake_ins_foto, None,
    ]
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
        patch("main.SITE_URL", "https://rambla.house"),
    ):
        client = _make_app()
        resp = client.get("/workshops/taller-de-rodaje")

    assert resp.status_code == 200
    body = resp.text
    assert "con Filmar Escuela" in body
    assert "https://cdn.example/filmar-destacada.jpg" in body
    assert "con Mila" not in body
    # El instructor real se sigue listando en el JSON-LD (SEO/datos
    # estructurados) aunque la institución gane el título de marketing.
    assert '"name": "Mila"' in body


def test_workshop_og_institucion_sin_foto_cae_al_logo(tmp_path):
    """Institución vinculada pero sin foto destacada en su galería propia —
    cae al logo (mismo orden de preferencia que `institucion_page`, el hub)."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    fake_taller = {
        "id": 7,
        "nombre": "Taller de Rodaje 2",
        "descripcion": "",
        "taller_id": 7,
        "fecha_inicio": None,
        "fecha_fin": None,
        "precio_total": None,
        "direccion": "",
        "faqs": [],
    }
    fake_institucion = {
        "id": 1,
        "nombre": "Filmar Escuela",
        "logo_url": "https://cdn.example/filmar-logo.svg",
    }

    conn = MagicMock()
    # taller, instructor=None, institución, foto destacada=None → cae al logo, hero_row.
    conn.execute.return_value.fetchone.side_effect = [
        fake_taller, None, fake_institucion, None, None,
    ]
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
        patch("main.SITE_URL", "https://rambla.house"),
    ):
        client = _make_app()
        resp = client.get("/workshops/taller-de-rodaje-2")

    assert resp.status_code == 200
    assert "https://cdn.example/filmar-logo.svg" in resp.text


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
        "id": 2,
        "nombre": "Taller de Foto",
        "descripcion": "Aprende fotografía",
        "taller_id": 2,
        "fecha_inicio": None,
        "fecha_fin": None,
        "precio_total": None,
        "direccion": "",
        "faqs": [],
    }
    fake_instructor = {
        "nombre": "Pedro López",
        "foto_url": "https://cdn.example/fallback.jpg",
        "foto_media_id": 99,
    }
    fake_mv = {"url": "https://cdn.example/og-variant.jpg"}

    conn = MagicMock()
    # 3er valor = institucion_row (sin institución) — 5to = hero_row (fotos
    # de la edición) — None = sin fotos subidas.
    conn.execute.return_value.fetchone.side_effect = [
        fake_taller, fake_instructor, None, fake_mv, None,
    ]
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


def test_workshop_faqpage_inyectada_junto_a_course_si_hay_faqs(tmp_path):
    """Si el taller tiene FAQs cargadas (FaqSection del admin), se inyecta un
    FAQPage AL LADO del Course schema — ninguno reemplaza al otro."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    fake_taller = {
        "id": 3,
        "nombre": "Taller con FAQ",
        "descripcion": "Tiene preguntas frecuentes",
        "taller_id": 3,
        "fecha_inicio": None,
        "fecha_fin": None,
        "precio_total": None,
        "direccion": "",
        "faqs": [
            {"pregunta": "¿Necesito experiencia previa?", "respuesta": "No, es para todo nivel."},
            {"pregunta": "", "respuesta": "se filtra por vacía"},
        ],
    }
    conn = MagicMock()
    # 3er None = institucion_row (sin institución vinculada) — 4to = hero_row.
    conn.execute.return_value.fetchone.side_effect = [fake_taller, None, None, None]
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
        patch("main.SITE_URL", "https://rambla.house"),
    ):
        client = _make_app()
        resp = client.get("/workshops/taller-con-faq")

    assert resp.status_code == 200
    body = resp.text
    assert '"@type": "Course"' in body
    assert '"@type": "FAQPage"' in body
    assert "¿Necesito experiencia previa?" in body
    assert "se filtra por vacía" not in body  # el par con pregunta vacía no entra


def test_workshop_sin_faqpage_si_no_hay_faqs(tmp_path):
    """Sin FAQs cargadas (el caso de HOY para los talleres reales), no se
    inyecta FAQPage — solo el Course schema, sin schema vacío."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    fake_taller = {
        "id": 4,
        "nombre": "Taller sin FAQ",
        "descripcion": "Todavía no cargó FAQs",
        "taller_id": 4,
        "fecha_inicio": None,
        "fecha_fin": None,
        "precio_total": None,
        "direccion": "",
        "faqs": [],
    }
    conn = MagicMock()
    # 3er None = institucion_row (sin institución vinculada) — 4to = hero_row.
    conn.execute.return_value.fetchone.side_effect = [fake_taller, None, None, None]
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
        patch("main.SITE_URL", "https://rambla.house"),
    ):
        client = _make_app()
        resp = client.get("/workshops/taller-sin-faq")

    assert resp.status_code == 200
    body = resp.text
    assert '"@type": "Course"' in body
    assert "FAQPage" not in body


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


def test_workshop_og_borrador_sin_bypass_filtra_por_activo(tmp_path):
    """Sin admin/bypass, la query de `_get_edicion_row` filtra `activo = TRUE`
    (mismo gate que `GET /talleres/{slug}` — un borrador no existe para el
    público, ni para el crawler de OG)."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    fake_taller = {
        "id": 5,
        "nombre": "Taller Sin Publicar", "descripcion": "En preparación",
        "taller_id": 5, "fecha_inicio": None, "fecha_fin": None, "precio_total": None,
        "direccion": "", "faqs": [],
    }
    conn = MagicMock()
    # 3er None = institucion_row (sin institución vinculada) — 4to = hero_row.
    conn.execute.return_value.fetchone.side_effect = [fake_taller, None, None, None]
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
        patch("main.SITE_URL", "https://rambla.house"),
        patch("auth.session.dev_bypass_enabled", return_value=False),
    ):
        client = _make_app()
        resp = client.get("/workshops/taller-sin-publicar")

    assert resp.status_code == 200
    sql = conn.execute.call_args_list[0].args[0]
    assert "e.activo = TRUE" in sql


def test_workshop_og_borrador_visible_con_dev_bypass(tmp_path):
    """Bug real (taller de Ariel Perissinotti, aún en borrador en `dev`):
    con `ADMIN_BYPASS_AUTH` (staging/local), la MISMA edición despublicada
    que ya ve el SPA (`GET /talleres/{slug}`, `incluir_borrador=es_admin`)
    tiene que ver también su propio OG — antes esta ruta filtraba
    `activo = TRUE` a mano, sin el bypass, y siempre caía al genérico."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    fake_taller = {
        "id": 5,
        "nombre": "Taller Sin Publicar", "descripcion": "En preparación",
        "taller_id": 5, "fecha_inicio": None, "fecha_fin": None, "precio_total": None,
        "direccion": "", "faqs": [],
    }
    fake_instructor = {
        "nombre": "Instructor Preview", "foto_url": "https://cdn.example/preview.jpg",
        "foto_media_id": None,
    }
    conn = MagicMock()
    # 3er None = institucion_row (sin institución vinculada) — 4to = hero_row.
    conn.execute.return_value.fetchone.side_effect = [fake_taller, fake_instructor, None, None]
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
        patch("main.SITE_URL", "https://rambla.house"),
        patch("auth.session.dev_bypass_enabled", return_value=True),
    ):
        client = _make_app()
        resp = client.get("/workshops/taller-sin-publicar")

    assert resp.status_code == 200
    sql = conn.execute.call_args_list[0].args[0]
    assert "e.activo = TRUE" not in sql
    body = resp.text
    assert "Taller Sin Publicar" in body
    assert "Instructor Preview" in body
