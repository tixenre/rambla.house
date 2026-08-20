"""
Rambla Rental API — FastAPI + PostgreSQL
Run: uvicorn main:app --reload --port 8000
"""

import json
import logging
import mimetypes
import os
import threading
import uuid
import html as _html
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Configurar logging ANTES de importar cualquier módulo del proyecto
# (algunos crean loggers a nivel de módulo).
from logging_config import setup_logging, request_id_var
setup_logging()

from config import settings

# ── Sentry (error tracking) ──────────────────────────────────────────────────
# Solo activo si SENTRY_DSN está seteado — dev/CI no lo necesitan.
_sentry_dsn = settings.SENTRY_DSN
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        traces_sample_rate=0.1,
        environment=settings.RAILWAY_ENVIRONMENT or "production",
        send_default_pii=False,
        # HTTPException = "ya manejado" en esta app (mismo criterio que
        # _global_exception_handler más abajo, que la re-propaga sin loguearla
        # como error): 4xx/5xx de negocio (sin stock, URL externa que rechaza
        # la descarga) ya le devuelven al cliente una respuesta clara. Sin este
        # filtro, cada rechazo esperado aparece en Sentry como si fuera un bug.
        ignore_errors=[HTTPException],
    )

from database import init_db, get_db, row_to_dict, FRONT, FRONT_NEW, MARCA_SUBQUERY
from services.catalogo import proyectar_seed
from config import SITE_URL
from routes.equipos          import router as equipos_router
from routes.alquileres       import router as alquileres_router
from routes.clientes         import router as clientes_router
from routes.estadisticas     import router as estadisticas_router
from routes.reportes         import router as reportes_router
from routes.contabilidad     import router as contabilidad_router
from routes.busquedas        import router as busquedas_router
from routes.dashboard        import router as dashboard_router
from auth import router as auth_router
from auth import auth_passkey_router
from auth import auth_sessions_router
from auth import auth_linking_router
from routes.settings         import router as settings_router
from routes.cliente_portal   import router as cliente_portal_router
from routes.marcas           import router as marcas_router
from routes.specs            import router as specs_router
from routes.unidades         import router as unidades_router
from routes.seo              import (
    router as seo_router,
    _build_categoria_slug as _cat_slug,
    _build_equipo_slug as _eq_slug,
)
from routes.calendar         import router as calendar_router
from routes.inventario       import router as inventario_router
from routes.email_templates  import router as email_templates_router
from routes.dataio           import router as dataio_router
from routes.estudio          import router as estudio_router, _parse_json_field
from routes.didit            import router as didit_router
from routes.facturacion      import router as facturacion_router
from routes.whatsapp         import router as whatsapp_router
from routes.comunicacion     import router as comunicacion_router
from routes.productoras      import router as productoras_router
from routes.talleres         import router as talleres_router
from routes.carritos         import router as carritos_router
from routes.checkout         import router as checkout_router
from routes.compartir        import router as compartir_router
from routes.rental_publico   import router as rental_publico_router
from routes.errores_admin    import router as errores_admin_router
from routes.media_api        import router as media_api_router
from routes.media_admin      import router as media_admin_router
from middleware          import auth_middleware

logger = logging.getLogger(__name__)

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Rambla Rental API", version="2.0")

# ── Rate limiting (#58) ──────────────────────────────────────────────────────
# El limiter vive en `rate_limit.py` (compartido con los routers que usan
# @limiter.limit en handlers sensibles, sin ciclos de import).
from rate_limit import limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    """Captura cualquier excepción no manejada, la persiste en server_errors y
    devuelve un 500 al cliente.

    HTTPException y RateLimitExceeded se propagan normalmente — este handler
    solo atrapa lo inesperado. El detalle completo (tipo + mensaje) SIEMPRE
    queda en `server_errors` (`log_server_error`) y en el log — al cliente solo
    le llega tipo+mensaje crudo en local (`not settings.is_railway`); en
    Railway (dev/staging incluido — corre con datos copiados de prod, ver
    MEMORIA) y en prod devolvemos un mensaje genérico, para no filtrar nombres
    de constraint/columna/librería a un caller externo.
    """
    from fastapi import HTTPException as _HTTPException
    from fastapi.responses import JSONResponse as _JSONResponse
    from services.error_log import log_server_error
    from logging_config import request_id_var

    if isinstance(exc, _HTTPException):
        raise exc

    route = str(request.url.path)
    rid = request_id_var.get(None)
    logger.exception("Error no manejado en %s (rid=%s)", route, rid)
    log_server_error(route, exc, request_id=rid)

    detail = (
        f"{type(exc).__name__}: {exc}"
        if not settings.is_railway
        else "Ocurrió un error inesperado — ya quedó registrado."
    )
    return _JSONResponse(
        status_code=500,
        content={"detail": detail},
    )


@app.on_event("startup")
async def _startup() -> None:
    """Startup: acota el threadpool + arranca el init de BD en background.

    Threadpool: FastAPI corre los handlers sync en el threadpool de AnyIO (default 40). Cada
    handler toma una conexión del pool (maxconn). Si los threads superan al pool,
    el excedente NO espera: psycopg2 lanza `PoolError: connection pool exhausted`
    → 500 en cascada. Acotando el threadpool a `pool_max()` menos un margen para
    workers de fondo (scheduler, init de BD, webhooks async que tocan la BD),
    los requests de más hacen cola en vez de explotar. Back-pressure, no errores.

    DB init: arranca aquí (no a nivel de módulo) para evitar que `import main`
    en los tests lance el thread antes de que el test tenga la BD preparada,
    lo que causaba un deadlock entre el upgrade de Alembic y el init_db() del
    fixture del test.
    """
    import anyio.to_thread
    from database import pool_max

    margen_fondo = 4  # scheduler + init + webhooks async que comparten el pool
    tokens = max(3, pool_max() - margen_fondo)
    anyio.to_thread.current_default_thread_limiter().total_tokens = tokens
    logger.info(
        "Threadpool acotado a %d (pool_max=%d, margen=%d) — back-pressure activo",
        tokens, pool_max(), margen_fondo,
    )

    global db_init_thread
    db_init_thread = threading.Thread(target=init_db_bg, daemon=True)
    db_init_thread.start()


async def request_id_middleware(request: Request, call_next):
    """Inyecta un request_id único en context para que los logs lo incluyan.

    Si el cliente envía un header X-Request-Id, lo respeta (útil para tracear
    desde Sentry/Cloudflare). Si no, generamos un UUID4.
    """
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex
    token = request_id_var.set(rid)
    try:
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response
    finally:
        request_id_var.reset(token)

# Orígenes permitidos para CORS con credenciales (cookie de sesión).
ALLOWED_ORIGINS = settings.frontend_origins

# Hardening pre-launch (#503): CORS con credenciales + localhost/wildcard en
# prod es peligroso. Rompemos el boot explícitamente para que no pase callado.
if os.getenv("RAILWAY_ENVIRONMENT"):
    _inseguros = [o for o in ALLOWED_ORIGINS if "localhost" in o or "127.0.0.1" in o or o == "*"]
    if _inseguros:
        raise RuntimeError(
            f"CORS inseguro en producción: FRONTEND_ORIGINS incluye {_inseguros}. "
            "Revisá la env var en Railway (no debe tener localhost ni '*')."
        )

# ── Content-Security-Policy (Report-Only) ──────────────────────────────────────
# Arranca en Report-Only: NO bloquea nada, solo reporta violaciones a /csp-report
# para mapear las fuentes reales en prod antes de pasar a enforcing. Fuentes
# relevadas del código: self · Google Fonts (googleapis/gstatic) · GA4
# (googletagmanager/google-analytics/analytics.google.com/doubleclick — GA4 usa
# varios subdominios, no solo google-analytics.com) · Sentry (ingest.us.sentry.io,
# error tracking del panel admin) · Cloudflare Insights (beacon automático) · R2
# (imágenes, *.r2.dev) · embeds (Google Maps, YouTube, Instagram embed.js +
# cdninstagram/fbcdn) · simpleicons (logos de marca). Confirmado/ajustado contra
# los reportes reales acumulados en prod (auditoría de seguridad, 2026-07-08).
# 'unsafe-inline' en style-src es inevitable por los `style={}` de React + el
# <style> que inyecta Google Fonts. Solo se aplica al HTML del SPA (no a /api ni
# assets, que no ejecutan nada).
CSP_REPORT_ONLY = "; ".join(
    [
        "default-src 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "frame-ancestors 'self'",
        "form-action 'self'",
        "script-src 'self' https://www.googletagmanager.com https://www.instagram.com "
        "https://static.cloudflareinsights.com",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data: blob: https://*.r2.dev https://www.googletagmanager.com "
        "https://*.google-analytics.com https://www.google.com.ar https://cdn.simpleicons.org "
        "https://*.cdninstagram.com https://*.fbcdn.net",
        "connect-src 'self' https://www.googletagmanager.com https://*.google-analytics.com "
        "https://analytics.google.com https://stats.g.doubleclick.net https://www.google.com.ar "
        "https://*.ingest.us.sentry.io https://*.r2.dev https://www.instagram.com",
        "frame-src 'self' blob: https://www.google.com https://maps.google.com "
        "https://www.youtube.com https://*.r2.dev https://www.instagram.com",
        "report-uri /csp-report",
    ]
)


