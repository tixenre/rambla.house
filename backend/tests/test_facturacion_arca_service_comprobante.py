"""Tests de services/facturacion_arca_service/comprobante.py — mapeo pedido →
ComprobanteInput. Puros (sin DB, sin red) — mismo patrón que
test_facturacion_centavos.py para el motor arca_fe hermano.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from arca_service_client import Alicuota, Concepto, CondicionIva, DocTipo
from services.facturacion_arca_service.comprobante import (
    construir_comprobante_input,
    idempotency_key_de_pedido,
)

pytestmark = pytest.mark.unit


def _pedido(**overrides) -> dict:
    base = {
        "id": 42,
        "numero_pedido": 422,
        "monto_total": 1000,
        "iva_monto": 210,
        "cliente_perfil_impuestos": "responsable_inscripto",
        "cliente_cuit": "20300000003",
        "cliente_dni": None,
        "cliente_nombre": "Cliente RI SA",
        "cliente_domicilio_fiscal": "Falsa 123",
        "fecha_desde": "2026-07-01",
        "fecha_hasta": "2026-07-05",
    }
    base.update(overrides)
    return base


def test_ri_con_iva_discrimina_alicuota():
    ci = construir_comprobante_input(
        _pedido(), emisor_condicion_iva=CondicionIva.RESPONSABLE_INSCRIPTO
    )
    assert ci.receptor_doc_tipo == DocTipo.CUIT
    assert ci.receptor_doc_nro == "20300000003"
    assert ci.receptor_condicion_iva == CondicionIva.RESPONSABLE_INSCRIPTO
    assert ci.importe_neto == Decimal("1000")
    assert ci.alicuota_unica == Alicuota.IVA_21
    assert ci.concepto == Concepto.SERVICIOS


def test_emisor_monotributo_nunca_suma_iva_aunque_el_pedido_tenga_iva_monto():
    """Mismo hecho fiscal que arca_fe (comprobante_pedido.py): un monotributista
    no le agrega el 21% a NADIE — sea cual sea la condición del receptor."""
    ci = construir_comprobante_input(
        _pedido(iva_monto=210), emisor_condicion_iva=CondicionIva.MONOTRIBUTO
    )
    assert ci.alicuota_unica is None
    assert ci.importe_neto == Decimal("1000")


def test_ri_sin_cuit_degrada_a_consumidor_final():
    ci = construir_comprobante_input(
        _pedido(cliente_cuit=None, cliente_dni="30111222"),
        emisor_condicion_iva=CondicionIva.RESPONSABLE_INSCRIPTO,
    )
    assert ci.receptor_doc_tipo == DocTipo.DNI
    assert ci.receptor_condicion_iva == CondicionIva.CONSUMIDOR_FINAL


def test_consumidor_final_con_dni():
    ci = construir_comprobante_input(
        _pedido(
            cliente_perfil_impuestos="consumidor_final",
            cliente_cuit=None,
            cliente_dni="30111222",
        ),
        emisor_condicion_iva=CondicionIva.RESPONSABLE_INSCRIPTO,
    )
    assert ci.receptor_doc_tipo == DocTipo.DNI
    assert ci.receptor_doc_nro == "30111222"
    assert ci.receptor_condicion_iva == CondicionIva.CONSUMIDOR_FINAL


def test_sin_cuit_ni_dni_cae_a_consumidor_final_sin_identificar():
    ci = construir_comprobante_input(
        _pedido(cliente_cuit=None, cliente_dni=None),
        emisor_condicion_iva=CondicionIva.RESPONSABLE_INSCRIPTO,
    )
    assert ci.receptor_doc_tipo == DocTipo.CONSUMIDOR_FINAL
    assert ci.receptor_doc_nro == "0"


def test_fecha_vto_pago_nunca_queda_en_el_pasado():
    """El pedido ya terminó (fecha_hasta en el pasado) — el vencimiento de pago
    tiene que ser hoy, no una fecha vieja que ARCA rechazaría."""
    ci = construir_comprobante_input(
        _pedido(fecha_hasta="2020-01-01"),
        emisor_condicion_iva=CondicionIva.RESPONSABLE_INSCRIPTO,
        fecha=date(2026, 8, 1),
    )
    assert ci.fecha_vto_pago == date(2026, 8, 1)


def test_receptor_nombre_y_domicilio_vienen_del_pedido():
    ci = construir_comprobante_input(
        _pedido(), emisor_condicion_iva=CondicionIva.RESPONSABLE_INSCRIPTO
    )
    assert ci.receptor_nombre == "Cliente RI SA"
    assert ci.receptor_domicilio == "Falsa 123"


def test_items_incluye_una_linea_con_el_neto_del_pedido():
    ci = construir_comprobante_input(
        _pedido(), emisor_condicion_iva=CondicionIva.RESPONSABLE_INSCRIPTO
    )
    assert len(ci.items) == 1
    assert ci.items[0].subtotal == Decimal("1000")
    assert "422" in ci.items[0].descripcion


def test_idempotency_key_usa_numero_pedido_si_existe():
    assert idempotency_key_de_pedido(_pedido()) == "pedido-422"


def test_idempotency_key_cae_a_id_sin_numero_pedido():
    assert idempotency_key_de_pedido(_pedido(numero_pedido=None)) == "pedido-42"


def test_idempotency_key_explicita_pisa_la_derivada():
    ci = construir_comprobante_input(
        _pedido(),
        emisor_condicion_iva=CondicionIva.RESPONSABLE_INSCRIPTO,
        idempotency_key="custom-key",
    )
    assert ci.idempotency_key == "custom-key"
