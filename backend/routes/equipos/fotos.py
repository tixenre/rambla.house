"""Fotos / media de un equipo (#501 fase a — extraído de `core`).

Cubre la superficie de medios del equipo: subida de fotos (archivo / URL), listado
/ borrado / reordenamiento, búsqueda-scraping de fotos, subida del HTML fuente y
diagnóstico de storage. Registra sus rutas en el router compartido del paquete
`routes.equipos`. Los helpers de R2 vienen de `services.media.storage` (no de
`core`); `core` mantiene su propio import de `_r2_config`/`_delete_from_r2` porque
`delete_equipo` también limpia el blob scrapeado. `UploadFotoFromUrlInput` lo
re-exporta el `__init__` del paquete (lo consume `test_ssrf`).
"""
import logging
import os
import re
import unicodedata
from typing import Optional

from fastapi import File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from auth.guards import require_admin
from database import get_db
from rate_limit import limiter, ADMIN_UPLOAD_LIMIT, ADMIN_WRITE_LIMIT
from routes.equipos.core import router

logger = logging.getLogger(__name__)

# /buscar-fotos: cuántos validamos y cuántos devolvemos. Este flow inspecciona
# más fuentes (Wikipedia, reviews, manufacturer) por eso el límite es mayor.
MAX_PHOTO_CANDIDATES_BUSCAR_VALIDATE = 24
MAX_PHOTO_CANDIDATES_BUSCAR_RETURN   = 16