# Estáticos no-hasheados servidos por el catch-all (estudio/*.jpg, favicon, icons,
# robots, manifests): cache de 1 día. Los bundles hasheados (/assets/*) van aparte
# como `immutable` 1 año (el hash de Vite invalida solos). El HTML del SPA → no-cache.
_STATIC_EXT_RE = re.compile(
    r"\.(?:js|css|jpg|jpeg|png|webp|avif|gif|svg|ico|woff2?|ttf|txt|json|map)$", re.I
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Fuera de prod (dev/staging/preview/local), nunca indexable — sin esto,
    # cualquier cosa que un crawler encuentre en dev-rambla.up.railway.app
    # (compartido, linkeado, o simplemente rastreado) podía entrar al índice
    # como contenido duplicado. Header, no depende de que el crawler respete
    # robots.txt (Google puede igual listar una URL bloqueada por robots.txt
    # si la encuentra linkeada — `X-Robots-Tag` es la señal que sí lo evita).
    # `robots.txt` (routes/seo.py) es la segunda capa: bloquea el CRAWL mismo.
    if not settings.is_production:
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    # Cache-Control por path (no se toca /api/* ni respuestas que ya fijan el suyo —
    # sitemap/calendar/doc-preview usan setdefault, así que su valor gana). Arregla
    # el "Use efficient cache lifetimes" de Lighthouse: el backend servía todo sin TTL.
    path = request.url.path
    if not path.startswith("/api/"):
        ctype = response.headers.get("content-type", "")
        if path.startswith("/assets/"):
            response.headers.setdefault(
                "Cache-Control", "public, max-age=31536000, immutable"
            )
        elif ctype.startswith("text/html"):
            response.headers.setdefault("Cache-Control", "no-cache")
        elif response.status_code == 200 and _STATIC_EXT_RE.search(path):
            response.headers.setdefault("Cache-Control", "public, max-age=86400")
    # DENY global por default (anti-clickjacking, #503). `setdefault` para que una
    # ruta pueda relajar a SAMEORIGIN cuando su HTML está hecho para embeberse en
    # un iframe del propio portal (preview de documentos) sin que el middleware lo
    # pise de vuelta a DENY.
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # El propio origen no usa cámara/micrófono/geolocalización/pagos vía Web API (la
    # verificación de identidad corre en el dominio de Didit, no embebida acá) — las
    # bloqueamos explícitamente (auditoría de seguridad, 2026-07-08).
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )
    # HSTS solo en prod: fuerza HTTPS por 1 año (incluye subdominios). NO en
    # dev/staging (no pinear sus dominios a HTTPS). `is_production` falla-a-prod ante
    # un env desconocido → del lado seguro (todo Railway es HTTPS; sobre HTTP el header
    # se ignora). Sin `preload` (compromiso difícil de revertir, requiere alta manual).
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    # CSP solo en el HTML del SPA (lo único que ejecuta scripts/estilos). Report-Only
    # → reporta, no bloquea: cero riesgo de romper prod mientras se mapean las fuentes.
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Content-Security-Policy-Report-Only"] = CSP_REPORT_ONLY
    return response

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(BaseHTTPMiddleware, dispatch=auth_middleware)
app.add_middleware(BaseHTTPMiddleware, dispatch=request_id_middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Montar el frontend clásico solo si existe (no existe en el monorepo rental-refine)
if FRONT.exists():
    app.mount("/static", StaticFiles(directory=str(FRONT)), name="static")

# Nuevo frontend (Vite SPA — rental-refine):
# Content-negotiation: sirve .br / .gz pre-comprimidos si el cliente los acepta.
# Reemplaza el StaticFiles mount porque StaticFiles no sirve FileResponse comprimidas
# incluso con GZipMiddleware (limitación de Starlette).
if FRONT_NEW.exists():
    _assets_dir = (FRONT_NEW / "assets").resolve()

    @app.get("/assets/{path:path}", include_in_schema=False)
    async def serve_asset(path: str, request: Request):
        """Sirve assets estáticos con content-negotiation (Brotli > gzip > raw)."""
        try:
            candidate = (_assets_dir / path).resolve()
        except Exception:
            raise HTTPException(status_code=400)
        if not candidate.is_file() or not candidate.is_relative_to(_assets_dir):
            raise HTTPException(status_code=404)
        ctype = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        cache = "public, max-age=31536000, immutable"
        accept_enc = request.headers.get("accept-encoding", "")
        if "br" in accept_enc:
            br = candidate.parent / (candidate.name + ".br")
            if br.is_file():
                return FileResponse(str(br), headers={
                    "Content-Encoding": "br", "Content-Type": ctype,
                    "Cache-Control": cache, "Vary": "Accept-Encoding",
                })
        if "gzip" in accept_enc:
            gz = candidate.parent / (candidate.name + ".gz")
            if gz.is_file():
                return FileResponse(str(gz), headers={
                    "Content-Encoding": "gzip", "Content-Type": ctype,
                    "Cache-Control": cache, "Vary": "Accept-Encoding",
                })
        return FileResponse(str(candidate), headers={
            "Cache-Control": cache, "Vary": "Accept-Encoding",
        })

# ── Routers ──────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(auth_passkey_router)  # /auth/passkey/* + /cliente/auth/passkey/* (sin prefijo /api)
app.include_router(auth_sessions_router)  # /auth/sessions/* + /cliente/auth/sessions/* (sin prefijo /api)
app.include_router(auth_linking_router)  # /cliente/auth/keys/* (métodos de acceso, sin prefijo /api)
app.include_router(equipos_router,        prefix="/api")
app.include_router(alquileres_router,     prefix="/api")
app.include_router(clientes_router,       prefix="/api")
app.include_router(estadisticas_router,   prefix="/api")
app.include_router(reportes_router,       prefix="/api")
app.include_router(contabilidad_router,   prefix="/api")
app.include_router(busquedas_router,      prefix="/api")
app.include_router(dashboard_router,      prefix="/api")
app.include_router(settings_router,       prefix="/api")
app.include_router(marcas_router,         prefix="/api")
app.include_router(specs_router,          prefix="/api")
app.include_router(unidades_router,       prefix="/api")
app.include_router(inventario_router,     prefix="/api/admin")
app.include_router(email_templates_router, prefix="/api")
app.include_router(dataio_router,         prefix="/api")
app.include_router(estudio_router,        prefix="/api")
app.include_router(didit_router,          prefix="/api")
app.include_router(facturacion_router,    prefix="/api")
app.include_router(whatsapp_router,       prefix="/api")
app.include_router(comunicacion_router,   prefix="/api")
app.include_router(productoras_router,    prefix="/api")
app.include_router(talleres_router,       prefix="/api")
app.include_router(carritos_router,       prefix="/api")
app.include_router(checkout_router,       prefix="/api")
app.include_router(compartir_router,      prefix="/api")  # /api/public/compartir (sin auth)
app.include_router(rental_publico_router, prefix="/api")  # /api/public/rental/disclaimers (sin auth)
app.include_router(errores_admin_router,  prefix="/api")
app.include_router(media_api_router,      prefix="/api")
app.include_router(media_admin_router,    prefix="/api")
app.include_router(seo_router)  # /sitemap.xml (sin prefijo /api — debe estar en root)
app.include_router(calendar_router)  # /calendar/feed.ics (root) + /api/admin/calendar/*
app.include_router(cliente_portal_router)

# ── CSP violation report sink ────────────────────────────────────────────────

_csp_logger = logging.getLogger("csp")


@app.post("/csp-report", include_in_schema=False)
async def csp_report(request: Request):
    """Recibe violaciones del CSP Report-Only (browser → report-uri).

    Las loggea para mapear qué fuentes reales usa prod antes de pasar a enforcing.
    Devuelve 204 sin cuerpo. Capea el payload para no loggear basura enorme.
    """
    try:
        body = await request.body()
        if body:
            _csp_logger.warning("csp-violation %s", body[:2000].decode("utf-8", "replace"))
    except Exception:  # nunca debe fallar la respuesta por un report malformado
        pass
    return Response(status_code=204)


# ── Health Check ─────────────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
def health():
    """Health check endpoint para Railway (liveness).

    Siempre responde `status: "ok"` para no tumbar el deploy — la app arranca
    aunque las migraciones fallen (decisión deliberada). Incluye un resumen del
    estado de migraciones para ver el drift de un vistazo; el detalle vive en
    `/health/migrations`.
    """
    import migration_state
    mig = migration_state.get_status()
    return {
        "status": "ok",
        "migrations": {"checked": mig["checked"], "ok": mig["ok"]},
    }


@app.get("/health/frontend", include_in_schema=False)
def health_frontend():
    """Readiness del SPA para el healthcheck de Railway.

    503 si el `dist` del frontend NO está donde el backend lo sirve (`FRONT_NEW`).
    Así un deploy que no puede servir el SPA (ej. la regresión de paths #930, o un
    `COPY` de dist roto) **falla el healthcheck y NO se promueve** — ni en staging
    ni en prod. A diferencia de `/health` (siempre 200, para tolerar fallos de
    migración a propósito), esto SÍ tumba el deploy si el SPA no se sirve.
    """
    if (FRONT_NEW / "index.html").is_file():
        return {"status": "ok", "frontend": "served"}
    return JSONResponse(
        {"status": "error", "frontend": "not_built", "expected": str(FRONT_NEW)},
        status_code=503,
    )


@app.get("/health/migrations", include_in_schema=False)
def health_migrations():
    """Estado detallado de las migraciones Alembic: revisión aplicada vs head
    esperado, y el error si el `upgrade head` del arranque falló.

    Pensado para chequear sin entrar a los logs de Railway si la BD quedó
    trabada en una revisión vieja (ver docs/RUNBOOK_MIGRACIONES.md). Responde
    200 siempre; mirar el campo `ok`.
    """
    import migration_state
    return migration_state.get_status()

# ── Páginas ──────────────────────────────────────────────────────────────────

def _serve_frontend(path: str = "index.html"):
    """Helper: sirve desde FRONT_NEW (Vite SPA) o FRONT (clásico) si existe."""
    new_file = FRONT_NEW / path
    if new_file.exists():
        return FileResponse(str(new_file))
    classic_file = FRONT / path
    if classic_file.exists():
        return FileResponse(str(classic_file))
    spa_index = FRONT_NEW / "index.html"
    if spa_index.exists():
        return FileResponse(str(spa_index))
    return JSONResponse({"error": "Frontend not built"}, status_code=503)

@app.get("/", include_in_schema=False)
def root():
    """Home. Inyecta el `og:image` configurado (`app_settings.og_image_url`) en el
    index.html servido, para los crawlers de WhatsApp/redes que NO ejecutan JS (el
    SPA lo lee en runtime, pero el bot solo ve el `<head>` estático → sin esto
    mostraba el `/icon-512.png` hardcodeado). Ante cualquier error sirve el index
    plano — nunca rompe la home."""
    try:
        index_file = FRONT_NEW / "index.html"
        if not index_file.exists():
            return _serve_frontend("index.html")
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = %s", ("og_image_url",)
            ).fetchone()
            # Foto principal del estudio = LCP del home (misma fuente y orden que
            # `useHeroPhotos`: es_principal DESC, orden ASC). Se preloadea para que
            # sea descubrible en el HTML inicial.
            hero_row = conn.execute(
                "SELECT url, url_sm, url_avif, url_sm_avif FROM estudio_fotos WHERE estudio_id = 1 "
                "ORDER BY es_principal DESC, orden ASC, id ASC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        html_text = index_file.read_text(encoding="utf-8")
        hero_url = (hero_row["url"].strip() if hero_row and hero_row["url"] else "")
        hero_sm = (hero_row["url_sm"].strip() if hero_row and hero_row["url_sm"] else "")
        hero_avif = (hero_row["url_avif"].strip() if hero_row and hero_row["url_avif"] else "")
        hero_sm_avif = (hero_row["url_sm_avif"].strip() if hero_row and hero_row["url_sm_avif"] else "")
        if hero_url.startswith("http"):
            html_text = _inject_hero_preload(
                html_text, hero_url, hero_sm or None,
                hero_avif or None, hero_sm_avif or None,
            )
        image = (row["value"].strip() if row and row["value"] else "")
        if image.startswith("http"):
            html_text = _set_og_image(html_text, image)
        return HTMLResponse(content=html_text)
    except Exception:
        logger.warning("OG injection de la home falló — sirvo index plano", exc_info=True)
        return _serve_frontend("index.html")

def _branding_redirect(setting_key: str, static_path: str):
    """Redirige a la URL de R2 del asset de branding si está configurada.
    Si no, el catch-all sirve el archivo estático del repo como fallback."""
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = %s", (setting_key,)
            ).fetchone()
        finally:
            conn.close()
        if row and row["value"] and row["value"].strip().startswith("http"):
            return RedirectResponse(row["value"].strip(), status_code=302)
    except Exception:
        pass
    return _serve_frontend(static_path)


