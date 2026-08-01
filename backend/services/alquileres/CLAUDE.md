# `backend/services/alquileres/` — motor de pedidos (creación, ítems, pagos, transiciones)

> Invariantes locales. El _por qué_ completo: issue de tracking #1312 (roadmap de 4 fases,
> todas landeadas) y `docs/DECISIONES.md` (entrada del split, misma fecha que cada fase).

**Toda la lógica de negocio de un pedido** (crear, editar ítems/datos, cotizar, pagar, transicionar
de estado, documentos) vive acá; `routes/alquileres/` es transporte (auth, conn/commit/rollback,
HTTP) y **delega** — mismo aspecto que ya tenía `routes/alquileres/descuentos.py` (el molde del
paquete completo, hoy generalizado a todo `routes/alquileres/`). El motor de reservas
(`backend/reservas/`) es SAGRADO: este paquete solo lo CONSUME
(`validar_stock_hipotetico`/`calcular_disponibilidad_draft`), nunca lo reimplementa — mismo
principio que `services/estudio/`.

## Estructura (CQRS-lite, espeja `services/estudio/`/`services/talleres/`)

```
services/alquileres/
  __init__.py       # barrel (docstring, sin __all__ — no hay re-exports públicos)
  queries/            # LECTURA — nunca mutan
    disponibilidad.py   # dias_no_disponibles_de_pedido, disponibilidad_de_rango,
                         # _parse_items_draft/_dias, _validar_horarios_habilitados
    documentos.py         # DOCUMENTOS, _doc_html, _ctx_mail_pedido, _cuerpo_mail_simple,
                          # _add_componentes, _agrupar_items_por_categoria,
                          # _ordenar_items_en_grupos (lectura + I/O externo — PDF/mail —
                          # cero escritura a DB)
    cotizacion.py          # cotizar_carrito (el cuerpo de /api/cotizar) +
                           # _resolver_descuentos_snapshot_o_vivo (lectura pura — vive
                           # ACÁ, no en commands/, pese a que su otro consumidor real es
                           # un command; ver la nota de invariante más abajo)
    detalle.py              # _get_alquiler_items/_detalle/_pagos, _es_historico,
                            # _turnos_vinculados, _pedido_principal_liviano,
                            # _clases_del_taller, _enriquecer_pedido_con_total
  commands/           # ESCRITURA — única puerta de mutación
    pagos.py             # PagoCreate, DESTINATARIOS_PAGO/METODOS_PAGO/defaults,
                         # _resolver_destino_metodo, _recalcular_monto_pagado,
                         # _agregar_pago, _agregar_pago_combinado, _anular_pago
    pedido.py             # _maybe_finalizar, _next_numero_pedido (sintaxis de lectura,
                          # `nextval()` muta), _delete_pedido (sin gate nuevo — ver nota)
    items.py               # _recalcular_total_pedido, _apply_pedido_datos,
                           # _apply_pedido_items, _validar_reemplazo_items_taller,
                           # _fecha_cambia, _puede_quedar_sin_items,
                           # propagar_descuento_a_presupuestos
    transiciones.py         # cambiar_estado, TRANSICIONES/FLOW/ESTADOS_QUE_RESERVAN/
                            # ESTADOS_REQUIEREN_FECHAS, _cascada_turnos_vinculados,
                            # _turno_supera_a_principal, _tiene_factura_activa,
                            # _requiere_revalidar_stock, _revalidar_stock
    creacion.py              # create_pedido, create_pedido_retry (el advisory lock +
                             # el retry-loop de deadlock, BYTE-IDÉNTICOS;
                             # _ADVISORY_NS_PEDIDO = 5390412)
```

**`modelos.py` (los Pydantic de request/response) se queda en `routes/alquileres/` — no se movió.**
Es el contrato HTTP, no lógica de negocio; ninguno de los 5 paquetes precedentes movió sus modelos
Pydantic fuera de las rutas. Donde un `command` necesita el tipo solo como forward-ref (nunca lo
instancia), el import queda detrás de `TYPE_CHECKING` (`items.py`/`creacion.py`) — evita un import
real de este paquete hacia `routes.*` que no hace falta. La única excepción real es `PagoCreate`
(`commands/pagos.py`): `_agregar_pago_combinado` la INSTANCIA como parte de su algoritmo de
reparto, no solo la tipa — mismo criterio que `SueltoItem` en `services/estudio/commands/reserva.py`.

## Invariante commands↔queries (igual que `contabilidad`/`descuentos`/`services/estudio`/`services/talleres`)

