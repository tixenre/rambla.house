"""Defaults + validación del destinatario/método de un pago (#722).

Pieza pura `_resolver_destino_metodo`: aplica los defaults del dueño
(Rental / transferencia) y rechaza valores fuera de la lista.
"""

import pytest
from fastapi import HTTPException

from routes.alquileres import (
    _resolver_destino_metodo,
    DESTINATARIOS_PAGO,
    METODOS_PAGO,
)

pytestmark = pytest.mark.unit


def test_defaults_rental_transferencia():
    assert _resolver_destino_metodo(None, None) == ("Rental", "transferencia")
    assert _resolver_destino_metodo("", "") == ("Rental", "transferencia")


def test_acepta_valores_validos():
    assert _resolver_destino_metodo("Pablo", "efectivo") == ("Pablo", "efectivo")
    assert _resolver_destino_metodo("Tincho", "efectivo") == ("Tincho", "efectivo")
    assert _resolver_destino_metodo("Rental", "transferencia") == ("Rental", "transferencia")


def test_destinatario_invalido_rechazado():
    with pytest.raises(HTTPException) as e:
        _resolver_destino_metodo("Fulano", "transferencia")
    assert e.value.status_code == 400


def test_metodo_invalido_rechazado():
    with pytest.raises(HTTPException) as e:
        _resolver_destino_metodo("Tincho", "cripto")
    assert e.value.status_code == 400


def test_constantes_son_la_fuente_unica():
    # El default tiene que pertenecer a la lista (no quedar huérfano).
    assert "Rental" in DESTINATARIOS_PAGO
    assert "transferencia" in METODOS_PAGO