@app.get("/favicon.png", include_in_schema=False)
def favicon_png():
    """Favicon — redirige al PNG derivado del motor de branding (R2) si existe."""
    return _branding_redirect("favicon_url", "favicon.png")


@app.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon():
    """Apple touch icon — redirige al PNG derivado del motor de branding (R2) si existe."""
    return _branding_redirect("apple_touch_icon_url", "apple-touch-icon.png")


@app.get("/icon-512.png", include_in_schema=False)
def icon_512():
    """Ícono 512×512 — redirige al PNG derivado del motor de branding (R2) si existe."""
    return _branding_redirect("icon_512_url", "icon-512.png")


@app.get("/login", include_in_schema=False)
def login_page():
    # El login del admin vive en el SPA en /admin/login.
    return RedirectResponse("/admin/login", status_code=307)

@app.get("/admin", include_in_schema=False)
def admin():
    return _serve_frontend("admin.html")

def _inject_og_meta(html_text: str, *, title: str, description: str, image: str, url: str) -> str:
    """Reemplaza los meta OG/Twitter del index.html con los de un equipo puntual."""
    def _set(text: str, attr: str, key: str, value: str) -> str:
        pat = re.compile(r'(<meta\s+' + attr + r'="' + re.escape(key) + r'"\s+content=")[^"]*(")')
        return pat.sub(lambda m: m.group(1) + _html.escape(value, quote=True) + m.group(2), text, count=1)

    for attr, key, value in (
        ("property", "og:title", title),
        ("property", "og:description", description),
        ("property", "og:image", image),
        ("property", "og:url", url),
        ("name", "twitter:title", title),
        ("name", "twitter:description", description),
        ("name", "twitter:image", image),
    ):
        html_text = _set(html_text, attr, key, value)
    html_text = re.sub(r"<title>[^<]*</title>", "<title>" + _html.escape(title) + "</title>", html_text, count=1)
    return html_text


def _inject_hero_preload(
    html_text: str,
    image: str,
    image_sm: str | None = None,
    image_avif: str | None = None,
    image_sm_avif: str | None = None,
) -> str:
    """Inserta `<link rel=preconnect>` al origen R2 + `<link rel=preload as=image
    fetchpriority=high>` del hero del home justo antes de `</head>`. La URL del hero
    sale de un query async (`useHeroPhotos`), así que sin esto el LCP no es descubrible
    en el HTML inicial — el browser no puede arrancar el fetch hasta correr el JS +
    responder la API (LCP ~21s en Lighthouse).

    Preloadeamos el AVIF cuando la foto principal lo tiene (`type=image/avif`): el hero
    se renderiza con `<img src=avif>` directo (NO `<picture>`), así que el preload AVIF
    matchea el elemento LCP de forma determinista — los browsers sin soporte AVIF ignoran
    el preload y caen a webp vía `onError` (helper `heroImgProps` en el front). Esto
    espeja la decisión del front sobre la MISMA foto (mismo orden es_principal DESC,
    orden ASC, id ASC) → preload y `<img>` apuntan al mismo recurso, una sola descarga.

    Si la principal NO tiene AVIF (NULL: subida pre-backfill o codec falló), caemos al
    preload webp. El `imagesizes="100vw"` matchea EXACTO el `sizes` del `<img>` del hero
    (mobile y desktop unificados) — Lighthouse mide el LCP mobile, que usa 100vw. El
    preconnect abre la conexión TLS al bucket R2 antes del fetch."""
    # Origen del bucket R2 (https://host) derivado de la URL del hero — sin hardcodear
    # el bucket, robusto ante cambios de ambiente.
    origin = "/".join(image.split("/")[:3])
    tags = ""
    if origin.startswith("http"):
        esc_origin = _html.escape(origin, quote=True)
        tags += f'<link rel="preconnect" href="{esc_origin}">'

    if image_avif:
        # AVIF-directo: el hero renderiza `<img src=avif>`, así que el preload AVIF
        # matchea el LCP. `type=image/avif` es obligatorio para que el browser lo trate
        # como AVIF y los que no lo soportan lo ignoren (caen a webp vía onError).
        esc_avif = _html.escape(image_avif, quote=True)
        if image_sm_avif:
            esc_sm_avif = _html.escape(image_sm_avif, quote=True)
            tags += (
                f'<link rel="preload" as="image" type="image/avif" fetchpriority="high"'
                f' imagesrcset="{esc_sm_avif} 800w, {esc_avif} 1600w"'
                f' imagesizes="100vw">'
            )
        else:
            tags += (
                f'<link rel="preload" as="image" type="image/avif"'
                f' fetchpriority="high" href="{esc_avif}">'
            )
    else:
        # Sin AVIF → preload webp (el front también renderiza webp en este caso).
        esc = _html.escape(image, quote=True)
        if image_sm:
            esc_sm = _html.escape(image_sm, quote=True)
            tags += (
                f'<link rel="preload" as="image" fetchpriority="high"'
                f' imagesrcset="{esc_sm} 800w, {esc} 1600w"'
                f' imagesizes="100vw">'
            )
        else:
            tags += f'<link rel="preload" as="image" fetchpriority="high" href="{esc}">'
    return html_text.replace("</head>", tags + "</head>", 1)


