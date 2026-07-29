"""Liquidación (#88) contra Postgres REAL — la parte que los tests puros no cubren.

Ejerce el SQL delicado: la window function que decide la fecha de saldado, el
prorrateo del total entre equipos, y el reparto por dueño. Más la reconciliación.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`): se saltea
salvo `RESERVAS_DB_TEST=1` + `DATABASE_URL` a una base con 'test' en el nombre.
Trabaja sobre ids altos (>= 9_300_000) y limpia al terminar.

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_reportes_liquidacion_db.py -v -m integration
"""
import os
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

# Equipos: Rental, Pablo, Tincho. Pedidos. Ids altos para no chocar con datos.
E_RENTAL, E_PABLO, E_TINCHO = 9_300_001, 9_300_002, 9_300_003
P_CRUCE, P_PARCIAL, P_MIXTO, P_LEGACY, P_SOBRE, P_PREJUNIO, P_SUBTOTAL_CERO = (
    9_300_101, 9_300_102, 9_300_103, 9_300_104, 9_300_105, 9_300_106, 9_300_107,
)
ALL_EQ = (E_RENTAL, E_PABLO, E_TINCHO)
ALL_PED = (P_CRUCE, P_PARCIAL, P_MIXTO, P_LEGACY, P_SOBRE, P_PREJUNIO, P_SUBTOTAL_CERO)


def _limpiar(conn):
    conn.execute("DELETE FROM alquiler_pagos WHERE pedido_id IN %s" % (ALL_PED,))
    conn.execute("DELETE FROM alquiler_items WHERE pedido_id IN %s" % (ALL_PED,))
    conn.execute("DELETE FROM alquileres WHERE id IN %s" % (ALL_PED,))
    conn.execute("DELETE FROM equipos WHERE id IN %s" % (ALL_EQ,))


def _equipo(conn, eid, nombre, dueno):
    conn.execute(
        "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s,%s,%s,%s)",
        (eid, nombre, 5, dueno),
    )


