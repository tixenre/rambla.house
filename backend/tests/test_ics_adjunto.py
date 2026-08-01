"""Test del consumidor del `.ics` adjunto al mail de confirmación
(`_ics_adjunto_pedido`).

La infra de adjuntos en sí (`Attachment` + propagación a los backends) se prueba
en `test_email_attachments.py`. Acá se verifica lo propio de esta rama: que un
pedido se convierte en un `Attachment` `.ics` válido y con el recordatorio
(`VALARM`) embebido, usando el generador canónico de `services/ical.py`.
"""
from datetime import datetime

import pytest

from services.comunicacion import ics_adjunto_pedido as _ics_adjunto_pedido
from services.email.base import Attachment

pytestmark = pytest.mark.unit


def _pedido(**over):
    base = {
        "id": 50,
        "numero_pedido": 1050,
        "cliente_nombre": "Juana",
        "estado": "confirmado",
        "tipo": "diaria",
        "fecha_desde": datetime(2026, 6, 5, 10, 0),
        "fecha_hasta": datetime(2026, 6, 6, 18, 0),
        "items": [],
    }
    base.update(over)
    return base


def test_devuelve_attachment_ics_con_recordatorio():
    adj = _ics_adjunto_pedido(_pedido())
    assert adj is not None and len(adj) == 1
    a = adj[0]
    assert isinstance(a, Attachment)
    assert a.filename == "pedido-1050.ics"
    assert a.mimetype.startswith("text/calendar")
    assert b"BEGIN:VCALENDAR" in a.content
    assert b"BEGIN:VALARM" in a.content  # recordatorio embebido (with_reminders)


def test_sin_fecha_desde_devuelve_none():
    assert _ics_adjunto_pedido(_pedido(fecha_desde=None)) is None
