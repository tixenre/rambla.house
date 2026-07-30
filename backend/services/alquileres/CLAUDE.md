# `backend/services/alquileres/` — motor de pedidos (creación, ítems, pagos, transiciones)

> Invariantes locales. El _por qué_ completo: issue de tracking #1312 (roadmap de 4 fases) y
> `docs/DECISIONES.md` (entrada del split, misma fecha que cada fase que aterriza).
>
> **Este paquete se construye incrementalmente.** Lo que sigue describe la estructura OBJETIVO
> (las 4 fases completas) — cada sección está marcada con su fase y si ya aterrizó o no. Antes de
> asumir que algo ya vive acá, confirmá contra el código: mientras una fase no aterrizó, esa lógica
> sigue en `routes/alquileres/` como siempre.

**Toda la lógica de negocio de un pedido** (crear, editar ítems/datos, cotizar, pagar, transicionar
de estado, documentos) vive acá; `routes/alquileres/` es transporte (auth, conn/commit/rollback,
HTTP) y **delega**. El motor de reservas (`backend/reservas/`) es SAGRADO: este paquete solo lo
CONSUME (`validar_stock_hipotetico`/`calcular_disponibilidad_draft`), nunca lo reimplementa —
mismo principio que `services/estudio/`.

## Estructura objetivo (CQRS-lite, espeja `services/estudio/`/`services/talleres/`)

```
services/alquileres/
  __init__.py       # barrel (docstring, sin __all__ — no hay re-exports públicos)
  queries/            # LECTURA — nunca mutan                         [Fase 1 — pendiente]
    disponibilidad.py   # get_disponibilidad, get_disponibilidad_dias, _parse_items_draft,
                         # _validar_horarios_habilitados
    documentos.py        # _doc_html, _ctx_mail_pedido, _cuerpo_mail_simple, _add_componentes,
                          # _agrupar_items_por_categoria, _ordenar_items_en_grupos (lectura + I/O
                          # externo — PDF/mail — cero escritura a DB)
    cotizacion.py          # cotizar (lectura/cómputo puro, cero escritura)
    detalle.py              # _get_alquiler_items/_detalle/_pagos, _turnos_vinculados,
                            # _clases_del_taller, _enriquecer_pedido_con_total,
                            # _get_historial_modificaciones, _pedido_principal_liviano
  commands/           # ESCRITURA — única puerta de mutación
    pagos.py             # _agregar_pago, _agregar_pago_combinado, _anular_pago,             [Fase 2]
                         # _recalcular_monto_pagado, _resolver_destino_metodo — pendiente
    pedido.py             # _delete_pedido (extraído del SQL inline que tenía el handler —      [Fase 2]
                          # sin gate nuevo, ver nota de #1311 abajo), _maybe_finalizar,
                          # _next_numero_pedido (sintaxis de lectura, `nextval()` muta) — pendiente
    items.py               # _recalcular_total_pedido, _apply_pedido_datos,                    [Fase 3]
                           # _apply_pedido_items, _resolver_descuentos_snapshot_o_vivo,
                           # _validar_reemplazo_items_taller, propagar_descuento_a_presupuestos
                           # — pendiente
    transiciones.py         # cambiar_estado, _cascada_turnos_vinculados,                        [Fase 4]
                            # _turno_supera_a_principal, _tiene_factura_activa,
                            # _requiere_revalidar_stock, _revalidar_stock — pendiente
    creacion.py              # create_pedido, create_pedido_retry (el advisory lock +           [Fase 4]
                             # el retry-loop de deadlock, BYTE-IDÉNTICOS) — pendiente
```

**`modelos.py` (los Pydantic de request/response) se queda en `routes/alquileres/` — no se mueve
en ninguna fase.** Es el contrato HTTP, no lógica de negocio; ninguno de los 5 paquetes precedentes
movió sus modelos Pydantic fuera de las rutas.

