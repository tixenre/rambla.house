"""Tests HTTP/contrato de routes/facturacion_arca_service.py — transporte fino,
mismo patrón que test_facturacion_routes.py (el hermano de arca_fe): guard de
admin, mapeo de errores, sin DB ni red real (todo mockeado).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main
from arca_service_client import NotFoundError
from routes import facturacion_arca_service as route_module
from services.facturacion_arca_service.client import ArcaServiceNoConfiguradoError

pytestmark = pytest.mark.unit

_http = TestClient(main.app, raise_server_exceptions=False)


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _fake_pedido() -> dict:
    return {"id": 42, "numero_pedido": 422, "monto_total": 1000, "iva_monto": 0}


class _FakeEmbedResult:
    embed_url = "https://arca.example.com/embed/comprobantes/tok/comprobante.html"
    expires_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class _FakeClientOk:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def crear_embed_token(self, external_ref, idempotency_key):
        self.called_with = (external_ref, idempotency_key)
        return _FakeEmbedResult()


class _FakeClientRaises:
    def __init__(self, exc):
        self._exc = exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def crear_embed_token(self, external_ref, idempotency_key):
        raise self._exc


def _post(monkeypatch, *, admin=True):
    if admin:
        monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    return _http.post(
        "/api/admin/pedidos/42/factura-arca-service/embed",
        json={"external_ref": "cliente-abc"},
    )


def test_sin_sesion_admin_rechaza(monkeypatch):
    monkeypatch.delenv("ADMIN_BYPASS_AUTH", raising=False)
    r = _post(monkeypatch, admin=False)
    assert r.status_code in (401, 403)


def test_sin_credenciales_configuradas_da_503(monkeypatch):
    monkeypatch.setattr(route_module, "get_db", lambda: _FakeConn())
    monkeypatch.setattr(route_module, "_get_pedido", lambda conn, pedido_id: _fake_pedido())
    monkeypatch.setattr(
        route_module,
        "get_client",
        lambda: (_ for _ in ()).throw(ArcaServiceNoConfiguradoError("no configurado")),
    )
    r = _post(monkeypatch)
    assert r.status_code == 503
    assert "no configurado" in r.json()["detail"]


def test_pedido_inexistente_da_404(monkeypatch):
    monkeypatch.setattr(route_module, "get_db", lambda: _FakeConn())

    def _raise(conn, pedido_id):
        raise ValueError(f"Pedido {pedido_id} no encontrado")

    monkeypatch.setattr(route_module, "_get_pedido", _raise)
    r = _post(monkeypatch)
    assert r.status_code == 404


def test_feliz_devuelve_embed_url_y_expires_at(monkeypatch):
    monkeypatch.setattr(route_module, "get_db", lambda: _FakeConn())
    monkeypatch.setattr(route_module, "_get_pedido", lambda conn, pedido_id: _fake_pedido())
    fake_client = _FakeClientOk()
    monkeypatch.setattr(route_module, "get_client", lambda: fake_client)

    r = _post(monkeypatch)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["embed_url"] == _FakeEmbedResult.embed_url
    assert body["expires_at"] == _FakeEmbedResult.expires_at.isoformat()
    # idempotency_key determinística (numero_pedido, no un valor random) — misma
    # que arma comprobante.idempotency_key_de_pedido para el pedido 422.
    assert fake_client.called_with == ("cliente-abc", "pedido-422")


def test_not_found_error_de_la_sdk_mapea_a_404(monkeypatch):
    """`crear_embed_token` devuelve NotFoundError si la idempotency_key no
    resuelve a una emisión propia (comprobante nunca emitido en arca-service) —
    tiene que llegar como 404, no como 502/500 genérico."""
    monkeypatch.setattr(route_module, "get_db", lambda: _FakeConn())
    monkeypatch.setattr(route_module, "_get_pedido", lambda conn, pedido_id: _fake_pedido())
    monkeypatch.setattr(
        route_module,
        "get_client",
        lambda: _FakeClientRaises(
            NotFoundError("no encontrado en arca-service", status_code=404)
        ),
    )
    r = _post(monkeypatch)
    assert r.status_code == 404
