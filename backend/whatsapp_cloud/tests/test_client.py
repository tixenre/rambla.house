"""Unit tests del cliente portable: mapeo respuesta de Meta → resultado/error tipado.

Sin red: se construyen `httpx.Response` reales y se interpretan, o se monkeypatchea
`httpx.post` para simular transporte. Espeja el estilo de los tests de `arca_fe`.
"""
from __future__ import annotations

import httpx
import pytest

from whatsapp_cloud import (
    EnvioResult,
    WhatsAppAuthError,
    WhatsAppClient,
    WhatsAppNetworkError,
    WhatsAppRateLimitError,
    WhatsAppRequestError,
    WhatsAppResponseError,
    body_components,
    with_retry,
)
from whatsapp_cloud.client import _CODIGOS_AUTH


def _client() -> WhatsAppClient:
    return WhatsAppClient(
        phone_number_id="123456", access_token="TESTTOKEN", base_url="https://graph.example/v21.0"
    )


def _resp(status, *, json=None, headers=None, text=None):
    if json is not None:
        return httpx.Response(status, json=json, headers=headers or {})
    return httpx.Response(status, text=text or "", headers=headers or {})


def test_body_components_vacio_y_lleno():
    assert body_components([]) == []
    comps = body_components(["Ana", "#42"])
    assert comps == [
        {"type": "body", "parameters": [{"type": "text", "text": "Ana"}, {"type": "text", "text": "#42"}]}
    ]


def test_exito_devuelve_wamid():
    resp = _resp(200, json={"messages": [{"id": "wamid.ABC"}]})
    res = WhatsAppClient._interpretar(resp, to="+549223", template_name="pedido_creado")
    assert isinstance(res, EnvioResult)
    assert res.message_id == "wamid.ABC"
    assert res.to == "+549223"
    assert res.template_name == "pedido_creado"


def test_200_sin_messages_es_response_error():
    resp = _resp(200, json={"messaging_product": "whatsapp"})
    with pytest.raises(WhatsAppResponseError):
        WhatsAppClient._interpretar(resp, to="+549223", template_name="t")


def test_401_es_auth_error():
    resp = _resp(401, json={"error": {"message": "Invalid OAuth token", "code": 190}})
    with pytest.raises(WhatsAppAuthError):
        WhatsAppClient._interpretar(resp, to="+549223", template_name="t")


def test_codigo_auth_gana_sobre_status_400():
    # code 190 (token vencido) puede venir con 400 → igual es Auth, no Request.
    assert 190 in _CODIGOS_AUTH
    resp = _resp(400, json={"error": {"message": "Session expired", "code": 190}})
    with pytest.raises(WhatsAppAuthError):
        WhatsAppClient._interpretar(resp, to="+549223", template_name="t")


def test_429_es_rate_limit_con_retry_after():
    resp = _resp(429, json={"error": {"message": "rate", "code": 130429}}, headers={"Retry-After": "12"})
    with pytest.raises(WhatsAppRateLimitError) as ei:
        WhatsAppClient._interpretar(resp, to="+549223", template_name="t")
    assert ei.value.retry_after == 12.0


def test_400_numero_invalido_es_request_error():
    resp = _resp(400, json={"error": {"message": "Recipient not in allowed list", "code": 131030}})
    with pytest.raises(WhatsAppRequestError) as ei:
        WhatsAppClient._interpretar(resp, to="+549223", template_name="t")
    assert ei.value.codigo == 131030
    assert "allowed list" in str(ei.value)


def test_500_es_network_error():
    resp = _resp(500, text="upstream error")
    with pytest.raises(WhatsAppNetworkError):
        WhatsAppClient._interpretar(resp, to="+549223", template_name="t")


def test_transporte_caido_es_network_error(monkeypatch):
    def _boom(*a, **k):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr("whatsapp_cloud.client.httpx.post", _boom)
    with pytest.raises(WhatsAppNetworkError):
        _client().enviar_template(to="+549223", template_name="t", lang_code="es_AR", body_params=["x"])


def test_enviar_template_valida_input():
    with pytest.raises(ValueError):
        _client().enviar_template(to="", template_name="t", lang_code="es_AR")
    with pytest.raises(ValueError):
        _client().enviar_template(to="+549", template_name="", lang_code="es_AR")


def test_with_retry_reintenta_network_y_despues_ok():
    llamadas = {"n": 0}

    def fn():
        llamadas["n"] += 1
        if llamadas["n"] < 2:
            raise WhatsAppNetworkError("timeout")
        return "ok"

    assert with_retry(fn, intentos=3, backoff_inicial=0.0) == "ok"
    assert llamadas["n"] == 2


def test_with_retry_no_reintenta_request_error():
    llamadas = {"n": 0}

    def fn():
        llamadas["n"] += 1
        raise WhatsAppRequestError("número inválido", errores=((131030, "x"),))

    with pytest.raises(WhatsAppRequestError):
        with_retry(fn, intentos=3, backoff_inicial=0.0)
    assert llamadas["n"] == 1  # no reintentó
