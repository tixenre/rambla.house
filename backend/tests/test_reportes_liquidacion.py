"""Reporte de liquidación (#88) — tests puros del motor (sin DB).

Cubre el modelo de comisiones (reparto + validación) y la agregación
(prorrateo ya viene en las filas; acá se testea reparto + buckets mes/día +
detalle por dueño). La parte SQL se valida en staging con datos reales.
"""

import pytest

from reportes.comisiones import DEFAULT_MODELO, repartir, validar_modelo
from reportes.liquidacion import agregar, combinar_meses, excluir_dueno


class TestRepartir:
    def test_rental_se_lleva_todo(self):
        assert repartir("Rental", 100000, DEFAULT_MODELO) == {"Rental": 100000}

    def test_pablo_50_45_5(self):
        r = repartir("Pablo", 100000, DEFAULT_MODELO)
        assert r == {"Pablo": 50000, "Rental": 45000, "Tincho": 5000}

    def test_tincho_50_45_5(self):
        r = repartir("Tincho", 100000, DEFAULT_MODELO)
        assert r == {"Tincho": 50000, "Rental": 45000, "Pablo": 5000}

    def test_dueno_desconocido_cobra_todo(self):
        # Un valor legacy fuera del modelo no pierde plata: 100% a sí mismo.
        assert repartir("Legacy SA", 100000, DEFAULT_MODELO) == {"Legacy SA": 100000}

    def test_reparto_suma_el_monto(self):
        for dueno in ("Rental", "Pablo", "Tincho"):
            assert sum(repartir(dueno, 123456, DEFAULT_MODELO).values()) == pytest.approx(123456)

    def test_estudio_se_lleva_todo(self):
        # Economía separada (#1283): el Estudio no reparte con nadie más — es
        # otra unidad de negocio, no una comisión sobre un equipo de Rental.
        assert repartir("Estudio", 90000, DEFAULT_MODELO) == {"Estudio": 90000}


class TestValidarModelo:
    def test_default_es_valido(self):
        validar_modelo(DEFAULT_MODELO)  # no lanza

    def test_rechaza_no_suma_100(self):
        with pytest.raises(ValueError):
            validar_modelo({"Pablo": {"Pablo": 50, "Rental": 40}})  # suma 90

    def test_rechaza_pct_fuera_de_rango(self):
        with pytest.raises(ValueError):
            validar_modelo({"Rental": {"Rental": 150}})

    def test_rechaza_vacio(self):
        with pytest.raises(ValueError):
            validar_modelo({})

    def test_rechaza_pct_no_numerico(self):
        with pytest.raises(ValueError):
            validar_modelo({"Rental": {"Rental": "100"}})