def _set_og_image(html_text: str, image: str) -> str:
    """Reemplaza SOLO `og:image` + `twitter:image` del index.html (el resto del
    `<head>` de la home ya es correcto). Mismo patrón que `_inject_og_meta`."""
    esc = _html.escape(image, quote=True)
    for attr, key in (("property", "og:image"), ("name", "twitter:image")):
        pat = re.compile(r'(<meta\s+' + attr + r'="' + re.escape(key) + r'"\s+content=")[^"]*(")')
        html_text = pat.sub(lambda m: m.group(1) + esc + m.group(2), html_text, count=1)
    return html_text


def _inject_json_ld(html_text: str, *schemas: dict) -> str:
    """Inserta uno o más bloques JSON-LD justo antes de </head>.

    Los crawlers/agentes que no ejecutan JS (Googlebot light, LLM indexers)
    ven el structured data directamente en el HTML inicial — sin esperar JS.
    Cada schema se emite en un <script> separado para facilitar el debug.

    `data-ssr-jsonld` marca estos scripts como server-injectados: la ruta
    cliente (equipo/escuelas/categoria) declara el MISMO JSON-LD de nuevo vía
    head() para cuando SÍ hay JS — sin el atributo, `main.tsx` no podría
    diferenciarlos de los estáticos (WebSite/LocalBusiness en index.html, sin
    equivalente client-side) al barrerlos antes de montar, y quedarían
    duplicados post-hidratación (mismo bug de clase que title/OG, 2026-08-13).
    """
    tags = "".join(
        f'<script type="application/ld+json" data-ssr-jsonld="1">{json.dumps(s, ensure_ascii=False)}</script>'
        for s in schemas
    )
    return html_text.replace("</head>", tags + "</head>", 1)


def _faq_page_schema(qa_pairs: list[tuple[str, str]]) -> dict | None:
    """Arma el JSON-LD `FAQPage` a partir de pares (pregunta, respuesta) ya
    resueltos por el caller (cada fuente de FAQ tiene su propia forma —
    grupos anidados en `app_settings.faq_json`, plano en `estudio.faq_json`/
    `talleres.faqs` — normalizarla es responsabilidad de quien llama).
    Filtra pares vacíos; `None` si no queda ninguno (nada que inyectar)."""
    items = [
        {
            "@type": "Question",
            "name": q.strip(),
            "acceptedAnswer": {"@type": "Answer", "text": a.strip()},
        }
        for q, a in qa_pairs
        if q and q.strip() and a and a.strip()
    ]
    if not items:
        return None
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": items}


def _get_initial_catalog(conn) -> dict:
    """Serializa equipos visibles + categorías para el script __INITIAL__ del catálogo.

    Delegated to services.catalogo.proyectar_seed (puerta única).
    """
    return proyectar_seed(conn)


def _inject_initial_data(html_text: str, data: dict) -> str:
    """Inyecta <script id="__INITIAL__" type="application/json"> antes de </body>.

    El frontend lo consume en main.tsx para pre-poblar React Query sin round-trip.
    Se escapa </script> dentro del payload para no romper el parser HTML.
    """
    payload = json.dumps(data, ensure_ascii=False, default=str)
    payload = payload.replace("</script>", r"<\/script>")
    script_tag = f'<script id="__INITIAL__" type="application/json">{payload}</script>'
    return html_text.replace("</body>", script_tag + "</body>", 1)


@app.get("/rental", include_in_schema=False)
def rental_page():
    """Catálogo público. Inyecta:
    - Hero preload (LCP del catálogo — misma fuente y orden que useHeroPhotos)
    - __INITIAL__ con equipos + categorías para hydration de React Query (sin round-trip)

    Ante cualquier error sirve el index.html plano — el SPA fetchea normalmente.
    """
    try:
        index_file = FRONT_NEW / "index.html"
        if not index_file.exists():
            return _serve_frontend("index.html")
        conn = get_db()
        try:
            hero_row = conn.execute(
                "SELECT url, url_sm, url_avif, url_sm_avif FROM estudio_fotos WHERE estudio_id = 1 "
                "ORDER BY es_principal DESC, orden ASC, id ASC LIMIT 1"
            ).fetchone()
            initial_data = _get_initial_catalog(conn)
        finally:
            conn.close()
        html_text = index_file.read_text(encoding="utf-8")
        hero_url = (hero_row["url"].strip() if hero_row and hero_row["url"] else "")
        hero_sm = (hero_row["url_sm"].strip() if hero_row and hero_row["url_sm"] else "")
        hero_avif = (hero_row["url_avif"].strip() if hero_row and hero_row["url_avif"] else "")
        hero_sm_avif = (hero_row["url_sm_avif"].strip() if hero_row and hero_row["url_sm_avif"] else "")
        if hero_url.startswith("http"):
            html_text = _inject_hero_preload(
                html_text, hero_url, hero_sm or None,
                hero_avif or None, hero_sm_avif or None,
            )
        html_text = _inject_initial_data(html_text, initial_data)
        return HTMLResponse(content=html_text)
    except Exception:
        logger.warning("rental_page: inyección falló — sirvo index plano", exc_info=True)
        return _serve_frontend("index.html")


def _nombre_equipo_publico(d: dict) -> str:
    """Nombre público a mostrar de un equipo: `nombre_publico` si está cargado,
    si no `marca + nombre` (sin duplicar la marca cuando ya forma parte del
    nombre base). Fuente única — usado por `equipo_page` y `categoria_page`
    para que el nombre en JSON-LD/OG sea el mismo en ambas rutas."""
    nombre = (d.get("nombre_publico") or "").strip()
    if nombre:
        return nombre
    marca = (d.get("marca") or "").strip()
    base = (d.get("nombre") or "").strip()
    return f"{marca} {base}".strip() if marca and marca.lower() not in base.lower() else base


