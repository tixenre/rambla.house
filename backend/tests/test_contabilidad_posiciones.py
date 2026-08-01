"""Posición acumulada de cada parte — tests PUROS del motor (sin DB).

El corazón es `clasificar_flujo`: qué movimiento cuenta como reparto entre partes y
cuál es plata que el negocio mueve puertas adentro. Es la diferencia entre una
posición correcta y una que un gasto operativo desvía en silencio.

La parte SQL (devengado real de la liquidación, cobros derivados) va en
`test_contabilidad_posiciones_db.py` contra Postgres real.
"""

from contabilidad.queries.posiciones import (
    calcular_posiciones,
    clasificar_flujo,
    flujos_netos,
    parte_de_cuenta,
    sugerir_transferencias,
)
from contabilidad.queries.saldos import calcular_saldos

# Mapa de cuentas del escenario: 1 Pablo (CC), 2 Tincho (CC), 5 Fondo Rental,
# 6 Caja Estudio, 3 Efectivo (caja genérica, no representa a ninguna parte).
PARTE_POR_CUENTA = {1: "Pablo", 2: "Tincho", 5: "Rental", 6: "Estudio", 3: None}
CC_POR_CUENTA = {1: True, 2: True, 5: False, 6: False, 3: False}


def _mov(monto, origen=None, destino=None):
    return {"monto": monto, "cuenta_origen_id": origen, "cuenta_destino_id": destino}


def _clasificar(monto, origen=None, destino=None):
    return clasificar_flujo(_mov(monto, origen, destino), PARTE_POR_CUENTA, CC_POR_CUENTA)


class TestParteDeCuenta:
    def test_una_cuenta_con_socio_es_esa_parte(self):
        assert parte_de_cuenta("Tincho", "socio", "Caja Tincho") == "Tincho"
        assert parte_de_cuenta("Estudio", "fondo", "Caja Estudio") == "Estudio"

    def test_un_fondo_sin_socio_cae_a_rental(self):
        assert parte_de_cuenta(None, "fondo", "Fondo Rental") == "Rental"

    def test_una_caja_generica_no_es_ninguna_parte(self):
        assert parte_de_cuenta(None, "caja", "Efectivo") is None


class TestClasificarFlujo:
    """La regla: la cuenta corriente de un socio no tiene caja, así que TODO lo que
    la toca es un reparto con el negocio; una caja real solo reparte cuando del otro
    lado hay otra parte."""

    def test_reparto_entre_dos_partes(self):
        assert _clasificar(110_500, origen=5, destino=2) == ("Rental", "Tincho")

    def test_gasto_desde_una_caja_real_no_es_reparto(self):
        # EL CASO QUE ROMPE LA FÓRMULA INGENUA `saldo − su_parte`: Rental paga un
        # gasto del negocio con su plata. Su cash baja, pero NO cambia en nada lo
        # que le debe a Pablo/Tincho/Estudio — la parte de cada uno es un
        # porcentaje de lo FACTURADO, no de lo que sobra tras los gastos.
        assert _clasificar(50_000, origen=5) is None

    def test_gasto_desde_la_caja_del_estudio_tampoco(self):
        assert _clasificar(50_000, origen=6) is None

    def test_gasto_desde_la_cuenta_de_un_socio_SI_es_reparto(self):
        # "El socio pagó un gasto de Rental con su propia plata" — su CC no tiene
        # caja, así que si sale plata de ahí es contra el negocio. Espeja el
        # comportamiento ya fijado por
        # `test_gasto_contra_cuenta_socio_cuenta_en_pyl_y_baja_deuda`.
        assert _clasificar(50_000, origen=2) == ("Tincho", "Rental")

    def test_el_negocio_le_carga_algo_a_un_socio(self):
        assert _clasificar(30_000, origen=3, destino=1) == ("Rental", "Pablo")

    def test_mover_plata_entre_dos_cajas_propias_no_es_reparto(self):
        assert _clasificar(80_000, origen=5, destino=3) is None

    def test_aporte_a_una_caja_generica_no_es_reparto(self):
        assert _clasificar(20_000, destino=3) is None

    def test_las_dos_patas_de_un_cambio_de_divisa_no_son_reparto(self):
        # `crear_cambio_divisa` escribe dos `ajuste` de una sola cuenta cada uno.
        assert _clasificar(100_000, origen=5) is None
        assert _clasificar(100, destino=3) is None


