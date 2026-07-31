# Flujo de pedidos — Rambla Rental

> Manual del recorrido de un pedido: desde que el cliente lo solicita hasta que se cierra, qué ve en
> cada paso, qué mails se mandan y cómo está modelado. Pensado para entender el sistema sin leer
> código. El detalle técnico vive en el commit history; acá va el **qué** y el **por qué**.

## 1. Ciclo de vida del pedido

Un pedido pasa por estos estados (columna `estado` de la tabla `alquileres`):

| Estado | Qué significa | Para el cliente |
|---|---|---|
| `borrador` | Pedido a medio cargar (lo usa el admin) — sandbox sin compromiso de ningún tipo, ni con plata, ni con stock, ni con un cliente, ni con un mensaje. | No lo ve — ni siquiera si ya tiene un cliente real asignado mientras se prueba algo. |
| `solicitado` (ex-`presupuesto`) | **Solicitud enviada, a confirmar.** Es donde caen todos los pedidos del cliente al crearse — ya hay compromiso con un cliente, un monto, fechas y comunicación. | "Solicitado" |
| `confirmado` | El compromiso en sí: confirmamos disponibilidad y precio. Acá se habilitan los documentos (remito/contrato). | "Confirmado" |
| `retirado` | El cliente pasó por el local y se llevó el equipo. | "Retirado" |
| `devuelto` | Recibimos el equipo de vuelta y lo revisamos. | "Devuelto" |
| `finalizado` | Pedido cerrado (normalmente automático — ver abajo). | "Finalizado" |
| `cancelado` | El pedido se dio de baja (estado terminal, sin salida). | "Cancelado" |

Los estados que **reservan stock** (cuentan contra la disponibilidad) son `solicitado`,
`confirmado` y `retirado` — `borrador` queda afuera a propósito.

### Qué le corresponde a cada estado

Tabla de referencia — qué acciones/efectos están habilitados en cada estado, para no tener que
reconstruir el criterio cada vez que se agrega una acción nueva a la página del pedido:

| Estado | Reserva stock | Pago | Mail / WhatsApp | Portal cliente | Facturar | Eliminar pedido |
|---|---|---|---|---|---|---|
| `borrador` | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (descartable, sin riesgo) |
| `solicitado` | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| `confirmado` | ✅ | ✅ | ✅ | ✅ | ✅ | ❓ hoy sin gate — pendiente de decidir |
| `retirado` | ✅ | ✅ | ✅ | ✅ | ✅ | ❓ hoy sin gate — pendiente de decidir |
| `devuelto` | — | ✅ | ✅ | ✅ | ✅ | ❓ hoy sin gate — pendiente de decidir |
| `finalizado` | — | ✅ | ✅ | ✅ | ✅ | ❓ hoy sin gate — pendiente de decidir |
| `cancelado` | ❌ | ❌ | ❓ sin decidir | ✅ | ❌ | ✅ (terminal, sin riesgo) |

"Eliminar pedido" no tiene gate por estado ni por plata para un pedido normal — el único guard
existente (`monto_pagado > 0` bloquea el borrado) es explícitamente solo para turnos del Estudio
vinculados (`routes/alquileres/pedidos.py::_delete_pedido`). Queda documentado como pendiente de
decisión a propósito — no es una decisión chica (borrar algo con plata/stock real comprometido).

**Motor único de transición** (`backend/routes/alquileres/transiciones.py::cambiar_estado`,
sesión 2026-07-06): antes esta lógica estaba desparramada (el PATCH admin, el cancelar del
cliente, el auto-finalizar); ahora es una sola puerta con un grafo explícito
(`TRANSICIONES`). El admin puede moverse **libremente hacia adelante y hacia atrás** entre
los estados operativos (necesita poder corregir un pedido ya avanzado), con dos guards:

- **Volver a `borrador` está bloqueado** si el pedido ya tiene plata cobrada (`monto_pagado
  > 0`) o una factura activa — no puede retroceder a un estado que ni siquiera exige
  fechas/ítems una vez que hay algo real comprometido.
- **`finalizado` es "estilo Magento"**: normalmente se prende solo (`devuelto` + pagado
  completo) y se apaga solo si se anula el pago que lo completaba — pero sigue siendo un
  destino manual válido, un paso desde/hacia `devuelto`, para el caso real de un pedido
  `monto_total=0` (comp/cortesía) que nunca cumple esa condición y quedaría trabado en
  `devuelto` para siempre sin el botón "Finalizar" del admin.

`cancelado` es alcanzable desde cualquier estado *antes* de `retirado` (para admin y
cliente), pero no tiene salida definida. El cliente (portal) solo puede disparar la
transición a `cancelado` — cualquier otro destino es rechazado.

## 2. El flujo de confirmación visible (qué ve el cliente al solicitar)

Cuando el cliente solicita un **rental** (carrito) o reserva el **estudio**:

1. Se crea el pedido en estado `solicitado`.
2. Se **vacía el carrito** / se cierra el form, y aparece un **toast** con el número de pedido
   ("Pedido #1023 enviado").
3. Se **redirige al portal del cliente** (`/cliente/portal?nuevo=<id>`), donde la card del pedido
   nuevo queda **expandida, scrolleada y resaltada** unos segundos, con un banner de bienvenida y la
   **línea de tiempo** del estado.

La idea es que el cliente sienta que "algo pasó" y sepa dónde seguir el estado — antes el feedback
era un panel pobre sin número ni próximos pasos.

El portal lee `?nuevo=<id>` una sola vez (después limpia la URL para que un refresh no lo vuelva a
disparar). Carrito y estudio comparten exactamente el mismo flujo.

## 3. Notificaciones (mails)

### Estado actual: **construido pero NO activado**

La infraestructura de mails está **completa y cableada** (`backend/services/email/`): plantillas
editables desde `/admin/email-templates`, render con Jinja2, backends Resend/SMTP, y log de envíos
en la tabla `emails_log`. **No envía nada todavía** porque no hay proveedor configurado: cae al
backend `test` (que loguea pero no manda).

**Para activarla** (es config/ops, no código): setear en producción las env vars
`RESEND_API_KEY` (o `SMTP_*`) + `EMAIL_PROVIDER` + `EMAIL_FROM` + `EMAIL_ADMIN_TO` (admite varios
destinatarios para el equipo).

### Qué mail se dispara en cada evento

| Evento | Mail(s) | Contenido |
|---|---|---|
| **Pedido creado** | `pedido_creado_cliente` (al cliente) + `pedido_creado_admin` (al equipo) | Cliente: resumen (fechas/total/items), número de pedido y **link al portal** para seguir el estado, con la aclaración de que el remito y el contrato se van a poder descargar desde ahí **cuando confirmemos**. Equipo: "entró un pedido #N de \<cliente\>" + link al back-office. |
| **Pedido confirmado** | `pedido_confirmado_cliente` (al cliente) | Confirma el pedido y avisa que **ya puede descargar el remito y el contrato** desde su portal. |
| **Recordatorio retiro** | `recordatorio_retiro` (al cliente) | Recordatorio D-1 del retiro. |

### Regla de documentos

El **remito** y el **contrato** **no existen mientras el pedido está en `solicitado`** — recién se
habilitan desde `confirmado` en adelante. Por eso el mail de creación **no promete descargas**
("vas a poder descargarlos cuando confirmemos"), y es el mail de confirmación el que dice "ya están
listos". La lógica de qué documentos están disponibles vive en
`backend/routes/cliente_portal.py` (`_documentos_disponibles`).

### WhatsApp (follow-up, todavía no)