@app.get("/equipo/{id_or_slug}", include_in_schema=False)
def equipo_page(id_or_slug: str):
    """Sirve el SPA para la ficha del equipo.

    Acepta id puro (`47`) o slug-id (`sony-fx3-47`) — antes exigía `int`, así que
    una URL con slug (la que genera el botón Compartir) tiraba 422 (#637-adyacente).
    Además inyecta los meta OG/Twitter del equipo en el HTML server-side para que
    los crawlers de WhatsApp/redes (que NO ejecutan JS) muestren la foto y el
    nombre reales en la preview del link. Ante cualquier error cae al index.html
    plano — nunca rompe la página.
    """
    try:
        m = re.search(r"(\d+)$", id_or_slug)
        index_file = FRONT_NEW / "index.html"
        if not m or not index_file.exists():
            return _serve_frontend("index.html")
        equipo_id = int(m.group(1))
        conn = get_db()
        try:
            row = conn.execute(
                f"""
                SELECT e.nombre, e.foto_url, e.nombre_publico,
                       e.precio_jornada, e.cantidad,
                       {MARCA_SUBQUERY},
                       ef.descripcion
                FROM equipos e
                LEFT JOIN equipo_fichas ef ON ef.equipo_id = e.id
                WHERE e.id = %s
                """,
                (equipo_id,),
            ).fetchone()
            # Variante OG (jpg) de la foto principal — la que WhatsApp sí renderiza.
            og_row = conn.execute(
                """
                SELECT mv.url FROM equipo_fotos ef
                JOIN media_variants mv ON mv.asset_id = ef.media_id
                WHERE ef.equipo_id = %s AND mv.name = 'og'
                ORDER BY ef.es_principal DESC, ef.orden ASC, ef.id ASC
                LIMIT 1
                """,
                (equipo_id,),
            ).fetchone()
            # Primera categoría del equipo (para BreadcrumbList).
            from services.categorias import categorias_de_equipos
            cat_map = categorias_de_equipos(conn, [equipo_id])
            cat_list = cat_map.get(equipo_id, [])
            cat_row = {"nombre": cat_list[0]["nombre"]} if cat_list else None
        finally:
            conn.close()
        if not row:
            return _serve_frontend("index.html")
        d = row_to_dict(row)
        nombre = _nombre_equipo_publico(d)
        title = f"{nombre} — Rambla Rental" if nombre else "Rambla Rental"
        desc = (d.get("descripcion") or "").strip()
        if len(desc) > 200:
            desc = desc[:197].rstrip() + "…"
        if not desc:
            desc = f"Alquilá {nombre} en Rambla Rental, Mar del Plata." if nombre else "Alquiler de equipos audiovisuales en Mar del Plata."
        # Preferir la variante OG (jpg) de la principal; fallback a foto_url (webp)
        # para fotos que todavía no tienen og (pre-backfill).
        og_url = (og_row["url"] if og_row else "") or ""
        if og_url.startswith("http"):
            image = og_url
        else:
            foto = (d.get("foto_url") or "").strip()
            image = foto if foto.startswith("http") else (f"{SITE_URL}{foto}" if foto else f"{SITE_URL}/og-image.png")
        url = f"{SITE_URL}/equipo/{id_or_slug}"
        html_text = _inject_og_meta(
            index_file.read_text(encoding="utf-8"),
            title=title, description=desc, image=image, url=url,
        )
        # JSON-LD server-side: Product + BreadcrumbList. Visible para crawlers
        # que no ejecutan JS (Googlebot light, LLM indexers, bots de precios).
        precio = d.get("precio_jornada")
        cantidad = d.get("cantidad") or 0
        marca_str = (d.get("marca") or "").strip()
        cat_nombre = (cat_row["nombre"] if cat_row else "").strip()
        product_schema: dict = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": nombre,
            "description": desc,
            "url": url,
            "image": image,
        }
        if marca_str:
            product_schema["brand"] = {"@type": "Brand", "name": marca_str}
        if cat_nombre:
            product_schema["category"] = cat_nombre
        if precio is not None:
            product_schema["offers"] = {
                "@type": "Offer",
                "priceCurrency": "ARS",
                "price": precio,
                "availability": "https://schema.org/InStock" if cantidad > 0 else "https://schema.org/OutOfStock",
                "priceSpecification": {
                    "@type": "UnitPriceSpecification",
                    "price": precio,
                    "priceCurrency": "ARS",
                    "unitText": "jornada",
                },
            }
        breadcrumb_items = [{"@type": "ListItem", "position": 1, "name": "Inicio", "item": f"{SITE_URL}/"}]
        if cat_nombre:
            breadcrumb_items.append({
                "@type": "ListItem", "position": 2,
                "name": cat_nombre,
                "item": f"{SITE_URL}/categoria/{_cat_slug(cat_nombre)}",
            })
        breadcrumb_items.append({
            "@type": "ListItem", "position": len(breadcrumb_items) + 1,
            "name": nombre, "item": url,
        })
        breadcrumb_schema = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": breadcrumb_items,
        }
        html_text = _inject_json_ld(html_text, product_schema, breadcrumb_schema)
        return HTMLResponse(content=html_text)
    except Exception:
        logger.warning("OG injection falló para /equipo/%s — sirvo index plano", id_or_slug, exc_info=True)
        return _serve_frontend("index.html")


@app.get("/categoria/{slug}", include_in_schema=False)
def categoria_page(slug: str):
    """Sirve el SPA para la página de categoría (ej. /categoria/lentes).

    Antes esta ruta dependía 100% de dos fetches client-side (/api/categorias
    + /api/equipos) para título/OG/JSON-LD Y el listado visible — invisible
    para cualquier bot que no ejecuta JS (la mayoría de los crawlers de IA) y
    también para el pase de render de Google, al que `robots.txt` le bloquea
    justamente `/api/`. Mismo patrón que `equipo_page`/`workshop_page`:
    inyecta OG/Twitter + CollectionPage/BreadcrumbList server-side, sin
    depender de JS. Ante cualquier error o slug inexistente cae al index.html
    plano — el SPA (`categoria.$slug.tsx`) resuelve normal.
    """
    try:
        index_file = FRONT_NEW / "index.html"
        if not index_file.exists():
            return _serve_frontend("index.html")
        conn = get_db()
        try:
            categorias = conn.execute(
                "SELECT id, nombre FROM categorias WHERE COALESCE(visible, true) = true"
            ).fetchall()
            categoria = next(
                (c for c in categorias if _cat_slug(c["nombre"]) == slug), None
            )
            if not categoria:
                return _serve_frontend("index.html")
            equipos = conn.execute(
                f"""
                SELECT e.id, {MARCA_SUBQUERY}, e.nombre, e.nombre_publico
                FROM equipos e
                JOIN equipo_categorias ec ON ec.equipo_id = e.id
                WHERE ec.categoria_id = %s
                  AND e.visible_catalogo = 1 AND e.estado != 'fuera_servicio'
                  AND e.es_recurso_interno = FALSE
                  AND e.eliminado_at IS NULL
                ORDER BY e.relevancia_manual ASC, e.popularidad_score DESC, e.nombre ASC
                """,
                (categoria["id"],),
            ).fetchall()
        finally:
            conn.close()
        nombre = categoria["nombre"]
        url = f"{SITE_URL}/categoria/{slug}"
        title = f"Alquiler de {nombre} — Rambla Rental"
        desc = (
            f"Alquilá {nombre.lower()} para tu próxima producción en Rambla Rental, Mar del Plata. "
            f"Más de {len(equipos)} equipos disponibles, por jornada."
        )
        image = f"{SITE_URL}/icon-512.png"
        html_text = _inject_og_meta(
            index_file.read_text(encoding="utf-8"),
            title=title, description=desc[:160], image=image, url=url,
        )
        breadcrumb_schema = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Inicio", "item": f"{SITE_URL}/"},
                {"@type": "ListItem", "position": 2, "name": nombre, "item": url},
            ],
        }
        item_list = []
        for i, r in enumerate(equipos[:20]):
            d = row_to_dict(r)
            eq_nombre = _nombre_equipo_publico(d)
            eq_slug = _eq_slug(d.get("marca"), d.get("nombre"), d["id"])
            item_list.append({
                "@type": "ListItem",
                "position": i + 1,
                "url": f"{SITE_URL}/equipo/{eq_slug}",
                "name": eq_nombre,
            })
        collection_schema = {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": title,
            "description": desc,
            "url": url,
            "mainEntity": {
                "@type": "ItemList",
                "numberOfItems": len(equipos),
                "itemListElement": item_list,
            },
        }
        html_text = _inject_json_ld(html_text, breadcrumb_schema, collection_schema)
        return HTMLResponse(content=html_text)
    except Exception:
        logger.warning("categoria_page: inyección falló para /categoria/%s — sirvo index plano", slug, exc_info=True)
        return _serve_frontend("index.html")


@app.get("/c/{token}", include_in_schema=False)
def compartido_page(token: str):
    """Sirve el SPA para un carrito compartido (/c/<token>) inyectando los meta
    OG/Twitter server-side, para que la preview de WhatsApp/redes (que NO ejecuta
    JS) muestre el título y los equipos reales del link (feature #4, #1092).

    La composición se resuelve EN VIVO contra el catálogo (nombre/foto actuales),
    consistente con el rearmado del carrito. Ante cualquier error o token
    inexistente cae al index.html plano — el SPA (`c.$token.tsx`) maneja el
    "link no encontrado" con su propia UI.
    """
    try:
        index_file = FRONT_NEW / "index.html"
        if not index_file.exists():
            return _serve_frontend("index.html")
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT titulo, items_json FROM carritos_compartidos WHERE token = %s",
                (token,),
            ).fetchone()
            if not row:
                return _serve_frontend("index.html")
            raw = row["items_json"]
            items = raw if isinstance(raw, list) else json.loads(raw or "[]")
            ids = [int(it["equipo_id"]) for it in items if it.get("equipo_id") is not None]
            titulo = (row["titulo"] or "").strip()
            equipos: dict = {}
            if ids:
                # alias `e` + MARCA_SUBQUERY por convención de queries de equipos (MEMORIA 2026-05-26)
                filas = conn.execute(
                    f"SELECT e.id, e.nombre, e.nombre_publico, e.foto_url, {MARCA_SUBQUERY}"
                    " FROM equipos e WHERE e.id = ANY(%s)",
                    (ids,),
                ).fetchall()
                equipos = {f["id"]: row_to_dict(f) for f in filas}
        finally:
            conn.close()

        def _nombre(d: dict) -> str:
            n = (d.get("nombre_publico") or "").strip()
            if n:
                return n
            marca = (d.get("marca") or "").strip()
            base = (d.get("nombre") or "").strip()
            return f"{marca} {base}".strip() if marca and marca.lower() not in base.lower() else base

        nombres = [_nombre(equipos[i]) for i in ids if i in equipos]
        n = len(nombres)
        # El título y la descripción enmarcan QUÉ es el link —te compartieron un listado para
        # armar un pedido—, no solo la marca ni la lista cruda de equipos. Así la preview de
        # WhatsApp le explica el link a quien lo recibe (caso gaffer → productor: "reservá esto").
        if titulo:
            title = f"{titulo} — listado de equipos · Rambla Rental"
        else:
            title = "Te compartieron un listado de equipos · Rambla Rental"
        if nombres:
            shown = ", ".join(nombres[:3])
            extra = n - 3
            if extra > 0:
                shown += f" y {extra} más"
            unidades = "1 equipo" if n == 1 else f"{n} equipos"
            # Cada línea aporta algo distinto y complementario: el título enmarca ("Te compartieron
            # un listado"), la descripción lista el CONTENIDO + dónde, y el mensaje de chat (front)
            # lleva la ACCIÓN ("Abrilo y reservalo"). Acá NO repetimos el arranque del título.
            desc = f"{unidades}: {shown} — para alquilar en Mar del Plata."
        else:
            desc = "Una selección de equipos para alquilar en Rambla Rental, Mar del Plata."
        if len(desc) > 200:
            desc = desc[:197].rstrip() + "…"
        # Imagen: la isologo de marca estática (og-image.png, 1200×630 ya encuadrada para OG). Un
        # listado compartido se presenta con la marca Rambla — no la foto de un equipo suelto, ni el
        # og_image_url de la home (un wordmark a sangre que WhatsApp recorta al centro → "MB").
        image = f"{SITE_URL}/og-image.png"
        url = f"{SITE_URL}/c/{token}"
        html_text = _inject_og_meta(
            index_file.read_text(encoding="utf-8"),
            title=title, description=desc, image=image, url=url,
        )
        return HTMLResponse(content=html_text)
    except Exception:
        logger.warning("OG injection falló para /c/%s — sirvo index plano", token, exc_info=True)
        return _serve_frontend("index.html")

