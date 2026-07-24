"""Tests del contexto de mails de pedido + la guarda de la migración de copy.

- `_pedido_email_context()` arma URLs **absolutas** (portal_url + admin_url): en un
  cliente de mail un link relativo no resuelve.
- `numero_pedido` cae al `id` cuando falta (filas legacy).
- La migración `e7c3a9f5d1b8` (copy nuevo) sólo pisa el template si sigue idéntico
  al default original sembrado en `a4e8c2b9d710` → sus constantes `_*_OLD_*` deben
  coincidir EXACTAMENTE con ese seed, o la guarda haría un no-op silencioso (y la
  garantía de "no pisar ediciones del admin" sería falsa).
"""
import datetime
import importlib.util
from pathlib import Path

import pytest

from routes.alquileres import _pedido_email_context, _cuerpo_mail_simple
from config import SITE_URL

pytestmark = pytest.mark.unit

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "versions"


def _load_migration(filename: str):
    path = VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── formato lindo del contexto ──────────────────────────────────────────────

class TestContextoFormato:
    def test_total_formateado_ars(self):
        ctx = _pedido_email_context({"id": 1, "monto_total": 12500, "items": []})
        assert ctx["total"] == "$ 12.500"

    def test_fecha_amable(self):
        ctx = _pedido_email_context(
            {"id": 1, "fecha_desde": datetime.datetime(2026, 6, 15, 10, 0), "items": []}
        )
        assert ctx["fecha_desde"] == "15 jun · 10:00"

    def test_items_html_es_tabla_con_nombre_escapado(self):
        # Nombre con HTML malicioso → debe quedar escapado (XSS-safe) aunque el
        # blob se inyecte con |safe en la plantilla.
        ctx = _pedido_email_context(
            {
                "id": 1,
                "items": [{"nombre": "<b>Cam</b>", "cantidad": 2, "subtotal": 9000}],
            }
        )
        html = ctx["items_html"]
        assert "<table" in html
        assert "&lt;b&gt;Cam&lt;/b&gt;" in html
        assert "<b>Cam</b>" not in html
        assert "× 2" in html
        assert "$ 9.000" in html

    def test_items_vacio_no_rompe(self):
        ctx = _pedido_email_context({"id": 1, "items": []})
        assert ctx["items_html"] == ""
        assert ctx["items_text"] == ""

    def test_items_html_muestra_fila_de_descuento_si_hay_bonificacion(self):
        # Bug (#1209, L1): el ítem mostraba el bruto por línea ($30.000, el
        # ejemplo real: 1 cámara a $10.000/día × 3 jornadas) y el "Total" del
        # mail el neto con el 10% de descuento por jornadas ya aplicado
        # ($27.000), sin ningún renglón que explicara la diferencia. Mismo
        # criterio bruto→descuento→neto que el Presupuesto
        # (`pdf_templates._pedido_html`): ahora la tabla de ítems trae una
        # fila de "Descuento" visible entre el bruto y el total.
        ctx = _pedido_email_context(
            {
                "id": 1,
                "items": [{"nombre": "Cámara", "cantidad": 1, "subtotal": 30000}],
                "descuento_monto": 3000,
                # `descuento_efectivo_pct` (el % GANADOR, lo que expone
                # `desglose_de_pedido` desde la Fase C-1, #1219) — no
                # `descuento_pct` crudo, que es solo el override manual.
                "descuento_efectivo_pct": 10,
            }
        )
        html = ctx["items_html"]
        assert "Descuento" in html
        assert "(10%)" in html
        assert "− $ 3.000" in html  # mismo signo "−" (U+2212) que el Presupuesto

    def test_items_html_sin_descuento_no_muestra_fila(self):
        # Regresión: un pedido sin descuento no debe ganar una fila espuria.
        ctx = _pedido_email_context(
            {
                "id": 1,
                "items": [{"nombre": "Cámara", "cantidad": 1, "subtotal": 30000}],
                "descuento_monto": 0,
            }
        )
        assert "Descuento" not in ctx["items_html"]


# ── info "estilo pasaje": jornadas + estado de pago ─────────────────────────

