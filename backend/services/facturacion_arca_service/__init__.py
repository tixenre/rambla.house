"""backend.services.facturacion_arca_service — motor de facturación ARCA/AFIP NUEVO,
sobre `arca_service_client` (tixenre/arca-service-sdk), EN PARALELO al motor existente
`services/facturacion/` (`arca_fe`) — no lo reemplaza, no lo importa, no lo toca.

Por qué en paralelo y no adentro de `services/facturacion/`: son dos integraciones
completamente distintas contra ARCA (`arca_fe` habla WSAA/WSFE directo por SOAP con
credenciales por `emisores_arca`; `arca-service` es un servicio HTTP aparte, con su
propio modelo Cliente/Plataforma) — mezclarlas en el mismo paquete acoplaría dos cosas
que today conviven a propósito sin tocarse, mientras se evalúa si `arca-service`
reemplaza a `arca_fe` más adelante.

Estructura:
    client.py       — factory de ArcaServiceClient/AsyncArcaServiceClient desde config
                       (ARCA_SERVICE_*, ver backend/config.py). Inerte sin credenciales.
    comprobante.py   — mapea un pedido de Rambla a `arca_service_client.ComprobanteInput`.
                       Reusa `services.facturacion.engine._get_pedido` (lectura, general,
                       no específico de arca_fe) para los datos ya enriquecidos; no
                       importa nada más de `services/facturacion/`.

Credenciales: se consiguen con `arca-service-client login` (self-serve, corrido a mano
por el dueño) — este módulo nunca las genera ni las pide, solo las lee de env vars."""
