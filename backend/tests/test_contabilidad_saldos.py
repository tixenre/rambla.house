"""Contabilidad (#809) — tests puros del motor (sin DB).

Cubre la validación de cuentas y el cálculo de saldos (la matemática: saldo_inicial
+ ingresos derivados + entradas − egresos). La parte SQL (derivación real de
`alquiler_pagos`) se valida en `test_contabilidad_db.py` contra Postgres real.
"""

import pytest

from contabilidad.constants import COBRADORES, TIPOS_CUENTA
from contabilidad.commands.cuentas import validar_cuenta
from contabilidad.queries.saldos import calcular_saldos


class TestValidarCuenta:
    def test_caja_simple_ok(self):
        validar_cuenta({"nombre": "Efectivo", "tipo": "caja"})  # no lanza

    def test_cuenta_socio_ok(self):
        validar_cuenta({"nombre": "Caja Tincho", "tipo": "socio", "socio": "Tincho"})

    def test_todos_los_tipos_son_validos(self):
        for tipo in TIPOS_CUENTA:
            data = {"nombre": f"X {tipo}", "tipo": tipo}
            if tipo == "socio":
                data["socio"] = "Pablo"
            validar_cuenta(data)

    def test_rechaza_nombre_vacio(self):
        with pytest.raises(ValueError):
            validar_cuenta({"nombre": "  ", "tipo": "caja"})

    def test_rechaza_tipo_desconocido(self):
        with pytest.raises(ValueError):
            validar_cuenta({"nombre": "X", "tipo": "billetera"})

    def test_fondo_rambla_como_cobrador_ok(self):
        # Rambla también cobra: el Fondo Rambla (tipo fondo) la representa.
        validar_cuenta({"nombre": "Fondo Rambla", "tipo": "fondo", "socio": "Rambla"})

    def test_rechaza_cobrador_invalido(self):
        with pytest.raises(ValueError):
            validar_cuenta({"nombre": "X", "tipo": "caja", "socio": "Mariano"})

    def test_socio_caja_con_rambla_falla(self):
        # Una caja de tipo 'socio' es de un socio humano, no de Rambla.
        with pytest.raises(ValueError):
            validar_cuenta({"nombre": "Caja X", "tipo": "socio", "socio": "Rambla"})

    def test_rechaza_socio_invalido(self):
        with pytest.raises(ValueError):
            validar_cuenta({"nombre": "Caja X", "tipo": "socio", "socio": "Mariano"})

    def test_cuenta_socio_sin_socio_falla(self):
        with pytest.raises(ValueError):
            validar_cuenta({"nombre": "Caja X", "tipo": "socio"})

    def test_rechaza_saldo_no_entero(self):
        with pytest.raises(ValueError):
            validar_cuenta({"nombre": "X", "tipo": "caja", "saldo_inicial": "1000"})

    def test_moneda_usd_ok(self):
        validar_cuenta({"nombre": "Dólares", "tipo": "caja", "moneda": "USD"})

    def test_rechaza_moneda_invalida(self):
        with pytest.raises(ValueError):
            validar_cuenta({"nombre": "X", "tipo": "caja", "moneda": "EUR"})

    def test_cobradores_son_los_cuatro(self):
        assert set(COBRADORES) == {"Pablo", "Tincho", "Rambla", "Estudio"}


class TestCalcularSaldos:
    def _cuentas(self):
        return [
            {"id": 1, "nombre": "Caja Tincho", "tipo": "socio", "socio": "Tincho", "saldo_inicial": 0},
            {"id": 2, "nombre": "Caja Pablo", "tipo": "socio", "socio": "Pablo", "saldo_inicial": 0},
            {"id": 3, "nombre": "Efectivo", "tipo": "caja", "socio": None, "saldo_inicial": 50000},
            {"id": 5, "nombre": "Fondo Rambla", "tipo": "fondo", "socio": None, "saldo_inicial": 0},
        ]

    def test_ingreso_derivado_va_a_la_caja_del_socio(self):
        filas = calcular_saldos(self._cuentas(), [], {"Tincho": 480000, "Pablo": 120000})
        by = {f["nombre"]: f for f in filas}
        assert by["Caja Tincho"]["saldo"] == 480000
        assert by["Caja Tincho"]["ingresos_alquiler"] == 480000
        assert by["Caja Pablo"]["saldo"] == 120000
        # Una caja sin socio NO recibe ingresos derivados.
        assert by["Efectivo"]["ingresos_alquiler"] == 0
        assert by["Efectivo"]["saldo"] == 50000  # solo su saldo inicial

    def test_movimientos_mueven_plata(self):
        movs = [
            {"monto": 25000, "cuenta_origen_id": 3, "cuenta_destino_id": None},   # gasto desde Efectivo
            {"monto": 100000, "cuenta_origen_id": 1, "cuenta_destino_id": 5},     # transf Tincho→Fondo
            {"monto": 30000, "cuenta_origen_id": None, "cuenta_destino_id": 2},   # aporte a Caja Pablo
        ]
        filas = calcular_saldos(self._cuentas(), movs, {"Tincho": 480000, "Pablo": 120000})
        by = {f["nombre"]: f for f in filas}
        # Tincho: 0 + 480000 (ingresos) − 100000 (transf out) = 380000
        assert by["Caja Tincho"]["saldo"] == 380000
        assert by["Caja Tincho"]["egresos"] == 100000
        # Pablo: 0 + 120000 + 30000 (aporte) = 150000
        assert by["Caja Pablo"]["saldo"] == 150000
        assert by["Caja Pablo"]["entradas"] == 30000
        # Efectivo: 50000 − 25000 (gasto) = 25000
        assert by["Efectivo"]["saldo"] == 25000
        assert by["Efectivo"]["egresos"] == 25000
        # Fondo Rambla: 0 + 100000 (transf in) = 100000
        assert by["Fondo Rambla"]["saldo"] == 100000
        assert by["Fondo Rambla"]["entradas"] == 100000

    def test_ingreso_de_socio_sin_caja_se_ignora(self):
        # Un destinatario que no tiene caja en la lista no rompe ni se pierde
        # silenciosamente en otra cuenta (la reconciliación lo cazará aparte).
        filas = calcular_saldos(self._cuentas(), [], {"Tincho": 100, "Fantasma": 999})
        total_ingresos = sum(f["ingresos_alquiler"] for f in filas)
        assert total_ingresos == 100  # los 999 del fantasma no entran a ninguna caja

    def test_sin_cuentas_da_lista_vacia(self):
        assert calcular_saldos([], [], {}) == []

    def test_totales_por_moneda_no_mezcla(self):
        from contabilidad.queries.saldos import _totales_por_moneda

        filas = [
            {"moneda": "ARS", "saldo": 100},
            {"moneda": "ARS", "saldo": 50},
            {"moneda": "USD", "saldo": 7},
        ]
        assert _totales_por_moneda(filas) == {"ARS": 150, "USD": 7}

    def test_cobros_ars_no_alimentan_caja_usd(self):
        cuentas = [
            {"id": 1, "nombre": "Caja Tincho", "tipo": "socio", "socio": "Tincho",
             "moneda": "ARS", "saldo_inicial": 0},
            {"id": 9, "nombre": "Dólares", "tipo": "caja", "socio": None,
             "moneda": "USD", "saldo_inicial": 0},
        ]
        by = {f["nombre"]: f for f in calcular_saldos(cuentas, [], {"Tincho": 500})}
        assert by["Caja Tincho"]["saldo"] == 500
        assert by["Dólares"]["saldo"] == 0  # los cobros ARS no caen en la caja USD


