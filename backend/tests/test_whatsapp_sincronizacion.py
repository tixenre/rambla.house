"""Tests del alta de plantillas en Meta (`services/whatsapp/sincronizacion.py`).

Sin red: se mockea el cliente de `whatsapp_cloud`. Lo que se prueba es la DECISIÓN
del adapter (qué crea, qué saltea, cómo informa), no el HTTP — eso ya lo cubre
`whatsapp_cloud/tests`.
"""
from __future__ import annotations

import pytest

import services.whatsapp.sincronizacion as sync
from services.whatsapp.plantillas import REGISTRO
from whatsapp_cloud import TemplateRemoto, WhatsAppError

pytestmark = pytest.mark.unit


class _FakeCliente:
    def __init__(self, existentes=(), falla_en=(), falla_listar=False):
        self.existentes = list(existentes)
        self.falla_en = set(falla_en)
        self.falla_listar = falla_listar
        self.creados: list[str] = []

    def listar(self, **_):
        if self.falla_listar:
            raise WhatsAppError("Meta no contestó")
        return self.existentes

    def crear_body(self, *, name, language, body_text, ejemplos, category="UTILITY"):
        if name in self.falla_en:
            raise WhatsAppError(f"Meta rechazó {name}")
        self.creados.append(name)
        return TemplateRemoto(
            name=name, language=language, status="PENDING", category=category.lower()
        )


def _con(monkeypatch, cli):
    monkeypatch.setattr(sync, "_cliente", lambda: cli)


# ── sincronizar ──────────────────────────────────────────────────────────
def test_crea_todas_cuando_no_existe_ninguna(monkeypatch):
    cli = _FakeCliente()
    _con(monkeypatch, cli)
    out = sync.sincronizar()
    assert out["ok"] is True
    assert out["creadas"] == len(REGISTRO) and out["ya_existian"] == 0
    assert set(cli.creados) == {p.meta_name for p in REGISTRO.values()}


def test_no_recrea_las_que_ya_existen(monkeypatch):
    """Se lista ANTES de crear: el 'ya existe' no depende del mensaje de error."""
    una = next(iter(REGISTRO.values()))
    cli = _FakeCliente(
        existentes=[TemplateRemoto(name=una.meta_name, language=una.lang, status="APPROVED", category="utility")]
    )
    _con(monkeypatch, cli)
    out = sync.sincronizar()
    assert out["ya_existian"] == 1
    assert una.meta_name not in cli.creados
    assert out["creadas"] == len(REGISTRO) - 1


def test_una_que_falla_no_frena_a_las_demas(monkeypatch):
    una = next(iter(REGISTRO.values()))
    cli = _FakeCliente(falla_en={una.meta_name})
    _con(monkeypatch, cli)
    out = sync.sincronizar()
    assert out["ok"] is False and out["fallidas"] == 1
    assert out["creadas"] == len(REGISTRO) - 1
    err = [r for r in out["resultados"] if r["resultado"] == "error"]
    assert err and err[0]["meta_name"] == una.meta_name


def test_sin_credencial_informa_y_no_rompe(monkeypatch):
    monkeypatch.setattr(sync, "_cliente", lambda: None)
    out = sync.sincronizar()
    assert out["ok"] is False and out["creadas"] == 0
    assert "WHATSAPP_BUSINESS_ACCOUNT_ID" in out["motivo"]


def test_si_meta_falla_al_listar_no_crea_nada(monkeypatch):
    """No se crea a ciegas: sin saber qué existe, se podría duplicar."""
    cli = _FakeCliente(falla_listar=True)
    _con(monkeypatch, cli)
    out = sync.sincronizar()
    assert out["ok"] is False and out["creadas"] == 0 and cli.creados == []


# ── estado_plantillas ────────────────────────────────────────────────────
def test_estado_marca_no_creada_y_el_estado_real(monkeypatch):
    una = next(iter(REGISTRO.values()))
    cli = _FakeCliente(
        existentes=[TemplateRemoto(name=una.meta_name, language=una.lang, status="APPROVED", category="utility")]
    )
    _con(monkeypatch, cli)
    out = sync.estado_plantillas()
    assert out["disponible"] is True
    por_key = {f["key"]: f for f in out["plantillas"]}
    assert por_key[una.key]["estado"] == "APPROVED" and por_key[una.key]["existe"] is True
    otras = [f for k, f in por_key.items() if k != una.key]
    assert all(f["estado"] == "NO_CREADA" and f["existe"] is False for f in otras)


def test_ejemplos_siguen_el_orden_de_los_campos():
    """Los valores de muestra que ve Meta van en el MISMO orden que los {{n}}."""
    p = REGISTRO["pedido_confirmado"]
    assert p.campos_ctx == ("cliente_nombre", "numero_pedido", "fecha_desde")
    assert sync._ejemplos_de(p.campos_ctx) == ["Santiago", "1042", "15 jun · 10:00"]