@app.get("/cliente", include_in_schema=False)
def cliente_login_page():
    return _serve_frontend("cliente.html")

@app.get("/cliente/portal", include_in_schema=False)
def cliente_portal_page():
    return _serve_frontend("cliente/portal.html")

@app.get("/cliente/registro", include_in_schema=False)
def cliente_registro_page():
    return _serve_frontend("cliente/registro.html")


@app.get("/estudio", include_in_schema=False)
def estudio_page():
    """Sirve el SPA del estudio con OG tags dinámicos (foto principal del estudio).
    Ante cualquier error sirve el index.html plano — nunca rompe la página."""
    try:
        index_file = FRONT_NEW / "index.html"
        if not index_file.exists():
            return _serve_frontend("index.html")
        conn = get_db()
        try:
            cfg = conn.execute(
                "SELECT nombre, tagline, descripcion, faq_json FROM estudio WHERE id = 1"
            ).fetchone()
            # Foto principal del estudio — preferir variante OG (jpg); fallback a url
            foto_row = conn.execute(
                """
                SELECT COALESCE(mv.url, ef.url) AS img_url
                FROM estudio_fotos ef
                LEFT JOIN media_variants mv ON mv.asset_id = ef.media_id AND mv.name = 'og'
                WHERE ef.estudio_id = 1
                ORDER BY ef.es_principal DESC, ef.orden ASC, ef.id ASC
                LIMIT 1
                """
            ).fetchone()
        finally:
            conn.close()
        nombre = (cfg["nombre"] if cfg else "") or "El Estudio"
        tagline = (cfg["tagline"] if cfg else "") or ""
        desc_raw = (cfg["descripcion"] if cfg else "") or tagline
        desc = desc_raw.strip()
        if len(desc) > 200:
            desc = desc[:197].rstrip() + "…"
        if not desc:
            desc = "Estudio de foto y video en Mar del Plata. Reservá por hora con todo el equipo incluido."
        title = f"{nombre} — Rambla Rental"
        img = (foto_row["img_url"] if foto_row else "") or ""
        if not img.startswith("http"):
            img = f"{SITE_URL}/og-image.png"
        html_text = _inject_og_meta(
            index_file.read_text(encoding="utf-8"),
            title=title, description=desc, image=img, url=f"{SITE_URL}/estudio",
        )
        # FAQPage — mismo `faq_json` que ya muestra la página (editable desde
        # el admin); condicionado a que haya contenido real, no un schema vacío.
        faq_items = _parse_json_field(cfg["faq_json"]) if cfg else None
        faq_schema = _faq_page_schema(
            [(it.get("q", ""), it.get("a", "")) for it in (faq_items or [])]
        )
        if faq_schema:
            html_text = _inject_json_ld(html_text, faq_schema)
        return HTMLResponse(content=html_text)
    except Exception:
        logger.warning("OG injection falló para /estudio — sirvo index plano", exc_info=True)
        return _serve_frontend("index.html")