def _pedido(conn, pid, monto_total, items, monto_pagado=0, estado="finalizado",
            fecha_desde="2026-06-05T08:00:00"):
    # fecha_desde default DENTRO del clean start (junio 2026) → cuenta para la
    # liquidación. Los tests que prueban la exclusión pasan una fecha anterior.
    conn.execute(
        """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta,
                                   monto_total, monto_pagado)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (pid, "Cliente liquidación", estado, fecha_desde, "2026-06-06T20:00:00",
         monto_total, monto_pagado),
    )
    for equipo_id, subtotal in items:
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal) VALUES (%s,%s,%s,%s)",
            (pid, equipo_id, 1, subtotal),
        )


def _pago(conn, pid, monto, fecha, concepto="pago"):
    conn.execute(
        "INSERT INTO alquiler_pagos (pedido_id, monto, concepto, fecha) VALUES (%s,%s,%s,%s)",
        (pid, monto, concepto, fecha),
    )


@pytest.fixture
def setup():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        _equipo(conn, E_RENTAL, "Equipo Rental", "Rental")
        _equipo(conn, E_PABLO, "Equipo Pablo", "Pablo")
        _equipo(conn, E_TINCHO, "Equipo Tincho", "Tincho")

        # P_CRUCE: total 100k, seña 40k en MAYO + saldo 60k en JUNIO → saldado en junio.
        _pedido(conn, P_CRUCE, 100000, [(E_PABLO, 100000)], monto_pagado=100000)
        _pago(conn, P_CRUCE, 40000, "2026-05-20T10:00:00", "seña")
        _pago(conn, P_CRUCE, 60000, "2026-06-03T10:00:00", "saldo")

        # P_PARCIAL: total 100k, solo 40k pagado → NO saldado → no aparece.
        _pedido(conn, P_PARCIAL, 100000, [(E_RENTAL, 100000)], monto_pagado=40000)
        _pago(conn, P_PARCIAL, 40000, "2026-06-10T10:00:00", "seña")

        # P_MIXTO: total 100k, 2 equipos (Rental 60k + Pablo 40k), saldado en junio.
        _pedido(conn, P_MIXTO, 100000, [(E_RENTAL, 60000), (E_PABLO, 40000)], monto_pagado=100000)
        _pago(conn, P_MIXTO, 100000, "2026-06-15T10:00:00", "pago total")

        # P_LEGACY: marcado pagado por la columna SIN ledger → debe caer en reconciliación.
        _pedido(conn, P_LEGACY, 50000, [(E_RENTAL, 50000)], monto_pagado=50000)

        # P_SOBRE: cobrado 80k pero el total quedó en 50k (editado a la baja tras cobrar)
        # → sobrepagado, debe caer en reconciliación. Saldado en julio (mes neutral
        # para no contaminar las aserciones de junio).
        _pedido(conn, P_SOBRE, 50000, [(E_RENTAL, 50000)], monto_pagado=80000)
        _pago(conn, P_SOBRE, 80000, "2026-07-20T10:00:00", "pago")

        # P_PREJUNIO: alquiler de MAYO (antes del clean start), pagado 100% en JUNIO.
        # NO debe contar para la liquidación: el corte es por fecha del alquiler.
        _pedido(conn, P_PREJUNIO, 100000, [(E_RENTAL, 100000)], monto_pagado=100000,
                fecha_desde="2026-05-15T08:00:00")
        _pago(conn, P_PREJUNIO, 100000, "2026-06-20T10:00:00", "pago")

        conn.commit()
    finally:
        conn.close()

    yield

    conn = get_db()
    try:
        _limpiar(conn)
        conn.commit()
    finally:
        conn.close()


def _liquidar(desde, hasta):
    from database import get_db
    from reportes.liquidacion import liquidar

    conn = get_db()
    try:
        return liquidar(conn, desde, hasta)
    finally:
        conn.close()


def test_cruce_se_atribuye_al_mes_de_saldado(setup):
    # En MAYO (solo la seña entró) el pedido NO debe aparecer: todavía no estaba
    # saldado. El total de mayo no incluye los 100k de P_CRUCE.
    mayo = _liquidar("2026-05-01", "2026-05-31")
    assert mayo["resumen"]["total"] == 0, mayo["resumen"]

    # En JUNIO sí aparece completo (saldó el 3/6), repartido 50/45/5 (es de Pablo).
    junio = _liquidar("2026-06-01", "2026-06-30")
    pb = junio["resumen"]["por_beneficiario"]
    # P_CRUCE (Pablo 100k → 50/45/5) + P_MIXTO (Rental 60k→100% + Pablo 40k→50/45/5).
    # Pablo: 50000 + 20000 = 70000; Rental: 45000 + 60000 + 18000 = 123000; Tincho: 5000 + 2000 = 7000.
    assert pb["Pablo"] == 70000, pb
    assert pb["Rental"] == 123000, pb
    assert pb["Tincho"] == 7000, pb


def test_parcial_no_aparece(setup):
    junio = _liquidar("2026-06-01", "2026-06-30")
    # P_PARCIAL (40k de 100k) no está saldado → no suma. El total de junio son los
    # dos pedidos saldados (100k + 100k = 200k), no incluye el parcial NI el
    # P_PREJUNIO (alquiler de mayo, fuera del clean start) aunque saldó en junio.
    assert junio["resumen"]["total"] == 200000, junio["resumen"]


def test_clean_start_excluye_alquiler_previo_a_junio(setup):
    # P_PREJUNIO: alquiler de mayo, pagado 100% el 20/6. El corte es por fecha del
    # alquiler → NO cuenta para la liquidación de junio, pese a saldar en junio.
    junio = _liquidar("2026-06-01", "2026-06-30")
    pedidos_dia = {d["dia"]: d["total"] for d in junio["por_dia"]}
    # No hay bucket el 20/6 (solo entró P_PREJUNIO ese día, y está excluido).
    assert "2026-06-20" not in pedidos_dia, pedidos_dia
    # Y el total de junio no incluye sus 100k.
    assert junio["resumen"]["total"] == 200000, junio["resumen"]

    # Tampoco aparece reabriendo el rango a todo 2026 (el corte no depende del rango).
    anio = _liquidar("2026-01-01", "2026-12-31")
    # Solo cuentan los saldados DENTRO del clean start: junio (200k) + julio
    # (P_SOBRE 50k de total, saldó 80k pero imputa el total). P_PREJUNIO fuera.
    assert all(m["mes"] >= "2026-06" for m in anio["por_mes"]), anio["por_mes"]


def test_prorrateo_conserva_la_plata(setup):
    junio = _liquidar("2026-06-01", "2026-06-30")
    # La suma del reparto == la suma de lo generado por dueño == total.
    suma_benef = sum(junio["resumen"]["por_beneficiario"].values())
    suma_generado = sum(d["monto_generado"] for d in junio["por_dueno"])
    assert suma_benef == junio["resumen"]["total"]
    assert suma_generado == junio["resumen"]["total"]


def test_buckets_diarios(setup):
    junio = _liquidar("2026-06-01", "2026-06-30")
    dias = {d["dia"]: d["total"] for d in junio["por_dia"]}
    assert dias.get("2026-06-03") == 100000  # P_CRUCE saldó este día
    assert dias.get("2026-06-15") == 100000  # P_MIXTO


def test_veces_alquilado(setup):
    junio = _liquidar("2026-06-01", "2026-06-30")
    # En junio hay 2 pedidos saldados (P_CRUCE + P_MIXTO).
    assert junio["resumen"]["pedidos"] == 2
    duenos = {d["dueno"]: d for d in junio["por_dueno"]}
    # El equipo de Pablo salió en ambos (P_CRUCE y P_MIXTO) → 2 veces.
    pablo = duenos["Pablo"]
    fx = {e["equipo"]: e for e in pablo["equipos"]}["Equipo Pablo"]
    assert fx["veces"] == 2
    assert pablo["pedidos"] == 2


def test_pedidos_detalle_incluye_cliente_y_numero_pedido(setup):
    # `pedidos_detalle` (2026-07-04) trae el pedido con cliente/numero_pedido
    # (cae a `cliente_nombre`/`id` cuando no hay cliente registrado/numero_pedido
    # asignado, como en el fixture de este archivo) y el monto que le tocó a ESE
    # dueño para ESE pedido — no el total del pedido cuando hay 2 dueños (P_MIXTO).
    junio = _liquidar("2026-06-01", "2026-06-30")
    duenos = {d["dueno"]: d for d in junio["por_dueno"]}

    pablo_ped = {p["pedido_id"]: p for p in duenos["Pablo"]["pedidos_detalle"]}
    assert pablo_ped[P_CRUCE]["numero_pedido"] == P_CRUCE  # sin numero_pedido → cae al id
    assert pablo_ped[P_CRUCE]["cliente"] == "Cliente liquidación"
    assert pablo_ped[P_CRUCE]["monto"] == 100000
    assert pablo_ped[P_MIXTO]["monto"] == 40000  # su parte del pedido mixto, no los 100k

    rental_ped = {p["pedido_id"]: p for p in duenos["Rental"]["pedidos_detalle"]}
    assert rental_ped[P_MIXTO]["monto"] == 60000  # la parte de Rental del mismo pedido


def test_reconciliacion_caza_pagado_sin_ledger(setup):
    from database import get_db
    from reportes.reconciliacion import reconciliar

    conn = get_db()
    try:
        rec = reconciliar(conn)
    finally:
        conn.close()
    # P_LEGACY está marcado pagado por la columna pero sin ledger → debe listarse.
    assert P_LEGACY in rec["pagados_sin_ledger"]["ids"], rec["pagados_sin_ledger"]
    # P_SOBRE se cobró por encima de su total actual → sobrepagado.
    assert P_SOBRE in rec["sobrepagados"]["ids"], rec["sobrepagados"]
    assert rec["ok"] is False


def test_reconciliacion_caza_desglose_divergente_del_pedido():
    """Fase 2 (#1184): generaliza el patrón del bug #405. Si `monto_total`
    persistido NO coincide con el desglose recalculado a partir del precio de
    línea YA PERSISTIDO del ítem (vía `finanzas_flujo.pedido.desglose_de_pedido`),
    el chequeo `desglose_divergente` lo caza — sin depender de un reporte puntual
    del dueño. Aislado de la fixture `setup` compartida (equipo/pedido propios)."""
    from database import get_db, init_db
    from reportes.reconciliacion import reconciliar

    E_DIV = 9_300_901
    P_DIVERGENTE = 9_300_902

    def _limpiar_local(conn):
        conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (P_DIVERGENTE,))
        conn.execute("DELETE FROM alquileres WHERE id = %s", (P_DIVERGENTE,))
        conn.execute("DELETE FROM equipos WHERE id = %s", (E_DIV,))

    init_db()
    conn = get_db()
    try:
        _limpiar_local(conn)
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s,%s,%s,%s)",
            (E_DIV, "Equipo desglose divergente", 5, "Rental"),
        )
        # 1 ítem, 1 jornada, precio_jornada=50000, cobro_modo='jornada' → el
        # desglose recalculado (sin descuento) da monto_neto=50000. Pero
        # monto_total persistido queda deliberadamente en 40000 (drift simulado,
        # mismo patrón que #405: el editor mostraba/facturaba un desglose que no
        # coincidía con lo persistido).
        conn.execute(
            """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta,
                                       monto_total, monto_pagado, descuento_pct)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (P_DIVERGENTE, "Cliente desglose", "finalizado",
             "2026-06-05T08:00:00", "2026-06-05T20:00:00", 40000, 40000, 0),
        )
        conn.execute(
            """INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, cobro_modo)
               VALUES (%s,%s,%s,%s,%s)""",
            (P_DIVERGENTE, E_DIV, 1, 50000, "jornada"),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        conn = get_db()
        try:
            rec = reconciliar(conn)
        finally:
            conn.close()
        assert P_DIVERGENTE in rec["desglose_divergente"]["ids"], rec["desglose_divergente"]
        assert rec["ok"] is False
    finally:
        conn = get_db()
        try:
            _limpiar_local(conn)
            conn.commit()
        finally:
            conn.close()


def test_reconciliacion_no_marca_falso_positivo_con_descuento_de_cliente():
    """Bug encontrado en staging (2026-07-04): `_pedidos_para_desglose` no
    seleccionaba `descuento_cliente_pct`/`descuento_manual_tipo`/
    `descuento_manual_monto` de `alquileres`, ni `equipos.tipo` en el join de
    ítems — así que `desglose_de_pedido` los recomputaba con 0/None y marcaba
    DIVERGENTE cualquier pedido cuyo único descuento fuera el del CLIENTE (el
    caso más común), aunque `monto_total` estuviera perfectamente calculado.
    Reproduce el caso real: 1 ítem $50.000, 25% de descuento de cliente,
    `monto_total` = 37.500 (correcto) — antes del fix esto se marcaba
    divergente (recomputaba sin el 25% → esperaba 50.000)."""
    from database import get_db, init_db
    from reportes.reconciliacion import reconciliar

    E_OK = 9_300_903
    P_OK = 9_300_904

    def _limpiar_local(conn):
        conn.execute("DELETE FROM alquiler_items WHERE pedido_id = %s", (P_OK,))
        conn.execute("DELETE FROM alquileres WHERE id = %s", (P_OK,))
        conn.execute("DELETE FROM equipos WHERE id = %s", (E_OK,))

    init_db()
    conn = get_db()
    try:
        _limpiar_local(conn)
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s,%s,%s,%s)",
            (E_OK, "Equipo descuento cliente OK", 5, "Rental"),
        )
        conn.execute(
            """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta,
                                       monto_total, monto_pagado, descuento_pct,
                                       descuento_cliente_pct)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (P_OK, "Cliente con descuento propio", "finalizado",
             "2026-06-05T08:00:00", "2026-06-05T20:00:00", 37500, 37500, 0, 25.0),
        )
        conn.execute(
            """INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, cobro_modo)
               VALUES (%s,%s,%s,%s,%s)""",
            (P_OK, E_OK, 1, 50000, "jornada"),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        conn = get_db()
        try:
            rec = reconciliar(conn)
        finally:
            conn.close()
        assert P_OK not in rec["desglose_divergente"]["ids"], rec["desglose_divergente"]
    finally:
        conn = get_db()
        try:
            _limpiar_local(conn)
            conn.commit()
        finally:
            conn.close()


def test_suma_items_cero_no_pierde_plata():
    """Fase 5 (#1184): P_SUBTOTAL_CERO tiene AMBOS ítems con subtotal 0 (ej. 100%
    de descuento a nivel ítem) pero monto_total=30000. Antes, `NULLIF(suma_items, 0)`
    daba NULL → esos 30k desaparecían en silencio del reporte de liquidación. Ahora
    se reparten en partes iguales entre los ítems del pedido — la plata no se pierde.
    Aislado de la fixture `setup` para no alterar sus totales/aserciones."""
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        _equipo(conn, E_TINCHO, "Equipo Tincho", "Tincho")
        _pedido(conn, P_SUBTOTAL_CERO, 30000, [(E_TINCHO, 0), (E_TINCHO, 0)], monto_pagado=30000)
        _pago(conn, P_SUBTOTAL_CERO, 30000, "2026-06-25T10:00:00", "pago")
        conn.commit()
    finally:
        conn.close()

    try:
        junio = _liquidar("2026-06-01", "2026-06-30")
        assert junio["resumen"]["total"] == 30000, junio["resumen"]
        pb = junio["resumen"]["por_beneficiario"]
        assert sum(pb.values()) == 30000, pb
    finally:
        conn = get_db()
        try:
            _limpiar(conn)
            conn.commit()
        finally:
            conn.close()
