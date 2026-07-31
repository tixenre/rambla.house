"""Helpers de reserva compartidos (`reservado_directo` / `reservado_total`).

`reservado_directo` es la subquery única de reserva DIRECTA. `reservado_total`
(C4 #635) es el conteo de consumo RECURSIVO que reemplazó al par
`reservado_directo + reservado_via_kit` (1 nivel): sube por el grafo inverso de
composición (`parientes_de`) y suma la reserva directa de cada antecesor ponderada
por la multiplicidad del camino — así un combo→kit→hoja reservado por otro pedido
descuenta la hoja (a 1 nivel no lo hacía → overbooking en anidados).

Estos tests fijan: el escalar de `reservado_directo`, la recursión de
`reservado_total` (directo, vía-kit 1 nivel, anidado, multiplicación de
cantidades), que params van como bound, y que `validar_stock`/
`validar_stock_hipotetico` comparten el MISMO helper (`reservado_total`) en vez
de re-copiar la subquery.
"""
import ast
import inspect

import pytest

from reservas import reservado_directo as _reservado_directo
from reservas import reservado_total as _reservado_total

pytestmark = pytest.mark.unit


class FakeRow(dict):
    pass


class FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _Conn:
    """FakeConn mínimo para `reservado_directo`: stubea la subquery directa."""

    def __init__(self, directo=0):
        self.directo = directo
        self.calls = []

    def execute(self, sql, params=()):
        s = " ".join(sql.split()).upper()
        self.calls.append((s, params))
        # reservado_directo (escalar) delega en reservado_directo_batch → IN + GROUP BY;
        # params = (*equipo_ids, excl, fh_buf, fd_buf). Substrings (no un match
        # contiguo): #1308 sumó un LEFT JOIN alquiler_turnos_estudio en el medio.
        if "FROM ALQUILER_ITEMS PI2" in s and "WHERE PI2.EQUIPO_ID IN" in s:
            eq_ids = params[:-3]
            return FakeCursor([FakeRow({0: e, 1: self.directo}) for e in eq_ids])
        return FakeCursor([])


class _RevConn:
    """FakeConn para `reservado_total`: grafo inverso (`parientes_de`) + reserva
    directa por equipo.

    parents:  dict[componente_id, list[(equipo_id, cantidad, esencial)]]
    directas: dict[equipo_id, int]  (lo que devuelve `reservado_directo` por equipo)
    """

    def __init__(self, parents=None, directas=None):
        self.parents = parents or {}
        self.directas = directas or {}

    def execute(self, sql, params=()):
        s = " ".join(sql.split()).upper()
        # parientes_de (grafo inverso completo).
        if s.startswith("SELECT EQUIPO_ID, COMPONENTE_ID, CANTIDAD") and "FROM KIT_COMPONENTES" in s:
            rows = [
                FakeRow(equipo_id=eq, componente_id=cid, cantidad=cant, esencial=ese)
                for cid, plist in self.parents.items()
                for (eq, cant, ese) in plist
            ]
            return FakeCursor(rows)
        # reservado_directo (escalar → reservado_directo_batch): IN + GROUP BY.
        if "FROM ALQUILER_ITEMS PI2" in s and "WHERE PI2.EQUIPO_ID IN" in s:
            eq_ids = params[:-3]
            return FakeCursor([FakeRow({0: e, 1: self.directas.get(e, 0)}) for e in eq_ids])
        return FakeCursor([])


# ── reservado_directo ────────────────────────────────────────────────────────

def test_reservado_directo_devuelve_escalar():
    assert _reservado_directo(_Conn(directo=3), 42, 7, "fh", "fd") == 3


def test_params_van_como_bound_y_en_orden():
    c = _Conn(directo=0)
    _reservado_directo(c, 42, 7, "FH", "FD")
    sql, params = c.calls[-1]
    # equipo_id, excl_pedido_id, fh_buf, fd_buf — en ese orden, como bound params.
    assert params == (42, 7, "FH", "FD")
    # SQL parametrizado: placeholders %s presentes (uppercased → %S) y sin {…} sin sustituir.
    assert "%S" in sql and "{" not in sql


