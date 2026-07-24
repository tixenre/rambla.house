"""`routes.equipos.kit` (add_kit_item / reorder_kit) contra Postgres REAL —
verifica el fix de dead rows (2026-07-04): el editor de kit del admin llama a
`POST /equipos/{id}/kit` una vez por cada campo que se ajusta (cantidad,
descuento, esencial), y `reorder_kit` hace un UPDATE por componente en cada
drag — ambos escribían incondicionalmente aunque el valor ya fuera el mismo.
El fix es un guard SQL (`WHERE ... IS DISTINCT FROM ...`) en vez de una
comparación en Python, porque acá el upsert/update ya es de UNA sola fila
(a diferencia de `asignar_categorias`, que reemplaza un SET completo).

Mismo método de prueba que los otros dos fixes de esta auditoría: `xmin`
como prueba directa de "no se escribió nada".

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py). Ids altos
(9_600_3xx) + limpieza antes/después. Llama a las funciones de la ruta
directamente (no HTTP) con `ADMIN_BYPASS_AUTH=1` — mismo patrón que
`test_estudio.py::TestEstudioAdminGuards` para el camino negativo.
"""
import os
from urllib.parse import urlparse

import pytest
from starlette.requests import Request

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

EQ, COMP = 9_600_301, 9_600_302


def _fake_request() -> Request:
    """Request real (no un stub crudo) — add_kit_item/reorder_kit llevan
    `@limiter.limit` (auditoría #1263): slowapi exige una instancia genuina
    de `starlette.requests.Request`. Sin conexión real — alcanza con el
    scope ASGI mínimo (ADMIN_BYPASS_AUTH hace que require_admin ni siquiera
    lo inspeccione)."""
    return Request(
        {"type": "http", "method": "POST", "path": "/api/equipos/1/kit", "headers": [], "client": ("127.0.0.1", 0)}
    )


def _limpiar(conn):
    conn.execute("DELETE FROM kit_componentes WHERE equipo_id IN (%s,%s)" % (EQ, COMP))
    conn.execute("DELETE FROM equipos WHERE id IN (%s,%s)" % (EQ, COMP))


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute("INSERT INTO equipos (id, nombre, cantidad) VALUES (%s,%s,%s)", (EQ, "eq-kit-test", 1))
        conn.execute("INSERT INTO equipos (id, nombre, cantidad) VALUES (%s,%s,%s)", (COMP, "comp-kit-test", 1))
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


def _fila(conn):
    r = conn.execute(
        "SELECT cantidad, descuento_pct, esencial, orden, xmin::text AS xmin "
        "FROM kit_componentes WHERE equipo_id=%s AND componente_id=%s",
        (EQ, COMP),
    ).fetchone()
    return r


def test_reenviar_los_mismos_valores_no_escribe(setup):
    from database import get_db
    from routes.equipos.kit import KitItem, add_kit_item

    conn = get_db()
    try:
        add_kit_item(EQ, KitItem(componente_id=COMP, cantidad=2, descuento_pct=10.0, esencial=True), _fake_request())
        antes = _fila(conn)

        # Mismo request (el usuario reabre el editor y no toca nada, o el
        # frontend re-envía el mismo valor) ⇒ no debería tocar la fila.
        add_kit_item(EQ, KitItem(componente_id=COMP, cantidad=2, descuento_pct=10.0, esencial=True), _fake_request())
        despues = _fila(conn)

        assert despues["xmin"] == antes["xmin"]
    finally:
        conn.close()


def test_cambiar_un_solo_campo_si_escribe(setup):
    from database import get_db
    from routes.equipos.kit import KitItem, add_kit_item

    conn = get_db()
    try:
        add_kit_item(EQ, KitItem(componente_id=COMP, cantidad=2, descuento_pct=10.0, esencial=True), _fake_request())
        antes = _fila(conn)

        # Solo cambia la cantidad ⇒ tiene que escribir.
        add_kit_item(EQ, KitItem(componente_id=COMP, cantidad=3, descuento_pct=10.0, esencial=True), _fake_request())
        despues = _fila(conn)

        assert despues["cantidad"] == 3
        assert despues["xmin"] != antes["xmin"]
    finally:
        conn.close()


