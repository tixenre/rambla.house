"""Tests unitarios (sin DB) — cuentas de cobro de una edición de taller: lista
(0+) de alias/cbu/banco, independiente de la modalidad de pago (pedido
explícito del dueño: "una lista de cuentas, sin atar a una forma de pago").

Espeja el estilo de `test_talleres_modalidades_cuotas.py`.
"""

import pytest

pytestmark = pytest.mark.unit


class TestValidarCuentasPago:
    def test_cuenta_valida_se_normaliza(self):
        from services.talleres.queries.clases import _validar_cuentas_pago

        result = _validar_cuentas_pago(
            [{"alias": "rambla.estudio", "cbu": "0170...", "banco": "BBVA"}]
        )
        assert result == [{"id": None, "alias": "rambla.estudio", "cbu": "0170...", "banco": "BBVA"}]

    def test_solo_alias_alcanza(self):
        from services.talleres.queries.clases import _validar_cuentas_pago

        result = _validar_cuentas_pago([{"alias": "rambla.rental"}])
        assert result[0]["alias"] == "rambla.rental"
        assert result[0]["cbu"] == ""
        assert result[0]["banco"] == ""

    def test_cuenta_totalmente_vacia_rechazada(self):
        from fastapi import HTTPException
        from services.talleres.queries.clases import _validar_cuentas_pago

        with pytest.raises(HTTPException) as exc:
            _validar_cuentas_pago([{"alias": "", "cbu": "", "banco": ""}])
        assert exc.value.status_code == 400

    def test_lista_vacia_no_rompe(self):
        from services.talleres.queries.clases import _validar_cuentas_pago

        assert _validar_cuentas_pago([]) == []

    def test_espacios_se_recortan(self):
        from services.talleres.queries.clases import _validar_cuentas_pago

        result = _validar_cuentas_pago([{"alias": "  rambla.estudio  ", "cbu": "", "banco": " BBVA "}])
        assert result[0]["alias"] == "rambla.estudio"
        assert result[0]["banco"] == "BBVA"

    def test_preserva_id_para_update(self):
        from services.talleres.queries.clases import _validar_cuentas_pago

        result = _validar_cuentas_pago([{"id": 7, "alias": "x", "cbu": "", "banco": ""}])
        assert result[0]["id"] == 7


class TestCuentaPagoDict:
    def test_passthrough_sin_plata_derivada(self):
        from routes.talleres import _cuenta_pago_dict

        d = _cuenta_pago_dict({"id": 3, "alias": "rambla.estudio", "cbu": "0170", "banco": "BBVA"})
        assert d == {"id": 3, "alias": "rambla.estudio", "cbu": "0170", "banco": "BBVA"}

    def test_campos_faltantes_caen_a_string_vacio(self):
        from routes.talleres import _cuenta_pago_dict

        d = _cuenta_pago_dict({"id": None, "alias": "solo-alias"})
        assert d["cbu"] == ""
        assert d["banco"] == ""
