"""C3 #635 — precio del combo derivado de sus componentes (dinámico).

El precio de un combo = Σ(precio_componente × cantidad × (1 − descuento_línea/100)),
en vivo (sigue el precio actual de los componentes). Kits y simples usan su precio
propio. Tests de la fórmula pura `_precio_combo_calc`.
"""
import pytest

from services.precios import _precio_combo_calc

pytestmark = pytest.mark.unit


def test_suma_con_descuento_por_linea():
    # comp A: 1000 ×2 desc 10% → 1800 ; comp B: 500 ×1 desc 70% → 150 → 1950
    comps = [
        {"precio_jornada": 1000, "cantidad": 2, "descuento_pct": 10},
        {"precio_jornada": 500, "cantidad": 1, "descuento_pct": 70},
    ]
    assert _precio_combo_calc(comps) == 1950


def test_sin_descuento_suma_full():
    assert _precio_combo_calc([{"precio_jornada": 1000, "cantidad": 2, "descuento_pct": 0}]) == 2000


def test_descuento_100_componente_gratis():
    comps = [
        {"precio_jornada": 1000, "cantidad": 1, "descuento_pct": 100},
        {"precio_jornada": 500, "cantidad": 1, "descuento_pct": 0},
    ]
    assert _precio_combo_calc(comps) == 500


def test_sin_componentes_da_cero():
    assert _precio_combo_calc([]) == 0


def test_redondea():
    # 333 ×1 desc 33% → 333 × 0.67 = 223.11 → 223
    assert _precio_combo_calc([{"precio_jornada": 333, "cantidad": 1, "descuento_pct": 33}]) == 223


class TestResolverDescuentoUniforme:
    """#1283 Fase 5 — dado un precio objetivo, resuelve el % uniforme que hace
    que `_precio_combo_calc` recomputado dé exactamente ese precio."""

    def test_resuelve_precio_exacto(self):
        from services.precios import resolver_descuento_uniforme, _precio_combo_calc

        comps = [
            {"precio_jornada": 1000, "cantidad": 2, "descuento_pct": 0},
            {"precio_jornada": 500, "cantidad": 1, "descuento_pct": 0},
        ]
        # bruto = 2500. Objetivo 2000 → d = 20%.
        d = resolver_descuento_uniforme(comps, 2000)
        assert d == pytest.approx(20.0)
        aplicado = [{**c, "descuento_pct": d} for c in comps]
        assert _precio_combo_calc(aplicado) == 2000

    def test_objetivo_igual_al_bruto_da_descuento_cero(self):
        from services.precios import resolver_descuento_uniforme

        comps = [{"precio_jornada": 1000, "cantidad": 1, "descuento_pct": 0}]
        assert resolver_descuento_uniforme(comps, 1000) == pytest.approx(0.0)

    def test_objetivo_cero_da_descuento_100(self):
        from services.precios import resolver_descuento_uniforme

        comps = [{"precio_jornada": 1000, "cantidad": 1, "descuento_pct": 0}]
        assert resolver_descuento_uniforme(comps, 0) == pytest.approx(100.0)

    def test_rechaza_objetivo_mayor_al_bruto(self):
        from services.precios import resolver_descuento_uniforme

        comps = [{"precio_jornada": 1000, "cantidad": 1, "descuento_pct": 0}]
        with pytest.raises(ValueError, match="no puede superar"):
            resolver_descuento_uniforme(comps, 1001)

    def test_rechaza_sin_componentes(self):
        from services.precios import resolver_descuento_uniforme

        with pytest.raises(ValueError, match="no tienen precio base"):
            resolver_descuento_uniforme([], 100)

    def test_rechaza_objetivo_negativo(self):
        from services.precios import resolver_descuento_uniforme

        comps = [{"precio_jornada": 1000, "cantidad": 1, "descuento_pct": 0}]
        with pytest.raises(ValueError, match="negativo"):
            resolver_descuento_uniforme(comps, -1)

    def test_ignora_el_descuento_previo_de_las_lineas(self):
        # El descuento VIEJO de cada línea no importa para resolver el nuevo — se
        # pisa por completo (el bruto se calcula sin descuento, como siempre).
        from services.precios import resolver_descuento_uniforme

        comps = [{"precio_jornada": 1000, "cantidad": 1, "descuento_pct": 99}]
        assert resolver_descuento_uniforme(comps, 500) == pytest.approx(50.0)


