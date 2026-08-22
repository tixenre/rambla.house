"""services.facturacion_arca_service.client — factory de ArcaServiceClient/
AsyncArcaServiceClient configurado desde `config.settings` (ARCA_SERVICE_*).

Vacío por default → inerte, mismo criterio default-deny que Didit/WhatsApp
(`settings.arca_service_enabled`). Las credenciales salen de
`arca-service-client login` (self-serve, corrido a mano por el dueño contra
arca-service) — este módulo nunca las genera ni las pide, solo las lee.
"""
from __future__ import annotations

from arca_service_client import ArcaServiceClient, AsyncArcaServiceClient

from config import settings


class ArcaServiceNoConfiguradoError(RuntimeError):
    """arca-service todavía no tiene credenciales configuradas (alguna de
    ARCA_SERVICE_BASE_URL/CLIENT_CERT_PATH/CLIENT_KEY_PATH/API_KEY está vacía).
    No es un error de arca-service ni de la red — es un problema de config
    local, antes de que exista ningún request. El caller (route) la traduce
    a un 503 con un mensaje claro, no a un 500."""


def _kwargs() -> dict:
    if not settings.arca_service_enabled:
        raise ArcaServiceNoConfiguradoError(
            "arca-service no está configurado — faltan una o más de "
            "ARCA_SERVICE_BASE_URL / ARCA_SERVICE_CLIENT_CERT_PATH / "
            "ARCA_SERVICE_CLIENT_KEY_PATH / ARCA_SERVICE_API_KEY. Corré "
            "`arca-service-client login` y seteá el resultado en el ambiente."
        )
    return {
        "base_url": settings.ARCA_SERVICE_BASE_URL,
        "client_cert_path": settings.ARCA_SERVICE_CLIENT_CERT_PATH,
        "client_key_path": settings.ARCA_SERVICE_CLIENT_KEY_PATH,
        "api_key": settings.ARCA_SERVICE_API_KEY,
    }


def get_client() -> ArcaServiceClient:
    """Cliente sync — el caller es responsable de cerrarlo (`.close()` o
    `with get_client() as client:`)."""
    return ArcaServiceClient(**_kwargs())


def get_async_client() -> AsyncArcaServiceClient:
    """Cliente async — el caller es responsable de cerrarlo (`await
    client.aclose()` o `async with get_async_client() as client:`)."""
    return AsyncArcaServiceClient(**_kwargs())