Las notificaciones se piensan **canal-agnósticas**: hoy el canal es mail, y WhatsApp es un
follow-up que se enchufaría al mismo punto de despacho
(`_dispatch_pedido_creado_emails` en `alquileres.py`, generalizándolo a un notificador multi-canal).
Requiere un proveedor (Meta Cloud API / Twilio), verificación del negocio, plantillas pre-aprobadas y
tiene costo por mensaje → es una iniciativa aparte.

## 4. `id` vs `numero_pedido` — no es un sistema duplicado

Un pedido tiene **dos identificadores con roles distintos** (patrón estándar, como el "id interno" +
"#1001" de cualquier e-commerce):

- **`id`** — clave primaria interna de la tabla `alquileres` (`SERIAL`). Existe siempre. Se usa para
  lo técnico: URLs (`/admin/pedidos/{id}`), joins, claves foráneas (`alquiler_items.pedido_id`), y
  para saber qué card abrir/resaltar en el portal (`?nuevo=<id>`).
- **`numero_pedido`** — el número "comercial" que ve el humano. Sale de **otra secuencia**
  (`numero_pedido_seq`), no del `id`. Es el que se muestra al cliente y sirve para buscar/referir un
  pedido. Se asigna **en la creación** (`_next_numero_pedido`), en los tres caminos: carrito, admin y
  estudio.

**Por qué dos y no uno:** el `id` incrementa por *cada fila* (incluidos borradores, tests, pedidos
borrados), así que no es una serie limpia para mostrarle al cliente. El `numero_pedido` tiene su
propia secuencia.

**Por qué "se ven dos números distintos" para el mismo pedido:** justamente porque vienen de
secuencias distintas — un pedido puede ser `id=47` y `numero_pedido=1023`. No es duplicación ni un
bug: es el identificador interno vs el comercial.

`numero_pedido` es `NULL`-able en el esquema y el código cae a mostrar el `id` cuando falta
(`numero_pedido or id`). Eso es solo una red de seguridad para filas viejas/legacy; los pedidos
nuevos siempre reciben su `numero_pedido` al crearse.

## 5. Familias de pedido — mismo modelo, 4 significados de fecha (Fase 1, #1308)

Un pedido vive siempre en la misma tabla `alquileres`, pero la columna `tipo` separa **4 familias**
con semántica de fecha distinta. Fuente única del predicado: `backend/tipos_pedido.py`
(`TIPOS_DERIVADOS`, `TIPOS_SIN_RETIRO`, `es_pedido_derivado()` / `es_pedido_taller()` + su espejo TS
`frontend/src/lib/tipos-pedido.ts`) — ningún consumidor nuevo debería reimplementar la lista de tipos
inline (guard: `test_tipos_pedido_source_scan.py`).

| `tipo` | Qué son `fecha_desde`/`fecha_hasta` | Se edita desde | Motor |
|---|---|---|---|
| `diaria` | Rango real de jornadas del alquiler (el caso rental clásico). | La página del pedido, libremente. | — |
| `estudio` | Franja horaria real de un turno (mismo día, hora de inicio/fin dentro del rango). | La agenda del Estudio (franja + tarifa + ítems); el pedido muestra pero no re-edita la franja. | `backend/services/estudio/` |
| `estudio_fijo` | Una muestra de una recurrencia semanal (el slot gobierna, el pedido es un reflejo). | El slot fijo, no el pedido. | `backend/services/estudio/` |
| `taller` | **Mes calendario contable** de la edición — NO un evento puntual (la verdad temporal real vive en `clases_taller`, con fecha + franja de cada clase). | La edición del taller (economía); el pedido solo admite **agregar** líneas manuales (ej. una matrícula) — no puede editar fechas ni borrar el ítem que generó la edición. | `backend/services/talleres/` |