@router.post("/admin/equipos/{id}/upload-html-source")
@limiter.limit(ADMIN_UPLOAD_LIMIT)
async def admin_upload_html_source(
    id: int,
    request: Request,
    file: UploadFile = File(...),
    categoria_hint: Optional[str] = None,
) -> dict:
    """Sube y persiste el HTML guardado de B&H, extrae specs y los devuelve.

    Guarda el blob en R2 (equipos/{id}/source.html), actualiza html_source_url
    en la BD y devuelve AutocompletarResult con los specs extraídos. Una segunda
    llamada sobreescribe el blob anterior (path determinístico sin timestamp).

    Args:
        id: ID del equipo al que se asocia el HTML.
        file: HTML guardado (Cmd+S → Webpage Complete).
        categoria_hint: categoría opcional para saltear auto-detección.

    Returns: {html_source_url, ...AutocompletarResult}
    """
    require_admin(request)

    with get_db() as conn:
        if not conn.execute("SELECT id FROM equipos WHERE id=%s", (id,)).fetchone():
            raise HTTPException(404, "Equipo no encontrado")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Archivo vacío")
    if len(content) > 5_000_000:
        raise HTTPException(400, "HTML demasiado grande (máx 5MB)")

    try:
        html_content = content.decode("utf-8", errors="replace")
    except Exception:
        raise HTTPException(400, "HTML inválido (no es UTF-8)")

    # Sniff mínimo (#1263): antes, cualquier byte que decodificara como UTF-8
    # se aceptaba sin chequear que fuera HTML de verdad.
    if not re.match(r"^\s*(<!doctype\s+html|<html)", html_content, re.IGNORECASE):
        raise HTTPException(400, "El archivo no parece ser HTML")

    path = f"equipos/{id}/source.html"
    with media_http():
        # text/plain (no text/html): este blob queda público en R2 y nada del
        # producto necesita que el navegador lo renderice vivo — solo se
        # re-lee server-side (re-extract-specs) para volver a parsear specs.
        # Servirlo como text/html permitía hostear HTML/JS arbitrario bajo el
        # dominio/CDN de Rambla con solo credenciales admin.
        html_source_url = _put_r2(path, content, "text/plain; charset=utf-8")

    with get_db() as conn:
        try:
            conn.execute(
                "UPDATE equipos SET html_source_url = %s, updated_at = CURRENT_TIMESTAMP WHERE id=%s",
                (html_source_url, id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    result = _extraer_specs_y_proponer(id, html_content, categoria_hint)

    return {"html_source_url": html_source_url, **result}


class EnriquecerFromHtmlBody(BaseModel):
    html: str
    categoria_hint: Optional[str] = None


@router.post("/admin/equipos/{id}/enriquecer-from-html")
@limiter.limit(ADMIN_UPLOAD_LIMIT)
def admin_enriquecer_from_html(id: int, body: EnriquecerFromHtmlBody, request: Request) -> dict:
    """Hermano JSON de upload-html-source (#1051 Stream B): mismo extractor
    (`extract_from_html`), mismo aprendizaje (#1203) — pero NO persiste nada
    en R2 ni toca `html_source_url`. Para cuando el HTML se consigue pegando
    texto (Chrome MCP, portapapeles) en vez de subir un archivo Cmd+S; el
    admin decide después si además quiere `upload-html-source` para dejarlo
    guardado.

    Returns: AutocompletarResult (mismo shape que upload-html-source, sin
    `html_source_url`).
    """
    require_admin(request)

    with get_db() as conn:
        if not conn.execute("SELECT id FROM equipos WHERE id=%s", (id,)).fetchone():
            raise HTTPException(404, "Equipo no encontrado")

    html_content = (body.html or "").strip()
    if not html_content:
        raise HTTPException(400, "HTML vacío")
    if len(html_content) > 5_000_000:
        raise HTTPException(400, "HTML demasiado grande (máx 5MB)")

    return _extraer_specs_y_proponer(id, html_content, body.categoria_hint)


@router.post("/admin/equipos/{id}/re-extract-specs")
@limiter.limit(ADMIN_UPLOAD_LIMIT)
def admin_re_extract_specs(id: int, request: Request, categoria_hint: Optional[str] = None) -> dict:
    """Re-corre la extracción sobre el HTML YA guardado del equipo, sin
    resubir el archivo (#1203) — típicamente después de agregar un spec
    nuevo al registry: los equipos con HTML guardado pueden traer su valor
    de un plumazo en vez de perseguir el archivo original de nuevo.

    Mismo motor (`extract_from_html`) que el upload — resultado idéntico al
    de resubir el mismo archivo. 404 si el equipo no tiene HTML guardado.

    Returns: mismo shape que upload-html-source (AutocompletarResult).
    """
    require_admin(request)

    with get_db() as conn:
        row = conn.execute(
            "SELECT html_source_url FROM equipos WHERE id=%s", (id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Equipo no encontrado")
        html_source_url = dict(row).get("html_source_url")
        if not html_source_url:
            raise HTTPException(404, "Este equipo no tiene HTML fuente guardado")

    path = f"equipos/{id}/source.html"
    with media_http():
        content = _get_r2(path)

    try:
        html_content = content.decode("utf-8", errors="replace")
    except Exception:
        raise HTTPException(400, "HTML guardado inválido (no es UTF-8)")

    result = _extraer_specs_y_proponer(id, html_content, categoria_hint)

    return {"html_source_url": html_source_url, **result}


def _extraer_specs_y_proponer(equipo_id: int, html_content: str, categoria_hint: Optional[str]) -> dict:
    """Corre `extract_from_html` + encola no-reconocidos (#1203). Fuente única
    para los 3 endpoints que procesan HTML de un equipo (upload-html-source,
    re-extract-specs, enriquecer-from-html) — mismo motor, mismo aprendizaje."""
    try:
        from services.specs_ingesta import extract_from_html
        result = extract_from_html(html_content, categoria_hint=categoria_hint)
    except Exception:
        logger.exception("Error extrayendo specs del HTML (equipo %d)", equipo_id)
        raise HTTPException(500, "No se pudo procesar el HTML")

    _proponer_no_reconocidos(equipo_id, result)
    return result


def _proponer_no_reconocidos(equipo_id: int, result: dict) -> None:
    """Encola en la cola de aprendizaje (#1203) los pares sin match de esta
    extracción, atribuidos al equipo. Best-effort: un fallo acá NO debe
    tirar abajo la subida del HTML (ya persistida) ni ocultar las specs
    reconocidas al frontend — solo se pierde la señal de aprendizaje de
    ESTA subida, recuperable resubiendo o con re-extract-specs."""
    unmatched = result.get("unmatched") or []
    if not unmatched:
        return
    try:
        from services.specs_ingesta import proponer_desde_equipo

        with get_db() as conn:
            proponer_desde_equipo(conn, equipo_id, result.get("categoria_sugerida"), unmatched)
            conn.commit()
    except Exception:
        logger.exception("No se pudo encolar specs no reconocidas (equipo %d)", equipo_id)



# ── Admin: búsqueda dedicada de fotos (separada del enriquecimiento) ─────────
#
# El enriquecedor general usa B&H/Adorama (mejor para specs) pero esos sitios
# bloquean hotlinking de fotos. Este endpoint busca específicamente en sitios
# con imágenes confiables (Wikipedia, manufacturer, sitios de review).

class BuscarFotosInput(BaseModel):
    nombre: Optional[str]      = None
    marca:  Optional[str]      = None
    modelo: Optional[str]      = None
    url:    Optional[str]      = None
    exclude: Optional[list[str]] = None  # URLs ya conocidas (para "buscar más")


@router.post("/admin/equipos/buscar-fotos")
@limiter.limit(ADMIN_UPLOAD_LIMIT)
def admin_buscar_fotos(payload: BuscarFotosInput, request: Request):
    """Busca fotos del equipo en fuentes optimizadas para imágenes (Wikipedia,
    manufacturer oficial, review sites). Devuelve lista validada de candidatos."""
    require_admin(request)

    import httpx
    import re
    import time as _time
    from services.media.errors import MediaError
    from services.media.security import _validate_ssrf_only

    # Timeout server-side (#1263): el AbortController de 30s del front solo
    # cancela la fetch del lado cliente — un handler sync de FastAPI sigue
    # corriendo aunque el admin ya haya visto "Timeout" y siguiera de largo.
    # Deadline propio, independiente de los timeouts por-llamada (Firecrawl
    # 45s, og:image 15s, validación HEAD 10s × hasta 24 candidatos).
    _deadline = _time.monotonic() + 25.0

    def _time_left() -> bool:
        return _time.monotonic() < _deadline

    FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
    if not FIRECRAWL_API_KEY:
        raise HTTPException(500, "FIRECRAWL_API_KEY no configurado")

    direct_url = (payload.url or "").strip() or None
    if direct_url and not direct_url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "URL inválida")
    # Anti-SSRF (#1263): direct_url es texto libre del admin — antes de este
    # fix, _og_images_from_html hacía un GET real desde el server sin chequear
    # IP privada/interna, a diferencia del endpoint hermano
    # upload-foto-from-url (que sí usa este mismo guard). Sin whitelist de
    # dominio (a propósito: acá puede venir cualquier sitio de producto, no
    # solo los hosts de _ALLOWED_PHOTO_HOSTS) — solo bloquea IP privada/
    # loopback/puerto raro, igual que los otros uploads manuales del admin.
    if direct_url:
        try:
            _validate_ssrf_only(direct_url)
        except MediaError as e:
            raise HTTPException(e.status, e.detail)

    query = " ".join(x for x in [payload.marca, payload.nombre, payload.modelo] if x).strip()
    if not direct_url and not query:
        raise HTTPException(400, "Falta nombre/marca o url")

    exclude_lc: set[str] = {(u or "").strip().lower() for u in (payload.exclude or [])}

    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type":  "application/json",
    }

    # Queries optimizados para fotos de producto con fondo blanco/neutro,
    # bien iluminadas — ideal para equipos audiovisuales de renta.
    # B&H primero: hero shots standarizados sobre fondo gris/blanco.
    PHOTO_QUERIES = [
        # 1. B&H Photo: fotos hero de producto, alta resolución, fondo neutro
        f"{query} product photo site:bhphotovideo.com",
        # 2. Adorama / KEH: misma categoría de retailers
        f"{query} product image (site:adorama.com OR site:keh.com)",
        # 3. Manufacturer oficial — página de producto
        f"{query} product page (site:canon.com OR site:usa.canon.com OR site:sony.com OR site:nikon.com OR "
        f"site:fujifilm.com OR site:panasonic.com OR site:blackmagicdesign.com OR site:aputure.com OR "
        f"site:godox.com OR site:rode.com OR site:sennheiser.com OR site:dji.com OR site:atomos.com OR "
        f"site:tilta.com OR site:smallrig.com OR site:saramonic.com OR site:zoom-na.com)",
        # 4. Wikipedia: fallback con imágenes limpias y sin paywall
        f"{query} (site:en.wikipedia.org OR site:commons.wikimedia.org OR site:es.wikipedia.org)",
    ]

    def _fc_search(q: str, client) -> list[str]:
        try:
            r = client.post(
                "https://api.firecrawl.dev/v2/search",
                headers=headers,
                json={"query": q, "limit": 3},
            )
        except httpx.HTTPError:
            return []
        if r.status_code != 200:
            return []
        data = r.json().get("data")
        rows = data if isinstance(data, list) else (data.get("web") if isinstance(data, dict) else None) or []
        urls = []
        for row in rows:
            u = (row.get("url") or "").strip() if isinstance(row, dict) else ""
            if u.lower().startswith(("http://", "https://")) and not u.lower().endswith(".pdf"):
                urls.append(u)
        return urls

    def _extract_images_from_page(url: str, client, trust_url: bool = False) -> list[str]:
        """Scrapea una página y extrae URLs de imagen (meta + markdown img tags).
        Si trust_url=True (cuando el usuario pega el link explícitamente), no
        descarta candidatos por dimensiones pequeñas en la URL — solo filtra
        patrones obvios de basura (thumbs, iconos, logos)."""
        try:
            r = client.post(
                "https://api.firecrawl.dev/v2/scrape",
                headers=headers,
                json={"url": url, "formats": ["markdown"], "onlyMainContent": False},
            )
        except httpx.HTTPError:
            return []
        if r.status_code != 200:
            return []
        sd = r.json().get("data") or {}
        meta = sd.get("metadata") or {}
        markdown = sd.get("markdown") or ""

        cands: list[str] = []
        seen: set[str] = set()

        def push(u: str | None) -> None:
            if not u or not isinstance(u, str):
                return
            u = u.strip()
            if not u.lower().startswith(("http://", "https://")):
                return
            # Filtrar tracking pixels y svgs decorativos
            if u.lower().endswith(".svg"):
                return
            lo = u.lower()
            # Filtrar thumbnails, iconos, logos y dimensiones pequeñas en la URL.
            # Patrones comunes que indican imagen de baja calidad:
            #   _thumb, -thumb, /thumbs/, _small, _sm, /icons/, /logos/,
            #   width=NN (≤200), w=NN (≤200), -100x100, _50x50, etc.
            LOW_QUALITY_PATTERNS = (
                "/thumb", "_thumb", "-thumb", "/thumbs/", "thumbnail",
                "/icon", "_icon", "-icon",
                "/logo", "_logo", "-logo", "favicon",
                "/avatar", "_avatar", "-avatar",
                "/sprite", "spacer.gif", "pixel.gif",
                "_sm.", "-sm.", "_small.", "-small.",
                # Ads, banners, promos, campaign creatives (B&H/Sony/etc.
                # incrustan estos en las páginas de producto; no son la
                # foto del equipo en sí).
                "/banner", "_banner", "-banner",
                "/promo", "_promo", "-promo",
                "/campaign", "_campaign", "-campaign",
                "/ads/", "/ad-", "_ad-", "adservice",
                "/marketing", "_marketing",
                "doubleclick", "googleads", "googlesyndication",
                "amazon-adsystem", "scorecardresearch",
                "/billboard", "_billboard",
                "/hero-banner", "homepage-banner",
                "watch-now", "/events/", "/event-",
                "in-residence", "panel-",
                "newsroom", "press-release", "press/",
            )
            if any(p in lo for p in LOW_QUALITY_PATTERNS):
                return
            if not trust_url:
                # Dimensiones pequeñas en URL: -100x100, _50x50, 200x150
                import re as _re
                m = _re.search(r"[-_/](\d{2,4})x(\d{2,4})", lo)
                if m:
                    w, h = int(m.group(1)), int(m.group(2))
                    if w < 800 or h < 800:
                        return
                # width=NN o w=NN <= 300 en query string
                m = _re.search(r"[?&](?:width|w|size)=(\d+)", lo)
                if m and int(m.group(1)) < 800:
                    return
            k = lo
            if k in seen or k in exclude_lc:
                return
            seen.add(k)
            cands.append(u)

        push(meta.get("ogImage") or meta.get("og:image"))
        push(meta.get("twitterImage") or meta.get("twitter:image"))
        # ![alt](url) en markdown
        for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)", markdown):
            push(m.group(1))
        # <img src="..."> en HTML embebido
        for m in re.finditer(r'<img[^>]+src=["\']?([^"\'>\s]+)', markdown):
            push(m.group(1))

        # Ordenar: primero URLs con indicadores de foto de producto (fondo blanco/hero)
        PRODUCT_INDICATORS = (
            "/product/", "_hero", "-hero", "_main", "-main",
            "-product-", "/images/", "bhphotovideo.com",
            "_front", "-front", "_top", "-top",
        )
        def _product_score(u: str) -> int:
            lo = u.lower()
            return sum(1 for p in PRODUCT_INDICATORS if p in lo)

        cands.sort(key=_product_score, reverse=True)
        return cands[:10]

    # Validación rápida: HEAD/GET parcial, descarta lo que no sea imagen real
    def _is_valid_image(url: str, client) -> bool:
        try:
            from urllib.parse import urlparse as _up
            host = (_up(url).hostname or "").lower()
            hdrs = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
                "Referer": f"https://{host}/" if host else "",
            }
            # Bajamos los primeros 16KB para chequear:
            #   1. Que sea una imagen (content-type)
            #   2. Que las dimensiones no sean de banner (relación ancho/alto
            #      muy extrema descarta banners promo tipo 728x90, 970x250).
            hdrs["Range"] = "bytes=0-16384"
            rg = client.get(url, headers=hdrs, follow_redirects=True, timeout=8.0)
            if rg.status_code not in (200, 206):
                return False
            ct = rg.headers.get("content-type", "")
            if not ct.startswith("image/"):
                return False
            # Intentar parsear el header para sacar dimensiones (PIL solo
            # necesita la cabecera). Si falla, asumimos válida.
            try:
                from PIL import Image as _PILImage
                from io import BytesIO as _BIO
                img = _PILImage.open(_BIO(rg.content))
                w, h = img.size
                if w > 0 and h > 0:
                    ratio = max(w, h) / max(1, min(w, h))
                    # Banners típicos: 8:1+ (728x90 ≈ 8.1, 970x250 ≈ 3.88).
                    # Cualquier cosa > 3.5:1 muy probable que sea banner/strip.
                    if ratio > 3.5:
                        return False
                    # Imágenes muy chicas no sirven como hero del producto.
                    if min(w, h) < 240:
                        return False
            except Exception:
                pass
            return True
        except httpx.HTTPError:
            pass
        return False

    def _og_images_from_html(url: str, client) -> list[str]:
        """Extrae og:image y twitter:image directamente del HTML sin Firecrawl.
        Más rápido y confiable para páginas de producto de B&H y similares."""
        og_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
            "Accept-Language": "en-US,en;q=0.9",
        }
        # Anti-SSRF (#1263): follow_redirects=True seguía ciego cualquier
        # salto sin re-validar — un producto que redirige a una IP interna
        # se descargaba igual. Re-validamos cada hop (mismo criterio que
        # _download_with_redirects en services/media/security.py), máximo 3.
        current = url
        r = None
        for _ in range(4):
            try:
                _validate_ssrf_only(current)
            except MediaError:
                return []
            try:
                r = client.get(current, headers=og_headers, timeout=15.0, follow_redirects=False)
            except httpx.HTTPError:
                return []
            if r.status_code in (301, 302, 303, 307, 308):
                location = r.headers.get("location")
                if not location:
                    return []
                from urllib.parse import urljoin as _urljoin
                current = _urljoin(current, location)
                continue
            break
        if r is None or r.status_code != 200:
            return []
        html = r.text[:100_000]
        imgs: list[str] = []
        seen: set[str] = set()
        def _push_og(u: str | None) -> None:
            if not u:
                return
            u = u.strip()
            if u.lower().startswith(("http://", "https://")) and u.lower() not in seen:
                seen.add(u.lower())
                imgs.append(u)
        # og:image (dos posibles órdenes de atributos)
        for pat in [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'og:image["\'][^>]*content=["\']([^"\']+)["\']',
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                _push_og(m.group(1))
                break
        # twitter:image
        for pat in [
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                _push_og(m.group(1))
                break
        return imgs

    all_cands: list[str] = []
    seen_lc: set[str] = set()
    # Cuando el usuario pegó una URL directa, marcamos las fotos obtenidas para
    # saltear la validación HEAD (B&H CDN puede rechazar HEADs cross-origin).
    direct_url_cands: set[str] = set()

    with httpx.Client(timeout=45.0) as client:
        if direct_url:
            # 1) Si la URL es directamente una imagen, usarla tal cual.
            if direct_url.lower().rsplit(".", 1)[-1] in ("jpg", "jpeg", "png", "webp", "avif", "gif"):
                all_cands.append(direct_url)
                seen_lc.add(direct_url.lower())
                direct_url_cands.add(direct_url.lower())

            # 2) Extraer og:image directamente del HTML (rápido, sin Firecrawl).
            #    Más confiable para B&H y sitios JS-pesados.
            for u in _og_images_from_html(direct_url, client):
                if u.lower() not in seen_lc:
                    seen_lc.add(u.lower())
                    all_cands.append(u)
                    direct_url_cands.add(u.lower())

            # 2b) B&H carrusel: si algún candidato sigue el patrón del CDN de B&H
            #     (static.bhphotovideo.com/c/product/{SKU}-{ANGLE}/{slug}), derivar
            #     los demás ángulos del carrusel sin hacer HEAD requests extra
            #     (el CDN bloquea cross-origin; los ángulos son de confianza).
            _BH_CDN_RE = re.compile(
                r"(https://static\.bhphotovideo\.com/c/product/\d+)-[A-Z0-9]+/([^?]+)",
                re.IGNORECASE,
            )
            for base_cand in list(all_cands):
                m_bh = _BH_CDN_RE.match(base_cand)
                if not m_bh:
                    continue
                base_prefix, slug = m_bh.group(1), m_bh.group(2)
                for angle in ("MAIN", "REAR", "SL01", "SL02", "SL03", "SL04", "SL05", "SL06", "SL07"):
                    u = f"{base_prefix}-{angle}/{slug}"
                    if u.lower() not in seen_lc:
                        seen_lc.add(u.lower())
                        all_cands.append(u)
                        direct_url_cands.add(u.lower())
                break  # solo necesitamos un candidato base para el patrón

            # 3) Firecrawl para más candidatos (especialmente imgs del body).
            for u in _extract_images_from_page(direct_url, client, trust_url=True):
                if u.lower() not in seen_lc:
                    seen_lc.add(u.lower())
                    all_cands.append(u)
        else:
            for q in PHOTO_QUERIES:
                if len(all_cands) >= 18 or not _time_left():
                    break
                for top in _fc_search(q, client)[:2]:
                    for u in _extract_images_from_page(top, client):
                        if u.lower() not in seen_lc:
                            seen_lc.add(u.lower())
                            all_cands.append(u)

        # Validar candidatos — los que vienen de URL directa se saltan la
        # validación (B&H CDN rechaza HEADs cross-origin; el og:image del propio
        # sitio es confiable sin necesidad de un round-trip extra).
        validated: list[str] = []
        with httpx.Client(timeout=10.0) as vc:
            for u in all_cands[:MAX_PHOTO_CANDIDATES_BUSCAR_VALIDATE]:
                if len(validated) >= MAX_PHOTO_CANDIDATES_BUSCAR_RETURN or not _time_left():
                    break
                if u.lower() in direct_url_cands or _is_valid_image(u, vc):
                    validated.append(u)

    return {"foto_candidates": validated, "total_inspeccionadas": len(all_cands)}



# ── Admin: descargar imagen externa y subirla a Cloudflare R2 ────────────────
#
# El frontend NO sube directamente al bucket porque eso requeriría exponer
# credenciales de R2 al browser. Acá lo hacemos en el backend con el secret
# guardado en env vars.
#
# SSRF guard
# ----------
# El admin autenticado puede pedir descargar cualquier URL externa. Sin
# allowlist, esto sería SSRF: un admin malicioso/comprometido podría hacer
# que el backend descargue http://localhost:5432/, http://169.254.169.254/
# (metadata cloud), o cualquier IP de la VPC interna de Railway. Filtramos:
# (1) sólo http(s) en puerto estándar (80/443), (2) host en allowlist de
# dominios conocidos, (3) la IP resuelta del host no es privada/loopback.


from services.media.security import _download_image_bytes, _validate_external_image_url
from services.media.storage import delete_object as _delete_from_r2, put as _put_r2, get as _get_r2
from services.media import (
    EQUIPO_DERIVE_SPECS,
    collect_asset_keys,
    purge_r2,
    store_upload,
)
from services.media_fastapi import media_http


def _foto_path(equipo_id: int, ext: str) -> str:
    """Genera path R2: equipos/{id}_{slug}/{id}_{slug}-{ts}.{ext}

    El timestamp en el nombre del archivo evita el problema del cache
    inmutable: R2 sirve los assets con Cache-Control: max-age=1año
    immutable, así que dos uploads al mismo path harían que el navegador
    siga mostrando el viejo durante un año. Con timestamp cada upload
    tiene URL nueva. El archivo anterior queda como huérfano en R2.
    """
    import time as _time
    try:
        with get_db() as conn:
            row = conn.execute("SELECT nombre FROM equipos WHERE id = %s", (equipo_id,)).fetchone()
        nombre = row[0] if row else ""
    except Exception:
        nombre = ""

    if nombre:
        slug = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
        slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")[:50]
    else:
        slug = ""

    ts = int(_time.time())
    if slug:
        folder   = f"{equipo_id}_{slug}"
        filename = f"{equipo_id}_{slug}-{ts}.{ext}"
    else:
        folder   = f"{equipo_id}"
        filename = f"{equipo_id}-{ts}.{ext}"
    return f"equipos/{folder}/{filename}"


class UploadFotoFromUrlInput(BaseModel):
    url: str


@router.post("/admin/equipos/{equipo_id}/upload-foto-from-url")
@limiter.limit(ADMIN_UPLOAD_LIMIT)
def admin_upload_foto_from_url(
    equipo_id: int,
    payload: UploadFotoFromUrlInput,
    request: Request,
):
    """Descarga imagen externa, la optimiza y la sube a Cloudflare R2.
    Crea una fila en equipo_fotos y sincroniza equipos.foto_url con la principal.
    Devuelve {public_url, path, size, content_type}.
    """
    require_admin(request)

    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(400, "URL vacía")

    cfg_pub = (os.getenv("R2_PUBLIC_BASE") or "").rstrip("/")
    if cfg_pub and url.startswith(cfg_pub + "/"):
        return {"public_url": url, "path": None, "skipped": True}

    with media_http():
        _validate_external_image_url(url)
        raw_content, _raw_ctype = _download_image_bytes(url)

    with get_db() as conn:
        try:
            with media_http():
                asset = store_upload(raw_content, kind="equipo", derive_specs=EQUIPO_DERIVE_SPECS, conn=conn)
            display = asset.variant("display")
            _insert_equipo_foto(conn, equipo_id, display.url, display.key, asset.id)
        except Exception:
            conn.rollback()
            raise

    return {
        "public_url": display.url,
        "path": display.key,
        "size": display.bytes,
        "size_original": len(raw_content),
        "content_type": display.content_type,
        "width": display.width or None,
        "height": display.height or None,
    }


# ── Admin: subir bytes de un archivo (multipart) directo a R2 ─────────────

@router.post("/admin/equipos/{equipo_id}/upload-foto")
@limiter.limit(ADMIN_UPLOAD_LIMIT)
async def admin_upload_foto_file(
    equipo_id: int,
    request: Request,
):
    """Sube un archivo (multipart/form-data, campo `file`) a R2 con pipeline
    no-destructivo: guarda el original + variante cuadrada 1200×1200.
    Crea una fila en equipo_fotos y sincroniza equipos.foto_url.
    """
    require_admin(request)

    form = await request.form()
    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        raise HTTPException(400, "Falta el campo 'file' en el form-data")

    raw_content = await file.read()
    if not raw_content:
        raise HTTPException(400, "Archivo vacío")
    if len(raw_content) > 20 * 1024 * 1024:
        raise HTTPException(413, "Archivo muy grande (máx 20MB)")

    with get_db() as conn:
        try:
            with media_http():
                asset = store_upload(raw_content, kind="equipo", derive_specs=EQUIPO_DERIVE_SPECS, conn=conn)
            display = asset.variant("display")
            _insert_equipo_foto(conn, equipo_id, display.url, display.key, asset.id)
        except Exception:
            conn.rollback()
            raise

    return {
        "public_url": display.url,
        "path": display.key,
        "size": display.bytes,
        "size_original": len(raw_content),
        "content_type": display.content_type,
        "width": display.width or None,
        "height": display.height or None,
    }


# ── Galería multi-foto de equipos (F2) ───────────────────────────────────────


def _get_equipo_fotos(conn, equipo_id: int) -> list[dict]:
    # `es_principal DESC` primero — mismo criterio que el resto de las
    # galerías (talleres/estudio); ver comentario en `_get_institucion_fotos`.
    rows = conn.execute(
        "SELECT id, url, path, media_id, orden, es_principal, created_at "
        "FROM equipo_fotos WHERE equipo_id = %s ORDER BY es_principal DESC, orden, id",
        (equipo_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "url": r["url"],
            "path": r["path"],
            "media_id": r["media_id"],
            "orden": r["orden"],
            "es_principal": bool(r["es_principal"]),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


def _principal_sm_url(conn, equipo_id: int) -> str | None:
    """URL de la variante 'display-sm' (600px) de la foto PRINCIPAL del equipo,
    para srcset. None si la principal no tiene esa variante (foto legacy sin
    media_id, o aún sin backfill) → el front cae a foto_url (sin srcset, cero rotura).
    """
    row = conn.execute(
        "SELECT media_id FROM equipo_fotos WHERE equipo_id = %s AND es_principal = TRUE LIMIT 1",
        (equipo_id,),
    ).fetchone()
    if not row or not row["media_id"]:
        return None
    v = conn.execute(
        "SELECT url FROM media_variants WHERE asset_id = %s AND name = 'display-sm' LIMIT 1",
        (row["media_id"],),
    ).fetchone()
    return v["url"] if v else None


def _principal_thumb_url(conn, equipo_id: int) -> str | None:
    """URL de la variante 'display-thumb' (160px) de la foto PRINCIPAL del equipo,
    para srcset en slots de ~48px. None si no existe (foto pre-backfill) → fallback seguro."""
    row = conn.execute(
        "SELECT media_id FROM equipo_fotos WHERE equipo_id = %s AND es_principal = TRUE LIMIT 1",
        (equipo_id,),
    ).fetchone()
    if not row or not row["media_id"]:
        return None
    v = conn.execute(
        "SELECT url FROM media_variants WHERE asset_id = %s AND name = 'display-thumb' LIMIT 1",
        (row["media_id"],),
    ).fetchone()
    return v["url"] if v else None


def _sync_principal_denorm(conn, equipo_id: int) -> None:
    """Sincroniza TODAS las columnas denormalizadas de la foto principal del equipo.

    Una sola UPDATE reemplaza los 3 sitios que antes actualizaban (url/sm/thumb) por separado.
    No commitea — el caller lo hace.
    """
    row = conn.execute(
        "SELECT url, media_id FROM equipo_fotos WHERE equipo_id = %s AND es_principal = TRUE LIMIT 1",
        (equipo_id,),
    ).fetchone()
    if not row:
        conn.execute(
            "UPDATE equipos SET foto_url = NULL, foto_url_sm = NULL, foto_url_thumb = NULL, "
            "foto_url_avif = NULL, foto_url_sm_avif = NULL, foto_url_thumb_avif = NULL, "
            "foto_lqip = NULL WHERE id = %s",
            (equipo_id,),
        )
        return

    principal_url = row["url"]
    media_id = row["media_id"]
    sm = thumb = avif = sm_avif = thumb_avif = lqip = None

    if media_id:
        for v in conn.execute(
            "SELECT name, url FROM media_variants WHERE asset_id = %s "
            "AND name IN ('display-sm','display-thumb','display-avif','display-sm-avif','display-thumb-avif')",
            (media_id,),
        ).fetchall():
            if v["name"] == "display-sm":
                sm = v["url"]
            elif v["name"] == "display-thumb":
                thumb = v["url"]
            elif v["name"] == "display-avif":
                avif = v["url"]
            elif v["name"] == "display-sm-avif":
                sm_avif = v["url"]
            elif v["name"] == "display-thumb-avif":
                thumb_avif = v["url"]
        lqip_row = conn.execute(
            "SELECT lqip FROM media_assets WHERE id = %s", (media_id,)
        ).fetchone()
        lqip = lqip_row["lqip"] if lqip_row else None

    conn.execute(
        "UPDATE equipos SET foto_url = %s, foto_url_sm = %s, foto_url_thumb = %s, "
        "foto_url_avif = %s, foto_url_sm_avif = %s, foto_url_thumb_avif = %s, foto_lqip = %s "
        "WHERE id = %s",
        (principal_url, sm, thumb, avif, sm_avif, thumb_avif, lqip, equipo_id),
    )


def _insert_equipo_foto(
    conn,
    equipo_id: int,
    url: str,
    path: str,
    media_id: int | None = None,
    orden: int | None = None,
) -> dict:
    """Inserta una fila en equipo_fotos y sincroniza equipos.foto_url con la principal.
    La primera foto del equipo se marca como principal automáticamente.

    `orden` explícito gana — mismo criterio que `_insert_edicion_foto`
    (routes/talleres.py): con upload concurrente, inferirlo acá corre una
    carrera (la foto que termina de procesarse primero, no la que el
    usuario eligió primero, gana el primer lugar).
    """
    if orden is None:
        cur = conn.execute(
            "SELECT COALESCE(MAX(orden), -1) + 1 AS next_orden FROM equipo_fotos WHERE equipo_id = %s",
            (equipo_id,),
        )
        orden = cur.fetchone()["next_orden"]

    cur2 = conn.execute("SELECT COUNT(*) AS cnt FROM equipo_fotos WHERE equipo_id = %s", (equipo_id,))
    is_first = cur2.fetchone()["cnt"] == 0

    conn.execute(
        "INSERT INTO equipo_fotos (equipo_id, url, path, media_id, orden, es_principal) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (equipo_id, url, path, media_id, orden, is_first),
    )

    if is_first:
        _sync_principal_denorm(conn, equipo_id)

    conn.commit()

    cur3 = conn.execute(
        "SELECT id, url, path, media_id, orden, es_principal, created_at "
        "FROM equipo_fotos WHERE equipo_id = %s ORDER BY id DESC LIMIT 1",
        (equipo_id,),
    )
    r = cur3.fetchone()
    return {
        "id": r["id"],
        "url": r["url"],
        "path": r["path"],
        "media_id": r["media_id"],
        "orden": r["orden"],
        "es_principal": bool(r["es_principal"]),
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


@router.get("/admin/equipos/{equipo_id}/fotos")
def get_equipo_fotos(equipo_id: int, request: Request):
    require_admin(request)
    with get_db() as conn:
        eq = conn.execute("SELECT id FROM equipos WHERE id = %s", (equipo_id,)).fetchone()
        if not eq:
            raise HTTPException(404, "Equipo no encontrado")
        return {"fotos": _get_equipo_fotos(conn, equipo_id)}


@router.post("/admin/equipos/{equipo_id}/fotos", status_code=201)
@limiter.limit(ADMIN_UPLOAD_LIMIT)
async def upload_equipo_foto(equipo_id: int, request: Request):
    """Sube una foto (multipart, campo 'file') al equipo. Guarda original + variante cuadrada."""
    require_admin(request)

    form = await request.form()
    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        raise HTTPException(400, "Falta el campo 'file'")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Archivo vacío")
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, "Archivo muy grande (máx 20 MB)")
    orden_raw = form.get("orden")
    orden = int(orden_raw) if orden_raw not in (None, "") else None

    with get_db() as conn:
        try:
            eq = conn.execute("SELECT id FROM equipos WHERE id = %s", (equipo_id,)).fetchone()
            if not eq:
                raise HTTPException(404, "Equipo no encontrado")
            with media_http():
                asset = store_upload(raw, kind="equipo", derive_specs=EQUIPO_DERIVE_SPECS, conn=conn)
            display = asset.variant("display")
            foto = _insert_equipo_foto(conn, equipo_id, display.url, display.key, asset.id, orden=orden)
        except Exception:
            conn.rollback()
            raise

    return foto


class EquipoFotoFromUrlBody(BaseModel):
    url: str


def _agregar_foto_desde_url(conn, equipo_id: int, url: str, cfg_pub: str) -> dict:
    """Descarga una URL externa, la sube a R2 y la agrega a la galería.
    Fuente única para el endpoint singular y el batch (#1051 Stream B)."""
    if cfg_pub and url.startswith(cfg_pub + "/"):
        raise HTTPException(400, "La URL ya está en el bucket — subí el archivo directamente")

    with media_http():
        _validate_external_image_url(url)
        raw, _raw_ctype = _download_image_bytes(url)
        asset = store_upload(raw, kind="equipo", derive_specs=EQUIPO_DERIVE_SPECS, conn=conn)
    display = asset.variant("display")
    return _insert_equipo_foto(conn, equipo_id, display.url, display.key, asset.id)


@router.post("/admin/equipos/{equipo_id}/fotos/from-url", status_code=201)
@limiter.limit(ADMIN_UPLOAD_LIMIT)
def upload_equipo_foto_from_url(equipo_id: int, body: EquipoFotoFromUrlBody, request: Request):
    """Descarga URL externa y la agrega a la galería del equipo."""
    require_admin(request)

    url = (body.url or "").strip()
    if not url:
        raise HTTPException(400, "URL vacía")

    cfg_pub = (os.getenv("R2_PUBLIC_BASE") or "").rstrip("/")

    with get_db() as conn:
        try:
            eq = conn.execute("SELECT id FROM equipos WHERE id = %s", (equipo_id,)).fetchone()
            if not eq:
                raise HTTPException(404, "Equipo no encontrado")
            foto = _agregar_foto_desde_url(conn, equipo_id, url, cfg_pub)
        except Exception:
            conn.rollback()
            raise

    return foto


class EquipoFotosFromUrlsBody(BaseModel):
    urls: list[str]


@router.post("/admin/equipos/{equipo_id}/fotos/from-urls", status_code=201)
@limiter.limit(ADMIN_UPLOAD_LIMIT)
def upload_equipo_fotos_from_urls(equipo_id: int, body: EquipoFotosFromUrlsBody, request: Request):
    """Batch de `fotos/from-url` (#1051 Stream B): agrega hasta 20 fotos de un
    saque — típicamente la galería completa de un HTML recién enriquecido
    (`enriquecer-from-html` devuelve `foto_candidates`). Best-effort por URL
    (mismo criterio que `/admin/equipos/buscar-fotos`): una que falla no
    aborta el resto — se reporta en `fallidas` en vez de perder el batch entero.

    Returns: {agregadas: EquipoFoto[], fallidas: [{url, error}]}
    """
    require_admin(request)

    urls = [u.strip() for u in (body.urls or []) if u and u.strip()]
    if not urls:
        raise HTTPException(400, "Sin URLs")
    if len(urls) > 20:
        raise HTTPException(400, "Máximo 20 URLs por batch")

    cfg_pub = (os.getenv("R2_PUBLIC_BASE") or "").rstrip("/")
    agregadas: list[dict] = []
    fallidas: list[dict] = []

    with get_db() as conn:
        eq = conn.execute("SELECT id FROM equipos WHERE id = %s", (equipo_id,)).fetchone()
        if not eq:
            raise HTTPException(404, "Equipo no encontrado")

        for url in urls:
            try:
                foto = _agregar_foto_desde_url(conn, equipo_id, url, cfg_pub)
                agregadas.append(foto)
            except HTTPException as e:
                conn.rollback()
                fallidas.append({"url": url, "error": str(e.detail)})
            except Exception as exc:
                conn.rollback()
                logger.warning("fotos/from-urls: fallo con %s: %s", url, exc)
                fallidas.append({"url": url, "error": "no se pudo descargar/procesar"})

    return {"agregadas": agregadas, "fallidas": fallidas}


@router.delete("/admin/equipos/{equipo_id}/fotos/{foto_id}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def delete_equipo_foto(equipo_id: int, foto_id: int, request: Request):
    require_admin(request)

    with get_db() as conn:
        cur = conn.execute(
            "SELECT url, path, media_id, es_principal FROM equipo_fotos "
            "WHERE id = %s AND equipo_id = %s",
            (foto_id, equipo_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Foto no encontrada")

        media_id = row["media_id"]
        path = row["path"]
        was_principal = bool(row["es_principal"])

        r2_keys: list[str] = []
        if media_id:
            r2_keys = collect_asset_keys(conn, media_id)

        conn.execute("DELETE FROM equipo_fotos WHERE id = %s", (foto_id,))
        if media_id:
            conn.execute("DELETE FROM media_assets WHERE id = %s", (media_id,))

        # Si era la principal, promover la siguiente en orden
        if was_principal:
            next_foto = conn.execute(
                "SELECT id, url FROM equipo_fotos WHERE equipo_id = %s ORDER BY orden, id LIMIT 1",
                (equipo_id,),
            ).fetchone()
            if next_foto:
                conn.execute(
                    "UPDATE equipo_fotos SET es_principal = TRUE WHERE id = %s", (next_foto["id"],)
                )
            _sync_principal_denorm(conn, equipo_id)

        conn.commit()

    if r2_keys:
        purge_r2(r2_keys)
    elif path:
        _delete_from_r2(path)

    return {"ok": True}


class EquipoFotoOrdenItem(BaseModel):
    id: int
    orden: int
    es_principal: bool


class EquipoFotoReorderBody(BaseModel):
    fotos: list[EquipoFotoOrdenItem]


@router.patch("/admin/equipos/{equipo_id}/fotos/orden")
@limiter.limit(ADMIN_WRITE_LIMIT)
def reorder_equipo_fotos(equipo_id: int, body: EquipoFotoReorderBody, request: Request):
    require_admin(request)

    with get_db() as conn:
        principal_url: str | None = None
        for f in body.fotos:
            conn.execute(
                "UPDATE equipo_fotos SET orden = %s, es_principal = %s "
                "WHERE id = %s AND equipo_id = %s",
                (f.orden, f.es_principal, f.id, equipo_id),
            )
            if f.es_principal:
                row = conn.execute(
                    "SELECT url FROM equipo_fotos WHERE id = %s", (f.id,)
                ).fetchone()
                if row:
                    principal_url = row["url"]

        if principal_url is not None:
            _sync_principal_denorm(conn, equipo_id)

        conn.commit()
        fotos = _get_equipo_fotos(conn, equipo_id)

    return {"fotos": fotos}


# ── Admin: diagnóstico de R2 (sin exponer secretos) ─────────────────────────

@router.get("/admin/storage/diag")
def admin_storage_diag(request: Request):
    """Verifica que R2 esté configurado correctamente. Sólo dice si las vars
    están presentes y si el upload+read end-to-end funciona. NUNCA devuelve
    el contenido del secret."""
    require_admin(request)

    import time as _time
    import httpx

    vars_status = {
        "R2_ACCOUNT_ID":         bool(os.getenv("R2_ACCOUNT_ID")),
        "R2_ACCESS_KEY_ID":      bool(os.getenv("R2_ACCESS_KEY_ID")),
        "R2_SECRET_ACCESS_KEY":  bool(os.getenv("R2_SECRET_ACCESS_KEY")),
        "R2_BUCKET":             os.getenv("R2_BUCKET") or "equipos-fotos",
        "R2_PUBLIC_BASE":        os.getenv("R2_PUBLIC_BASE") or None,
    }
    missing = [k for k, v in vars_status.items() if v is False]
    if missing:
        return {"ok": False, "vars": vars_status, "missing": missing, "tested": False}

    # Smoke test: subir un blob chico y leerlo
    try:
        sample = b"R2 smoke test " + str(int(_time.time())).encode()
        path = f"diag/smoke-{int(_time.time())}.txt"
        with media_http():
            public_url = _put_r2(path, sample, "text/plain")
        verify = httpx.get(public_url, timeout=10.0)
        ok = verify.status_code == 200 and verify.content == sample
        return {
            "ok":         ok,
            "vars":       vars_status,
            "tested":     True,
            "public_url": public_url,
            "verify":     verify.status_code,
        }
    except HTTPException as e:
        return {"ok": False, "vars": vars_status, "tested": True, "error": e.detail}
    except Exception as e:
        return {"ok": False, "vars": vars_status, "tested": True, "error": str(e)}
