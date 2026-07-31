"""Guard de portabilidad: el core whatsapp_cloud NO puede importar backend.* ni frameworks.

Gemelo de `arca_fe/tests/test_portabilidad.py` — mismo invariante duro: la librería es
portable (solo data plana + httpx), todo el I/O y las decisiones viven en el adapter
`services/whatsapp/`.
"""
from __future__ import annotations

import pathlib
import re

_CORE_PKG = pathlib.Path(__file__).parent.parent  # .../backend/whatsapp_cloud/


def _iter_core_sources():
    """Itera los .py del core, excluyendo los tests (que sí pueden importar lo que quieran)."""
    for py in _CORE_PKG.glob("*.py"):
        if not py.name.startswith("test_"):
            yield py


def test_sin_imports_backend():
    """Ningún módulo del core importa backend.* ."""
    pattern = re.compile(r"^\s*(import\s+backend|from\s+backend)\b", re.MULTILINE)
    violators = [py.name for py in _iter_core_sources() if pattern.search(py.read_text())]
    assert not violators, f"whatsapp_cloud core no debe importar backend.*: {violators}"


def test_sin_imports_fastapi():
    """Ningún módulo del core importa fastapi."""
    pattern = re.compile(r"^\s*(import\s+fastapi|from\s+fastapi)\b", re.MULTILINE)
    violators = [py.name for py in _iter_core_sources() if pattern.search(py.read_text())]
    assert not violators, f"whatsapp_cloud core no debe importar fastapi: {violators}"


def test_sin_imports_psycopg():
    """Ningún módulo del core importa psycopg (acceso a BD)."""
    pattern = re.compile(r"^\s*(import\s+psycopg|from\s+psycopg)\b", re.MULTILINE)
    violators = [py.name for py in _iter_core_sources() if pattern.search(py.read_text())]
    assert not violators, f"whatsapp_cloud core no debe importar psycopg: {violators}"


def test_version_semver():
    """El __version__ existe y tiene formato SemVer X.Y.Z."""
    import whatsapp_cloud

    parts = whatsapp_cloud.__version__.split(".")
    assert len(parts) == 3, f"__version__ no es SemVer: {whatsapp_cloud.__version__!r}"
    assert all(p.isdigit() for p in parts), f"__version__ no es numérico: {whatsapp_cloud.__version__!r}"


def test_all_exports_son_importables():
    """Todo símbolo en __all__ es importable desde el paquete."""
    import whatsapp_cloud

    for name in whatsapp_cloud.__all__:
        assert hasattr(whatsapp_cloud, name), f"'{name}' en __all__ pero no importable"
