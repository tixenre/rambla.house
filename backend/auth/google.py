"""auth/google.py — login con Google OAuth 2.0 (admin + cliente) + el `router` compartido.

Crea el `router` de auth (google + staging registran sus rutas sobre él, patrón
`cliente_portal`). Movido verbatim de `routes/auth.py`; lo único que cambia son los
imports (sesión/rate-limit/guards salen de los hermanos `auth.*`).
"""
import logging
import os
import secrets

from authlib.integrations.httpx_client import OAuth2Client
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired

from auth.ratelimit import _check_rate, _record_fail
from auth.session import (
    COOKIE_SECURE,
    _make_session_response,
    dev_bypass_enabled,
    get_session,
    require_session,
    signer,
)
from config import settings
from net_utils import get_client_ip

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Config ──────────────────────────────────────────────────────────────────

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

# Base URL del backend. En Railway viene del entorno; en dev local usamos
# localhost:8000 (que el proxy de Vite reescribe). Las env vars REDIRECT_URI
# / CLIENTE_REDIRECT_URI tienen prioridad — si están seteadas se respetan
# tal cual (útil para staging u otros entornos custom).
def _default_oauth_base() -> str:
    # SITE_URL seteado explícitamente via env var → es el dominio canónico
    # (prod: rambla.house, staging: dev-rambla.up.railway.app).
    site_url = os.getenv("SITE_URL", "").strip()
    if site_url:
        return site_url
    if settings.is_railway:
        return "https://ramblarental.up.railway.app"
    return "http://localhost:8000"

_OAUTH_BASE          = _default_oauth_base()
REDIRECT_URI         = os.getenv("REDIRECT_URI")         or f"{_OAUTH_BASE}/auth/callback"
CLIENTE_REDIRECT_URI = os.getenv("CLIENTE_REDIRECT_URI") or f"{_OAUTH_BASE}/cliente/auth/callback"
POST_LOGIN_URL       = os.getenv("POST_LOGIN_URL", "/admin")
FRONTEND_BASE        = os.getenv("FRONTEND_BASE_URL", "")   # e.g. http://localhost:3000 en dev
MAPS_API_KEY         = settings.GOOGLE_MAPS_API_KEY

ALLOWED_EMAILS: set[str] = {
    e.strip().lower()
    for e in os.getenv("ALLOWED_EMAILS", "").split(",")
    if e.strip()
}

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO  = "https://www.googleapis.com/oauth2/v3/userinfo"


# ── Helpers OAuth ────────────────────────────────────────────────────────────

def _oauth_client() -> OAuth2Client:
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Google OAuth no configurado en el servidor.")
    return OAuth2Client(
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope="openid email profile",
    )