def test_campos_nulos_tolerados():
    # precio/cantidad/descuento None → tratados como 0
    comps = [
        {"precio_jornada": None, "cantidad": 2, "descuento_pct": 0},
        {"precio_jornada": 800, "cantidad": None, "descuento_pct": None},
        {"precio_jornada": 600, "cantidad": 1, "descuento_pct": None},
    ]
    assert _precio_combo_calc(comps) == 600


# ── Batch (catálogo: precio efectivo de combos sin N+1) ────────────────────────


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Filtra las filas de componentes por los equipo_id pedidos (= ANY(%s))."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, _sql, params=None):
        ids = set(params[0]) if params else set()
        return _FakeCursor([r for r in self._rows if r["equipo_id"] in ids])


def test_precios_combo_batch_agrupa_y_calcula_por_equipo():
    from services.precios import precios_combo_batch

    rows = [
        {"equipo_id": 10, "precio_jornada": 1000, "cantidad": 2, "descuento_pct": 10},
        {"equipo_id": 10, "precio_jornada": 500, "cantidad": 1, "descuento_pct": 70},
        {"equipo_id": 20, "precio_jornada": 1000, "cantidad": 2, "descuento_pct": 0},
    ]
    out = precios_combo_batch(_FakeConn(rows), [10, 20, 30])
    # 10 == el mismo cálculo que test_suma_con_descuento_por_linea (1950); 20 → 2000;
    # 30 no tiene componentes vivos → no aparece (el caller cae a 0).
    assert out == {10: 1950, 20: 2000}


def test_precios_combo_batch_sin_ids_no_consulta():
    from services.precios import precios_combo_batch

    assert precios_combo_batch(_FakeConn([]), []) == {}


# ── Candado de PREVENCIÓN: batch (catálogo) == single (ficha/cotizar) ───────────


class _DualFakeConn:
    """Responde el SELECT single de `precio_combo` (sin `equipo_id` en las filas) Y el
    batch de `precios_combo_batch` (con `equipo_id`) con los MISMOS componentes — para
    verificar que ambos caminos dan idéntico precio de combo (no pueden divergir)."""

    def __init__(self, combo_id, componentes):
        self._id = combo_id
        self._comps = componentes

    def execute(self, sql, params=None):
        if "ANY" in sql:  # batch: filas con equipo_id
            ids = set(params[0]) if params else set()
            rows = (
                [{**c, "equipo_id": self._id} for c in self._comps]
                if self._id in ids else []
            )
        else:  # single (precio_combo): filas sin equipo_id
            rows = list(self._comps)
        return _FakeCursor(rows)


def test_batch_y_single_dan_el_mismo_precio_de_combo():
    """Prevención: el precio de combo del catálogo (`precios_combo_batch`) y el de la
    ficha/carrito (`precio_combo`) tienen que coincidir SIEMPRE — los dos derivan de
    `_precio_combo_calc`. Si alguien cambia una fórmula y no la otra, esto falla y el
    drift catálogo≠cobrado no puede volver."""
    from services.precios import precio_combo, precios_combo_batch

    comps = [
        {"precio_jornada": 1000, "cantidad": 2, "descuento_pct": 10},
        {"precio_jornada": 500, "cantidad": 1, "descuento_pct": 70},
    ]
    conn = _DualFakeConn(42, comps)
    assert precios_combo_batch(conn, [42])[42] == precio_combo(conn, 42)
