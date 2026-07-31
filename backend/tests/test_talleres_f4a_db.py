"""Escuela v2 F4a — candados contra Postgres REAL: video hero (YouTube),
modalidades de pago (upsert + validación + fallback sintético + snapshot al
inscribirse).

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

TALLER_ID = 9_830_001
SLUG = "test-f4a-video-modalidades-zzq"


def _limpiar(conn):
    conn.execute(
        "DELETE FROM taller_inscripciones WHERE taller_id = %s", (TALLER_ID,)
    )
    conn.execute(
        "DELETE FROM edicion_modalidades_pago WHERE edicion_id IN "
        "(SELECT id FROM ediciones_taller WHERE taller_id = %s)",
        (TALLER_ID,),
    )
    conn.execute("DELETE FROM ediciones_taller WHERE taller_id = %s", (TALLER_ID,))
    conn.execute("DELETE FROM talleres WHERE id = %s", (TALLER_ID,))
    conn.execute("DELETE FROM media_assets WHERE original_key = 'test-f4a-fake-poster'")


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
            (TALLER_ID, SLUG, SLUG, "Taller F4a"),
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


def _crear_edicion(t, numero=1, modalidades=None):
    body = t.EdicionCreateBody(
        clases=[
            t.ClaseBody(fecha="2099-03-06", hora_inicio_min=510, hora_fin_min=750, titulo="Clase 1"),
        ],
        numero_edicion=numero,
        precio_total=100_000,
        activo=False,
    )
    d = t.admin_create_edicion(TALLER_ID, body, None)
    ed = d["ediciones"][0] if "ediciones" in d else d
    if modalidades is not None:
        t.admin_update_edicion(
            ed["id"],
            t.EdicionUpdateBody(modalidades=modalidades),
            None,
        )
    return ed


class _FakeVariant:
    def __init__(self, url):
        self.url = url


class _FakeAsset:
    def __init__(self, asset_id, url):
        self.id = asset_id
        self.variants = [_FakeVariant(url)]

    def variant(self, name):
        return self.variants[0] if name == "display" else None


def test_video_url_invalida_400(taller_base):
    t = taller_base
    with pytest.raises(t.HTTPException) as exc:
        t.admin_update_concepto(
            TALLER_ID, t.TallerConceptoUpdateBody(video_url="no-es-una-url-de-youtube"), None
        )
    assert exc.value.status_code == 400


def test_video_url_guarda_y_borra(taller_base, monkeypatch):
    """PATCH con una URL válida guarda video_url + poster (mockeado, sin red
    real); PATCH con '' borra los 3 campos."""
    from database import get_db
    t = taller_base

    # El FK video_poster_media_id exige un id real en media_assets — insertamos
    # el asset "descargado" a mano (la descarga en sí la mockeamos, no la DB).
    with get_db() as conn:
        row = conn.execute(
            "INSERT INTO media_assets (kind, original_key) VALUES ('taller', 'test-f4a-fake-poster') "
            "RETURNING id"
        ).fetchone()
        conn.commit()
    fake_asset_id = row["id"]

    monkeypatch.setattr(
        t, "store_youtube_poster",
        lambda vid, *, kind, conn: _FakeAsset(fake_asset_id, "https://cdn.example.com/poster.webp"),
    )
    d = t.admin_update_concepto(
        TALLER_ID,
        t.TallerConceptoUpdateBody(video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        None,
    )
    assert d["video_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert d["video_poster_url"] == "https://cdn.example.com/poster.webp"

    d2 = t.admin_update_concepto(TALLER_ID, t.TallerConceptoUpdateBody(video_url=""), None)
    assert d2["video_url"] == ""
    assert d2["video_poster_url"] == ""


def test_get_taller_publico_video_none_sin_url(taller_base, monkeypatch):
    """Sin video_url configurado, el público recibe `video: null` (no rompe
    por una URL ausente ni por una mal pegada)."""
    from fastapi.testclient import TestClient
    import main
    t = taller_base

    ed = _crear_edicion(t)
    with_get_db = __import__("database").get_db
    with with_get_db() as conn:
        conn.execute("UPDATE ediciones_taller SET activo = TRUE WHERE id = %s", (ed["id"],))
        conn.commit()

    client = TestClient(main.app)
    r = client.get(f"/api/talleres/{ed['slug']}")
    assert r.status_code == 200, r.text
    assert r.json()["video"] is None


def test_modalidades_upsert_sincroniza(taller_base):
    """PATCH con 2 modalidades nuevas las crea; un segundo PATCH que mantiene
    una (por id), agrega una nueva y omite la tercera → sincroniza (update +
    insert + delete), igual que _upsert_clases."""
    t = taller_base
    ed = _crear_edicion(t)

    d1 = t.admin_update_edicion(
        ed["id"],
        t.EdicionUpdateBody(modalidades=[
            t.ModalidadPagoBody(codigo="3-cuotas", label="3 cuotas", monto_total=240_000),
            t.ModalidadPagoBody(codigo="un-pago", label="Un pago", nota="10% off", monto_total=648_000),
        ]),
        None,
    )
    assert [m["codigo"] for m in d1["modalidades"]] == ["3-cuotas", "un-pago"]
    id_3_cuotas = d1["modalidades"][0]["id"]
    assert d1["modalidades"][1]["monto_total_str"] == "$648.000"

    d2 = t.admin_update_edicion(
        ed["id"],
        t.EdicionUpdateBody(modalidades=[
            t.ModalidadPagoBody(id=id_3_cuotas, codigo="3-cuotas", label="3 cuotas (editado)", monto_total=250_000),
            t.ModalidadPagoBody(codigo="ex-alumnos", label="Ex alumnos", monto_total=612_000),
        ]),
        None,
    )
    codigos = [m["codigo"] for m in d2["modalidades"]]
    assert codigos == ["3-cuotas", "ex-alumnos"], "un-pago se borró, ex-alumnos se creó, 3-cuotas se editó"
    assert d2["modalidades"][0]["label"] == "3 cuotas (editado)"
    assert d2["modalidades"][0]["id"] == id_3_cuotas, "el update preserva el id (no fue delete+insert)"


@pytest.mark.parametrize("kwargs,fragment", [
    ({"codigo": "", "label": "x", "monto_total": 100}, "código"),
    ({"codigo": "x", "label": "", "monto_total": 100}, "label"),
])
def test_modalidades_validacion_campos_vacios(taller_base, kwargs, fragment):
    t = taller_base
    ed = _crear_edicion(t)
    with pytest.raises(t.HTTPException) as exc:
        t.admin_update_edicion(
            ed["id"], t.EdicionUpdateBody(modalidades=[t.ModalidadPagoBody(**kwargs)]), None
        )
    assert exc.value.status_code == 400
    assert fragment in exc.value.detail


def test_modalidades_validacion_monto_no_positivo_rechazada_por_pydantic(taller_base):
    """monto_total <= 0 lo rechaza el propio Field(gt=0) de Pydantic (422 a
    nivel HTTP real; acá, llamando la función directo, ValidationError)."""
    import pydantic
    t = taller_base
    with pytest.raises(pydantic.ValidationError):
        t.ModalidadPagoBody(codigo="x", label="x", monto_total=0)


def test_modalidades_codigo_duplicado_400(taller_base):
    t = taller_base
    ed = _crear_edicion(t)
    with pytest.raises(t.HTTPException) as exc:
        t.admin_update_edicion(
            ed["id"],
            t.EdicionUpdateBody(modalidades=[
                t.ModalidadPagoBody(codigo="x", label="Uno", monto_total=100),
                t.ModalidadPagoBody(codigo="x", label="Dos", monto_total=200),
            ]),
            None,
        )
    assert exc.value.status_code == 400
    assert "duplicado" in exc.value.detail


def test_inscripcion_sin_modalidades_usa_fallback_sintetico(taller_base):
    """Edición sin modalidades configuradas → el snapshot usa el fallback
    'Pago total' = precio_total (cero ruptura para Jime)."""
    from fastapi.testclient import TestClient
    from database import get_db
    import main
    t = taller_base

    ed = _crear_edicion(t)
    with get_db() as conn:
        conn.execute(
            "UPDATE ediciones_taller SET activo = TRUE, cupos_total = 5 WHERE id = %s",
            (ed["id"],),
        )
        conn.commit()

    client = TestClient(main.app)
    r = client.post(f"/api/talleres/{ed['slug']}/inscripcion", json={
        "nombre": "Sin Modalidad", "email": "sinmodalidad@example.com", "telefono": "2235550003",
    })
    assert r.status_code == 200, r.text

    with get_db() as conn:
        row = conn.execute(
            "SELECT modalidad_codigo, modalidad_label, modalidad_monto FROM taller_inscripciones "
            "WHERE edicion_id = %s AND email = %s",
            (ed["id"], "sinmodalidad@example.com"),
        ).fetchone()
    assert row["modalidad_codigo"] == "total"
    assert row["modalidad_monto"] == 100_000


def test_inscripcion_con_modalidad_elegida_snapshotea(taller_base):
    """Edición CON modalidades: elegir una válida la snapshotea; elegir un
    código inexistente → 400."""
    from fastapi.testclient import TestClient
    from database import get_db
    import main
    t = taller_base

    ed = _crear_edicion(t, modalidades=[
        t.ModalidadPagoBody(codigo="3-cuotas", label="3 cuotas", monto_total=240_000),
        t.ModalidadPagoBody(codigo="un-pago", label="Un pago", monto_total=648_000),
    ])
    with get_db() as conn:
        conn.execute(
            "UPDATE ediciones_taller SET activo = TRUE, cupos_total = 5 WHERE id = %s",
            (ed["id"],),
        )
        conn.commit()

    client = TestClient(main.app)
    r = client.post(f"/api/talleres/{ed['slug']}/inscripcion", json={
        "nombre": "Con Modalidad", "email": "conmodalidad@example.com", "telefono": "2235550004",
        "modalidad_codigo": "un-pago",
    })
    assert r.status_code == 200, r.text
    with get_db() as conn:
        row = conn.execute(
            "SELECT modalidad_codigo, modalidad_monto FROM taller_inscripciones "
            "WHERE edicion_id = %s AND email = %s",
            (ed["id"], "conmodalidad@example.com"),
        ).fetchone()
    assert row["modalidad_codigo"] == "un-pago"
    assert row["modalidad_monto"] == 648_000

    r2 = client.post(f"/api/talleres/{ed['slug']}/inscripcion", json={
        "nombre": "Modalidad Inválida", "email": "invalida@example.com", "telefono": "2235550005",
        "modalidad_codigo": "no-existe",
    })
    assert r2.status_code == 400, r2.text


def test_inscripcion_sin_elegir_default_a_la_primera(taller_base):
    """Edición CON modalidades pero sin elegir ninguna (cableado-apagado: el
    form v1 no manda el campo) → default a la primera de la lista."""
    from fastapi.testclient import TestClient
    from database import get_db
    import main
    t = taller_base

    ed = _crear_edicion(t, modalidades=[
        t.ModalidadPagoBody(codigo="3-cuotas", label="3 cuotas", monto_total=240_000),
        t.ModalidadPagoBody(codigo="un-pago", label="Un pago", monto_total=648_000),
    ])
    with get_db() as conn:
        conn.execute(
            "UPDATE ediciones_taller SET activo = TRUE, cupos_total = 5 WHERE id = %s",
            (ed["id"],),
        )
        conn.commit()

    client = TestClient(main.app)
    r = client.post(f"/api/talleres/{ed['slug']}/inscripcion", json={
        "nombre": "Default", "email": "default-modalidad@example.com", "telefono": "2235550006",
    })
    assert r.status_code == 200, r.text
    with get_db() as conn:
        row = conn.execute(
            "SELECT modalidad_codigo FROM taller_inscripciones WHERE edicion_id = %s AND email = %s",
            (ed["id"], "default-modalidad@example.com"),
        ).fetchone()
    assert row["modalidad_codigo"] == "3-cuotas"
