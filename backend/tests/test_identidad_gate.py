"""Gate de verificación de identidad (PR1 + PR2).

PR1: "Verificado" = `clientes.dni_validado_at IS NOT NULL`. El gate rechaza con
403 los flujos de creación de pedido (`POST /api/cliente/pedidos`) y de reserva
del estudio (`POST /api/estudio/reservas`). Sesión Didit acepta `return_to`
interno (allowlist anti open-redirect); inválido/ausente → fallback (nunca 400).

PR2: Webhook Didit maneja "Declined" → estado='rechazado' y "Processing" /
"In_review" / "Under_review" → estado='en_revision'. "Approved" sigue
escribiendo estado='verificado' (cubierto en integración; aquí solo los nuevos).

Tests puros: TestClient + monkeypatch de DB y clientes Didit. Sin DB ni red.
"""

import pytest
from fastapi.testclient import TestClient

import main
from auth.session import signer
from routes.didit import _es_path_interno_seguro

pytestmark = pytest.mark.unit

client = TestClient(main.app, raise_server_exceptions=False)

# Cookie de cliente firmada con el signer real de la app (mismo SECRET_KEY de tests).
_COOKIE_CLIENTE = f"session={signer.dumps({'email': 'x@test.com', 'role': 'cliente', 'cliente_id': 123, 'jti': 'gate-cli'})}"


@pytest.fixture(autouse=True)
def _sessions_active(monkeypatch):
    """jti obligatorio: la cookie de test lleva jti pero no está en la allowlist →
    stubbeamos is_active para darla por activa y que el request llegue al guard."""
    monkeypatch.setattr("auth.queries.sessions.is_active", lambda jti: {"jti": jti})


# ── Fakes de DB ───────────────────────────────────────────────────────────────

class _FakeRow(dict):
    """sqlite3.Row-like: subscriptable y .keys()."""


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class _FakeConn:
    """Conn fake que siempre devuelve la misma fila de cliente para cualquier
    SELECT sobre `clientes`. Suficiente para que el gate decida. El cooldown
    anti-ráfaga (#1169) consulta `kyc_events` aparte — sin fila "reciente" acá
    (None), o los tests de creación exitosa quedarían siempre bloqueados con 429."""

    def __init__(self, cliente_row):
        self._row = cliente_row

    def execute(self, sql, params=()):
        if "kyc_events" in sql:
            return _FakeCursor(None)
        return _FakeCursor(self._row)

    def commit(self):
        pass

    def rollback(self):
        # El handler del estudio envuelve todo en try/except → rollback() al
        # propagar (incluso un HTTPException del gate). El conn real lo tiene.
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass


def _fake_get_db(cliente_row):
    return lambda: _FakeConn(cliente_row)


# ── Gate: POST /api/cliente/pedidos ───────────────────────────────────────────

_BODY_PEDIDO = {
    "fecha_desde": "2030-01-01T10:00",
    "fecha_hasta": "2030-01-02T10:00",
    "items": [{"equipo_id": 7, "cantidad": 1, "precio_jornada": 1}],
}


def test_pedido_cliente_sin_verificar_devuelve_403(monkeypatch):
    """Cliente con dni_validado_at=None → el gate corta con 403 antes de crear."""
    monkeypatch.setattr(
        "auth.guards.get_db",
        _fake_get_db(_FakeRow(id=123, dni_validado_at=None)),
    )
    res = client.post(
        "/api/cliente/pedidos", json=_BODY_PEDIDO, headers={"Cookie": _COOKIE_CLIENTE}
    )
    assert res.status_code == 403, res.text


def test_pedido_cliente_verificado_no_bloquea_por_identidad(monkeypatch):
    """Cliente verificado → el gate NO bloquea. Puede fallar después por otra
    validación, pero NUNCA con 403 por identidad."""
    monkeypatch.setattr(
        "auth.guards.get_db",
        _fake_get_db(_FakeRow(id=123, dni_validado_at="2026-06-01T10:00:00")),
    )
    res = client.post(
        "/api/cliente/pedidos", json=_BODY_PEDIDO, headers={"Cookie": _COOKIE_CLIENTE}
    )
    assert res.status_code != 403, (
        f"El gate bloqueó por identidad a un cliente verificado → {res.status_code}"
    )


# ── Gate: POST /api/estudio/reservas ──────────────────────────────────────────

_BODY_ESTUDIO = {
    "fecha": "2030-01-01",
    "start": "09:00",
    "horas": 2,
}


def test_reserva_estudio_sin_verificar_devuelve_403(monkeypatch):
    """Cliente sin verificar → 403 en la reserva del estudio. El handler hace su
    propio SELECT del cliente (al que le agregamos dni_validado_at); la fila del
    estudio (id=1) la sirve el mismo FakeConn antes — devolvemos una fila con
    equipo_id seteado para pasar el chequeo previo y llegar al cliente."""
    fila = _FakeRow(
        id=1, equipo_id=99, nombre="X", apellido="Y", email="x@test.com",
        telefono="1", dni_validado_at=None,
    )
    monkeypatch.setattr("routes.estudio.get_db", _fake_get_db(fila))
    res = client.post(
        "/api/estudio/reservas", json=_BODY_ESTUDIO, headers={"Cookie": _COOKIE_CLIENTE}
    )
    assert res.status_code == 403, res.text


# ── Allowlist anti open-redirect ──────────────────────────────────────────────

@pytest.mark.parametrize(
    "p",
    [
        "/",
        "/x",
        "/?pedido=retomar",
        "/estudio?d=2026-01-01&h=09:00",
    ],
)
def test_path_interno_seguro_acepta(p):
    assert _es_path_interno_seguro(p) is True


