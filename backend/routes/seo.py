"""
routes/seo.py — sitemap.xml dinámico para SEO.

Lista las URLs públicas que queremos que Google indexe:
- Home / catálogo
- Páginas estáticas (Estudio, FAQ)
- Detalle de cada equipo visible

NO incluye:
- /admin/* (info privada)
- /cliente/* (info privada)
- Equipos ocultos (visible=false)
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime

logger = logging.getLogger(__name__)

from config import SITE_URL, settings  # URL pública + is_production (fuente única)
from xml.sax.saxutils import escape

from fastapi import APIRouter, Response

from database import get_db, MARCA_SUBQUERY

router = APIRouter()

# Fuera de prod (dev/staging/preview/local) no queremos NADA indexado — Disallow: /
# global, sin Sitemap (no tiene sentido anunciar uno que no debe rastrearse). El
# `X-Robots-Tag: noindex` del middleware (main.py) es la capa que de verdad lo
# saca del índice; esto es la segunda capa, evita gastar crawl budget del bot.
_ROBOTS_NON_PROD = "User-agent: *\nDisallow: /\n"


@router.get("/robots.txt", include_in_schema=False)
def robots_txt():
    """robots.txt dinámico — antes un archivo estático en frontend/public/ (mismo
    contenido en TODO ambiente, incluido dev/staging). Ahora por-ambiente: solo
    prod anuncia el catálogo indexable + el sitemap; el resto bloquea todo."""
    if not settings.is_production:
        return Response(content=_ROBOTS_NON_PROD, media_type="text/plain")
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /equipo/\n"
        "Allow: /categoria/\n"
        "Allow: /estudio\n"
        "Allow: /escuelas/\n"
        "Allow: /preguntas-frecuentes\n"
        "\n"
        "# Bloquear back-office y portal cliente (info privada).\n"
        "Disallow: /admin\n"
        "Disallow: /admin/\n"
        "Disallow: /cliente\n"
        "Disallow: /cliente/\n"
        "Disallow: /api/\n"
        "\n"
        "# Sitemap dinámico generado por el backend.\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    return Response(content=body, media_type="text/plain")


def _build_equipo_slug(marca: str | None, nombre: str | None, equipo_id: int) -> str:
    """Construye el slug-id canónico para un equipo. Equivalente al helper
    frontend `buildEquipoSlug()` — mantener sincronizado.

    Ej: ("Sony", "FX3 Cuerpo", 47) → "sony-fx3-cuerpo-47"
    """
    text = f"{marca or ''} {nombre or ''}".strip()
    # Sacar acentos: NFD descompone, encode/decode quita los combining marks.
    normalized = unicodedata.normalize("NFD", text)
    no_accents = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", no_accents.lower()).strip("-")[:80]
    if not slug:
        return str(equipo_id)
    return f"{slug}-{equipo_id}"


def _build_categoria_slug(nombre: str | None) -> str:
    """Slugifica el nombre de una categoría. Equivalente al helper frontend
    `buildCategoriaSlug()` — mantener sincronizado.

    Ej: "Iluminación" → "iluminacion"
    """
    if not nombre:
        return ""
    normalized = unicodedata.normalize("NFD", nombre)
    no_accents = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", no_accents.lower()).strip("-")

@router.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    """Sitemap XML compatible con Google / Bing.

    Spec: https://www.sitemaps.org/protocol.html
    """
    today = datetime.utcnow().strftime("%Y-%m-%d")

    # Páginas estáticas con priority/changefreq.
    urls: list[dict] = [
        {"loc": f"{SITE_URL}/", "lastmod": today, "changefreq": "daily", "priority": "1.0"},
        {"loc": f"{SITE_URL}/rental", "lastmod": today, "changefreq": "daily", "priority": "0.9"},
        {"loc": f"{SITE_URL}/estudio", "lastmod": today, "changefreq": "monthly", "priority": "0.8"},
        {"loc": f"{SITE_URL}/escuelas", "lastmod": today, "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{SITE_URL}/preguntas-frecuentes", "lastmod": today, "changefreq": "monthly", "priority": "0.6"},
    ]

    # Detalle por equipo + páginas de categoría. Si la BD no está disponible,
    # devolvemos sitemap parcial con solo estáticas — Google reintenta.
    try:
        with get_db() as conn:
            equipos = conn.execute(f"""
                SELECT e.id, {MARCA_SUBQUERY}, e.nombre,
                       COALESCE(e.updated_at, e.created_at) AS lastmod
                FROM equipos e
                WHERE COALESCE(e.visible_catalogo, 1) != 0
                ORDER BY e.id
            """).fetchall()
            # Categorías visibles. Filtramos las que no tienen equipos para no
            # listar URLs con resultado vacío.
            categorias = conn.execute("""
                SELECT c.nombre
                FROM categorias c
                WHERE COALESCE(c.visible, true) = true
                  AND EXISTS (
                    SELECT 1 FROM equipo_categorias ec
                    JOIN equipos e ON e.id = ec.equipo_id
                    WHERE ec.categoria_id = c.id
                      AND COALESCE(e.visible_catalogo, 1) != 0
                  )
                ORDER BY c.nombre
            """).fetchall()
            # Workshops individuales — indexables por Google y agentes LLM.
            # `/escuelas/{slug}` resuelve contra `ediciones_taller.slug`, NO
            # `talleres.slug` (_get_edicion_row en routes/talleres.py): un
            # taller con más de una edición tiene un slug DISTINTO por
            # edición, y solo coinciden por construcción para la primera
            # (`slug_base`). Leer `talleres.slug` dejaba afuera del sitemap
            # cualquier edición #2+ y podía listar una edición ya vencida
            # (`activo=FALSE`) para siempre (bug 2026-08-20). Mismo filtro
            # que `GET /talleres` (routes/talleres.py::list_talleres, "una
            # card por edición") — fuente única de qué está públicamente vivo.
            talleres = conn.execute(
                """
                SELECT e.slug, e.updated_at
                FROM ediciones_taller e
                JOIN talleres t ON t.id = e.taller_id
                WHERE e.activo = TRUE AND t.activo = TRUE
                ORDER BY e.slug
                """
            ).fetchall()

            # Hubs de institución (/escuelas/instituciones/{slug}) — indexables
            # (main.py::institucion_page arma OG/JSON-LD dedicado) pero no
            # tenían entrada en el sitemap hasta ahora.
            instituciones = conn.execute(
                "SELECT slug, updated_at FROM instituciones ORDER BY slug"
            ).fetchall()

        for r in equipos:
            lastmod_raw = r["lastmod"]
            lastmod = (
                lastmod_raw.strftime("%Y-%m-%d")
                if hasattr(lastmod_raw, "strftime")
                else today
            )
            slug = _build_equipo_slug(r["marca"], r["nombre"], r["id"])
            urls.append({
                "loc": f"{SITE_URL}/equipo/{slug}",
                "lastmod": lastmod,
                "changefreq": "weekly",
                "priority": "0.7",
            })

        # URLs de categoría — landings de tráfico orgánico
        # ("alquiler lentes Mar del Plata" → /categoria/lentes).
        for r in categorias:
            cat_slug = _build_categoria_slug(r["nombre"])
            if not cat_slug:
                continue
            urls.append({
                "loc": f"{SITE_URL}/categoria/{cat_slug}",
                "lastmod": today,
                "changefreq": "weekly",
                "priority": "0.8",
            })

        for r in talleres:
            edicion_slug = (r["slug"] or "").strip()
            if not edicion_slug:
                continue
            lastmod_raw = r["updated_at"]
            lastmod = (
                lastmod_raw.strftime("%Y-%m-%d") if hasattr(lastmod_raw, "strftime") else today
            )
            urls.append({
                "loc": f"{SITE_URL}/escuelas/{edicion_slug}",
                "lastmod": lastmod,
                "changefreq": "monthly",
                "priority": "0.7",
            })

        for r in instituciones:
            inst_slug = (r["slug"] or "").strip()
            if not inst_slug:
                continue
            lastmod_raw = r["updated_at"]
            lastmod = (
                lastmod_raw.strftime("%Y-%m-%d") if hasattr(lastmod_raw, "strftime") else today
            )
            urls.append({
                "loc": f"{SITE_URL}/escuelas/instituciones/{inst_slug}",
                "lastmod": lastmod,
                "changefreq": "monthly",
                "priority": "0.6",
            })
    except Exception:
        logger.error("sitemap: error al generar URLs de equipos y categorías desde BD", exc_info=True)

    # Construir XML.
    body = ['<?xml version="1.0" encoding="UTF-8"?>']
    body.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for u in urls:
        body.append("  <url>")
        body.append(f"    <loc>{escape(u['loc'])}</loc>")
        body.append(f"    <lastmod>{u['lastmod']}</lastmod>")
        body.append(f"    <changefreq>{u['changefreq']}</changefreq>")
        body.append(f"    <priority>{u['priority']}</priority>")
        body.append("  </url>")
    body.append("</urlset>")

    return Response(
        content="\n".join(body),
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},  # 1h cache
    )

