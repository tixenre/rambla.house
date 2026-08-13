"""Cuentas de cobro de una edición — candados contra Postgres REAL: upsert
(sincroniza igual que modalidades/clases) + serialización pública/admin.

OPT-IN y seguro por defecto (RESERVAS_DB_TEST=1 + DATABASE_URL a una base de
prueba). Ids altos + limpieza antes/después. Mismo patrón que
`test_talleres_f4a_db.py`.
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

TALLER_ID = 9_830_002
SLUG = "test-cuentas-pago-zzq"


def _limpiar(conn):
    conn.execute(
        "DELETE FROM edicion_cuentas_pago WHERE edicion_id IN "
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
            (TALLER_ID, SLUG, SLUG, "Taller cuentas de pago"),
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


def _crear_edicion(t, numero=1):
    body = t.EdicionCreateBody(
        clases=[
            t.ClaseBody(fecha="2099-03-06", hora_inicio_min=510, hora_fin_min=750, titulo="Clase 1"),
        ],
        numero_edicion=numero,
        precio_total=100_000,
        activo=False,
    )
    d = t.admin_create_edicion(TALLER_ID, body, None)
    return d["ediciones"][0] if "ediciones" in d else d


def test_edicion_nace_sin_cuentas(taller_base):
    """Una edición recién creada no trae cuentas de cobro (mismo patrón que
    modalidades: no se setean en la creación, solo por PATCH después)."""
    t = taller_base
    ed = _crear_edicion(t)
    assert ed["cuentas_pago"] == []


def test_cuentas_upsert_sincroniza(taller_base):
    """PATCH con 2 cuentas nuevas las crea; un segundo PATCH que mantiene una
    (por id), agrega una nueva y omite la tercera → sincroniza (update +
    insert + delete), igual que modalidades/clases."""
    t = taller_base
    ed = _crear_edicion(t)

    d1 = t.admin_update_edicion(
        ed["id"],
        t.EdicionUpdateBody(cuentas_pago=[
            t.CuentaPagoBody(alias="rambla.estudio", cbu="0170", banco="BBVA"),
            t.CuentaPagoBody(alias="rambla.rental", cbu="", banco="Galicia"),
        ]),
        None,
    )
    assert [c["alias"] for c in d1["cuentas_pago"]] == ["rambla.estudio", "rambla.rental"]
    id_estudio = d1["cuentas_pago"][0]["id"]

    d2 = t.admin_update_edicion(
        ed["id"],
        t.EdicionUpdateBody(cuentas_pago=[
            t.CuentaPagoBody(id=id_estudio, alias="rambla.estudio", cbu="0170", banco="BBVA (editado)"),
            t.CuentaPagoBody(alias="tercera-cuenta", cbu="", banco=""),
        ]),
        None,
    )
    alias_out = [c["alias"] for c in d2["cuentas_pago"]]
    assert alias_out == ["rambla.estudio", "tercera-cuenta"], "rambla.rental se borró, tercera-cuenta se creó"
    assert d2["cuentas_pago"][0]["banco"] == "BBVA (editado)"
    assert d2["cuentas_pago"][0]["id"] == id_estudio, "el update preserva el id (no fue delete+insert)"


def test_cuenta_vacia_rechazada_400(taller_base):
    t = taller_base
    ed = _crear_edicion(t)
    with pytest.raises(t.HTTPException) as exc:
        t.admin_update_edicion(
            ed["id"],
            t.EdicionUpdateBody(cuentas_pago=[t.CuentaPagoBody(alias="", cbu="", banco="")]),
            None,
        )
    assert exc.value.status_code == 400


def test_get_taller_publico_incluye_cuentas_pago(taller_base):
    """El endpoint público expone `cuentas_pago` junto con `modalidades` —
    lista independiente, sin fallback sintético (a diferencia de
    modalidades, que sí sintetiza "Pago total" sin configurar ninguna)."""
    from fastapi.testclient import TestClient
    import main
    t = taller_base

    ed = _crear_edicion(t)
    t.admin_update_edicion(
        ed["id"],
        t.EdicionUpdateBody(
            activo=True,
            cuentas_pago=[t.CuentaPagoBody(alias="rambla.estudio", cbu="", banco="BBVA")],
        ),
        None,
    )

    client = TestClient(main.app)
    r = client.get(f"/api/talleres/{ed['slug']}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["cuentas_pago"] == [
        {"id": data["cuentas_pago"][0]["id"], "alias": "rambla.estudio", "cbu": "", "banco": "BBVA"}
    ]
    # Modalidades sigue con su fallback sintético — no confundir los dos.
    assert data["modalidades"][0]["codigo"] == "total"
