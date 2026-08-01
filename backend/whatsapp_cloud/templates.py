"""whatsapp_cloud.templates — alta y consulta de *message templates*. PORTABLE.

Meta separa dos superficies y acá se respeta esa separación:
  - **Cloud API** (mandar mensajes) → cuelga del `phone_number_id` → `client.py`.
  - **Business Management API** (administrar templates) → cuelga del **WABA id** →
    este módulo.

Por eso es un cliente aparte y no un método más de `WhatsAppClient`: la credencial
apunta a otra entidad y el token necesita otro permiso
(`whatsapp_business_management`, además del `_messaging` que usa el envío).

Dar de alta por API **no saltea la revisión de Meta**: el template nace en `PENDING`
y Meta lo aprueba o lo rechaza. Lo que evita es el copiar-pegar a mano de cada uno.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ._respuesta import pedir

_TIMEOUT_DEFAULT = 20.0


@dataclass(frozen=True)
class TemplateRemoto:
    """Un template tal como Meta lo conoce hoy."""

    name: str
    language: str
    status: str  # APPROVED | PENDING | REJECTED | PAUSED | DISABLED
    category: str
    id: Optional[str] = None
    motivo_rechazo: Optional[str] = None


@dataclass(frozen=True)
class WhatsAppTemplatesClient:
    """Administra los templates de UNA WhatsApp Business Account.

    `base_url` viene ya resuelta por el adapter (ej. 'https://graph.facebook.com/v21.0').
    """

    waba_id: str
    access_token: str
    base_url: str
    timeout: float = _TIMEOUT_DEFAULT

    def listar(self, *, limite: int = 100) -> list[TemplateRemoto]:
        """Los templates que existen hoy en la cuenta, con su estado de aprobación."""
        data = pedir(
            "GET",
            f"{self.base_url}/{self.waba_id}/message_templates",
            token=self.access_token,
            timeout=self.timeout,
            contexto="la consulta de templates",
            params={"fields": "name,status,category,language", "limit": limite},
        )
        filas = data.get("data") if isinstance(data, dict) else None
        if not isinstance(filas, list):
            return []
        out: list[TemplateRemoto] = []
        for f in filas:
            if not isinstance(f, dict) or not f.get("name"):
                continue
            out.append(
                TemplateRemoto(
                    name=str(f.get("name")),
                    language=str(f.get("language") or ""),
                    status=str(f.get("status") or "").upper(),
                    category=str(f.get("category") or "").lower(),
                    id=str(f["id"]) if f.get("id") else None,
                )
            )
        return out

    def crear_body(
        self,
        *,
        name: str,
        language: str,
        body_text: str,
        ejemplos: list[str],
        category: str = "UTILITY",
    ) -> TemplateRemoto:
        """Da de alta un template de solo-BODY con parámetros posicionales `{{n}}`.

        `ejemplos` son los valores de muestra que Meta exige para revisar, EN ORDEN
        (uno por cada `{{n}}`). Meta exige además que los `{{n}}` aparezcan en orden
        ascendente dentro del texto — eso lo garantiza el registro del adapter, no acá.
        """
        componentes: list[dict] = [{"type": "BODY", "text": body_text}]
        if ejemplos:
            componentes[0]["example"] = {"body_text": [list(ejemplos)]}

        payload = {
            "name": name,
            "language": language,
            "category": category.upper(),
            "parameter_format": "POSITIONAL",
            "components": componentes,
        }
        data = pedir(
            "POST",
            f"{self.base_url}/{self.waba_id}/message_templates",
            token=self.access_token,
            timeout=self.timeout,
            contexto=f"la creación del template '{name}'",
            json=payload,
        )
        estado = "PENDING"
        tid = None
        if isinstance(data, dict):
            estado = str(data.get("status") or "PENDING").upper()
            tid = str(data["id"]) if data.get("id") else None
        return TemplateRemoto(
            name=name, language=language, status=estado, category=category.lower(), id=tid
        )
