# Sistema: WhatsApp — notificaciones salientes por Meta Cloud API

> Manual técnico (fuente única del **cómo funciona**). Las reglas de criterio y el
> _porqué_ viven en `MEMORIA.md`/`DECISIONES.md` y se **linkean**, no se copian.
> Índice maestro en `MANIFIESTO.md` §8.
>
> **Estado:** canal completo (saliente + entrante) construido; falta la
> configuración de Meta del dueño (token real, número, plantillas aprobadas).

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
| **Adapter Rambla** | `backend/services/whatsapp/` | Todo el I/O y las decisiones: credenciales/gating (`config.py`), readiness (`estado.py`), registro de templates (`plantillas.py`), la **boca de envío** fail-safe + idempotente (`envio.py`) y el **webhook entrante** (`webhook.py`: firma + estado de entrega + auto-reply). |

### Librería `whatsapp_cloud/`
- `client.py::WhatsAppClient.enviar_template(to, template_name, lang_code, body_params)` / `enviar_texto(to, body)` → `POST {base}/{phone_number_id}/messages` (con `template` o `type=text`). Mapea la respuesta de Meta a `EnvioResult(wamid)` o a la taxonomía tipada. `enviar_texto` es texto LIBRE — solo lo usa el auto-reply del webhook, nunca para iniciar contacto (eso son los templates).
- `errores.py`: `WhatsAppError` base + `WhatsAppAuthError` / `WhatsAppRateLimitError` / `WhatsAppNetworkError` / `WhatsAppRequestError` (Meta rechazó por número/template) / `WhatsAppResponseError` (respuesta inesperada). El **tipo decide** reintentar/avisar (espejo de `arca_fe.errores`). Los códigos de credencial de Meta (190, etc.) mandan sobre el HTTP status.
- `retry.py::with_retry`: opt-in, reintenta solo network + rate-limit (respeta `Retry-After`).
- `__version__` arranca en `"0.0.0"` (misma política que `arca_fe`: bumpea al primer envío real en prod).

### Adapter `services/whatsapp/`
- `config.py`: `resolver_creds()` (de ENV), `canal_habilitado(conn)` (gating por config), `destinatario_permitido(to)` (allowlist en no-prod).
- `estado.py::diagnosticar(conn)`: readiness en el shape `{chequeos:[{check,ok,bloqueante,mensaje}], listo}` (molde `facturacion.diagnostico.diagnosticar_emisor`) para el back-office.
- `plantillas.py::REGISTRO`: **fuente única** de qué templates existen, su nombre en Meta, idioma, el mapeo ctx→params y el copy sugerido para dar de alta.
- `envio.py::enviar_evento_pedido(plantilla_key, pedido, ctx)`: la boca de envío. Si el template pide `whatsapp_contacto` (el WhatsApp real, para invitar a escribir sin decir "respondé este mensaje"), lo agrega acá sobre una copia del ctx — `pedido_email_context` es una función PURA a propósito (unit-testeada sin Postgres) y no abre conexión.
- `webhook.py`: firma HMAC (`verify_signature`) + handshake de verificación (`verify_challenge`) + `procesar_evento(payload, conn)` — ver sección propia abajo.

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
resuelve. La columna "Estrategia" de abajo es el **default de fábrica**: el dueño puede cambiar
por dónde sale cada evento desde `/admin/comunicacion` (ver `SISTEMA_COMUNICACION.md`). Los
eventos con canal WhatsApp:

| Evento | Template WhatsApp (`plantillas.REGISTRO`) | Estrategia | Disparador |
| --- | --- | --- | --- |
| Pedido creado | `pedido_creado` | WhatsApp plan A / mail plan B (+ mail al admin siempre) | `routes/alquileres/core.py` + `routes/estudio.py` → `notificar_pedido` |
| Pedido confirmado | `pedido_confirmado` | WhatsApp + mail con `.ics` (ambos) | `routes/alquileres/pedidos.py` → `notificar_pedido` |
| Recordatorio de retiro | `recordatorio_retiro` | WhatsApp plan A / mail plan B (default) | `jobs/recordatorios.py` — 2 pasadas por día: el mismo día a la mañana, o la víspera a la hora de cierre si el retiro es temprano (`jobs/recordatorios_config.py`) |
| Recordatorio de devolución D-1/D-0/vencido | `recordatorio_devolucion_{d1,d0,vencido}` | solo whatsapp (default) | `jobs/recordatorios_devolucion.py` — 3 ventanas prendibles por separado (`jobs/recordatorios_devolucion_config.py`) |

