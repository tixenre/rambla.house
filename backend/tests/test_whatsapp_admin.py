"""Aviso interno al equipo por WhatsApp (Pablo, Tincho) — sin red ni DB real.

Lo que importa acá: que le llegue a TODOS los del equipo (el bug que motivó el
cambio de índice), que no dependa del opt-in del cliente, y que un número roto o un
fallo de Meta no deje sin mensaje a los demás.
"""
from __future__ import annotations

import pytest

import services.whatsapp.envio as envio
from services.whatsapp.config import WhatsAppCreds

pytestmark = pytest.mark.unit


class _FakeCur:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConn:
    """`ya_enviados` = set de (alquiler_id, template_key, to_phone) ya 'sent'."""

    def __init__(self, ya_enviados=()):
        self.ya = set(ya_enviados)
        self.insertados: list[tuple] = []

    def execute(self, sql, params=()):
        if "SELECT id FROM whatsapp_log" in sql:
            aid, tpl, to = params[0], params[1], params[2]
            return _FakeCur({"id": 1} if (aid, tpl, to) in self.ya else None)
        return _FakeCur(None)

    def insert_returning(self, sql, params):
        self.insertados.append(params)
        return len(self.insertados)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class _FakeClient:
    def __init__(self, falla_en=()):
        self.falla_en = set(falla_en)
        self.enviados: list[str] = []

    def enviar_template(self, *, to, template_name, lang_code, body_params):
        from whatsapp_cloud import WhatsAppError

        if to in self.falla_en:
            raise WhatsAppError(f"Meta rechazó {to}")
        self.enviados.append(to)
        return type("R", (), {"message_id": f"wamid-{to}"})()


PEDIDO = {"id": 77, "cliente_id": 5}
CTX = {"numero_pedido": "1042", "cliente_nombre": "Ana", "fecha_desde": "15 jun"}
DOS = ["+5492235550001", "+5492235550002"]


def _preparar(monkeypatch, conn, client, numeros=DOS, permitido=True, habilitado=True):
    monkeypatch.setattr(envio, "resolver_creds",
                        lambda: WhatsAppCreds(phone_number_id="P", access_token="T", base_url="https://g"))
    monkeypatch.setattr(envio, "get_db", lambda: conn)
    monkeypatch.setattr(envio, "canal_habilitado", lambda c: habilitado)
    monkeypatch.setattr(envio, "destinatario_permitido", lambda to: permitido)
    import services.whatsapp.config as cfg
    monkeypatch.setattr(cfg, "destinatarios_admin", lambda c: list(numeros))
    import whatsapp_cloud
    monkeypatch.setattr(whatsapp_cloud, "WhatsAppClient", lambda **k: client)


def test_le_llega_a_todo_el_equipo(monkeypatch):
    """El bug que motivó el cambio de índice: con la clave vieja (pedido, plantilla)
    el segundo integrante se quedaba sin mensaje."""
    conn, client = _FakeConn(), _FakeClient()
    _preparar(monkeypatch, conn, client)
    out = envio.enviar_evento_admin("pedido_creado_admin", PEDIDO, CTX)
    assert out["enviados"] == 2
    assert client.enviados == DOS


def test_no_le_re_manda_al_que_ya_recibio(monkeypatch):
    """Idempotencia POR DESTINATARIO: uno ya lo tiene, el otro igual lo recibe."""
    conn = _FakeConn(ya_enviados={(77, "pedido_creado_admin", DOS[0])})
    client = _FakeClient()
    _preparar(monkeypatch, conn, client)
    out = envio.enviar_evento_admin("pedido_creado_admin", PEDIDO, CTX)
    assert out["enviados"] == 1
    assert client.enviados == [DOS[1]]


def test_uno_que_falla_no_deja_sin_mensaje_al_otro(monkeypatch):
    conn, client = _FakeConn(), _FakeClient(falla_en={DOS[0]})
    _preparar(monkeypatch, conn, client)
    out = envio.enviar_evento_admin("pedido_creado_admin", PEDIDO, CTX)
    assert out["ok"] is False and out["enviados"] == 1
    assert client.enviados == [DOS[1]]


def test_no_depende_del_opt_in_del_cliente(monkeypatch):
    """El equipo configuró sus números: ese es el consentimiento. Un cliente sin
    opt-in no puede dejar al equipo sin enterarse del pedido."""
    conn, client = _FakeConn(), _FakeClient()
    _preparar(monkeypatch, conn, client)
    monkeypatch.setattr(envio, "_opt_in", lambda c, cid: False)
    out = envio.enviar_evento_admin("pedido_creado_admin", PEDIDO, CTX)
    assert out["enviados"] == 2


def test_sin_numeros_configurados_no_rompe(monkeypatch):
    conn, client = _FakeConn(), _FakeClient()
    _preparar(monkeypatch, conn, client, numeros=[])
    out = envio.enviar_evento_admin("pedido_creado_admin", PEDIDO, CTX)
    assert out["ok"] is True and out["enviados"] == 0
    assert out["reason"] == "sin_destinatarios"


def test_canal_apagado_no_manda(monkeypatch):
    conn, client = _FakeConn(), _FakeClient()
    _preparar(monkeypatch, conn, client, habilitado=False)
    out = envio.enviar_evento_admin("pedido_creado_admin", PEDIDO, CTX)
    assert out["enviados"] == 0 and client.enviados == []


def test_params_en_el_orden_del_template():
    from services.whatsapp.plantillas import REGISTRO

    p = REGISTRO["pedido_creado_admin"]
    assert p.campos_ctx == ("numero_pedido", "cliente_nombre", "fecha_desde")
    assert p.params(CTX) == ["1042", "Ana", "15 jun"]
