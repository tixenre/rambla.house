"""Cierres de liquidación (#721) contra Postgres REAL.

Ejerce lo que los tests puros no cubren: que cerrar un mes CONGELA la foto (cambiar
el modelo o editar un pedido después no altera el mes cerrado), que el reporte sirve
la foto en vez de recalcular, que reabrir vuelve a vivo, y que la reconciliación caza
un pedido editado dentro de un mes cerrado.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`): se saltea salvo
`RESERVAS_DB_TEST=1` + `DATABASE_URL` a una base con 'test' en el nombre. Trabaja
sobre ids altos (>= 9_400_000) y limpia al terminar.

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_reportes_cierres_db.py -v -m integration
"""
import json
import os
import threading
from urllib.parse import urlparse

import pytest

_OPT_IN = os.getenv("RESERVAS_DB_TEST") == "1"
_DB_URL = os.getenv("DATABASE_URL", "")
_DB_NAME = urlparse(_DB_URL).path.lstrip("/") if _DB_URL else ""


def _looks_like_test_db() -> bool:
    return bool(_DB_NAME) and "test" in _DB_NAME.lower()


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _OPT_IN,
        reason="opt-in: setear RESERVAS_DB_TEST=1 + DATABASE_URL a una base de prueba",
    ),
    pytest.mark.skipif(
        _OPT_IN and not _looks_like_test_db(),
        reason=f"DATABASE_URL ({_DB_NAME!r}) no parece base de test — abortado por seguridad",
    ),
]

E_PABLO, E_RENTAL = 9_400_001, 9_400_002
P_JUNIO, P_EDIT = 9_400_101, 9_400_102
ALL_EQ = (E_PABLO, E_RENTAL)
ALL_PED = (P_JUNIO, P_EDIT)
MES = "2026-06"


def _limpiar(conn):
    conn.execute("DELETE FROM liquidacion_cierres WHERE mes IN ('2026-06','2026-07')")
    conn.execute("DELETE FROM alquiler_pagos WHERE pedido_id IN %s" % (ALL_PED,))
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id IN %s" % (ALL_PED,))
    conn.execute("DELETE FROM alquileres WHERE id IN %s" % (ALL_PED,))
    conn.execute("DELETE FROM equipos WHERE id IN %s" % (ALL_EQ,))


def _modelo(conn, modelo: dict):
    conn.execute(
        """INSERT INTO app_settings (key, value, updated_by)
           VALUES ('comisiones_modelo', %s, 'test')
           ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
        (json.dumps(modelo),),
    )


@pytest.fixture
def setup():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s,%s,%s,%s)",
            (E_PABLO, "Equipo Pablo", 5, "Pablo"),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s,%s,%s,%s)",
            (E_RENTAL, "Equipo Rental", 5, "Rental"),
        )
        # P_JUNIO: 100k de Pablo, alquiler y saldo en junio → cuenta para junio
        # (fecha_desde dentro del clean start, ver liquidacion.LIQUIDACION_INICIO).
        conn.execute(
            """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, monto_total, monto_pagado)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (P_JUNIO, "Cliente", "finalizado", "2026-06-05T08:00:00", 100000, 100000),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal) VALUES (%s,%s,%s,%s)",
            (P_JUNIO, E_PABLO, 1, 100000),
        )
        conn.execute(
            "INSERT INTO alquiler_pagos (pedido_id, monto, concepto, fecha) VALUES (%s,%s,%s,%s)",
            (P_JUNIO, 100000, "pago", "2026-06-15T10:00:00"),
        )
        # Modelo default conocido.
        _modelo(conn, {"Pablo": {"Pablo": 50, "Rental": 45, "Tincho": 5}, "Rental": {"Rental": 100}})
        conn.commit()
    finally:
        conn.close()

    yield

    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute("DELETE FROM app_settings WHERE key = 'comisiones_modelo'")
        conn.commit()
    finally:
        conn.close()


def _conn():
    from database import get_db

    return get_db()


def test_cerrar_congela_frente_a_cambio_de_modelo(setup):
    from reportes.cierres import cerrar_mes
    from reportes.liquidacion import liquidar

    conn = _conn()
    try:
        # En vivo, junio reparte Pablo 50/45/5 sobre 100k.
        vivo = liquidar(conn, "2026-06-01", "2026-06-30")
        assert vivo["resumen"]["por_beneficiario"]["Pablo"] == 50000

        # Cerramos junio → foto inmutable.
        snap = cerrar_mes(conn, MES, "tincho@test")
        assert snap["cerrado"] is True
        assert snap["cerrado_por"] == "tincho@test"
        assert snap["resumen"]["por_beneficiario"]["Pablo"] == 50000

        # Cambiamos el modelo: ahora Pablo se lleva todo.
        _modelo(conn, {"Pablo": {"Pablo": 100}, "Rental": {"Rental": 100}})
        conn.commit()

        # El mes ABIERTO recalcularía (Pablo 100k); el CERRADO sigue 50k.
        from reportes.cierres import snapshot_de

        frozen = snapshot_de(conn, MES)
        assert frozen["resumen"]["por_beneficiario"]["Pablo"] == 50000, "la foto debe quedar firme"
        # Y un mes distinto (julio, abierto) usa el modelo nuevo.
        julio_vivo = liquidar(conn, "2026-07-01", "2026-07-31")
        assert julio_vivo["resumen"]["total"] == 0  # no hay pedidos en julio
    finally:
        conn.close()


