"""Candado de `tipos_pedido.py` como fuente única de las familias de pedido
(Fase 1, #1308): ningún consumidor debe reimplementar una lista literal de
tipos (`('estudio', 'estudio_fijo', 'taller')` y variantes) — todos importan
las constantes/predicados de `tipos_pedido.py`. Mismo patrón que
`test_finanzas_flujo_source_scan.py`.

El bug real que esto blinda: antes de esta pasada, `routes/estadisticas.py`
repetía el mismo literal 9 veces (7 `NOT IN` + 2 `IN`), y `routes/dashboard.py`/
`jobs/recordatorios.py`/`services/estudio/queries/disponibilidad.py` cada uno
tenía su propia copia local de `('taller', 'estudio_fijo')` — 4 fuentes de la
misma verdad, cualquiera podía desincronizarse silenciosamente de las otras.
"""
import inspect
import re

import pytest

import jobs.recordatorios as recordatorios
import routes.alquileres.core as alquileres_core
import routes.alquileres.transiciones as transiciones
import routes.dashboard as dashboard
import routes.estadisticas as estadisticas
import services.estudio.queries.disponibilidad as estudio_disponibilidad
import tipos_pedido

pytestmark = pytest.mark.unit

# Matchea una tupla SQL literal de 2+ nombres de tipo conocidos, en CÓDIGO real
# (no en comentarios/docstrings) — ej. `('estudio', 'estudio_fijo')` o
# `('taller','estudio_fijo')`. Deliberadamente NO se prohíbe un `p.tipo = 'taller'`
# individual (comparar contra UN tipo no es la duplicación que esto evita).
_TIPO = r"'(?:estudio|estudio_fijo|taller)'"
_LITERAL_TUPLA = re.compile(rf"\(\s*{_TIPO}\s*,\s*{_TIPO}")


def _codigo_sin_comentarios(src: str) -> str:
    """Líneas de código real, sin las que son puro comentario `#...` (no
    parsea docstrings de más de una línea, pero alcanza para los módulos de
    este test — ningún literal a evitar vive dentro de un docstring largo)."""
    return "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )


@pytest.mark.parametrize(
    "modulo",
    [dashboard, recordatorios, estadisticas, estudio_disponibilidad],
)
def test_modulo_no_reimplementa_tupla_literal_de_tipos(modulo):
    src = _codigo_sin_comentarios(inspect.getsource(modulo))
    m = _LITERAL_TUPLA.search(src)
    assert m is None, (
        f"{modulo.__name__} reimplementa una tupla literal de tipos de pedido "
        f"({m.group(0)!r} si matcheó) — usar TIPOS_*_SQL de tipos_pedido.py."
    )


def test_dashboard_usa_la_constante_compartida():
    src = inspect.getsource(dashboard)
    assert "TIPOS_SIN_RETIRO_SQL" in src
    assert "from tipos_pedido import" in src


def test_recordatorios_usa_la_constante_compartida():
    src = inspect.getsource(recordatorios)
    assert "TIPOS_SIN_RETIRO_SQL" in src


def test_estudio_disponibilidad_usa_la_constante_compartida():
    src = inspect.getsource(estudio_disponibilidad._centinela_libre)
    assert "TIPOS_SIN_RETIRO_SQL" in src


def test_estadisticas_usa_las_constantes_compartidas():
    src = inspect.getsource(estadisticas)
    assert src.count("TIPOS_DERIVADOS_SQL") >= 7, (
        "Las 7 agregaciones de rental deben excluir TIPOS_DERIVADOS_SQL "
        "(estudio + estudio_fijo + taller)."
    )
    assert src.count("TIPOS_ESTUDIO_SQL") >= 2, (
        "Las 2 agregaciones de la sección Estudio deben filtrar TIPOS_ESTUDIO_SQL."
    )


