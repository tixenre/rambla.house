"""Candado de `pedidos_vinculados.py` como fuente única del eje
`pedido_principal_id` — ningún consumidor debe reimplementar el literal
`pedido_principal_id IS NULL`/`IS NOT NULL` a mano; todos importan
`SIN_PRINCIPAL_SQL`/`es_turno_vinculado` de `pedidos_vinculados.py`. Mismo
patrón que `test_tipos_pedido_source_scan.py`.

El bug real que esto blinda: `list_pedidos` (`routes/alquileres/pedidos.py`)
nunca filtró este eje, así que un turno vinculado se listaba como pedido
propio en `/admin/pedidos` — la queja original del dueño (#1308, tanda de
"el turno deja de listarse aparte").
"""
import inspect
import re

import pytest

import pedidos_vinculados
import routes.alquileres.pedidos as alquileres_pedidos
import routes.equipos.dashboard as equipos_dashboard

pytestmark = pytest.mark.unit

_LITERAL = re.compile(r"pedido_principal_id\s+IS\s+(?:NOT\s+)?NULL", re.IGNORECASE)


def _codigo_sin_comentarios(src: str) -> str:
    return "\n".join(line for line in src.splitlines() if not line.strip().startswith("#"))


@pytest.mark.parametrize("modulo", [alquileres_pedidos, equipos_dashboard])
def test_modulo_no_reimplementa_el_literal(modulo):
    src = _codigo_sin_comentarios(inspect.getsource(modulo))
    m = _LITERAL.search(src)
    assert m is None, (
        f"{modulo.__name__} reimplementa el literal de pedido_principal_id "
        f"({m.group(0)!r} si matcheó) — usar SIN_PRINCIPAL_SQL de pedidos_vinculados.py."
    )


def test_list_pedidos_usa_la_constante_compartida():
    src = inspect.getsource(alquileres_pedidos.list_pedidos)
    assert "SIN_PRINCIPAL_SQL" in src


def test_equipos_dashboard_usa_la_constante_compartida():
    src = inspect.getsource(equipos_dashboard)
    assert "SIN_PRINCIPAL_SQL" in src
    assert "TURNO_VINCULADO_SQL" in src


class TestEsTurnoVinculado:
    def test_true_con_principal(self):
        assert pedidos_vinculados.es_turno_vinculado({"pedido_principal_id": 5}) is True

    def test_false_sin_principal(self):
        assert pedidos_vinculados.es_turno_vinculado({"pedido_principal_id": None}) is False

    def test_false_sin_columna(self):
        assert pedidos_vinculados.es_turno_vinculado({}) is False