def test_reabrir_vuelve_a_vivo(setup):
    from reportes.cierres import cerrar_mes, cierre_de, reabrir_mes, snapshot_de

    conn = _conn()
    try:
        cerrar_mes(conn, MES, "x")
        assert cierre_de(conn, MES) is not None
        assert reabrir_mes(conn, MES) is True
        assert cierre_de(conn, MES) is None
        assert snapshot_de(conn, MES) is None
        # Reabrir un mes ya abierto devuelve False (no había nada que borrar).
        assert reabrir_mes(conn, MES) is False
    finally:
        conn.close()


def test_reconciliacion_caza_pedido_editado_en_mes_cerrado(setup):
    from reportes.cierres import cerrar_mes
    from reportes.reconciliacion import reconciliar

    conn = _conn()
    try:
        cerrar_mes(conn, MES, "x")
        # Reconciliación limpia recién cerrado.
        rec = reconciliar(conn)
        assert rec["mes_cerrado_desactualizado"]["cantidad"] == 0, rec["mes_cerrado_desactualizado"]

        # Editamos el pedido saldado en junio DESPUÉS del cierre (bump updated_at).
        conn.execute(
            "UPDATE alquileres SET updated_at = CURRENT_TIMESTAMP + INTERVAL '1 hour' WHERE id = %s",
            (P_JUNIO,),
        )
        conn.commit()

        rec2 = reconciliar(conn)
        stale = rec2["mes_cerrado_desactualizado"]
        assert P_JUNIO in stale["ids"], stale
        assert MES in stale["meses"], stale
        assert rec2["ok"] is False
    finally:
        conn.close()


def test_lock_serializa_cerrar_mes_concurrente(setup):
    """Fase 3 (#1184): verifica que `_lock_mes` (pg_advisory_xact_lock) realmente
    serializa contra Postgres real — no solo en teoría. Una conexión toma el lock
    de MES y lo retiene; una segunda conexión que intenta `cerrar_mes` del MISMO
    mes debe quedar bloqueada hasta que la primera libere (commit), en vez de
    correr en paralelo."""
    import time

    from database import get_db
    from reportes.cierres import _lock_mes, cerrar_mes

    orden: list[str] = []
    lock_tomado = threading.Event()
    liberar_lock = threading.Event()
    errores: dict[str, Exception] = {}

    def _tomar_lock_y_esperar():
        conn = get_db()
        try:
            _lock_mes(conn, MES)
            orden.append("A_tomo_lock")
            lock_tomado.set()
            liberar_lock.wait(timeout=5)
            conn.commit()  # libera el advisory lock xact-scoped
            orden.append("A_libero_lock")
        except Exception as e:  # noqa: BLE001 — se re-lanza al hilo principal
            errores["A"] = e
        finally:
            conn.close()

    def _cerrar_mes_bloqueado():
        lock_tomado.wait(timeout=5)
        conn = get_db()
        try:
            cerrar_mes(conn, MES, "b")
            orden.append("B_cerro_mes")
        except Exception as e:  # noqa: BLE001
            errores["B"] = e
        finally:
            conn.close()

    ta = threading.Thread(target=_tomar_lock_y_esperar)
    tb = threading.Thread(target=_cerrar_mes_bloqueado)
    ta.start()
    lock_tomado.wait(timeout=5)
    tb.start()
    time.sleep(0.3)  # B debería seguir esperando el lock en este punto.
    assert "B_cerro_mes" not in orden, "B no debería poder cerrar_mes mientras A retiene el lock"
    liberar_lock.set()
    ta.join(timeout=5)
    tb.join(timeout=5)

    assert not ta.is_alive() and not tb.is_alive(), "deadlock: algún hilo no terminó"
    assert not errores, f"errores en los hilos: {errores}"
    assert orden == ["A_tomo_lock", "A_libero_lock", "B_cerro_mes"], orden


