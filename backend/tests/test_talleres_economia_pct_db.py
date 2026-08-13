"""Economía del taller — modo 'porcentaje' contra Postgres REAL: candados que
el fake conn de `test_talleres.py` no puede dar (SQL real de
`_revenue_inscriptos` + el flujo completo `admin_update_edicion` ->
`_regenerar_pedidos_taller` -> filas reales en `alquileres`/`alquiler_items`).

Pedido explícito del dueño: "si se anotan 6 vamos al %50". Mismo patrón que
`test_talleres_cuentas_pago_db.py`.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_talleres_economia_pct_db.py -v -m integration
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

TALLER_ID = 9_830_003
SLUG = "test-economia-pct-zzq"


def _limpiar(conn):
    conn.execute(
        "DELETE FROM alquileres WHERE taller_edicion_id IN "
        "(SELECT id FROM ediciones_taller WHERE taller_id = %s)",
        (TALLER_ID,),
    )
    conn.execute(
        "DELETE FROM taller_inscripciones WHERE edicion_id IN "
        "(SELECT id FROM ediciones_taller WHERE taller_id = %s)",
        (TALLER_ID,),
    )
    conn.execute("DELETE FROM ediciones_taller WHERE taller_id = %s", (TALLER_ID,))
    conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))


@pytest.fixture
def taller_base(monkeypatch):
    import routes.talleres as t
    from database import get_db, init_db

    monkeypatch.setattr(t, "require_admin", lambda r: None)
    monkeypatch.setattr(t, "send_email", lambda *a, **k: None)
    monkeypatch.setattr(t, "get_admin_tos", lambda: ["admin@example.com"])

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
            (TALLER_ID, SLUG, SLUG, "Taller economía %"),
        )
        conn.commit()
    finally:
        conn.close()

    yield t

    conn = get_db()
    try:
        _limpiar(conn)
        conn.commit()
    finally:
        conn.close()


def _crear_edicion(t, **ov):
    kwargs = dict(
        clases=[
            t.ClaseBody(fecha="2099-03-06", hora_inicio_min=510, hora_fin_min=750, titulo="Clase 1"),
        ],
        numero_edicion=1,
        precio_total=100_000,
        activo=False,
    )
    kwargs.update(ov)
    body = t.EdicionCreateBody(**kwargs)
    d = t.admin_create_edicion(TALLER_ID, body, None)
    return d["ediciones"][0] if "ediciones" in d else d


def _inscribir(conn, edicion_id, *, monto, en_lista_espera=False, email="x@example.com"):
    conn.execute(
        """
        INSERT INTO taller_inscripciones
            (taller_id, edicion_id, nombre, email, telefono, en_lista_espera, estado, modalidad_monto)
        VALUES (%s, %s, 'Test', %s, '+5491100000000', %s, 'pendiente_sena', %s)
        """,
        (TALLER_ID, edicion_id, email, en_lista_espera, monto),
    )


def test_revenue_inscriptos_suma_solo_no_en_lista_espera(taller_base):
    from database import get_db
    from services.talleres.queries.economia import _revenue_inscriptos

    t = taller_base
    ed = _crear_edicion(t)
    conn = get_db()
    try:
        _inscribir(conn, ed["id"], monto=100_000, email="a@example.com")
        _inscribir(conn, ed["id"], monto=100_000, email="b@example.com")
        _inscribir(conn, ed["id"], monto=999_999, en_lista_espera=True, email="c@example.com")
        conn.commit()
        assert _revenue_inscriptos(conn, ed["id"]) == 200_000
    finally:
        conn.close()


def test_revenue_inscriptos_cero_sin_inscriptos(taller_base):
    from database import get_db
    from services.talleres.queries.economia import _revenue_inscriptos

    t = taller_base
    ed = _crear_edicion(t)
    conn = get_db()
    try:
        assert _revenue_inscriptos(conn, ed["id"]) == 0
    finally:
        conn.close()


def test_admin_update_edicion_porcentaje_end_to_end(taller_base):
    """El flujo completo: 2 inscriptos confirmados ($100.000 c/u) + Estudio al
    50% -> el pedido mensual regenerado cobra $100.000 por el Estudio (mismo
    número que devuelve el preview del dict admin)."""
    from database import get_db

    t = taller_base
    ed = _crear_edicion(t)
    conn = get_db()
    try:
        _inscribir(conn, ed["id"], monto=100_000, email="a@example.com")
        _inscribir(conn, ed["id"], monto=100_000, email="b@example.com")
        conn.commit()
    finally:
        conn.close()

    out = t.admin_update_edicion(
        ed["id"],
        t.EdicionUpdateBody(
            activo=True,
            usa_estudio=True, valor_estudio_tipo="porcentaje", valor_estudio_pct=50,
            valor_estudio_modo="mensual",
        ),
        None,
    )
    assert out["inscriptos_revenue"] == 200_000
    assert out["valor_estudio_efectivo"] == 100_000

    conn = get_db()
    try:
        pedidos = conn.execute(
            "SELECT id, monto_total FROM alquileres WHERE taller_edicion_id = %s",
            (ed["id"],),
        ).fetchall()
        assert len(pedidos) >= 1
        for p in pedidos:
            assert p["monto_total"] == 100_000
            item = conn.execute(
                "SELECT subtotal FROM alquiler_items WHERE pedido_id = %s", (p["id"],)
            ).fetchone()
            assert item["subtotal"] == 100_000
    finally:
        conn.close()


def test_valor_estudio_tipo_invalido_400(taller_base):
    t = taller_base
    ed = _crear_edicion(t)
    with pytest.raises(t.HTTPException) as exc:
        t.admin_update_edicion(
            ed["id"], t.EdicionUpdateBody(valor_estudio_tipo="mitad"), None,
        )
    assert exc.value.status_code == 400


def test_valor_estudio_pct_fuera_de_rango_400(taller_base):
    t = taller_base
    ed = _crear_edicion(t)
    with pytest.raises(t.HTTPException) as exc:
        t.admin_update_edicion(
            ed["id"], t.EdicionUpdateBody(valor_estudio_pct=101), None,
        )
    assert exc.value.status_code == 400


def test_edicion_nace_en_fijo_por_defecto(taller_base):
    t = taller_base
    ed = _crear_edicion(t)
    assert ed["valor_estudio_tipo"] == "fijo"
    assert ed["valor_equipos_tipo"] == "fijo"
    assert ed["inscriptos_revenue"] == 0
