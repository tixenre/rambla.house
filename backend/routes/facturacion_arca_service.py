"""Routes del motor de facturación NUEVO (arca-service) — EN PARALELO al motor
`arca_fe` existente (`routes/facturacion.py`), ver `services/facturacion_arca_service/
__init__.py`. Hoy solo la vista embebible (iframe) — evaluación inicial del SDK, no
un reemplazo del flujo de facturación real todavía.

Sin credenciales configuradas (`settings.arca_service_enabled=False`, el caso normal
hasta que exista un invite + `arca-service-client login`), todo acá responde 503 con
un mensaje claro — nunca un 500 ni una excepción sin atrapar.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from arca_service_client import (
    AfipUnavailableError,
    ArcaServiceError,
    ArcaServiceServerError,
    NotFoundError,
    RateLimitedError,
    ServiceNotReadyError,
    ValidationError,
)
import httpx

from auth.guards import require_admin
from database import get_db
from rate_limit import limiter, ADMIN_WRITE_LIMIT
from services.facturacion.engine import _get_pedido
from services.facturacion_arca_service.client import (
    ArcaServiceNoConfiguradoError,
    get_client,
)
from services.facturacion_arca_service.comprobante import idempotency_key_de_pedido

router = APIRouter()


def _status_for_arca_service_error(exc: ArcaServiceError) -> int:
    """Mapea cada subtipo real de `ArcaServiceError` a un status HTTP que refleje
    qué pasó — mismo espíritu que `routes/facturacion.py::_status_for_arca_error`
    para arca_fe, adaptado a la jerarquía de `arca_service_client` (ver su
    README, sección "Errores")."""
    if isinstance(exc, NotFoundError):
        return 404
    if isinstance(exc, ValidationError):
        return 422
    if isinstance(exc, RateLimitedError):
        return 429
    if isinstance(exc, AfipUnavailableError):
        return 502
    if isinstance(exc, ServiceNotReadyError):
        return 503
    if isinstance(exc, ArcaServiceServerError):
        return 502
    return 502  # ArcaServiceError base — cualquier otro caso de la jerarquía


class EmbedComprobanteBody(BaseModel):
    # `external_ref` de arca-service (UUID devuelto por `por_cuit`) — todavía no hay
    # una tabla local que lo persista por pedido (no hay onboarding real con el que
    # probarlo), así que lo pasa el caller explícito por ahora. Ver el docstring de
    # `services/facturacion_arca_service/__init__.py`.
    external_ref: str


@router.post("/admin/pedidos/{pedido_id}/factura-arca-service/embed")
@limiter.limit(ADMIN_WRITE_LIMIT)
def crear_embed_comprobante(pedido_id: int, body: EmbedComprobanteBody, request: Request):
    """Genera un `embed_url` (iframe) para un comprobante YA EMITIDO en arca-service
    para este pedido — la `idempotency_key` es determinística
    (`comprobante.idempotency_key_de_pedido`), así que solo hace falta el
    `external_ref` de la Plataforma/Cliente que lo emitió.

    NO emite nada acá — `crear_embed_token` falla con `NotFoundError` (404) si
    todavía no existe una emisión para esa `idempotency_key`."""
    require_admin(request)
    with get_db() as conn:
        try:
            pedido = _get_pedido(conn, pedido_id)
        except ValueError:
            raise HTTPException(404, f"Pedido {pedido_id} no encontrado")

    idempotency_key = idempotency_key_de_pedido(pedido)

    try:
        with get_client() as client:
            resultado = client.crear_embed_token(body.external_ref, idempotency_key)
    except ArcaServiceNoConfiguradoError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ArcaServiceError as exc:
        raise HTTPException(_status_for_arca_service_error(exc), str(exc)) from exc
    except httpx.HTTPError as exc:
        # Falla de TRANSPORTE (timeout/DNS/conexión) — la SDK no las envuelve a
        # propósito (ver su README), llegan acá tal cual.
        raise HTTPException(502, f"No se pudo contactar a arca-service: {exc}") from exc

    return {
        "embed_url": resultado.embed_url,
        "expires_at": resultado.expires_at.isoformat(),
    }
