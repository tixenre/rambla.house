"""C5 (#1308 rediseño "turno como ítem") — un ítem con `turno_estudio_id` queda
INVISIBLE para el gate genérico (`roots`), sin tocar el núcleo sagrado.

Extiende el harness diferencial de C4 (`test_gate_caracterizacion_c4.py`,
`_World`/`_mundo_aleatorio`/`_gate_referencia`) con mundos que mezclan ítems
normales (sin turno) e ítems de un turno del Estudio embebido: confirma que
`validar_stock` da el MISMO resultado que si los ítems del turno directamente
no existieran en el pedido — la garantía de que `gate.py::_validar_demanda`/
`expandir_demanda`/el `FOR UPDATE` no cambiaron una línea (Fase 1).

El equipo del turno puede coincidir con uno YA usado por el pedido "real" a
propósito: confirma que la exclusión es por FILA (columna `turno_estudio_id`),
no por equipo_id — dos ítems del mismo equipo, uno con turno y otro sin,
deben tratarse distinto.

Lo que este archivo NO prueba (a propósito, fuera de su alcance): la ventana
horaria propia del turno (COALESCE en las queries de lectura, `_centinela_libre`)
— el harness de C4/C5 es agnóstico de fechas (usa una ventana fija en el
`assert`). Esa corrección de overlap real se prueba con Postgres real en
`test_reservas_concurrency_db.py`.
"""
import random

import pytest

from reservas import validar_stock

from tests.test_gate_caracterizacion_c4 import _World, _mundo_aleatorio

pytestmark = pytest.mark.unit


def _mundo_mixto(rng: random.Random) -> tuple[_World, _World]:
    """Devuelve (sin_turno, con_turno): el mismo mundo base, y una variante con
    1-3 ítems ADICIONALES marcados `turno_estudio_id` (un id cualquiera,
    verdadero — el valor puntual no importa, solo que sea truthy). El equipo
    de cada ítem de turno se elige al azar entre TODOS los del mundo (hojas y
    kits), pudiendo repetir uno que el pedido "real" ya usa."""
    base = _mundo_aleatorio(rng)
    todos = list(base.equipos.keys())
    n_turno = rng.randint(1, 3)
    items_turno = [
        {"equipo_id": rng.choice(todos), "cantidad": rng.randint(1, 2),
         "turno_estudio_id": 999}
        for _ in range(n_turno)
    ]
    con_turno = _World(
        base.equipos, base.kit, base.reservas_directas,
        base.pedido_items + items_turno, base.mantenimiento,
    )
    return base, con_turno


@pytest.mark.parametrize("seed", range(300))
def test_items_de_turno_embebido_invisibles_para_el_gate_generico(seed):
    rng = random.Random(seed)
    sin_turno, con_turno = _mundo_mixto(rng)

    esperado = set(validar_stock(sin_turno, 7, "2026-06-01", "2026-06-05"))
    real = set(validar_stock(con_turno, 7, "2026-06-01", "2026-06-05"))

    assert real == esperado, (
        f"seed={seed}: un ítem de turno embebido cambió el resultado del gate genérico "
        f"— debería ser invisible (excluido por `turno_estudio_id IS NULL`).\n"
        f"  con turno ={sorted(real)}\n  sin turno={sorted(esperado)}\n"
        f"  pedido_items (con turno)={con_turno.pedido_items}"
    )


@pytest.mark.parametrize("seed", range(300))
def test_mismo_equipo_como_item_normal_y_como_suelto_de_turno_no_se_confunden(seed):
    """Caso puntual del anterior, aislado: si el ítem de turno usa el MISMO
    `equipo_id` que un ítem normal del pedido, la demanda real (sin turno)
    sigue siendo solo la del ítem normal — el de turno no debe sumarse ni
    restarse a esa demanda, sea cual sea su cantidad."""
    rng = random.Random(seed)
    base = _mundo_aleatorio(rng)
    if not base.pedido_items:
        return
    equipo_compartido = base.pedido_items[0]["equipo_id"]
    con_turno = _World(
        base.equipos, base.kit, base.reservas_directas,
        base.pedido_items + [
            {"equipo_id": equipo_compartido, "cantidad": rng.randint(1, 3),
             "turno_estudio_id": 999},
        ],
        base.mantenimiento,
    )

    esperado = set(validar_stock(base, 7, "2026-06-01", "2026-06-05"))
    real = set(validar_stock(con_turno, 7, "2026-06-01", "2026-06-05"))
    assert real == esperado, (
        f"seed={seed}: un ítem de turno sobre el MISMO equipo_id que un ítem "
        f"normal ({equipo_compartido}) contaminó la demanda del gate genérico."
    )
