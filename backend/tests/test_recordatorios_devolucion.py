"""Tests del recordatorio de devolución: config (3 ventanas) + job (sin DB/red)."""
from __future__ import annotations

from datetime import datetime

import jobs.recordatorios_devolucion as jd
from jobs import recordatorios_devolucion_config as cfgmod


# ── fake conn ───────────────────────────────────────────────────────────
class _FakeCur:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConnPedidos:
    """Devuelve la misma lista de pedidos para cualquier SELECT del barrido."""

    def __init__(self, pedidos):
        self.pedidos = pedidos

    def execute(self, sql, params=()):
        return _FakeCur(self.pedidos)

    def close(self):
        pass


class _FakeConnSettings:
    """Devuelve valores de app_settings desde un dict {key: value}."""

    def __init__(self, valores):
        self.valores = valores

    def execute(self, sql, params=()):
        key = params[0] if params else None
        val = self.valores.get(key)
        return _FakeCur([{"value": val}] if val is not None else [])

    def close(self):
        pass


# ── config ──────────────────────────────────────────────────────────────
def test_config_default_todo_apagado(monkeypatch):
    for env, _ in cfgmod.VENTANAS.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.delenv("REMINDERS_DEVOLUCION_HOUR", raising=False)
    cfg = cfgmod.resolve(_FakeConnSettings({}))
    assert cfg["ventanas"] == set()
    assert cfg["alguna"] is False
    assert cfg["hora"] == cfgmod.DEFAULT_HORA


def test_config_env_override_por_ventana(monkeypatch):
    monkeypatch.setenv("REMINDERS_DEVOLUCION_D1", "1")
    monkeypatch.setenv("REMINDERS_DEVOLUCION_D0", "0")
    monkeypatch.delenv("REMINDERS_DEVOLUCION_VENCIDO", raising=False)
    cfg = cfgmod.resolve(_FakeConnSettings({"recordatorios_devolucion_vencido_enabled": "1"}))
    assert cfg["ventanas"] == {"d1", "vencido"}  # d1 por env, vencido por setting, d0 apagado
    assert cfg["alguna"] is True


def test_config_hora_clamp(monkeypatch):
    monkeypatch.delenv("REMINDERS_DEVOLUCION_HOUR", raising=False)
    cfg = cfgmod.resolve(_FakeConnSettings({"recordatorios_devolucion_hora": "99"}))
    assert cfg["hora"] == 23  # clamp a [0,23]


# ── job ─────────────────────────────────────────────────────────────────
def _hoy():
    return datetime(2026, 7, 11, 10, 0, 0)


def test_job_solo_corre_ventanas_activas(monkeypatch):
    monkeypatch.setattr(jd, "pedido_email_context", lambda p: {})
    sent = []
    monkeypatch.setattr(jd, "notificar_pedido", lambda tpl, p, ctx: sent.append((tpl, p["id"])) or {"whatsapp": {"ok": True}})
    conn = _FakeConnPedidos([{"id": 1, "cliente_id": 2, "numero_pedido": "A"}])

    r = jd.enviar_recordatorios_devolucion(conn=conn, hoy=_hoy(), ventanas={"d0"})
    assert set(r["ventanas"]) == {"d0"}  # las otras dos no corren
    assert r["ventanas"]["d0"]["enviados"] == 1
    assert sent == [("recordatorio_devolucion_d0", 1)]


def test_job_usa_template_correcto_por_ventana(monkeypatch):
    monkeypatch.setattr(jd, "pedido_email_context", lambda p: {})
    sent = []
    monkeypatch.setattr(jd, "notificar_pedido", lambda tpl, p, ctx: sent.append(tpl) or {"whatsapp": {"ok": True}})
    conn = _FakeConnPedidos([{"id": 1, "cliente_id": 2, "numero_pedido": "A"}])

    jd.enviar_recordatorios_devolucion(conn=conn, hoy=_hoy(), ventanas={"d1", "d0", "vencido"})
    assert set(sent) == {
        "recordatorio_devolucion_d1",
        "recordatorio_devolucion_d0",
        "recordatorio_devolucion_vencido",
    }


def test_job_dry_run_no_envia(monkeypatch):
    monkeypatch.setattr(jd, "pedido_email_context", lambda p: {})
    sent = []
    monkeypatch.setattr(jd, "notificar_pedido", lambda *a: sent.append(a) or {"whatsapp": {"ok": True}})
    conn = _FakeConnPedidos([{"id": 1, "cliente_id": 2, "numero_pedido": "A"}])

    r = jd.enviar_recordatorios_devolucion(conn=conn, hoy=_hoy(), ventanas={"d0"}, dry_run=True)
    assert sent == []
    assert r["ventanas"]["d0"]["pedidos"][0]["status"] == "dry_run"


def test_job_cuenta_skipped(monkeypatch):
    monkeypatch.setattr(jd, "pedido_email_context", lambda p: {})
    monkeypatch.setattr(jd, "notificar_pedido", lambda *a: {"whatsapp": {"ok": True, "skipped": True, "reason": "sin_opt_in"}})
    conn = _FakeConnPedidos([{"id": 1, "cliente_id": 2, "numero_pedido": "A"}])

    r = jd.enviar_recordatorios_devolucion(conn=conn, hoy=_hoy(), ventanas={"d0"})
    assert r["ventanas"]["d0"]["saltados"] == 1
    assert r["ventanas"]["d0"]["enviados"] == 0
