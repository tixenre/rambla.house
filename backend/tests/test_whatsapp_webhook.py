"""Tests del webhook entrante de WhatsApp (`services/whatsapp/webhook.py`).

Sin red/DB real: firma HMAC calculada a mano, conn/cliente fakeados. Espeja el
estilo de `tests/test_didit_webhook.py` (mismo patrón de firma fail-closed).
"""
from __future__ import annotations

import hashlib
import hmac

import pytest

import services.whatsapp.webhook as wh
from config import settings

pytestmark = pytest.mark.unit


def _firmar(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


# ── verify_signature ──────────────────────────────────────────────────────
def test_signature_valida_pasa(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", "s3cr3t")
    body = b'{"entry": []}'
    wh.verify_signature(body, _firmar(body, "s3cr3t"))  # no levanta


def test_signature_invalida_rechaza(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", "s3cr3t")
    with pytest.raises(wh.WhatsAppWebhookError):
        wh.verify_signature(b'{"entry": []}', _firmar(b'{"entry": []}', "otro-secret"))


def test_signature_sin_header_rechaza(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", "s3cr3t")
    with pytest.raises(wh.WhatsAppWebhookError):
        wh.verify_signature(b"{}", "")


def test_signature_sin_secret_configurado_rechaza_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", "")
    with pytest.raises(wh.WhatsAppWebhookError):
        wh.verify_signature(b"{}", "sha256=loquesea")


# ── verify_challenge ──────────────────────────────────────────────────────
def test_challenge_valido_devuelve_el_challenge(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "mi-token")
    assert wh.verify_challenge("subscribe", "mi-token", "XYZ123") == "XYZ123"


def test_challenge_token_incorrecto_rechaza(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "mi-token")
    with pytest.raises(wh.WhatsAppWebhookError):
        wh.verify_challenge("subscribe", "otro", "XYZ123")


def test_challenge_mode_incorrecto_rechaza(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "mi-token")
    with pytest.raises(wh.WhatsAppWebhookError):
        wh.verify_challenge("unsubscribe", "mi-token", "XYZ123")


def test_challenge_sin_token_configurado_rechaza(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "")
    with pytest.raises(wh.WhatsAppWebhookError):
        wh.verify_challenge("subscribe", "cualquiera", "XYZ123")


# ── _aplicar_estados ──────────────────────────────────────────────────────
class _FakeConn:
    def __init__(self):
        self.updates = []

    def execute(self, sql, params=()):
        self.updates.append(params)
        return self


def test_aplicar_estados_actualiza_por_wamid():
    conn = _FakeConn()
    value = {"statuses": [{"id": "wamid.A", "status": "delivered"}]}
    n = wh._aplicar_estados(value, conn)
    assert n == 1
    assert conn.updates == [("delivered", None, "wamid.A")]


def test_aplicar_estados_guarda_el_error_si_fallo():
    conn = _FakeConn()
    value = {
        "statuses": [
            {"id": "wamid.B", "status": "failed", "errors": [{"title": "Recipient unreachable"}]}
        ]
    }
    wh._aplicar_estados(value, conn)
    assert conn.updates == [("failed", "Recipient unreachable", "wamid.B")]


def test_aplicar_estados_ignora_estado_desconocido_o_sin_wamid():
    conn = _FakeConn()
    value = {"statuses": [{"id": "wamid.C", "status": "sent"}, {"status": "delivered"}]}
    assert wh._aplicar_estados(value, conn) == 0
    assert conn.updates == []


# ── es_mensaje_de_baja ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "texto",
    [
        "BAJA", "baja", "Baja por favor", "STOP", "no me escriban mas",
        "No me escriban", "cancelar avisos", "unsubscribe", "NO MOLESTEN",
        "no molestar", "no me molesten mas",
    ],
)
def test_es_mensaje_de_baja_detecta_variantes(texto):
    assert wh.es_mensaje_de_baja(texto) is True


@pytest.mark.parametrize(
    "texto",
    ["", "hola", "trabajaba en eso", "cuando retiro el equipo?", "gracias!", "che bajá el volumen"],
)
def test_es_mensaje_de_baja_no_falsos_positivos_obvios(texto):
    assert wh.es_mensaje_de_baja(texto) is False


# ── _resolver_cliente_por_telefono / _procesar_baja ───────────────────────
class _FakeCursorRow:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConnClientes:
    """Sirve los SELECT de verified_contacts/clientes y registra el UPDATE."""

    def __init__(self, *, verified=None, cliente=None):
        self._verified = verified
        self._cliente = cliente
        self.updates = []

    def execute(self, sql, params=()):
        upper = sql.strip().upper()
        if "VERIFIED_CONTACTS" in upper:
            return _FakeCursorRow(self._verified)
        if upper.startswith("SELECT ID FROM CLIENTES"):
            return _FakeCursorRow(self._cliente)
        if upper.startswith("UPDATE CLIENTES"):
            self.updates.append(params)
            return _FakeCursorRow(None)
        raise AssertionError(f"query inesperada en el fake: {sql}")


def test_resolver_cliente_por_telefono_prioriza_verified_contacts():
    conn = _FakeConnClientes(verified={"cliente_id": 7}, cliente={"id": 999})
    assert wh._resolver_cliente_por_telefono(conn, "+5492235550000") == 7


def test_resolver_cliente_por_telefono_cae_a_clientes_base():
    conn = _FakeConnClientes(verified=None, cliente={"id": 9})
    assert wh._resolver_cliente_por_telefono(conn, "+5492235550000") == 9


def test_resolver_cliente_por_telefono_no_encuentra():
    conn = _FakeConnClientes(verified=None, cliente=None)
    assert wh._resolver_cliente_por_telefono(conn, "+5492235550000") is None


def test_procesar_baja_actualiza_opt_in_y_devuelve_true():
    conn = _FakeConnClientes(verified={"cliente_id": 7})
    assert wh._procesar_baja(conn, "5492235550000") is True
    assert len(conn.updates) == 1
    assert conn.updates[0][1] == 7  # (now_ar(), cliente_id)


def test_procesar_baja_sin_cliente_conocido_no_actualiza_y_devuelve_false():
    conn = _FakeConnClientes(verified=None, cliente=None)
    assert wh._procesar_baja(conn, "5492235550000") is False
    assert conn.updates == []


def test_procesar_baja_telefono_invalido_no_actualiza():
    conn = _FakeConnClientes(verified={"cliente_id": 7})
    assert wh._procesar_baja(conn, "no-es-un-telefono") is False
    assert conn.updates == []


# ── _responder_entrantes ──────────────────────────────────────────────────
def test_responder_entrantes_sin_creds_no_hace_nada(monkeypatch):
    monkeypatch.setattr("services.whatsapp.config.resolver_creds", lambda: None)
    n = wh._responder_entrantes({"messages": [{"from": "+549", "id": "wamid.IN"}]}, conn=object())
    assert n == 0


def test_responder_entrantes_envia_y_cuenta(monkeypatch):
    import whatsapp_cloud

    class _Creds:
        phone_number_id = "123"
        access_token = "TOK"
        base_url = "https://graph.example/v21.0"

    monkeypatch.setattr("services.whatsapp.config.resolver_creds", lambda: _Creds())
    monkeypatch.setattr("services.comunicacion.contacto.telefono_negocio", lambda conn: "+54 9 223 585-2510")

    enviados = []

    class _FakeClient:
        def __init__(self, **kw):
            pass

        def enviar_texto(self, *, to, body):
            enviados.append((to, body))
            return whatsapp_cloud.EnvioResult(message_id="wamid.OUT", to=to)

    monkeypatch.setattr(whatsapp_cloud, "WhatsAppClient", _FakeClient)

    value = {"messages": [{"from": "+5492235550000", "id": "wamid.IN", "type": "text"}]}
    n = wh._responder_entrantes(value, conn=object())
    assert n == 1
    assert enviados[0][0] == "+5492235550000"
    assert "+54 9 223 585-2510" in enviados[0][1]


def test_responder_entrantes_baja_con_cliente_conocido_apaga_opt_in_y_confirma(monkeypatch):
    import whatsapp_cloud

    class _Creds:
        phone_number_id = "123"
        access_token = "TOK"
        base_url = "https://graph.example/v21.0"

    monkeypatch.setattr("services.whatsapp.config.resolver_creds", lambda: _Creds())
    monkeypatch.setattr("services.comunicacion.contacto.telefono_negocio", lambda conn: "+549")

    enviados = []

    class _FakeClient:
        def __init__(self, **kw):
            pass

        def enviar_texto(self, *, to, body):
            enviados.append((to, body))
            return whatsapp_cloud.EnvioResult(message_id="wamid.OUT", to=to)

    monkeypatch.setattr(whatsapp_cloud, "WhatsAppClient", _FakeClient)

    conn = _FakeConnClientes(verified={"cliente_id": 42})
    value = {
        "messages": [
            {"from": "5492235550000", "id": "wamid.IN", "text": {"body": "BAJA por favor"}}
        ]
    }
    n = wh._responder_entrantes(value, conn=conn)
    assert n == 1
    assert conn.updates and conn.updates[0][1] == 42  # opt_in apagado para ESE cliente
    assert "no te vamos a volver a escribir" in enviados[0][1].lower()


def test_responder_entrantes_baja_sin_cliente_conocido_solo_redirige(monkeypatch):
    import whatsapp_cloud

    class _Creds:
        phone_number_id = "123"
        access_token = "TOK"
        base_url = "https://graph.example/v21.0"

    monkeypatch.setattr("services.whatsapp.config.resolver_creds", lambda: _Creds())
    monkeypatch.setattr("services.comunicacion.contacto.telefono_negocio", lambda conn: "+549")

    enviados = []

    class _FakeClient:
        def __init__(self, **kw):
            pass

        def enviar_texto(self, *, to, body):
            enviados.append((to, body))
            return whatsapp_cloud.EnvioResult(message_id="wamid.OUT", to=to)

    monkeypatch.setattr(whatsapp_cloud, "WhatsAppClient", _FakeClient)

    conn = _FakeConnClientes(verified=None, cliente=None)
    value = {"messages": [{"from": "5492235550000", "id": "wamid.IN", "text": {"body": "STOP"}}]}
    n = wh._responder_entrantes(value, conn=conn)
    assert n == 1
    assert conn.updates == []
    assert "no llegan" in enviados[0][1].lower()  # el copy genérico de redirect


def test_responder_entrantes_un_fallo_de_envio_no_rompe(monkeypatch):
    import whatsapp_cloud

    class _Creds:
        phone_number_id = "123"
        access_token = "TOK"
        base_url = "https://graph.example/v21.0"

    monkeypatch.setattr("services.whatsapp.config.resolver_creds", lambda: _Creds())
    monkeypatch.setattr("services.comunicacion.contacto.telefono_negocio", lambda conn: "+549")

    class _FakeClient:
        def __init__(self, **kw):
            pass

        def enviar_texto(self, *, to, body):
            raise whatsapp_cloud.WhatsAppError("boom")

    monkeypatch.setattr(whatsapp_cloud, "WhatsAppClient", _FakeClient)
    value = {"messages": [{"from": "+549", "id": "wamid.IN"}]}
    assert wh._responder_entrantes(value, conn=object()) == 0  # no propaga, cuenta 0 enviados


def test_responder_entrantes_sin_mensajes_no_hace_nada():
    assert wh._responder_entrantes({}, conn=object()) == 0


# ── procesar_evento (orquestación) ────────────────────────────────────────
def test_procesar_evento_cuenta_entregas_y_respuestas(monkeypatch):
    import whatsapp_cloud

    class _Creds:
        phone_number_id = "123"
        access_token = "TOK"
        base_url = "https://graph.example/v21.0"

    monkeypatch.setattr("services.whatsapp.config.resolver_creds", lambda: _Creds())
    monkeypatch.setattr("services.comunicacion.contacto.telefono_negocio", lambda conn: "+549")

    class _FakeClient:
        def __init__(self, **kw):
            pass

        def enviar_texto(self, *, to, body):
            return whatsapp_cloud.EnvioResult(message_id="wamid.OUT", to=to)

    monkeypatch.setattr(whatsapp_cloud, "WhatsAppClient", _FakeClient)

    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{"id": "wamid.A", "status": "delivered"}],
                    "messages": [{"from": "+549", "id": "wamid.IN"}],
                }
            }]
        }]
    }
    out = wh.procesar_evento(payload, _FakeConn())
    assert out == {"entregas_actualizadas": 1, "mensajes_respondidos": 1}


def test_procesar_evento_payload_basura_no_propaga():
    assert wh.procesar_evento({"entry": "no es una lista de dicts"}, _FakeConn()) == {
        "entregas_actualizadas": 0,
        "mensajes_respondidos": 0,
    }


def test_procesar_evento_sin_entry_es_no_op():
    assert wh.procesar_evento({}, _FakeConn()) == {
        "entregas_actualizadas": 0,
        "mensajes_respondidos": 0,
    }