class TestCuentaCorrienteSocio:
    """Pablo/Tincho son cuentas corrientes: deuda = arranque + cobró − su parte ± rendiciones.
    Rambla (Fondo) es una caja de plata real (su parte NO se resta)."""

    def _cuentas(self):
        return [
            {"id": 1, "nombre": "Pablo", "tipo": "socio", "socio": "Pablo", "saldo_inicial": 601000},
            {"id": 2, "nombre": "Tincho", "tipo": "socio", "socio": "Tincho", "saldo_inicial": 30000},
            {"id": 5, "nombre": "Fondo Rambla", "tipo": "fondo", "socio": "Rambla", "saldo_inicial": 0},
        ]

    def test_arranque_es_deuda(self):
        # Sin cobros ni su parte: Pablo arranca DEUDOR por su arranque.
        by = {f["nombre"]: f for f in calcular_saldos(self._cuentas(), [], {}, {})}
        assert by["Pablo"]["es_cuenta_corriente"] is True
        assert by["Pablo"]["saldo"] == 601000
        assert by["Pablo"]["estado"] == "deudor"

    def test_su_parte_baja_la_deuda(self):
        # Pablo: arranque 601000 + cobró 200000 − su parte 261000 = 540000 (deudor).
        by = {
            f["nombre"]: f
            for f in calcular_saldos(self._cuentas(), [], {"Pablo": 200000}, {"Pablo": 261000})
        }
        assert by["Pablo"]["saldo"] == 540000
        assert by["Pablo"]["ingresos_alquiler"] == 200000
        assert by["Pablo"]["su_parte"] == 261000
        assert by["Pablo"]["estado"] == "deudor"

    def test_se_da_vuelta_a_acreedor(self):
        # Si su parte supera arranque+cobró → Rambla le debe (acreedor, saldo negativo).
        by = {
            f["nombre"]: f for f in calcular_saldos(self._cuentas(), [], {}, {"Pablo": 700000})
        }
        assert by["Pablo"]["saldo"] == -99000  # 601000 − 700000
        assert by["Pablo"]["estado"] == "acreedor"

    def test_saldado_en_cero(self):
        by = {
            f["nombre"]: f for f in calcular_saldos(self._cuentas(), [], {}, {"Pablo": 601000})
        }
        assert by["Pablo"]["saldo"] == 0
        assert by["Pablo"]["estado"] == "saldado"

    def test_rendir_baja_la_deuda_y_entra_a_la_caja(self):
        # Pablo rinde 100000 (transfiere de su cuenta corriente al Fondo Rambla):
        # su deuda baja y el Fondo (caja real) recibe la plata.
        movs = [{"monto": 100000, "cuenta_origen_id": 1, "cuenta_destino_id": 5}]
        by = {f["nombre"]: f for f in calcular_saldos(self._cuentas(), movs, {}, {})}
        assert by["Pablo"]["saldo"] == 501000  # 601000 − 100000
        assert by["Fondo Rambla"]["saldo"] == 100000

    def test_rambla_es_caja_no_cuenta_corriente(self):
        # El Fondo Rambla representa a Rambla pero es CAJA: su parte no se resta,
        # lo que cobra suma como cash real.
        by = {
            f["nombre"]: f
            for f in calcular_saldos(self._cuentas(), [], {"Rambla": 374000}, {"Rambla": 999})
        }
        assert by["Fondo Rambla"]["es_cuenta_corriente"] is False
        assert by["Fondo Rambla"]["su_parte"] == 0
        assert by["Fondo Rambla"]["saldo"] == 374000