class TestContextoReserva:
    def test_jornadas_derivadas_de_fechas(self):
        ctx = _pedido_email_context(
            {
                "id": 1,
                "fecha_desde": datetime.datetime(2026, 6, 15, 10, 0),
                "fecha_hasta": datetime.datetime(2026, 6, 17, 10, 0),
                "items": [],
            }
        )
        assert ctx["cantidad_jornadas"] == 2

    def test_jornadas_ya_enriquecidas_tienen_prioridad(self):
        # Si el pedido ya trae cantidad_jornadas (de _enriquecer_pedido_con_total),
        # se reusa en vez de recalcular.
        ctx = _pedido_email_context({"id": 1, "cantidad_jornadas": 5, "items": []})
        assert ctx["cantidad_jornadas"] == 5

    def test_pago_completo(self):
        ctx = _pedido_email_context(
            {"id": 1, "monto_total": 10000, "monto_pagado": 10000, "items": []}
        )
        assert ctx["pago_estado"] == "Pago completo ✓"
        assert ctx["saldo_pendiente"] == "$ 0"

    def test_pago_parcial_muestra_sena_y_saldo(self):
        ctx = _pedido_email_context(
            {"id": 1, "monto_total": 10000, "monto_pagado": 4000, "items": []}
        )
        assert ctx["pago_estado"] == "Pagado $ 4.000 · saldo pendiente $ 6.000"
        assert ctx["total_pagado"] == "$ 4.000"
        assert ctx["saldo_pendiente"] == "$ 6.000"

    def test_pago_pendiente(self):
        ctx = _pedido_email_context(
            {"id": 1, "monto_total": 10000, "monto_pagado": 0, "items": []}
        )
        assert ctx["pago_estado"] == "Pendiente de pago"

    def test_sin_total_no_muestra_estado_de_pago(self):
        ctx = _pedido_email_context({"id": 1, "monto_total": 0, "items": []})
        assert ctx["pago_estado"] == ""


# ── render de los templates enriquecidos al cliente ─────────────────────────

class TestTemplatesEnriquecidos:
    """Los mails al cliente (creado/confirmado) suman secciones nuevas. El
    mismo template tiene que servir para el disparo automático (sin nota ni
    adjuntos) y para el envío manual desde el modal (con `mensaje_admin` +
    `docs_adjuntos`) — vía bloques `{% if %}`."""

    import jinja2 as _jinja2

    _env_html = _jinja2.Environment(autoescape=True)
    _env_text = _jinja2.Environment(autoescape=False)

    _CTX = {
        "cliente_nombre": "Juan Pérez",
        "numero_pedido": 1234,
        "fecha_desde": "20 may · 10:00",
        "fecha_hasta": "24 may · 18:00",
        "cantidad_jornadas": 4,
        "periodo_label": "4 jornadas",  # lo que produciría _pedido_email_context para cantidad_jornadas=4
        "total": "$ 12.500",
        "pago_estado": "Pagado $ 6.250 · saldo pendiente $ 6.250",
        "items_html": "<table></table>",
        "items_text": "- Sony FX3 × 1",
        "portal_url": "https://x/cliente/portal",
        "gcal_url": "https://cal",
    }

    def _tpl(self, key: str):
        from services.email.default_templates import DEFAULT_TEMPLATES

        return DEFAULT_TEMPLATES[key]

    def _render(self, key: str, ctx: dict) -> tuple[str, str]:
        tpl = self._tpl(key)
        # Espeja el render real: el saludo usa el nombre de pila derivado.
        ctx = {
            "cliente_nombre_pila": (ctx.get("cliente_nombre") or "").split()[0]
            if ctx.get("cliente_nombre")
            else "",
            **ctx,
        }
        return (
            self._env_html.from_string(tpl["body_html"]).render(**ctx),
            self._env_text.from_string(tpl["body_text"]).render(**ctx),
        )

    @pytest.mark.parametrize(
        "key", ["pedido_creado_cliente", "pedido_confirmado_cliente"]
    )
    def test_saludo_por_nombre_de_pila(self, key):
        # "Juan Pérez" → "Hola Juan," (solo nombre de pila, no el apellido).
        html, text = self._render(key, self._CTX)
        assert "Hola Juan," in html
        assert "Hola Juan," in text
        assert "Hola Juan Pérez" not in html

    @pytest.mark.parametrize(
        "key", ["pedido_creado_cliente", "pedido_confirmado_cliente"]
    )
    def test_modo_modal_muestra_nota_jornadas_y_adjuntos(self, key):
        ctx = {
            **self._CTX,
            "mensaje_admin": "¡Te esperamos el jueves!",
            "docs_adjuntos": ["Contrato", "Cotización"],
        }
        html, text = self._render(key, ctx)
        assert "Duración:</strong> 4 jornadas" in html
        assert "¡Te esperamos el jueves!" in html
        assert "Contrato, Cotización" in html
        assert "Duración: 4 jornadas" in text
        assert "Contrato, Cotización" in text

    def test_confirmado_sin_adjuntos_cae_al_portal(self):
        # Disparo automático: sin nota ni adjuntos no debe filtrar esos bloques.
        html, _ = self._render("pedido_confirmado_cliente", self._CTX)
        assert "descargar el <strong>remito</strong>" in html
        assert "Te adjuntamos en este mail" not in html

    def test_confirmado_muestra_estado_de_pago(self):
        html, text = self._render("pedido_confirmado_cliente", self._CTX)
        assert "saldo pendiente $ 6.250" in html
        assert "saldo pendiente $ 6.250" in text