class TestAgregar:
    def _filas(self):
        # Un pedido de Pablo saldado en mayo, uno de Rental saldado en junio.
        return [
            {"fecha": "2026-05-10", "pedido_id": 1, "dueno": "Pablo",
             "equipo": "Sony FX3", "monto": 100000},
            {"fecha": "2026-06-03", "pedido_id": 2, "dueno": "Rental",
             "equipo": "Canon R5", "monto": 40000},
        ]

    def test_resumen_total_y_reparto(self):
        d = agregar(self._filas(), DEFAULT_MODELO)
        assert d["resumen"]["total"] == 140000
        pb = d["resumen"]["por_beneficiario"]
        # Pablo: 50k; Rental: 45k (de Pablo) + 40k (suyo) = 85k; Tincho: 5k.
        assert pb["Pablo"] == 50000
        assert pb["Rental"] == 85000
        assert pb["Tincho"] == 5000

    def test_buckets_por_mes_atribuyen_al_mes_de_saldado(self):
        d = agregar(self._filas(), DEFAULT_MODELO)
        meses = {m["mes"]: m for m in d["por_mes"]}
        assert set(meses) == {"2026-05", "2026-06"}
        assert meses["2026-05"]["total"] == 100000
        assert meses["2026-06"]["total"] == 40000

    def test_por_dia_y_por_dueno(self):
        d = agregar(self._filas(), DEFAULT_MODELO)
        dias = {x["dia"] for x in d["por_dia"]}
        assert dias == {"2026-05-10", "2026-06-03"}
        duenos = {x["dueno"]: x for x in d["por_dueno"]}
        assert duenos["Pablo"]["monto_generado"] == 100000
        assert duenos["Pablo"]["reparto"]["Rental"] == 45000
        assert duenos["Pablo"]["equipos"][0]["equipo"] == "Sony FX3"

    def test_cuenta_veces_alquilado(self):
        # Mismo equipo de Pablo en 2 pedidos distintos → veces == 2; total pedidos == 3.
        filas = [
            {"fecha": "2026-06-03", "pedido_id": 1, "dueno": "Pablo",
             "equipo": "Sony FX3", "monto": 100000},
            {"fecha": "2026-06-10", "pedido_id": 2, "dueno": "Pablo",
             "equipo": "Sony FX3", "monto": 60000},
            {"fecha": "2026-06-15", "pedido_id": 3, "dueno": "Rental",
             "equipo": "Canon R5", "monto": 40000},
        ]
        d = agregar(filas, DEFAULT_MODELO)
        assert d["resumen"]["pedidos"] == 3
        pablo = {x["dueno"]: x for x in d["por_dueno"]}["Pablo"]
        assert pablo["pedidos"] == 2
        assert pablo["equipos"][0]["veces"] == 2

    def test_filas_vacias(self):
        d = agregar([], DEFAULT_MODELO)
        assert d["resumen"]["total"] == 0
        assert d["resumen"]["pedidos"] == 0
        assert d["por_mes"] == [] and d["por_dia"] == [] and d["por_dueno"] == []

    def test_pedidos_detalle_por_dueno(self):
        # Un pedido con equipos de 2 dueños distintos: cada dueño ve SU monto
        # para ESE pedido en `pedidos_detalle`, no el total del pedido (2026-07-04).
        filas = [
            {"fecha": "2026-06-03", "pedido_id": 1, "numero_pedido": 501,
             "cliente": "Juan Pérez", "dueno": "Pablo", "equipo": "Sony FX3", "monto": 60000},
            {"fecha": "2026-06-03", "pedido_id": 1, "numero_pedido": 501,
             "cliente": "Juan Pérez", "dueno": "Rental", "equipo": "Canon R5", "monto": 40000},
        ]
        d = agregar(filas, DEFAULT_MODELO)
        duenos = {x["dueno"]: x for x in d["por_dueno"]}
        pablo_pedidos = duenos["Pablo"]["pedidos_detalle"]
        rental_pedidos = duenos["Rental"]["pedidos_detalle"]
        assert pablo_pedidos == [
            {"pedido_id": 1, "numero_pedido": 501, "cliente": "Juan Pérez",
             "fecha": "2026-06-03", "monto": 60000},
        ]
        assert rental_pedidos[0]["monto"] == 40000

    def test_pedidos_detalle_fallback_sin_numero_ni_cliente(self):
        # Filas sin numero_pedido/cliente (compat con filas viejas/otros tests)
        # caen a pedido_id y string vacío — no explota.
        d = agregar(self._filas(), DEFAULT_MODELO)
        pablo = {x["dueno"]: x for x in d["por_dueno"]}["Pablo"]
        assert pablo["pedidos_detalle"][0]["numero_pedido"] == 1  # == pedido_id
        assert pablo["pedidos_detalle"][0]["cliente"] == ""