**Invariante commands↔queries (igual que `contabilidad`/`descuentos`/`services/estudio`/
`services/talleres`):** `commands/` puede importar de `queries/`; `queries/` **nunca** de
`commands/`. Sin test automático que lo verifique (ningún paquete precedente lo tiene) — es
convención de review, la hace cumplir el supervisor.

## Reglas que no se rompen

- **El paquete NO importa de `routes.*` — con una excepción documentada y preservada a propósito:**
  hay un ciclo real `routes.alquileres ↔ routes.cliente_portal` sostenido HOY por imports diferidos
  (dentro del cuerpo de función, nunca a nivel de módulo) en AMBAS direcciones —
  `transiciones.py::cambiar_estado` necesita `cliente_portal.ESTADOS_MODIFICABLES`/
  `_cancelar_solicitudes_pendientes` de vuelta. La Fase 4 preserva este import diferido TAL CUAL
  (solo cambia el path de origen de `routes.alquileres.transiciones` a
  `services.alquileres.commands.transiciones`) — no se rediseña el ciclo en esta iniciativa. Un
  import a nivel de MÓDULO nuevo entre este paquete y `routes.cliente_portal` rompería el ciclo en
  tiempo de import — eso sí es un bug real, no una variante aceptable.
- **`_next_numero_pedido` parece lectura (`SELECT nextval(...)`) pero `nextval()` tiene efecto real**
  (avanza la secuencia) — va a `commands/`, no a `queries/`, pese a la sintaxis.
- **`_delete_pedido` (Fase 2) se extrae SIN agregarle ningún gate nuevo.** La decisión de si
  "Eliminar pedido" necesita bloquear contra `monto_pagado`/stock real sigue abierta (issue #1311,
  charla aparte) — esta fase solo le da un lugar limpio para el día que se decida, no decide nada.
- **`FOR UPDATE`/`pg_advisory_xact_lock`/las transacciones se mueven BYTE-IDÉNTICOS.** Ninguna fase
  cambia el orden de lock-antes-de-insertar ni el manejo de `DeadlockDetected` de
  `create_pedido_retry` — son la garantía dura del motor, no se tocan al moverlos de archivo.
- **`HTTPException` se levanta directo desde `queries/`/`commands/`** (no `ValueError` +
  traducción en el route) — mismo estilo que `services/estudio/`/`services/talleres/`, y lo que ya
  hace el código hoy en `routes/alquileres/`. Move-verbatim no cambia el tipo de excepción.
- **Cada fase que toque algo que inserta contra el motor de reservas debe sumar su directorio al
  `fuentes` de `tests/test_gate_not_bypassed.py`** (Fase 3 es la que aplica — `_apply_pedido_items`
  es donde vive el INSERT relevante) — mismo mecanismo ya usado para sumar `services/estudio`/
  `services/talleres`; sin esto el guard estructural anti-bypass pierde cobertura en silencio.
- **~57 call-sites externos** (8 archivos de producción — `routes/estudio.py`, `routes/talleres.py`,
  `jobs/recordatorios.py`, `clientes/commands/cliente.py`, todo `routes/cliente_portal/` — más ~33
  tests) dependen del re-export plano de `routes/alquileres/` hoy. Cada fase que mueve un símbolo
  con consumidores externos actualiza esos imports en la misma PR — no se deja un símbolo
  "duplicado" en los dos lugares.

El supervisor marca: lógica de pedidos reimplementada fuera de este paquete una vez que su fase ya
aterrizó; un `queries/` importando de `commands/`; un import a nivel de MÓDULO nuevo entre este
paquete y `routes.cliente_portal` (rompería el ciclo documentado); el `FOR UPDATE`/
`pg_advisory_xact_lock`/el retry-loop de `create_pedido_retry` tocado o reordenado al moverlo; un
gate nuevo agregado a `_delete_pedido` sin que la decisión de #1311 se haya tomado; una fase que
toque el motor de reservas sin sumar su directorio a `test_gate_not_bypassed.py`.
