# Sistema: WhatsApp — notificaciones salientes por Meta Cloud API

> Manual técnico (fuente única del **cómo funciona**). Las reglas de criterio y el
> _porqué_ viven en `MEMORIA.md`/`DECISIONES.md` y se **linkean**, no se copian.
> Índice maestro en `MANIFIESTO.md` §8.
>
> **Estado:** describe el scaffold inicial del canal (rama
> `claude/whatsapp-business-integration-nv589d`). Lo que quedó **fuera a propósito**
> —la captura de opt-in en el front— está marcado al final como **pendiente**.

## Qué resuelve

Un **único canal** para mandar notificaciones de WhatsApp a los clientes (recordatorios,
confirmaciones, avisos), acoplado a la **boca de notificaciones que ya existe** para el
mail — no un sistema paralelo. Materializa la _2026-05-27 — Notificaciones canal-agnósticas_
("multi-canal a un punto único, mail hoy, WhatsApp follow-up; se activan por config, no
código"): el mail sale como siempre y, para el mismo evento, se le suma el canal WhatsApp.

## Arquitectura: dos capas (molde `arca_fe`)

Mismo patrón lib-agnóstica + adapter que la facturación ARCA (`SISTEMA_FACTURACION.md`):

| Capa | Paquete | Qué contiene |
| --- | --- | --- |
| **Librería portable** | `backend/whatsapp_cloud/` | Cliente HTTP de la Cloud API (Graph) + errores tipados + retry. **Cero** imports de `backend.*`/FastAPI/psycopg (invariante verificado por `whatsapp_cloud/tests/test_portabilidad.py`). Recibe credenciales + `base_url` ya resueltas; devuelve resultado (`wamid`) o error tipado. No persiste, no gatea, no elige número. |
| **Adapter Rambla** | `backend/services/whatsapp/` | Todo el I/O y las decisiones: credenciales/gating (`config.py`), readiness (`estado.py`), registro de templates (`plantillas.py`) y la **boca de envío** fail-safe + idempotente (`envio.py`). |

### Librería `whatsapp_cloud/`
- `client.py::WhatsAppClient.enviar_template(to, template_name, lang_code, body_params)` → `POST {base}/{phone_number_id}/messages`. Mapea la respuesta de Meta a `EnvioResult(wamid)` o a la taxonomía tipada.
- `errores.py`: `WhatsAppError` base + `WhatsAppAuthError` / `WhatsAppRateLimitError` / `WhatsAppNetworkError` / `WhatsAppRequestError` (Meta rechazó por número/template) / `WhatsAppResponseError` (respuesta inesperada). El **tipo decide** reintentar/avisar (espejo de `arca_fe.errores`). Los códigos de credencial de Meta (190, etc.) mandan sobre el HTTP status.
- `retry.py::with_retry`: opt-in, reintenta solo network + rate-limit (respeta `Retry-After`).
- `__version__` arranca en `"0.0.0"` (misma política que `arca_fe`: bumpea al primer envío real en prod).

### Adapter `services/whatsapp/`
- `config.py`: `resolver_creds()` (de ENV), `canal_habilitado(conn)` (gating por config), `destinatario_permitido(to)` (allowlist en no-prod).
- `estado.py::diagnosticar(conn)`: readiness en el shape `{chequeos:[{check,ok,bloqueante,mensaje}], listo}` (molde `facturacion.diagnostico.diagnosticar_emisor`) para el back-office.
- `plantillas.py::REGISTRO`: **fuente única** de qué templates existen, su nombre en Meta, idioma, el mapeo ctx→params y el copy sugerido para dar de alta.
- `envio.py::enviar_evento_pedido(plantilla_key, pedido, ctx)`: la boca de envío.

## Credencial y gating: ENV, no DB

**Decisión de diseño** (pendiente de registrar en `MEMORIA.md` con OK del dueño): el token y el
`phone_number_id` viven en **variables de entorno** (`WHATSAPP_ACCESS_TOKEN`,
`WHATSAPP_PHONE_NUMBER_ID`), NO cifrados en la DB como los certs ARCA. Razón: WhatsApp es **una
sola cuenta de plataforma** (marca Rambla única — no multi-emisor) y **no tiene host de
homologación** como ARCA (es el mismo Graph, envíos reales). Si el token viviera en `app_settings`,
staging —que corre con una **BD clonada de prod**— heredaría el token de prod y podría mensajear a
clientes reales. En ENV cada ambiente de Railway tiene el suyo (o ninguno) → staging es seguro por
construcción. Mismo patrón que `RESEND_API_KEY`/`DIDIT_API_KEY` (secretos de terceros = ENV; ARCA es
la excepción por ser multi-emisor con certs subidos por UI).

**Gating (defensa en profundidad), en `envio.py` + `config.py`:**
1. **credencial presente** (`resolver_creds()`): sin token/número → canal inerte.
2. **canal prendido** (`canal_habilitado`): env `WHATSAPP_ENABLED` > app_settings `whatsapp_enabled` > **default OFF**.
3. **opt-in del cliente** (`clientes.whatsapp_opt_in`): Meta exige consentimiento demostrable; default FALSE.
4. **teléfono E.164** (`_resolver_telefono`): vía `identity.contacts.telefono_contacto` (verificado E.164 > crudo), pasado por el **embudo único** `services/telefono` (libphonenumber, región AR) que valida y normaliza a E.164; un número inválido → no se envía.
5. **destinatario permitido** (`destinatario_permitido`): en prod cualquiera; **fuera de prod solo la allowlist** `WHATSAPP_TEST_RECIPIENTS` (red anti-spam, espeja el número de test de Meta).

## Contrato de la boca de envío (`enviar_evento_pedido`)

Mismo contrato que `services.email.send_email`:
- **Nunca propaga**: cada gate no cumplido devuelve `{ok:True, skipped:True, reason}`; un fallo del provider se loguea `status='failed'` sin tumbar al caller.
- **Loguea siempre** en `whatsapp_log` (`to_phone`, `template_key`, `alquiler_id`, `status`, `wamid`, `error`). Sin `cliente_id` (espeja `emails_log`; keyea por `alquiler_id`, que sobrevive un merge de cuentas — así no suma una FK a `clientes` que clasificar en `identity/merge`).
- **Idempotente por pedido**: el índice único parcial `idx_whatsapp_log_idempotente (alquiler_id, template_key) WHERE status='sent'` garantiza un solo envío 'sent' por pedido+template. Clave: el gate de los jobs del scheduler es una **variable en memoria que se resetea en cada restart** (causó el spam del mail de reconciliación) — la idempotencia real la da el índice, no la var.

## Eventos y enganche (dónde se dispara)

El WhatsApp NO se dispara directo: se dispara como **plan A** de la capa única de
comunicación (`services/comunicacion/` — ver [`SISTEMA_COMUNICACION.md`](SISTEMA_COMUNICACION.md)).
El registro `comunicacion/eventos.py` declara, por evento, su template de mail + su template de
WhatsApp + la **estrategia** (plan A/B); `comunicacion.notificar_pedido(evento, pedido, ctx)` la
resuelve. Los eventos que hoy salen por WhatsApp:

| Evento | Template WhatsApp (`plantillas.REGISTRO`) | Estrategia | Disparador |
| --- | --- | --- | --- |
| Pedido creado | `pedido_creado` | WhatsApp plan A / mail plan B (+ mail al admin siempre) | `routes/alquileres/core.py` + `routes/estudio.py` → `notificar_pedido` |
| Pedido confirmado | `pedido_confirmado` | WhatsApp + mail con `.ics` (ambos) | `routes/alquileres/pedidos.py` → `notificar_pedido` |
| Recordatorio de retiro (D-1) | `recordatorio_retiro` | WhatsApp plan A / mail plan B | `jobs/recordatorios.py` → `notificar_pedido` |
| Recordatorio de devolución D-1/D-0/vencido | `recordatorio_devolucion_{d1,d0,vencido}` | solo whatsapp | `jobs/recordatorios_devolucion.py` — 3 ventanas prendibles por separado (`jobs/recordatorios_devolucion_config.py`) |

El scheduler in-process (`jobs/scheduler.py`) corre los dos barridos diarios (retiro + devolución),
cada uno con su gate de hora y su var de dedup; la idempotencia final la da `whatsapp_log`.

## Templates a dar de alta en Meta

`plantillas.REGISTRO` es la lista a pre-aprobar en el WhatsApp Manager, **categoría utility** (la más
barata; no marketing). El `meta_name` debe coincidir EXACTO con el aprobado, el `lang` con el idioma
elegido (default `es_AR`), y cada `{{n}}` del copy con `campos_ctx` en orden. `GET /admin/whatsapp/estado`
devuelve el registro con el copy sugerido para copiar-pegar.

## Superficie HTTP admin (`routes/whatsapp.py`)

- `GET /api/admin/whatsapp/estado` — readiness + los templates a dar de alta.
- `POST /api/admin/whatsapp/test` — envía un template a un número (E.164) para validar el pipeline con el número de test de Meta (respeta la allowlist de no-prod; no persiste en `whatsapp_log`).
- `POST /api/admin/whatsapp/recordatorios-devolucion/run` — barrido de devolución on-demand (`dry_run=True` por default: preview seguro).

## Setup (trámite Meta, fuera de código)

1. Crear/vincular la **WhatsApp Business Account (WABA)** en Meta Business Manager (requiere verificación del negocio).
2. **Display name** aprobado (ej. "Rambla Rental").
3. **Número** registrado como sender (el de click-to-chat o uno nuevo; si se migra el que ya se usa, planificar la migración).
4. **Token** (recomendado System User permanente → no expira, no hace falta caché de renovación). Setear en Railway: `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` (+ opcional `WHATSAPP_BUSINESS_ACCOUNT_ID`). En staging/local, dejar vacío o usar el número de test + `WHATSAPP_TEST_RECIPIENTS`.
5. Dar de alta los **templates utility** de `REGISTRO` y esperar su aprobación.
6. Prender el canal: `whatsapp_enabled` en `/admin/settings` (o env `WHATSAPP_ENABLED`).

## Testing

- `whatsapp_cloud/tests/` (portabilidad + mapeo de respuesta, sin red).
- `tests/test_whatsapp_adapter.py` (gating, skips, happy path, mapeo de templates).
- `tests/test_comunicacion.py` (plan A/B: fallback, ambos, solo_mail, solo_whatsapp; mail al admin siempre; una sola tarea en background).
- `tests/test_recordatorios_devolucion.py` (config de ventanas + job).
- La migración `w1h2a3t4s5a6` (whatsapp_log + opt-in) se ejercita en `test_alembic_upgrade_db.py`.

## Embudo de teléfono (`services/telefono.py`)

Puerta única de validación/formateo a E.164 (libphonenumber, región AR), por la que
pasa TODO número: al **guardar** (`formatear_para_guardar`: E.164 si es válido, si no el
crudo — no bloquea) en registro/perfil (`cliente_portal/cuenta.py`) y alta admin
(`clientes.py`); al **re-chequear** el `full_number` que trae Didit (`services/didit/
decision.py` — no-op si ya está bien); y al **enviar** (`normalizar_e164` estricto en
`whatsapp/envio.py`: inválido → no se manda). Así el número se asegura una sola forma,
no dependemos de que cada fuente lo mande formateado. (El **rechazo duro** —bloquear un
alta con teléfono inválido— es una decisión de UX aparte; hoy el guardado es lenient.)

## Pendiente (fuera del scaffold, a propósito)

- **Captura de opt-in en el front** (portal/checkout): la columna `clientes.whatsapp_opt_in` existe; falta el punto de captura y su UI.
- **Recepción de mensajes / webhooks de estado de entrega**: fuera de alcance (esto es solo saliente).
