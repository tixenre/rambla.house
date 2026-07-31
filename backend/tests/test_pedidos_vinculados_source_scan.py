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

import clientes.queries.historial as clientes_historial
import jobs.recordatorios as jobs_recordatorios
import pedidos_vinculados
import routes.alquileres.pedidos as alquileres_pedidos
import routes.cliente_portal.pedidos as portal_pedidos
import routes.dashboard as admin_dashboard
import routes.equipos.dashboard as equipos_dashboard

pytestmark = pytest.mark.unit

_LITERAL = re.compile(r"pedido_principal_id\s+IS\s+(?:NOT\s+)?NULL", re.IGNORECASE)

# Todo módulo que filtre por el eje `pedido_principal_id` va acá — es el candado
# que evita que la próxima superficie que oculte (o muestre) un turno vinculado
# lo haga con un literal suelto en vez de la constante compartida.
_CONSUMIDORES = [
    alquileres_pedidos,
    equipos_dashboard,
    portal_pedidos,
    clientes_historial,
    jobs_recordatorios,
    admin_dashboard,
]


def _codigo_sin_comentarios(src: str) -> str:
    return "\n".join(line for line in src.splitlines() if not line.strip().startswith("#"))


@pytest.mark.parametrize("modulo", _CONSUMIDORES)
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


@pytest.mark.parametrize("modulo", _CONSUMIDORES)
def test_modulo_importa_la_constante(modulo):
    """No alcanza con no reimplementar el literal: el módulo tiene que estar
    filtrando de verdad. Si alguien saca el filtro de una de estas superficies,
    el turno vinculado vuelve a asomar como pedido propio ahí."""
    src = inspect.getsource(modulo)
    assert "SIN_PRINCIPAL_SQL" in src, (
        f"{modulo.__name__} está en la lista de consumidores del eje pero no usa "
        "SIN_PRINCIPAL_SQL — ¿se removió el filtro de turnos vinculados?"
    )


def test_recordatorios_filtra_por_el_eje_y_no_por_tipo_estudio():
    """El recordatorio de retiro excluye el turno VINCULADO, no `tipo='estudio'`:
    un turno del Estudio suelto es un evento real y debe seguir recibiéndolo."""
    src = inspect.getsource(jobs_recordatorios._pedidos_para_retiro)
    assert "SIN_PRINCIPAL_SQL" in src
    assert "'estudio'" not in src


class TestEsTurnoVinculado:
    def test_true_con_principal(self):
        assert pedidos_vinculados.es_turno_vinculado({"pedido_principal_id": 5}) is True

    def test_false_sin_principal(self):
        assert pedidos_vinculados.es_turno_vinculado({"pedido_principal_id": None}) is False

    def test_false_sin_columna(self):
        assert pedidos_vinculados.es_turno_vinculado({}) is False
