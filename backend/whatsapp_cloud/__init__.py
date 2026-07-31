"""whatsapp_cloud — core PORTABLE del envío por WhatsApp Business (Meta Cloud API).

Diseñado como LIBRERÍA reusable, mismo molde que `arca_fe`: este paquete NO importa
`backend.*` ni ningún framework (FastAPI, psycopg, etc.). Solo data plana + `httpx`.
El consumidor arma los datos y llama a la API pública; el I/O (persistencia, gating,
credenciales, resolución de teléfono, log de envíos) lo pone el adapter de cada app.

En Rambla el adapter vive en `backend/services/whatsapp/`. El día que se extraiga a un
paquete pip propio, este directorio se levanta tal cual. Un test de portabilidad
(`tests/test_portabilidad.py`) verifica que el core nunca importe `backend.*`.

Versionado (misma política que `arca_fe`): `__version__` arranca en `"0.0.0"` mientras
la librería no haya mandado un mensaje real en producción — no se bumpea por feature ni
por cambio de superficie hasta cruzar esa vara. Cuando se confirme el primer envío real,
arranca el SemVer de verdad en `"0.1.0"`.
"""

__version__ = "0.0.0"

from .modelos import EnvioResult, body_components
from .client import WhatsAppClient
from .retry import with_retry
from .errores import (
    WhatsAppError,
    WhatsAppAuthError,
    WhatsAppRateLimitError,
    WhatsAppNetworkError,
    WhatsAppResponseError,
    WhatsAppRequestError,
)

__all__ = [
    "__version__",
    # modelos + armado de components
    "EnvioResult",
    "body_components",
    # cliente HTTP
    "WhatsAppClient",
    # retry/backoff opcional
    "with_retry",
    # taxonomía de errores (todo lo que el cliente levanta hereda de WhatsAppError)
    "WhatsAppError",
    "WhatsAppAuthError",
    "WhatsAppRateLimitError",
    "WhatsAppNetworkError",
    "WhatsAppResponseError",
    "WhatsAppRequestError",
]
