"""Tests de la capa única de comunicación (registro + despachador plan A/B). Sin DB/red.

Modelo (2026-07-12): WhatsApp es plan A, el mail plan B. Cada evento declara su
`estrategia` (fallback / ambos / solo_mail / solo_whatsapp); el mail al admin sale
SIEMPRE, fuera del plan A/B del cliente.
"""
from __future__ import annotations

import services.comunicacion.despacho as d
import services.whatsapp as wa
from services.comunicacion.eventos import (
    AMBOS,
    ESTRATEGIAS,
    FALLBACK,
    REGISTRO,
    SOLO_MAIL,
    SOLO_WHATSAPP,
    CanalMail,
    EventoComunicacion,
)


class _FakeBG:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **k):
        self.tasks.append((fn, a, k))


def _mock_mail(monkeypatch, sink=None):
    """Mockea `send_email` para devolver el `to`/`template`/`attachments` y, opcional,
    apilar cada llamada en `sink`."""
    def fake(*a, **k):
        rec = {"ok": True, "template": a[0], "to": a[1], "attachments": k.get("attachments")}
        if sink is not None:
            sink.append(rec)
        return rec
    monkeypatch.setattr(d, "send_email", fake)


# ── registro (fuente única) ──────────────────────────────────────────────
def test_registro_referencia_templates_whatsapp_reales_y_estrategia_valida():
    from services.whatsapp.plantillas import REGISTRO as WA

    for ev in REGISTRO.values():
        assert ev.estrategia in ESTRATEGIAS, f"{ev.key}: estrategia inválida {ev.estrategia!r}"
        if ev.whatsapp:
            assert ev.whatsapp in WA, f"{ev.key}: template whatsapp '{ev.whatsapp}' no existe"
        # Coherencia estrategia ↔ templates declarados.
        if ev.estrategia in (SOLO_WHATSAPP, AMBOS, FALLBACK):
            assert ev.whatsapp, f"{ev.key}: {ev.estrategia} necesita template de WhatsApp"
        if ev.estrategia in (SOLO_MAIL, AMBOS):
            assert ev.mail and ev.mail.template_cliente, f"{ev.key}: {ev.estrategia} necesita mail al cliente"


def test_devolucion_es_solo_whatsapp():
    for k in ("recordatorio_devolucion_d1", "recordatorio_devolucion_d0", "recordatorio_devolucion_vencido"):
        ev = REGISTRO[k]
        assert ev.estrategia == SOLO_WHATSAPP and ev.mail is None


def test_confirmacion_es_ambos_con_ics():
    ev = REGISTRO["pedido_confirmado"]
    assert ev.estrategia == AMBOS
    assert ev.mail.con_adjunto_ics is True
    assert ev.whatsapp == "pedido_confirmado"


# ── plan A/B: FALLBACK ────────────────────────────────────────────────────
def test_fallback_whatsapp_entrego_no_manda_mail_al_cliente_pero_si_al_admin(monkeypatch):
    sink = []
    _mock_mail(monkeypatch, sink)
    monkeypatch.setattr(d, "get_admin_to", lambda: "admin@x.com")
    monkeypatch.setattr(wa, "enviar_evento_pedido", lambda *a, **k: {"ok": True, "wamid": "W"})
    res = d.notificar_pedido("pedido_creado", {"id": 1, "cliente_id": 2, "cliente_email": "c@x.com"}, {})
    # WhatsApp llegó → NO se manda el mail al cliente; el admin SÍ (fuera del plan A/B).
    assert res["whatsapp"]["wamid"] == "W"
    tos = [m["to"] for m in sink]
    assert tos == ["admin@x.com"]
    assert res["mail"][0]["to"] == "admin@x.com"


def test_fallback_whatsapp_no_disponible_cae_a_mail_del_cliente(monkeypatch):
    sink = []
    _mock_mail(monkeypatch, sink)
    monkeypatch.setattr(d, "get_admin_to", lambda: "admin@x.com")
    monkeypatch.setattr(wa, "enviar_evento_pedido", lambda *a, **k: {"ok": True, "skipped": True, "reason": "sin_opt_in"})
    res = d.notificar_pedido("pedido_creado", {"id": 1, "cliente_id": 2, "cliente_email": "c@x.com"}, {})
    # WhatsApp no llegó → mail al cliente (plan B) + mail al admin.
    tos = sorted(m["to"] for m in sink)
    assert tos == ["admin@x.com", "c@x.com"]
    assert len(res["mail"]) == 2


def test_fallback_whatsapp_duplicado_cuenta_como_entregado(monkeypatch):
    sink = []
    _mock_mail(monkeypatch, sink)
    monkeypatch.setattr(d, "get_admin_to", lambda: "admin@x.com")
    monkeypatch.setattr(wa, "enviar_evento_pedido", lambda *a, **k: {"ok": True, "skipped": True, "reason": "duplicado"})
    res = d.notificar_pedido("pedido_creado", {"id": 1, "cliente_id": 2, "cliente_email": "c@x.com"}, {})
    # 'duplicado' = ya se había mandado ese WhatsApp → NO se cae al mail del cliente.
    tos = [m["to"] for m in sink]
    assert tos == ["admin@x.com"]


