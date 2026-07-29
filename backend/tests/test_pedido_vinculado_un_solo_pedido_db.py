"""Un pedido de alquiler + sus turnos del Estudio vinculados son UNA sola venta:
una factura, un total, sin "pedidos fantasmas" en ninguna superficie de cara al
dueño ni al cliente (#1308 — "no quiero dobles pedidos fantasmas... quiero
cobrar una sola cosa y facturar y establecer el estado").

Cubre lo que la tanda anterior NO cubría: la factura combinada + el gate de
facturar el turno solo, el mail fantasma del recordatorio de retiro, el portal
del cliente, la ficha admin del cliente, el dashboard y la liquidación.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_pedido_vinculado_un_solo_pedido_db.py -v -m integration
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

import main  # noqa: E402 — importado después del gating, mismo patrón que los otros *_db.py

CLIENTE_ID = 9_499_102
PRINCIPAL_ID = 9_499_110
TURNO_ID = 9_499_111
TURNO_SUELTO_ID = 9_499_120
EQ_ID = 9_499_101

MONTO_PRINCIPAL = 40_000
MONTO_TURNO = 30_000

_IDS = (PRINCIPAL_ID, TURNO_ID, TURNO_SUELTO_ID)

from auth.session import signer  # noqa: E402 — después del gating, como el resto del módulo

_COOKIE = "session=" + signer.dumps(
    {
        "email": "unsolopedido@test.com",
        "role": "cliente",
        "cliente_id": CLIENTE_ID,
        "jti": "unsolopedido-cli",
    }
)


@pytest.fixture
def _sesion_cliente(monkeypatch):
    """La cookie firmada de arriba entra; la allowlist de sesiones se stubea
    (mismo patrón que `test_cliente_portal_pedidos_lista_detalle_db.py`)."""
    monkeypatch.setattr("auth.queries.sessions.is_active", lambda jti: {"jti": jti})


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN (%s, %s, %s)", _IDS
    )
    conn.execute("DELETE FROM alquiler_pagos WHERE pedido_id IN (%s, %s, %s)", _IDS)
    conn.execute("DELETE FROM alquileres WHERE cliente_id = %s", (CLIENTE_ID,))
    conn.execute("DELETE FROM equipos WHERE id = %s", (EQ_ID,))
    conn.execute("DELETE FROM clientes WHERE id = %s", (CLIENTE_ID,))


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    from database import get_db

    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO clientes (id, nombre, apellido, email, telefono) "
            "VALUES (%s,'UnSolo','Pedido','unsolopedido@test.com','+5491100009102')",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada) VALUES (%s,%s,5,10000)",
            (EQ_ID, "Equipo test (un solo pedido)"),
        )
        # Principal: alquiler normal, confirmado, con un ítem real.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_email, "
            "cliente_telefono, estado, tipo, fecha_desde, fecha_hasta, numero_pedido, "
            "monto_total, monto_pagado) "
            "VALUES (%s,%s,'Un Solo Pedido','unsolopedido@test.com','+5491100009102',"
            "'confirmado','diaria','2033-06-01','2033-06-05',949910,%s,0)",
            (PRINCIPAL_ID, CLIENTE_ID, MONTO_PRINCIPAL),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal) "
            "VALUES (%s,%s,1,10000,%s)",
            (PRINCIPAL_ID, EQ_ID, MONTO_PRINCIPAL),
        )
        # Turno del Estudio VINCULADO al principal — franja horaria propia.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_email, "
            "cliente_telefono, estado, tipo, fecha_desde, fecha_hasta, numero_pedido, "
            "monto_total, monto_pagado, pedido_principal_id) "
            "VALUES (%s,%s,'Un Solo Pedido','unsolopedido@test.com','+5491100009102',"
            "'confirmado','estudio','2033-06-02 10:00','2033-06-02 12:00',949911,%s,0,%s)",
            (TURNO_ID, CLIENTE_ID, MONTO_TURNO, PRINCIPAL_ID),
        )
        conn.execute(
            "INSERT INTO alquiler_items (pedido_id, equipo_id, cantidad, precio_jornada, subtotal, cobro_modo) "
            "VALUES (%s,%s,1,%s,%s,'fijo')",
            (TURNO_ID, EQ_ID, MONTO_TURNO, MONTO_TURNO),
        )
        # Turno del Estudio SUELTO (sin principal) — sigue siendo un pedido de
        # primera clase: guarda contra confundir el eje con `tipo='estudio'`.
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_email, "
            "cliente_telefono, estado, tipo, fecha_desde, fecha_hasta, numero_pedido, "
            "monto_total, monto_pagado) "
            "VALUES (%s,%s,'Un Solo Pedido','unsolopedido@test.com','+5491100009102',"
            "'confirmado','estudio','2033-06-20 10:00','2033-06-20 12:00',949912,15000,0)",
            (TURNO_SUELTO_ID, CLIENTE_ID),
        )
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


@pytest.fixture(scope="module")
def client_con_db():
    from database import init_db
    from fastapi.testclient import TestClient

    init_db()
    with TestClient(main.app, raise_server_exceptions=True) as c:
        if main.db_init_thread is not None:
            main.db_init_thread.join(timeout=60)
        yield c


# ── La factura es UNA sola, e incluye la plata del Estudio ────────────────────

def test_la_factura_del_principal_incluye_la_plata_del_turno(client_con_db, setup):
    """Discrimina: sin combinar, `monto_total` del pedido cargado para facturar
    sería solo el del alquiler (40.000) — la plata del Estudio quedaría afuera
    del comprobante."""
    from database import get_db
    from services.facturacion.engine import _get_pedido

    conn = get_db()
    try:
        pedido = _get_pedido(conn, PRINCIPAL_ID)
    finally:
        conn.close()

    assert pedido["monto_total"] == MONTO_PRINCIPAL + MONTO_TURNO
    assert [t["pedido_id"] for t in pedido["turnos_combinados"]] == [TURNO_ID]


def test_un_turno_cancelado_no_entra_en_la_factura(client_con_db, setup):
    from database import get_db
    from services.facturacion.engine import _get_pedido

    conn = get_db()
    try:
        conn.execute("UPDATE alquileres SET estado='cancelado' WHERE id=%s", (TURNO_ID,))
        conn.commit()
        pedido = _get_pedido(conn, PRINCIPAL_ID)
    finally:
        conn.close()

    assert pedido["monto_total"] == MONTO_PRINCIPAL
    assert "turnos_combinados" not in pedido


def test_el_periodo_de_servicio_cubre_la_franja_del_turno(client_con_db, setup):
    """El comprobante declara el período real de lo que factura: si el turno cae
    fuera del rango de días del alquiler, el período se expande."""
    from database import get_db
    from services.facturacion.engine import _get_pedido

    conn = get_db()
    try:
        # Turno ANTES del alquiler (que arranca el 2033-06-01).
        conn.execute(
            "UPDATE alquileres SET fecha_desde='2033-05-20 10:00', "
            "fecha_hasta='2033-05-20 12:00' WHERE id=%s",
            (TURNO_ID,),
        )
        conn.commit()
        pedido = _get_pedido(conn, PRINCIPAL_ID)
    finally:
        conn.close()

    assert pedido["fecha_desde"].strftime("%Y-%m-%d") == "2033-05-20"
    assert pedido["fecha_hasta"].strftime("%Y-%m-%d") == "2033-06-05"


def test_el_turno_vinculado_no_se_factura_solo(client_con_db, setup):
    """Sin este gate se podía emitir DOS veces la misma plata: la del principal
    (que ahora la incluye) y la del turno por su cuenta."""
    from database import get_db
    from services.facturacion.engine import _get_pedido, _rechazar_si_es_turno_vinculado

    conn = get_db()
    try:
        turno = _get_pedido(conn, TURNO_ID)
    finally:
        conn.close()

    with pytest.raises(ValueError, match="pedido principal"):
        _rechazar_si_es_turno_vinculado(turno)


def test_un_turno_suelto_si_se_factura(client_con_db, setup):
    """El gate es por el EJE, no por `tipo='estudio'`."""
    from database import get_db
    from services.facturacion.engine import _get_pedido, _rechazar_si_es_turno_vinculado

    conn = get_db()
    try:
        suelto = _get_pedido(conn, TURNO_SUELTO_ID)
    finally:
        conn.close()

    _rechazar_si_es_turno_vinculado(suelto)  # no levanta


# ── Nada de mails fantasma ───────────────────────────────────────────────────

def test_el_turno_vinculado_no_recibe_recordatorio_de_retiro(client_con_db, setup):
    """Era un mail REAL al cliente: "mañana retirás tu pedido #<turno>", además
    del recordatorio del pedido verdadero."""
    from database import get_db, now_ar
    from jobs.recordatorios import _pedidos_para_retiro

    conn = get_db()
    try:
        # Las fechas del set son lejanas; mover ambos turnos a "mañana".
        manana = now_ar().replace(hour=10, minute=0, second=0, microsecond=0)
        from datetime import timedelta

        manana = manana + timedelta(days=1)
        for pid in (PRINCIPAL_ID, TURNO_ID, TURNO_SUELTO_ID):
            conn.execute(
                "UPDATE alquileres SET fecha_desde=%s, fecha_hasta=%s WHERE id=%s",
                (manana, manana + timedelta(hours=2), pid),
            )
        conn.commit()
        ids = {p["id"] for p in _pedidos_para_retiro(conn, now_ar(), 1)}
    finally:
        conn.close()

    assert PRINCIPAL_ID in ids, "el pedido real sí tiene que recordarse"
    assert TURNO_ID not in ids, "el turno vinculado NO manda su propio recordatorio"
    assert TURNO_SUELTO_ID in ids, "un turno del Estudio suelto sí es un evento propio"


# ── Portal del cliente: un pedido, un total ──────────────────────────────────

def test_portal_no_lista_el_turno_y_su_total_es_el_combinado(client_con_db, setup, _sesion_cliente):
    """Discrimina: sin el filtro el cliente veía DOS cards (dos números, dos
    totales); sin la consolidación vería una card con la plata del Estudio
    faltante."""
    r = client_con_db.get("/api/cliente/pedidos", headers={"Cookie": _COOKIE})
    assert r.status_code == 200, r.text
    por_id = {p["id"]: p for p in r.json()}

    assert TURNO_ID not in por_id, "el turno vinculado no es un pedido del cliente"
    assert TURNO_SUELTO_ID in por_id, "un turno del Estudio suelto sí lo es"
    assert por_id[PRINCIPAL_ID]["monto_total"] == MONTO_PRINCIPAL + MONTO_TURNO


def test_portal_404_en_el_detalle_del_turno_vinculado(client_con_db, setup, _sesion_cliente):
    r = client_con_db.get(f"/api/cliente/pedidos/{TURNO_ID}", headers={"Cookie": _COOKIE})
    assert r.status_code == 404

    ok = client_con_db.get(f"/api/cliente/pedidos/{PRINCIPAL_ID}", headers={"Cookie": _COOKIE})
    assert ok.status_code == 200
    assert ok.json()["monto_total"] == MONTO_PRINCIPAL + MONTO_TURNO


def test_portal_no_puede_cancelar_el_turno_vinculado(client_con_db, setup, _sesion_cliente):
    """Era el único write que el cliente podía hacerle a la fila fantasma."""
    r = client_con_db.patch(
        f"/api/cliente/pedidos/{TURNO_ID}/cancelar", headers={"Cookie": _COOKIE}
    )
    assert r.status_code == 404


def test_combinar_turnos_suma_pagado_y_recalcula_iva(client_con_db, setup):
    """El IVA se recalcula sobre el neto COMBINADO — no se suman los IVA por
    fila (el turno no tiene perfil fiscal propio)."""
    from database import get_db, row_to_dict
    from services.finanzas_flujo.pedido import combinar_turnos_vinculados

    conn = get_db()
    try:
        conn.execute(
            "UPDATE alquileres SET monto_pagado=%s WHERE id=%s", (10_000, PRINCIPAL_ID)
        )
        conn.execute(
            "UPDATE alquileres SET monto_pagado=%s WHERE id=%s", (5_000, TURNO_ID)
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM alquileres WHERE id=%s", (PRINCIPAL_ID,)
        ).fetchone()
        p = row_to_dict(row)
        p["con_iva"] = True
        combinar_turnos_vinculados(conn, p)
    finally:
        conn.close()

    assert p["monto_total"] == MONTO_PRINCIPAL + MONTO_TURNO
    assert p["monto_pagado"] == 15_000
    assert p["iva_monto"] == round((MONTO_PRINCIPAL + MONTO_TURNO) * 0.21)


# ── Ficha admin del cliente ──────────────────────────────────────────────────

def test_historial_del_cliente_consolida_en_una_fila(client_con_db, setup):
    """Antes mostraba 2 filas (el pedido y su turno). Ahora una sola, con la
    plata del turno adentro — ocultar sin consolidar habría subestimado el
    total gastado."""
    from clientes.queries.historial import resumen
    from database import get_db

    conn = get_db()
    try:
        filas = resumen(conn, CLIENTE_ID)
    finally:
        conn.close()

    por_id = {f["id"]: f for f in filas}
    assert TURNO_ID not in por_id, "el turno vinculado no es una fila propia"
    assert TURNO_SUELTO_ID in por_id, "el turno suelto sí"
    assert por_id[PRINCIPAL_ID]["monto_total"] == MONTO_PRINCIPAL + MONTO_TURNO
    assert por_id[PRINCIPAL_ID]["turnos_estudio"] == 1
    assert por_id[TURNO_SUELTO_ID]["turnos_estudio"] == 0


# ── Dashboard admin ──────────────────────────────────────────────────────────

def test_dashboard_no_cuenta_el_turno_como_pedido_activo(client_con_db, setup):
    r = client_con_db.get("/api/dashboard")
    assert r.status_code == 200, r.text
    ids_salen = {x["id"] for x in r.json().get("salen_hoy", [])}
    assert TURNO_ID not in ids_salen


# ── Liquidación: el aporte va bajo el número del pedido real ─────────────────

# ── Sacar un turno del pedido lo BORRA, no lo cancela ────────────────────────

def test_sacar_un_turno_lo_borra_de_verdad(client_con_db, setup):
    """Pedido del dueño: "que se comporte como cuando saco un equipo, simplemente
    se borra y listo" — antes quedaba una tarjeta "Cancelado" colgada en la
    sección. Hard delete: la fila y sus ítems desaparecen."""
    from database import get_db

    r = client_con_db.delete(f"/api/alquileres/{TURNO_ID}")
    assert r.status_code == 204, r.text

    conn = get_db()
    try:
        assert conn.execute(
            "SELECT id FROM alquileres WHERE id = %s", (TURNO_ID,)
        ).fetchone() is None
        assert conn.execute(
            "SELECT id FROM alquiler_items WHERE pedido_id = %s", (TURNO_ID,)
        ).fetchone() is None
        # El principal queda intacto, sin el turno.
        assert conn.execute(
            "SELECT id FROM alquileres WHERE id = %s", (PRINCIPAL_ID,)
        ).fetchone() is not None
    finally:
        conn.close()


def test_no_se_puede_sacar_un_turno_con_plata_cobrada(client_con_db, setup):
    """El pago combinado escribe las filas de `alquiler_pagos` con el `pedido_id`
    del turno: borrarlo con plata encima haría desaparecer un cobro real."""
    from database import get_db

    conn = get_db()
    try:
        conn.execute(
            "UPDATE alquileres SET monto_pagado = %s WHERE id = %s", (10_000, TURNO_ID)
        )
        conn.commit()
    finally:
        conn.close()

    r = client_con_db.delete(f"/api/alquileres/{TURNO_ID}")
    assert r.status_code == 409, r.text
    assert "plata cobrada" in r.json()["detail"]


def test_un_pedido_normal_con_plata_se_sigue_pudiendo_borrar(client_con_db, setup):
    """El guard es SOLO para turnos vinculados — el borrado de un pedido normal
    (con su propia "Zona peligrosa") no cambia."""
    from database import get_db

    conn = get_db()
    try:
        conn.execute(
            "UPDATE alquileres SET monto_pagado = %s WHERE id = %s", (10_000, PRINCIPAL_ID)
        )
        conn.commit()
    finally:
        conn.close()

    r = client_con_db.delete(f"/api/alquileres/{PRINCIPAL_ID}")
    assert r.status_code == 204, r.text


def test_liquidacion_agrupa_el_turno_bajo_el_numero_del_principal(client_con_db, setup):
    """El aporte del Estudio deja de figurar como un pedido separado en el
    reporte — se agrupa bajo la venta real. La ATRIBUCIÓN por dueño no cambia."""
    from database import get_db
    from reportes.liquidacion import filas_atribucion

    conn = get_db()
    try:
        conn.execute(
            "UPDATE alquileres SET monto_pagado = monto_total WHERE id IN (%s, %s)",
            (PRINCIPAL_ID, TURNO_ID),
        )
        for pid, monto in ((PRINCIPAL_ID, MONTO_PRINCIPAL), (TURNO_ID, MONTO_TURNO)):
            conn.execute(
                "INSERT INTO alquiler_pagos (pedido_id, monto, concepto, fecha) "
                "VALUES (%s,%s,'test','2033-06-10')",
                (pid, monto),
            )
        conn.commit()
        filas = filas_atribucion(conn, "2033-06-01", "2033-06-30")
    finally:
        conn.close()

    del_set = [f for f in filas if f["pedido_id"] in (PRINCIPAL_ID, TURNO_ID)]
    assert del_set, "el pedido tiene que aparecer en la liquidación"
    # Ninguna fila se identifica con el turno: todas caen bajo el principal.
    assert all(f["pedido_id"] == PRINCIPAL_ID for f in del_set)
    assert all(f["numero_pedido"] == 949910 for f in del_set)


# ── Borrar el principal se lleva sus turnos ──────────────────────────────────


def _existe(pedido_id: int) -> bool:
    from database import get_db

    conn = get_db()
    try:
        return conn.execute(
            "SELECT 1 FROM alquileres WHERE id = %s", (pedido_id,)
        ).fetchone() is not None
    finally:
        conn.close()


def test_borrar_el_principal_se_lleva_su_turno(client_con_db, setup):
    """Discrimina: la FK es `ON DELETE SET NULL`, así que sin el borrado en
    cascada el turno SOBREVIVÍA solo —con su número y su estado— y volvía a la
    lista como un pedido más. Ese es el "doble pedido fantasma" (uno con número
    y otro sin) que reportó el dueño después de borrar el pedido que los unía."""
    r = client_con_db.delete(f"/api/alquileres/{PRINCIPAL_ID}")
    assert r.status_code == 204, r.text
    assert not _existe(PRINCIPAL_ID)
    assert not _existe(TURNO_ID), "el turno vinculado tiene que irse con su pedido"
    # El turno SUELTO no se toca: es un pedido de primera clase del Estudio.
    assert _existe(TURNO_SUELTO_ID)


def test_no_se_borra_un_pedido_cuyo_turno_tiene_plata_cobrada(client_con_db, setup):
    """La plata cobrada no desaparece en silencio: si el turno tiene un cobro,
    se frena TODO el borrado (ni el pedido ni el turno), igual que la ✕ del
    turno suelto."""
    from database import get_db

    conn = get_db()
    try:
        conn.execute(
            "UPDATE alquileres SET monto_pagado = 10000 WHERE id = %s", (TURNO_ID,)
        )
        conn.commit()
    finally:
        conn.close()

    r = client_con_db.delete(f"/api/alquileres/{PRINCIPAL_ID}")
    assert r.status_code == 409, r.text
    assert "plata cobrada" in r.json()["detail"]
    assert _existe(PRINCIPAL_ID) and _existe(TURNO_ID), "no se borra nada a medias"
