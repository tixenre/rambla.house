# Sistema: Comunicación — la capa única multi-canal (mail + WhatsApp)

> Manual técnico (fuente única del **cómo funciona**). Las reglas de criterio y el
> _porqué_ viven en `MEMORIA.md`/`DECISIONES.md` y se **linkean**, no se copian.
> Índice maestro en `MANIFIESTO.md` §8.

## Qué resuelve

Un **único lugar** para "qué le comunicamos al cliente y por qué medio". Materializa
_2026-05-27 — Notificaciones canal-agnósticas a un punto único_. Antes cada evento nombraba a
mano su template de mail y su template de WhatsApp, desparramado por routes y jobs; ahora hay
**un registro** de eventos de comunicación + **un despachador** que resuelve el envío por canal.

## Plan A/B: WhatsApp primero, mail de respaldo (no los dos)

Decisión del dueño (_2026-07-12_): **WhatsApp es plan A, el mail es plan B**. Para un evento
al cliente NO se manda por los dos canales a la vez — se prefiere WhatsApp y, si no llegó
(sin opt-in / sin E.164 / canal apagado / falló), recién ahí se cae al mail. Cada evento
declara su **estrategia** de cómo alcanzar al cliente:

| Estrategia | Qué hace | Eventos hoy |
| --- | --- | --- |
| `FALLBACK` | WhatsApp plan A → mail plan B (uno u otro). | `pedido_creado`, `recordatorio_retiro` |
| `AMBOS` | WhatsApp **y** mail. La confirmación: el WhatsApp confirma y el **mail lleva el `.ics`** (WhatsApp no adjunta calendario). | `pedido_confirmado` |
| `SOLO_MAIL` | Solo mail. Comunicaciones **formales** (contrato / documentos) van siempre por mail. | _(disponible; sin evento cableado aún)_ |
| `SOLO_WHATSAPP` | Solo WhatsApp. | `recordatorio_devolucion_{d1,d0,vencido}` |

Los 6 eventos tienen hoy plantilla en los dos canales (los 3 de devolución nacieron
canal-WhatsApp —ese sigue siendo su default— pero tienen su mail para que la elección sea real),
así que cualquiera de las cuatro formas es elegible en cualquiera de ellos.

El **mail al admin** (`CanalMail.template_admin`) es **independiente** del plan A/B del
cliente: si el evento lo declara, sale **siempre** por mail (el admin se entera del pedido
pase lo que pase con el canal del cliente).

### Lo que declara el registro es el DEFAULT — el dueño puede cambiarlo

La estrategia del `REGISTRO` es **el default de fábrica**, no un valor fijo: desde
`/admin/comunicacion` el dueño elige, por evento, si sale por WhatsApp, por mail o por los dos
(`services/comunicacion/estrategia.py`, setting `comunicacion_estrategia_<evento>`). Dos reglas
lo hacen seguro:

- **Solo se puede elegir un canal que el evento tenga cableado** (`posibles()`): un evento sin
  plantilla de mail no puede quedar en "solo mail". Lo valida el endpoint al guardar **y** la
  resolución al leer (una fila vieja o corrupta cae al default).
- **Fail-open**: si la BD no contesta o el valor no sirve, se despacha como declara el código.
  Un problema de configuración nunca deja al cliente sin aviso.

El despacho cachea la elección en proceso con TTL corto (evita una query por notificación); al
guardar, el endpoint invalida el cache — con varios workers, los demás convergen en segundos.

**Cómo se decide el fallback (y por qué en background):** el despacho corre el sender de
WhatsApp **síncrono** y mira su resultado (`wamid` = enviado; `skipped/duplicado` = ya había
salido antes → también cuenta como llegado; cualquier otro skip/fallo → cae a mail). Para no
bloquear el request, en modo `background` se encola **una sola tarea** que corre todo el plan
A/B adentro — así la decisión usa el resultado real del WhatsApp en vez de encolar dos envíos
a ciegas.

## Forma: facade + registro (NO CQRS-lite)

`services/comunicacion/` es un **facade + registro** (molde `services/finanzas_flujo/`), **no**
CQRS-lite (`queries/`+`commands/`, como `contabilidad/`). Razón: comunicación es **orquestación**
(leo config + opt-in → fan-out) + **logs append-only** (`emails_log`/`whatsapp_log`, que ya viven
dentro de cada sender), no una superficie de mutación de dominio con invariantes que justifique el
split. Si algún día suma **preferencias por cliente** (CRUD de opt-in/out por canal) **+ una cola de
mensajes con estados** (encolado→enviado→entregado→falló), ahí aparecería un `commands/` real — no
antes (empirismo proporcional, _2026-06-27_).

## Piezas

| Módulo | Rol |
| --- | --- |
| `services/comunicacion/eventos.py` | **Registro fuente única**: `REGISTRO[evento]` = `EventoComunicacion(estrategia=..., mail=CanalMail(...), whatsapp="<template>")`. Un evento declara su template **por canal** + la **estrategia** (plan A/B) con la que se alcanza al cliente. |
| `services/comunicacion/estrategia.py` | **Por dónde sale HOY cada evento**: `efectiva(ev)` = lo que eligió el dueño (setting `comunicacion_estrategia_<evento>`) o, si no eligió / no sirve / la BD no contesta, el default del registro. `posibles(ev)` acota la elección a los canales que ese evento tiene cableados. |
| `services/comunicacion/opciones.py` | **Qué se puede configurar de cada evento** (horario del barrido, antelación, números del equipo): declara las perillas de cada evento apuntando a keys de `app_settings` **ya permitidas**. No redeclara keys/env/defaults — los importa de `jobs/recordatorios_config.py` y `jobs/recordatorios_devolucion_config.py`, que siguen siendo la fuente única de la resolución `env > settings > default`. Se guardan por el `PUT /api/admin/settings/{key}` de siempre. |
| `services/comunicacion/despacho.py` | `notificar_pedido(evento, pedido, ctx=None, *, background)`: lee el registro y resuelve el envío según la estrategia (`_despachar_cliente` = plan A/B; el admin siempre por mail). Arma el contexto (`pedido_email_context`, si no se pasa `ctx`) y el `.ics` (`ics_adjunto_pedido`). Reusa los senders de cada canal — no reimplementa el envío. Devuelve `{"mail": [...], "whatsapp": ...}`. |

