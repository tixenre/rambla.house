"""
middleware.py — Protección de rutas con cookie de sesión.
"""

from fastapi import Request
from fastapi.responses import RedirectResponse, JSONResponse
from auth.session import get_session, dev_bypass_enabled
from routes.settings import PUBLIC_SETTINGS_KEYS

PUBLIC_EXACT = {"/", "/login", "/admin/login", "/cliente", "/health", "/health/migrations", "/health/frontend", "/csp-report"}

PUBLIC_PREFIXES = (
    "/auth/google",
    "/auth/callback",
    "/auth/logout",
    "/auth/me",
    "/auth/config",
    "/auth/dev-login",
    "/auth/staging-login",  # login programático de staging (gateado en el handler: no-prod + secreto)
    "/static/",
    "/assets/",
    "/equipo/",
    "/cliente/",
)

# Prefijos públicos de SOLO LECTURA — el catálogo anónimo los consume por GET.
# Sus endpoints de ESCRITURA viven bajo /api/admin/... con require_admin; acá se
# eximen únicamente para GET/HEAD para que una escritura anónima bajo el mismo
# prefijo (regresión tipo el CRUD de /api/equipos) caiga igual en el chequeo de
# sesión. NO sustituye al require_admin por handler — es defensa en profundidad.
PUBLIC_API_READONLY = (
    "/api/equipos",
    "/api/categorias",
    "/api/disponibilidad",
    # Hub público de una institución co-presentadora (ej. "Filmar") — solo
    # lectura, GET /api/instituciones/{slug}. El CRUD admin vive bajo
    # /api/admin/instituciones con su propio require_admin.
    "/api/instituciones",
)

# Prefijos públicos que aceptan POST a propósito (cada uno valida adentro lo suyo).
PUBLIC_API_ANY = (
    "/api/cotizar",  # cotización del carrito: pública (catálogo anónimo cotiza
    # como consumidor_final). No escribe; los descuentos/IVA de cliente requieren
    # sesión adentro del handler (get_session), así que abrirla es seguro.
    "/api/public/",
    "/api/cliente/registro",  # registro-info y registro (sin sesión)
    "/api/cliente/claim",  # claim-info y claim de invitación (sin sesión — se reclama con token)
    # /api/estudio expone la config del espacio (incluyendo pack curado) y la
    # disponibilidad por franja — son lecturas públicas. La creación de reservas
    # vive bajo /api/estudio/reservas y tiene su propio `_require_cliente` en el
    # handler, así que el guard de cliente se sigue aplicando ahí.
    "/api/estudio",
    # /api/talleres: lista, detalle, upload de comprobante e inscripción son todos
    # públicos (cualquier visitante puede inscribirse sin sesión). Los endpoints
    # admin de talleres viven bajo /api/admin/talleres y tienen su propio
    # require_admin, por lo que quedan protegidos igual que el resto del admin.
    "/api/talleres",
    # Webhooks server-to-server (Didit): los llama un tercero SIN cookie de
    # sesión, así que el guard de sesión los cortaría con 401 antes del handler
    # (y la verificación de identidad nunca se persistiría). Se autentican por
    # firma HMAC-SHA256 dentro del handler (`verify_webhook`, fail-closed si el
    # secret no está) — NO por sesión. Por eso van exentos del middleware.
    "/api/webhooks/",
    # Heartbeat de carrito (#280 Fase 1): visitantes anónimos también persisten
    # su carrito. El handler valida el session_id internamente (UUID válido) y
    # solo asocia cliente_id si hay sesión activa — auth opcional, no ausente.
    # El endpoint admin de carritos (/api/admin/carritos) no tiene este prefijo
    # y sigue protegido por require_admin dentro del handler.
    "/api/cart/heartbeat",
)

# Archivos estáticos que viven en la raíz del build de Vite (`public/` se copia
# a `dist/`): fotos del estudio (/estudio/*.jpg), favicon, icons, manifest,
# robots, fuentes, etc. Son públicos por naturaleza y los sirve el spa_fallback
# de main.py (que ya tiene guard anti-traversal y solo devuelve archivos reales
# de dist/). Sin esto, el auth_middleware los bloquea y redirige a /login → la
# imagen/asset queda roto. Se matchea por extensión (las rutas del SPA son URLs
# limpias sin extensión) y se excluye /api/ para no abrir endpoints de datos.
STATIC_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".ico",
    ".json", ".txt", ".xml", ".webmanifest",
    ".woff", ".woff2", ".ttf", ".otf",
    ".css", ".js", ".map", ".mp4", ".webm", ".pdf",
)



async def auth_middleware(request: Request, call_next):
    path = request.url.path

    if path in PUBLIC_EXACT:
        return await call_next(request)
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return await call_next(request)
    # Lecturas públicas del catálogo: solo GET/HEAD se eximen sin sesión. Una
    # escritura bajo el mismo prefijo NO se exime (cae al guard de sesión abajo,
    # y el handler además exige require_admin).
    if request.method in ("GET", "HEAD") and any(path.startswith(p) for p in PUBLIC_API_READONLY):
        return await call_next(request)
    if any(path.startswith(p) for p in PUBLIC_API_ANY):
        return await call_next(request)
    # `/api/settings/{key}` y `/api/settings` (lectura): pese al docstring de
    # `get_setting`/`list_settings` ("lectura pública"), esta ruta NO estaba
    # eximida acá — un visitante anónimo (Logo, FAQ, hero del catálogo, el
    # date picker, el Footer) recibía 401 en silencio. Solo se exime GET/HEAD,
    # y solo para las keys de `PUBLIC_SETTINGS_KEYS` (el resto — comisiones,
    # recordatorios, email_* — sigue atrás del guard); `list_settings` filtra
    # a ese mismo subset cuando no hay sesión, así que `/api/settings` (sin
    # key) también se puede eximir sin dumpear settings internas.
    if request.method in ("GET", "HEAD") and (
        path == "/api/settings"
        or (
            path.startswith("/api/settings/")
            and path[len("/api/settings/") :] in PUBLIC_SETTINGS_KEYS
        )
    ):
        return await call_next(request)
    # Assets estáticos de dist root (no-/api/ con extensión de archivo).
    if not path.startswith("/api/") and path.endswith(STATIC_EXTENSIONS):
        return await call_next(request)

    # Páginas del SPA por URL directa (deep link / refresh): toda ruta limpia que
    # NO sea /api/ ni /admin la sirve el catch-all (index.html), y el SPA hace su
    # routing + auth client-side (el portal cliente redirige a /cliente/login solo;
    # los datos siguen detrás de /api/ con sesión → 401). Sin esto, un deep link o
    # refresh a una página pública (/rental, /estudio, /workshops, /preguntas-*) caía
    # a /login —regresión al mover el catálogo de `/` a `/rental`—. /admin y /api se
    # siguen protegiendo server-side abajo.
    if not path.startswith("/api/") and not path.startswith("/admin"):
        return await call_next(request)

    if dev_bypass_enabled():
        return await call_next(request)

    session = get_session(request)
    if not session:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "No autenticado"}, status_code=401)
        return RedirectResponse("/login")

    return await call_next(request)