# ── reservado_total — conteo de consumo recursivo (C4) ───────────────────────

def test_reservado_total_solo_directo():
    # Sin compuestos: cuenta solo la reserva directa del propio equipo.
    assert _reservado_total(_RevConn(directas={42: 3}), 42, 7, "fh", "fd") == 3


def test_reservado_total_via_kit_un_nivel():
    # Equipo 20 es componente del kit 10 (q1); el kit 10 está reservado 1 vez.
    conn = _RevConn(parents={20: [(10, 1, True)]}, directas={10: 1})
    assert _reservado_total(conn, 20, 7, "fh", "fd") == 1


def test_reservado_total_anidado():
    # Combo 30 → Kit 10 → Hoja 20 (q1 cada arista); el combo 30 reservado 2 veces.
    # A 1 nivel daba 0 (el combo no es padre directo de la hoja) → overbooking.
    conn = _RevConn(parents={20: [(10, 1, True)], 10: [(30, 1, True)]}, directas={30: 2})
    assert _reservado_total(conn, 20, 7, "fh", "fd") == 2


def test_reservado_total_multiplica_cantidades():
    # Kit 10 contiene 3× hoja 20; el kit reservado 2 → consume 6 hojas.
    conn = _RevConn(parents={20: [(10, 3, True)]}, directas={10: 2})
    assert _reservado_total(conn, 20, 7, "fh", "fd") == 6


def test_reservado_total_suma_directo_y_via_compuesto():
    # 1 reserva directa de la hoja 20 + 1 vía kit 10 (q1) = 2.
    conn = _RevConn(parents={20: [(10, 1, True)]}, directas={20: 1, 10: 1})
    assert _reservado_total(conn, 20, 7, "fh", "fd") == 2


# ── Guard estructural: gate e hipotético comparten el helper ─────────────────

def test_gate_e_hipotetico_comparten_el_nucleo():
    """El gate AUTORITATIVO y el dry-run comparten la MISMA pieza: ambos
    delegan en el núcleo único `reservas.gate._validar_demanda`, que es quien usa
    el helper de consumo compartido (`reservado_total`) — así no pueden volver a
    divergir a ninguna profundidad (MEMORIA 2026-05-30 / 2026-05-31).

    Verifica dos cosas:
      1. El núcleo `_validar_demanda` usa `reservado_total` y NO re-copia la
         subquery cruda de reserva directa.
      2. Las dos entradas del motor (`validar_stock`, `validar_stock_hipotetico`)
         delegan en `_validar_demanda` y tampoco re-inlinean la subquery.
    """
    from reservas import validar_stock, validar_stock_hipotetico
    from reservas.gate import _validar_demanda

    def _names(fn):
        return {n.id for n in ast.walk(ast.parse(inspect.getsource(fn)))
                if isinstance(n, ast.Name)}

    # 1. El núcleo usa el helper de consumo y no re-copia la subquery.
    nucleo_names = _names(_validar_demanda)
    assert "reservado_total" in nucleo_names, (
        "_validar_demanda no usa el helper compartido de consumo (reservado_total)"
    )
    assert "FROM alquiler_items pi2" not in inspect.getsource(_validar_demanda), (
        "_validar_demanda re-copia la subquery en vez de usar el helper"
    )

    # 2. Las dos entradas del motor delegan en el núcleo y no inlinean la subquery.
    for fn in (validar_stock, validar_stock_hipotetico):
        assert "_validar_demanda" in _names(fn), (
            f"{fn.__name__} no delega en el núcleo único _validar_demanda"
        )
        assert "FROM alquiler_items pi2" not in inspect.getsource(fn), (
            f"{fn.__name__} re-copia la subquery en vez de delegar en el núcleo"
        )

