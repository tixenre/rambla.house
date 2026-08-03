"""La POSICIÓN acumulada de cada parte, contra Postgres REAL.

Cubre el cableado que los tests puros no pueden: que `partes_socios()`/`posiciones()`
devenguen de verdad contra la liquidación, y que el crédito de una CAJA contra otra
(Rental cobró lo que le corresponde al Estudio) exista como número — hasta ahora solo
vivía dentro de `rendicion(mes)`, con otro reloj y el signo al revés.

Cierra además el hueco que dejó la auditoría: **`partes_socios()` no tenía ni un test
propio**, así que la resta de `su_parte` —la operación que decide si un socio es
deudor o acreedor— nunca se ejerció contra Postgres; su única cobertura era el dict
`partes` inyectado a mano en los tests puros.

Las aserciones son por DELTA (antes vs. después de insertar), no absolutas: la base de
prueba puede tener pedidos saldados de otras corridas dentro del clean start.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`).

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_contabilidad_posicion_db.py -v -m integration
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

# Ids altos propios, para no chocar con los de los otros *_db.py.
EQ_TINCHO, EQ_ESTUDIO = 9_492_010, 9_492_011
PED_TINCHO, PED_ESTUDIO = 9_492_020, 9_492_021

# Dentro del clean start (LIQUIDACION_INICIO = 2026-06-01) y del rango que
# `posiciones()`/`partes_socios()` recorren (clean start → hoy).
FECHA_ALQUILER = "2026-06-05T08:00:00"
FECHA_FIN = "2026-06-06T20:00:00"
FECHA_PAGO = "2026-06-15T10:00:00"


@pytest.fixture
def conn():
    """Conexión transaccional: lo que inserta el test se DESCARTA con rollback."""
    from database import get_db, init_db

    init_db()
    c = get_db()
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def _cuenta_id(conn, nombre: str):
    row = conn.execute("SELECT id FROM cuentas WHERE nombre = %s", (nombre,)).fetchone()
    return row[0] if row else None


def _pos(conn) -> dict:
    from contabilidad.queries.posiciones import posiciones

    return {p["parte"]: p["pendiente"] for p in posiciones(conn)["partes"]}


def _saldo_cc(conn, socio: str) -> int:
    from contabilidad.queries.saldos import saldos

    for f in saldos(conn)["socios"]:
        if f["socio"] == socio:
            return int(f["saldo"])
    raise AssertionError(f"no encontré la cuenta corriente de {socio!r}")


def _pedido_saldado(conn, *, ped: int, equipo: int, dueno: str, monto: int,
                    cobro: str, nombre_eq: str, pagado: int | None = None):
    """Un pedido finalizado con un ítem de un equipo de `dueno` (para que la
    liquidación devengue de verdad) y el cobro a nombre de `cobro`. `pagado=None`
    → 100% pagado, o sea SALDADO (lo único que la liquidación cuenta)."""
    pagado = monto if pagado is None else pagado
    conn.execute(
        "INSERT INTO equipos (id, nombre, cantidad, dueno) VALUES (%s,%s,%s,%s)",
        (equipo, nombre_eq, 3, dueno),
    )
    conn.execute(
        """INSERT INTO alquileres (id, cliente_nombre, estado, fecha_desde, fecha_hasta,
                                   monto_total, monto_pagado)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (ped, "Cli posicion", "finalizado", FECHA_ALQUILER, FECHA_FIN, monto, pagado),
    )
    conn.execute(
        "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, subtotal) "
        "VALUES (%s,%s,%s,%s)",
        (ped, equipo, 1, monto),
    )
    conn.execute(
        """INSERT INTO alquiler_pagos (pedido_id, monto, concepto, destinatario, metodo, fecha)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (ped, pagado, "pago", cobro, "transferencia", FECHA_PAGO),
    )


def test_partes_socios_devenga_contra_la_liquidacion(conn):
    """El primer test de `partes_socios()` contra Postgres real. Un equipo de Tincho
    por $100.000 reparte 50/45/5 (Tincho/Rental/Pablo, `DEFAULT_MODELO`)."""
    from contabilidad.queries.saldos import partes_socios

    antes = partes_socios(conn)
    _pedido_saldado(conn, ped=PED_TINCHO, equipo=EQ_TINCHO, dueno="Tincho",
                    monto=100_000, cobro="Rental", nombre_eq="Equipo de Tincho")
    despues = partes_socios(conn)

    def delta(p):
        return despues.get(p, 0) - antes.get(p, 0)

    assert delta("Tincho") == 50_000
    assert delta("Rental") == 45_000
    assert delta("Pablo") == 5_000


def test_el_credito_del_estudio_contra_rental_existe(conn):
    """El caso que motivó la iniciativa. Al Estudio le corresponde el 100% de lo suyo
    (`DEFAULT_MODELO["Estudio"]`), pero lo cobró Rental → su caja no se mueve, y ese
    crédito no aparecía en ninguna vista de saldos."""
    from contabilidad.queries.saldos import saldos

    def caja_estudio():
        for f in saldos(conn)["cajas"]:
            if f["nombre"] == "Caja Estudio":
                return int(f["saldo"])
        raise AssertionError("falta la Caja Estudio en el seed")

    antes_pos, antes_caja = _pos(conn), caja_estudio()
    _pedido_saldado(conn, ped=PED_ESTUDIO, equipo=EQ_ESTUDIO, dueno="Estudio",
                    monto=120_000, cobro="Rental", nombre_eq="Espacio Estudio test")
    despues = _pos(conn)

    assert caja_estudio() == antes_caja, "el Estudio no cobró: su caja no se mueve"
    # Positivo = le falta recibir. Este es el número que no existía.
    assert despues["Estudio"] - antes_pos["Estudio"] == 120_000
    assert despues["Rental"] - antes_pos["Rental"] == -120_000


def test_posicion_y_cuenta_corriente_coinciden_contra_postgres(conn):
    """El candado cruzado que hoy no existe en ningún test: las dos lecturas del
    mismo hecho tienen que dar el mismo número (con el signo al revés)."""
    _pedido_saldado(conn, ped=PED_TINCHO, equipo=EQ_TINCHO, dueno="Tincho",
                    monto=100_000, cobro="Tincho", nombre_eq="Equipo de Tincho")
    assert _pos(conn)["Tincho"] == -_saldo_cc(conn, "Tincho")


def test_un_gasto_de_rental_no_mueve_ninguna_posicion(conn):
    """La prueba de fuego contra Postgres: un gasto operativo baja el cash del Fondo
    Rental pero NO cambia lo que Rental le debe a las otras partes."""
    from contabilidad.commands.movimientos import crear_movimiento

    _pedido_saldado(conn, ped=PED_TINCHO, equipo=EQ_TINCHO, dueno="Tincho",
                    monto=100_000, cobro="Rental", nombre_eq="Equipo de Tincho")
    antes = _pos(conn)

    cat = conn.execute(
        "SELECT id FROM gasto_categorias WHERE activa = TRUE ORDER BY id LIMIT 1"
    ).fetchone()
    crear_movimiento(conn, tipo="gasto", monto=50_000,
                     cuenta_origen_id=_cuenta_id(conn, "Fondo Rental"),
                     categoria_id=cat[0], fecha="2026-06-20", por="test")

    assert _pos(conn) == antes


def test_un_reparto_sin_marcar_igual_cuenta_para_la_posicion(conn):
    """El botón "Me pagó / Le cargué" de la ficha del socio crea una `transferencia`
    SIN `es_rendicion`, así que `ya_transferido` (la vista mensual) no la ve. La
    posición sí: el clasificador mira las CUENTAS que toca, no la marca."""
    from contabilidad.commands.movimientos import crear_movimiento

    _pedido_saldado(conn, ped=PED_TINCHO, equipo=EQ_TINCHO, dueno="Tincho",
                    monto=100_000, cobro="Tincho", nombre_eq="Equipo de Tincho")
    antes = _pos(conn)

    crear_movimiento(conn, tipo="transferencia", monto=40_000,
                     cuenta_origen_id=_cuenta_id(conn, "Caja Tincho"),
                     cuenta_destino_id=_cuenta_id(conn, "Fondo Rental"),
                     fecha="2026-06-20", por="test")  # sin es_rendicion, a propósito

    assert _pos(conn)["Tincho"] - antes["Tincho"] == 40_000, (
        "el reparto sin marcar tiene que acercar la posición de Tincho a cero"
    )
    # Y sigue coincidiendo con su cuenta corriente.
    assert _pos(conn)["Tincho"] == -_saldo_cc(conn, "Tincho")


def test_deudor_acumulado_aunque_el_mes_diga_que_le_falta_cobrar(conn):
    """El escenario EXACTO del incidente que disparó esta iniciativa, que hasta ahora
    ningún test cruzaba.

    Tincho arrastra una deuda acumulada grande (arranque pre-sistema) y en el mes
    devenga $50.000 que cobró Rental. La rendición MENSUAL lo lee como "a Tincho le
    falta recibir" y sugiere `Rental → Tincho` — mientras el acumulado dice que
    Tincho le debe plata a Rental. Transferirle de verdad esos $50.000 le SUBE la
    deuda: correcto aritméticamente, absurdo operativamente.

    Este test fija lo que resuelve esta fase: la posición acumulada existe, es la
    verdad, y dice lo contrario que el mes."""
    from contabilidad.commands.cuentas import editar_cuenta
    from contabilidad.queries.rendicion import rendicion

    cta = _cuenta_id(conn, "Caja Tincho")
    assert cta, "la Caja Tincho es parte del seed de init_db()"
    editar_cuenta(conn, cta, campos={"saldo_inicial": 734_088}, por="test")

    _pedido_saldado(conn, ped=PED_TINCHO, equipo=EQ_TINCHO, dueno="Tincho",
                    monto=100_000, cobro="Rental", nombre_eq="Equipo de Tincho")

    # Acumulado: Tincho TIENE DE MÁS (le debe a Rental) pese a lo devengado del mes.
    assert _pos(conn)["Tincho"] < 0
    assert _saldo_cc(conn, "Tincho") > 0  # el mismo hecho, signo opuesto

    # Mensual: el mismo Tincho aparece como "le falta recibir". Las dos lecturas
    # conviven; la acumulada es la que manda para decidir si mover plata.
    by = {p["persona"]: p for p in rendicion(conn, "2026-06")["personas"]}
    assert by["Tincho"]["pendiente"] > 0, "en el mes devengó y no cobró"


def test_float_de_pedidos_a_medio_cobrar_se_reporta(conn):
    """Parte de la posición viene de plata cobrada de pedidos que TODAVÍA no se
    terminaron de cobrar: está en la mano de alguien pero su devengado no existe aún
    (la liquidación solo cuenta pedidos saldados). Sin nombrarlo, el número de la
    posición incluiría algo que no es repartible todavía y nadie lo sabría."""
    from contabilidad.queries.posiciones import posiciones

    antes = posiciones(conn)["float_sin_saldar"]
    _pedido_saldado(conn, ped=PED_TINCHO, equipo=EQ_TINCHO, dueno="Tincho",
                    monto=100_000, cobro="Rental", nombre_eq="Equipo de Tincho",
                    pagado=30_000)  # seña: NO saldado
    assert posiciones(conn)["float_sin_saldar"] - antes == 30_000


def test_la_sena_de_un_pedido_abierto_va_a_en_curso_no_a_repartible(conn):
    """El escenario EXACTO del incidente 2026-08-03: Rental cobra una seña de un
    pedido que todavía no cerró. La tarjeta decía "tiene de más" (pendiente) y el
    dueño lo leyó como deuda — pero esa plata no se reparte hasta que el pedido
    cierre. `repartible` no se mueve; `en_curso` la nombra; los `sugeridos` NO
    proponen transferirla."""
    from contabilidad.queries.posiciones import posiciones

    antes = {p["parte"]: p for p in posiciones(conn)["partes"]}

    _pedido_saldado(conn, ped=PED_TINCHO, equipo=EQ_TINCHO, dueno="Tincho",
                    monto=100_000, cobro="Rental", nombre_eq="Equipo de Tincho",
                    pagado=30_000)  # seña: el pedido queda ABIERTO

    pos = posiciones(conn)
    despues = {p["parte"]: p for p in pos["partes"]}

    r_antes, r_despues = antes["Rental"], despues["Rental"]
    assert r_despues["en_curso"] - r_antes["en_curso"] == 30_000, \
        "la seña tiene que aparecer como 'en curso'"
    assert r_despues["repartible"] == r_antes["repartible"], \
        "la seña NO mueve lo repartible: el pedido no cerró, nada devengó"
    assert r_despues["pendiente"] - r_antes["pendiente"] == -30_000, \
        "el acumulado total sí la cuenta (identidad pendiente == repartible − en_curso)"
    # Y ninguna transferencia sugerida intenta repartir la seña: Tincho (el dueño
    # del equipo) todavía no devengó nada de este pedido.
    for s in pos["sugeridos"]:
        assert not (s["de"] == "Rental" and s["a"] == "Tincho" and s["monto"] >= 30_000), s


def test_reconciliacion_caza_devengado_sin_cuenta(conn):
    """Un beneficiario del modelo de comisiones que no tiene caja donde verse: su
    plata se devenga contra nadie. Es el "pendiente conocido" que quedó anotado al
    construir el motor y hasta ahora no tenía red."""
    import json

    from contabilidad.queries.reconciliacion import reconciliar

    _pedido_saldado(conn, ped=PED_TINCHO, equipo=EQ_TINCHO, dueno="Tincho",
                    monto=100_000, cobro="Rental", nombre_eq="Equipo de Tincho")
    assert reconciliar(conn)["devengado_sin_cuenta"]["cantidad"] == 0

    conn.execute(
        """INSERT INTO app_settings (key, value) VALUES ('comisiones_modelo', %s)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        (json.dumps({"Tincho": {"Fantasma": 100}}),),
    )
    out = reconciliar(conn)
    assert out["devengado_sin_cuenta"]["cantidad"] == 1
    assert out["devengado_sin_cuenta"]["beneficiarios"][0]["beneficiario"] == "Fantasma"
    assert out["devengado_sin_cuenta"]["monto"] == 100_000
    assert out["ok"] is False