@app.get("/escuelas/{slug}", include_in_schema=False)
@app.get("/escuela/{slug}", include_in_schema=False)  # alias viejo (singular): el front lo redirige a /escuelas, acá sirve OG para scrapers
@app.get("/workshops/{slug}", include_in_schema=False)  # alias más viejo: el front lo redirige a /escuelas, acá sirve OG para scrapers
def workshop_page(slug: str, request: Request):
    """Sirve el SPA del taller con OG tags dinámicos (foto del instructor),
    JSON-LD `Course` y el preload del hero (LCP). Ante cualquier error sirve
    el index.html plano — nunca rompe la página.

    `slug` es el de la EDICIÓN (mismo que resuelve `GET /talleres/{slug}` vía
    `ediciones_taller.slug` — no `talleres.slug`, el del CONCEPTO, que solo
    coincide por convención para la 1ª edición). Escuela v2 F6: fechas/precio
    salen de `ediciones_taller`, instructor de `instructores` (las columnas
    legacy que antes vivían en `talleres` ya no existen).

    Visibilidad de un BORRADOR (`activo=FALSE`) — reusa `_get_edicion_row`
    (`routes/talleres.py`), la MISMA puerta que `GET /talleres/{slug}`: en
    prod, solo lo ve una sesión admin; en `dev`/local con `ADMIN_BYPASS_AUTH`
    lo ve cualquiera (igual que ya ve la página del SPA). Antes esta ruta
    filtraba `activo=TRUE` a mano, sin ese bypass — un taller en borrador
    servía la página bien (la API SÍ respetaba el bypass) pero SIEMPRE con el
    OG genérico del sitio, aunque quien comparte el link en staging esté
    viendo el borrador real (encontrado con el taller de Ariel Perissinotti,
    aún sin publicar)."""
    try:
        index_file = FRONT_NEW / "index.html"
        if not index_file.exists():
            return _serve_frontend("index.html")
        from auth.guards import is_admin_email
        from auth.session import dev_bypass_enabled, get_session
        from routes.talleres import _get_edicion_row

        session = get_session(request)
        es_admin = dev_bypass_enabled() or bool(session and is_admin_email(session.get("email")))
        conn = get_db()
        try:
            try:
                taller = _get_edicion_row(conn, slug, incluir_borrador=es_admin)
            except HTTPException:
                return _serve_frontend("index.html")
            instructor_row = conn.execute(
                "SELECT i.nombre, i.foto_url, i.foto_media_id "
                "FROM taller_instructores ti JOIN instructores i ON i.id = ti.instructor_id "
                "WHERE ti.taller_id = %s ORDER BY ti.orden, i.id LIMIT 1",
                (taller["taller_id"],),
            ).fetchone()
            # Institución co-presentadora — gana como identidad del OG/título
            # sobre el instructor cuando el taller tiene una vinculada (pedido
            # del dueño: compartir "Taller X... con Mila" leía raro para un
            # taller co-presentado por una institución — la marca del hub
            # tiene que ganar). Mismo orden que `_get_instituciones_taller`
            # (ti.orden, ins.id): la PRIMERA vinculada, no todas.
            institucion_row = conn.execute(
                "SELECT ins.id, ins.nombre, ins.logo_url "
                "FROM taller_instituciones ti JOIN instituciones ins ON ins.id = ti.institucion_id "
                "WHERE ti.taller_id = %s ORDER BY ti.orden, ins.id LIMIT 1",
                (taller["taller_id"],),
            ).fetchone()
            # Foto OG: institución (foto destacada de su galería, después su
            # logo) gana sobre el instructor — mismo orden de preferencia que
            # `institucion_page` usa para el hub. El instructor solo entra si
            # el taller NO tiene institución vinculada.
            og_img = ""
            if institucion_row:
                ins_foto_row = conn.execute(
                    "SELECT url FROM institucion_fotos "
                    "WHERE institucion_id = %s AND es_principal = TRUE LIMIT 1",
                    (institucion_row["id"],),
                ).fetchone()
                og_img = (ins_foto_row["url"].strip() if ins_foto_row and ins_foto_row["url"] else "")
                if not og_img:
                    og_img = (institucion_row["logo_url"] or "").strip()
            if not og_img:
                # Foto OG del instructor: preferir variante 'og' del media;
                # fallback a 'display' o foto_url (foto subida antes del motor).
                media_id = instructor_row["foto_media_id"] if instructor_row else None
                if media_id:
                    mv = conn.execute(
                        "SELECT url FROM media_variants "
                        "WHERE asset_id = %s AND name IN ('og', 'display') "
                        "ORDER BY CASE name WHEN 'og' THEN 0 ELSE 1 END LIMIT 1",
                        (media_id,),
                    ).fetchone()
                    og_img = (mv["url"] if mv else "") or ""
                if not og_img and instructor_row:
                    og_img = instructor_row["foto_url"] or ""
            # Hero preload — misma fuente y orden que TallerGaleria.tsx
            # (es_principal DESC, orden ASC, id ASC): la portada de la
            # galería es el LCP de la página del taller, igual que
            # estudio_fotos lo es para la home/rental.
            hero_row = conn.execute(
                "SELECT url, url_sm, url_avif, url_sm_avif FROM edicion_fotos "
                "WHERE edicion_id = %s ORDER BY es_principal DESC, orden ASC, id ASC LIMIT 1",
                (taller["id"],),
            ).fetchone()
        finally:
            conn.close()
        nombre = (taller["nombre"] or "").strip()
        instructor = (instructor_row["nombre"] or "").strip() if instructor_row else ""
        institucion_nombre = (institucion_row["nombre"] or "").strip() if institucion_row else ""
        # Identidad del título/descripción: institución primero (si el
        # taller la tiene vinculada), instructor si no — mismo criterio que
        # el de la foto OG de arriba.
        identidad = institucion_nombre or instructor
        desc_raw = (taller["descripcion"] or "").strip()
        if len(desc_raw) > 200:
            desc_raw = desc_raw[:197].rstrip() + "…"
        if not desc_raw:
            desc_raw = f"Taller con {identidad} en Rambla, Mar del Plata." if identidad else "Talleres audiovisuales en Mar del Plata."
        title = f"{nombre} con {identidad} — Rambla" if identidad else f"{nombre} — Rambla"
        if not og_img.startswith("http"):
            # og-image.png (1200×630, ya encuadrada para OG) — no icon-512.png
            # (ícono cuadrado): el mismo bug ya se había corregido en /c/{token}
            # y en la home (ver sus comentarios), pero acá seguía sin
            # arreglarse — WhatsApp lo mostraba como el logo gigante sin
            # contexto (taller de Ariel Perissinotti, sin foto de instructor
            # cargada todavía).
            og_img = f"{SITE_URL}/og-image.png"
        taller_url = f"{SITE_URL}/escuelas/{slug}"
        html_text = _inject_og_meta(
            index_file.read_text(encoding="utf-8"),
            title=title, description=desc_raw, image=og_img, url=taller_url,
        )
        hero_url = (hero_row["url"].strip() if hero_row and hero_row["url"] else "")
        hero_sm = (hero_row["url_sm"].strip() if hero_row and hero_row["url_sm"] else "")
        hero_avif = (hero_row["url_avif"].strip() if hero_row and hero_row["url_avif"] else "")
        hero_sm_avif = (hero_row["url_sm_avif"].strip() if hero_row and hero_row["url_sm_avif"] else "")
        if hero_url.startswith("http"):
            html_text = _inject_hero_preload(
                html_text, hero_url, hero_sm or None,
                hero_avif or None, hero_sm_avif or None,
            )
        # JSON-LD Course schema — visible para crawlers/agentes sin JS. `Course`
        # (no `Event`) porque es el tipo que Google trata distinto cuando alguien
        # busca "cursos"/"talleres" (rich result propio); `CourseInstance` sigue
        # llevando fecha/lugar/instructor (es subtipo de Event, no se pierde nada).
        direccion = (taller["direccion"] or "").strip() or "Chaco 1392"
        course_instance: dict = {
            "@type": "CourseInstance",
            "courseMode": "Onsite",
            "location": {
                "@type": "Place",
                "name": "Rambla",
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": direccion,
                    "addressLocality": "Mar del Plata",
                    "addressRegion": "Buenos Aires",
                    "addressCountry": "AR",
                },
            },
        }
        if instructor:
            course_instance["instructor"] = {"@type": "Person", "name": instructor}
        if taller["fecha_inicio"]:
            course_instance["startDate"] = str(taller["fecha_inicio"])[:10]
        if taller["fecha_fin"]:
            course_instance["endDate"] = str(taller["fecha_fin"])[:10]
        course_schema: dict = {
            "@context": "https://schema.org",
            "@type": "Course",
            "name": nombre,
            "description": desc_raw,
            "url": taller_url,
            "image": og_img,
            "provider": {"@type": "Organization", "name": "Rambla", "sameAs": SITE_URL},
            "hasCourseInstance": course_instance,
        }
        if taller["precio_total"] is not None:
            course_schema["offers"] = {
                "@type": "Offer",
                "price": taller["precio_total"],
                "priceCurrency": "ARS",
                "availability": "https://schema.org/InStock",
                "url": taller_url,
                "category": "Free" if taller["precio_total"] == 0 else "Paid",
            }
        schemas = [course_schema]
        # FAQPage — condicionado a que el taller tenga FAQs cargadas (hoy
        # ninguno las tiene todavía, ver FaqSection del admin): empieza a
        # inyectarse solo apenas se cargue contenido, sin tocar código de nuevo.
        faq_schema = _faq_page_schema(
            [(f.get("pregunta", ""), f.get("respuesta", "")) for f in (taller["faqs"] or [])]
        )
        if faq_schema:
            schemas.append(faq_schema)
        html_text = _inject_json_ld(html_text, *schemas)
        return HTMLResponse(content=html_text)
    except Exception:
        logger.warning("OG injection falló para el taller %s — sirvo index plano", slug, exc_info=True)
        return _serve_frontend("index.html")


@app.get("/escuelas/instituciones/{slug}", include_in_schema=False)
def institucion_page(slug: str):
    """Sirve el SPA del hub de institución con OG tags dinámicos (foto
    destacada o logo) + JSON-LD `Organization` — mismo patrón que
    `workshop_page` de acá arriba, para crawlers/agentes que no ejecutan JS
    (WhatsApp entre ellos: sin esto, compartir el link del hub mostraba el
    OG genérico del sitio en vez de la institución real — el `head()` de la
    ruta cliente, `escuelas.instituciones.$slug.tsx`, ya arma lo mismo, pero
    solo aplica DESPUÉS de que React hidrata, y esta app es SPA pura, sin
    SSR). Ante cualquier error sirve el index.html plano — nunca rompe la
    página."""
    try:
        index_file = FRONT_NEW / "index.html"
        if not index_file.exists():
            return _serve_frontend("index.html")
        conn = get_db()
        try:
            ins_row = conn.execute(
                "SELECT id, nombre, descripcion, logo_url FROM instituciones WHERE slug = %s",
                (slug,),
            ).fetchone()
            if ins_row is None:
                return _serve_frontend("index.html")
            foto_row = conn.execute(
                "SELECT url FROM institucion_fotos "
                "WHERE institucion_id = %s AND es_principal = TRUE LIMIT 1",
                (ins_row["id"],),
            ).fetchone()
        finally:
            conn.close()
        nombre = (ins_row["nombre"] or "").strip()
        desc_raw = (ins_row["descripcion"] or "").strip()
        if len(desc_raw) > 200:
            desc_raw = desc_raw[:197].rstrip() + "…"
        if not desc_raw:
            desc_raw = f"Talleres de {nombre} en Rambla, Mar del Plata."
        title = f"Talleres de {nombre} en Rambla"
        # Misma preferencia que el resto de las páginas con OG dinámico: la
        # foto más rica primero (foto_destacada, pensada para una card
        # social), el logo como segunda opción (mejor que nada, aunque su
        # proporción no sea ideal), y recién ahí el genérico del sitio. El
        # `head()` del cliente (mismo route) solo usa el logo porque ahí ya
        # se ve la página real con JS corriendo; acá, sin JS, el `og:image`
        # es lo único que un link preview llega a mostrar.
        og_img = (foto_row["url"].strip() if foto_row and foto_row["url"] else "")
        if not og_img:
            og_img = (ins_row["logo_url"] or "").strip()
        if not og_img.startswith("http"):
            og_img = f"{SITE_URL}/og-image.png"
        institucion_url = f"{SITE_URL}/escuelas/instituciones/{slug}"
        html_text = _inject_og_meta(
            index_file.read_text(encoding="utf-8"),
            title=title, description=desc_raw, image=og_img, url=institucion_url,
        )
        org_schema: dict = {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": nombre,
            "description": desc_raw,
            "url": institucion_url,
        }
        if og_img.startswith("http"):
            org_schema["logo"] = og_img
        html_text = _inject_json_ld(html_text, org_schema)
        return HTMLResponse(content=html_text)
    except Exception:
        logger.warning(
            "OG injection falló para la institución %s — sirvo index plano", slug, exc_info=True
        )
        return _serve_frontend("index.html")


