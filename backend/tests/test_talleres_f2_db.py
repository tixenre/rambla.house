"""Escuela v2 F2 — candados contra Postgres REAL: borradores, publicar
re-verifica el estudio, upsert de clases preserva la portada, tyc_aceptado_at.

Los endpoints admin se llaman como FUNCIONES (no están rate-limited) con
`require_admin` monkeypatcheado — el objeto de test es la lógica de datos, no
la auth (que tiene sus propios tests). La inscripción va por HTTP (TestClient)
porque sí está rate-limited.

OPT-IN y seguro por defecto (RESERVAS_DB_TEST=1 + DATABASE_URL a una base de
prueba). Ids altos + limpieza antes/después.
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

TALLER_ID = 9_810_001
SLUG = "test-f2-clases-ricas-zzq"


def _limpiar(conn):
    conn.execute(
        "DELETE FROM taller_inscripciones WHERE taller_id = %s", (TALLER_ID,)
    )
    conn.execute(
        "DELETE FROM clases_taller WHERE edicion_id IN "
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
    monkeypatch.setattr(t, "get_admin_to", lambda: "admin@example.com")

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            "INSERT INTO talleres (id, slug, slug_base, nombre) VALUES (%s, %s, %s, %s)",
            (TALLER_ID, SLUG, SLUG, "Taller F2"),
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


def _crear_edicion(t, numero=1, activo=None, clases=None):
    body = t.EdicionCreateBody(
        clases=clases
        or [
            t.ClaseBody(fecha="2099-03-06", hora_inicio_min=510, hora_fin_min=750,
                        titulo="Clase 1", descripcion="Temario 1"),
            t.ClaseBody(fecha="2099-03-13", hora_inicio_min=510, hora_fin_min=750,
                        titulo="Clase 2", descripcion="Temario 2"),
        ],
        numero_edicion=numero,
        **({"activo": activo} if activo is not None else {}),
    )
    return t.admin_create_edicion(TALLER_ID, body, None)


def test_edicion_nace_borrador_y_no_chequea_estudio(taller_base, monkeypatch):
    """Default F2: la edición nace despublicada, y crearla como borrador NO
    corre el chequeo del estudio (correría recién al publicar)."""
    import services.estudio.queries.disponibilidad as est_disp
    t = taller_base

    def _boom(*a, **k):
        raise AssertionError("un borrador no debe verificar el estudio al crearse")

    monkeypatch.setattr(est_disp, "verificar_sesiones_disponibles", _boom)
    d = _crear_edicion(t)
    assert d["activo"] is False

    from database import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT activo FROM ediciones_taller WHERE taller_id = %s", (TALLER_ID,)
        ).fetchone()
    assert row["activo"] is False


def test_publicar_reverifica_estudio_y_409_mantiene_borrador(taller_base, monkeypatch):
    """Publicar (activo false→true) re-verifica la disponibilidad del estudio:
    si el chequeo falla → 409 y la edición SIGUE en borrador; si pasa → publicada."""
    from fastapi import HTTPException
    import services.estudio.queries.estudio as est_row
    import services.estudio.queries.disponibilidad as est_disp
    from database import get_db
    t = taller_base

    d = _crear_edicion(t)
    edicion_id = d["ediciones"][0]["id"] if "ediciones" in d else d["id"]

    # El estudio puede no estar configurado en la DB de test → forzamos un
    # estudio "real" para que el camino de verificación se ejecute.
    monkeypatch.setattr(est_row, "_get_estudio_row", lambda conn: {"equipo_id": 1, "buffer_horas": 0})

    def _conflicto(*a, **k):
        raise HTTPException(409, "El estudio no está libre (test)")

    monkeypatch.setattr(est_disp, "verificar_sesiones_disponibles", _conflicto)
    with pytest.raises(HTTPException) as exc:
        t.admin_update_edicion(edicion_id, t.EdicionUpdateBody(activo=True), None)
    assert exc.value.status_code == 409
    with get_db() as conn:
        row = conn.execute(
            "SELECT activo FROM ediciones_taller WHERE id = %s", (edicion_id,)
        ).fetchone()
    assert row["activo"] is False, "tras el 409 debe seguir en borrador"

    llamado = {}

    def _ok(conn, estudio, sesiones, **k):
        llamado["sesiones"] = list(sesiones)

    monkeypatch.setattr(est_disp, "verificar_sesiones_disponibles", _ok)
    d2 = t.admin_update_edicion(edicion_id, t.EdicionUpdateBody(activo=True), None)
    assert d2["activo"] is True
    assert len(llamado["sesiones"]) == 2, "publicar verifica las clases EXISTENTES"


def test_upsert_clases_preserva_portada(taller_base):
    """PATCH de clases con id = UPDATE (la portada sobrevive); sin el id en la
    lista = DELETE. El delete+insert ciego de antes perdía la portada."""
    from database import get_db
    t = taller_base

    d = _crear_edicion(t)
    ed = d["ediciones"][0] if "ediciones" in d else d
    edicion_id = ed["id"]
    clase1 = ed["clases"][0]

    with get_db() as conn:
        conn.execute(
            "UPDATE clases_taller SET portada_url = 'https://cdn.example/portada.webp' "
            "WHERE id = %s",
            (clase1["id"],),
        )
        conn.commit()

    # Editar el título de la clase 1 (con id) + reemplazar la clase 2 por una nueva
    nuevo = t.admin_update_edicion(
        edicion_id,
        t.EdicionUpdateBody(clases=[
            t.ClaseBody(id=clase1["id"], fecha=clase1["fecha"], hora_inicio_min=510,
                        hora_fin_min=750, titulo="Clase 1 renombrada", descripcion="X"),
            t.ClaseBody(fecha="2099-03-20", hora_inicio_min=540, hora_fin_min=780,
                        titulo="Clase nueva"),
        ]),
        None,
    )
    por_titulo = {c["titulo"]: c for c in nuevo["clases"]}
    assert por_titulo["Clase 1 renombrada"]["portada_url"] == "https://cdn.example/portada.webp"
    assert por_titulo["Clase 1 renombrada"]["id"] == clase1["id"]
    assert por_titulo["Clase nueva"]["portada_url"] == ""
    assert "Clase 2" not in por_titulo, "la clase sin id en la lista se borra"


def test_clases_misma_franja_titulos_distintos(taller_base):
    """'Clase 11 y 12 se dictan juntas' (Filmar): misma fecha y franja con
    títulos distintos es válido; con el MISMO título es duplicado (400)."""
    from fastapi import HTTPException
    t = taller_base

    d = _crear_edicion(t, clases=[
        t.ClaseBody(fecha="2099-04-03", hora_inicio_min=840, hora_fin_min=1320,
                    titulo="Clase 11"),
        t.ClaseBody(fecha="2099-04-03", hora_inicio_min=840, hora_fin_min=1320,
                    titulo="Clase 12"),
    ])
    ed = d["ediciones"][0] if "ediciones" in d else d
    assert len(ed["clases"]) == 2

    with pytest.raises(HTTPException) as exc:
        t._validar_clases([
            t.ClaseBody(fecha="2099-04-03", hora_inicio_min=840, hora_fin_min=1320,
                        titulo="Igual"),
            t.ClaseBody(fecha="2099-04-03", hora_inicio_min=840, hora_fin_min=1320,
                        titulo="Igual"),
        ])
    assert exc.value.status_code == 400


def test_inscripcion_registra_tyc(taller_base):
    """acepta_terminos=True → tyc_aceptado_at con timestamp; ausente → NULL
    (cableado-apagado: el form actual no manda el campo y sigue funcionando)."""
    from fastapi.testclient import TestClient
    from database import get_db
    import main
    t = taller_base

    # Edición ACTIVA con cupos llenos → lista de espera (sin comprobante).
    body = t.EdicionCreateBody(
        clases=[t.ClaseBody(fecha="2099-05-01", hora_inicio_min=540, hora_fin_min=780)],
        numero_edicion=7,
        activo=False,
    )
    d = t.admin_create_edicion(TALLER_ID, body, None)
    ed = d["ediciones"][0] if "ediciones" in d else d
    with get_db() as conn:
        conn.execute(
            "UPDATE ediciones_taller SET activo = TRUE, cupos_total = 1, "
            "cupos_confirmados = 1 WHERE id = %s",
            (ed["id"],),
        )
        conn.commit()

    client = TestClient(main.app)
    r1 = client.post(f"/api/talleres/{ed['slug']}/inscripcion", json={
        "nombre": "Tyc Sí", "email": "tyc-si@example.com", "telefono": "2235550001",
        "acepta_terminos": True,
    })
    assert r1.status_code == 200, r1.text
    r2 = client.post(f"/api/talleres/{ed['slug']}/inscripcion", json={
        "nombre": "Tyc No", "email": "tyc-no@example.com", "telefono": "2235550002",
    })
    assert r2.status_code == 200, r2.text

    with get_db() as conn:
        rows = conn.execute(
            "SELECT email, tyc_aceptado_at FROM taller_inscripciones "
            "WHERE edicion_id = %s ORDER BY id",
            (ed["id"],),
        ).fetchall()
    por_email = {r["email"]: r["tyc_aceptado_at"] for r in rows}
    assert por_email["tyc-si@example.com"] is not None
    assert por_email["tyc-no@example.com"] is None


def test_borrador_404_publico_y_preview_admin(taller_base, monkeypatch):
    """Una edición en borrador: 404 para el público; visible (con borrador=true)
    para una sesión admin (acá simulada con el dev-bypass)."""
    from fastapi.testclient import TestClient
    import auth.session as auth_session
    import main
    t = taller_base

    d = _crear_edicion(t, numero=9)
    ed = d["ediciones"][0] if "ediciones" in d else d
    client = TestClient(main.app)

    monkeypatch.setattr(auth_session, "dev_bypass_enabled", lambda: False)
    assert client.get(f"/api/talleres/{ed['slug']}").status_code == 404

    monkeypatch.setattr(auth_session, "dev_bypass_enabled", lambda: True)
    r = client.get(f"/api/talleres/{ed['slug']}")
    assert r.status_code == 200
    assert r.json()["borrador"] is True


def test_edicion_anterior_no_expone_borrador(taller_base):
    """'edicion_anterior' (dato de contexto en la página pública de OTRA edición)
    no debe traer una edición vuelta a borrador — antes filtraba solo por
    numero_edicion (sin `activo = TRUE`, a diferencia de 'proxima_edicion' 5
    líneas arriba en el mismo archivo), filtrando pago_alias/pago_cbu/pago_banco
    de una edición que el dueño despublicó."""
    from fastapi.testclient import TestClient
    from database import get_db
    import main
    t = taller_base

    d1 = _crear_edicion(t, numero=1)
    ed1 = d1["ediciones"][0] if "ediciones" in d1 else d1
    d2 = _crear_edicion(t, numero=2)
    ed2 = d2["ediciones"][0] if "ediciones" in d2 else d2

    with get_db() as conn:
        # ed1 = "anterior" de ed2: en algún momento estuvo publicada (con sus
        # datos bancarios reales) y el dueño la volvió a borrador — el
        # escenario real que motiva el fix.
        conn.execute(
            "UPDATE ediciones_taller SET activo = FALSE, pago_alias = %s, "
            "pago_cbu = %s, pago_banco = %s WHERE id = %s",
            ("alias-secreto-1", "cbu-secreto-1", "Banco Secreto", ed1["id"]),
        )
        conn.execute("UPDATE ediciones_taller SET activo = TRUE WHERE id = %s", (ed2["id"],))
        conn.commit()

    client = TestClient(main.app)
    r = client.get(f"/api/talleres/{ed2['slug']}")
    assert r.status_code == 200, r.text
    assert r.json()["edicion_anterior"] is None, (
        "una edición en borrador no debe aparecer como 'edicion_anterior' "
        "(antes filtraba solo por numero_edicion, exponiendo datos bancarios)"
    )
