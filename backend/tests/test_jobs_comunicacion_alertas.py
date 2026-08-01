"""Tests del job de alerta proactiva de fallas de comunicación
(`jobs/comunicacion_alertas.py`). Mirror de `test_jobs_reconciliacion.py`:
`_fallos_ultimas_24h` y `send_raw_email` se mockean — solo se ejerce el
contrato del job (cuándo manda mail, a quién, y que nunca propague).
"""
from __future__ import annotations

import pytest

import jobs.comunicacion_alertas as job

pytestmark = pytest.mark.unit


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _pocos_fallos():
    return {"mail": [{"template_key": "x", "to_addr": "a@test.com", "error": "boom"}], "whatsapp": []}


def _muchos_fallos():
    return {
        "mail": [
            {"template_key": "pedido_creado_cliente", "to_addr": "a@test.com", "error": "smtp caído"},
            {"template_key": "pedido_confirmado_cliente", "to_addr": "b@test.com", "error": "smtp caído"},
        ],
        "whatsapp": [
            {"template_key": "pedido_creado", "to_phone": "+549", "error": "token vencido"},
        ],
    }


class TestChequearYAlertar:
    def test_pocos_fallos_no_manda_mail(self, monkeypatch):
        monkeypatch.setattr(job, "get_db", lambda: _FakeConn())
        monkeypatch.setattr(job, "_alertado_recientemente", lambda conn: False)
        monkeypatch.setattr(job, "_fallos_ultimas_24h", lambda conn: _pocos_fallos())
        sent = []
        monkeypatch.setattr(job, "send_raw_email", lambda **kw: (sent.append(kw), {"ok": True})[1])
        assert job.chequear_fallas_y_alertar() is False
        assert not sent

    def test_fallos_por_encima_del_umbral_manda_mail_a_cada_admin(self, monkeypatch):
        from config import settings

        monkeypatch.setattr(settings, "ADMIN_EMAILS", "a@test.com,b@test.com")
        monkeypatch.setattr(job, "get_db", lambda: _FakeConn())
        monkeypatch.setattr(job, "_alertado_recientemente", lambda conn: False)
        monkeypatch.setattr(job, "_fallos_ultimas_24h", lambda conn: _muchos_fallos())
        sent = []

        def fake_send(**kw):
            sent.append(kw)
            return {"ok": True}

        monkeypatch.setattr(job, "send_raw_email", fake_send)
        assert job.chequear_fallas_y_alertar() is True
        assert {s["to"] for s in sent} == {"a@test.com", "b@test.com"}
        assert "token vencido" in sent[0]["body_html"]
        assert sent[0]["log_key"] == "comunicacion_alerta"

    def test_send_fallido_no_propaga_y_devuelve_false(self, monkeypatch):
        monkeypatch.setattr(job, "get_db", lambda: _FakeConn())
        monkeypatch.setattr(job, "_alertado_recientemente", lambda conn: False)
        monkeypatch.setattr(job, "_fallos_ultimas_24h", lambda conn: _muchos_fallos())
        monkeypatch.setattr(job, "send_raw_email", lambda **kw: {"ok": False, "error": "smtp caído"})
        assert job.chequear_fallas_y_alertar() is False

    def test_ya_alertado_recientemente_no_recalcula_ni_manda(self, monkeypatch):
        monkeypatch.setattr(job, "get_db", lambda: _FakeConn())
        monkeypatch.setattr(job, "_alertado_recientemente", lambda conn: True)
        calls = []
        monkeypatch.setattr(
            job, "_fallos_ultimas_24h", lambda conn: (calls.append(1), _muchos_fallos())[1]
        )
        sent = []
        monkeypatch.setattr(job, "send_raw_email", lambda **kw: (sent.append(kw), {"ok": True})[1])
        assert job.chequear_fallas_y_alertar() is False
        assert not sent
        assert not calls


class TestResumenHtml:
    def test_incluye_el_detalle_de_cada_fallo(self):
        html = job._resumen_html(_muchos_fallos(), total=3)
        assert "smtp caído" in html
        assert "token vencido" in html
        assert "3" in html

    def test_sin_detalle_no_rompe(self):
        html = job._resumen_html({"mail": [], "whatsapp": []}, total=0)
        assert "sin detalle disponible" in html
