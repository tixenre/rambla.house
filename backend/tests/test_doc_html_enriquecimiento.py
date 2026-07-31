"""`_doc_html` (documentos.py) — cada documento enriquece con los datos fiscales
que su propia plantilla necesita.

Candado de fuente (mismo patrón que `test_contenido_sql_safety.py`/
`test_finanzas_flujo_source_scan.py`, inspect.getsource + assert sobre el
texto): los 4 documentos (Remito, Detalle de seguro, Checklist de retiro,
Contrato) comparten la plantilla `_cliente_block` (pdf_templates.py), que
muestra el CUIT si `pedido["cliente_cuit"]` está seteado — así que los 4
branches de `_doc_html` deben llamar `_enriquecer_pedido_con_cliente_fiscal`
para que ese dato llegue. Hallazgo de auditoría (#1254): "Detalle de seguro"
(entonces `kind="albaran"` — el nombre interno quedó desactualizado; renombrado
a `kind="detalle-seguro"` en #1313) era el único que no lo hacía.
"""
import inspect

import pytest

from routes.alquileres.documentos import _doc_html

pytestmark = pytest.mark.unit


def _src_kind(kind: str) -> str:
    """Extrae el bloque `if kind == "..."` de `_doc_html` para ese kind puntual
    (hasta el próximo `if kind ==` o el final de la función) — así un branch no
    puede "pasar" el candado porque OTRO branch sí llama al enriquecimiento."""
    src = inspect.getsource(_doc_html)
    marker = f'if kind == "{kind}"'
    start = src.index(marker)
    resto = src[start + len(marker):]
    siguiente = resto.find('if kind ==')
    return resto[:siguiente] if siguiente != -1 else resto


@pytest.mark.parametrize("kind", ["remito", "detalle-seguro", "checklist-retiro", "contrato"])
def test_doc_html_enriquece_datos_fiscales(kind):
    bloque = _src_kind(kind)
    assert "_enriquecer_pedido_con_cliente_fiscal" in bloque, (
        f"_doc_html(kind='{kind}') no llama _enriquecer_pedido_con_cliente_fiscal — "
        f"su plantilla (_cliente_block, compartida por los 4 documentos) muestra el "
        f"CUIT si está presente, así que los 4 branches deben enriquecerlo."
    )