def test_fallback_sin_whatsapp_helper_lo_trata_como_no_entregado():
    assert d._whatsapp_entregado(None) is False
    assert d._whatsapp_entregado({"ok": False, "error": "x"}) is False
    assert d._whatsapp_entregado({"ok": True, "skipped": True, "reason": "sin_telefono_e164"}) is False
    assert d._whatsapp_entregado({"ok": True, "wamid": "W"}) is True
    assert d._whatsapp_entregado({"ok": True, "skipped": True, "reason": "duplicado"}) is True


# ── AMBOS (confirmación): WhatsApp + mail con .ics ────────────────────────
def test_confirmado_manda_whatsapp_y_mail_con_ics(monkeypatch):
    sink = []
    _mock_mail(monkeypatch, sink)
    monkeypatch.setattr(d, "ics_adjunto_pedido", lambda p: ["ICS"])
    monkeypatch.setattr(d, "get_admin_to", lambda: "admin@x.com")  # confirmación NO tiene admin
    monkeypatch.setattr(wa, "enviar_evento_pedido", lambda *a, **k: {"ok": True, "wamid": "W"})
    res = d.notificar_pedido("pedido_confirmado", {"id": 1, "cliente_id": 2, "cliente_email": "c@x.com"}, {})
    assert res["whatsapp"]["wamid"] == "W"  # WhatsApp salió
    assert len(res["mail"]) == 1 and res["mail"][0]["to"] == "c@x.com"  # y el mail al cliente
    assert res["mail"][0]["attachments"] == ["ICS"]  # con el .ics


# ── SOLO_WHATSAPP (devolución): nunca mail ────────────────────────────────
def test_devolucion_solo_whatsapp_no_manda_mail(monkeypatch):
    mail_called = []
    _mock_mail(monkeypatch, mail_called)
    monkeypatch.setattr(wa, "enviar_evento_pedido", lambda *a, **k: {"ok": True, "wamid": "W"})
    res = d.notificar_pedido("recordatorio_devolucion_d1", {"id": 1, "cliente_id": 2}, {})
    assert mail_called == [] and res["mail"] == []
    assert res["whatsapp"]["wamid"] == "W"


# ── SOLO_MAIL (contrato / documentos formales): nunca WhatsApp ────────────
def test_solo_mail_no_toca_whatsapp(monkeypatch):
    wa_called = []
    _mock_mail(monkeypatch)
    monkeypatch.setattr(wa, "enviar_evento_pedido", lambda *a, **k: wa_called.append(a) or {"ok": True})
    ev = EventoComunicacion(
        key="contrato", descripcion="doc formal", estrategia=SOLO_MAIL,
        mail=CanalMail(template_cliente="contrato_cliente"),
    )
    out = d._despachar_cliente(ev, {"id": 1, "cliente_email": "c@x.com"}, {})
    assert wa_called == []
    assert out["whatsapp"] is None and out["mail"]["to"] == "c@x.com"


# ── sin datos de contacto ─────────────────────────────────────────────────
def test_sin_email_cliente_igual_avisa_al_admin(monkeypatch):
    sink = []
    _mock_mail(monkeypatch, sink)
    monkeypatch.setattr(d, "get_admin_to", lambda: "admin@x.com")
    # WhatsApp no disponible y el cliente no tiene email → solo el admin recibe.
    monkeypatch.setattr(wa, "enviar_evento_pedido", lambda *a, **k: {"ok": True, "skipped": True, "reason": "sin_opt_in"})
    res = d.notificar_pedido("pedido_creado", {"id": 1, "cliente_id": 2}, {})  # sin cliente_email
    assert [m["to"] for m in sink] == ["admin@x.com"]
    assert res["whatsapp"]["skipped"] is True


# ── background: una sola tarea encolada (el fallback ve el resultado real) ─
def test_background_encola_una_sola_tarea(monkeypatch):
    sink = []
    _mock_mail(monkeypatch, sink)
    monkeypatch.setattr(d, "get_admin_to", lambda: "admin@x.com")
    monkeypatch.setattr(wa, "enviar_evento_pedido", lambda *a, **k: {"ok": True, "wamid": "W"})
    bg = _FakeBG()
    res = d.notificar_pedido(
        "pedido_creado", {"id": 1, "cliente_id": 2, "cliente_email": "c@x.com"}, {"x": 1}, background=bg
    )
    assert res == {"mail": [], "whatsapp": None}  # encolado; nada síncrono
    assert len(bg.tasks) == 1  # UNA sola tarea (no dos ciegas)
    fn, a, k = bg.tasks[0]
    fn()  # correrla ejecuta el plan A/B completo
    assert [m["to"] for m in sink] == ["admin@x.com"]  # WhatsApp llegó → solo admin por mail


# ── contexto / evento desconocido ─────────────────────────────────────────
def test_ctx_none_se_arma_solo_con_pedido_email_context(monkeypatch):
    llamado = []
    monkeypatch.setattr(d, "pedido_email_context", lambda p: llamado.append(p.get("id")) or {"built": True})
    _mock_mail(monkeypatch)
    monkeypatch.setattr(d, "get_admin_to", lambda: "")
    monkeypatch.setattr(wa, "enviar_evento_pedido", lambda *a, **k: {"ok": True, "wamid": "W"})
    d.notificar_pedido("pedido_creado", {"id": 7, "cliente_id": 2, "cliente_email": "c@x.com"})  # ctx omitido
    assert llamado == [7]


def test_evento_desconocido_no_rompe():
    assert d.notificar_pedido("no_existe", {"id": 1}, {}) == {"mail": [], "whatsapp": None}
