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

El **mail al admin** (`CanalMail.template_admin`) es **independiente** del plan A/B del
cliente: si el evento lo declara, sale **siempre** por mail (el admin se entera del pedido
pase lo que pase con el canal del cliente).

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
| `services/comunicacion/despacho.py` | `notificar_pedido(evento, pedido, ctx=None, *, background)`: lee el registro y resuelve el envío según la estrategia (`_despachar_cliente` = plan A/B; el admin siempre por mail). Arma el contexto (`pedido_email_context`, si no se pasa `ctx`) y el `.ics` (`ics_adjunto_pedido`). Reusa los senders de cada canal — no reimplementa el envío. Devuelve `{"mail": [...], "whatsapp": ...}`. |

Todos los consumidores llaman `notificar_pedido` / importan `pedido_email_context`/
`ics_adjunto_pedido` **directo de `comunicacion`** (routes de alquileres/estudio, documentos,
jobs de recordatorios) — no hay capa de compatibilidad intermedia.

## Canales (senders que el despachador reusa)

- **Mail** → `services/email.send_email` (templates HTML en la DB `email_templates`, editables en `/admin/email-templates`). Ver el propio `services/email`.
- **WhatsApp** → `services/whatsapp.enviar_evento_pedido` (templates pre-aprobados por Meta). Ver [`SISTEMA_WHATSAPP.md`](SISTEMA_WHATSAPP.md).

**No es "un template para los dos canales"**: cada medio tiene el suyo por diseño (el mail es HTML
nuestro; el WhatsApp es un template rígido pre-aprobado por Meta). Lo que el registro unifica es el
**evento** — el mismo disparador y contexto eligen, por canal, su template, y qué medios salen.

## Cómo se agrega un evento nuevo

1. Dar de alta el/los template(s): mail en `email_templates` (o migración), WhatsApp en Meta +
   `services/whatsapp/plantillas.py`.
2. Sumar la entrada al `REGISTRO` de `comunicacion/eventos.py` (templates por canal + `estrategia`).
3. Disparar con `comunicacion.notificar_pedido("<evento>", pedido, ctx, background=...)`.

El plan A/B, el gating por canal (WhatsApp gateado por credencial/opt-in/E.164), la
idempotencia y el fail-safe salen gratis de los senders y de la estrategia declarada.

## Tests

`tests/test_comunicacion.py` (registro consistente + fan-out por evento/canal/override; `ctx`
opcional). El armado de contexto/`.ics` lo cubren `tests/test_pedido_email_context.py` y
`tests/test_ics_adjunto.py`.