def test_liquidar_rango_multimes_respeta_mes_cerrado(setup):
    """El bug real (#1209): la vista "Mes a mes"/el total anual recalculaba TODO
    el rango en vivo, ignorando que junio ya estaba cerrado — la fila de junio y
    el total anual mostraban el modelo de comisiones NUEVO, mientras la tarjeta
    del mes individual (que sí usa `snapshot_de`) mostraba la foto vieja. Este
    test arma exactamente ese escenario (cerrar junio, cambiar el modelo, sumar
    un pedido en julio abierto) y verifica que TODAS las superficies —la
    tarjeta de un mes, la fila de junio dentro del año, el resumen anual, y el
    detalle por dueño— coincidan: junio con la foto vieja, julio con el modelo
    nuevo, y el total la suma correcta de ambos (no todo recalculado con el
    modelo nuevo)."""
    from reportes.cierres import cerrar_mes, liquidar_rango, mes_de_rango
    from routes.reportes import _data_liquidacion

    conn = _conn()
    P_JULIO = 9_400_103
    try:
        # Cerramos junio con el modelo vigente (Pablo 50/45/5): P_JUNIO (100k de
        # Pablo) → Pablo se queda con 50k, congelado en la foto.
        cerrar_mes(conn, MES, "tincho@test")

        # Pedido nuevo, de Pablo, saldado en JULIO (mes abierto) — 40k.
        conn.execute(
            """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, monto_total, monto_pagado)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (P_JULIO, "Cliente", "finalizado", "2026-07-05T08:00:00", 40000, 40000),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal) VALUES (%s,%s,%s,%s)",
            (P_JULIO, E_PABLO, 1, 40000),
        )
        conn.execute(
            "INSERT INTO alquiler_pagos (pedido_id, monto, concepto, fecha) VALUES (%s,%s,%s,%s)",
            (P_JULIO, 40000, "pago", "2026-07-10T10:00:00"),
        )
        conn.commit()

        # Cambiamos el modelo DESPUÉS de cerrar junio: ahora Pablo se lo lleva todo.
        _modelo(conn, {"Pablo": {"Pablo": 100}, "Rental": {"Rental": 100}})
        conn.commit()

        anio_rango = liquidar_rango(conn, "2026-01-01", "2026-12-31")
        assert mes_de_rango("2026-01-01", "2026-12-31") is None  # confirma el camino multi-mes

        por_mes = {m["mes"]: m for m in anio_rango["por_mes"]}
        # Junio (CERRADO): sigue la foto vieja — Pablo 50k, NO 100k (el bug real
        # habría mostrado 100k acá, recalculando con el modelo nuevo).
        assert por_mes["2026-06"]["por_beneficiario"]["Pablo"] == 50000, por_mes["2026-06"]
        # Julio (ABIERTO): usa el modelo nuevo — Pablo se lleva el 100% de sus 40k.
        assert por_mes["2026-07"]["por_beneficiario"]["Pablo"] == 40000, por_mes["2026-07"]

        # El resumen anual es la SUMA de ambas fuentes (50k + 40k = 90k), no el
        # resultado de recalcular los 140k enteros con el modelo nuevo (140k).
        assert anio_rango["resumen"]["por_beneficiario"]["Pablo"] == 90000, anio_rango["resumen"]
        assert anio_rango["resumen"]["total"] == 140000, anio_rango["resumen"]  # 100k + 40k

        # El detalle por dueño combinado también es consistente con lo de arriba.
        pablo_dueno = {d["dueno"]: d for d in anio_rango["por_dueno"]}["Pablo"]
        assert pablo_dueno["monto_generado"] == 140000, pablo_dueno
        assert pablo_dueno["reparto"]["Pablo"] == 90000, pablo_dueno
        assert pablo_dueno["pedidos"] == 2, pablo_dueno

        # La tarjeta de UN mes puntual (junio) sigue mostrando la misma foto —
        # ninguna superficie de la app puede divergir para el mismo mes cerrado.
        mes_individual = _data_liquidacion(conn, "2026-06-01", "2026-06-30")
        assert mes_individual["resumen"]["por_beneficiario"]["Pablo"] == 50000
        assert mes_individual["cerrado"] is True

        # Y la fuente única del route (JSON/CSV/PDF/mail) para el rango anual da
        # exactamente lo mismo que `liquidar_rango` — no hay un segundo camino.
        anio_route = _data_liquidacion(conn, "2026-01-01", "2026-12-31")
        assert anio_route["resumen"] == anio_rango["resumen"]
    finally:
        conn.execute("DELETE FROM alquiler_pagos WHERE pedido_id = %s", (P_JULIO,))
        conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (P_JULIO,))
        conn.execute("DELETE FROM alquileres WHERE id = %s", (P_JULIO,))
        conn.commit()
        conn.close()
