"""Unit tests del adapter services/whatsapp (sin DB, sin red).

Cubre el registro de templates, el gating/credenciales y la orquestación de `envio`
(cada rama de skip + happy path) con conn y cliente falsos. La idempotencia real a
nivel DB (índice único parcial) queda cubierta por la aplicación de la migración en
`test_alembic_upgrade_db.py`.
"""
from __future__ import annotations

import re

from config import settings
from services.whatsapp import plantillas as plmod
from services.whatsapp import config as cfg
from services.whatsapp import envio as env
from services.whatsapp import estado as est


# ── plantillas ──────────────────────────────────────────────────────────
def test_registro_tiene_los_eventos_esperados():
    assert set(plmod.REGISTRO) == {
        "pedido_creado",
        "pedido_creado_admin",  # aviso interno al equipo (Pablo/Tincho)
        "pedido_confirmado",
        "recordatorio_retiro",
        "recordatorio_devolucion_d1",
        "recordatorio_devolucion_d0",
        "recordatorio_devolucion_vencido",
    }


def test_params_mapea_en_orden_y_faltante_es_vacio():
    p = plmod.REGISTRO["pedido_confirmado"]
    ctx = {"cliente_nombre": "Ana", "numero_pedido": 42}  # falta fecha_desde
    assert p.params(ctx) == ["Ana", "42", ""]


def test_copy_ejemplo_tiene_tantos_placeholders_como_campos():
    """Cada {{n}} del copy sugerido para Meta se corresponde con un campo del ctx."""
    for p in plmod.REGISTRO.values():
        placeholders = {int(n) for n in re.findall(r"\{\{(\d+)\}\}", p.copy_ejemplo)}
        assert placeholders == set(range(1, len(p.campos_ctx) + 1)), (
            f"{p.key}: placeholders {placeholders} vs {len(p.campos_ctx)} campos"
        )


def test_copy_ejemplo_placeholders_en_orden_ascendente():
    """Meta RECHAZA un template cuyos {{n}} no aparezcan en orden ascendente en el
    cuerpo. El copy sugerido es lo que el dueño copia-pega en el WhatsApp Manager, así
    que tiene que salir aprobado tal cual: {{1}} antes que {{2}}, {{2}} antes que {{3}}.
    (Cazado en la práctica: `recordatorio_devolucion_d1`/`_d0` decían el número de
    pedido DESPUÉS de la fecha → aparecían como 1,3,2 y Meta los habría rechazado.)"""
    for p in plmod.REGISTRO.values():
        orden = [int(n) for n in re.findall(r"\{\{(\d+)\}\}", p.copy_ejemplo)]
        assert orden == sorted(orden), (
            f"{p.key}: los placeholders aparecen {orden}; Meta exige orden ascendente"
        )


def test_key_igual_a_meta_name_y_template_key():
    for k, p in plmod.REGISTRO.items():
        assert p.key == k
        assert p.meta_name  # no vacío


# ── config: credenciales + gating ───────────────────────────────────────
def test_resolver_creds_none_si_falta_token(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "123", raising=False)
    assert cfg.resolver_creds() is None


def test_resolver_creds_ok(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "TOK", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "PNID", raising=False)
    creds = cfg.resolver_creds()
    assert creds is not None
    assert creds.access_token == "TOK"
    assert creds.phone_number_id == "PNID"
    assert creds.base_url == cfg.GRAPH_BASE


def test_destinatario_permitido_prod_vs_allowlist(monkeypatch):
    # No-producción: solo la allowlist.
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT", "dev", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_TEST_RECIPIENTS", "+5492235550000, +5491100000000", raising=False)
    assert cfg.destinatario_permitido("+5492235550000") is True
    assert cfg.destinatario_permitido("+5490000000000") is False
    # Producción: cualquiera.
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT", "production", raising=False)
    assert cfg.destinatario_permitido("+5490000000000") is True


