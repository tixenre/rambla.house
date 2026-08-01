"""services.finanzas_flujo.pedido — el desglose de plata de un pedido.

Candado del bug de `cobro_modo` (auditoría cruzada de plata, 2026-07-02):
`_enriquecer_pedido_con_total` (`routes/alquileres/core.py`) armaba los ítems
para `calcular_total` SIN pasarle `cobro_modo` — una línea 'fijo' (ej. flete,
#805) se multiplicaba igual por jornadas al mostrar/facturar. Ahora
`desglose_de_pedido` es la fuente única para los 6 consumidores reales
(detalle admin, PDF/mail, portal cliente, facturación).
"""
import pytest

from services.finanzas_flujo.pedido import desglose_de_pedido

pytestmark = pytest.mark.unit


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConn:
    """Responde el único SELECT de perfil_impuestos con la fila dada (o None
    si el pedido ya trae `cliente_perfil_impuestos`)."""

    def __init__(self, row=None):
        self._row = row

    def execute(self, _sql, _params=None):
        return _FakeCursor(self._row)


def _pedido(items, **extra):
    base = {
        "items": items,
        "fecha_desde": "2026-07-01T10:00:00",
        "fecha_hasta": "2026-07-04T10:00:00",  # 3 jornadas
        "cliente_perfil_impuestos": "consumidor_final",
        "descuento_pct": 0,
    }
    base.update(extra)
    return base


def test_linea_jornada_se_multiplica_por_jornadas():
    pedido = _pedido([{"equipo_id": 1, "cantidad": 2, "precio_jornada": 1000, "cobro_modo": "jornada"}])
    out = desglose_de_pedido(_FakeConn(), pedido)
    assert out["bruto"] == 1000 * 2 * 3  # precio * cantidad * jornadas


def test_linea_fija_no_se_multiplica_por_jornadas():
    # El bug: antes esto daba 20000*3=60000 en vez de 20000 (flete, #805).
    pedido = _pedido([{"equipo_id": None, "cantidad": 1, "precio_jornada": 20000, "cobro_modo": "fijo"}])
    out = desglose_de_pedido(_FakeConn(), pedido)
    assert out["bruto"] == 20000


def test_mezcla_de_lineas_jornada_y_fija():
    pedido = _pedido([
        {"equipo_id": 1, "cantidad": 1, "precio_jornada": 1000, "cobro_modo": "jornada"},
        {"equipo_id": None, "cantidad": 1, "precio_jornada": 20000, "cobro_modo": "fijo"},
    ])
    out = desglose_de_pedido(_FakeConn(), pedido)
    assert out["bruto"] == (1000 * 3) + 20000


def test_sin_cobro_modo_default_jornada():
    # Ítems viejos sin la key (pre #805) deben seguir comportándose como antes.
    pedido = _pedido([{"equipo_id": 1, "cantidad": 1, "precio_jornada": 1000}])
    out = desglose_de_pedido(_FakeConn(), pedido)
    assert out["bruto"] == 1000 * 3


def test_devuelve_y_muta_el_mismo_dict():
    pedido = _pedido([{"equipo_id": 1, "cantidad": 1, "precio_jornada": 1000, "cobro_modo": "jornada"}])
    out = desglose_de_pedido(_FakeConn(), pedido)
    assert out is pedido
    assert pedido["cantidad_jornadas"] == 3
    assert "monto_neto" in pedido


def test_linea_de_turno_embebido_no_acumula_el_descuento_global():
    """Candado del hallazgo de auditoría (#1308): `items_para_total` no
    propagaba `turno_estudio_id`, así que una línea de un turno del Estudio
    EMBEBIDO (`cobro_modo='fijo'`, ver `services.estudio.commands.reserva`)
    contaba en la base del descuento global igual que un equipo normal —
    divergía de `_recalcular_total_pedido` (`commands/items.py`), que SÍ la
    excluye. Reproduce el caso real confirmado en vivo: equipo $10.000×3
    jornadas ($30.000 bruto) + turno $69.000 fijo, cliente con 10% —
    persistido/correcto: descuento SOLO sobre los $30.000 del equipo →
    neto = (30.000+69.000) - 3.000 = 96.000. El bug daba 89.100 (10% sobre
    los 99.000 combinados)."""
    pedido = _pedido(
        [
            {"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000, "cobro_modo": "jornada"},
            {
                "equipo_id": 2, "cantidad": 1, "precio_jornada": 69000,
                "cobro_modo": "fijo", "turno_estudio_id": 501,
            },
        ],
        descuento_cliente_pct=10.0,
    )
    out = desglose_de_pedido(_FakeConn(), pedido)
    assert out["bruto"] == 30000 + 69000
    assert out["descuento_monto"] == 3000
    assert out["monto_neto"] == 96000