class TestExcluirDueno:
    """Separar la Liquidación del Estudio y la de Rental (2026-08-03): el
    Estudio se modela como "otro dueño 100% self" solo para que el reparto lo
    calcule sin código aparte, pero la página de Liquidación (reparto real
    entre Pablo/Tincho/Rental) no debe mostrarlo mezclado."""

    def _filas_mixtas(self):
        # Un pedido con equipo de Pablo Y el centinela del Estudio (mismo
        # pedido — caso real: un turno del Estudio embebido en un alquiler
        # normal, #1308), más un pedido de Rental puro en otro mes.
        return [
            {"fecha": "2026-06-03", "pedido_id": 1, "numero_pedido": 501,
             "cliente": "Juan Pérez", "dueno": "Pablo", "equipo": "Sony FX3", "monto": 60000},
            {"fecha": "2026-06-03", "pedido_id": 1, "numero_pedido": 501,
             "cliente": "Juan Pérez", "dueno": "Estudio", "equipo": "Estudio (espacio)",
             "monto": 40000},
            {"fecha": "2026-07-10", "pedido_id": 2, "numero_pedido": 502,
             "cliente": "Ana Gómez", "dueno": "Rental", "equipo": "Canon R5", "monto": 100000},
        ]

    def test_resta_el_total_del_dueno_excluido(self):
        d = agregar(self._filas_mixtas(), DEFAULT_MODELO)
        assert d["resumen"]["total"] == 200000  # 60k + 40k + 100k

        sin_estudio = excluir_dueno(d, "Estudio")
        assert sin_estudio["resumen"]["total"] == 160000  # 60k + 100k, sin los 40k

    def test_saca_la_clave_de_los_tres_por_beneficiario(self):
        # No alcanza con sacarlo de la lista `beneficiarios`: la clave del
        # dict tiene que desaparecer de resumen Y de cada mes/día — un
        # consumidor que iterara Object.keys() en vez de la lista lo seguiría
        # viendo (bug real encontrado al escribir el test de ruta contra DB).
        d = agregar(self._filas_mixtas(), DEFAULT_MODELO)
        assert "Estudio" in d["resumen"]["por_beneficiario"]
        sin_estudio = excluir_dueno(d, "Estudio")
        assert "Estudio" not in sin_estudio["resumen"]["por_beneficiario"]
        assert all("Estudio" not in m["por_beneficiario"] for m in sin_estudio["por_mes"])
        assert all("Estudio" not in x["por_beneficiario"] for x in sin_estudio["por_dia"])

    def test_saca_la_fila_de_por_dueno_y_de_beneficiarios(self):
        d = agregar(self._filas_mixtas(), DEFAULT_MODELO)
        d["beneficiarios"] = ["Pablo", "Rental", "Tincho", "Estudio"]
        sin_estudio = excluir_dueno(d, "Estudio")
        assert {x["dueno"] for x in sin_estudio["por_dueno"]} == {"Pablo", "Rental"}
        assert "Estudio" not in sin_estudio["beneficiarios"]
        assert sin_estudio["beneficiarios"] == ["Pablo", "Rental", "Tincho"]

    def test_el_pedido_mixto_conserva_la_parte_de_pablo(self):
        # El mismo pedido #501 aportó a Pablo Y a Estudio: excluir Estudio no
        # debe tocar la fila de Pablo (su propia atribución en ESE pedido).
        d = agregar(self._filas_mixtas(), DEFAULT_MODELO)
        sin_estudio = excluir_dueno(d, "Estudio")
        pablo = next(x for x in sin_estudio["por_dueno"] if x["dueno"] == "Pablo")
        assert pablo["monto_generado"] == 60000
        assert pablo["pedidos_detalle"][0]["monto"] == 60000

    def test_ajusta_por_mes_y_por_dia_con_el_detalle_del_pedido(self):
        d = agregar(self._filas_mixtas(), DEFAULT_MODELO)
        sin_estudio = excluir_dueno(d, "Estudio")
        meses = {m["mes"]: m["total"] for m in sin_estudio["por_mes"]}
        dias = {x["dia"]: x["total"] for x in sin_estudio["por_dia"]}
        # Junio tenía 60k (Pablo) + 40k (Estudio) = 100k; sin Estudio, 60k.
        assert meses["2026-06"] == 60000
        assert meses["2026-07"] == 100000
        assert dias["2026-06-03"] == 60000
        assert dias["2026-07-10"] == 100000

    def test_resumen_pedidos_no_se_ajusta_a_proposito(self):
        # "cuántos alquileres se cobraron" es un hecho del negocio, no de
        # atribución por dueño — el pedido mixto sigue contando 1 vez.
        d = agregar(self._filas_mixtas(), DEFAULT_MODELO)
        sin_estudio = excluir_dueno(d, "Estudio")
        assert sin_estudio["resumen"]["pedidos"] == d["resumen"]["pedidos"] == 2

    def test_no_op_si_el_dueno_no_generó_nada(self):
        filas_sin_estudio = [
            {"fecha": "2026-06-03", "pedido_id": 1, "dueno": "Rental",
             "equipo": "Canon R5", "monto": 100000},
        ]
        d = agregar(filas_sin_estudio, DEFAULT_MODELO)
        assert excluir_dueno(d, "Estudio") == d

    def test_degrada_sin_explotar_sin_pedidos_detalle(self):
        # Snapshot viejo (antes de 2026-07-04): `pedidos_detalle` puede faltar.
        # `total` se ajusta igual (viene de monto_generado); por_mes/por_dia
        # quedan sin tocar para ese dueño — no revienta.
        d = agregar(self._filas_mixtas(), DEFAULT_MODELO)
        for fila in d["por_dueno"]:
            fila.pop("pedidos_detalle", None)
        sin_estudio = excluir_dueno(d, "Estudio")
        assert sin_estudio["resumen"]["total"] == 160000
        assert {m["mes"]: m["total"] for m in sin_estudio["por_mes"]} == {
            "2026-06": 100000,  # sin el detalle no se puede aislar — queda el bruto
            "2026-07": 100000,
        }