def test_canal_habilitado_env_override(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENABLED", "1")
    assert cfg.canal_habilitado(_FakeConn()) is True
    monkeypatch.setenv("WHATSAPP_ENABLED", "0")
    assert cfg.canal_habilitado(_FakeConn()) is False


def test_canal_habilitado_desde_settings(monkeypatch):
    monkeypatch.delenv("WHATSAPP_ENABLED", raising=False)
    assert cfg.canal_habilitado(_FakeConn(whatsapp_enabled="1")) is True
    assert cfg.canal_habilitado(_FakeConn(whatsapp_enabled="")) is False


# ── estado ──────────────────────────────────────────────────────────────
def test_diagnosticar_no_listo_sin_credenciales(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "", raising=False)
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT", "dev", raising=False)
    d = est.diagnosticar(_FakeConn(whatsapp_enabled=""))
    assert d["listo"] is False
    checks = {c["check"]: c["ok"] for c in d["chequeos"]}
    assert checks["token_cargado"] is False
    assert checks["phone_number_id"] is False


def test_diagnosticar_listo_con_todo(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "TOK", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "PNID", raising=False)
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT", "production", raising=False)
    monkeypatch.delenv("WHATSAPP_ENABLED", raising=False)
    d = est.diagnosticar(_FakeConn(whatsapp_enabled="1"))
    assert d["listo"] is True


# ── envio: orquestación + skips ─────────────────────────────────────────
def test_envio_plantilla_desconocida():
    r = env.enviar_evento_pedido("no_existe", {"id": 1, "cliente_id": 1}, {})
    assert r["skipped"] and r["reason"] == "plantilla_desconocida"


def test_envio_sin_credenciales(monkeypatch):
    monkeypatch.setattr(env, "resolver_creds", lambda: None)
    r = env.enviar_evento_pedido("pedido_creado", {"id": 1, "cliente_id": 1}, {})
    assert r["ok"] and r["skipped"] and r["reason"] == "sin_credenciales"


def _con_creds(monkeypatch):
    monkeypatch.setattr(env, "resolver_creds", lambda: cfg.WhatsAppCreds("PNID", "TOK"))


def test_envio_canal_apagado(monkeypatch):
    _con_creds(monkeypatch)
    monkeypatch.setattr(env, "get_db", lambda: _FakeConn())
    monkeypatch.setattr(env, "canal_habilitado", lambda conn: False)
    r = env.enviar_evento_pedido("pedido_creado", {"id": 1, "cliente_id": 1}, {})
    assert r["skipped"] and r["reason"] == "canal_apagado"


def test_envio_sin_opt_in(monkeypatch):
    _con_creds(monkeypatch)
    monkeypatch.setattr(env, "get_db", lambda: _FakeConn(opt_in=False))
    monkeypatch.setattr(env, "canal_habilitado", lambda conn: True)
    r = env.enviar_evento_pedido("pedido_creado", {"id": 1, "cliente_id": 5}, {})
    assert r["skipped"] and r["reason"] == "sin_opt_in"


def test_envio_sin_telefono_e164(monkeypatch):
    _con_creds(monkeypatch)
    monkeypatch.setattr(env, "get_db", lambda: _FakeConn(opt_in=True))
    monkeypatch.setattr(env, "canal_habilitado", lambda conn: True)
    monkeypatch.setattr(env, "_resolver_telefono", lambda conn, pedido: None)
    r = env.enviar_evento_pedido("pedido_creado", {"id": 1, "cliente_id": 5}, {})
    assert r["skipped"] and r["reason"] == "sin_telefono_e164"


def test_envio_destinatario_no_permitido(monkeypatch):
    _con_creds(monkeypatch)
    monkeypatch.setattr(env, "get_db", lambda: _FakeConn(opt_in=True))
    monkeypatch.setattr(env, "canal_habilitado", lambda conn: True)
    monkeypatch.setattr(env, "_resolver_telefono", lambda conn, pedido: "+5490000000000")
    monkeypatch.setattr(env, "destinatario_permitido", lambda to: False)
    r = env.enviar_evento_pedido("pedido_creado", {"id": 1, "cliente_id": 5}, {})
    assert r["skipped"] and r["reason"] == "destinatario_no_permitido"


def test_envio_duplicado(monkeypatch):
    _con_creds(monkeypatch)
    monkeypatch.setattr(env, "get_db", lambda: _FakeConn(opt_in=True, existing_log={"id": 7}))
    monkeypatch.setattr(env, "canal_habilitado", lambda conn: True)
    monkeypatch.setattr(env, "_resolver_telefono", lambda conn, pedido: "+5492235550000")
    monkeypatch.setattr(env, "destinatario_permitido", lambda to: True)
    r = env.enviar_evento_pedido("pedido_creado", {"id": 1, "cliente_id": 5}, {})
    assert r["skipped"] and r["reason"] == "duplicado" and r["log_id"] == 7


def test_envio_happy_path(monkeypatch):
    import whatsapp_cloud

    _con_creds(monkeypatch)
    fake_conn = _FakeConn(opt_in=True, existing_log=None)
    monkeypatch.setattr(env, "get_db", lambda: fake_conn)
    monkeypatch.setattr(env, "canal_habilitado", lambda conn: True)
    monkeypatch.setattr(env, "_resolver_telefono", lambda conn, pedido: "+5492235550000")
    monkeypatch.setattr(env, "destinatario_permitido", lambda to: True)

    class _FakeClient:
        def __init__(self, **kw):
            pass

        def enviar_template(self, **kw):
            return whatsapp_cloud.EnvioResult(message_id="wamid.OK", to=kw["to"], template_name=kw["template_name"])

    monkeypatch.setattr(whatsapp_cloud, "WhatsAppClient", _FakeClient)

    ctx = {"cliente_nombre": "Ana", "numero_pedido": "42"}
    r = env.enviar_evento_pedido("pedido_creado", {"id": 9, "cliente_id": 5}, ctx)
    assert r["ok"] and r["wamid"] == "wamid.OK"
    assert fake_conn.committed
    # params: (to, template_key, alquiler_id, status, wamid, error) → status = idx 3
    assert fake_conn.inserted and fake_conn.inserted[0][1][3] == "sent"


def test_envio_falla_provider_se_loguea_failed(monkeypatch):
    import whatsapp_cloud

    _con_creds(monkeypatch)
    fake_conn = _FakeConn(opt_in=True, existing_log=None)
    monkeypatch.setattr(env, "get_db", lambda: fake_conn)
    monkeypatch.setattr(env, "canal_habilitado", lambda conn: True)
    monkeypatch.setattr(env, "_resolver_telefono", lambda conn, pedido: "+5492235550000")
    monkeypatch.setattr(env, "destinatario_permitido", lambda to: True)

    class _BoomClient:
        def __init__(self, **kw):
            pass

        def enviar_template(self, **kw):
            raise whatsapp_cloud.WhatsAppRequestError("número inválido", errores=((131030, "x"),))

    monkeypatch.setattr(whatsapp_cloud, "WhatsAppClient", _BoomClient)
    r = env.enviar_evento_pedido("pedido_creado", {"id": 9, "cliente_id": 5}, {"cliente_nombre": "A", "numero_pedido": "1"})
    assert r["ok"] is False and "inválido" in r["error"]
    assert fake_conn.inserted[0][1][3] == "failed"


# ── helpers de teléfono ─────────────────────────────────────────────────
def test_resolver_telefono_pasa_por_el_embudo():
    # El embudo (services/telefono) valida + normaliza: inválido → None, local
    # válido → E.164, E.164 → se mantiene.
    assert env._resolver_telefono(_FakeConn(), {"cliente_telefono": "222-nuevo"}) is None
    assert env._resolver_telefono(_FakeConn(), {"cliente_telefono": "223 555-0100"}) == "+542235550100"
    assert env._resolver_telefono(_FakeConn(), {"cliente_telefono": "+54 9 223 555 0100"}) == "+5492235550100"


# ── fake conn mínima ────────────────────────────────────────────────────
class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, *, opt_in=True, existing_log=None, whatsapp_enabled="1"):
        self.opt_in = opt_in
        self.existing_log = existing_log
        self.whatsapp_enabled = whatsapp_enabled
        self.inserted = []
        self.committed = False

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if "whatsapp_opt_in FROM clientes" in s:
            return _FakeCursor({"whatsapp_opt_in": self.opt_in})
        if "FROM whatsapp_log" in s:
            return _FakeCursor(self.existing_log)
        if "app_settings" in s:
            return _FakeCursor({"value": self.whatsapp_enabled} if self.whatsapp_enabled else None)
        return _FakeCursor(None)

    def insert_returning(self, sql, params=(), *, column="id"):
        self.inserted.append((sql, params))
        return 99

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass
