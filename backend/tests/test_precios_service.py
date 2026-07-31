"""Tests del servicio canónico de precios — services/precios.py.

Fuente de verdad de los totales del pedido. Estos tests aseguran:
- La fórmula de jornadas no trunca (#502).
- Los descuentos se aplican como max(cliente, jornadas) — no acumulativos.
- En empate gana cliente (alineado con front cart-total.ts).
- IVA solo para Responsable Inscripto.
- `neto` se persiste en `alquileres.monto_total`; el IVA es derivado.
"""

from datetime import datetime

import pytest

from services.precios import (
    IVA_PCT,
    PERFIL_RI,
    calcular_total,
    es_responsable_inscripto,
    jornadas_periodo,
)


pytestmark = pytest.mark.unit


# ── jornadas_periodo ─────────────────────────────────────────────────────


class TestJornadasPeriodo:
    def test_un_dia_exacto(self):
        d0 = datetime(2026, 6, 1, 10, 0)
        d1 = datetime(2026, 6, 2, 10, 0)
        assert jornadas_periodo(d0, d1) == 1

    def test_un_dia_y_medio_redondea_arriba(self):
        # 36 horas → 2 jornadas (ceil)
        d0 = datetime(2026, 6, 1, 10, 0)
        d1 = datetime(2026, 6, 2, 22, 0)
        assert jornadas_periodo(d0, d1) == 2

    def test_dos_dias_exactos(self):
        d0 = datetime(2026, 6, 1, 10, 0)
        d1 = datetime(2026, 6, 3, 10, 0)
        assert jornadas_periodo(d0, d1) == 2

    def test_retiro_10am_devolucion_14pm_dia_siguiente_es_2_jornadas(self):
        # Regresión #502: el cálculo viejo (.days) daba 1; el correcto (ceil/24h) da 2.
        d0 = datetime(2026, 6, 1, 10, 0)
        d1 = datetime(2026, 6, 2, 14, 0)  # 28 horas
        assert jornadas_periodo(d0, d1) == 2

    def test_fechas_nulas_devuelven_uno(self):
        assert jornadas_periodo(None, None) == 1
        assert jornadas_periodo(datetime(2026, 6, 1), None) == 1
        assert jornadas_periodo(None, datetime(2026, 6, 2)) == 1

    def test_fechas_invertidas_devuelven_uno(self):
        d0 = datetime(2026, 6, 2)
        d1 = datetime(2026, 6, 1)
        assert jornadas_periodo(d0, d1) == 1

    def test_misma_fecha_devuelve_uno(self):
        d = datetime(2026, 6, 1, 10, 0)
        assert jornadas_periodo(d, d) == 1


# ── es_responsable_inscripto ─────────────────────────────────────────────


class TestEsResponsableInscripto:
    def test_ri(self):
        assert es_responsable_inscripto("responsable_inscripto") is True

    def test_consumidor_final(self):
        assert es_responsable_inscripto("consumidor_final") is False

    def test_monotributo_no_es_ri(self):
        # Monotributo no factura IVA discriminado en este negocio.
        assert es_responsable_inscripto("monotributo") is False

    def test_none_no_es_ri(self):
        assert es_responsable_inscripto(None) is False

    def test_vacio_no_es_ri(self):
        assert es_responsable_inscripto("") is False


# ── calcular_total ───────────────────────────────────────────────────────