def test_reorder_al_mismo_orden_no_escribe(setup):
    from database import get_db
    from routes.equipos.kit import KitItem, KitReorder, add_kit_item, reorder_kit

    conn = get_db()
    try:
        add_kit_item(EQ, KitItem(componente_id=COMP, cantidad=1), _fake_request())
        conn.execute("UPDATE kit_componentes SET orden=0 WHERE equipo_id=%s AND componente_id=%s", (EQ, COMP))
        conn.commit()
        antes = _fila(conn)

        # Reordenar con el MISMO orden (soltar en el mismo lugar) ⇒ no-op.
        reorder_kit(EQ, KitReorder(orden=[COMP]), _fake_request())
        despues = _fila(conn)

        assert despues["orden"] == 0
        assert despues["xmin"] == antes["xmin"]
    finally:
        conn.close()


# ── Precio objetivo del combo (#1283 Fase 5) ─────────────────────────────────

COMBO, C1, C2, SIMPLE = 9_601_001, 9_601_002, 9_601_003, 9_601_004


def _limpiar_combo(conn):
    conn.execute("DELETE FROM kit_componentes WHERE equipo_id IN (%s,%s)" % (COMBO, SIMPLE))
    conn.execute("DELETE FROM equipos WHERE id IN (%s,%s,%s,%s)" % (COMBO, C1, C2, SIMPLE))


@pytest.fixture
def setup_combo(monkeypatch):
    monkeypatch.setenv("ADMIN_BYPASS_AUTH", "1")
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar_combo(conn)
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, tipo) VALUES (%s,%s,%s,%s)",
            (COMBO, "combo-precio-objetivo-test", 9999, "combo"),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, tipo) VALUES (%s,%s,%s,%s)",
            (SIMPLE, "simple-precio-objetivo-test", 1, "simple"),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada) VALUES (%s,%s,%s,%s)",
            (C1, "componente-1", 5, 1000),
        )
        conn.execute(
            "INSERT INTO equipos (id, nombre, cantidad, precio_jornada) VALUES (%s,%s,%s,%s)",
            (C2, "componente-2", 5, 500),
        )
        conn.execute(
            "INSERT INTO kit_componentes (equipo_id, componente_id, cantidad) VALUES (%s,%s,%s)",
            (COMBO, C1, 2),
        )
        conn.execute(
            "INSERT INTO kit_componentes (equipo_id, componente_id, cantidad) VALUES (%s,%s,%s)",
            (COMBO, C2, 1),
        )
        conn.commit()
    finally:
        conn.close()
    yield
    conn = get_db()
    try:
        _limpiar_combo(conn)
        conn.commit()
    finally:
        conn.close()


def test_precio_objetivo_aplica_descuento_uniforme(setup_combo):
    from routes.equipos.kit import PrecioObjetivoBody, set_precio_objetivo_combo

    # bruto = 1000×2 + 500×1 = 2500. Objetivo 2000 → 20% en CADA línea.
    out = set_precio_objetivo_combo(COMBO, PrecioObjetivoBody(precio_objetivo=2000), _fake_request())
    assert out["precio_combo"] == 2000
    assert {round(c["descuento_pct"], 4) for c in out["kit"]} == {20.0}


def test_precio_objetivo_rechaza_equipo_no_combo(setup_combo):
    from fastapi import HTTPException
    from routes.equipos.kit import PrecioObjetivoBody, set_precio_objetivo_combo

    with pytest.raises(HTTPException) as exc:
        set_precio_objetivo_combo(SIMPLE, PrecioObjetivoBody(precio_objetivo=100), _fake_request())
    assert exc.value.status_code == 400
    assert "combo" in exc.value.detail


def test_precio_objetivo_rechaza_sin_componentes(setup_combo):
    from fastapi import HTTPException
    from database import get_db
    from routes.equipos.kit import PrecioObjetivoBody, set_precio_objetivo_combo

    conn = get_db()
    try:
        conn.execute("UPDATE equipos SET tipo='combo' WHERE id=%s", (SIMPLE,))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(HTTPException) as exc:
        set_precio_objetivo_combo(SIMPLE, PrecioObjetivoBody(precio_objetivo=100), _fake_request())
    assert exc.value.status_code == 400
    assert "componentes" in exc.value.detail


def test_precio_objetivo_rechaza_objetivo_mayor_al_bruto(setup_combo):
    from fastapi import HTTPException
    from routes.equipos.kit import PrecioObjetivoBody, set_precio_objetivo_combo

    with pytest.raises(HTTPException) as exc:
        set_precio_objetivo_combo(COMBO, PrecioObjetivoBody(precio_objetivo=99999), _fake_request())
    assert exc.value.status_code == 400
    assert "no puede superar" in exc.value.detail
