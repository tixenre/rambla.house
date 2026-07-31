"""Configuración general de la app — fuente única, tipada y validada.

`Settings` (pydantic-settings) declara las env vars con tipo y default en UN
solo lugar, en vez de ~69 `os.getenv` dispersos. Se instancia una vez
(`settings`) al importar este módulo, así la validación de tipos corre al boot
(fail-fast) en vez de explotar a mitad de un request. Ver #511.

Migración incremental (issue #511): viven acá las **críticas** (auth / CORS /
DB / seguridad / observabilidad) + email + integraciones. El resto (OAuth,
R2/storage, owner, etc.) se irá migrando desde sus `os.getenv` actuales.

El parsing (listas, sets, bools derivados) vive en propiedades de `Settings`
para que cada consumidor lea la forma ya cocida y no repita el split/lower.
"""

from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Carga los .env del backend acá mismo, sin depender de que otro módulo
        # (database.py) haya corrido load_dotenv antes — así Settings ve los
        # valores sin importar el orden de imports. `.env.local` pisa a `.env`
        # (último gana); las env vars reales del proceso pisan a ambos.
        env_file=(_BACKEND_DIR / ".env", _BACKEND_DIR / ".env.local"),
        env_file_encoding="utf-8",
        # Ignora env vars no declaradas (muchas aún sin migrar); matching de
        # nombres case-insensitive (las env son MAYÚSCULAS).
        case_sensitive=False,
        extra="ignore",
    )

    # ── URLs ────────────────────────────────────────────────────────────
    # URL pública del sitio (dominio canónico). Override con env var SITE_URL
    # por ambiente (prod ya la tiene seteada; este default cubre local/dev).
    SITE_URL: str = "https://rambla.house"

    # ── Auth / seguridad ────────────────────────────────────────────────
    # Firma de la cookie de sesión. Sin esto la app no puede autenticar:
    # `routes/auth.py` aborta el boot si queda vacía (con el comando para
    # generarla).
    SECRET_KEY: str = ""
    # Emails con permiso de admin (coma-separados).
    ADMIN_EMAILS: str = "tinchosantini@gmail.com"
    # Fuerza `Secure` en la cookie (en Railway se infiere; ver `cookie_secure`).
    COOKIE_SECURE: str = ""

    # ── Infra / observabilidad ──────────────────────────────────────────
    DATABASE_URL: Optional[str] = None
    # Seteada por Railway en sus entornos; sirve para detectar "estamos en prod".
    RAILWAY_ENVIRONMENT: Optional[str] = None
    # Error tracking; opcional (dev/CI no lo necesitan).
    SENTRY_DSN: Optional[str] = None
    # Orígenes permitidos para CORS con credenciales (coma-separados). Incluye el
    # puerto del `vite dev` (:3000) además del default de Vite (:5173): es el origin
    # que el navegador reporta en la assertion de passkey, sin él WebAuthn falla en
    # local. En Railway se setea por env (dominio real).
    FRONTEND_ORIGINS: str = "http://localhost:3000,http://localhost:5173,http://localhost:8000"

    # ── Didit — verificación de identidad (DNI + selfie → RENAPER) ──────────
    # Se activa por configuración: si DIDIT_API_KEY está vacía, los endpoints de
    # verificación devuelven 503. Mismo patrón que RESEND_API_KEY para mails.
    # DIDIT_WORKFLOW_ID es obligatorio para crear sesiones (identifica el flujo
    # de verificación configurado en el Console de Didit).
    DIDIT_API_KEY:        str = ""
    DIDIT_WEBHOOK_SECRET: str = ""
    DIDIT_WORKFLOW_ID:    str = ""

    # ── Email — construido, no activado (MEMORIA 2026-05-27) ────────────
    # El canal se activa por config, no por código: con RESEND_API_KEY (o
    # SMTP_*) el mail sale de verdad; sin nada, backend `test` que solo
    # loggea. EMAIL_PROVIDER fuerza el backend (resend | smtp | test).
    EMAIL_PROVIDER: str = ""
    RESEND_API_KEY: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_TLS: bool = True
    # from / admin_to: la env pisa el valor editable en app_settings
    # (resolución en services/email/service.py).
    EMAIL_FROM: str = ""
    EMAIL_ADMIN_TO: str = ""

    # ── WhatsApp Business — Meta Cloud API (construido, activado por config) ──
    # Una sola cuenta de plataforma (marca Rambla única): el token y el número
    # viven en ENV (como RESEND/DIDIT), NO cifrados en DB — así cada ambiente de
    # Railway tiene el suyo y staging (BD clonada de prod) nunca hereda el token
    # de prod. Sin token/phone_number_id el canal es inerte. Ver
    # services/whatsapp/config.py.
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = ""
    # Allowlist de destinatarios (E.164 coma-separados) para NO-producción: fuera
    # de prod solo se le manda a estos números (red anti-spam; el número de test
    # de Meta igual restringe server-side, esto es defensa en profundidad).
    WHATSAPP_TEST_RECIPIENTS: str = ""

    # ── Integraciones ────────────────────────────────────────────────────
    GOOGLE_MAPS_API_KEY: str = ""

    @field_validator("SITE_URL")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    # ── Formas cocidas (parsing centralizado) ───────────────────────────
    @property
    def is_railway(self) -> bool:
        """True si corremos en un entorno de Railway (proxy para 'es prod')."""
        return self.RAILWAY_ENVIRONMENT is not None

    @property
    def is_production(self) -> bool:
        """True solo en el ambiente PRODUCTIVO de Railway. Staging (`dev`),
        previews y local quedan afuera.

        Se usa para no contaminar las analíticas de prod desde staging: el
        ambiente `dev` corre con una BD copiada de prod (ver MEMORIA), así que
        compartiría el mismo `ga4_measurement_id` — pero no debe trackear.
        Falla hacia 'sí es prod' ante un nombre de entorno desconocido (mejor
        ver datos en prod que apagarlos en silencio); bloquea solo los nombres
        de no-producción conocidos y el local (RAILWAY_ENVIRONMENT vacío)."""
        env = (self.RAILWAY_ENVIRONMENT or "").strip().lower()
        if not env:
            return False
        return env not in {"dev", "staging", "development", "preview", "test", "local"}

    @property
    def admin_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}

    @property
    def cookie_secure(self) -> bool:
        return self.is_railway or self.COOKIE_SECURE.strip().lower() == "true"

    @property
    def frontend_origins(self) -> list[str]:
        return [o.strip() for o in self.FRONTEND_ORIGINS.split(",") if o.strip()]

    @property
    def didit_enabled(self) -> bool:
        return bool(self.DIDIT_API_KEY and self.DIDIT_WEBHOOK_SECRET)


settings = Settings()

# Back-compat: varios módulos hacen `from config import SITE_URL`.
SITE_URL = settings.SITE_URL
