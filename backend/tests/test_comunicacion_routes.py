"""Tests del endpoint del módulo de Comunicación (`routes/comunicacion.py`).

Lo que importa acá: el back-office NO puede tener su propia lista de eventos — el
endpoint tiene que espejar el `REGISTRO` (fuente única). Si alguien agrega un evento
y no aparece en la pantalla, esto lo caza.
"""
from __future__ import annotations

import pytest

import routes.comunicacion as rc
from services.comunicacion.eventos import ESTRATEGIA_LABEL, ESTRATEGIAS, REGISTRO

pytestmark = pytest.mark.unit


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Sirve `email_templates` desde un dict key → (subject, enabled)."""

    def __init__(self, templates):
        self._t = templates

    def execute(self, sql, params=()):
        return _FakeCursor(
            [
                {"key": k, "subject": v[0], "enabled": v[1]}
                for k, v in self._t.items()
                if k in list(params)
            ]
        )

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_deps(monkeypatch, templates):
    monkeypatch.setattr(rc, "require_admin", lambda request: None)
    monkeypatch.setattr(rc, "get_db", lambda: _FakeConn(templates))
    import services.email.service as es
    import services.whatsapp as wa

    monkeypatch.setattr(
        es, "channel_status", lambda: {"provider": "test", "activo": False, "from_addr": "x@y", "admin_to": "a@b"}
    )
    monkeypatch.setattr(
        wa, "diagnosticar", lambda conn: {"listo": False, "chequeos": [], "ambiente": "no_produccion"}
    )


# Todos los templates de mail que el registro referencia, como si existieran.
_TODOS = {
    t: (f"Asunto de {t}", True)
    for ev in REGISTRO.values()
    if ev.mail
    for t in (ev.mail.template_cliente, ev.mail.template_admin)
    if t
}


def test_devuelve_todos_los_eventos_del_registro(monkeypatch):
    """Espeja el REGISTRO: ni de más ni de menos."""
    _fake_deps(monkeypatch, _TODOS)
    out = rc.listar_eventos(request=None)
    assert {e["key"] for e in out["eventos"]} == set(REGISTRO)


def test_cada_evento_trae_estrategia_legible(monkeypatch):
    _fake_deps(monkeypatch, _TODOS)
    for e in rc.listar_eventos(request=None)["eventos"]:
        assert e["estrategia"] in ESTRATEGIAS
        assert e["estrategia_label"] == ESTRATEGIA_LABEL[e["estrategia"]]
        assert e["estrategia_detalle"]  # no vacío: la pantalla lo muestra


def test_marca_un_template_de_mail_que_no_existe(monkeypatch):
    """Si el registro apunta a un template ausente, el evento no podría mandar ese
    mail — la pantalla tiene que poder gritarlo (`existe: False`)."""
    _fake_deps(monkeypatch, {})  # ningún template en la tabla
    out = rc.listar_eventos(request=None)
    con_mail = [e for e in out["eventos"] if e["mail_cliente"]]
    assert con_mail, "el registro debería tener al menos un evento con mail al cliente"
    assert all(e["mail_cliente"]["existe"] is False for e in con_mail)


def test_confirmado_declara_ics_y_devolucion_no_tiene_mail(monkeypatch):
    _fake_deps(monkeypatch, _TODOS)
    por_key = {e["key"]: e for e in rc.listar_eventos(request=None)["eventos"]}
    assert por_key["pedido_confirmado"]["con_adjunto_ics"] is True
    dev = por_key["recordatorio_devolucion_d1"]
    assert dev["mail_cliente"] is None and dev["whatsapp"] is not None


def test_incluye_estado_de_los_dos_canales(monkeypatch):
    _fake_deps(monkeypatch, _TODOS)
    canales = rc.listar_eventos(request=None)["canales"]
    assert "provider" in canales["mail"]
    assert "listo" in canales["whatsapp"]
