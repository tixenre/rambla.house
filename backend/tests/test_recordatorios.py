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
    """Reemplaza el despacho (`notificar_pedido`) por un stub que registra llamadas.
    El job ahora despacha por la capa única de comunicación (mail + WhatsApp); acá se
    intercepta ahí y se devuelve un resultado de canal mail OK."""
    calls = []

    def fake_notificar(evento_key, pedido, ctx, **k):
        calls.append((evento_key, pedido.get("cliente_email"), pedido.get("id"), ctx))
        return {"mail": [{"ok": True, "provider": "test", "log_id": len(calls)}], "whatsapp": {"ok": True}}

    monkeypatch.setattr(rec, "notificar_pedido", fake_notificar)
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
    desde, hasta = rec._ventana(HOY, rec.PASADA_VISPERA, 12)
    rec._pedidos_para_retiro(conn, desde, hasta)
    assert "a.tipo NOT IN ('taller', 'estudio_fijo')" in conn.sql


# ── Job: envío real ──────────────────────────────────────────────────────────

class TestEnviar:
    def test_manda_uno_por_pedido_y_cuenta(self, capture_send):
        conn = FakeJobConn([_pedido(id=1), _pedido(id=2, numero_pedido=1002,
                                                   cliente_email="b@x.com")])
        res = rec.enviar_recordatorios_retiro(conn, hoy=HOY, corte_manana=12)
        assert res["candidatos"] == 2
        assert res["enviados"] == 2
        assert res["fallidos"] == 0
        assert len(capture_send) == 2
        # Usa el template correcto y el id del pedido como alquiler_id.
        assert capture_send[0][0] == "recordatorio_retiro"
        assert capture_send[0][2] == 1

    def test_contexto_trae_variables_del_template(self, capture_send):
        conn = FakeJobConn([_pedido(numero_pedido=1234)])
        rec.enviar_recordatorios_retiro(conn, hoy=HOY, corte_manana=12)
        ctx = capture_send[0][3]
        assert ctx["numero_pedido"] == 1234
        assert ctx["cliente_nombre"] == "Juana"
        assert "portal_url" in ctx and "fecha_desde" in ctx

    def test_pasada_de_la_manana_mira_lo_que_queda_de_hoy(self, capture_send):
        """Los retiros de HOY que todavía no ocurrieron (incluye el rescate de un
        temprano que no recibió el aviso de anoche)."""
        conn = FakeJobConn([_pedido()])
        res = rec.enviar_recordatorios_retiro(
            conn, hoy=HOY, pasada=rec.PASADA_MANANA, corte_manana=12
        )
        assert res["pasada"] == "manana"
        assert res["desde"] == HOY.isoformat()               # desde AHORA
        assert res["hasta"] == "2026-06-05T00:00:00"         # hasta el fin de hoy
        assert capture_send[0][3]["dias_antes"] == 0         # el copy dice "hoy"

    def test_pasada_de_la_vispera_mira_los_de_manana_temprano(self, capture_send):
        conn = FakeJobConn([_pedido()])
        res = rec.enviar_recordatorios_retiro(
            conn, hoy=HOY, pasada=rec.PASADA_VISPERA, corte_manana=12
        )
        assert res["pasada"] == "vispera"
        assert res["desde"] == "2026-06-05T00:00:00"         # mañana 00:00
        assert res["hasta"] == "2026-06-05T12:00:00"         # …hasta el corte
        assert capture_send[0][3]["dias_antes"] == 1         # el copy dice "mañana"

    def test_el_corte_mueve_la_ventana_de_la_vispera(self):
        """Subir el corte hace que más retiros cuenten como "de mañana"."""
        _, hasta = rec._ventana(HOY, rec.PASADA_VISPERA, 15)
        assert hasta.isoformat() == "2026-06-05T15:00:00"

    def test_send_fallido_se_contabiliza_sin_propagar(self, monkeypatch):
        monkeypatch.setattr(
            rec, "notificar_pedido",
            lambda *a, **k: {"mail": [{"ok": False, "error": "boom"}], "whatsapp": None},
        )
        conn = FakeJobConn([_pedido()])
        res = rec.enviar_recordatorios_retiro(conn, hoy=HOY, corte_manana=12)
        assert res["enviados"] == 0 and res["fallidos"] == 1
        assert res["pedidos"][0]["status"] == "failed"
        assert res["pedidos"][0]["error"] == "boom"

    def test_conn_propia_se_cierra(self, capture_send, monkeypatch):
        conn = FakeJobConn([_pedido()])
        monkeypatch.setattr(rec, "get_db", lambda: conn)
        rec.enviar_recordatorios_retiro(hoy=HOY, corte_manana=12)  # sin conn → la abre y cierra
        assert conn.closed is True

    def test_conn_ajena_no_se_cierra(self, capture_send):
        conn = FakeJobConn([_pedido()])
        rec.enviar_recordatorios_retiro(conn, hoy=HOY, corte_manana=12)
        assert conn.closed is False

    def test_excluye_items_de_turno_embebido_del_listado_a_traer(self, capture_send, monkeypatch):
        """Hallazgo de auditoría (#1308 rediseño "turno como ítem"): el centinela/
        sueltos de un turno del Estudio EMBEBIDO se usan ENTERO adentro del
        Estudio — no hay nada que "traer" para ese retiro — así que no deben
        aparecer en `items_text`/`items_html` del recordatorio, a diferencia del
        equipo normal del mismo pedido."""
        monkeypatch.setattr(
            rec, "_get_alquiler_items",
            lambda conn, pedido_id: [
                {"nombre": "Cámara normal", "cantidad": 1, "turno_estudio_id": None},
                {"nombre": "Estudio (espacio)", "cantidad": 1, "turno_estudio_id": 501},
            ],
        )
        conn = FakeJobConn([_pedido()])
        rec.enviar_recordatorios_retiro(conn, hoy=HOY, corte_manana=12)
        ctx = capture_send[0][3]
        assert "Cámara normal" in ctx["items_text"]
        assert "Estudio (espacio)" not in ctx["items_text"]