class TestCierresPuros:
    """Helpers puros de cierres.py (#721): no tocan DB."""

    def test_validar_mes_acepta_formato(self):
        from reportes.cierres import validar_mes

        validar_mes("2026-06")  # no lanza

    @pytest.mark.parametrize("malo", ["2026-13", "2026-00", "2026-6", "junio", "2026/06", ""])
    def test_validar_mes_rechaza(self, malo):
        from reportes.cierres import validar_mes

        with pytest.raises(ValueError):
            validar_mes(malo)

    def test_rango_mes(self):
        from reportes.cierres import rango_mes

        assert rango_mes("2026-06") == ("2026-06-01", "2026-06-30")
        assert rango_mes("2026-02") == ("2026-02-01", "2026-02-28")  # no bisiesto
        assert rango_mes("2024-02") == ("2024-02-01", "2024-02-29")  # bisiesto
        assert rango_mes("2026-12") == ("2026-12-01", "2026-12-31")

    def test_mes_de_rango_detecta_mes_calendario(self):
        from reportes.cierres import mes_de_rango

        assert mes_de_rango("2026-06-01", "2026-06-30") == "2026-06"
        assert mes_de_rango("2026-02-01", "2026-02-28") == "2026-02"

    def test_mes_de_rango_none_si_no_es_mes_exacto(self):
        from reportes.cierres import mes_de_rango

        assert mes_de_rango("2026-01-01", "2026-12-31") is None  # año entero
        assert mes_de_rango("2026-06-01", "2026-06-15") is None  # medio mes
        assert mes_de_rango("2026-06-02", "2026-06-30") is None  # no arranca el 1
        assert mes_de_rango("2026-06-01", "2026-07-31") is None  # dos meses

    def test_meses_en_rango(self):
        from reportes.cierres import _meses_en_rango

        assert _meses_en_rango("2026-01-01", "2026-12-31") == [
            f"2026-{m:02d}" for m in range(1, 13)
        ]
        assert _meses_en_rango("2026-06-01", "2026-06-30") == ["2026-06"]
        assert _meses_en_rango("2026-11-15", "2027-02-10") == [
            "2026-11", "2026-12", "2027-01", "2027-02",
        ]  # cruza año


