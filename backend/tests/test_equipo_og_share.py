"""La ruta /equipo/{id_or_slug} acepta slug-id y sirve OG por equipo.

Regresión: la ruta exigía `id: int`, así que la URL slug-id que genera el botón
Compartir (`/equipo/red-camara-...-331`) tiraba 422 (int_parsing) → el link no
abría y el crawler de WhatsApp no llegaba al HTML (sin og:image). Ver captura en
el reporte del dueño.
"""

from fastapi.testclient import TestClient

import main


_SAMPLE_HTML = """<!doctype html><html><head>
<title>Rambla Rental — default</title>
<meta property="og:title" content="Rambla Rental — default" />
<meta property="og:description" content="desc default" />
<meta property="og:image" content="https://rambla.house/icon-512.png" />
<meta property="og:url" content="https://rambla.house/" />
<meta name="twitter:title" content="Rambla Rental — default" />
<meta name="twitter:description" content="desc default" />
<meta name="twitter:image" content="https://rambla.house/icon-512.png" />
</head><body><div id="root"></div></body></html>"""


def test_inject_og_meta_reemplaza_tags():
    out = main._inject_og_meta(
        _SAMPLE_HTML,
        title="Cámara RED KOMODO-X — Rambla Rental",
        description="Cámara de cine digital Super35.",
        image="https://cdn.example.com/komodo.webp",
        url="https://rambla.house/equipo/red-komodo-x-331",
    )
    # OG por equipo, no el default
    assert '<meta property="og:title" content="Cámara RED KOMODO-X — Rambla Rental" />' in out
    assert '<meta property="og:image" content="https://cdn.example.com/komodo.webp" />' in out
    assert '<meta property="og:url" content="https://rambla.house/equipo/red-komodo-x-331" />' in out
    assert "Cámara de cine digital Super35." in out
    # Twitter también
    assert '<meta name="twitter:image" content="https://cdn.example.com/komodo.webp" />' in out
    # <title> del tab
    assert "<title>Cámara RED KOMODO-X — Rambla Rental</title>" in out
    # No quedó el default
    assert "icon-512.png" not in out


def test_inject_og_meta_escapa_html():
    """Comillas y símbolos se escapan para no romper el atributo HTML."""
    out = main._inject_og_meta(
        _SAMPLE_HTML,
        title='Lente 24" macro',
        description="a & b < c",
        image="https://x/y.webp",
        url="https://x/equipo/z-1",
    )
    assert "&quot;" in out  # la comilla del título se escapó
    assert "&amp;" in out and "&lt;" in out  # & y < de la descripción


def test_ruta_equipo_acepta_slug_sin_422():
    """La URL slug-id no debe tirar 422 (int_parsing) como antes."""
    client = TestClient(main.app)
    resp = client.get("/equipo/red-camara-red-komodo-x-montura-rf-super-35-331")
    # Lo crítico: NO es 422. Según haya build de front o no, será 200 (HTML) o
    # 503 (frontend not built en CI) — ambos prueban que el slug fue aceptado.
    assert resp.status_code != 422


def test_inject_json_ld_marca_los_scripts_como_ssr():
    """`data-ssr-jsonld` distingue el JSON-LD server-injectado del estático
    (WebSite/LocalBusiness en index.html, sin equivalente client-side): sin el
    marker, `main.tsx` no puede barrerlo antes de que la ruta cliente
    (equipo/escuelas/categoria) vuelva a declarar el mismo schema — quedaban
    duplicados post-hidratación (mismo bug de clase que title/OG)."""
    out = main._inject_json_ld(
        _SAMPLE_HTML,
        {"@type": "Product", "name": "Cámara RED"},
        {"@type": "BreadcrumbList"},
    )
    assert out.count('data-ssr-jsonld="1"') == 2
    assert '"@type": "Product"' in out
    assert '"@type": "BreadcrumbList"' in out


def test_set_og_image_home_reemplaza_solo_la_imagen():
    """La home inyecta el og:image configurado (og_image_url) para crawlers,
    sin tocar el resto del <head>."""
    out = main._set_og_image(_SAMPLE_HTML, "https://cdn.example.com/branding/og.jpg?v=9")
    assert '<meta property="og:image" content="https://cdn.example.com/branding/og.jpg?v=9" />' in out
    assert '<meta name="twitter:image" content="https://cdn.example.com/branding/og.jpg?v=9" />' in out
    assert "icon-512.png" not in out  # reemplazó el default
    # No tocó título ni descripción (la home ya los trae bien en el index estático).
    assert '<meta property="og:title" content="Rambla Rental — default" />' in out
    assert '<meta property="og:description" content="desc default" />' in out
