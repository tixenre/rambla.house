"""Escuela v2 F4b — candados contra Postgres REAL: verificar seña, ofrecer
cupo al siguiente (link tokenizado, reclamo transaccional), interesados admin.

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

TALLER_ID = 9_850_001
SLUG = "test-f4b-cupo-sena-zzq"


def _limpiar(conn):
    conn.execute(
        "DELETE FROM taller_inscripciones WHERE taller_id = %s", (TALLER_ID,)
    )
    conn.execute("DELETE FROM interesados_taller WHERE taller_id = %s", (TALLER_ID,))
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
            (TALLER_ID, SLUG, SLUG, "Taller F4b"),
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


def _crear_edicion_activa(t, cupos_total=5, cupos_confirmados=0, precio_sena=100_000):
    from database import get_db

    body = t.EdicionCreateBody(
        clases=[t.ClaseBody(fecha="2099-03-06", hora_inicio_min=510, hora_fin_min=750)],
        numero_edicion=1,
        precio_total=precio_sena * 2,
        precio_sena=precio_sena,
        activo=False,
    )
    d = t.admin_create_edicion(TALLER_ID, body, None)
    ed = d["ediciones"][0] if "ediciones" in d else d
    with get_db() as conn:
        conn.execute(
            "UPDATE ediciones_taller SET activo = TRUE, cupos_total = %s, "
            "cupos_confirmados = %s WHERE id = %s",
            (cupos_total, cupos_confirmados, ed["id"]),
        )
        conn.commit()
    return ed


def _insertar_inscripcion(edicion_id, *, en_lista_espera, estado, email=None):
    from database import get_db

    email = email or f"test-f4b-{edicion_id}-{estado}@example.com"
    with get_db() as conn:
        row = conn.execute(
            "INSERT INTO taller_inscripciones "
            "(taller_id, edicion_id, nombre, email, telefono, en_lista_espera, estado) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (TALLER_ID, edicion_id, "Test F4b", email, "2235550000", en_lista_espera, estado),
        ).fetchone()
        conn.commit()
    return row["id"]


def test_verificar_sena_pendiente_a_confirmada(taller_base):
    t = taller_base
    ed = _crear_edicion_activa(t)
    ins_id = _insertar_inscripcion(ed["id"], en_lista_espera=False, estado="pendiente_sena")

    t.admin_verificar_sena(TALLER_ID, ins_id, None)

    from database import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT estado, sena_verificada_at FROM taller_inscripciones WHERE id = %s",
            (ins_id,),
        ).fetchone()
    assert row["estado"] == "confirmada"
    assert row["sena_verificada_at"] is not None


def test_verificar_sena_rechaza_si_no_esta_pendiente(taller_base):
    t = taller_base
    ed = _crear_edicion_activa(t)
    ins_id = _insertar_inscripcion(ed["id"], en_lista_espera=True, estado="en_espera")

    with pytest.raises(t.HTTPException) as exc:
        t.admin_verificar_sena(TALLER_ID, ins_id, None)
    assert exc.value.status_code == 400


def test_ofrecer_cupo_marca_estado_sin_tocar_cupos_ni_lista(taller_base):
    """Ofrecer el cupo NO lo reserva todavía: cupos_confirmados y
    en_lista_espera quedan intactos — recién cambian cuando la persona
    reclama vía el token."""
    t = taller_base
    ed = _crear_edicion_activa(t, cupos_total=5, cupos_confirmados=3)
    ins_id = _insertar_inscripcion(ed["id"], en_lista_espera=True, estado="en_espera")

    t.admin_ofrecer_cupo(TALLER_ID, ins_id, None)

    from database import get_db
    with get_db() as conn:
        ins = conn.execute(
            "SELECT estado, cupo_ofrecido_at, en_lista_espera FROM taller_inscripciones WHERE id = %s",
            (ins_id,),
        ).fetchone()
        edicion = conn.execute(
            "SELECT cupos_confirmados FROM ediciones_taller WHERE id = %s", (ed["id"],)
        ).fetchone()
    assert ins["estado"] == "cupo_ofrecido"
    assert ins["cupo_ofrecido_at"] is not None
    assert ins["en_lista_espera"] is True, "sigue en la lista hasta que reclama"
    assert edicion["cupos_confirmados"] == 3, "ofrecer NO reserva el cupo"


def test_ofrecer_cupo_rechaza_si_no_esta_en_espera(taller_base):
    t = taller_base
    ed = _crear_edicion_activa(t)
    ins_id = _insertar_inscripcion(ed["id"], en_lista_espera=False, estado="pendiente_sena")

    with pytest.raises(t.HTTPException) as exc:
        t.admin_ofrecer_cupo(TALLER_ID, ins_id, None)
    assert exc.value.status_code == 400


def test_claim_cupo_via_token_reclama_y_suma_cupo(taller_base):
    from fastapi.testclient import TestClient
    from database import get_db
    import main
    t = taller_base

    ed = _crear_edicion_activa(t, cupos_total=5, cupos_confirmados=3)
    ins_id = _insertar_inscripcion(ed["id"], en_lista_espera=True, estado="en_espera")
    t.admin_ofrecer_cupo(TALLER_ID, ins_id, None)
    token = t._generar_token_cupo(ins_id)

    client = TestClient(main.app)

    r_get = client.get(f"/api/talleres/sena/{token}")
    assert r_get.status_code == 200, r_get.text
    assert r_get.json()["taller_nombre"] == "Taller F4b"

    r_post = client.post(f"/api/talleres/sena/{token}", json={
        "comprobante_url": "https://example.com/comprobante.jpg",
    })
    assert r_post.status_code == 200, r_post.text

    with get_db() as conn:
        ins = conn.execute(
            "SELECT estado, en_lista_espera, comprobante_url FROM taller_inscripciones WHERE id = %s",
            (ins_id,),
        ).fetchone()
        edicion = conn.execute(
            "SELECT cupos_confirmados FROM ediciones_taller WHERE id = %s", (ed["id"],)
        ).fetchone()
    assert ins["estado"] == "pendiente_sena"
    assert ins["en_lista_espera"] is False
    assert ins["comprobante_url"] == "https://example.com/comprobante.jpg"
    assert edicion["cupos_confirmados"] == 4

    # El link ya reclamado no sirve una segunda vez (single-use vía estado).
    r_post2 = client.post(f"/api/talleres/sena/{token}", json={
        "comprobante_url": "https://example.com/otro.jpg",
    })
    assert r_post2.status_code == 410, r_post2.text


def test_upload_comprobante_sena_no_necesita_slug(taller_base, monkeypatch):
    """F5: la página pública 'completá tu seña' solo tiene el token — el
    upload de comprobante tiene que resolver todo por ahí, sin slug."""
    from fastapi.testclient import TestClient
    import main
    t = taller_base

    ed = _crear_edicion_activa(t, cupos_total=5, cupos_confirmados=3)
    ins_id = _insertar_inscripcion(ed["id"], en_lista_espera=True, estado="en_espera")
    t.admin_ofrecer_cupo(TALLER_ID, ins_id, None)
    token = t._generar_token_cupo(ins_id)

    monkeypatch.setattr(
        t, "store_raw_document",
        lambda raw, *, kind, ref, content_type: (f"key-{ref}", "https://cdn.example.com/comprobante.pdf"),
    )

    client = TestClient(main.app)
    r = client.post(
        f"/api/talleres/sena/{token}/upload-comprobante",
        files={"file": ("comprobante.pdf", b"%PDF-fake", "application/pdf")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"] == "https://cdn.example.com/comprobante.pdf"
    assert body["key"].startswith(f"key-sena-{ins_id}-")


def test_upload_comprobante_sena_token_invalido_404(taller_base):
    from fastapi.testclient import TestClient
    import main
    t = taller_base

    client = TestClient(main.app)
    r = client.post(
        "/api/talleres/sena/token-inventado/upload-comprobante",
        files={"file": ("comprobante.pdf", b"%PDF-fake", "application/pdf")},
    )
    assert r.status_code == 404, r.text


def test_claim_cupo_ya_tomado_409(taller_base):
    """1 solo cupo libre, 2 ofertas en carrera — la primera gana, la segunda
    409 en vez de sobrevender."""
    from fastapi.testclient import TestClient
    import main
    t = taller_base

    ed = _crear_edicion_activa(t, cupos_total=5, cupos_confirmados=4)  # 1 libre
    ins_a = _insertar_inscripcion(ed["id"], en_lista_espera=True, estado="en_espera",
                                   email="a@example.com")
    ins_b = _insertar_inscripcion(ed["id"], en_lista_espera=True, estado="en_espera",
                                   email="b@example.com")
    t.admin_ofrecer_cupo(TALLER_ID, ins_a, None)
    t.admin_ofrecer_cupo(TALLER_ID, ins_b, None)
    token_a = t._generar_token_cupo(ins_a)
    token_b = t._generar_token_cupo(ins_b)

    client = TestClient(main.app)
    r_a = client.post(f"/api/talleres/sena/{token_a}", json={"comprobante_url": "https://x/a.jpg"})
    assert r_a.status_code == 200, r_a.text
    r_b = client.post(f"/api/talleres/sena/{token_b}", json={"comprobante_url": "https://x/b.jpg"})
    assert r_b.status_code == 409, r_b.text


def test_claim_cupo_token_invalido_404(taller_base):
    from fastapi.testclient import TestClient
    import main
    _ = taller_base
    client = TestClient(main.app)
    assert client.get("/api/talleres/sena/token-basura").status_code == 404
    assert client.post(
        "/api/talleres/sena/token-basura", json={"comprobante_url": "https://x/y.jpg"}
    ).status_code == 404


def test_claim_cupo_no_ofrecido_410(taller_base):
    from fastapi.testclient import TestClient
    import main
    t = taller_base

    ed = _crear_edicion_activa(t)
    ins_id = _insertar_inscripcion(ed["id"], en_lista_espera=False, estado="confirmada")
    token = t._generar_token_cupo(ins_id)

    client = TestClient(main.app)
    assert client.get(f"/api/talleres/sena/{token}").status_code == 410
    r = client.post(f"/api/talleres/sena/{token}", json={"comprobante_url": "https://x/y.jpg"})
    assert r.status_code == 410


def test_claim_cupo_requiere_comprobante_400(taller_base):
    from fastapi.testclient import TestClient
    import main
    t = taller_base

    ed = _crear_edicion_activa(t)
    ins_id = _insertar_inscripcion(ed["id"], en_lista_espera=True, estado="en_espera")
    t.admin_ofrecer_cupo(TALLER_ID, ins_id, None)
    token = t._generar_token_cupo(ins_id)

    client = TestClient(main.app)
    r = client.post(f"/api/talleres/sena/{token}", json={})
    assert r.status_code == 400


def test_admin_list_interesados(taller_base):
    from database import get_db
    t = taller_base

    with get_db() as conn:
        conn.execute(
            "INSERT INTO interesados_taller (taller_id, nombre, email, telefono) "
            "VALUES (%s, %s, %s, %s), (%s, %s, %s, %s)",
            (TALLER_ID, "Interesado Uno", "uno@example.com", "223",
             TALLER_ID, "Interesado Dos", "dos@example.com", "223"),
        )
        conn.commit()

    result = t.admin_list_interesados(TALLER_ID, None)
    assert len(result) == 2
    assert {r["email"] for r in result} == {"uno@example.com", "dos@example.com"}
    assert all(r["notificado_at"] is None for r in result)


def test_admin_notificar_interesado_marca_notificado_at(taller_base):
    from database import get_db
    t = taller_base

    with get_db() as conn:
        row = conn.execute(
            "INSERT INTO interesados_taller (taller_id, nombre, email, telefono) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (TALLER_ID, "Interesado", "interesado@example.com", "223"),
        ).fetchone()
        conn.commit()
    interesado_id = row["id"]

    t.admin_notificar_interesado(TALLER_ID, interesado_id, None)

    with get_db() as conn:
        after = conn.execute(
            "SELECT notificado_at FROM interesados_taller WHERE id = %s", (interesado_id,)
        ).fetchone()
    assert after["notificado_at"] is not None


def test_admin_notificar_interesado_404_si_no_existe(taller_base):
    t = taller_base
    with pytest.raises(t.HTTPException) as exc:
        t.admin_notificar_interesado(TALLER_ID, 999_999_999, None)
    assert exc.value.status_code == 404


def test_eliminar_inscripcion_espera_lock_y_ve_estado_fresco(taller_base):
    """Regresión (hallazgo del supervisor, reproducido con dos conexiones
    reales): admin_delete_inscripcion no tomaba FOR UPDATE — si el reclamo de
    un cupo (POST /talleres/sena/{token}) commiteaba en_lista_espera=False +
    cupos_confirmados+1 justo ENTRE el SELECT y el DELETE del admin, este
    borraba la fila con el en_lista_espera VIEJO (True), se saltaba el
    decremento, y cupos_confirmados quedaba contando de más para siempre. Con
    el FOR UPDATE del fix, el DELETE del admin espera a que el reclamo libere
    el lock y ve el estado fresco post-commit → decrementa correctamente."""
    import threading
    import time
    from database import get_db
    t = taller_base

    ed = _crear_edicion_activa(t, cupos_total=5, cupos_confirmados=3)
    ins_id = _insertar_inscripcion(ed["id"], en_lista_espera=True, estado="cupo_ofrecido")

    orden: list[str] = []
    lock_tomado = threading.Event()
    liberar_lock = threading.Event()
    errores: dict[str, Exception] = {}

    def _simular_reclamo():
        conn = get_db()
        try:
            conn.execute(
                "SELECT id FROM taller_inscripciones WHERE id = %s FOR UPDATE", (ins_id,)
            )
            orden.append("reclamo_tomo_lock")
            lock_tomado.set()
            liberar_lock.wait(timeout=5)
            # Lo mismo que hace claim_oferta_cupo antes de comittear.
            conn.execute(
                "UPDATE taller_inscripciones SET en_lista_espera = FALSE, "
                "estado = 'pendiente_sena' WHERE id = %s",
                (ins_id,),
            )
            conn.execute(
                "UPDATE ediciones_taller SET cupos_confirmados = cupos_confirmados + 1 "
                "WHERE id = %s",
                (ed["id"],),
            )
            conn.commit()
            orden.append("reclamo_commiteo")
        except Exception as e:  # noqa: BLE001
            errores["reclamo"] = e
        finally:
            conn.close()

    def _borrar():
        lock_tomado.wait(timeout=5)
        try:
            t.admin_delete_inscripcion(TALLER_ID, ins_id, None)
            orden.append("admin_borro")
        except Exception as e:  # noqa: BLE001
            errores["admin"] = e

    ta = threading.Thread(target=_simular_reclamo)
    tb = threading.Thread(target=_borrar)
    ta.start()
    lock_tomado.wait(timeout=5)
    tb.start()
    time.sleep(0.3)  # admin debería seguir esperando el lock en este punto.
    assert "admin_borro" not in orden, "el admin no debería poder borrar mientras el reclamo retiene el lock"
    liberar_lock.set()
    ta.join(timeout=5)
    tb.join(timeout=5)

    assert not ta.is_alive() and not tb.is_alive(), "deadlock: algún hilo no terminó"
    assert not errores, f"errores en los hilos: {errores}"
    assert orden == ["reclamo_tomo_lock", "reclamo_commiteo", "admin_borro"], orden

    with get_db() as conn:
        edicion = conn.execute(
            "SELECT cupos_confirmados FROM ediciones_taller WHERE id = %s", (ed["id"],)
        ).fetchone()
    # El reclamo sumó 1 (3→4); el admin borró una inscripción que YA estaba
    # confirmada (en_lista_espera=False fresco) → debe restar 1 (4→3). Sin el
    # fix, el admin veía el en_lista_espera VIEJO (True) y no restaba nada →
    # hubiera quedado en 4 (contado de más para siempre).
    assert edicion["cupos_confirmados"] == 3, (
        f"esperaba 3 (el reclamo sumó, el borrado de la confirmada resta) — "
        f"quedó en {edicion['cupos_confirmados']}: cupos contados de más"
    )