def _oauth_client_cliente() -> OAuth2Client:
    """Mismo helper que `_oauth_client()` pero para el flujo de CLIENTE (otro
    `redirect_uri`). Antes se repetía inline en `cliente_auth_google`,
    `cliente_auth_google_link` y `cliente_auth_callback` — única fuente ahora."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Google OAuth no configurado en el servidor.")
    return OAuth2Client(
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        redirect_uri=CLIENTE_REDIRECT_URI,
        scope="openid email profile",
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/auth/me")
def auth_me(request: Request):
    """Devuelve info de la sesión actual + flag `is_admin`.

    El flag es necesario para que el front sepa si renderizar el
    backoffice o redirect a una pantalla "sin acceso". `require_session`
    solo verifica que haya sesión válida (cualquier Google login), pero
    es admin solo si el email está en ADMIN_EMAILS.
    """
    from auth.guards import is_admin_email

    if dev_bypass_enabled():
        return {"email": "bypass@local", "name": "Dev Admin", "is_admin": True}

    session = require_session(request)
    email = (session.get("email") or "").strip().lower()
    return {**session, "is_admin": is_admin_email(email)}


def _revoke_current_session(request: Request) -> None:
    """Revoca server-side la sesión actual (logout real): mata el `jti` en la
    allowlist para que la cookie no se pueda "revivir" si fue robada. Defensivo:
    sin sesión / sin jti (ej. cookie vieja pre-deploy) es no-op."""
    session = get_session(request)
    jti = session.get("jti") if session else None
    if jti:
        from auth.commands import sessions as sessions_commands  # perezoso: rompe el ciclo con auth/__init__
        sessions_commands.revoke(jti)


@router.get("/auth/logout")
def auth_logout(request: Request):
    _revoke_current_session(request)
    res = RedirectResponse(f"{FRONTEND_BASE}/admin/login", status_code=303)
    res.delete_cookie("session")
    return res


@router.post("/auth/logout")
def auth_logout_post(request: Request):
    _revoke_current_session(request)
    res = JSONResponse({"ok": True})
    res.delete_cookie("session")
    return res


@router.get("/auth/google")
def auth_google(request: Request):
    """Redirige al usuario a la pantalla de selección de cuenta de Google."""
    # State firmado: verificable por firma en el callback, sin depender de cookie.
    # Resuelve state_mismatch en browsers con ITP/strict mode/ad-blockers.
    state = signer.dumps({"nonce": secrets.token_urlsafe(16)})
    client = _oauth_client()
    uri, _ = client.create_authorization_url(
        GOOGLE_AUTH_URL,
        state=state,
        access_type="online",
        prompt="select_account",
    )
    res = RedirectResponse(uri, status_code=302)
    # Cookie como capa extra (browsers sin bloqueo la usan; los que bloquean
    # pasan igual porque la firma del state es suficiente).
    res.set_cookie("oauth_state", state, httponly=True, samesite="lax",
                   secure=COOKIE_SECURE, max_age=600)
    return res


@router.get("/auth/callback")
def auth_callback(request: Request):
    """Google redirige acá con el código de autorización."""
    ip = get_client_ip(request)
    _check_rate(ip)

    error = request.query_params.get("error")
    if error:
        return RedirectResponse(f"{FRONTEND_BASE}/admin/login?error={error}", status_code=303)

    code  = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        return RedirectResponse(f"{FRONTEND_BASE}/admin/login?error=no_code", status_code=303)

    # Verificar state anti-CSRF: cookie match (ideal) o firma válida (fallback
    # para browsers con ITP/strict mode/ad-blockers que bloquean la cookie).
    saved_state = request.cookies.get("oauth_state")
    state_ok = bool(saved_state and saved_state == state)
    if not state_ok and state:
        try:
            signer.loads(state, max_age=600)
            state_ok = True
            if not saved_state:
                logger.info("admin OAuth: state por firma (sin cookie) ip=%s", ip)
        except (BadSignature, SignatureExpired):
            pass
    if not state_ok:
        _record_fail(ip)
        return RedirectResponse(f"{FRONTEND_BASE}/admin/login?error=state_mismatch", status_code=303)

    # Intercambiar código por token
    client = _oauth_client()
    try:
        client.fetch_token(GOOGLE_TOKEN_URL, code=code)
    except Exception as e:
        logger.warning("Admin OAuth token_error: %s", e, exc_info=True)
        _record_fail(ip)
        return RedirectResponse(f"{FRONTEND_BASE}/admin/login?error=token_error", status_code=303)

    # Obtener datos del usuario — authlib ya tiene el token guardado tras fetch_token()
    try:
        resp = client.get(GOOGLE_USERINFO)
        resp.raise_for_status()
        userinfo = resp.json()
    except Exception as e:
        logger.warning("Admin OAuth userinfo_error: %s", e, exc_info=True)
        _record_fail(ip)
        return RedirectResponse(f"{FRONTEND_BASE}/admin/login?error=userinfo_error", status_code=303)

    email = userinfo.get("email", "").lower()
    name  = userinfo.get("name", email)

    if not email:
        _record_fail(ip)
        return RedirectResponse(f"{FRONTEND_BASE}/admin/login?error=no_email", status_code=303)

    # Verificar email autorizado
    if ALLOWED_EMAILS and email not in ALLOWED_EMAILS:
        _record_fail(ip)
        return RedirectResponse(f"{FRONTEND_BASE}/admin/login?error=not_allowed", status_code=303)

    # 2º factor obligatorio para admin (#1098 extensión, criterio del dueño): si esta cuenta
    # YA tiene una passkey enrolada, Google solo NO alcanza — no minteamos sesión acá, mandamos
    # a confirmar con la passkey (el login discoverable ya existente la mintea de verdad). Sin
    # passkey todavía: Google alcanza HOY, pero `AdminLayout` fuerza el enrolamiento on-the-fly
    # apenas entra (mismo primitivo `registerPasskey`, sin código nuevo de ese lado).
    from auth.passkey import queries as passkey_queries
    if passkey_queries.list_for_owner("admin", owner_email=email):
        # Import local (no al tope del archivo): `auth.backup_codes` importa `router` DESDE
        # este módulo, así que un import a nivel de módulo acá crearía un ciclo.
        from auth.backup_codes import set_pending_2fa_cookie
        res = RedirectResponse(f"{FRONTEND_BASE}/admin/login?paso=passkey", status_code=303)
        set_pending_2fa_cookie(res, email)
        res.delete_cookie("oauth_state")
        return res

    res = _make_session_response(email, name, redirect=POST_LOGIN_URL, request=request)
    # Limpiar cookie de state
    res.delete_cookie("oauth_state")
    return res


@router.get("/auth/config")
def auth_config():
    dev_mode = dev_bypass_enabled()
    return {
        "google_enabled": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
        "dev_mode": dev_mode,
    }


@router.get("/api/public/maps-key")
def public_maps_key():
    return {"key": MAPS_API_KEY or None}


# ── OAuth para clientes ───────────────────────────────────────────────────────

def _safe_next_path(raw: str | None) -> str | None:
    """Valida que `next` sea una ruta interna segura (no open-redirect).

    Acepta solo paths que empiezan con un único `/` (no `//`, que sería
    protocol-relative y abriría a otro dominio). Rechaza esquemas explícitos.
    Devuelve la ruta validada o None.
    """
    if not raw:
        return None
    s = raw.strip()
    if not s.startswith("/"):
        return None
    if s.startswith("//") or s.startswith("/\\"):  # protocol-relative → otro host
        return None
    # XSS hardening: el valor se embebe en el HTML+JS del callback
    # (<script>…replace("{next}")…</script>). Rechazar caracteres que permitan
    # romper ese contexto (`<`/`>` → `</script>`, comillas, backtick, backslash)
    # o whitespace/control — un path interno legítimo no los necesita.
    if any(c in s for c in "<>\"'`\\") or any(c.isspace() or ord(c) < 0x20 for c in s):
        return None
    if ":" in s.split("/", 2)[1] if "/" in s[1:] else False:  # noqa: E501
        # Defensivo: si algún componente trae ':' antes de un '/' adicional,
        # podría intentarse `/\\example.com:443/x` u otros tricks. Rechazamos.
        return None
    # Tope de longitud razonable (URL-encoded params se inflan).
    if len(s) > 2048:
        return None
    return s


@router.get("/cliente/auth/google")
def cliente_auth_google(request: Request):
    """Inicia el flujo OAuth de Google para clientes.

    Si llega `?next=<path>`, la guardamos en cookie para volver ahí después del
    login en vez de mandar siempre a /cliente/portal. Solo aceptamos paths
    internos (validación en `_safe_next_path` — no open-redirect).
    """
    client = _oauth_client_cliente()
    state = signer.dumps({"nonce": secrets.token_urlsafe(16)})
    uri, _ = client.create_authorization_url(
        GOOGLE_AUTH_URL,
        state=state,
        access_type="online",
        prompt="select_account",
    )
    res = RedirectResponse(uri, status_code=302)
    res.set_cookie("oauth_state_cliente", state, httponly=True, samesite="lax",
                   secure=COOKIE_SECURE, max_age=600)
    next_path = _safe_next_path(request.query_params.get("next"))
    if next_path:
        res.set_cookie(
            "oauth_next_cliente", next_path, httponly=True, samesite="lax",
            secure=COOKIE_SECURE, max_age=600,
        )
    return res


@router.get("/cliente/auth/google/link")
def cliente_auth_google_link(request: Request):
    """Vincular OTRA cuenta de Google a la cuenta del cliente **ya logueado**
    (account-linking — "varias llaves"). NO es un login: el callback detecta el
    `link_cliente_id` firmado en el state y vincula la identidad en vez de mintear una
    sesión nueva. Requiere sesión de cliente; el `cliente_id` viaja firmado (no forjable)."""
    sess = get_session(request)
    if not sess or sess.get("role") != "cliente":
        raise HTTPException(401, "Sesión de cliente requerida.")
    client = _oauth_client_cliente()
    state = signer.dumps({"nonce": secrets.token_urlsafe(16), "link_cliente_id": sess["cliente_id"]})
    uri, _ = client.create_authorization_url(
        GOOGLE_AUTH_URL, state=state, access_type="online", prompt="select_account",
    )
    res = RedirectResponse(uri, status_code=302)
    res.set_cookie("oauth_state_cliente", state, httponly=True, samesite="lax",
                   secure=COOKIE_SECURE, max_age=600)
    return res


def _link_cliente_id_de_state(state: str | None):
    """Extrae el `link_cliente_id` del state firmado (None si no es un link o expiró)."""
    if not state:
        return None
    try:
        payload = signer.loads(state, max_age=600)
    except (BadSignature, SignatureExpired):
        return None
    return payload.get("link_cliente_id") if isinstance(payload, dict) else None


def _redirect_borrando_oauth(url: str):
    res = RedirectResponse(url, status_code=303)
    res.delete_cookie("oauth_state_cliente")
    res.delete_cookie("oauth_next_cliente")
    return res


def _completar_link_google(request: Request, link_cid: int, sub: str | None, email: str | None):
    """Vincula el `sub` de Google a la cuenta logueada y vuelve a "métodos de acceso"
    con un estado. Defensa: la sesión actual TIENE que ser la de esa cuenta (no se
    vincula a una cuenta ajena aunque el state lo diga). **Una cuenta = un Google**:
    un segundo Google distinto se rechaza. Si el Google ya es de OTRA cuenta, intenta
    **unir las dos** (sabemos que es la misma persona)."""
    base = f"{FRONTEND_BASE}/cliente/portal?tab=perfil"
    current = get_session(request)
    if not current or current.get("role") != "cliente" or current.get("cliente_id") != link_cid or not sub:
        return RedirectResponse(f"{base}&keys=error", status_code=303)
    from auth.commands.identities import link_identity  # perezoso
    from auth.queries.identities import google_identity_for_cliente
    # Una cuenta = un Google: si ya hay un Google distinto vinculado, no sumamos otro.
    ya = google_identity_for_cliente(link_cid)
    if ya is not None and ya["identifier"] != sub:
        return _redirect_borrando_oauth(f"{base}&keys=ya_google")
    resultado = link_identity(cliente_id=link_cid, method="google", identifier=sub,
                              email=email, verified=True)
    if resultado == "taken_by_other":
        # El Google ya es de OTRA cuenta. El usuario está logueado en `link_cid` (probó una
        # llave de A) Y acaba de probar control de ese Google (llave de B) → es la MISMA
        # persona → unimos las dos cuentas, si una es absorbible (liviana/vacía).
        return _merge_cuentas_por_google(request, actual=link_cid, sub=sub)
    estado = {"linked": "ok", "already_yours": "ya"}.get(resultado, "error")
    return _redirect_borrando_oauth(f"{base}&keys={estado}")


def _merge_cuentas_por_google(request: Request, *, actual: int, sub: str):
    """El Google que se quiso vincular ya es de otra cuenta. Se unen si una de las dos es
    **absorbible** (liviana/vacía); si ambas tienen datos, no se auto-mergea → "taken"
    (el merge general con reasignación de datos es Fase 2)."""
    from auth.queries.identities import find_cliente_by_identity
    from auth.queries.account_merge import account_is_absorbable
    from auth.commands.account_merge import merge_accounts
    base = f"{FRONTEND_BASE}/cliente/portal?tab=perfil"
    otra = find_cliente_by_identity("google", sub)
    if otra is None or otra == actual:
        return _redirect_borrando_oauth(f"{base}&keys=error")  # carrera: ya no está tomado
    if account_is_absorbable(actual):
        # Estás parado en la cuenta liviana; tu cuenta real es `otra` → unila ahí y entrá a ella.
        merge_accounts(source=actual, target=otra)
        return _mint_session_para_cuenta(otra, request, redirect=f"{base}&keys=merged")
    if account_is_absorbable(otra):
        # Tu cuenta (donde estás) es la real; la del Google era vacía → absorbela acá.
        merge_accounts(source=otra, target=actual)
        return _redirect_borrando_oauth(f"{base}&keys=merged")
    return _redirect_borrando_oauth(f"{base}&keys=taken")  # ambas con datos → Fase 2


def _mint_session_para_cuenta(cliente_id: int, request: Request, *, redirect: str):
    """Mintea una sesión de cliente para `cliente_id` tras un merge que borró la cuenta en
    la que estabas. Pasa por el punto único `_make_session_response` (jti + revocable)."""
    from database import get_db  # perezoso: evita ciclo al importar auth
    with get_db() as conn:
        c = conn.execute(
            "SELECT id, email, nombre, apellido FROM clientes WHERE id = %s", (cliente_id,)
        ).fetchone()
    if not c:
        return _redirect_borrando_oauth(f"{FRONTEND_BASE}/cliente/login?error=merge")
    name = f"{c['nombre'] or ''} {c['apellido'] or ''}".strip() or (c["email"] or "")
    res = _make_session_response(
        email=c["email"] or "", name=name, redirect=redirect,
        extra={"role": "cliente", "cliente_id": c["id"]}, request=request,
    )
    res.delete_cookie("oauth_state_cliente")
    res.delete_cookie("oauth_next_cliente")
    return res


@router.get("/cliente/auth/callback")
def cliente_auth_callback(request: Request):
    """Google redirige acá. Si el cliente existe → sesión. Si no → registro."""
    ip = get_client_ip(request)
    _check_rate(ip)

    error = request.query_params.get("error")
    if error:
        return RedirectResponse(f"{FRONTEND_BASE}/cliente/login?error={error}", status_code=303)

    code  = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        return RedirectResponse(f"{FRONTEND_BASE}/cliente/login?error=no_code", status_code=303)

    saved_state = request.cookies.get("oauth_state_cliente")
    state_ok = bool(saved_state and saved_state == state)
    if not state_ok and state:
        try:
            signer.loads(state, max_age=600)
            state_ok = True
            if not saved_state:
                logger.info("cliente OAuth: state por firma (sin cookie) ip=%s", ip)
        except (BadSignature, SignatureExpired):
            pass
    if not state_ok:
        _record_fail(ip)
        return RedirectResponse(f"{FRONTEND_BASE}/cliente/login?error=state_mismatch", status_code=303)

    client = _oauth_client_cliente()
    try:
        client.fetch_token(GOOGLE_TOKEN_URL, code=code)
    except Exception as e:
        logger.warning("Cliente OAuth token_error: %s", e, exc_info=True)
        _record_fail(ip)
        return RedirectResponse(f"{FRONTEND_BASE}/cliente/login?error=token_error", status_code=303)

    try:
        resp = client.get(GOOGLE_USERINFO)
        resp.raise_for_status()
        userinfo = resp.json()
    except Exception as e:
        logger.warning("Cliente OAuth userinfo_error: %s", e, exc_info=True)
        _record_fail(ip)
        return RedirectResponse(f"{FRONTEND_BASE}/cliente/login?error=userinfo_error", status_code=303)

    email = userinfo.get("email", "").lower()
    name  = userinfo.get("name", email)

    if not email:
        _record_fail(ip)
        return RedirectResponse(f"{FRONTEND_BASE}/cliente/login?error=no_email", status_code=303)

    # Resolver la cuenta por el `sub` ESTABLE de Google (ancla), con fallback por mail
    # para las cuentas previas a `login_identities` (backfillea el sub). Que el ancla
    # sea el `sub` y no el mail = un cliente que cambió su mail en Google sigue entrando
    # a la misma cuenta.
    from auth.commands.identities import find_or_backfill_google  # perezoso: evita ciclo con auth/__init__
    sub = userinfo.get("sub") or userinfo.get("id")

    # ¿Es un LINK (vincular Google a una cuenta ya logueada), no un login? El
    # `link_cliente_id` viaja firmado en el state (lo puso /cliente/auth/google/link).
    # En ese caso no minteamos sesión: vinculamos la identidad y volvemos a la cuenta.
    link_cid = _link_cliente_id_de_state(state)
    if link_cid is not None:
        return _completar_link_google(request, link_cid, sub, email)

    cliente_id = find_or_backfill_google(sub, email)

    if cliente_id is not None:
        # Cliente conocido → crear sesión directamente. Si llegó `next` válido
        # (cookie seteada por /cliente/auth/google), volvemos ahí en vez de al
        # portal — habilita el flujo de "iniciar sesión y volver a /estudio".
        next_path = _safe_next_path(request.cookies.get("oauth_next_cliente"))
        target = f"{FRONTEND_BASE}{next_path}" if next_path else f"{FRONTEND_BASE}/cliente/portal"
        # Punto único de minteo (registra la sesión server-side con `jti` → revocable),
        # con el mismo redirect-via-JS que arma `_make_session_response`.
        res = _make_session_response(
            email, name, redirect=target,
            extra={"role": "cliente", "cliente_id": cliente_id}, request=request,
        )
        res.delete_cookie("oauth_state_cliente")
        res.delete_cookie("oauth_next_cliente")
        return res
    else:
        # Cliente nuevo → token de registro (válido 30 min). Lleva el `sub` para que el
        # alta nazca con su llave de Google. El `next` lo descartamos: el registro lleva
        # su propio camino y el cliente navega al destino después del alta.
        reg_token = signer.dumps({"tipo": "registro", "email": email, "name": name, "google_sub": sub})
        redirect_url = f"{FRONTEND_BASE}/cliente/registro?t={reg_token}"
        res = RedirectResponse(redirect_url, status_code=303)
        res.delete_cookie("oauth_state_cliente")
        res.delete_cookie("oauth_next_cliente")
        return res
