"""Seed de email_templates en init_db() contra Postgres REAL (#fix sección rota).

Reproduce el bug: si la tabla `email_templates` está vacía, /admin/email-templates
no puede abrir ni previsualizar nada (render_template tira 404). Verifica que
init_db() siembra todas las plantillas del sistema y que el preview
(render_template) anda para cada una.

OPT-IN y SEGURO POR DEFECTO (mismo gating que los demás `*_db.py`):

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test \
      RESERVAS_DB_TEST=1 SECRET_KEY=dev \
      python -m pytest tests/test_email_templates_seed_db.py -v -m integration
"""
import os
from urllib.parse import urlparse

import pytest

_OPT_IN = os.getenv("RESERVAS_DB_TEST") == "1"
_DB_NAME = urlparse(os.getenv("DATABASE_URL", "")).path.lstrip("/")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _OPT_IN, reason="opt-in: RESERVAS_DB_TEST=1 + DATABASE_URL de test"),
    pytest.mark.skipif(
        _OPT_IN and "test" not in _DB_NAME.lower(),
        reason=f"DATABASE_URL ({_DB_NAME!r}) no parece base de test — abortado",
    ),
]

EXPECTED_KEYS = {
    "pedido_creado_cliente",
    "pedido_confirmado_cliente",
    "pedido_creado_admin",
    "recordatorio_retiro",
}

_CTX = {
    "cliente_nombre": "Juan Pérez",
    "cliente_email": "juan@ejemplo.com",
    "cliente_telefono": "+54 9 223 585 2510",
    "numero_pedido": "1234",
    "fecha_desde": "20 may · 10:00",
    "fecha_hasta": "24 may · 18:00",
    "total": "$ 12.500",
    "notas": "Trípode extra.",
    "items_html": "<p>Sony FX3 × 1</p>",
    "items_text": "- Sony FX3 × 1",
    "admin_url": "https://x/admin",
    "portal_url": "https://x/portal",
}


def test_init_db_siembra_y_el_preview_anda():
    from database import init_db, get_db
    from services.email import render_template

    # Asegura que el esquema exista: este archivo puede ser el PRIMERO en tocar
    # la BD descartable del job de CI (test_alembic_upgrade_db.py no deja el
    # suyo instalado para los pasos siguientes — cada `*_db.py` es responsable
    # de su propio init_db(), mismo criterio que test_login_identities_db.py).
    init_db()

    # Punto de partida: tabla VACÍA (reproduce el estado roto).
    conn = get_db()
    try:
        conn.execute("DELETE FROM email_templates WHERE key = ANY(%s)", (list(EXPECTED_KEYS),))
        conn.commit()
    finally:
        conn.close()

    # init_db() debe re-sembrarlas todas (idempotente).
    init_db()

    conn = get_db()
    try:
        rows = conn.execute("SELECT key FROM email_templates").fetchall()
        keys = {r["key"] for r in rows}
    finally:
        conn.close()
    assert EXPECTED_KEYS <= keys, f"faltan: {EXPECTED_KEYS - keys}"

    # El preview (lo que estaba roto) ahora renderiza para cada plantilla.
    for key in EXPECTED_KEYS:
        out = render_template(key, _CTX)
        assert out["subject"].strip()
        assert out["html"].strip()
        assert "Juan Pérez" in out["html"] or "1234" in out["html"]


def test_seed_no_pisa_ediciones_del_admin():
    from database import init_db, get_db

    init_db()  # asegura el esquema, por si este test corre primero

    # Simular una plantilla editada por un admin.
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO email_templates (key, subject, body_html, body_text, updated_by)
            VALUES ('pedido_creado_cliente', 'EDITADO', '<p>editado</p>', 'editado', 'admin@x.com')
            ON CONFLICT (key) DO UPDATE
            SET subject = EXCLUDED.subject, body_html = EXCLUDED.body_html,
                body_text = EXCLUDED.body_text, updated_by = EXCLUDED.updated_by
            """
        )
        conn.commit()
    finally:
        conn.close()

    init_db()  # no debe pisar (ON CONFLICT DO NOTHING)

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT subject FROM email_templates WHERE key = 'pedido_creado_cliente'"
        ).fetchone()
    finally:
        conn.close()
    assert row["subject"] == "EDITADO"

    # Restaurar el contenido canónico para no contaminar otros tests.
    conn = get_db()
    try:
        conn.execute("DELETE FROM email_templates WHERE key = 'pedido_creado_cliente'")
        conn.commit()
    finally:
        conn.close()
    init_db()


def test_pedido_creado_cliente_no_escapa_la_tabla_de_items():
    """Regresión de un bug real en staging (migración `p3d1d0cr34d0`): esta fila
    había quedado congelada en copy prehistórico con `{{ items_html }}` SIN
    `|safe` — Jinja (autoescape=True) escapaba el HTML de la tabla entero, que
    se veía como texto crudo (`<table role="presentation" ...>` visible) en vez
    de una tabla real. Verifica el contenido HOY vigente en la BD — si alguna
    vez alguien vuelve a congelar esta fila sin `|safe`, esto lo caza."""
    from database import init_db
    from services.email import render_template

    init_db()  # asegura el esquema + el seed canónico, por si corre solo

    ctx = dict(_CTX, items_html="<table><tr><td>Sony FX3</td></tr></table>")
    out = render_template("pedido_creado_cliente", ctx)
    assert "<table><tr><td>Sony FX3</td></tr></table>" in out["html"]
    assert "&lt;table&gt;" not in out["html"]


def test_ninguna_plantilla_con_items_html_escapa_la_tabla():
    """Generaliza la regresión anterior a TODA la clase de bug (migración
    `1t3mss4f3f1x`): se encontró el mismo defecto en `pedido_confirmado_cliente`
    (screenshot del dueño) después de haber arreglado solo `pedido_creado_cliente`
    — dos filas con el mismo síntoma confirman que es una clase, no un caso
    aislado. Recorre TODAS las keys cuya plantilla canónica usa
    `items_html|safe` y verifica que la fila vigente en la BD renderiza la
    tabla sin escapar, para que un tercer caso no vuelva a colarse en silencio."""
    from database import init_db
    from services.email import render_template
    from services.email.default_templates import DEFAULT_TEMPLATES

    init_db()  # asegura el esquema + el seed canónico, por si corre solo

    keys_con_items = [
        key for key, tpl in DEFAULT_TEMPLATES.items()
        if "{{ items_html|safe }}" in tpl["body_html"]
    ]
    assert keys_con_items  # sanity: la lista no está vacía

    ctx = dict(_CTX, items_html="<table><tr><td>Sony FX3</td></tr></table>")
    for key in keys_con_items:
        out = render_template(key, ctx)
        assert "<table><tr><td>Sony FX3</td></tr></table>" in out["html"], key
        assert "&lt;table&gt;" not in out["html"], key
