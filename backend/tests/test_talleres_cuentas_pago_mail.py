"""Tests puros (sin DB) del fix de cuentas de cobro en el mail de inscripción
a un taller (hallazgo del supervisor, 2026-08-13): el admin edita la lista de
cuentas desde "Precios y forma de pago" (`edicion_cuentas_pago`), pero el mail
de confirmación seguía interpolando los 3 campos viejos (`pago_alias`/
`pago_cbu`/`pago_banco`) — un cambio de cuenta en la UI no se reflejaba en el
mail. Cubre los dos helpers nuevos (`routes/talleres.py`) y el render REAL del
template `taller_inscripcion_cliente` (Jinja de verdad, no un mock) con el
contexto que arman.
"""
from routes.talleres import _cuentas_pago_efectivas, _cuentas_pago_para_mail


# ── _cuentas_pago_efectivas ───────────────────────────────────────────────────

def test_efectivas_usa_la_lista_si_trae_algo():
    cuentas = [{"alias": "rambla.mp", "cbu": "", "banco": ""}]
    out = _cuentas_pago_efectivas(cuentas, pago_alias="viejo", pago_cbu="", pago_banco="")
    assert out == cuentas


def test_efectivas_cae_a_los_campos_viejos_si_la_lista_esta_vacia():
    out = _cuentas_pago_efectivas([], pago_alias="alias.viejo", pago_cbu="CBU123", pago_banco="Galicia")
    assert out == [{"alias": "alias.viejo", "cbu": "CBU123", "banco": "Galicia"}]


def test_efectivas_vacio_si_no_hay_nada_en_ningun_lado():
    assert _cuentas_pago_efectivas([], pago_alias="", pago_cbu="", pago_banco="") == []


# ── _cuentas_pago_para_mail ───────────────────────────────────────────────────

def test_para_mail_una_cuenta_completa():
    html, text = _cuentas_pago_para_mail([{"alias": "rambla.mp", "cbu": "CBU999", "banco": "Galicia"}])
    assert "rambla.mp" in html and "CBU999" in html and "Galicia" in html
    assert "<strong>Alias:</strong>" in html
    assert "  Alias: rambla.mp" in text
    assert "  CBU: CBU999" in text
    assert "  Banco: Galicia" in text


def test_para_mail_salta_campos_vacios_sin_separador_colgando():
    """Mismo criterio que `DatosPago`/`UnaCuenta` del frontend: un campo vacío
    no deja un separador colgando (ej. "CBU: ")."""
    html, text = _cuentas_pago_para_mail([{"alias": "rambla.mp", "cbu": "", "banco": ""}])
    assert "CBU" not in html and "Banco" not in html
    assert "CBU" not in text and "Banco" not in text
    assert "rambla.mp" in html and "rambla.mp" in text


def test_para_mail_multiples_cuentas_un_bloque_cada_una():
    cuentas = [
        {"alias": "cuenta.uno", "cbu": "", "banco": ""},
        {"alias": "cuenta.dos", "cbu": "", "banco": ""},
    ]
    html, text = _cuentas_pago_para_mail(cuentas)
    assert html.count("<p") == 2
    assert "cuenta.uno" in html and "cuenta.dos" in html
    assert "cuenta.uno" in text and "cuenta.dos" in text


def test_para_mail_escapa_html_en_los_valores():
    html, _ = _cuentas_pago_para_mail([{"alias": "<script>x</script>", "cbu": "", "banco": ""}])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_para_mail_lista_vacia_da_strings_vacios():
    assert _cuentas_pago_para_mail([]) == ("", "")


# ── Render REAL del template (Jinja de verdad, no mock) ──────────────────────

def _render(cuentas_pago_html: str, cuentas_pago_text: str) -> tuple[str, str]:
    from services.email.default_templates import DEFAULT_TEMPLATES
    from services.email.service import _jinja_html, _jinja_text

    tpl = DEFAULT_TEMPLATES["taller_inscripcion_cliente"]
    ctx = {
        "en_lista_espera": False,
        "nombre_pila": "Santiago",
        "taller_nombre": "Workshop de prueba",
        "tipo_taller": "intensivo",
        "fecha_inicio_str": "sábado 12 de agosto",
        "fecha_fin_str": "domingo 13 de agosto",
        "horario": "10:00 a 18:00",
        "direccion": "Chaco 1392",
        "precio_sena_str": "$ 15.000",
        "cuentas_pago_html": cuentas_pago_html,
        "cuentas_pago_text": cuentas_pago_text,
        "tiene_ics": False,
    }
    html = _jinja_html.from_string(tpl["body_html"]).render(**ctx)
    text = _jinja_text.from_string(tpl["body_text"]).render(**ctx)
    return html, text


def test_render_real_con_una_cuenta():
    html_frag, text_frag = _cuentas_pago_para_mail(
        [{"alias": "rambla.mp", "cbu": "CBU999", "banco": "Galicia"}]
    )
    html, text = _render(html_frag, text_frag)
    for out in (html, text):
        assert "rambla.mp" in out
        assert "CBU999" in out
        assert "Galicia" in out
        # Nada de sintaxis Jinja cruda sobreviviendo al render.
        assert "{%" not in out and "{{" not in out


def test_render_real_con_dos_cuentas():
    html_frag, text_frag = _cuentas_pago_para_mail(
        [
            {"alias": "cuenta.uno", "cbu": "", "banco": ""},
            {"alias": "cuenta.dos", "cbu": "", "banco": ""},
        ]
    )
    html, text = _render(html_frag, text_frag)
    for out in (html, text):
        assert "cuenta.uno" in out
        assert "cuenta.dos" in out
