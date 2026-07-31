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
    """Devuelve la lista de pedidos para el SELECT del barrido.

    Las consultas a `app_settings` (la config de ventanas/antelación, que el job
    resuelve solo si no se le pasa) devuelven vacío → el job cae a los defaults.
    Antes este fake contestaba pedidos a CUALQUIER query, incluida la de settings."""

    def __init__(self, pedidos):
        self.pedidos = pedidos

    def execute(self, sql, params=()):
        if "app_settings" in sql:
            return _FakeCur([])
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


# ── antelación configurable de la víspera (pedido del dueño) ──────────────
def test_dias_antes_mueve_solo_la_ventana_vispera(monkeypatch):
    """`dias_antes=3` busca devoluciones de 3 días adelante en la víspera; D-0 y
    'vencido' NO se mueven (son puntos fijos, no antelación)."""
    import jobs.recordatorios_devolucion as jd

    vistos: list[tuple[str, int]] = []

    def fake_pedidos(conn, hoy, offset_dias, template_key):
        vistos.append((template_key, offset_dias))
        return []

    monkeypatch.setattr(jd, "_pedidos_para_devolucion", fake_pedidos)
    jd.enviar_recordatorios_devolucion(conn=_FakeConnPedidos([]), hoy=_hoy(), dias_antes=3)

    por_tpl = dict(vistos)
    assert por_tpl["recordatorio_devolucion_d1"] == 3      # la víspera se corrió
    assert por_tpl["recordatorio_devolucion_d0"] == 0      # fijo
    assert por_tpl["recordatorio_devolucion_vencido"] == -1  # fijo


def test_dias_antes_sale_de_la_config_si_no_se_pasa(monkeypatch):
    import jobs.recordatorios_devolucion as jd
    import jobs.recordatorios_devolucion_config as cfg

    monkeypatch.setattr(cfg, "resolve", lambda conn=None: {"dias_antes": 5})
    monkeypatch.setattr(jd, "_pedidos_para_devolucion", lambda *a, **k: [])
    out = jd.enviar_recordatorios_devolucion(conn=_FakeConnPedidos([]), hoy=_hoy())
    assert out["dias_antes"] == 5


def test_config_clampea_la_antelacion():
    """Fuera de rango o basura → default, sin romper el barrido."""
    from jobs.recordatorios_devolucion_config import _clamp_int, DEFAULT_DIAS_ANTES

    assert _clamp_int("999", DEFAULT_DIAS_ANTES, 1, 14) == 14
    assert _clamp_int("0", DEFAULT_DIAS_ANTES, 1, 14) == 1
    assert _clamp_int("xx", DEFAULT_DIAS_ANTES, 1, 14) == DEFAULT_DIAS_ANTES
