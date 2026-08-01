"""services.whatsapp — adapter Rambla del canal WhatsApp (Meta Cloud API).

Espeja `services/facturacion/` respecto de `arca_fe`: la librería portable
`whatsapp_cloud` hace el HTTP + errores tipados; este paquete pone el I/O y las
decisiones de Rambla — credenciales/gating (`config`), readiness (`estado`),
registro de templates (`plantillas`) y la boca de envío fail-safe + idempotente
(`envio`).

Punto de entrada: `enviar_evento_pedido(plantilla_key, pedido, ctx)`.
"""
from __future__ import annotations

from services.whatsapp.config import (
    WhatsAppCreds,
    canal_habilitado,
    destinatario_permitido,
    resolver_creds,
)
from services.whatsapp.envio import enviar_evento_admin, enviar_evento_pedido
from services.whatsapp.estado import diagnosticar
from services.whatsapp.plantillas import REGISTRO, PlantillaWA
from services.whatsapp.sincronizacion import estado_plantillas, sincronizar
from services.whatsapp.webhook import (
    WhatsAppWebhookError,
    procesar_evento,
    verify_challenge,
    verify_signature,
)

__all__ = [
    "enviar_evento_pedido",
    "enviar_evento_admin",
    "diagnosticar",
    "estado_plantillas",
    "sincronizar",
    "REGISTRO",
    "PlantillaWA",
    "resolver_creds",
    "canal_habilitado",
    "destinatario_permitido",
    "WhatsAppCreds",
    "WhatsAppWebhookError",
    "verify_signature",
    "verify_challenge",
    "procesar_evento",
]
