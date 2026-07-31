"""services.whatsapp.plantillas — registro de los *message templates* de WhatsApp.

**Fuente única** de qué templates existen y cómo se mapea el contexto de un pedido
a los parámetros del template. Este archivo NO define el copy en Meta (los templates
se dan de alta y se aprueban en el WhatsApp Manager); acá vive:

  - `key`        → identificador interno + `template_key` en `whatsapp_log`.
  - `meta_name`  → el nombre EXACTO del template aprobado en Meta (debe coincidir).
  - `lang`       → código de idioma del template en Meta (ej. `es_AR`).
  - `campos_ctx` → qué variables del contexto del pedido van al body, EN ORDEN
                   (mapean a los `{{1}}`, `{{2}}`, ... del template).
  - `copy_ejemplo` → el texto sugerido para dar de alta en Meta (categoría *utility*).

El contexto del pedido lo arma `services/comunicacion.pedido_email_context`
(la misma fuente que los mails), así el WhatsApp ve exactamente las mismas variables
ya formateadas (fechas amables, número de pedido, nombre).
"""
from __future__ import annotations

from dataclasses import dataclass

# Idioma de los templates en Meta. Debe coincidir con el que se elige al dar de
# alta cada template en el WhatsApp Manager. Argentina → es_AR.
LANG = "es_AR"


@dataclass(frozen=True)
class PlantillaWA:
    key: str
    meta_name: str
    lang: str
    idempotente_por_pedido: bool
    descripcion: str
    copy_ejemplo: str
    campos_ctx: tuple[str, ...]

    def params(self, ctx: dict) -> list[str]:
        """Valores del body EN ORDEN, tomados del contexto del pedido. Una clave
        ausente cae a "" (Meta rechaza un parámetro faltante, no uno vacío)."""
        return [str(ctx.get(c) or "") for c in self.campos_ctx]


# El registro es la lista de templates a pedir de alta en Meta (categoría utility).
# `{{n}}` en el copy_ejemplo se corresponde 1:1 con `campos_ctx` en el mismo orden.
REGISTRO: dict[str, PlantillaWA] = {
    "pedido_creado": PlantillaWA(
        key="pedido_creado",
        meta_name="pedido_creado",
        lang=LANG,
        idempotente_por_pedido=True,
        descripcion="Acuse al cliente cuando entra una solicitud de reserva.",
        copy_ejemplo=(
            "Hola {{1}} 👋 Recibimos tu solicitud de reserva Nº {{2}} en Rambla. "
            "Te avisamos apenas la confirmemos. ¡Gracias!"
        ),
        campos_ctx=("cliente_nombre", "numero_pedido"),
    ),
    "pedido_confirmado": PlantillaWA(
        key="pedido_confirmado",
        meta_name="pedido_confirmado",
        lang=LANG,
        idempotente_por_pedido=True,
        descripcion="Aviso al cliente cuando su reserva pasa a confirmada.",
        copy_ejemplo=(
            "Hola {{1}} 🎬 Tu reserva Nº {{2}} en Rambla quedó CONFIRMADA. "
            "Retiro: {{3}}. Cualquier cosa, respondé este mensaje."
        ),
        campos_ctx=("cliente_nombre", "numero_pedido", "fecha_desde"),
    ),
    "recordatorio_retiro": PlantillaWA(
        key="recordatorio_retiro",
        meta_name="recordatorio_retiro",
        lang=LANG,
        idempotente_por_pedido=True,
        descripcion="Recordatorio D-1 del retiro del equipo (reserva confirmada).",
        copy_ejemplo=(
            "Hola {{1}} 📸 Te recordamos que mañana retirás el equipo de tu reserva "
            "Nº {{2}} ({{3}}). ¡Te esperamos!"
        ),
        campos_ctx=("cliente_nombre", "numero_pedido", "fecha_desde"),
    ),
    "recordatorio_devolucion_d1": PlantillaWA(
        key="recordatorio_devolucion_d1",
        meta_name="recordatorio_devolucion_d1",
        lang=LANG,
        idempotente_por_pedido=True,
        descripcion="Recordatorio la víspera de la devolución (D-1).",
        copy_ejemplo=(
            "Hola {{1}} ⏰ Te recordamos que tu reserva Nº {{2}} vence mañana ({{3}}): "
            "pasá a devolver el equipo. ¡Gracias!"
        ),
        campos_ctx=("cliente_nombre", "numero_pedido", "fecha_hasta"),
    ),
    "recordatorio_devolucion_d0": PlantillaWA(
        key="recordatorio_devolucion_d0",
        meta_name="recordatorio_devolucion_d0",
        lang=LANG,
        idempotente_por_pedido=True,
        descripcion="Aviso el día de la devolución (D-0).",
        copy_ejemplo=(
            "Hola {{1}} 📅 Tu reserva Nº {{2}} vence hoy ({{3}}). Coordiná con nosotros "
            "la devolución del equipo. ¡Gracias!"
        ),
        campos_ctx=("cliente_nombre", "numero_pedido", "fecha_hasta"),
    ),
    "recordatorio_devolucion_vencido": PlantillaWA(
        key="recordatorio_devolucion_vencido",
        meta_name="recordatorio_devolucion_vencido",
        lang=LANG,
        idempotente_por_pedido=True,
        descripcion="Aviso al día siguiente si el equipo figura sin devolver (D+1).",
        copy_ejemplo=(
            "Hola {{1}} ⚠️ Tu reserva Nº {{2}} venció el {{3}} y el equipo figura sin "
            "devolver. Por favor comunicate para coordinar la devolución."
        ),
        campos_ctx=("cliente_nombre", "numero_pedido", "fecha_hasta"),
    ),
}