El scheduler in-process (`jobs/scheduler.py`) corre los dos barridos diarios (retiro + devolución),
cada uno con su gate de hora y su var de dedup; ninguno de los dos re-lista un pedido ya
alcanzado por CUALQUIER canal (`whatsapp_log` **o** `emails_log`).

## Templates a dar de alta en Meta

`plantillas.REGISTRO` es la lista a pre-aprobar en el WhatsApp Manager, **categoría utility** (la más
barata; no marketing). El `meta_name` debe coincidir EXACTO con el aprobado, el `lang` con el idioma
elegido (default `es_AR`), y cada `{{n}}` del copy con `campos_ctx` en orden. `GET /admin/whatsapp/estado`
devuelve el registro con el copy sugerido para copiar-pegar.

## Superficie HTTP admin (`routes/whatsapp.py`)

- `GET /api/admin/whatsapp/estado` — readiness + los templates a dar de alta.
- `POST /api/admin/whatsapp/test` — envía un template a un número (E.164) para validar el pipeline con el número de test de Meta (respeta la allowlist de no-prod; no persiste en `whatsapp_log`).
- `POST /api/admin/whatsapp/recordatorios-devolucion/run` — barrido de devolución on-demand (`dry_run=True` por default: preview seguro).

## Webhook entrante (`GET`/`POST /api/webhooks/whatsapp`)

Sin coexistencia ni bandeja, una respuesta del cliente al número de avisos se perdía en el
aire (ni siquiera un error). El webhook resuelve dos cosas — mismo criterio anti-vanish que
motivó el copy con `whatsapp_contacto` (arriba):

1. **Estado de entrega real** (`statuses[]`): hasta ahora `whatsapp_log.status='sent'` solo
   decía que Meta ACEPTÓ el envío, no que llegó. El webhook completa `delivery_status`
   (`delivered`/`read`/`failed`) + `delivery_error` + `delivered_at` — columnas NUEVAS,
   nullable (migración `w3bh00k1nb0x`). **`status` no se toca**: esa columna sostiene el
   índice único de idempotencia (`idx_whatsapp_log_idempotente`, `WHERE status='sent'`) —
   pisarla con el estado de entrega la sacaría del índice y reabriría la puerta a un
   duplicado. El cruce es por `wamid`.
2. **Mensajes entrantes** (`messages[]`): a cada uno le contesta un texto LIBRE
   (`WhatsAppClient.enviar_texto`, válido dentro de la ventana de servicio de 24h que el
   propio mensaje abre) redirigiendo al WhatsApp real del negocio
   (`comunicacion.contacto.telefono_negocio`) — best-effort, un fallo de envío queda
   logueado sin romper el webhook. Si el texto pide **baja**
   (`webhook.es_mensaje_de_baja`: "baja"/"stop"/"cancelar"/"no me escriban"/"no molest*",
   sin distinguir mayúsculas/acentos salvo el caso puntual "baja" vs "bajá" — ver el
   comentario en el código), y el teléfono resuelve a un cliente conocido
   (`_resolver_cliente_por_telefono`: `verified_contacts` primero, `clientes.telefono` de
   fallback), se apaga `whatsapp_opt_in` de ESE cliente y se confirma con un copy distinto
   ("no te vamos a volver a escribir"). Best-effort por diseño: no cubre cualquier frase en
   lenguaje natural, y si el teléfono no resuelve a un cliente conocido, cae al redirect
   genérico (no hay a quién apagarle el opt-in).

**Tope de tamaño del body** (`_MAX_WEBHOOK_BODY` en `routes/whatsapp.py`, 256 KB): el
endpoint es público (sin sesión) — antes de verificar la firma se corta un `Content-Length`
declarado por encima del tope, y tras leer el body se vuelve a chequear (por si el header
mentía o faltaba, ej. chunked transfer). Evita que cualquiera, sin firma válida, fuerce al
server a bufferear/hashear un payload desproporcionado. Los payloads reales de Meta son de
unos pocos KB.

**Auth: HMAC, no sesión** (lo llama Meta server-to-server) — mismo criterio que
`services/didit/webhook.py`, adaptado al esquema de Meta:

- `GET` — el handshake que Meta hace UNA vez al guardar el Callback URL
  (`hub.mode=subscribe`, `hub.verify_token`, `hub.challenge`): si el token coincide con
  `WHATSAPP_WEBHOOK_VERIFY_TOKEN` (un string que vos elegís y pegás en los dos lados),
  devuelve `hub.challenge` tal cual.