**Por qué el pedido de taller "impone días" que no son reales:** `_regenerar_pedidos_taller`
(`services/talleres/commands/economia.py`) arma un pedido de resumen por mes con
`fecha_desde`/`fecha_hasta` clampeados al rango de la edición dentro de ese mes — es la unidad de
cobro (una línea de crédito al mes), no un compromiso de "el cliente tiene el equipo estos 7 días".
La UI del pedido lo refleja **honestamente**: en vez de "7 jornadas", la card de Fechas muestra la
lista de clases reales (`clases_taller`, enriquecida vía `taller_edicion_id` en el detalle del
pedido) con su día y franja — nunca el rango contable ni un conteo de jornadas.

**Blindaje:** `estudio` / `estudio_fijo` / `taller` son pedidos **derivados** (`es_pedido_derivado()`)
— sus fechas no se editan desde el pedido (409 si se intenta) y su(s) ítem(s) auto-generados
(centinela del Estudio / "Uso de equipos" de la edición) no se pueden quitar ni reemplazar por PATCH
genérico, aunque sí se puede **agregar** una línea nueva (matrícula, extra) sobre un pedido de
taller. `_revalidar_stock` salta taller (su disponibilidad ya la garantiza el gate de la edición, no
el motor de reservas genérico), y ningún derivado sin retiro real (`TIPOS_SIN_RETIRO`) dispara
"salió"/"volvió" ni recordatorios de retiro (`estudio` sí, porque puede tener un retiro físico real
de equipos sueltos).

**Puente Talleres → Pedidos:** la pestaña "Precios y pago" de una edición de taller lista los
pedidos mensuales que generó (`GET /admin/ediciones/{id}/pedidos`), cada uno linkeando de vuelta a
su página real — para administrar el cobro sin salir de Talleres.

### El turno del Estudio vinculado a un pedido de alquiler (#1308)

Un pedido de alquiler puede llevar horas del Estudio: se agregan desde la sección **"Turnos del
Estudio"** de su propia página. Por debajo eso crea una fila aparte en `alquileres`
(`tipo='estudio'` + `pedido_principal_id` apuntando al pedido), porque una franja horaria y un rango
de días son granularidades de tiempo incompatibles en las mismas columnas — y porque la economía del
Estudio se atribuye distinto.

**Pero eso es un detalle interno: no es un pedido.** Pedido del dueño, textual: *"no quiero dobles
pedidos fantasmas… quiero cobrar una sola cosa y facturar y establecer el estado"*. En consecuencia,
un turno vinculado:

| Se comporta como… | Cómo |
|---|---|
| **Un solo estado** | La cascada arrastra el turno al mismo paso de `FLOW` que su principal, y el gate `_turno_supera_a_principal` le impide adelantarse — si el pedido no confirmó, el turno tampoco. |
| **Un solo cobro** | `_agregar_pago_combinado` reparte un pago entre el pedido y sus turnos (satura el principal primero). |
| **Una sola factura** | `finanzas_flujo.pedido.combinar_turnos_vinculados` suma su plata al importe del comprobante del principal; facturar el turno solo da 400. |
| **Una sola fila en pantalla** | Se excluye (con su plata consolidada en el principal) de: lista de pedidos, cuentas por cobrar, portal del cliente, historial del cliente, dashboard y liquidación. Su página propia redirige al pedido real. |
| **Un solo mail** | No dispara recordatorio de retiro ni mail de confirmación propios. |

**Dónde SÍ se ve la fila, porque ahí no es ruido:** la agenda (calendario admin, feed iCal, agenda
del Estudio — es ocupación real del espacio), la economía del Estudio (estadísticas y atribución por
dueño — es una unidad de negocio propia) y el export contable / backup (`dataio`, que también
exporta `tipo` + el vínculo por número de pedido para no revivirlo desvinculado al restaurar).

Un turno del Estudio **suelto** (sin `pedido_principal_id`, dado de alta desde la agenda) sigue
siendo un pedido de primera clase en todas esas superficies. El eje es la columna, no el `tipo`:
fuente única `backend/pedidos_vinculados.py`, guard `test_pedidos_vinculados_source_scan.py`.