Todos los consumidores llaman `notificar_pedido` / importan `pedido_email_context`/
`ics_adjunto_pedido` **directo de `comunicacion`** (routes de alquileres/estudio, documentos,
jobs de recordatorios) — no hay capa de compatibilidad intermedia.

## Canales (senders que el despachador reusa)

- **Mail** → `services/email.send_email` (templates HTML en la DB `email_templates`, editables en `/admin/comunicacion`). Ver el propio `services/email`.
- **WhatsApp** → `services/whatsapp.enviar_evento_pedido` (templates pre-aprobados por Meta). El canal no tiene bandeja: los templates que invitan a escribir usan `whatsapp_contacto` (el WhatsApp real del negocio) en vez de "respondé este mensaje", y un webhook auto-responde a quien igual le escribe al número de avisos. Ver [`SISTEMA_WHATSAPP.md`](SISTEMA_WHATSAPP.md).

**No es "un template para los dos canales"**: cada medio tiene el suyo por diseño (el mail es HTML
nuestro; el WhatsApp es un template rígido pre-aprobado por Meta). Lo que el registro unifica es el
**evento** — el mismo disparador y contexto eligen, por canal, su template, y qué medios salen.

## El back-office: `/admin/comunicacion`

Una pantalla, **una tarjeta por evento**, y adentro de cada evento **todo lo que hace falta para
comunicarlo**: el texto que sale por cada canal (la plantilla de WhatsApp con su estado de
aprobación en Meta + la de mail, con su on/off y su editor), a quién le llega (cliente / equipo)
y sus perillas (`opciones.py`: encendido, antelación, hora del barrido, números del equipo),
incluido el selector de **por dónde sale** (`estrategia.py`).
Criterio del dueño: **la configuración vive en el mensaje que corresponde** — antes el
recordatorio de retiro tenía su propia tarjeta en Settings, suelta de la comunicación que
gobierna, y las plantillas de mail vivían en otra lista aparte.

**Cuándo sale un aviso de barrido** también se configura ahí: el recordatorio de retiro no es
"N días antes" fijo — depende de la hora del retiro (mismo día a la mañana; la víspera a la hora
de cierre si el retiro es temprano). El criterio y sus perillas viven en
`jobs/recordatorios_config.py`; la hora de cierre sale de `horarios_retiro` vía
`services/fechas.ultima_hora_laboral` (no se re-declara). Los eventos que dispara un barrido
(retiro y devolución) traen además un botón para **simular** a quién le llegaría hoy, sin mandar.

Lo que queda **fuera** de un evento, porque es transversal: el estado de los dos canales
(remitente del mail, readiness de WhatsApp, alta de plantillas en Meta, envío de prueba), los
mails que dispara **Talleres** (no pasan por el registro — decir que son eventos sería mentir
sobre quién los manda) y el **registro de envíos**.

`GET /api/admin/comunicacion/eventos` (`routes/comunicacion.py`) arma todo eso: espeja el
`REGISTRO`, resuelve el asunto/on-off de cada template de mail (una query), pregunta a Meta el
estado de aprobación de cada plantilla y adjunta las opciones con su valor efectivo. Una opción
pisada por una **env var** viaja con `bloqueada_por_env` y la pantalla la muestra en solo-lectura
(si la dejara editar, el admin guardaría un valor que el ambiente ignora).

## Cómo se agrega un evento nuevo

1. Dar de alta el/los template(s): mail en `email_templates` (o migración), WhatsApp en Meta +
   `services/whatsapp/plantillas.py`.
2. Sumar la entrada al `REGISTRO` de `comunicacion/eventos.py` (`titulo` + templates por canal +
   `estrategia`). Si el evento tiene perillas (horario, antelación, destinatarios), declararlas en
   `comunicacion/opciones.py` — la pantalla las muestra adentro de su tarjeta sola.
3. Disparar con `comunicacion.notificar_pedido("<evento>", pedido, ctx, background=...)`.

El plan A/B, el gating por canal (WhatsApp gateado por credencial/opt-in/E.164), la
idempotencia y el fail-safe salen gratis de los senders y de la estrategia declarada.

## Tests

`tests/test_comunicacion.py` (registro consistente + plan A/B por evento/canal; `ctx` opcional),
`tests/test_comunicacion_routes.py` (el endpoint espeja el registro, cada evento trae sus opciones
y su plantilla, ningún mail queda sin lugar donde editarse) y
`tests/test_settings_comunicacion.py` (las settings que edita la pantalla se normalizan/validan en
el endpoint: switches a `"1"/"0"`, rangos de hora/antelación, números del equipo por el embudo
único `services/telefono`). El armado de contexto/`.ics` lo cubren
`tests/test_pedido_email_context.py` y `tests/test_ics_adjunto.py`.