- `POST` — firma `X-Hub-Signature-256: sha256=<hex>` sobre el body crudo, con
  `WHATSAPP_APP_SECRET` (el **App Secret** de Meta → tu app → Settings → Basic —
  **DISTINTO** del access token: ese autoriza a enviar, este verifica que un evento
  entrante lo mandó Meta). Fail-closed: sin el secret configurado, rechaza todo.

Ambas rutas están exentas del middleware de sesión por el prefijo `/api/webhooks/`
(`middleware.PUBLIC_API_ANY`, ya usado por Didit). El chequeo `webhook_configurado` de
`diagnosticar()` es **no bloqueante** (se puede seguir mandando sin esto) y muestra la
Callback URL exacta a pegar en Meta.

## Setup (trámite Meta, fuera de código)

1. Crear/vincular la **WhatsApp Business Account (WABA)** en Meta Business Manager (requiere verificación del negocio).
2. **Display name** aprobado (ej. "Rambla Rental").
3. **Número** registrado como sender (el de click-to-chat o uno nuevo; si se migra el que ya se usa, planificar la migración).
4. **Token** (recomendado System User permanente → no expira, no hace falta caché de renovación). Setear en Railway: `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` (+ opcional `WHATSAPP_BUSINESS_ACCOUNT_ID`). En staging/local, dejar vacío o usar el número de test + `WHATSAPP_TEST_RECIPIENTS`.
5. Dar de alta los **templates utility** de `REGISTRO` y esperar su aprobación (botón "Crear las que falten" en `/admin/comunicacion`, o a mano en el WhatsApp Manager con el copy sugerido).
6. Prender el canal: interruptor en la tarjeta de WhatsApp de `/admin/comunicacion` (o env `WHATSAPP_ENABLED`).
7. **Webhook** (opcional pero recomendado — sin esto no hay estado de entrega ni respuesta a mensajes entrantes): en Meta → tu app → WhatsApp → Configuration, Callback URL = `{SITE_URL}/api/webhooks/whatsapp`, Verify token = cualquier string que elijas. Setear en Railway ESE MISMO string en `WHATSAPP_WEBHOOK_VERIFY_TOKEN`, más `WHATSAPP_APP_SECRET` (Settings → Basic → App Secret, **no** el access token).

## Testing

- `whatsapp_cloud/tests/` (portabilidad + mapeo de respuesta, sin red).
- `tests/test_whatsapp_adapter.py` (gating, skips, happy path, mapeo de templates).
- `tests/test_comunicacion.py` (plan A/B: fallback, ambos, solo_mail, solo_whatsapp; mail al admin siempre; una sola tarea en background).
- `tests/test_recordatorios_devolucion.py` (config de ventanas + job).
- La migración `w1h2a3t4s5a6` (whatsapp_log + opt-in) y `w3bh00k1nb0x` (columnas de estado de entrega) se ejercitan en `test_alembic_upgrade_db.py`.
- `tests/test_whatsapp_webhook.py` (firma HMAC fail-closed, handshake de verificación, aplicar estados de entrega sin tocar `status`, auto-reply a mensajes entrantes, detección de baja + apagado de `whatsapp_opt_in`, `procesar_evento` nunca propaga).
- `tests/test_whatsapp_webhook_route.py` (HTTP real vía `TestClient`: tope de tamaño del body antes de la firma).
- `whatsapp_cloud/tests/test_client.py` cubre `enviar_texto` (mensaje libre, sin `template` en el payload).

## Embudo de teléfono (`services/telefono.py`)

Puerta única de validación/formateo a E.164 (libphonenumber, región AR), por la que
pasa TODO número: al **guardar** (`formatear_para_guardar`: E.164 si es válido, si no el
crudo — no bloquea) en registro/perfil (`cliente_portal/cuenta.py`) y alta admin
(`clientes.py`); al **re-chequear** el `full_number` que trae Didit (`services/didit/
decision.py` — no-op si ya está bien); y al **enviar** (`normalizar_e164` estricto en
`whatsapp/envio.py`: inválido → no se manda). Así el número se asegura una sola forma,
no dependemos de que cada fuente lo mande formateado. (El **rechazo duro** —bloquear un
alta con teléfono inválido— es una decisión de UX aparte; hoy el guardado es lenient.)

## Pendiente

- Nada del lado del código: falta la **configuración de Meta** del dueño (token real
  permanente, número, plantillas aprobadas, webhook). Ver "Setup" arriba.
