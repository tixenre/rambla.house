"""Tests HTTP del route del webhook de WhatsApp (`routes/whatsapp.py`).

A diferencia de `test_whatsapp_webhook.py` (unit, sobre `services/whatsapp/
webhook.py` puro), acá se pega contra la app real vía `TestClient` — necesario
para probar el tope de tamaño de body, que vive en el route (antes de llegar a
la firma/`procesar_evento`). Mismo patrón que `test_didit_webhook_threadpool.py`.
"""
from __future__ import annotations

import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

import main
import routes.whatsapp as wa_routes
from config import settings

pytestmark = pytest.mark.unit

_SECRET = "test-app-secret-whatsapp"


def _firmar(body: bytes) -> str:
    return "sha256=" + hmac.new(_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_webhook_rechaza_content_length_declarado_de_mas(monkeypatch):
    """Content-Length mentiroso por encima del tope → 413 sin leer el body."""
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", _SECRET)
    client = TestClient(main.app, raise_server_exceptions=False)
    res = client.post(
        "/api/webhooks/whatsapp",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(wa_routes._MAX_WEBHOOK_BODY + 1),
        },
    )
    assert res.status_code == 413


def test_webhook_rechaza_body_real_por_encima_del_tope(monkeypatch):
    """Sin Content-Length confiable, el chequeo post-lectura igual corta."""
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", _SECRET)
    body = b'{"padding": "' + b"x" * (wa_routes._MAX_WEBHOOK_BODY + 1) + b'"}'
    client = TestClient(main.app, raise_server_exceptions=False)
    res = client.post(
        "/api/webhooks/whatsapp", content=body, headers={"Content-Type": "application/json"}
    )
    assert res.status_code == 413


def test_webhook_body_chico_pasa_el_tope_y_llega_a_verificar_firma(monkeypatch):
    """Un body normal no lo frena el tope — sigue de largo hasta la firma (que acá
    falla a propósito, para no depender de la DB en este test)."""
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", _SECRET)
    body = b'{"entry": []}'
    client = TestClient(main.app, raise_server_exceptions=False)
    res = client.post(
        "/api/webhooks/whatsapp",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=invalida"},
    )
    assert res.status_code == 401  # pasó el tope de tamaño, rechazó por firma