def test_recalcular_total_pedido_es_no_op_para_derivados_no_solo_estudio():
    """Candado del bug latente encontrado en esta pasada: `taller` no estaba
    en el no-op → un pedido de taller podía llevarse un % de descuento de
    cliente/jornadas/manual que no le correspondía (nunca se disparaba porque
    esos campos daban 0 por coincidencia, no por regla)."""
    src = inspect.getsource(alquileres_core._recalcular_total_pedido)
    assert "es_pedido_derivado(p)" in src


def test_apply_pedido_datos_bloquea_fecha_de_cualquier_derivado():
    src = inspect.getsource(alquileres_core._apply_pedido_datos)
    assert "es_pedido_derivado(p)" in src


def test_apply_pedido_items_no_bloquea_en_bloque_a_taller():
    """`_apply_pedido_items` sigue rechazando estudio/estudio_fijo en bloque
    (`es_pedido_estudio`) pero NO extiende ese 409 a `taller` — taller necesita
    poder agregar líneas (matrícula), solo protege el ítem auto. Además, un
    taller NUNCA pasa por `calcular_total`/la jerarquía de descuentos (bug
    latente cerrado en esta pasada, análogo al de `_recalcular_total_pedido`):
    su monto es la suma llana de sus líneas."""
    src = inspect.getsource(alquileres_core._apply_pedido_items)
    assert "es_pedido_estudio(p)" in src
    assert "_validar_reemplazo_items_taller" in src
    assert "es_pedido_taller(p)" in src
    assert "sum(r[4] for r in rows)" in src


def test_revalidar_stock_taller_se_saltea_no_va_al_motor_ni_al_revalidador_de_estudio():
    src = inspect.getsource(transiciones._revalidar_stock)
    assert "es_pedido_taller(p)" in src
    assert "revalidar_disponibilidad_estudio" in src  # rama de estudio, sin cambios


def test_tipos_derivados_es_superset_de_tipos_estudio_mas_taller():
    assert set(tipos_pedido.TIPOS_DERIVADOS) == set(tipos_pedido.TIPOS_ESTUDIO) | {"taller"}


def test_tipos_sin_retiro_es_taller_y_estudio_fijo_sin_estudio_real():
    assert set(tipos_pedido.TIPOS_SIN_RETIRO) == {"taller", "estudio_fijo"}
    assert "estudio" not in tipos_pedido.TIPOS_SIN_RETIRO


class TestEsPedidoDerivado:
    def test_true_para_los_3_tipos(self):
        for tipo in ("estudio", "estudio_fijo", "taller"):
            assert tipos_pedido.es_pedido_derivado({"tipo": tipo}) is True

    def test_false_para_diaria(self):
        assert tipos_pedido.es_pedido_derivado({"tipo": "diaria"}) is False

    def test_false_sin_columna_tipo(self):
        assert tipos_pedido.es_pedido_derivado({}) is False


class TestEsPedidoTaller:
    def test_true_solo_para_taller(self):
        assert tipos_pedido.es_pedido_taller({"tipo": "taller"}) is True
        assert tipos_pedido.es_pedido_taller({"tipo": "estudio"}) is False
        assert tipos_pedido.es_pedido_taller({"tipo": "estudio_fijo"}) is False
        assert tipos_pedido.es_pedido_taller({"tipo": "diaria"}) is False

    def test_no_revienta_con_keyerror_sobre_dict_parcial_sin_tipo(self):
        """El bug que este predicado existe para evitar: un `p["tipo"] ==`
        directo revienta con KeyError sobre un FakeConn/dict de test parcial
        (`test_pedido_apply_items_regresion_500.py`, encontrado en esta
        pasada al agregar el guard de taller a `_apply_pedido_items`)."""
        assert tipos_pedido.es_pedido_taller({}) is False


class TestEsPedidoEstudioSigueExcluyendoTaller:
    def test_taller_no_es_pedido_estudio(self):
        assert tipos_pedido.es_pedido_estudio({"tipo": "taller"}) is False
