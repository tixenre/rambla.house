"""Tests puros del seed de plantillas de email (default_templates).

La sección /admin/email-templates se rompía cuando la tabla `email_templates`
quedaba vacía (las filas vivían solo en migraciones; con migraciones trabadas,
nada que abrir/previsualizar). Ahora `init_db()` siembra el contenido desde
`services/email/default_templates.py`. Estos tests fijan que ese contenido esté
completo y bien formado (sin tocar DB).
"""
from services.email.default_templates import DEFAULT_TEMPLATES

EXPECTED_KEYS = {
    "pedido_creado_cliente",
    "pedido_confirmado_cliente",
    "pedido_creado_admin",
    "recordatorio_retiro",
    "modificacion_solicitada_admin",
    "modificacion_resuelta_cliente",
    "modificacion_cancelada_admin",
    "taller_inscripcion_admin",
    "taller_inscripcion_cliente",
    "taller_cambio_datos",
    # F4b: seña (verificar) + ofrecer cupo al siguiente + interesados.
    "taller_sena_confirmada",
    "taller_cupo_ofrecido",
    "taller_interesado_nueva_edicion",
}


def test_estan_todas_las_plantillas():
    assert set(DEFAULT_TEMPLATES) == EXPECTED_KEYS


def test_ningun_campo_vacio():
    for key, tpl in DEFAULT_TEMPLATES.items():
        for field in ("subject", "body_html", "body_text"):
            assert tpl[field].strip(), f"{key}.{field} está vacío"


def test_jinja_balanceado_sin_doble_escape():
    # Tras el f-string no debe quedar doble-escape residual ({{{{ / }}}}), y las
    # llaves Jinja {{ }} deben quedar balanceadas.
    for key, tpl in DEFAULT_TEMPLATES.items():
        for field in ("subject", "body_html", "body_text"):
            s = tpl[field]
            assert "{{{{" not in s and "}}}}" not in s, f"{key}.{field} doble-escape"
            assert s.count("{{") == s.count("}}"), f"{key}.{field} llaves desbalanceadas"


def test_idempotentes_son_subconjunto():
    # Las plantillas marcadas idempotentes en el service tienen que existir en el seed.
    from services.email.service import _IDEMPOTENT_PER_PEDIDO

    assert _IDEMPOTENT_PER_PEDIDO <= set(DEFAULT_TEMPLATES)