# ── Job: dry_run ─────────────────────────────────────────────────────────────

class TestDryRun:
    def test_no_manda_nada(self, capture_send):
        conn = FakeJobConn([_pedido(id=1), _pedido(id=2)])
        res = rec.enviar_recordatorios_retiro(conn, hoy=HOY, corte_manana=12, dry_run=True)
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
    """`hora_vispera` sale de `horarios_retiro` (fuente única de los horarios):
    el FakeSettingsConn de abajo no lo sirve → cae al default (18)."""

    def _sin_env(self, monkeypatch):
        for v in ("REMINDERS_ENABLED", "REMINDERS_HOUR", "REMINDERS_CORTE_MANANA"):
            monkeypatch.delenv(v, raising=False)

    def test_defaults_sin_env_ni_settings(self, monkeypatch):
        self._sin_env(monkeypatch)
        r = cfg.resolve(FakeSettingsConn())
        assert r == {"enabled": False, "hora": 9, "corte_manana": 12, "hora_vispera": 18}

    def test_settings_mandan_si_no_hay_env(self, monkeypatch):
        self._sin_env(monkeypatch)
        conn = FakeSettingsConn({
            "recordatorios_enabled": "1",
            "recordatorios_hora": "7",
            "recordatorios_corte_manana": "14",
        })
        assert cfg.resolve(conn) == {
            "enabled": True, "hora": 7, "corte_manana": 14, "hora_vispera": 18
        }

    def test_env_overridea_settings(self, monkeypatch):
        monkeypatch.setenv("REMINDERS_ENABLED", "0")  # env explícito apaga
        monkeypatch.setenv("REMINDERS_HOUR", "11")
        monkeypatch.delenv("REMINDERS_CORTE_MANANA", raising=False)
        conn = FakeSettingsConn({
            "recordatorios_enabled": "1",         # lo pisa el env "0"
            "recordatorios_hora": "7",            # lo pisa el env "11"
            "recordatorios_corte_manana": "10",
        })
        assert cfg.resolve(conn) == {
            "enabled": False, "hora": 11, "corte_manana": 10, "hora_vispera": 18
        }

    def test_clamp_valores_fuera_de_rango(self, monkeypatch):
        self._sin_env(monkeypatch)
        conn = FakeSettingsConn({
            "recordatorios_hora": "99",           # → 23
            "recordatorios_corte_manana": "99",   # → 23
        })
        r = cfg.resolve(conn)
        assert r["hora"] == 23 and r["corte_manana"] == 23

    def test_valores_basura_caen_al_default(self, monkeypatch):
        self._sin_env(monkeypatch)
        conn = FakeSettingsConn({
            "recordatorios_hora": "xx",
            "recordatorios_corte_manana": "",
        })
        r = cfg.resolve(conn)
        assert r["hora"] == 9 and r["corte_manana"] == 12

    def test_hora_vispera_sale_de_los_horarios_de_retiro(self, monkeypatch):
        """Si el galpón cierra 17:30, el aviso de la víspera sale a las 17."""
        self._sin_env(monkeypatch)
        conn = FakeSettingsConn({
            "horarios_retiro": '{"lun": {"desde": "09:00", "hasta": "17:30"}}',
        })
        from datetime import date

        assert cfg.resolve(conn, dia=date(2026, 6, 1))["hora_vispera"] == 17   # lunes
        assert cfg.resolve(conn, dia=date(2026, 6, 2))["hora_vispera"] == 18   # martes: sin config
