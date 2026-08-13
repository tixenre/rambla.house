"""Tests unitarios (sin DB) — modalidades de pago: `monto_cuota` derivado de
`monto_total`/`n_cuotas`, nunca tipeado a mano (fix: comunicación de cuotas).

Espeja el estilo de `test_talleres.py` (pytest.mark.unit, sin mocks de
conexión donde no hace falta — acá las 3 funciones bajo test son puras).
"""

import pytest

pytestmark = pytest.mark.unit


class TestMontoPorCuota:
    def test_division_exacta(self):
        from routes.talleres import _monto_por_cuota

        assert _monto_por_cuota(320_000, 4) == 80_000

    def test_pago_unico(self):
        from routes.talleres import _monto_por_cuota

        assert _monto_por_cuota(100_000, 1) == 100_000

    def test_division_inexacta_redondea(self):
        from routes.talleres import _monto_por_cuota

        # 100_000 / 3 = 33_333.33... -> redondeado al peso, no truncado.
        assert _monto_por_cuota(100_000, 3) == 33_333


class TestModalidadDict:
    def test_incluye_monto_cuota_calculado(self):
        from routes.talleres import _modalidad_dict

        d = _modalidad_dict(
            {"codigo": "mensual", "label": "Mensual", "nota": "", "monto_total": 320_000, "n_cuotas": 4}
        )
        assert d["n_cuotas"] == 4
        assert d["monto_cuota"] == 80_000
        assert d["monto_cuota_str"] == "$80.000"
        assert d["monto_total_str"] == "$320.000"

    def test_n_cuotas_ausente_default_a_1(self):
        """El fallback sintético de `_modalidades_publicas` (edición sin
        modalidades configuradas) no setea `n_cuotas` — tiene que caer a 1,
        no romper."""
        from routes.talleres import _modalidad_dict

        d = _modalidad_dict({"codigo": "total", "label": "Pago total", "nota": "", "monto_total": 100_000})
        assert d["n_cuotas"] == 1
        assert d["monto_cuota"] == 100_000
        assert d["monto_cuota_str"] == "$100.000"


class TestValidarModalidades:
    def test_default_n_cuotas_1(self):
        from services.talleres.queries.clases import _validar_modalidades

        result = _validar_modalidades(
            [{"codigo": "total", "label": "Pago total", "monto_total": 100_000}]
        )
        assert result[0]["n_cuotas"] == 1

    def test_n_cuotas_explicito_se_normaliza(self):
        from services.talleres.queries.clases import _validar_modalidades

        result = _validar_modalidades(
            [{"codigo": "mensual", "label": "Mensual", "monto_total": 320_000, "n_cuotas": 4}]
        )
        assert result[0]["n_cuotas"] == 4

    def test_n_cuotas_menor_a_1_rechazada(self):
        from fastapi import HTTPException
        from services.talleres.queries.clases import _validar_modalidades

        with pytest.raises(HTTPException) as exc:
            _validar_modalidades(
                [{"codigo": "mensual", "label": "Mensual", "monto_total": 320_000, "n_cuotas": 0}]
            )
        assert exc.value.status_code == 400
        assert "n_cuotas" in exc.value.detail
