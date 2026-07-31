"""Constantes compartidas entre `queries/` y `commands/` de `services/estudio/`
(y consumidas por `routes/estudio.py` para el CRUD de slots, y por
`routes/talleres.py` para el gate de publicación) — viven fuera de ambos
subpaquetes por el mismo motivo que `contabilidad/constants.py`."""

# Namespace del advisory lock para operaciones que validan+escriben en el estudio
# (slots y talleres). Privado de este flujo; evita colisión con el NS de pedidos.
_ADVISORY_NS_ESTUDIO = 5390413