class TestCombinarMeses:
    """`combinar_meses` (#1209): junta N reportes por-mes (foto congelada o en
    vivo, le da igual) en un solo reporte multi-mes. Sumar es seguro porque un
    pedido pertenece a un único mes de saldado — nunca se solapan."""

    def _mes(self, mes: str, pablo_total: int, pablo_benef: int, rental_benef: int):
        """Un reporte de un solo mes con la forma de `liquidar`, con un único
        pedido de Pablo repartido según se indique."""
        return {
            "resumen": {
                "total": pablo_total,
                "pedidos": 1,
                "por_beneficiario": {"Pablo": pablo_benef, "Rental": rental_benef},
            },
            "por_mes": [
                {
                    "mes": mes,
                    "total": pablo_total,
                    "por_beneficiario": {"Pablo": pablo_benef, "Rental": rental_benef},
                }
            ],
            "por_dia": [{"dia": f"{mes}-10", "total": pablo_total,
                         "por_beneficiario": {"Pablo": pablo_benef, "Rental": rental_benef}}],
            "por_dueno": [
                {
                    "dueno": "Pablo",
                    "monto_generado": pablo_total,
                    "pedidos": 1,
                    "reparto": {"Pablo": pablo_benef, "Rental": rental_benef},
                    "equipos": [{"equipo": "Sony FX3", "monto": pablo_total, "veces": 1}],
                    "pedidos_detalle": [
                        {"pedido_id": int(mes.replace("-", "")), "numero_pedido": 900,
                         "cliente": "Cliente de prueba", "fecha": f"{mes}-10",
                         "monto": pablo_total},
                    ],
                }
            ],
            "modelo": {"Pablo": {"Pablo": 100}},
            "beneficiarios": ["Pablo", "Rental"],
        }

    def test_suma_resumen_sin_duplicar(self):
        junio = self._mes("2026-06", 100000, 50000, 50000)  # foto vieja (50/50)
        julio = self._mes("2026-07", 40000, 40000, 0)  # en vivo, modelo nuevo (100% Pablo)
        d = combinar_meses([junio, julio])
        assert d["resumen"]["total"] == 140000
        assert d["resumen"]["pedidos"] == 2
        assert d["resumen"]["por_beneficiario"] == {"Pablo": 90000, "Rental": 50000}

    def test_por_mes_conserva_cada_fuente_por_separado(self):
        junio = self._mes("2026-06", 100000, 50000, 50000)
        julio = self._mes("2026-07", 40000, 40000, 0)
        d = combinar_meses([junio, julio])
        por_mes = {m["mes"]: m for m in d["por_mes"]}
        assert por_mes["2026-06"]["por_beneficiario"]["Pablo"] == 50000  # foto intacta
        assert por_mes["2026-07"]["por_beneficiario"]["Pablo"] == 40000  # en vivo intacto

    def test_por_dueno_acumula_equipos_y_veces(self):
        junio = self._mes("2026-06", 100000, 50000, 50000)
        julio = self._mes("2026-07", 40000, 40000, 0)
        d = combinar_meses([junio, julio])
        pablo = {x["dueno"]: x for x in d["por_dueno"]}["Pablo"]
        assert pablo["monto_generado"] == 140000
        assert pablo["pedidos"] == 2
        assert pablo["equipos"][0]["equipo"] == "Sony FX3"
        assert pablo["equipos"][0]["monto"] == 140000
        assert pablo["equipos"][0]["veces"] == 2

    def test_por_dueno_concatena_pedidos_detalle(self):
        # Un pedido pertenece a un único mes de saldado → concatenar las listas
        # de `pedidos_detalle` de cada mes es seguro, no hay dupes (2026-07-04).
        junio = self._mes("2026-06", 100000, 50000, 50000)
        julio = self._mes("2026-07", 40000, 40000, 0)
        d = combinar_meses([junio, julio])
        pablo = {x["dueno"]: x for x in d["por_dueno"]}["Pablo"]
        assert len(pablo["pedidos_detalle"]) == 2
        assert {p["fecha"] for p in pablo["pedidos_detalle"]} == {"2026-06-10", "2026-07-10"}
        # Ordenado por monto descendente, igual que `equipos`.
        assert pablo["pedidos_detalle"][0]["monto"] == 100000

    def test_beneficiarios_es_la_union_en_orden_de_aparicion(self):
        junio = self._mes("2026-06", 100000, 50000, 50000)
        junio["beneficiarios"] = ["Pablo", "Rental"]
        julio = self._mes("2026-07", 40000, 40000, 0)
        julio["beneficiarios"] = ["Pablo", "Rental", "Tincho"]
        d = combinar_meses([junio, julio])
        assert d["beneficiarios"] == ["Pablo", "Rental", "Tincho"]

    def test_lista_vacia(self):
        d = combinar_meses([])
        assert d["resumen"]["total"] == 0
        assert d["resumen"]["pedidos"] == 0
        assert d["por_mes"] == [] and d["por_dia"] == [] and d["por_dueno"] == []
        assert d["beneficiarios"] == []
