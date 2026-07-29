"""Descuento PROPIO de un turno del Estudio (#1308) contra Postgres REAL.

El dueño pidió que el resumen del pedido se lea en dos partes (equipos /
turnos) y que **el descuento sea por sección** — el turno gana el suyo, aparte
del de los equipos.

Lo que estos tests fijan:

1. El descuento del turno se aplica de verdad a `alquileres.monto_total` (que
   es NETO), tanto en % como en $ fijo.
2. **No hace falta una columna nueva:** un turno ES una fila de `alquileres`,
   así que reusa `descuento_pct`/`descuento_manual_tipo`/`descuento_manual_monto`.
3. El descuento **sobrevive** a cualquier otra edición del turno (mover la
   franja, agregar un suelto): `None` en el PATCH = "no lo toques". Sin esto,
   tocar la hora borraría el descuento en silencio — plata perdida.
4. La **promo (combo) no acumula** el descuento global (Fase C-3, #1219) — su
   precio ya trae el suyo horneado. Es lo que hace que `monto_total` coincida
   con lo que reconstruye `desglose_de_pedido`.
5. El invariante que lo ata todo: `monto_total == desglose_de_pedido(...)["monto_neto"]`,
   que es EXACTAMENTE lo que compara el chequeo `desglose_divergente` de la
   reconciliación (`reportes/reconciliacion.py`) — que sí cubre los pedidos del
   Estudio. Si el motor del Estudio descontara "a mano" en vez de pasar por
   `calcular_total`, este assert falla y el dueño recibiría el mail diario de
   reconciliación.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_turno_estudio_descuento_db.py -v -m integration
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

CLIENTE_ID = 9_477_001
PEDIDO_PRINCIPAL_ID = 9_477_010
PRECIO_HORA = 10_000
HORAS = 2
ESPACIO = PRECIO_HORA * HORAS  # 20.000


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquiler_items WHERE pedido_id IN "
        "(SELECT id FROM alquileres WHERE cliente_id = %s OR id = %s)",
        (CLIENTE_ID, PEDIDO_PRINCIPAL_ID),
    )
    conn.execute(
        "DELETE FROM alquileres WHERE cliente_id = %s OR id = %s",
        (CLIENTE_ID, PEDIDO_PRINCIPAL_ID),
    )
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
            "VALUES (%s,'Descuento','Turno','descuento.turno@test.com','+5491100000011')",
            (CLIENTE_ID,),
        )
        conn.execute(
            "INSERT INTO alquileres (id, cliente_id, cliente_nombre, cliente_email, "
            "estado, fecha_desde, fecha_hasta, numero_pedido) "
            "VALUES (%s,%s,'Descuento Turno','descuento.turno@test.com',"
            "'confirmado','2031-06-01','2031-06-05',947701)",
            (PEDIDO_PRINCIPAL_ID, CLIENTE_ID),
        )
        conn.execute(
            "UPDATE estudio SET precio_hora=%s, buffer_horas=0, min_horas=1, "
            "open_hour=0, close_hour=24, anticipacion_min_horas=0 WHERE id=1",
            (PRECIO_HORA,),
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


def _crear_turno(client, *, fecha="2031-06-02", start="10:00", horas=HORAS):
    r = client.post(
        "/api/admin/estudio/reservas",
        json={
            "fecha": fecha, "start": start, "horas": horas,
            "pedido_principal_id": PEDIDO_PRINCIPAL_ID,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _fila(pedido_id: int) -> dict:
    from database import get_db, row_to_dict

    conn = get_db()
    try:
        return row_to_dict(
            conn.execute(
                "SELECT monto_total, descuento_pct, descuento_manual_tipo, "
                "descuento_manual_monto FROM alquileres WHERE id=%s",
                (pedido_id,),
            ).fetchone()
        )
    finally:
        conn.close()


def _neto_recalculado(pedido_id: int) -> int:
    """El neto que reconstruye el desglose GENÉRICO desde los ítems — el mismo
    número que compara `desglose_divergente` en la reconciliación."""
    from database import get_db, row_to_dict
    from services.finanzas_flujo.pedido import desglose_de_pedido

    conn = get_db()
    try:
        pedido = row_to_dict(
            conn.execute(
                "SELECT id, fecha_desde, fecha_hasta, monto_total, cliente_id, "
                "descuento_pct, descuento_jornadas_pct, descuento_cliente_pct, "
                "descuento_manual_tipo, descuento_manual_monto "
                "FROM alquileres WHERE id=%s",
                (pedido_id,),
            ).fetchone()
        )
        pedido["items"] = [
            row_to_dict(r)
            for r in conn.execute(
                "SELECT pi.equipo_id, pi.cantidad, pi.precio_jornada, pi.cobro_modo, "
                "e.tipo AS equipo_tipo FROM alquiler_items pi "
                "LEFT JOIN equipos e ON e.id = pi.equipo_id WHERE pi.pedido_id=%s",
                (pedido_id,),
            ).fetchall()
        ]
        return int(round(desglose_de_pedido(conn, pedido)["monto_neto"]))
    finally:
        conn.close()


def test_turno_nace_sin_descuento(client_con_db, setup):
    """El alta no ofrece descuento: el total es el bruto puro. Es la línea base
    contra la que se mide que el descuento efectivamente descuenta."""
    turno_id = _crear_turno(client_con_db)
    fila = _fila(turno_id)
    assert fila["monto_total"] == ESPACIO
    assert (fila["descuento_pct"] or 0) == 0


def test_descuento_pct_baja_el_monto_total_del_turno(client_con_db, setup):
    """DISCRIMINANTE: sin aplicar el descuento en el motor del Estudio,
    `monto_total` seguiría siendo 20.000 y este assert falla."""
    turno_id = _crear_turno(client_con_db)
    r = client_con_db.patch(
        f"/api/admin/estudio/reservas/{turno_id}",
        json={"descuento_pct": 25, "descuento_manual_tipo": "pct"},
    )
    assert r.status_code == 200, r.text

    fila = _fila(turno_id)
    assert fila["monto_total"] == 15_000  # 20.000 − 25%
    assert float(fila["descuento_pct"]) == 25.0
    # El invariante que mantiene callada a la reconciliación.
    assert _neto_recalculado(turno_id) == fila["monto_total"]


def test_descuento_en_pesos_fijos(client_con_db, setup):
    turno_id = _crear_turno(client_con_db)
    r = client_con_db.patch(
        f"/api/admin/estudio/reservas/{turno_id}",
        json={"descuento_manual_tipo": "monto", "descuento_manual_monto": 3_000},
    )
    assert r.status_code == 200, r.text

    fila = _fila(turno_id)
    assert fila["monto_total"] == ESPACIO - 3_000
    assert fila["descuento_manual_tipo"] == "monto"
    assert fila["descuento_manual_monto"] == 3_000
    assert _neto_recalculado(turno_id) == fila["monto_total"]


def test_el_descuento_sobrevive_a_editar_la_franja(client_con_db, setup):
    """DISCRIMINANTE del contrato de `None`: mover la hora manda un PATCH SIN
    campos de descuento. Si `None` significara "resetear" (como en
    `espacio_monto`), el descuento se borraría en silencio y el turno volvería
    a 40.000 — plata perdida sin que nada avise."""
    turno_id = _crear_turno(client_con_db)
    client_con_db.patch(
        f"/api/admin/estudio/reservas/{turno_id}", json={"descuento_pct": 25}
    )
    assert _fila(turno_id)["monto_total"] == 15_000

    # Ahora solo se reprograma: 4 horas en vez de 2 → bruto 40.000.
    r = client_con_db.patch(f"/api/admin/estudio/reservas/{turno_id}", json={"horas": 4})
    assert r.status_code == 200, r.text

    fila = _fila(turno_id)
    assert float(fila["descuento_pct"]) == 25.0, "el descuento se perdió al mover la franja"
    assert fila["monto_total"] == 30_000  # 40.000 − 25%
    assert _neto_recalculado(turno_id) == fila["monto_total"]


def test_descuento_cero_lo_saca(client_con_db, setup):
    """Mandar 0 explícito SÍ lo borra (0 es el sentinel de "sin override",
    mismo criterio que un pedido normal) — distinto de omitir el campo."""
    turno_id = _crear_turno(client_con_db)
    client_con_db.patch(
        f"/api/admin/estudio/reservas/{turno_id}", json={"descuento_pct": 25}
    )
    assert _fila(turno_id)["monto_total"] == 15_000

    r = client_con_db.patch(
        f"/api/admin/estudio/reservas/{turno_id}", json={"descuento_pct": 0}
    )
    assert r.status_code == 200, r.text
    assert _fila(turno_id)["monto_total"] == ESPACIO


def test_la_cotizacion_previa_muestra_el_mismo_neto_que_se_persiste(client_con_db, setup):
    """El preview no puede mostrar un número distinto al que va a guardar —
    misma clase de desfasaje que el del pedido #445."""
    turno_id = _crear_turno(client_con_db)
    r = client_con_db.get(
        "/api/admin/estudio/reservas/cotizar",
        params={
            "fecha": "2031-06-02", "start": "10:00", "horas": HORAS,
            "pedido_id": turno_id, "descuento_pct": 25,
        },
    )
    assert r.status_code == 200, r.text
    cotiz = r.json()
    assert cotiz["bruto"] == ESPACIO
    assert cotiz["descuento_monto"] == 5_000
    assert cotiz["monto_total"] == 15_000

    client_con_db.patch(
        f"/api/admin/estudio/reservas/{turno_id}", json={"descuento_pct": 25}
    )
    assert _fila(turno_id)["monto_total"] == cotiz["monto_total"]