@app.get("/preguntas-frecuentes", include_in_schema=False)
def preguntas_frecuentes_page():
    """Sirve el SPA de preguntas frecuentes, inyectando FAQPage JSON-LD
    server-side cuando el setting `faq_json` (app_settings, editable desde
    /admin/settings → Preguntas frecuentes) está configurado — mismo
    contenido que ya ve un lector con JS (`useFaqGroups`, `data/faq.ts`).

    Si el setting no está seteado, no inyecta nada acá: el fallback
    hardcodeado (`FAQ_GROUPS` en `data/faq.ts`) solo existe del lado
    cliente — duplicarlo acá crearía una segunda copia del mismo texto que
    puede divergir con el tiempo (dos verdades). Ante cualquier error sirve
    el index.html plano — nunca rompe la página.
    """
    try:
        index_file = FRONT_NEW / "index.html"
        if not index_file.exists():
            return _serve_frontend("index.html")
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = %s", ("faq_json",)
            ).fetchone()
        finally:
            conn.close()
        groups = _parse_json_field(row["value"]) if row else None
        faq_schema = _faq_page_schema(
            [
                (it.get("q", ""), it.get("a", ""))
                for g in (groups or [])
                for it in g.get("items", [])
            ]
        )
        if not faq_schema:
            return _serve_frontend("index.html")
        html_text = _inject_json_ld(index_file.read_text(encoding="utf-8"), faq_schema)
        return HTMLResponse(content=html_text)
    except Exception:
        logger.warning("preguntas_frecuentes_page: inyección falló — sirvo index plano", exc_info=True)
        return _serve_frontend("index.html")


# ── SPA catch-all: rutas del nuevo frontend (TanStack Router) ────────────────
# Debe ir AL FINAL para no interceptar rutas de API ni páginas de admin.

@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    """
    Devuelve index.html del nuevo frontend para cualquier ruta no reconocida.
    TanStack Router maneja el enrutamiento del lado del cliente.
    Las rutas /api/* y /static/* se capturan antes que esta.

    Antes de caer al index.html, sirve archivos estáticos reales que viven en
    la raíz del build de Vite (`public/` se copia a `dist/`): /estudio/*.jpg,
    /favicon.png, /robots.txt, /icon-512.png, /manifest-admin.json, etc. Sin
    esto, esos assets caen al catch-all y devuelven el HTML del SPA → imagen
    rota. El mount /assets solo cubre dist/assets (bundles hasheados).
    """
    if full_path:
        front_root = FRONT_NEW.resolve()
        candidate = (front_root / full_path).resolve()
        # Guard anti path-traversal: el archivo tiene que vivir dentro de dist/.
        if candidate.is_file() and candidate.is_relative_to(front_root):
            return FileResponse(str(candidate))
    return _serve_frontend("index.html")

# ── Init DB (non-blocking) ───────────────────────────────────────────────────
# Initialize DB in background thread to not block app startup / healthcheck

def _run_alembic_migrations() -> None:
    """Corre `alembic upgrade head` en background al arrancar.

    Falla silenciosamente con log de error — la app sigue arrancando. Crítico
    para no romper deploys si una migración tiene un bug.

    Idempotente: en BD pre-Alembic, el baseline es no-op + agrega la tabla
    `alembic_version`. Próximos arranques solo aplican migraciones nuevas.
    """
    from alembic import command
    from alembic.config import Config
    import migration_state
    backend_root = Path(__file__).resolve().parent
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    try:
        command.upgrade(cfg, "head")
    except Exception as e:
        # Capturar el estado ANTES de re-lanzar, para que /health muestre que
        # la BD quedó trabada (drift) aunque la app siga arrancando.
        migration_state.record_failure(e, cfg)
        raise
    migration_state.record_success(cfg)


def _seed_registry() -> None:
    """Persiste el registry de specs (código `services/specs/registry/`) a la DB.

    Idempotente: solo crea/actualiza `spec_definitions` y
    `categoria_spec_templates` con base en lo declarado en el código.
    Los equipos NO se cargan acá — el flujo activo es vía
    `tools/specs_import_preview.py` → `dataio.cli import`.

    Los seeders por categoría que existían (camaras.py, lentes.py, etc.)
    se eliminaron en Fase C del refactor de specs: eran fallback histórico
    para arrancar ambientes nuevos, hoy reemplazados por dataio.import_all.
    """
    from database import get_db
    try:
        from services.specs import seed_all_categorias
        conn = get_db()
        try:
            result = seed_all_categorias(conn)
            conn.commit()
            total_specs = sum(
                r["stats"].get("specs_creadas", 0)
                for r in result["categorias"].values()
            )
            total_purgadas = sum(
                r["stats"].get("specs_purgadas", 0)
                for r in result["categorias"].values()
            )
            logger.info(
                "Registry seedeado: %d specs en %d categorías (purgadas=%d)",
                total_specs, len(result["categorias"]), total_purgadas,
            )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                logger.warning("cleanup: error en rollback de conexión del seeder", exc_info=True)
            raise
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Registry seeder falló (no crítico): %s", e)


def init_db_bg():
    try:
        init_db()
        logger.info("BD PostgreSQL inicializada")
    except Exception as e:
        logger.error("No se pudo inicializar BD: %s. La app continuará — verificar DATABASE_URL.", e, exc_info=True)
        return  # Si init_db falló, no tiene sentido correr alembic.

    try:
        _run_alembic_migrations()
        logger.info("Migraciones Alembic al día")
    except Exception as e:
        logger.error("Falló alembic upgrade: %s. La app sigue arrancando — revisar manualmente.", e, exc_info=True)

    # Registry de specs → DB (idempotente, siempre corre en boot).
    # Persiste spec_definitions + categoria_spec_templates desde el
    # código del registry (`backend/services/specs/registry/catalogo/*.py`).
    # Sin esto, las tablas de specs quedarían vacías.
    try:
        _seed_registry()
    except Exception as e:
        logger.error("Falló _seed_registry: %s. La app sigue.", e, exc_info=True)

    # Catálogo (equipos/categorías/marcas/etc.): si `/data/catalog/`
    # tiene los JSONs versionados, los importa vía dataio. Si no existe,
    # la DB se mantiene como está (los ambientes en producción ya tienen
    # equipos persistidos de boots anteriores; los ambientes nuevos se
    # cargan vía `python -m backend.dataio.cli import` manualmente).
    from database import get_db
    from dataio import orchestrator as dataio_orch

    if dataio_orch.has_catalog_data():
        conn = get_db()
        try:
            stats = dataio_orch.import_all(conn)
            conn.commit()
            total_ins = sum(s.get("inserted", 0) for s in stats.values())
            total_upd = sum(s.get("updated", 0) for s in stats.values())
            logger.info(
                "dataio.import_all OK: +%d inserts, ~%d updates desde /data/catalog/",
                total_ins, total_upd,
            )
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(
                "dataio.import_all falló: %s. El operador debe arreglar el JSON.",
                e, exc_info=True,
            )
        finally:
            conn.close()
    else:
        logger.info(
            "dataio.import_all: /data/catalog/ vacío o ausente — DB se mantiene "
            "como está. Para cargar equipos nuevos, usar "
            "`python -m backend.dataio.cli import` después de generar JSONs con "
            "`tools/specs_import_preview.py`."
        )

    # Auto-run del ranking si nunca corrió (popularidad_score=0 en todos
    # los equipos). Después de eso, queda en manos del admin desde
    # /admin/settings. Issue #131.
    try:
        _maybe_run_initial_ranking()
    except Exception as e:
        logger.error("Falló cálculo inicial de ranking: %s. La app sigue. Recalcular manual desde /admin/settings.", e, exc_info=True)


def _maybe_run_initial_ranking() -> None:
    """Corre el cálculo de ranking SI ningún equipo tiene
    ranking_actualizado seteado (nunca se corrió). Después de la primera
    vez, queda en manos del admin re-correrlo desde /admin/settings.
    """
    from database import get_db
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM equipos WHERE ranking_actualizado IS NOT NULL"
        ).fetchone()
        ya_corrio = int(row["n"] or 0) > 0
        if ya_corrio:
            logger.info("Ranking ya tiene datos previos — se saltea el cálculo inicial.")
            return

        logger.info("Corriendo cálculo inicial de ranking (primera vez)...")
        from services.ranking_service import recalcular_ranking_todos
        result = recalcular_ranking_todos(conn, dry_run=False)
        logger.info(
            "Ranking inicial OK: %d equipos · %d categorías · %d marcas actualizados",
            len(result.get("cambios", [])),
            len(result.get("cambios_categorias", [])),
            len(result.get("cambios_marcas", [])),
        )
    finally:
        conn.close()


db_init_thread: threading.Thread | None = None  # arranca en el startup event

# Scheduler in-process de recordatorios de retiro (opt-in por REMINDERS_ENABLED).
# Decisión 2026-06-04 / issue #735: corre dentro de este proceso, no es un
# servicio aparte. Apagado por default → no manda nada en staging/test.
from jobs.scheduler import start_scheduler

start_scheduler()