class TestCalcularTotal:
    def test_pedido_simple_sin_descuento_sin_iva(self):
        # 2 items × 1000/jornada × 3 jornadas = 6000
        r = calcular_total(
            items=[{"equipo_id": 1, "cantidad": 2, "precio_jornada": 1000}],
            jornadas=3,
        )
        assert r["bruto"] == 6000
        assert r["descuento_pct"] == 0
        assert r["descuento_monto"] == 0
        assert r["neto"] == 6000
        assert r["con_iva"] is False
        assert r["iva_monto"] == 0
        assert r["total_final"] == 6000

    def test_pedido_con_descuento_cliente(self):
        # 10000 - 10% = 9000
        r = calcular_total(
            items=[{"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000}],
            jornadas=1,
            descuento_cliente_pct=10.0,
        )
        assert r["bruto"] == 10000
        assert r["descuento_pct"] == 10.0
        assert r["descuento_monto"] == 1000
        assert r["neto"] == 9000

    def test_descuento_jornadas_gana_si_es_mayor(self):
        r = calcular_total(
            items=[{"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000}],
            jornadas=7,
            descuento_cliente_pct=5.0,
            descuento_jornadas_pct=15.0,
        )
        # bruto = 10000 * 7 = 70000; 15% off = 59500
        assert r["descuento_pct"] == 15.0
        assert r["neto"] == 59500

    def test_descuento_cliente_gana_si_es_mayor(self):
        r = calcular_total(
            items=[{"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000}],
            jornadas=2,
            descuento_cliente_pct=20.0,
            descuento_jornadas_pct=5.0,
        )
        # bruto = 20000; 20% off = 16000
        assert r["descuento_pct"] == 20.0
        assert r["neto"] == 16000

    def test_descuento_empate_no_se_acumula(self):
        # Si fueran acumulativos sería 20%, pero el modelo dice max → 10%.
        r = calcular_total(
            items=[{"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000}],
            jornadas=1,
            descuento_cliente_pct=10.0,
            descuento_jornadas_pct=10.0,
        )
        assert r["descuento_pct"] == 10.0
        assert r["neto"] == 9000

    def test_responsable_inscripto_suma_iva(self):
        # 10000 neto + 21% IVA = 12100
        r = calcular_total(
            items=[{"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000}],
            jornadas=1,
            perfil_impuestos=PERFIL_RI,
        )
        assert r["con_iva"] is True
        assert r["iva_pct"] == IVA_PCT
        assert r["iva_monto"] == 2100
        assert r["neto"] == 10000
        assert r["total_final"] == 12100

    def test_consumidor_final_no_suma_iva(self):
        r = calcular_total(
            items=[{"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000}],
            jornadas=1,
            perfil_impuestos="consumidor_final",
        )
        assert r["con_iva"] is False
        assert r["iva_monto"] == 0
        assert r["total_final"] == 10000

    def test_ri_con_descuento_iva_sobre_neto(self):
        # Regresión del lado #502: el IVA debe calcularse SOBRE el neto
        # (con descuento aplicado), no sobre el bruto.
        r = calcular_total(
            items=[{"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000}],
            jornadas=1,
            descuento_cliente_pct=10.0,
            perfil_impuestos=PERFIL_RI,
        )
        # bruto 10000, neto 9000, IVA = round(9000 * 0.21) = 1890
        assert r["neto"] == 9000
        assert r["iva_monto"] == 1890
        assert r["total_final"] == 10890

    def test_items_vacios(self):
        r = calcular_total(items=[], jornadas=3, perfil_impuestos=PERFIL_RI)
        assert r["bruto"] == 0
        assert r["neto"] == 0
        assert r["iva_monto"] == 0
        assert r["total_final"] == 0

    def test_jornadas_cero_se_clampa_a_uno(self):
        # Defensivo: si llega 0 (no debería), tratamos como 1.
        r = calcular_total(
            items=[{"equipo_id": 1, "cantidad": 1, "precio_jornada": 1000}],
            jornadas=0,
        )
        assert r["bruto"] == 1000

    def test_redondeo_es_consistente(self):
        # Caso real de test_pricing: 231300 con 15% → 196605 (no 196604.5)
        r = calcular_total(
            items=[{"equipo_id": 1, "cantidad": 1, "precio_jornada": 231300}],
            jornadas=1,
            descuento_cliente_pct=15.0,
        )
        assert r["neto"] == 196605


# ── cobro_modo: líneas personalizadas fijo vs jornada (#805) ──────────────


class TestCobroModo:
    def test_bruto_linea_jornada_multiplica_por_jornadas(self):
        from services.precios import bruto_linea
        it = {"cantidad": 2, "precio_jornada": 5000, "cobro_modo": "jornada"}
        assert bruto_linea(it, jornadas=3) == 2 * 5000 * 3

    def test_bruto_linea_fijo_ignora_jornadas(self):
        from services.precios import bruto_linea
        it = {"cantidad": 2, "precio_jornada": 5000, "cobro_modo": "fijo"}
        # 'fijo' = monto único: precio × cantidad, sin × jornadas.
        assert bruto_linea(it, jornadas=3) == 2 * 5000

    def test_bruto_linea_default_es_jornada(self):
        from services.precios import bruto_linea
        it = {"cantidad": 1, "precio_jornada": 1000}  # sin cobro_modo
        assert bruto_linea(it, jornadas=4) == 4000

    def test_total_mezcla_equipo_y_linea_fija(self):
        # Equipo: 10.000 × 1 × 3 jornadas = 30.000.
        # Línea fija (flete): 20.000 × 1, NO × jornadas = 20.000.
        # Bruto = 50.000.
        r = calcular_total(
            items=[
                {"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000, "cobro_modo": "jornada"},
                {"equipo_id": None, "cantidad": 1, "precio_jornada": 20000, "cobro_modo": "fijo"},
            ],
            jornadas=3,
        )
        assert r["bruto"] == 50000

    def test_descuento_aplica_a_toda_la_mezcla(self):
        # El dueño quiere las líneas libres tratadas como cualquier equipo para
        # descuento: 50.000 bruto − 10% = 45.000 neto.
        r = calcular_total(
            items=[
                {"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000, "cobro_modo": "jornada"},
                {"equipo_id": None, "cantidad": 1, "precio_jornada": 20000, "cobro_modo": "fijo"},
            ],
            jornadas=3,
            descuento_cliente_pct=10.0,
        )
        assert r["neto"] == 45000


# ── Combos no acumulables con el descuento global (Fase C-3, #1219) ───────


class TestCombosNoAcumulables:
    def test_combo_no_recibe_el_descuento_global(self):
        # Equipo simple: 10.000 × 1 jornada = 10.000 (descontable).
        # Combo: 20.000 × 1 jornada = 20.000 (YA trae su descuento de
        # componente horneado en el precio — no se le vuelve a aplicar el
        # 10% de cliente encima).
        # bruto = 30.000; descuento = 10% de 10.000 (solo el simple) = 1.000.
        r = calcular_total(
            items=[
                {"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000, "es_combo": False},
                {"equipo_id": 2, "cantidad": 1, "precio_jornada": 20000, "es_combo": True},
            ],
            jornadas=1,
            descuento_cliente_pct=10.0,
        )
        assert r["bruto"] == 30000
        assert r["descuento_monto"] == 1000
        assert r["neto"] == 29000

    def test_es_combo_ausente_se_trata_como_no_combo(self):
        # Sin `es_combo` en el dict (default de ItemPrecio, total=False):
        # comportamiento IDÉNTICO a antes de C-3 — participa del descuento.
        r = calcular_total(
            items=[{"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000}],
            jornadas=1,
            descuento_cliente_pct=10.0,
        )
        assert r["neto"] == 9000

    def test_todo_combos_no_hay_descuento_aunque_haya_pct(self):
        r = calcular_total(
            items=[{"equipo_id": 2, "cantidad": 1, "precio_jornada": 20000, "es_combo": True}],
            jornadas=1,
            descuento_cliente_pct=50.0,
        )
        assert r["descuento_monto"] == 0
        assert r["neto"] == 20000

    def test_override_manual_monto_se_capea_al_bruto_descontable_no_al_total(self):
        # Bruto descontable (solo el simple) = 10.000; combo = 20.000, exento.
        # Un override manual de $50.000 no puede comerse el combo — se capea
        # a los 10.000 descontables.
        r = calcular_total(
            items=[
                {"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000, "es_combo": False},
                {"equipo_id": 2, "cantidad": 1, "precio_jornada": 20000, "es_combo": True},
            ],
            jornadas=1,
            descuento_manual_tipo="monto",
            descuento_manual_monto=50000,
        )
        assert r["descuento_monto"] == 10000  # capeado, no 30.000
        assert r["neto"] == 20000  # el combo queda intacto


class TestTurnoEmbebidoNoAcumulable:
    """#1308 rediseño "turno como ítem", Fase 3.1 — una línea con
    `turno_estudio_id` recibe el MISMO aislamiento que un combo (mismo bloque
    `bruto_descontable`, ver el docstring de `calcular_total`). Mismos 4 casos
    que `TestCombosNoAcumulables`, sustituyendo `es_combo` por
    `turno_estudio_id` (un id real de `alquiler_turnos_estudio`, no un bool)."""

    def test_turno_no_recibe_el_descuento_global(self):
        # Equipo simple: 10.000 × 1 jornada = 10.000 (descontable).
        # Turno embebido: 20.000 (ya resolvió su propio precio al insertarse
        # — no se le vuelve a aplicar el 10% de cliente encima).
        # bruto = 30.000; descuento = 10% de 10.000 (solo el simple) = 1.000.
        r = calcular_total(
            items=[
                {"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000, "turno_estudio_id": None},
                {"equipo_id": 2, "cantidad": 1, "precio_jornada": 20000, "turno_estudio_id": 501},
            ],
            jornadas=1,
            descuento_cliente_pct=10.0,
        )
        assert r["bruto"] == 30000
        assert r["descuento_monto"] == 1000
        assert r["neto"] == 29000

    def test_turno_estudio_id_ausente_se_trata_como_no_turno(self):
        # Sin `turno_estudio_id` en el dict: comportamiento IDÉNTICO a antes
        # de la Fase 3 — participa del descuento (el 100% de los callers
        # existentes antes de #1308).
        r = calcular_total(
            items=[{"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000}],
            jornadas=1,
            descuento_cliente_pct=10.0,
        )
        assert r["neto"] == 9000

    def test_todo_turnos_no_hay_descuento_aunque_haya_pct(self):
        r = calcular_total(
            items=[{"equipo_id": 2, "cantidad": 1, "precio_jornada": 20000, "turno_estudio_id": 501}],
            jornadas=1,
            descuento_cliente_pct=50.0,
        )
        assert r["descuento_monto"] == 0
        assert r["neto"] == 20000

    def test_override_manual_monto_se_capea_al_bruto_descontable_sin_turno(self):
        # Bruto descontable (solo el simple) = 10.000; turno = 20.000, exento.
        # Un override manual de $50.000 no puede comerse el turno — se capea
        # a los 10.000 descontables.
        r = calcular_total(
            items=[
                {"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000, "turno_estudio_id": None},
                {"equipo_id": 2, "cantidad": 1, "precio_jornada": 20000, "turno_estudio_id": 501},
            ],
            jornadas=1,
            descuento_manual_tipo="monto",
            descuento_manual_monto=50000,
        )
        assert r["descuento_monto"] == 10000  # capeado, no 30.000
        assert r["neto"] == 20000  # el turno queda intacto

    def test_combo_y_turno_embebido_conviven_sin_pisarse(self):
        """Un pedido puede tener a la vez un combo Y un turno embebido (ej.
        equipos + una sesión del Estudio) — ambos exentos del descuento
        global, cada uno por su propia razón, sin interferir entre sí."""
        r = calcular_total(
            items=[
                {"equipo_id": 1, "cantidad": 1, "precio_jornada": 10000, "es_combo": False},
                {"equipo_id": 2, "cantidad": 1, "precio_jornada": 15000, "es_combo": True},
                {"equipo_id": 3, "cantidad": 1, "precio_jornada": 20000, "turno_estudio_id": 501},
            ],
            jornadas=1,
            descuento_cliente_pct=10.0,
        )
        assert r["bruto"] == 45000
        assert r["descuento_monto"] == 1000  # 10% de 10.000, solo el simple
        assert r["neto"] == 44000
