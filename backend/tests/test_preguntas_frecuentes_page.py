"""Tests de /preguntas-frecuentes: FAQPage JSON-LD server-side.

Antes esta ruta dependía 100% de un fetch client-side a /api/settings/
faq_json (o el fallback hardcodeado de data/faq.ts, solo client-side) para
mostrar el FAQPage — invisible para bots sin JS. Ahora, si el setting
`faq_json` está configurado, se inyecta server-side (mismo patrón que
equipo/categoria/escuelas/estudio). Si no está configurado (el caso de HOY
en prod), no inyecta nada — no duplica el fallback hardcodeado del front.
"""
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

STATIC_INDEX = """<!doctype html>
<html><head>
<title>Rambla</title>
<meta property="og:title" content="OLD TITLE" />
</head><body></body></html>"""


def _make_app():
    import main
    return TestClient(main.app)


def test_preguntas_frecuentes_inyecta_faqpage_si_setting_configurado(tmp_path):
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    faq_json = (
        '[{"title": "Reservas", "items": '
        '[{"q": "¿Cómo reservo?", "a": "Elegís equipo y fechas."}, '
        '{"q": "", "a": "se filtra por vacía"}]}]'
    )
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {"value": faq_json}
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
    ):
        client = _make_app()
        resp = client.get("/preguntas-frecuentes")

    assert resp.status_code == 200
    body = resp.text
    assert '"@type": "FAQPage"' in body
    assert "¿Cómo reservo?" in body
    assert "se filtra por vacía" not in body
    assert 'data-ssr-jsonld="1"' in body


def test_preguntas_frecuentes_sin_setting_no_inyecta(tmp_path):
    """Sin el setting configurado (estado real de prod hoy), sirve el index
    plano — el fallback hardcodeado del front sigue mostrando la FAQ vía JS,
    pero no se duplica ese contenido acá."""
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
    ):
        client = _make_app()
        resp = client.get("/preguntas-frecuentes")

    assert resp.status_code == 200
    assert "OLD TITLE" in resp.text
    assert "FAQPage" not in resp.text


def test_preguntas_frecuentes_setting_json_invalido_no_inyecta(tmp_path):
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {"value": "esto no es json"}
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
    ):
        client = _make_app()
        resp = client.get("/preguntas-frecuentes")

    assert resp.status_code == 200
    assert "FAQPage" not in resp.text


def test_preguntas_frecuentes_fallback_ante_error_bd(tmp_path):
    index = tmp_path / "index.html"
    index.write_text(STATIC_INDEX)

    conn = MagicMock()
    conn.execute.side_effect = RuntimeError("BD caída")
    conn.close = MagicMock()

    with (
        patch("main.FRONT_NEW", tmp_path),
        patch("main.get_db", return_value=conn),
    ):
        client = _make_app()
        resp = client.get("/preguntas-frecuentes")

    assert resp.status_code == 200
    assert "OLD TITLE" in resp.text


def test_preguntas_frecuentes_fallback_sin_index(tmp_path):
    with patch("main.FRONT_NEW", tmp_path):
        client = _make_app()
        resp = client.get("/preguntas-frecuentes")
    assert resp.status_code in (200, 404, 503)
