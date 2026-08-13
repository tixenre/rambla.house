"""Fuera de prod (dev/staging/preview/local), el sitio no debe ser indexable:
robots.txt bloquea todo Y cada respuesta lleva X-Robots-Tag: noindex.

Antes robots.txt era un archivo estático (mismo contenido en TODO ambiente,
incluido dev/staging, público en dev-rambla.up.railway.app) — cualquier cosa
que un crawler encontrara ahí podía sumarse al índice como duplicado del
contenido real de rambla.house.
"""
from fastapi.testclient import TestClient

import config


def _set_is_production(monkeypatch, value: bool):
    monkeypatch.setattr(type(config.settings), "is_production", property(lambda self: value))


def _make_app():
    import main
    return TestClient(main.app)


def test_robots_txt_disallow_todo_fuera_de_prod(monkeypatch):
    _set_is_production(monkeypatch, False)
    client = _make_app()
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert "Disallow: /\n" in resp.text
    assert "Allow:" not in resp.text
    assert "Sitemap:" not in resp.text


def test_robots_txt_permisivo_en_prod(monkeypatch):
    _set_is_production(monkeypatch, True)
    client = _make_app()
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert "Allow: /equipo/" in resp.text
    assert "Allow: /categoria/" in resp.text
    assert "Sitemap: https://rambla.house/sitemap.xml" in resp.text


def test_x_robots_tag_noindex_fuera_de_prod(monkeypatch):
    _set_is_production(monkeypatch, False)
    client = _make_app()
    resp = client.get("/robots.txt")
    assert resp.headers.get("x-robots-tag") == "noindex, nofollow"


def test_x_robots_tag_ausente_en_prod(monkeypatch):
    _set_is_production(monkeypatch, True)
    client = _make_app()
    resp = client.get("/robots.txt")
    assert "x-robots-tag" not in resp.headers