class TestPosiciones:
    def test_el_credito_del_estudio_contra_rental_existe(self):
        # El caso que motivó la iniciativa: al Estudio le corresponden $120.000 que
        # cobró Rental. Antes esto no existía en ninguna vista de saldos.
        partes = {
            p["parte"]: p
            for p in calcular_posiciones(
                devengado={"Estudio": 120_000}, cobrado={"Rental": 120_000},
                flujo_neto={}, arranques={},
            )
        }
        assert partes["Estudio"]["pendiente"] == 120_000   # le falta recibir
        assert partes["Rental"]["pendiente"] == -120_000   # tiene de más

    def test_un_gasto_de_rental_no_mueve_ninguna_posicion(self):
        """La prueba de fuego de la fórmula: el gasto baja el cash de Rental pero
        deja las 4 posiciones exactamente donde estaban."""
        base = {"devengado": {"Rental": 219_450, "Tincho": 110_500},
                "cobrado": {"Rental": 461_000}, "arranques": {}}
        sin_gasto = {p["parte"]: p["pendiente"] for p in calcular_posiciones(
            flujo_neto=flujos_netos([], PARTE_POR_CUENTA, CC_POR_CUENTA), **base)}
        con_gasto = {p["parte"]: p["pendiente"] for p in calcular_posiciones(
            flujo_neto=flujos_netos([_mov(50_000, origen=5)], PARTE_POR_CUENTA,
                                    CC_POR_CUENTA), **base)}
        assert sin_gasto == con_gasto

    def test_un_reparto_acerca_las_posiciones_a_cero(self):
        base = {"devengado": {"Rental": 219_450, "Tincho": 110_500},
                "cobrado": {"Rental": 461_000}, "arranques": {}}
        antes = {p["parte"]: p["pendiente"] for p in calcular_posiciones(
            flujo_neto={}, **base)}
        assert antes["Tincho"] == 110_500

        flujo = flujos_netos([_mov(110_500, origen=5, destino=2)],
                             PARTE_POR_CUENTA, CC_POR_CUENTA)
        despues = {p["parte"]: p["pendiente"] for p in calcular_posiciones(
            flujo_neto=flujo, **base)}
        assert despues["Tincho"] == 0
        assert despues["Rental"] == antes["Rental"] + 110_500

    def test_el_arranque_del_socio_es_deuda(self):
        partes = {p["parte"]: p for p in calcular_posiciones(
            devengado={}, cobrado={}, flujo_neto={}, arranques={"Pablo": 601_000})}
        assert partes["Pablo"]["pendiente"] == -601_000  # tiene de más = debe


class TestIdentidadConLaCuentaCorriente:
    """El candado que impide que las dos lecturas vuelvan a divergir: para un socio
    humano, `posicion == −saldo_cc`. No son dos cálculos que hay que mantener
    sincronizados a mano — es el mismo número."""

    ESCENARIOS = [
        ("solo arranque", 601_000, 0, 0, []),
        ("cobró de más", 30_000, 500_000, 205_604, []),
        ("acreedor", 0, 0, 700_000, []),
        ("con reparto al fondo", 601_000, 0, 0, [_mov(100_000, origen=2, destino=5)]),
        ("con gasto pagado por el socio", 0, 500_000, 100_000,
         [_mov(50_000, origen=2)]),
        ("el negocio le cargó algo", 0, 0, 0, [_mov(30_000, origen=3, destino=2)]),
    ]

    def test_posicion_de_socio_es_el_negativo_de_su_cc(self):
        for nombre, arranque, cobrado, devengado, movs in self.ESCENARIOS:
            cuentas = [
                {"id": 2, "nombre": "Caja Tincho", "tipo": "socio", "socio": "Tincho",
                 "saldo_inicial": arranque},
                {"id": 5, "nombre": "Fondo Rental", "tipo": "fondo", "socio": "Rental",
                 "saldo_inicial": 0},
                {"id": 3, "nombre": "Efectivo", "tipo": "caja", "socio": None,
                 "saldo_inicial": 0},
            ]
            cc = {f["nombre"]: f for f in calcular_saldos(
                cuentas, movs, {"Tincho": cobrado}, {"Tincho": devengado})}
            pos = {p["parte"]: p for p in calcular_posiciones(
                devengado={"Tincho": devengado}, cobrado={"Tincho": cobrado},
                flujo_neto=flujos_netos(movs, PARTE_POR_CUENTA, CC_POR_CUENTA),
                arranques={"Tincho": arranque})}
            assert cc["Caja Tincho"]["saldo"] == -pos["Tincho"]["pendiente"], (
                f"escenario {nombre!r}: cuenta corriente "
                f"{cc['Caja Tincho']['saldo']} vs posición {pos['Tincho']['pendiente']}"
            )


class TestSugerirTransferencias:
    def test_empareja_al_que_tiene_de_mas_con_el_que_le_falta(self):
        sug = sugerir_transferencias({"Rental": -241_550, "Pablo": 11_050,
                                      "Tincho": 110_500, "Estudio": 120_000})
        assert sum(s["monto"] for s in sug) == 241_550
        assert all(s["de"] == "Rental" for s in sug)
        assert {s["a"] for s in sug} == {"Pablo", "Tincho", "Estudio"}

    def test_balanceado_no_sugiere_nada(self):
        assert sugerir_transferencias({p: 0 for p in
                                       ("Pablo", "Tincho", "Rental", "Estudio")}) == []

    def test_determinismo(self):
        pend = {"Rental": -100, "Pablo": 60, "Tincho": 40}
        assert sugerir_transferencias(pend) == sugerir_transferencias(pend)

    def test_conservacion(self):
        pend = {"Rental": -150, "Pablo": 100, "Tincho": 50, "Estudio": 0}
        sug = sugerir_transferencias(pend)
        assert sum(s["monto"] for s in sug) == sum(v for v in pend.values() if v > 0)