@pytest.mark.parametrize(
    "p",
    [
        "",
        None,
        "//evil.com",
        "http://evil",
        "https://x",
        "/\\evil",
        "\\\\evil",
        "/x\n",
        "/" + "a" * 600,
    ],
)
def test_path_interno_seguro_rechaza(p):
    assert _es_path_interno_seguro(p) is False


# ── return_to en la sesión Didit ──────────────────────────────────────────────

class _FakeSession:
    def __init__(self):
        self.session_id = "sess-test"
        self.url = "https://verification.didit.me/redirect"


def _capture_create_session(monkeypatch):
    """Mockea create_session en routes.didit para capturar el return_url y evita
    pegarle a la API real. Mockea también el UPDATE de clientes (get_db)."""
    captured = {}

    def fake_create_session(*, return_url, vendor_data):
        captured["return_url"] = return_url
        return _FakeSession()

    monkeypatch.setattr("routes.didit.create_session", fake_create_session)
    monkeypatch.setattr(
        "routes.didit.get_db", _fake_get_db(_FakeRow(id=123)),
    )
    # El endpoint ahora registra consentimiento (identity/kyc) — no-op en este test.
    monkeypatch.setattr("routes.didit.kyc.registrar_consentimiento", lambda *a, **k: None)
    return captured


def test_sesion_return_to_interno_se_cuela_urlencoded(monkeypatch):
    captured = _capture_create_session(monkeypatch)
    res = client.post(
        "/api/cliente/verificacion/sesion",
        json={"return_to": "/?pedido=retomar"},
        headers={"Cookie": _COOKIE_CLIENTE},
    )
    assert res.status_code == 201, res.text
    ru = captured["return_url"]
    assert "return_to=" in ru
    # Urlencodeado: la barra y el '?' del path interno van escapados (%2F / %3F).
    assert "%2F" in ru


def test_sesion_return_to_externo_cae_al_fallback(monkeypatch):
    captured = _capture_create_session(monkeypatch)
    res = client.post(
        "/api/cliente/verificacion/sesion",
        json={"return_to": "http://evil"},
        headers={"Cookie": _COOKIE_CLIENTE},
    )
    assert res.status_code == 201, res.text
    assert "return_to=" not in captured["return_url"]


def test_sesion_sin_body_sigue_creando(monkeypatch):
    """El portal hoy postea SIN body → no debe romper (no 422); usa el fallback."""
    captured = _capture_create_session(monkeypatch)
    res = client.post(
        "/api/cliente/verificacion/sesion",
        headers={"Cookie": _COOKIE_CLIENTE},
    )
    assert res.status_code == 201, res.text
    assert "return_to=" not in captured["return_url"]


# ── Webhook PR2: el route fino delega en identity/kyc ────────────────────────
# El route es transporte: mapea el status de Didit → la llamada a kyc. La conducta
# (el UPDATE del estado) se testea en test_identity_kyc. Acá: que delegue bien.


def _mock_webhook(monkeypatch):
    """No-op del HMAC + captura de las llamadas a kyc.* (el route delega en kyc)."""
    calls = {"aprobar": [], "actualizar": []}
    monkeypatch.setattr("routes.didit.verify_webhook", lambda **kw: None)
    monkeypatch.setattr("routes.didit.kyc.aprobar", lambda **kw: calls["aprobar"].append(kw) or True)
    monkeypatch.setattr("routes.didit.kyc.actualizar_estado",
                        lambda **kw: calls["actualizar"].append(kw) or True)
    return calls


_WH_HEADERS = {"X-Signature": "x", "X-Timestamp": "0"}


def test_webhook_declined_delega_rechazado(monkeypatch):
    """Webhook Declined → kyc.actualizar_estado(estado='rechazado', motivo=…)."""
    calls = _mock_webhook(monkeypatch)
    res = client.post(
        "/api/webhooks/didit",
        json={"session_id": "sess-decline", "status": "Declined", "vendor_data": "123",
              "decision": {"decline_reason": "foto borrosa"}},
        headers=_WH_HEADERS,
    )
    assert res.status_code == 200, res.text
    assert calls["actualizar"], "no delegó en kyc.actualizar_estado"
    kw = calls["actualizar"][0]
    assert kw["estado"] == "rechazado" and kw["motivo"] == "foto borrosa"
    assert kw["cliente_id"] == 123 and kw["session_id"] == "sess-decline"


def test_webhook_processing_delega_en_revision(monkeypatch):
    """Webhook Processing → kyc.actualizar_estado(estado='en_revision', motivo None)."""
    calls = _mock_webhook(monkeypatch)
    res = client.post(
        "/api/webhooks/didit",
        json={"session_id": "sess-proc", "status": "Processing", "vendor_data": "123"},
        headers=_WH_HEADERS,
    )
    assert res.status_code == 200, res.text
    assert calls["actualizar"], "no delegó en kyc.actualizar_estado"
    kw = calls["actualizar"][0]
    assert kw["estado"] == "en_revision" and kw.get("motivo") is None


def test_webhook_in_review_delega_en_revision(monkeypatch):
    """Webhook In_review → mismo camino que Processing."""
    calls = _mock_webhook(monkeypatch)
    res = client.post(
        "/api/webhooks/didit",
        json={"session_id": "sess-review", "status": "In_review", "vendor_data": "123"},
        headers=_WH_HEADERS,
    )
    assert res.status_code == 200, res.text
    assert calls["actualizar"] and calls["actualizar"][0]["estado"] == "en_revision"
