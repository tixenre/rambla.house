"""Tests del job de recordatorios de retiro (`jobs/recordatorios.py`) y del
gating del scheduler in-process (`jobs/scheduler.py`).

La consulta SQL real (filtrar por estado/fecha/NOT EXISTS) se prueba a nivel
Postgres en otro lado; acá se aísla la lógica del job con un conn fake que
devuelve los pedidos candidatos, y se verifica el ruteo a `send_email`, el
conteo del resumen y el modo `dry_run`. El envío real (idempotencia vía índice
único) es responsabilidad de `services.email`, ya cubierto en su propio test.
"""

from datetime import datetime

import pytest

import jobs.recordatorios as rec
import jobs.recordatorios_config as cfg
import jobs.scheduler as sched

pytestmark = pytest.mark.unit


# ── Fakes ────────────────────────────────────────────────────────────────────

class FakeRow(dict):
    pass


class FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class FakeJobConn:
    """Conn que sirve el barrido de pedidos y deja vacíos los items."""

    def __init__(self, pedidos):
        self._pedidos = pedidos
        self.closed = False

    def execute(self, sql, params=()):
        s = " ".join(sql.split()).upper()
        if "FROM ALQUILERES A" in s and "NOT EXISTS" in s:
            return FakeCursor([FakeRow(**p) for p in self._pedidos])
        if "FROM ALQUILER_ITEMS" in s:
            return FakeCursor([])  # sin items → contexto con items vacíos
        return FakeCursor([])

    def close(self):
        self.closed = True


HOY = datetime(2026, 6, 4, 10, 0, 0)


def _pedido(**over):
    base = dict(
        id=1, numero_pedido=1001, cliente_nombre="Juana",
        cliente_email="juana@x.com", cliente_telefono="099",
        fecha_desde=datetime(2026, 6, 5, 10, 0), fecha_hasta=datetime(2026, 6, 6, 18, 0),
        monto_total=12500, notas="",
    )
    base.update(over)
    return base


@pytest.fixture
def capture_send(monkeypatch):
    """Reemplaza send_email por un stub que registra llamadas."""
    calls = []

    def fake_send(template_key, to, context, alquiler_id=None):
        calls.append((template_key, to, alquiler_id, context))
        return {"ok": True, "provider": "test", "log_id": len(calls)}

    monkeypatch.setattr(rec, "send_email", fake_send)
    return calls


class _CapturingConn:
    """Conn mínima que solo registra el SQL ejecutado — para el candado de abajo,
    no ejercita ninguna lógica de negocio."""

    def __init__(self):
        self.sql = None

    def execute(self, sql, params=()):
        self.sql = sql
        return FakeCursor([])


def test_pedidos_para_retiro_excluye_taller_y_estudio_fijo():
    """Candado: ninguno de los dos es un evento real de un día puntual (taller =
    mes contable completo; estudio_fijo = muestra de una recurrencia) — hoy además
    ninguno lleva `cliente_email`, así que el filtro de abajo ya los excluiría en
    la práctica, pero el filtro explícito no depende de esa coincidencia."""
    conn = _CapturingConn()
    rec._pedidos_para_retiro(conn, HOY, dias_antes=1)
    assert "a.tipo NOT IN ('taller', 'estudio_fijo')" in conn.sql


# ── Job: envío real ──────────────────────────────────────────────────────────

class TestEnviar:
    def test_manda_uno_por_pedido_y_cuenta(self, capture_send):
        conn = FakeJobConn([_pedido(id=1), _pedido(id=2, numero_pedido=1002,
                                                   cliente_email="b@x.com")])
        res = rec.enviar_recordatorios_retiro(conn, hoy=HOY)
        assert res["candidatos"] == 2
        assert res["enviados"] == 2
        assert res["fallidos"] == 0
        assert len(capture_send) == 2
        # Usa el template correcto y el id del pedido como alquiler_id.
        assert capture_send[0][0] == "recordatorio_retiro"
        assert capture_send[0][2] == 1

    def test_contexto_trae_variables_del_template(self, capture_send):
        conn = FakeJobConn([_pedido(numero_pedido=1234)])
        rec.enviar_recordatorios_retiro(conn, hoy=HOY)
        ctx = capture_send[0][3]
        assert ctx["numero_pedido"] == 1234
        assert ctx["cliente_nombre"] == "Juana"
        assert "portal_url" in ctx and "fecha_desde" in ctx

    def test_fecha_retiro_es_manana(self, capture_send):
        conn = FakeJobConn([])
        res = rec.enviar_recordatorios_retiro(conn, hoy=HOY)
        assert res["fecha_retiro"] == "2026-06-05"  # HOY + 1 (default)
        assert res["dias_antes"] == 1
        assert res["candidatos"] == 0
        assert capture_send == []

    def test_dias_antes_define_la_ventana_y_el_contexto(self, capture_send):
        conn = FakeJobConn([_pedido()])
        res = rec.enviar_recordatorios_retiro(conn, hoy=HOY, dias_antes=3)
        assert res["dias_antes"] == 3
        assert res["fecha_retiro"] == "2026-06-07"  # HOY (jun 4) + 3
        # el copy adaptable necesita dias_antes en el contexto del mail
        assert capture_send[0][3]["dias_antes"] == 3

    def test_send_fallido_se_contabiliza_sin_propagar(self, monkeypatch):
        monkeypatch.setattr(
            rec, "send_email",
            lambda *a, **k: {"ok": False, "error": "boom"},
        )
        conn = FakeJobConn([_pedido()])
        res = rec.enviar_recordatorios_retiro(conn, hoy=HOY)
        assert res["enviados"] == 0 and res["fallidos"] == 1
        assert res["pedidos"][0]["status"] == "failed"
        assert res["pedidos"][0]["error"] == "boom"

    def test_conn_propia_se_cierra(self, capture_send, monkeypatch):
        conn = FakeJobConn([_pedido()])
        monkeypatch.setattr(rec, "get_db", lambda: conn)
        rec.enviar_recordatorios_retiro(hoy=HOY)  # sin conn → la abre y cierra
        assert conn.closed is True

    def test_conn_ajena_no_se_cierra(self, capture_send):
        conn = FakeJobConn([_pedido()])
        rec.enviar_recordatorios_retiro(conn, hoy=HOY)
        assert conn.closed is False


