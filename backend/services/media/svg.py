"""Detección + sanitización de SVG subido por un admin.

Extraído de `routes/marcas.py` (único caller hasta ahora) para reusarlo
en `routes/talleres.py` (logo de institución) sin duplicar la lógica de
sanitización — es código de seguridad (defensa en profundidad contra XSS
en un SVG que se inlinea en el DOM), duplicarlo arriesga que un futuro
fix de seguridad se aplique en una copia y no en la otra.
"""

import re


def is_svg(raw: bytes, filename: str | None) -> bool:
    """Heurística para detectar SVG: o el nombre termina en .svg, o los
    primeros bytes contienen <?xml o <svg.
    """
    if filename and filename.lower().endswith(".svg"):
        return True
    head = raw[:512].lstrip().lower()
    return head.startswith(b"<?xml") or head.startswith(b"<svg")


def sanitize_svg(raw: bytes) -> bytes:
    """Strip <script> tags y atributos on* del SVG antes de subirlo a R2.
    Defensa en profundidad — los uploads requieren admin auth pero un
    admin comprometido podría inyectar XSS en cualquier página que inline
    el SVG.
    """
    text = raw.decode("utf-8", errors="ignore")
    # <script>...</script> (sin importar atributos)
    text = re.sub(r"<\s*script\b[^>]*>.*?<\s*/\s*script\s*>",
                  "", text, flags=re.IGNORECASE | re.DOTALL)
    # <script ... /> auto-closed
    text = re.sub(r"<\s*script\b[^>]*/\s*>", "", text, flags=re.IGNORECASE)
    # atributos on* (onclick, onload, onerror, etc.) — match con/sin comillas
    text = re.sub(r'\s+on[a-z]+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)',
                  "", text, flags=re.IGNORECASE)
    # <foreignObject> permite HTML arbitrario adentro del SVG → tirarlo.
    text = re.sub(r"<\s*foreignObject\b[^>]*>.*?<\s*/\s*foreignObject\s*>",
                  "", text, flags=re.IGNORECASE | re.DOTALL)
    return text.encode("utf-8")