def test_descuento_invalido_rechazado(client_con_db, setup):
    """Los validadores son los MISMOS que los de un pedido (importados, no
    copiados): un % fuera de rango se rechaza igual acá."""
    turno_id = _crear_turno(client_con_db)
    r = client_con_db.patch(
        f"/api/admin/estudio/reservas/{turno_id}", json={"descuento_pct": 150}
    )
    assert r.status_code == 422, r.text
    assert _fila(turno_id)["monto_total"] == ESPACIO


def test_cotizar_del_pedido_principal_devuelve_el_combinado_con_iva(client_con_db, setup):
    """El rail muestra UN total con IVA para las dos partes. El IVA sobre el
    neto COMBINADO lo resuelve el backend: sumar el total del principal (con
    IVA) a los turnos (netos) daría de menos.

    DISCRIMINANTE: sin el bloque `combinado` de `/api/cotizar`, `combinado` es
    None y estos asserts fallan.
    """
    from database import get_db

    # Cliente RI → el pedido lleva IVA.
    conn = get_db()
    try:
        conn.execute(
            "UPDATE clientes SET perfil_impuestos='responsable_inscripto' WHERE id=%s",
            (CLIENTE_ID,),
        )
        conn.commit()
    finally:
        conn.close()

    turno_id = _crear_turno(client_con_db)
    client_con_db.patch(
        f"/api/admin/estudio/reservas/{turno_id}", json={"descuento_pct": 25}
    )
    assert _fila(turno_id)["monto_total"] == 15_000

    r = client_con_db.post(
        "/api/cotizar",
        json={
            "items": [{"equipo_id": None, "cantidad": 1, "precio_jornada": 100_000,
                       "cobro_modo": "fijo"}],
            "fecha_desde": "2031-06-01T10:00:00",
            "fecha_hasta": "2031-06-05T10:00:00",
            "cliente_id": CLIENTE_ID,
            "pedido_id": PEDIDO_PRINCIPAL_ID,
            "respetar_precio_item": True,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # El desglose de siempre sigue siendo SOLO el del principal (clave aditiva).
    assert data["neto"] == 100_000
    combinado = data["combinado"]
    assert combinado is not None, "el pedido tiene un turno vinculado y no vino el combinado"
    assert combinado["turnos_total"] == 15_000
    assert combinado["neto"] == 115_000
    assert combinado["iva_monto"] == round(115_000 * 0.21)
    assert combinado["total_final"] == 115_000 + round(115_000 * 0.21)
    # Lo que estaba mal antes: el front sumaba total_final(principal) + neto(turno).
    assert combinado["total_final"] != data["total_final"] + 15_000


def test_sin_turnos_vinculados_no_hay_combinado(client_con_db, setup):
    """Sin turnos, `combinado` es null y el rail se lee como siempre (una sola
    parte) — cero cambio para el 99% de los pedidos."""
    r = client_con_db.post(
        "/api/cotizar",
        json={
            "items": [{"equipo_id": None, "cantidad": 1, "precio_jornada": 50_000,
                       "cobro_modo": "fijo"}],
            "fecha_desde": "2031-06-01T10:00:00",
            "fecha_hasta": "2031-06-05T10:00:00",
            "cliente_id": CLIENTE_ID,
            "pedido_id": PEDIDO_PRINCIPAL_ID,
            "respetar_precio_item": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["combinado"] is None


def test_get_pedido_combina_bruto_y_descuento_del_turno_no_solo_el_neto(client_con_db, setup):
    """DISCRIMINANTE (`services/facturacion/engine._get_pedido`, vía
    `combinar_turnos_vinculados`): antes de este fix, el combinado sumaba
    directo el `monto_total` (ya neto) del turno al `bruto` del principal sin
    nunca tocar `descuento_monto` — con un turno que tiene SU PROPIO
    descuento, eso hacía que `bruto` reportara de MENOS (el neto del turno,
    no su bruto real) y `descuento_monto` nunca sumara el aporte del turno.
    La resta `bruto - descuento_monto` seguía dando el neto correcto por
    coincidencia (los dos números erraban por el mismo monto) — por eso este
    test verifica los valores ABSOLUTOS, no solo la resta."""
    from database import get_db
    from services.facturacion.engine import _get_pedido

    turno_id = _crear_turno(client_con_db)
    r = client_con_db.patch(
        f"/api/admin/estudio/reservas/{turno_id}", json={"descuento_pct": 25}
    )
    assert r.status_code == 200, r.text
    assert _fila(turno_id)["monto_total"] == 15_000  # 20.000 − 25%

    conn = get_db()
    try:
        pedido = _get_pedido(conn, PEDIDO_PRINCIPAL_ID)
    finally:
        conn.close()

    # El principal de este fixture no tiene ítems propios — todo el combinado
    # viene del turno, aislando exactamente lo que se está probando.
    assert pedido["monto_total"] == 15_000
    assert pedido["bruto"] == 20_000, (
        "el bruto combinado tiene que ser el BRUTO real del turno (20.000), "
        "no su neto ya descontado (15.000)"
    )
    assert pedido["descuento_monto"] == 5_000, (
        "el descuento propio del turno (25% de 20.000) tiene que sumar al "
        "descuento_monto combinado, no perderse"
    )
    assert pedido["bruto"] - pedido["descuento_monto"] == pedido["monto_total"]
