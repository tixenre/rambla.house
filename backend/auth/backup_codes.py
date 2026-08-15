"""auth/backup_codes.py — recovery del 2º factor admin (#Pablo, 2026-08-15).

Una vez que una cuenta admin tiene una passkey, `auth/google.py::auth_callback`
deja de mintear sesión con Google solo (2º factor obligatorio, ver ese
docstring) — hasta ahora, perder el dispositivo con la passkey dejaba a la
cuenta sin salida salvo un `DELETE` manual en `passkey_credentials` (ver
DECISIONES.md 2026-08-15). Códigos de un solo uso, generados 10 a la vez
(regenerar invalida el set viejo — nunca se acumulan), hasheados con sha256
(alta entropía generada por el server, no una password elegida por el
usuario — un hash rápido es correcto acá, no hace falta bcrypt/scrypt).

Registra sus rutas sobre el `router` compartido de `auth.google` (mismo
patrón que `auth.staging`) porque extiende ESE flujo puntual: la cookie
`pending_2fa` que identifica "Google ya confirmó esta cuenta, falta el 2º
factor" la escribe `auth_callback` y la lee `backup_code_login` acá — sin
esa cookie, un código de respaldo por sí solo no alcanza para nada (haría
falta ADEMÁS haber pasado por Google en esta misma sesión de browser).

NO reemplaza la passkey — es el respaldo. Recuperarse con un código deja al
admin CON SESIÓN pero sin passkey funcional en este dispositivo; el frontend
lo manda derecho a registrar una nueva (mismo primitivo `registerPasskey`,
sin código nuevo de ese lado) antes de soltarlo al resto del admin.
"""
import hashlib
import logging
import secrets
import string

from fastapi import HTTPException, Request
from pydantic import BaseModel
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from auth.google import router
from auth.guards import require_admin
from auth.ratelimit import _check_rate, _record_fail
from auth.session import COOKIE_SECURE, _make_session_response
from config import settings
from database import get_db
from net_utils import get_client_ip

logger = logging.getLogger(__name__)

N_CODIGOS = 10
_ALFABETO = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1IL")
_PENDING_COOKIE = "pending_2fa"
_PENDING_MAX_AGE = 300  # 5 min — mismo orden que el challenge de WebAuthn (passkey/ceremonies.py)

_pending_signer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="admin-pending-2fa")


# ── Cookie "Google ya confirmó, falta 2º factor" ──────────────────────────────
# La escribe auth_callback (auth/google.py) al redirigir a ?paso=passkey; la
# lee backup_code_login acá abajo. Sin esto, verificar un código exigiría que
# el cliente mande el email a mano (más fricción, y abre la puerta a probar
# códigos contra emails al voleo en vez de contra la cuenta que Google acaba
# de confirmar EN ESTA MISMA sesión de browser).

def sign_pending_2fa(email: str) -> str:
    return _pending_signer.dumps({"email": email})


def _read_pending_2fa(token: str) -> str | None:
    try:
        data = _pending_signer.loads(token, max_age=_PENDING_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("email")


# ── Generación + hash ─────────────────────────────────────────────────────────

def _generar_codigo() -> str:
    mitad = lambda: "".join(secrets.choice(_ALFABETO) for _ in range(5))  # noqa: E731
    return f"{mitad()}-{mitad()}"


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


# ── Queries + commands (tabla chica, sin CQRS-lite — no hay dominio que separar) ─

def contar_disponibles(owner_email: str) -> int:
    with get_db() as conn:
        r = conn.execute(
            "SELECT COUNT(*) AS n FROM admin_backup_codes "
            "WHERE LOWER(owner_email) = LOWER(%s) AND used_at IS NULL",
            (owner_email,),
        ).fetchone()
    return r["n"] if r else 0


def generar_codigos(owner_email: str) -> list[str]:
    """Reemplaza el set completo (borra los viejos, usados o no) por 10 nuevos.
    Devuelve los códigos en TEXTO PLANO — única vez que existen fuera del hash;
    el caller los muestra una sola vez y no los guarda en ningún lado más."""
    codigos = [_generar_codigo() for _ in range(N_CODIGOS)]
    with get_db() as conn:
        with conn.transaction():
            conn.execute(
                "DELETE FROM admin_backup_codes WHERE LOWER(owner_email) = LOWER(%s)",
                (owner_email,),
            )
            for c in codigos:
                conn.execute(
                    "INSERT INTO admin_backup_codes (owner_email, code_hash) VALUES (%s, %s)",
                    (owner_email, _hash(c)),
                )
    return codigos


def verificar_y_consumir(owner_email: str, code: str) -> bool:
    """Atómico (UPDATE...RETURNING): dos requests concurrentes con el MISMO
    código no pueden consumirlo dos veces — el segundo ve `used_at` ya seteado
    y no matchea `IS NULL`, RETURNING no da fila, devuelve False."""
    with get_db() as conn:
        with conn.transaction():
            r = conn.execute(
                """UPDATE admin_backup_codes SET used_at = NOW()
                   WHERE LOWER(owner_email) = LOWER(%s) AND code_hash = %s AND used_at IS NULL
                   RETURNING id""",
                (owner_email, _hash(code)),
            ).fetchone()
    return r is not None


# ── Rutas ──────────────────────────────────────────────────────────────────────

class BackupCodeLoginIn(BaseModel):
    code: str


@router.post("/auth/backup-code/generar")
def generar(request: Request):
    """Admin YA logueado — regenera su set de 10 códigos. Reusa `require_admin`
    (misma sesión de siempre); no depende de la cookie `pending_2fa`."""
    admin = require_admin(request)
    codigos = generar_codigos(admin["email"])
    logger.info("admin backup-codes regenerados email=%s", admin["email"])
    return {"codigos": codigos}


@router.get("/auth/backup-code/estado")
def estado(request: Request):
    admin = require_admin(request)
    return {"disponibles": contar_disponibles(admin["email"])}


@router.post("/auth/backup-code/login")
def backup_code_login(body: BackupCodeLoginIn, request: Request):
    """Completa el 2º factor con un código de respaldo en vez de la passkey.
    Exige la cookie `pending_2fa` (Google confirmado EN ESTA sesión de
    browser, ver docstring del módulo) — sin ella, ni con el código correcto
    hay nada que verificar contra qué cuenta."""
    ip = get_client_ip(request)
    _check_rate(ip)  # mismo bucket por-IP que login/OAuth/staging — defensa en profundidad
    email = _read_pending_2fa(request.cookies.get(_PENDING_COOKIE) or "")
    if not email:
        _record_fail(ip)
        raise HTTPException(400, "Sesión de login expirada. Entrá de nuevo con Google.")
    if not verificar_y_consumir(email, body.code):
        _record_fail(ip)
        raise HTTPException(401, "Código inválido, ya usado, o vencido.")
    logger.info("admin backup-code consumido email=%s", email)
    res = _make_session_response(email=email, name=email, request=request)
    res.delete_cookie(_PENDING_COOKIE)
    return res


def set_pending_2fa_cookie(res, email: str) -> None:
    """Helper para `auth_callback` (auth/google.py) — separado acá para que ese
    archivo no tenga que conocer el salt/serializer de este módulo."""
    res.set_cookie(
        _PENDING_COOKIE, sign_pending_2fa(email), httponly=True, samesite="lax",
        secure=COOKIE_SECURE, max_age=_PENDING_MAX_AGE,
    )