# ── Job: dry_run ─────────────────────────────────────────────────────────────

class TestDryRun:
    def test_no_manda_nada(self, capture_send):
        conn = FakeJobConn([_pedido(id=1), _pedido(id=2)])
        res = rec.enviar_recordatorios_retiro(conn, hoy=HOY, dry_run=True)
        assert res["dry_run"] is True
        assert res["candidatos"] == 2
        assert res["enviados"] == 0 and res["fallidos"] == 0
        assert capture_send == []  # send_email jamás se llamó
        assert all(p["status"] == "dry_run" for p in res["pedidos"])


# ── Scheduler: arranque del thread (gating real es en runtime) ───────────────

class TestSchedulerArranque:
    """El thread arranca SIEMPRE salvo el kill-switch; el on/off real se decide
    en runtime dentro del loop vía resolve() (env > settings > default)."""

    def test_kill_switch_no_arranca(self, monkeypatch):
        monkeypatch.setenv("REMINDERS_SCHEDULER_DISABLED", "1")
        monkeypatch.setattr(sched.threading, "Thread",
                            lambda *a, **k: pytest.fail("no debía arrancar"))
        assert sched.start_scheduler() is False

    def test_arranca_sin_kill_switch(self, monkeypatch):
        monkeypatch.delenv("REMINDERS_SCHEDULER_DISABLED", raising=False)

        class FakeThread:
            def __init__(self, *a, **k):
                self.started = False

            def start(self):
                self.started = True

        monkeypatch.setattr(sched.threading, "Thread", FakeThread)
        assert sched.start_scheduler() is True


# ── Config del recordatorio: precedencia env > settings > default ─────────────

class FakeSettingsConn:
    """Conn que sirve valores de app_settings desde un dict key→value."""

    def __init__(self, settings=None):
        self._s = settings or {}
        self.closed = False

    def execute(self, sql, params=()):
        key = params[0] if params else None
        val = self._s.get(key)
        return FakeCursor([FakeRow(value=val)] if val is not None else [])

    def close(self):
        self.closed = True


class TestResolveConfig:
    def test_defaults_sin_env_ni_settings(self, monkeypatch):
        for v in ("REMINDERS_ENABLED", "REMINDERS_HOUR", "REMINDERS_DIAS_ANTES"):
            monkeypatch.delenv(v, raising=False)
        r = cfg.resolve(FakeSettingsConn())
        assert r == {"enabled": False, "hora": 9, "dias_antes": 1}

    def test_settings_mandan_si_no_hay_env(self, monkeypatch):
        for v in ("REMINDERS_ENABLED", "REMINDERS_HOUR", "REMINDERS_DIAS_ANTES"):
            monkeypatch.delenv(v, raising=False)
        conn = FakeSettingsConn({
            "recordatorios_enabled": "1",
            "recordatorios_hora": "7",
            "recordatorios_dias_antes": "2",
        })
        assert cfg.resolve(conn) == {"enabled": True, "hora": 7, "dias_antes": 2}

    def test_env_overridea_settings(self, monkeypatch):
        monkeypatch.setenv("REMINDERS_ENABLED", "0")  # env explícito apaga
        monkeypatch.setenv("REMINDERS_HOUR", "11")
        monkeypatch.delenv("REMINDERS_DIAS_ANTES", raising=False)
        conn = FakeSettingsConn({
            "recordatorios_enabled": "1",   # lo pisa el env "0"
            "recordatorios_hora": "7",      # lo pisa el env "11"
            "recordatorios_dias_antes": "5",
        })
        assert cfg.resolve(conn) == {"enabled": False, "hora": 11, "dias_antes": 5}

    def test_clamp_valores_fuera_de_rango(self, monkeypatch):
        for v in ("REMINDERS_ENABLED", "REMINDERS_HOUR", "REMINDERS_DIAS_ANTES"):
            monkeypatch.delenv(v, raising=False)
        conn = FakeSettingsConn({
            "recordatorios_hora": "99",        # → 23
            "recordatorios_dias_antes": "999", # → 14 (MAX)
        })
        r = cfg.resolve(conn)
        assert r["hora"] == 23 and r["dias_antes"] == 14

    def test_valores_basura_caen_al_default(self, monkeypatch):
        for v in ("REMINDERS_ENABLED", "REMINDERS_HOUR", "REMINDERS_DIAS_ANTES"):
            monkeypatch.delenv(v, raising=False)
        conn = FakeSettingsConn({
            "recordatorios_hora": "xx",
            "recordatorios_dias_antes": "",
        })
        r = cfg.resolve(conn)
        assert r["hora"] == 9 and r["dias_antes"] == 1