# ── cuerpo del mail "mensaje simple" (compartido envío + preview) ───────────

class TestCuerpoMailSimple:
    def test_subject_y_lista_de_docs(self):
        subject, body_html, text = _cuerpo_mail_simple(
            1023, "Juan Pérez", ["contrato", "pdf"], None
        )
        assert subject == "Documentos de tu pedido #1023"
        # El saludo es por nombre de pila, no el nombre completo.
        assert "Hola Juan," in body_html
        assert "Juan Pérez" not in body_html
        assert "Contrato" in body_html and "Remito" in body_html
        assert "Contrato, Remito" in text

    def test_sin_nombre_usa_saludo_generico(self):
        _, body_html, _ = _cuerpo_mail_simple(1, "", ["pdf"], None)
        assert "<p>Hola,</p>" in body_html

    def test_nota_del_admin_se_escapa(self):
        # El mensaje lo escribe el admin; igual se escapa por las dudas (XSS).
        _, body_html, _ = _cuerpo_mail_simple(1, "Ana", ["pdf"], "<b>ojo</b>")
        assert "&lt;b&gt;ojo&lt;/b&gt;" in body_html
        assert "<b>ojo</b>" not in body_html


# ── _pedido_email_context ───────────────────────────────────────────────────

class TestPedidoEmailContext:
    def test_urls_absolutas(self):
        ctx = _pedido_email_context({"id": 123, "numero_pedido": 1023, "items": []})
        assert ctx["portal_url"] == f"{SITE_URL}/cliente/portal"
        assert ctx["admin_url"] == f"{SITE_URL}/admin/pedidos/123"
        # Ambas tienen que ser absolutas para funcionar dentro de un mail.
        assert ctx["portal_url"].startswith("http")
        assert ctx["admin_url"].startswith("http")

    def test_numero_pedido_usa_el_valor_propio(self):
        ctx = _pedido_email_context({"id": 7, "numero_pedido": 1023, "items": []})
        assert ctx["numero_pedido"] == 1023

    def test_numero_pedido_cae_al_id_si_falta(self):
        ctx = _pedido_email_context({"id": 7, "items": []})
        assert ctx["numero_pedido"] == 7


# ── Guarda de la migración de copy ──────────────────────────────────────────

class TestMigracionCopyGuard:
    def test_old_constants_coinciden_con_el_seed_original(self):
        infra = _load_migration("a4e8c2b9d710_email_infra.py")
        copy = _load_migration("e7c3a9f5d1b8_email_copy_portal_link.py")

        # _DEFAULTS: lista de (key, subject, body_html, body_text)
        seed = {row[0]: (row[1], row[2], row[3]) for row in infra._DEFAULTS}

        creado_subj, creado_html, creado_text = seed["pedido_creado_cliente"]
        assert copy._CREADO_OLD_SUBJECT == creado_subj
        assert copy._CREADO_OLD_HTML == creado_html
        assert copy._CREADO_OLD_TEXT == creado_text

        conf_subj, conf_html, conf_text = seed["pedido_confirmado_cliente"]
        assert copy._CONFIRMADO_SUBJECT == conf_subj
        assert copy._CONFIRMADO_OLD_HTML == conf_html
        assert copy._CONFIRMADO_OLD_TEXT == conf_text

    def test_copy_nuevo_referencia_el_portal(self):
        copy = _load_migration("e7c3a9f5d1b8_email_copy_portal_link.py")
        # El copy nuevo al cliente debe incluir el link al portal.
        assert "{{ portal_url }}" in copy._CREADO_NEW_HTML
        assert "{{ portal_url }}" in copy._CREADO_NEW_TEXT
        assert "{{ portal_url }}" in copy._CONFIRMADO_NEW_HTML
        assert "{{ portal_url }}" in copy._CONFIRMADO_NEW_TEXT