`commands/` puede importar de `queries/`; `queries/` **nunca** de `commands/`. Sin test automático
que lo verifique (ningún paquete precedente lo tiene) — es convención de review, la hace cumplir el
supervisor.

**Caso real de este invariante:** `_resolver_descuentos_snapshot_o_vivo` es lectura pura (nunca
muta) pero su consumidor HISTÓRICO/principal (`_recalcular_total_pedido`/`_apply_pedido_items`,
`commands/items.py`) es un command — parecería "pertenecer" ahí. Pero como TAMBIÉN la necesita
`cotizar_carrito` (lectura, `queries/cotizacion.py`), el único lugar que respeta la dirección del
invariante en ambos sentidos es `queries/cotizacion.py`: vive ahí, y `commands/items.py` la importa
de vuelta. Precedente para el próximo caso similar: cuando un helper de lectura pura tiene un
consumidor en `commands/`, va a `queries/` — nunca al revés, aunque el consumidor "más importante"
sea un command.

## Reglas que no se rompen

- **El paquete NO importa de `routes.*`.** Hasta la remoción de "solicitudes de modificación"
  (retiro de la feature del portal, ver `docs/DECISIONES.md`) había acá un ciclo real
  `services.alquileres ↔ routes.cliente_portal` sostenido por imports diferidos en AMBAS
  direcciones (`cambiar_estado` necesitaba `routes.cliente_portal.ESTADOS_MODIFICABLES`/
  `_cancelar_solicitudes_pendientes` de vuelta) — se cerró solo, sin rediseño, al borrar esa
  llamada. Queda una sola dirección real, un import normal (no un ciclo):
  `routes/cliente_portal/pedidos.py::cliente_cancelar_pedido` importa
  `services.alquileres.commands.transiciones.cambiar_estado` (deferred dentro de la función, por
  convención del paquete, no por necesidad de romper un ciclo). Un import a nivel de MÓDULO nuevo
  DESDE este paquete HACIA `routes.cliente_portal` reabriría un ciclo — eso sí sería un bug real.
- **`_next_numero_pedido` parece lectura (`SELECT nextval(...)`) pero `nextval()` tiene efecto real**
  (avanza la secuencia) — vive en `commands/pedido.py`, no en `queries/`, pese a la sintaxis.
- **`_delete_pedido` se extrajo SIN agregarle ningún gate nuevo.** La decisión de si "Eliminar
  pedido" necesita bloquear contra `monto_pagado`/stock real sigue abierta (issue #1311, charla
  aparte) — la extracción solo le dio un lugar limpio, no decidió nada.
- **`FOR UPDATE`/`pg_advisory_xact_lock`/las transacciones se movieron BYTE-IDÉNTICOS.** Ninguna
  fase cambió el orden de lock-antes-de-insertar ni el manejo de `DeadlockDetected` de
  `create_pedido_retry` — son la garantía dura del motor, no se tocaron al moverlos de archivo.
- **`HTTPException` se levanta directo desde `queries/`/`commands/`** (no `ValueError` +
  traducción en el route) — mismo estilo que `services/estudio/`/`services/talleres/`.
- **`_apply_pedido_items` (`commands/items.py`) es donde vive el INSERT contra el motor de
  reservas — sumado a `tests/test_gate_not_bypassed.py`** (`fuentes` + `ALLOWLIST_DELEGADORES`
  apuntan acá) para que el guard estructural anti-bypass no pierda cobertura.
- **~57 call-sites externos** (8 archivos de producción — `routes/estudio.py`, `routes/talleres.py`,
  `jobs/recordatorios.py`, `clientes/commands/cliente.py`, todo `routes/cliente_portal/` — más ~33
  tests) dependían del re-export plano de `routes/alquileres/` — todos preservados: `routes/alquileres/
  {core,detalle,disponibilidad,documentos,cotizacion,pagos,transiciones,pedidos}.py` son puro
  re-export/transporte sobre este paquete, mismos nombres públicos en los mismos módulos de siempre.
  Un símbolo nuevo con consumidores externos actualiza esos imports en la misma PR — no se deja
  "duplicado" en los dos lugares.

El supervisor marca: lógica de pedidos reimplementada fuera de este paquete; un `queries/`
importando de `commands/`; un import a nivel de MÓDULO nuevo desde este paquete hacia
`routes.cliente_portal` (reabriría el ciclo ya cerrado); el `FOR UPDATE`/`pg_advisory_xact_lock`/el
retry-loop de `create_pedido_retry` tocado o reordenado; un gate nuevo agregado a `_delete_pedido`
sin que la decisión de #1311 se haya tomado; un INSERT nuevo contra `alquiler_items` que no pase por
`test_gate_not_bypassed.py`.
