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

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Sirve `email_templates` (dict key → (subject, enabled)) y `app_settings`
    (dict key → value), que es lo que el endpoint consulta."""

    def __init__(self, templates, settings=None):
        self._t = templates
        self._s = settings or {}

    def execute(self, sql, params=()):
        if "email_templates" in sql:
            return _FakeCursor(
                [{"key": k, "subject": v[0], "enabled": v[1]} for k, v in self._t.items()]
            )
        if "app_settings" in sql:
            pedidas = list(params)
            return _FakeCursor(
                [{"key": k, "value": v} for k, v in self._s.items() if k in pedidas]
            )
        raise AssertionError(f"query inesperada: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_deps(monkeypatch, templates, settings=None):
    monkeypatch.setattr(rc, "require_admin", lambda request: None)
    monkeypatch.setattr(rc, "get_db", lambda: _FakeConn(templates, settings))
    import services.email.service as es
    import services.whatsapp as wa

    monkeypatch.setattr(
        es, "channel_status", lambda: {"provider": "test", "activo": False, "from_addr": "x@y", "admin_to": "a@b"}
    )
    monkeypatch.setattr(
        wa, "diagnosticar", lambda conn: {"listo": False, "chequeos": [], "ambiente": "no_produccion"}
    )
    # Sin red: el estado de aprobación en Meta se simula (el endpoint lo pide para
    # mostrarlo adentro de cada evento).
    monkeypatch.setattr(
        wa, "estado_plantillas", lambda: {"disponible": False, "motivo": "sin credencial", "plantillas": []}
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


def test_confirmado_declara_ics(monkeypatch):
    _fake_deps(monkeypatch, _TODOS)
    por_key = {e["key"]: e for e in rc.listar_eventos(request=None)["eventos"]}
    assert por_key["pedido_confirmado"]["con_adjunto_ics"] is True


# ── por dónde sale: elegible desde la pantalla ───────────────────────────────
def test_evento_trae_como_cambiar_por_donde_sale(monkeypatch):
    _fake_deps(monkeypatch, _TODOS)
    ev = {e["key"]: e for e in rc.listar_eventos(request=None)["eventos"]}["pedido_creado"]
    assert ev["estrategia_setting"] == "comunicacion_estrategia_pedido_creado"
    assert ev["estrategia_default"] == "fallback"
    # Tiene los dos canales cableados → puede ser cualquiera de las cuatro formas.
    assert {o["valor"] for o in ev["estrategias_posibles"]} == set(ESTRATEGIAS)
    assert all(o["label"] and o["detalle"] for o in ev["estrategias_posibles"])


def test_la_elegida_por_el_dueno_pisa_al_default_del_registro(monkeypatch):
    _fake_deps(
        monkeypatch, _TODOS,
        settings={"comunicacion_estrategia_pedido_creado": "solo_mail"},
    )
    ev = {e["key"]: e for e in rc.listar_eventos(request=None)["eventos"]}["pedido_creado"]
    assert ev["estrategia"] == "solo_mail"          # lo que eligió el dueño
    assert ev["estrategia_default"] == "fallback"   # lo que declara el código
    assert ev["estrategia_label"] == ESTRATEGIA_LABEL["solo_mail"]


def test_un_valor_guardado_que_no_sirve_cae_al_default(monkeypatch):
    """Una fila vieja/corrupta no puede dejar un evento sin forma de salir."""
    _fake_deps(
        monkeypatch, _TODOS,
        settings={"comunicacion_estrategia_pedido_creado": "por_paloma_mensajera"},
    )
    ev = {e["key"]: e for e in rc.listar_eventos(request=None)["eventos"]}["pedido_creado"]
    assert ev["estrategia"] == "fallback"


def test_incluye_estado_de_los_dos_canales(monkeypatch):
    _fake_deps(monkeypatch, _TODOS)
    canales = rc.listar_eventos(request=None)["canales"]
    assert "provider" in canales["mail"]
    assert "listo" in canales["whatsapp"]
    # Para poder ofrecer "crear las que falten" desde la pantalla.
    assert canales["whatsapp"]["gestion_plantillas"]["disponible"] is False


# ── todo lo del evento, adentro del evento ───────────────────────────────────
def test_cada_evento_trae_sus_opciones_configurables(monkeypatch):
    """La config de un evento (horario/antelación/destinatarios) viaja DENTRO del
    evento — no en una pantalla aparte."""
    from services.comunicacion.opciones import OPCIONES

    _fake_deps(monkeypatch, _TODOS, settings={"recordatorios_dias_antes": "3"})
    por_key = {e["key"]: e for e in rc.listar_eventos(request=None)["eventos"]}

    for ev_key, ops in OPCIONES.items():
        assert {o["setting"] for o in por_key[ev_key]["opciones"]} == {o.setting for o in ops}

    retiro = {o["setting"]: o for o in por_key["recordatorio_retiro"]["opciones"]}
    assert retiro["recordatorios_dias_antes"]["valor"] == "3"  # el guardado
    assert retiro["recordatorios_enabled"]["valor"] == "0"     # sin fila → default
    assert retiro["recordatorios_hora"]["tipo"] == "numero"

    # Un evento sin perillas no inventa ninguna.
    assert por_key["pedido_confirmado"]["opciones"] == []


def test_opcion_pisada_por_env_se_devuelve_bloqueada(monkeypatch):
    """Si la env var manda, la UI no puede dejar editar la de la BD (guardaría un
    valor que el ambiente ignora)."""
    monkeypatch.setenv("REMINDERS_HOUR", "21")
    _fake_deps(monkeypatch, _TODOS, settings={"recordatorios_hora": "9"})
    por_key = {e["key"]: e for e in rc.listar_eventos(request=None)["eventos"]}
    hora = {o["setting"]: o for o in por_key["recordatorio_retiro"]["opciones"]}["recordatorios_hora"]
    assert hora["valor"] == "21" and hora["bloqueada_por_env"] == "REMINDERS_HOUR"


def test_evento_trae_su_plantilla_de_whatsapp_con_estado_en_meta(monkeypatch):
    _fake_deps(monkeypatch, _TODOS)
    por_key = {e["key"]: e for e in rc.listar_eventos(request=None)["eventos"]}
    wa = por_key["pedido_creado"]["whatsapp"]
    assert wa["meta_name"] and wa["parametros"] and "estado_meta" in wa
    # El aviso interno al equipo también es parte del evento.
    assert por_key["pedido_creado"]["whatsapp_admin"]["key"] == "pedido_creado_admin"


def test_los_mails_que_ningun_evento_dispara_se_listan_aparte(monkeypatch):
    """Ningún template queda sin lugar donde editarse: los de Talleres (que no
    pasan por el registro) van en `otros_mails`."""
    _fake_deps(monkeypatch, {**_TODOS, "taller_inscripcion_cliente": ("Inscripción", True)})
    out = rc.listar_eventos(request=None)
    assert [m["template"] for m in out["otros_mails"]] == ["taller_inscripcion_cliente"]
