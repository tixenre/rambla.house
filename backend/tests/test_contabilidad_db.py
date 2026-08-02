"""Contabilidad (#809) contra Postgres REAL — lo que el test puro no cubre.

Ejerce el cableado con datos reales: la DERIVACIÓN de ingresos desde
`alquiler_pagos` (un cobro de cliente alimenta la caja de su socio, sin cargar
nada a mano), los movimientos moviendo plata entre cuentas, y la baja lógica.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`): se saltea
salvo `RESERVAS_DB_TEST=1` + `DATABASE_URL` a una base con 'test' en el nombre.
Cada test trabaja en una transacción que se DESCARTA con rollback al terminar
(no toca datos commiteados) y usa ids altos (>= 9_400_000).

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_contabilidad_db.py -v -m integration
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

PED = 9_400_001


def _ensure_cuenta(conn, nombre: str, **kwargs) -> None:
    """Crea la cuenta de ejemplo si todavía no existe. Idempotente A PROPÓSITO:
    `cerrar_mes`/`reabrir_mes` (`contabilidad/cierres.py`) comitean de verdad
    (son acciones durables reales, no solo del request) — si un test anterior
    los llamó, esta cuenta puede haber sobrevivido al rollback de SU propio
    `conn` fixture. Sin el chequeo, el segundo test que la crea pisa el único
    parcial `cuentas_nombre_activa_uq` con UniqueViolation."""
    from contabilidad.commands.cuentas import crear_cuenta

    if _cuenta_id(conn, nombre) is None:
        crear_cuenta(conn, nombre=nombre, por="test-seed", **kwargs)


@pytest.fixture
def conn():
    """Conexión transaccional: lo que inserta el test se DESCARTA con rollback al
    terminar, así no quedan datos sucios (no hace falta limpieza manual).

    Efectivo/Banco/Dólares ya NO están en el seed de `init_db()` (#quitadas en
    44ede548 — resucitaban en cada boot si el dueño las daba de baja, por el
    `ON CONFLICT DO NOTHING` sin agarrar `socio=NULL` bajo el índice parcial
    `activa`). Este archivo las sigue necesitando como cajas de ejemplo para
    varios tests → se crean acá (idempotente, ver `_ensure_cuenta`)."""
    from database import get_db, init_db

    init_db()  # garantiza el esquema (su propia conexión/commit)
    c = get_db()
    try:
        _ensure_cuenta(c, "Efectivo", tipo="caja")
        _ensure_cuenta(c, "Banco", tipo="caja")
        _ensure_cuenta(c, "Dólares", tipo="caja", moneda="USD")
        yield c
    finally:
        c.rollback()
        c.close()


def _saldo(conn, nombre: str):
    from contabilidad.queries.saldos import saldos
    for f in saldos(conn)["cuentas"]:
        if f["nombre"] == nombre:
            return f["saldo"]
    return None


def _cuenta_id(conn, nombre: str):
    row = conn.execute("SELECT id FROM cuentas WHERE nombre = %s", (nombre,)).fetchone()
    return row[0] if row else None


def _pedido_y_pago(conn, monto, destinatario, fecha="2026-06-15T10:00:00",
                   fecha_desde="2026-06-05T08:00:00", ped=PED):
    conn.execute(
        """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta,
                                   monto_total, monto_pagado)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (ped, "Cliente contab", "finalizado", fecha_desde,
         "2026-06-06T20:00:00", monto, monto),
    )
    conn.execute(
        """INSERT INTO alquiler_pagos (pedido_id, monto, concepto, destinatario, metodo, fecha)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (ped, monto, "pago", destinatario, "transferencia", fecha),
    )


def _mov(conn, tipo, monto, origen=None, destino=None):
    conn.execute(
        """INSERT INTO movimientos (tipo, monto, cuenta_origen_id, cuenta_destino_id, created_by)
           VALUES (%s,%s,%s,%s,%s)""",
        (tipo, monto, origen, destino, "test"),
    )


def test_cobro_de_cliente_alimenta_la_caja_del_socio(conn):
    # El corazón de Fase 1: sin cargar ningún movimiento, un pago cobrado por
    # Tincho hace subir el saldo de Caja Tincho exactamente por ese monto.
    base = _saldo(conn, "Caja Tincho")
    _pedido_y_pago(conn, 200000, "Tincho")
    despues = _saldo(conn, "Caja Tincho")
    assert despues - base == 200000


def test_el_cobro_no_toca_la_caja_del_otro_socio(conn):
    base_pablo = _saldo(conn, "Caja Pablo")
    _pedido_y_pago(conn, 200000, "Tincho")
    assert _saldo(conn, "Caja Pablo") == base_pablo  # Pablo no se mueve


def test_cobro_de_rental_alimenta_el_fondo_rental(conn):
    # Rental también cobra (default): su plata cae en la caja Fondo Rental.
    base = _saldo(conn, "Fondo Rental")
    _pedido_y_pago(conn, 80000, "Rental")
    assert _saldo(conn, "Fondo Rental") - base == 80000


def test_ingresos_derivados_agrupan_por_destinatario(conn):
    from contabilidad.queries.saldos import ingresos_derivados

    base = ingresos_derivados(conn).get("Tincho", 0)
    _pedido_y_pago(conn, 150000, "Tincho")
    assert ingresos_derivados(conn).get("Tincho", 0) - base == 150000


def test_alquiler_previo_al_clean_start_no_entra_a_finanzas(conn):
    # Clean start por FECHA DEL ALQUILER (no de pago): un pedido cuyo alquiler fue
    # antes de junio, aunque se cobre en junio, NO suma al saldo de la caja del socio
    # ni a los cobros mensuales. Queda "cobrado y listo" en el pedido, fuera de Finanzas.
    from contabilidad.queries.saldos import ingresos_derivados
    from contabilidad.queries.movimientos import cobros_mensuales

    base_caja = _saldo(conn, "Caja Tincho")
    base_ing = ingresos_derivados(conn).get("Tincho", 0)
    base_cobros = sum(r["monto"] for r in cobros_mensuales(conn, cobrador="Tincho"))

    _pedido_y_pago(conn, 300000, "Tincho",
                   fecha="2026-06-15T10:00:00", fecha_desde="2026-05-20T08:00:00",
                   ped=9_400_050)

    assert _saldo(conn, "Caja Tincho") == base_caja  # la caja no se mueve
    assert ingresos_derivados(conn).get("Tincho", 0) == base_ing  # no deriva ingreso
    assert sum(r["monto"] for r in cobros_mensuales(conn, cobrador="Tincho")) == base_cobros


def test_nombre_se_libera_al_dar_de_baja(conn):
    # El nombre es único solo entre activas: dar de baja una cuenta libera su
    # nombre, así se puede reusar (caso real: renombrar a un nombre que tenía una
    # cuenta vieja de baja).
    from contabilidad.commands.cuentas import crear_cuenta, desactivar_cuenta

    nombre = "Reuso Test 9400"
    c1 = crear_cuenta(conn, nombre=nombre, tipo="caja", por="test")
    desactivar_cuenta(conn, c1["id"], por="test")  # saldo 0 → baja OK
    c2 = crear_cuenta(conn, nombre=nombre, tipo="caja", por="test")
    assert c2["id"] != c1["id"]
    assert c2["nombre"] == nombre


def test_gasto_baja_el_saldo_de_la_caja_de_origen(conn):
    base = _saldo(conn, "Efectivo")
    _mov(conn, "gasto", 25000, origen=_cuenta_id(conn, "Efectivo"))
    assert _saldo(conn, "Efectivo") - base == -25000


def test_transferencia_mueve_plata_entre_cuentas(conn):
    base_pablo = _saldo(conn, "Caja Pablo")
    base_fondo = _saldo(conn, "Fondo Rental")
    _mov(conn, "transferencia", 60000,
         origen=_cuenta_id(conn, "Caja Pablo"), destino=_cuenta_id(conn, "Fondo Rental"))
    assert _saldo(conn, "Caja Pablo") - base_pablo == -60000
    assert _saldo(conn, "Fondo Rental") - base_fondo == 60000


def test_transferencia_entre_partes_se_auto_marca_es_rendicion(conn):
    # Sin que el caller pida `es_rendicion`, una transferencia entre dos partes
    # distintas (Tincho↔Fondo Rental) queda marcada sola — así aparece en
    # `ya_transferido`/"Movimientos de rendición" igual que un saldado explícito
    # de `saldar()`, sin que el form general tenga que saber que esa marca existe.
    from contabilidad.commands.movimientos import crear_movimiento
    from services.fechas import mes_actual_ar

    mov = crear_movimiento(
        conn, tipo="transferencia", monto=45000,
        cuenta_origen_id=_cuenta_id(conn, "Caja Tincho"),
        cuenta_destino_id=_cuenta_id(conn, "Fondo Rental"),
        por="test",
    )
    assert mov["es_rendicion"] is True
    assert mov["rendicion_mes"] == mes_actual_ar()


def test_reparto_desde_caja_generica_no_se_marca(conn):
    # Efectivo → Caja Tincho ES un reparto para la posición ACUMULADA (el
    # clasificador hace caer una caja genérica a "Rental"), pero acá NO se marca
    # `es_rendicion` a propósito: `ya_transferido` mapea cada punta SIN fallback y
    # saltea la que da None, así que marcarlo le sumaría a Tincho sin restarle a
    # Rental y la rendición del mes dejaría de cerrar en cero.
    #
    # Este test fija esa asimetría para que nadie "alinee" las dos condiciones
    # creyendo que es una inconsistencia (hallazgo del supervisor: el comentario
    # viejo decía que eran la misma condición, y no lo son).
    from contabilidad.commands.movimientos import crear_movimiento
    from contabilidad.queries.posiciones import clasificar_flujo, parte_de_cuenta

    efectivo, tincho = _cuenta_id(conn, "Efectivo"), _cuenta_id(conn, "Caja Tincho")

    mov = crear_movimiento(
        conn, tipo="transferencia", monto=30000,
        cuenta_origen_id=efectivo, cuenta_destino_id=tincho, por="test",
    )
    assert mov["es_rendicion"] is False, "marcarlo rompería el cierre en cero del mes"

    # Pero la posición acumulada SÍ lo cuenta — las dos cosas a la vez son correctas.
    filas = conn.execute(
        "SELECT id, socio, tipo, nombre FROM cuentas WHERE id IN (%s, %s)",
        (efectivo, tincho),
    ).fetchall()
    parte_por_cuenta = {
        r["id"]: parte_de_cuenta(r["socio"], r["tipo"], r["nombre"]) for r in filas
    }
    cc_por_cuenta = {efectivo: False, tincho: True}
    assert clasificar_flujo(
        {"monto": 30000, "cuenta_origen_id": efectivo, "cuenta_destino_id": tincho},
        parte_por_cuenta, cc_por_cuenta,
    ) == ("Rental", "Tincho")


def test_transferencia_entre_dos_cajas_propias_no_se_marca(conn):
    # Efectivo y Banco son las dos "Rental" (ninguna representa a otra parte):
    # mover plata entre ellas es puertas adentro del negocio, no un reparto.
    from contabilidad.commands.movimientos import crear_movimiento

    mov = crear_movimiento(
        conn, tipo="transferencia", monto=20000,
        cuenta_origen_id=_cuenta_id(conn, "Efectivo"),
        cuenta_destino_id=_cuenta_id(conn, "Banco"),
        por="test",
    )
    assert mov["es_rendicion"] is False
    assert mov["rendicion_mes"] is None


def test_saldo_iguala_la_derivacion(conn):
    # Invariante: el saldo de una caja de socio (sin movimientos que la toquen)
    # == sus ingresos derivados (+ su saldo inicial, que es 0 en el seed).
    from contabilidad.queries.saldos import ingresos_derivados
    _pedido_y_pago(conn, 90000, "Pablo")
    assert _saldo(conn, "Caja Pablo") == ingresos_derivados(conn).get("Pablo", 0)


def test_socios_coinciden_con_destinatarios_de_pago(conn):
    # Anti-drift: los socios del módulo contable son exactamente los destinatarios
    # posibles de un cobro (si alguien agrega un tercero, este test obliga a tocar
    # los dos lados).
    from contabilidad.constants import COBRADORES
    from routes.alquileres import DESTINATARIOS_PAGO

    assert set(COBRADORES) == set(DESTINATARIOS_PAGO)


def test_desactivar_falla_si_la_cuenta_tiene_saldo(conn):
    from contabilidad.commands.cuentas import crear_cuenta, desactivar_cuenta

    c = crear_cuenta(conn, nombre="Caja Test ZZ", tipo="caja", saldo_inicial=50000)
    with pytest.raises(ValueError):
        desactivar_cuenta(conn, c["id"])


def _categoria_id(conn, nombre="Otros"):
    row = conn.execute("SELECT id FROM gasto_categorias WHERE nombre = %s", (nombre,)).fetchone()
    return row[0] if row else None


def test_crear_gasto_baja_caja_y_anular_lo_restaura(conn):
    # El engine (no SQL crudo): un gasto baja la caja; anularlo la restaura, porque
    # los movimientos anulados no cuentan para el saldo.
    from contabilidad.commands.movimientos import anular_movimiento, crear_movimiento

    base = _saldo(conn, "Efectivo")
    mov = crear_movimiento(
        conn, tipo="gasto", monto=12000, cuenta_origen_id=_cuenta_id(conn, "Efectivo"),
        categoria_id=_categoria_id(conn), por="test",
    )
    assert _saldo(conn, "Efectivo") - base == -12000
    anular_movimiento(conn, mov["id"], motivo="cargado por error", por="test")
    assert _saldo(conn, "Efectivo") == base  # restaurado


def test_reporte_mensual_cargo_a_socio_no_toca_ganancia(conn):
    # Núcleo del reporte: un CARGO a un socio (Rental le compró algo) es una
    # transferencia, NO un gasto → aparece en socios_mes pero NO baja la ganancia.
    from contabilidad.commands.movimientos import crear_movimiento
    from contabilidad.queries.reporte_mensual import reporte_mensual

    mes = "2026-06"
    base = reporte_mensual(conn, mes)
    cargo_base = base["socios_mes"]["cargos"]["Pablo"]
    gan_base = base["ganancia_neta"]

    crear_movimiento(
        conn, tipo="transferencia", monto=50000,
        cuenta_origen_id=_cuenta_id(conn, "Efectivo"),
        cuenta_destino_id=_cuenta_id(conn, "Caja Pablo"),
        fecha="2026-06-15", por="test",
    )
    rep = reporte_mensual(conn, mes)
    assert rep["socios_mes"]["cargos"]["Pablo"] - cargo_base == 50000  # aparece como cargo
    assert rep["ganancia_neta"] == gan_base  # NO toca la ganancia


def test_reporte_mensual_gasto_si_baja_ganancia(conn):
    # Contraste: un gasto real SÍ baja la ganancia neta.
    from contabilidad.commands.movimientos import crear_movimiento
    from contabilidad.queries.reporte_mensual import reporte_mensual

    mes = "2026-06"
    gan_base = reporte_mensual(conn, mes)["ganancia_neta"]
    crear_movimiento(
        conn, tipo="gasto", monto=20000, cuenta_origen_id=_cuenta_id(conn, "Efectivo"),
        categoria_id=_categoria_id(conn), fecha="2026-06-10", por="test",
    )
    assert reporte_mensual(conn, mes)["ganancia_neta"] == gan_base - 20000


def test_reporte_ganancia_descuenta_comision_de_duenos(conn):
    # Núcleo del fix de plata: un pedido saldado de $100k con equipo de Pablo. Del
    # reparto, a Rental le tocan $45k (45%); Pablo+Tincho se llevan $55k. La
    # ganancia parte de los $45k de Rental, NO de los $100k facturados — la comisión
    # de los dueños es un COSTO, no ganancia de Rental.
    from contabilidad.queries.reporte_mensual import reporte_mensual

    EQ, PEDX = 9_400_700, 9_400_701
    conn.execute(
        "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s,%s,%s,%s)",
        (EQ, "Equipo Pablo gan", 1, "Pablo"),
    )
    conn.execute(
        """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta,
                                   monto_total, monto_pagado)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (PEDX, "Cli gan", "finalizado", "2026-06-05T08:00:00", "2026-06-06T20:00:00",
         100000, 100000),
    )
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal) VALUES (%s,%s,%s,%s)",
        (PEDX, EQ, 1, 100000),
    )
    conn.execute(
        """INSERT INTO alquiler_pagos (pedido_id, monto, concepto, destinatario, metodo, fecha)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (PEDX, 100000, "pago", "Rental", "transferencia", "2026-06-15T10:00:00"),
    )

    rep = reporte_mensual(conn, "2026-06")
    assert rep["devengado"]["total"] == 100000  # se facturó el total
    assert rep["devengado"]["por_socio"]["Rental"] == 45000  # a Rental le toca el 45%
    assert rep["comisiones_duenos"] == 55000  # Pablo 50k + Tincho 5k
    assert rep["ganancia_neta"] == 45000  # parte de Rental − 0 gastos (NO los 100k)
    # Invariante del modelo: ganancia = facturado − comisiones − gastos.
    assert rep["ganancia_neta"] == (
        rep["devengado"]["total"] - rep["comisiones_duenos"] - rep["gastos"]["total"]
    )


def test_listar_movimientos_resuelve_nombres(conn):
    from contabilidad.commands.movimientos import crear_movimiento
    from contabilidad.queries.movimientos import listar_movimientos

    crear_movimiento(
        conn, tipo="transferencia", monto=5000,
        cuenta_origen_id=_cuenta_id(conn, "Caja Pablo"),
        cuenta_destino_id=_cuenta_id(conn, "Banco"), por="test",
    )
    movs = listar_movimientos(conn, tipo="transferencia")
    assert any(
        m["cuenta_origen_nombre"] == "Caja Pablo" and m["cuenta_destino_nombre"] == "Banco"
        for m in movs
    )


def test_gasto_necesita_categoria(conn):
    from contabilidad.commands.movimientos import crear_movimiento

    with pytest.raises(ValueError):
        crear_movimiento(conn, tipo="gasto", monto=1000,
                         cuenta_origen_id=_cuenta_id(conn, "Efectivo"), por="test")


def test_rendicion_cierra_en_cero_y_saldar(conn):
    # El invariante de oro: la rendición está atada al universo del reporte, así
    # que lo cobrado == el total del reporte. Y registrar los sugeridos deja todo
    # saldado. Mes futuro aislado para no chocar con datos de otros tests.
    from contabilidad.queries.rendicion import rendicion
    from contabilidad.commands.rendicion import saldar

    MES = "2026-09"
    EQ, PED2 = 9_400_900, 9_400_901
    conn.execute(
        "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s,%s,%s,%s)",
        (EQ, "Equipo Rend", 3, "Pablo"),
    )
    conn.execute(
        """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta,
                                   monto_total, monto_pagado)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (PED2, "Cli rend", "finalizado", "2026-09-05T08:00:00", "2026-09-06T20:00:00",
         100000, 100000),
    )
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal) VALUES (%s,%s,%s,%s)",
        (PED2, EQ, 1, 100000),
    )
    conn.execute(
        """INSERT INTO alquiler_pagos (pedido_id, monto, concepto, destinatario, metodo, fecha)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (PED2, 100000, "pago", "Tincho", "transferencia", "2026-09-15T10:00:00"),
    )

    r = rendicion(conn, MES)
    assert r["total_cobrado"] == r["total_reporte"] == 100000, r
    assert r["cuadra"] is True
    by = {p["persona"]: p for p in r["personas"]}
    assert by["Pablo"]["le_corresponde"] == 50000  # equipo de Pablo → 50/45/5
    assert by["Rental"]["le_corresponde"] == 45000
    assert by["Tincho"]["le_corresponde"] == 5000
    assert by["Tincho"]["cobro"] == 100000  # todo lo cobró Tincho
    assert sum(p["pendiente"] for p in r["personas"]) == 0  # cierra en cero

    # Registrar los sugeridos deja todo saldado.
    for s in r["sugeridos"]:
        saldar(conn, MES, de=s["de"], a=s["a"], monto=s["monto"], por="test")
    r2 = rendicion(conn, MES)
    assert r2["sugeridos"] == []
    assert all(p["pendiente"] == 0 for p in r2["personas"])


def test_cierre_traba_la_edicion_del_mes(conn):
    from contabilidad.commands.cierres import cerrar_mes, reabrir_mes
    from contabilidad.queries.cierres import mes_cerrado
    from contabilidad.commands.movimientos import crear_movimiento

    MES = "2026-08"
    reabrir_mes(conn, MES)  # idempotente: limpia un cierre colgado de una corrida previa
    assert mes_cerrado(conn, MES) is False
    try:
        cerrar_mes(conn, MES, "test")
        assert mes_cerrado(conn, MES) is True
        # Un gasto fechado en el mes cerrado queda trabado.
        with pytest.raises(ValueError):
            crear_movimiento(
                conn, tipo="gasto", monto=1000, cuenta_origen_id=_cuenta_id(conn, "Efectivo"),
                categoria_id=_categoria_id(conn), fecha="2026-08-10", por="test",
            )
    finally:
        reabrir_mes(conn, MES)
    assert mes_cerrado(conn, MES) is False
    # Reabierto, el mismo gasto entra.
    m = crear_movimiento(
        conn, tipo="gasto", monto=1000, cuenta_origen_id=_cuenta_id(conn, "Efectivo"),
        categoria_id=_categoria_id(conn), fecha="2026-08-10", por="test",
    )
    assert m["id"]


def test_reconciliar_corre(conn):
    from contabilidad.queries.reconciliacion import reconciliar

    r = reconciliar(conn)
    assert "ok" in r
    assert "saldos_negativos" in r and "pagos_sin_socio" in r


def test_beneficiario_se_guarda_y_autocompleta(conn):
    from contabilidad.commands.movimientos import crear_movimiento
    from contabilidad.queries.movimientos import beneficiarios_usados, listar_movimientos

    crear_movimiento(
        conn, tipo="gasto", monto=125000, cuenta_origen_id=_cuenta_id(conn, "Efectivo"),
        categoria_id=_categoria_id(conn), beneficiario="Jimena", por="test",
    )
    assert "Jimena" in beneficiarios_usados(conn)
    # filtrable para ver el historial de esa persona
    movs = listar_movimientos(conn, beneficiario="Jimena")
    assert movs and all(m["beneficiario"] == "Jimena" for m in movs)


def test_cobros_mensuales_agrega_por_mes(conn):
    from contabilidad.queries.movimientos import cobros_mensuales

    _pedido_y_pago(conn, 120000, "Tincho", fecha="2026-06-15T10:00:00")
    junio = [r for r in cobros_mensuales(conn, cobrador="Tincho") if r["mes"] == "2026-06"]
    assert junio and junio[0]["monto"] >= 120000  # agrega el cobro del mes


def test_caja_usd_existe_y_totales_por_moneda(conn):
    from contabilidad.queries.saldos import saldos

    s = saldos(conn)
    by = {c["nombre"]: c for c in s["cuentas"]}
    assert by["Dólares"]["moneda"] == "USD"  # caja en dólares seedeada
    assert "USD" in s["totales"] and "ARS" in s["totales"]


def test_transferencia_entre_monedas_distintas_falla(conn):
    from contabilidad.commands.movimientos import crear_movimiento

    with pytest.raises(ValueError):
        crear_movimiento(
            conn, tipo="transferencia", monto=1000,
            cuenta_origen_id=_cuenta_id(conn, "Efectivo"),   # ARS
            cuenta_destino_id=_cuenta_id(conn, "Dólares"),   # USD
            por="test",
        )


def test_cambio_divisa_compra_dolares_ok(conn):
    """Comprar USD con ARS: dos `ajuste` atados, cada uno en su caja/moneda."""
    from contabilidad.commands.movimientos import crear_cambio_divisa

    efectivo_id = _cuenta_id(conn, "Efectivo")   # ARS
    dolares_id = _cuenta_id(conn, "Dólares")     # USD
    saldo_ars_antes = _saldo(conn, "Efectivo")
    saldo_usd_antes = _saldo(conn, "Dólares")

    r = crear_cambio_divisa(
        conn, cuenta_origen_id=efectivo_id, cuenta_destino_id=dolares_id,
        monto_origen=125_000, cotizacion=1250, por="test",
    )

    assert r["origen"]["tipo"] == "ajuste" and r["origen"]["monto"] == 125_000
    assert r["origen"]["cuenta_origen_id"] == efectivo_id
    assert r["destino"]["tipo"] == "ajuste" and r["destino"]["monto"] == 100
    assert r["destino"]["cuenta_destino_id"] == dolares_id
    assert r["cotizacion"] == 1250.0
    # Cada pata guarda la cotización y apunta a la otra por `movimiento_par_id`.
    assert r["origen"]["cotizacion"] == 1250.0
    assert r["origen"]["movimiento_par_id"] == r["destino"]["id"]
    assert r["destino"]["movimiento_par_id"] == r["origen"]["id"]
    # Efecto real en los saldos: sale de la caja ARS, entra a la caja USD.
    assert _saldo(conn, "Efectivo") == saldo_ars_antes - 125_000
    assert _saldo(conn, "Dólares") == saldo_usd_antes + 100


def test_cambio_divisa_venta_de_dolares_deriva_cotizacion(conn):
    """Vender USD por ARS (dirección inversa) dando ambos montos — sin
    cotización explícita, se deriva."""
    from contabilidad.commands.movimientos import crear_cambio_divisa

    dolares_id = _cuenta_id(conn, "Dólares")
    efectivo_id = _cuenta_id(conn, "Efectivo")

    r = crear_cambio_divisa(
        conn, cuenta_origen_id=dolares_id, cuenta_destino_id=efectivo_id,
        monto_origen=50, monto_destino=62_500, por="test",
    )

    assert r["origen"]["monto"] == 50 and r["origen"]["cuenta_origen_id"] == dolares_id
    assert r["destino"]["monto"] == 62_500 and r["destino"]["cuenta_destino_id"] == efectivo_id
    assert r["cotizacion"] == 1250.0


def test_cambio_divisa_misma_moneda_falla(conn):
    from contabilidad.commands.movimientos import crear_cambio_divisa

    with pytest.raises(ValueError):
        crear_cambio_divisa(
            conn, cuenta_origen_id=_cuenta_id(conn, "Efectivo"),
            cuenta_destino_id=_cuenta_id(conn, "Banco"),
            monto_origen=1000, monto_destino=1000, por="test",
        )


def test_cambio_divisa_mes_cerrado_falla(conn):
    # Mes propio ("2026-09", no usado por otros tests) y cerrar_mes/reabrir_mes
    # comitean de verdad (no se descartan con el rollback del fixture) — mismo
    # try/finally que `test_cierre_traba_la_edicion_del_mes`.
    from contabilidad.commands.cierres import cerrar_mes, reabrir_mes
    from contabilidad.commands.movimientos import crear_cambio_divisa

    MES = "2026-09"
    reabrir_mes(conn, MES)
    try:
        cerrar_mes(conn, MES, "test")
        with pytest.raises(ValueError, match="cerrado"):
            crear_cambio_divisa(
                conn, cuenta_origen_id=_cuenta_id(conn, "Efectivo"),
                cuenta_destino_id=_cuenta_id(conn, "Dólares"),
                monto_origen=10_000, cotizacion=1250, fecha=f"{MES}-15", por="test",
            )
    finally:
        reabrir_mes(conn, MES)


def test_crear_y_desactivar_cuenta_vacia(conn):
    from contabilidad.commands.cuentas import crear_cuenta, desactivar_cuenta

    c = crear_cuenta(conn, nombre="Caja Test Vacia ZZ", tipo="caja")
    desactivado = desactivar_cuenta(conn, c["id"])
    assert desactivado["activa"] is False


def test_retiro_aporte_ajuste_extremo_a_extremo(conn):
    # Gasto y transferencia ya se ejercen extremo-a-extremo (crear_movimiento)
    # en otros tests de este archivo; retiro/aporte/ajuste NO tenían ningún test
    # contra Postgres real (solo su validación estructural, pura, en
    # test_contabilidad_movimientos.py) — auditoría 2026-07-02. Acá se prueba
    # el camino de escritura real: validación + INSERT + derivación del saldo.
    from contabilidad.commands.movimientos import crear_movimiento

    efectivo = _cuenta_id(conn, "Efectivo")
    banco = _cuenta_id(conn, "Banco")
    base_efectivo = _saldo(conn, "Efectivo")
    base_banco = _saldo(conn, "Banco")

    # Retiro: un socio saca plata de una caja — sale del sistema, sin destino.
    crear_movimiento(conn, tipo="retiro", monto=8000, cuenta_origen_id=efectivo, por="test")
    assert _saldo(conn, "Efectivo") - base_efectivo == -8000

    # Aporte: un socio mete plata — entra al sistema, sin origen.
    crear_movimiento(conn, tipo="aporte", monto=15000, cuenta_destino_id=banco, por="test")
    assert _saldo(conn, "Banco") - base_banco == 15000

    # Ajuste: conciliación manual, puede ser de un solo lado (acá: solo origen,
    # como una merma/pérdida en Efectivo — no exige el otro lado).
    crear_movimiento(conn, tipo="ajuste", monto=500, cuenta_origen_id=efectivo,
                     nota="Merma de caja", por="test")
    assert _saldo(conn, "Efectivo") - base_efectivo == -8500  # retiro + ajuste acumulados

    # Conservación: nada de esto tocó Banco más que el aporte, ni viceversa —
    # las cajas no se contaminan entre sí sin un movimiento que las vincule.
    assert _saldo(conn, "Banco") - base_banco == 15000


def test_ajuste_con_origen_y_destino_mueve_ambos_saldos(conn):
    # Único hueco combinatorio real entre los 5 tipos de movimiento: un ajuste
    # con AMBOS lados a la vez (conciliación entre dos cajas, sin ser
    # "transferencia" en el sentido operativo) — auditoría 2026-07-02.
    from contabilidad.commands.movimientos import crear_movimiento

    efectivo = _cuenta_id(conn, "Efectivo")
    banco = _cuenta_id(conn, "Banco")
    base_efectivo = _saldo(conn, "Efectivo")
    base_banco = _saldo(conn, "Banco")

    crear_movimiento(conn, tipo="ajuste", monto=3000, cuenta_origen_id=efectivo,
                     cuenta_destino_id=banco, nota="Corrección de conteo", por="test")
    assert _saldo(conn, "Efectivo") - base_efectivo == -3000
    assert _saldo(conn, "Banco") - base_banco == 3000


def test_editar_cuenta_end_to_end(conn):
    # editar_cuenta no tenía NINGÚN test — auditoría 2026-07-02. Es la función
    # de escritura de mayor riesgo real (se usa hoy en producción para editar
    # el saldo_inicial de arranque de un socio).
    from contabilidad.commands.cuentas import crear_cuenta, editar_cuenta

    c = crear_cuenta(conn, nombre="Caja Editar ZZ", tipo="caja", saldo_inicial=1000)

    editado = editar_cuenta(conn, c["id"], campos={"saldo_inicial": 5000}, por="test")
    assert editado["saldo_inicial"] == 5000

    editado = editar_cuenta(conn, c["id"], campos={"nombre": "Caja Editar ZZ Renombrada"}, por="test")
    assert editado["nombre"] == "Caja Editar ZZ Renombrada"

    # tipo/socio NO están en _CAMPOS_EDITABLES → se ignoran en silencio, no se tocan.
    editado = editar_cuenta(conn, c["id"], campos={"tipo": "banco", "socio": "Pablo"}, por="test")
    assert editado["tipo"] == "caja"
    assert editado["socio"] is None

    # El nombre viejo queda libre (índice parcial WHERE activa) — otra cuenta
    # nueva puede reusarlo sin chocar.
    c2 = crear_cuenta(conn, nombre="Caja Editar ZZ", tipo="caja")
    assert c2["id"] != c["id"]


def test_editar_movimiento_revalida_cuentas_y_categoria(conn):
    # editar_movimiento no repetía las validaciones de crear_movimiento — bug
    # real: se podía cambiar cuenta_destino_id a una cuenta de OTRA moneda sin
    # ningún error, violando la invariante ARS≠USD (auditoría 2026-07-02, fix
    # en _validar_cuentas_y_categoria). Este test confirma el fix.
    from contabilidad.commands.movimientos import crear_movimiento, editar_movimiento

    efectivo = _cuenta_id(conn, "Efectivo")
    banco = _cuenta_id(conn, "Banco")
    dolares = _cuenta_id(conn, "Dólares")

    mov = crear_movimiento(conn, tipo="transferencia", monto=10000,
                           cuenta_origen_id=efectivo, cuenta_destino_id=banco, por="test")

    # Editar a una cuenta de OTRA moneda: debe fallar (antes del fix, pasaba).
    with pytest.raises(ValueError):
        editar_movimiento(conn, mov["id"], campos={"cuenta_destino_id": dolares}, por="test")

    # Editar a una cuenta inexistente: debe fallar.
    with pytest.raises(ValueError):
        editar_movimiento(conn, mov["id"], campos={"cuenta_origen_id": 999_999_999}, por="test")

    # Editar la categoría de un gasto a una inexistente: debe fallar.
    gasto = crear_movimiento(conn, tipo="gasto", monto=2000, cuenta_origen_id=efectivo,
                             categoria_id=_categoria_id(conn), por="test")
    with pytest.raises(ValueError):
        editar_movimiento(conn, gasto["id"], campos={"categoria_id": 999_999_999}, por="test")

    # El camino sano (misma moneda, cuenta activa) sigue andando.
    editado = editar_movimiento(conn, mov["id"], campos={"monto": 12000}, por="test")
    assert editado["monto"] == 12000


def test_saldo_de_cuenta_fallback_inactiva_e_inexistente(conn):
    # El fallback de saldo_de_cuenta (cuenta que no aparece en saldos() porque
    # está desactivada, o no existe) nunca corría bajo test — auditoría 2026-07-02.
    from contabilidad.commands.cuentas import crear_cuenta, desactivar_cuenta
    from contabilidad.commands.movimientos import crear_movimiento
    from contabilidad.queries.saldos import saldo_de_cuenta

    c = crear_cuenta(conn, nombre="Caja Fallback ZZ", tipo="caja")
    efectivo = _cuenta_id(conn, "Efectivo")
    # Llevarla a saldo 0 (entra y sale lo mismo) para poder desactivarla.
    crear_movimiento(conn, tipo="transferencia", monto=4000,
                     cuenta_origen_id=efectivo, cuenta_destino_id=c["id"], por="test")
    crear_movimiento(conn, tipo="transferencia", monto=4000,
                     cuenta_origen_id=c["id"], cuenta_destino_id=efectivo, por="test")
    assert saldo_de_cuenta(conn, c["id"]) == 0

    desactivar_cuenta(conn, c["id"])
    # Ya no aparece en saldos()["cuentas"] (solo activas) — el fallback recalcula.
    assert saldo_de_cuenta(conn, c["id"]) == 0

    assert saldo_de_cuenta(conn, 999_999_999) == 0  # inexistente


def test_anular_movimiento_es_rendicion_ya_saldado(conn):
    # anular_movimiento no distingue si el movimiento es parte de una rendición
    # ya saldada — auditoría 2026-07-02. Este test documenta el comportamiento
    # (correcto, no un bug): ya_transferido() excluye el anulado ("la plata no
    # se borra" reflejado en la rendición: el saldado deja de contar y el
    # pendiente reaparece), pero _movimientos_rendicion (el log de auditoría)
    # lo sigue mostrando — es intencional, no una divergencia accidental.
    from contabilidad.queries.rendicion import rendicion, ya_transferido
    from contabilidad.commands.rendicion import saldar
    from contabilidad.commands.movimientos import anular_movimiento

    MES = "2026-10"
    EQ, PED = 9_400_910, 9_400_911
    # Dueño Pablo pero cobrado por Tincho (mismo patrón que
    # test_rendicion_cierra_en_cero_y_saldar): genera un sugerido real de
    # Tincho→Pablo, no ambiguo como cuando cobra el mismo que corresponde.
    conn.execute(
        "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s,%s,%s,%s)",
        (EQ, "Equipo Anular Rend", 2, "Pablo"),
    )
    conn.execute(
        """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta,
                                   monto_total, monto_pagado)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (PED, "Cli anular rend", "finalizado", "2026-10-05T08:00:00", "2026-10-06T20:00:00",
         50000, 50000),
    )
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal) VALUES (%s,%s,%s,%s)",
        (PED, EQ, 1, 50000),
    )
    conn.execute(
        """INSERT INTO alquiler_pagos (pedido_id, monto, concepto, destinatario, metodo, fecha)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (PED, 50000, "pago", "Tincho", "transferencia", "2026-10-15T10:00:00"),
    )

    r = rendicion(conn, MES)
    assert r["cuadra"] is True
    sugeridos = r["sugeridos"]
    assert sugeridos, "esperaba al menos un sugerido para saldar"
    s = sugeridos[0]
    mov = saldar(conn, MES, de=s["de"], a=s["a"], monto=s["monto"], por="test")

    ya = ya_transferido(conn, MES)
    assert ya[s["a"]] > 0  # ya recibió, vía el saldado

    anular_movimiento(conn, mov["id"], motivo="carga duplicada", por="test")

    # Al anular, ya_transferido() ya NO lo cuenta — el pendiente reaparece.
    ya2 = ya_transferido(conn, MES)
    assert ya2[s["a"]] == 0

    # Pero el log de auditoría (_movimientos_rendicion, vía rendicion()) SÍ lo
    # sigue mostrando — no desaparece, queda trazable.
    r2 = rendicion(conn, MES)
    ids_en_log = [m["id"] for m in r2["movimientos"]]
    assert mov["id"] in ids_en_log


def test_reabrir_mes_assert_retorno(conn):
    # reabrir_mes se ejecutaba en otros tests (como limpieza) pero nunca se
    # asserteaba su valor de retorno True/False — auditoría 2026-07-02. El
    # equivalente en reportes/cierres.py sí lo testea en ambos casos.
    from contabilidad.commands.cierres import cerrar_mes, reabrir_mes

    MES = "2026-11"
    assert reabrir_mes(conn, MES) is False  # no había cierre → nada que reabrir

    cerrar_mes(conn, MES, "test")
    assert reabrir_mes(conn, MES) is True  # había cierre → lo borró

    assert reabrir_mes(conn, MES) is False  # ya no hay nada → False de nuevo


def test_retiro_aporte_bloqueados_contra_cuenta_socio(conn):
    # Resuelto 2026-07-02 (confirmado con el dueño): la cuenta de un socio humano
    # es puro balance de deuda (su plata real está en un banco aparte, fuera del
    # sistema) — retiro/aporte representan plata física entrando/saliendo de una
    # CAJA, así que no tienen sentido de negocio contra un balance de deuda.
    from contabilidad.commands.movimientos import crear_movimiento

    caja_pablo = _cuenta_id(conn, "Caja Pablo")

    with pytest.raises(ValueError, match="retiro"):
        crear_movimiento(conn, tipo="retiro", monto=1000, cuenta_origen_id=caja_pablo, por="test")
    with pytest.raises(ValueError, match="aporte"):
        crear_movimiento(conn, tipo="aporte", monto=1000, cuenta_destino_id=caja_pablo, por="test")


def test_gasto_contra_cuenta_socio_cuenta_en_pyl_y_baja_deuda(conn):
    # Permitido a propósito: "el socio pagó un gasto de Rental con su propia
    # plata". Un solo movimiento hace las dos cosas — cuenta en el P&L
    # categorizado (gastos_por_categoria no filtra por tipo de cuenta origen,
    # solo por moneda) Y baja la deuda del socio (egresos resta en la fórmula de
    # cuenta corriente) — Rental ahora le debe eso.
    from contabilidad.commands.movimientos import crear_movimiento
    from contabilidad.queries.reporte_mensual import reporte_mensual
    from contabilidad.queries.saldos import saldos

    mes = "2026-08"
    caja_pablo = _cuenta_id(conn, "Caja Pablo")
    antes = next(f for f in saldos(conn)["socios"] if f["nombre"] == "Caja Pablo")["saldo"]
    gastos_base = reporte_mensual(conn, mes)["gastos"]["total"]

    crear_movimiento(
        conn, tipo="gasto", monto=7000, cuenta_origen_id=caja_pablo,
        categoria_id=_categoria_id(conn), fecha=f"{mes}-10", por="test",
    )

    despues = next(f for f in saldos(conn)["socios"] if f["nombre"] == "Caja Pablo")["saldo"]
    assert despues == antes - 7000  # baja su deuda (o lo acerca a acreedor)
    assert reporte_mensual(conn, mes)["gastos"]["total"] == gastos_base + 7000  # cuenta en el P&L


def test_editar_movimiento_no_puede_reapuntar_retiro_a_cuenta_socio(conn):
    # El bloqueo de retiro/aporte contra una cuenta de socio vive en
    # _validar_cuentas_y_categoria, compartida por crear_movimiento Y
    # editar_movimiento — pero solo estaba probado por el camino de creación.
    # Mismo patrón de gap que el bug original de editar_movimiento (auditoría
    # 2026-07-02): no alcanza con que "debería andar igual", hay que confirmarlo.
    from contabilidad.commands.movimientos import crear_movimiento, editar_movimiento

    efectivo = _cuenta_id(conn, "Efectivo")
    caja_pablo = _cuenta_id(conn, "Caja Pablo")

    retiro = crear_movimiento(conn, tipo="retiro", monto=1000, cuenta_origen_id=efectivo, por="test")
    with pytest.raises(ValueError, match="retiro"):
        editar_movimiento(conn, retiro["id"], campos={"cuenta_origen_id": caja_pablo}, por="test")

    aporte = crear_movimiento(conn, tipo="aporte", monto=1000, cuenta_destino_id=efectivo, por="test")
    with pytest.raises(ValueError, match="aporte"):
        editar_movimiento(conn, aporte["id"], campos={"cuenta_destino_id": caja_pablo}, por="test")
