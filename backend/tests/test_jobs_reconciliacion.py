"""Tests del job de alerta proactiva de reconciliación de plata (#1184 Fase 2,
`jobs/reconciliacion.py`). El semáforo (`estado`) y el envío (`send_raw_email`)
se mockean — la lógica de los chequeos ya está testeada en
`test_reportes_liquidacion.py`/`test_contabilidad_db.py`; acá solo se ejerce el
contrato del job: cuándo manda mail, a quién, y que nunca propague.
"""
from __future__ import annotations

import pytest

import jobs.reconciliacion as job

pytestmark = pytest.mark.unit


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _ok_estado():
    return {"ok": True, "reporte": {"ok": True}, "contabilidad": {"ok": True}}


def _prod(monkeypatch):
    """Simula producción — ver test_analytics_config.py::_set_env, mismo patrón.
    El job está gateado a `settings.is_production`; sin esto, todos los tests
    de más abajo pasarían por el motivo equivocado (gate, no la lógica real)."""
    from config import settings

    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT", "production")


def _bad_estado():
    return {
        "ok": False,
        "reporte": {
            "ok": False,
            "pagados_sin_ledger": {"cantidad": 0, "ids": []},
            "monto_pagado_divergente": {"cantidad": 0, "ids": []},
            "sobrepagados": {"cantidad": 1, "ids": [42]},
            "mes_cerrado_desactualizado": {"cantidad": 0, "ids": [], "meses": []},
            "duenos_no_canonicos": [],
            "desglose_divergente": {"cantidad": 0, "ids": []},
        },
        "contabilidad": {
            "ok": True,
            "saldos_negativos": {"cantidad": 0, "cuentas": []},
            "pagos_sin_socio": {"cantidad": 0, "monto": 0},
            "movimientos_cuenta_inactiva": {"cantidad": 0},
        },
    }


class TestChequearYAlertar:
    def test_todo_ok_no_manda_mail(self, monkeypatch):
        _prod(monkeypatch)
        monkeypatch.setattr(job, "get_db", lambda: _FakeConn())
        monkeypatch.setattr(job, "_alertado_recientemente", lambda conn: False)
        monkeypatch.setattr(job, "estado", lambda conn: _ok_estado())
        sent = []
        monkeypatch.setattr(
            job, "send_raw_email", lambda **kw: (sent.append(kw), {"ok": True})[1]
        )
        assert job.chequear_reconciliacion_y_alertar() is False
        assert not sent

    def test_divergencia_manda_mail_a_cada_admin(self, monkeypatch):
        from config import settings

        _prod(monkeypatch)
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "a@test.com,b@test.com")
        monkeypatch.setattr(job, "get_db", lambda: _FakeConn())
        monkeypatch.setattr(job, "_alertado_recientemente", lambda conn: False)
        monkeypatch.setattr(job, "estado", lambda conn: _bad_estado())
        sent = []

        def fake_send(**kw):
            sent.append(kw)
            return {"ok": True}

        monkeypatch.setattr(job, "send_raw_email", fake_send)
        assert job.chequear_reconciliacion_y_alertar() is True
        assert {s["to"] for s in sent} == {"a@test.com", "b@test.com"}
        assert "Sobrepagados" in sent[0]["body_html"]

    def test_send_fallido_no_propaga_y_devuelve_false(self, monkeypatch):
        _prod(monkeypatch)
        monkeypatch.setattr(job, "get_db", lambda: _FakeConn())
        monkeypatch.setattr(job, "_alertado_recientemente", lambda conn: False)
        monkeypatch.setattr(job, "estado", lambda conn: _bad_estado())
        monkeypatch.setattr(
            job, "send_raw_email", lambda **kw: {"ok": False, "error": "smtp caído"}
        )
        assert job.chequear_reconciliacion_y_alertar() is False

    def test_ya_alertado_recientemente_no_recalcula_ni_manda(self, monkeypatch):
        """El dedup contra `emails_log` corta ANTES de llamar a `estado()` —
        no solo evita el mail, evita recalcular el semáforo entero."""
        _prod(monkeypatch)
        monkeypatch.setattr(job, "get_db", lambda: _FakeConn())
        monkeypatch.setattr(job, "_alertado_recientemente", lambda conn: True)
        estado_calls = []
        monkeypatch.setattr(
            job, "estado", lambda conn: (estado_calls.append(1), _bad_estado())[1]
        )
        sent = []
        monkeypatch.setattr(
            job, "send_raw_email", lambda **kw: (sent.append(kw), {"ok": True})[1]
        )
        assert job.chequear_reconciliacion_y_alertar() is False
        assert not sent
        assert not estado_calls

    def test_no_produccion_no_alerta_ni_toca_db(self, monkeypatch):
        """Gate de staging (#reporte-emails-dev): en `dev`/local no se manda ni
        se consulta el semáforo — corta ANTES de `get_db()`."""
        from config import settings

        monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT", "dev")
        get_db_calls = []
        monkeypatch.setattr(job, "get_db", lambda: (get_db_calls.append(1), _FakeConn())[1])
        sent = []
        monkeypatch.setattr(
            job, "send_raw_email", lambda **kw: (sent.append(kw), {"ok": True})[1]
        )
        assert job.chequear_reconciliacion_y_alertar() is False
        assert not sent
        assert not get_db_calls


class TestResumenHtml:
    def test_incluye_los_chequeos_con_cantidad_positiva(self):
        html = job._resumen_html(_bad_estado())
        assert "Sobrepagados" in html
        assert "1 pedido" in html

    def test_sin_items_positivos_no_rompe(self):
        html = job._resumen_html({"reporte": {}, "contabilidad": {}})
        assert "revisar el dashboard" in html
