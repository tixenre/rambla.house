"""#1308 — round-trip de dataio para `alquileres.tipo` + `pedido_principal_id`.

Bug latente (misma clase que el de `alquiler_pagos.anulado`, 2026-07-03):
`export_alquileres` no incluía ninguna de las dos columnas → un ciclo
`dataio export` → `dataio import` (backup/restore o clonado de ambiente)
devolvía TODO como `tipo='diaria'` y **desvinculado**: un turno del Estudio
revivía como un alquiler normal suelto, con su franja horaria leída como si
fuera un rango de días — exactamente el "pedido fantasma" que la iniciativa
elimina, pero horneado en los datos y ya sin forma de saber a qué pedido
pertenecía.

El vínculo viaja por NÚMERO de pedido, no por id: los ids difieren entre
ambientes (mismo criterio que `equipo_slug` en los items).

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás *_db.py):
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_dataio_pedido_vinculado_roundtrip_db.py -v -m integration
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

PRINCIPAL_ID = 9_700_101
TURNO_ID = 9_700_102
NUM_PRINCIPAL = 9_700_101
NUM_TURNO = 9_700_102


def _limpiar(conn):
    # El turno primero: su FK al principal es ON DELETE SET NULL, pero borrar
    # en orden deja la limpieza determinista.
    conn.execute("DELETE FROM alquileres WHERE id IN (%s, %s)", (TURNO_ID, PRINCIPAL_ID))


@pytest.fixture
def pedido_con_turno_vinculado():
    from database import get_db, init_db

    init_db()
    conn = get_db()
    try:
        _limpiar(conn)
        conn.execute(
            """
            INSERT INTO alquileres
                (id, numero_pedido, cliente_nombre, estado, tipo,
                 fecha_desde, fecha_hasta, monto_total, monto_pagado)
            VALUES (%s, %s, 'Cliente Roundtrip Vinculado', 'confirmado', 'diaria',
                    '2034-07-01', '2034-07-05', 100000, 0)
            """,
            (PRINCIPAL_ID, NUM_PRINCIPAL),
        )
        conn.execute(
            """
            INSERT INTO alquileres
                (id, numero_pedido, cliente_nombre, estado, tipo,
                 fecha_desde, fecha_hasta, monto_total, monto_pagado,
                 pedido_principal_id)
            VALUES (%s, %s, 'Cliente Roundtrip Vinculado', 'confirmado', 'estudio',
                    '2034-07-02 10:00', '2034-07-02 12:00', 30000, 0, %s)
            """,
            (TURNO_ID, NUM_TURNO, PRINCIPAL_ID),
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


def test_export_incluye_tipo_y_el_vinculo(pedido_con_turno_vinculado):
    from database import get_db
    from dataio.exporters import export_alquileres

    conn = get_db()
    try:
        rows = export_alquileres(conn)
    finally:
        conn.close()

    principal = next(r for r in rows if r["numero_pedido"] == NUM_PRINCIPAL)
    turno = next(r for r in rows if r["numero_pedido"] == NUM_TURNO)

    assert principal["tipo"] == "diaria"
    assert principal["pedido_principal_numero"] is None
    assert turno["tipo"] == "estudio"
    assert turno["pedido_principal_numero"] == NUM_PRINCIPAL


def test_import_no_desvincula_ni_convierte_el_turno_en_pedido_normal(
    pedido_con_turno_vinculado,
):
    """Round-trip completo: export → se borran las filas (ambiente fresco) →
    import → el turno vuelve como `tipo='estudio'` y atado a su principal.
    Sin el fix volvía como un alquiler 'diaria' suelto."""
    from database import get_db
    from dataio.exporters import export_alquileres
    from dataio.importers import import_alquileres
    from dataio.natural_keys import KeyResolver

    conn = get_db()
    try:
        rows = export_alquileres(conn)
        del_set = [r for r in rows if r["numero_pedido"] in (NUM_PRINCIPAL, NUM_TURNO)]
        assert len(del_set) == 2

        _limpiar(conn)
        conn.commit()

        import_alquileres(conn, del_set, KeyResolver(conn))
        conn.commit()

        principal = conn.execute(
            "SELECT id, tipo, pedido_principal_id FROM alquileres WHERE numero_pedido = %s",
            (NUM_PRINCIPAL,),
        ).fetchone()
        turno = conn.execute(
            "SELECT id, tipo, pedido_principal_id FROM alquileres WHERE numero_pedido = %s",
            (NUM_TURNO,),
        ).fetchone()

        assert principal is not None and turno is not None
        assert principal["tipo"] == "diaria"
        assert principal["pedido_principal_id"] is None
        assert turno["tipo"] == "estudio", "el turno no puede revivir como alquiler normal"
        assert turno["pedido_principal_id"] == principal["id"], (
            "el vínculo se re-resuelve por numero_pedido, con el id NUEVO del destino"
        )
    finally:
        # Los ids re-insertados son nuevos (serial) — limpiar por numero_pedido.
        conn.execute(
            "DELETE FROM alquileres WHERE numero_pedido IN (%s, %s)",
            (NUM_TURNO, NUM_PRINCIPAL),
        )
        conn.commit()
        conn.close()


def test_el_vinculo_se_resuelve_aunque_el_principal_venga_despues(
    pedido_con_turno_vinculado,
):
    """El orden del archivo no garantiza que el principal preceda a su turno —
    por eso el import ata los vínculos en una segunda pasada."""
    from database import get_db
    from dataio.exporters import export_alquileres
    from dataio.importers import import_alquileres
    from dataio.natural_keys import KeyResolver

    conn = get_db()
    try:
        rows = export_alquileres(conn)
        del_set = [r for r in rows if r["numero_pedido"] in (NUM_PRINCIPAL, NUM_TURNO)]
        # Turno PRIMERO, principal después.
        del_set.sort(key=lambda r: 0 if r["numero_pedido"] == NUM_TURNO else 1)

        _limpiar(conn)
        conn.commit()

        import_alquileres(conn, del_set, KeyResolver(conn))
        conn.commit()

        turno = conn.execute(
            "SELECT pedido_principal_id FROM alquileres WHERE numero_pedido = %s",
            (NUM_TURNO,),
        ).fetchone()
        principal = conn.execute(
            "SELECT id FROM alquileres WHERE numero_pedido = %s", (NUM_PRINCIPAL,)
        ).fetchone()
        assert turno["pedido_principal_id"] == principal["id"]
    finally:
        conn.execute(
            "DELETE FROM alquileres WHERE numero_pedido IN (%s, %s)",
            (NUM_TURNO, NUM_PRINCIPAL),
        )
        conn.commit()
        conn.close()
