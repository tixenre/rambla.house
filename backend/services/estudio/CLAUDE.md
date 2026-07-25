# `backend/services/estudio/` — motor de disponibilidad y reserva de El Estudio

> Invariantes locales. El _por qué_ completo: `docs/DECISIONES.md` (entrada del split, misma fecha
> que esta pasada) y la fundacional _2026-05-27 — El Estudio: producto aparte que reusa el motor de
> reservas_.

**Toda la decisión de "el estudio está libre / se reserva" vive acá**; `routes/estudio.py` es
transporte (auth, conn/commit/rollback, HTTP) y conserva perfil/fotos/trabajos, el CRUD de slots
fijos y las vistas de agenda/ocupación del dashboard admin (lectura agregada de display, sin
decisión de negocio — no referencian símbolos de este paquete). El motor de reservas de equipos
(`backend/reservas/`) es SAGRADO: este paquete solo lo CONSUME (`calcular_disponibilidad`,
`validar_stock_hipotetico`), nunca lo reimplementa. El **espacio** (equipo centinela,
`estudio.equipo_id`) usa una query DEDICADA con SU buffer propio — no pasa por el motor.

## Estructura (CQRS-lite, espeja `descuentos/` y `contabilidad/`)

```
services/estudio/
  __init__.py       # barrel (docstring, sin __all__ — no hay re-exports públicos)
  constants.py        # _ADVISORY_NS_ESTUDIO (lock namespace del CRUD de slots del route +
                       # del gate de publicación de talleres, no de la reserva por hora)
  queries/            # LECTURA — nunca mutan
    estudio.py           # _get_estudio_row (fila singleton id=1)
    disponibilidad.py      # _franja_estudio, _viola_anticipacion, _centinela_libre (buffer
                            # propio del espacio), _slot_bloqueante, _taller_bloqueante,
                            # _estudio_disponible (engine unificado: slot→taller→centinela),
                            # verificar_sesiones_disponibles (409, la usan slots + talleres),
                            # revalidar_disponibilidad_estudio (la usa transiciones.cambiar_estado)
    promo.py              # get_disponibilidad (wrapper LOCAL sobre reservas.calcular_disponibilidad,
                           # conexión propia — ver "Reglas" abajo), _pack_equipo_ids (sobrevive
                           # como semilla de componentes), _promo_info
  commands/           # ESCRITURA — única puerta de mutación
    reserva.py           # SueltoItem, _ESTADOS_ADMIN_CREACION, _crear_pedido_estudio (núcleo
                          # compartido cliente+admin), editar_reserva (PATCH admin)
    promo.py              # crear_promo (crea el combo desde el pack curado)
```

**Invariante commands↔queries (igual que `contabilidad`/`descuentos`):** `commands/` puede importar
de `queries/`; `queries/` **nunca** de `commands/`.

## Reglas que no se rompen

- **ESPACIO ≠ EQUIPOS.** El centinela (`_centinela_libre`) usa SOLO `estudio.buffer_horas`, query
  dedicada — NO el motor sagrado, así el buffer global de equipos no interviene. La promo/los
  sueltos son equipos reales → SÍ pasan por `reservas` (`validar_stock_hipotetico`). No mezclar.
- **El re-chequeo de `_centinela_libre` bajo `SELECT ... FOR UPDATE` es la garantía DURA**; el
  chequeo temprano (`_slot_bloqueante`/`_taller_bloqueante` al principio de `_crear_pedido_estudio`)
  es estructural, no reemplaza el lock. **Orden lock-antes-de-insertar** en `_crear_pedido_estudio`
  es a propósito (deadlock simétrico documentado inline, encontrado con
  `test_concurrencia_admin_dos_altas_misma_franja_solo_una_pasa`) — no invertirlo.
- **Promo = BEST-EFFORT (nunca 409, arma `promo_advertencia`); sueltos = DURO (409 si falta
  stock).** Decisión explícita del dueño (ya revertida una vez, `0a8364a`) — no "corregir" la promo
  a duro. El split entre ambos vive en el CALLER (`_crear_pedido_estudio`/`editar_reserva`); el gate
  (`validar_stock_hipotetico`) no cambia de comportamiento.
- **El paquete NO importa de `routes.*`.** Dos piezas resuelven esto sin recrear el anti-patrón:
  `queries/promo.py::get_disponibilidad` es un wrapper LOCAL de 3 líneas sobre
  `reservas.calcular_disponibilidad` (con conexión PROPIA — deliberado, es un snapshot
  committed-only; nunca pasarle la conn del caller); `commands/`/`queries/` reciben `estudio`,
  `cliente_id`/`cliente_nombre`/etc. ya resueltos como parámetros — la resolución de sesión/cliente/
  Didit queda en el route (`crear_reserva_estudio`, `_resolver_cliente_admin`).
- **Duplicación conocida, no resuelta en este split (documentada a propósito):** (1) el predicado
  SQL "taller activo con clase en la fecha" está copiado en `_taller_bloqueante` (acá) y en las
  vistas de agenda/ocupación del route (`agenda_estudio`/`_ocupacion_estudio_rango`, ambas fuera de
  este paquete — son vistas agregadas de display, no gates); (2) el cálculo de precio
  promo+sueltos está copiado en `_crear_pedido_estudio`, `editar_reserva` y `cotizar_reserva_estudio`
  (route). Ninguna es un problema de concurrencia — el lock de creación está unificado en un solo
  lugar (`_crear_pedido_estudio`). Si aparece de nuevo, evaluar unificar; no es alcance de este split.
- **Inconsistencia de locking conocida, NO resuelta (documentar y avisar, no tocar sin chequear
  primero):** publicar un taller/slot usa `pg_advisory_xact_lock(_ADVISORY_NS_ESTUDIO, 1)`
  (namespace de este paquete, tomado desde `routes/estudio.py` y `routes/talleres.py`); crear una
  reserva por hora usa `SELECT ... FOR UPDATE` sobre la fila del centinela. Son primitivas
  distintas que no se bloquean entre sí — raza teórica angosta, nunca observada.
- **`editar_reserva` no re-implementa el gate de identidad/anticipación** (son del cliente público,
  no aplican al admin) — solo re-valida slot/taller/stock, igual que `_crear_pedido_estudio`.
- **Un `estudio_fijo` (pedido de slot) no se edita acá** (`editar_reserva` lo rechaza con 409) — lo
  gobierna su slot (`routes/estudio.py::_regenerar_pedidos_slot`, fuera de este paquete a propósito:
  dominio "slots", no "disponibilidad/reserva por hora").

El supervisor marca: lógica de disponibilidad/reserva del Estudio reimplementada fuera de este
paquete; un import de `routes.*` dentro de `services/estudio/`; un `queries/` importando de
`commands/`; un commit dentro de un command (el route es dueño de la transacción); la promo vuelta
DURA o un suelto vuelto best-effort; el re-chequeo bajo `FOR UPDATE` removido o reordenado después
del INSERT del ítem centinela.
