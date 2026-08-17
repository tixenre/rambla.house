"""Motor único de autenticación de Rambla.

Agrupa toda la auth —antes desperdigada en `routes/auth.py` (god-module),
`admin_guard.py`, `routes/cliente_portal/core.py` y `services/passkeys/`— en un
paquete-motor, como `reservas/` o `contabilidad/`. Cada método de login (Google
OAuth, passkey, staging) es un hermano alrededor del **núcleo de sesión**
(`session.py`): los dos convergen en la MISMA cookie firmada, y los guards
(`guards.py`) solo la leen (agnósticos del método).

Submódulos:
- `session`    → primitivas de sesión (signer, mint, get/require) + config de cookie.
- `ratelimit`  → rate-limit por IP compartido (OAuth callbacks + staging-login).
- `guards`     → require_admin / require_cliente / is_admin_email.
- `google`     → rutas OAuth de Google (admin + cliente) + el `router` compartido.
- `staging`    → dev-login / staging-login (registran sobre el router de google).
- `passkey`    → motor WebAuthn + rutas.
- `backup_codes` → recovery del 2º factor admin (códigos de un solo uso, cuando
  se pierde el dispositivo con la passkey) — registra sobre el router de google.
- `queries.sessions` / `commands.sessions` / `sessions_routes` → allowlist de
  sesiones + revocación (logout real, "cerrar mis otras sesiones"). La cookie
  firmada lleva un `jti`; la tabla decide si sigue viva.
- `queries.identities` / `commands.identities` → llaves de login del cliente
  (Google/mail, tabla `login_identities`); `linking.py` las une con las passkeys
  en "métodos de acceso".
- `queries.account_merge` / `commands.account_merge` → unir dos cuentas cuando
  son la misma persona (una absorbible, sin datos que perder).
- `queries.magic` / `commands.magic` → magic-link single-use (invitación de
  cuenta, atajo de recuperación).

La superficie pública (símbolos + routers) se ensambla al final de este módulo.
"""
# Importar los submódulos dispara el registro de rutas sobre el router compartido.
# `session` primero (corre el boot-check de SECRET_KEY); `google` crea el router y
# registra sus rutas; `staging` registra las suyas sobre ese mismo router.
import auth.session  # noqa: F401
import auth.ratelimit  # noqa: F401
import auth.guards  # noqa: F401
import auth.google  # noqa: F401
import auth.staging  # noqa: F401
import auth.backup_codes  # noqa: F401
import auth.passkey.routes  # noqa: F401
import auth.sessions_routes  # noqa: F401
import auth.linking  # noqa: F401

from auth.google import router  # router compartido google + staging
from auth.passkey.routes import router as auth_passkey_router
from auth.sessions_routes import router as auth_sessions_router
from auth.linking import router as auth_linking_router

__all__ = ["router", "auth_passkey_router", "auth_sessions_router", "auth_linking_router"]
