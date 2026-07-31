"""Validación de las settings que configuran la comunicación (`routes/settings.py`).

Estas keys las edita el back-office DESDE cada evento (`/admin/comunicacion`), por
el mismo `PUT /api/admin/settings/{key}` de siempre — así que la normalización tiene
que vivir en el endpoint, no en la pantalla.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routes.settings as rs

pytestmark = pytest.mark.unit


class _FakeConn:
    """Captura el (key, value) que se persiste."""

    def __init__(self):
        self.escrito: tuple | None = None
        self.borrado: str | None = None

    def execute(self, sql, params=()):
        if sql.strip().upper().startswith("DELETE"):
            self.borrado = params[0]
        else:
            self.escrito = (params[0], params[1])
        return self

    def commit(self):
        pass

    def rollback(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def conn(monkeypatch):
    c = _FakeConn()
    monkeypatch.setattr(rs, "require_admin", lambda request: {"email": "admin@x.com"})
    monkeypatch.setattr(rs, "get_db", lambda: c)
    return c


def _put(key, value):
    return rs.update_setting.__wrapped__(key=key, payload={"value": value}, request=None)


def test_numeros_del_equipo_se_guardan_normalizados_a_e164(conn):
    """El embudo único (services/telefono) corre al GUARDAR: si un número está mal
    el admin se entera acá, no cuando el aviso no llegó."""
    _put("whatsapp_admin_numeros", "2236898641 , +54 9 223 585-2510")
    # El embudo no inventa el 9 de celular: normaliza lo que le dan (acá, una línea
    # fija y un celular) — por eso el placeholder de la UI pide el número completo.
    assert conn.escrito == ("whatsapp_admin_numeros", "+542236898641, +5492235852510")


def test_numeros_del_equipo_deduplican(conn):
    _put("whatsapp_admin_numeros", "+54 9 223 585 2510, +5492235852510")
    assert conn.escrito[1] == "+5492235852510"


def test_numero_invalido_del_equipo_se_rechaza(conn):
    with pytest.raises(HTTPException) as e:
        _put("whatsapp_admin_numeros", "+5492236898641, 123")
    assert e.value.status_code == 400 and "123" in e.value.detail
    assert conn.escrito is None  # no se guardó nada a medias


def test_numeros_del_equipo_se_pueden_vaciar(conn):
    _put("whatsapp_admin_numeros", "")
    assert conn.borrado == "whatsapp_admin_numeros"  # vuelve al default (nadie)


@pytest.mark.parametrize(
    "key",
    [
        "recordatorios_devolucion_d1_enabled",
        "recordatorios_devolucion_d0_enabled",
        "recordatorios_devolucion_vencido_enabled",
        "whatsapp_enabled",
    ],
)
def test_switches_se_normalizan_a_1_0(conn, key):
    _put(key, "true")
    assert conn.escrito == (key, "1")
    _put(key, "nada")
    assert conn.escrito == (key, "0")


@pytest.mark.parametrize(
    "key,ok,fuera",
    [
        ("recordatorios_hora", "23", "24"),
        ("recordatorios_devolucion_hora", "0", "-1"),
        ("recordatorios_dias_antes", "14", "15"),
        ("recordatorios_devolucion_dias_antes", "1", "0"),
    ],
)
def test_rangos_de_horario_y_antelacion(conn, key, ok, fuera):
    _put(key, ok)
    assert conn.escrito == (key, ok)
    with pytest.raises(HTTPException) as e:
        _put(key, fuera)
    assert e.value.status_code == 400


# ── por dónde sale cada evento (la elección del dueño) ───────────────────────
def test_guardar_por_donde_sale_un_evento(conn):
    _put("comunicacion_estrategia_pedido_creado", "ambos")
    assert conn.escrito == ("comunicacion_estrategia_pedido_creado", "ambos")


def test_una_forma_de_mandar_inventada_se_rechaza(conn):
    with pytest.raises(HTTPException) as e:
        _put("comunicacion_estrategia_pedido_creado", "por_paloma_mensajera")
    assert e.value.status_code == 400
    assert conn.escrito is None


def test_evento_inexistente_se_rechaza(conn):
    with pytest.raises(HTTPException) as e:
        _put("comunicacion_estrategia_no_existe", "ambos")
    assert e.value.status_code == 400


def test_vaciarla_vuelve_al_default_del_registro(conn):
    _put("comunicacion_estrategia_pedido_creado", "")
    assert conn.borrado == "comunicacion_estrategia_pedido_creado"
