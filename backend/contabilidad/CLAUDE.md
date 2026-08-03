# `backend/contabilidad/` — motor único de la plata "de adentro"

> Invariantes locales. El _por qué_ completo: `docs/DECISIONES.md` _2026-06-07 — `backend/contabilidad/`_,
> _2026-07-02 — CQRS-lite en `contabilidad/`_ y _2026-07-02 — Auditoría de `backend/contabilidad/`: bordes
> reforzados_.

**Toda la plata interna del negocio vive acá** (cajas/cuentas, libro de movimientos, saldos,
rendición entre socios, ganancia/P&L, cierre contable, reconciliación); los routes son solo
transporte HTTP. No re-implementar plata interna ad-hoc en un route.

## Estructura (CQRS-lite, espeja `services/specs/` y `services/specs_ingesta/`)

```
contabilidad/
  __init__.py       # barrel (docstring, sin __all__ — no hay re-exports públicos)
  constants.py       # TIPOS_CUENTA, COBRADORES, SOCIOS_HUMANOS, MONEDAS,
                      # TIPOS_MOVIMIENTO, METODOS_MOVIMIENTO, PARTES — las usan
                      # AMBOS lados (por eso no viven en commands/)
  queries/            # LECTURA — nunca mutan
    categorias.py       # listar_categorias
    cuentas.py            # listar_cuentas, obtener_cuenta
    movimientos.py          # listar_movimientos, obtener_movimiento,
                             # gastos_por_categoria, cobros_mensuales, beneficiarios_usados
    cierres.py                # cierre_de, mes_cerrado, snapshot_de
    saldos.py                   # partes_socios, ingresos_derivados, movimientos_planos,
                                 # calcular_saldos (PURA), saldos, saldo_de_cuenta
    rendicion.py                  # _netting (PURA), cobrado_por_socio, ya_transferido,
                                   # cuenta_de_parte, rendicion — la foto de UN MES
    posiciones.py                  # parte_de_cuenta, clasificar_flujo (PURA),
                                    # flujos_netos (PURA), sugerir_transferencias (PURA),
                                    # calcular_posiciones (PURA), posiciones — el ACUMULADO
    pyl.py                         # ingresos_devengados, ganancia_neta
    reconciliacion.py                # reconciliar
    reporte_mensual.py                 # reporte_mensual
    tablero.py                           # tablero, mes_actual
  commands/           # ESCRITURA — única puerta de mutación
    categorias.py       # validar_categoria (PURA), crear_categoria
    cuentas.py            # validar_cuenta (PURA), crear_cuenta, editar_cuenta, desactivar_cuenta
    movimientos.py          # validar_estructura_movimiento (PURA), crear_movimiento,
                             # editar_movimiento, anular_movimiento, actualizar_comprobante,
                             # _exigir_mes_abierto (guard, incluye _lock_mes), _validar_cuentas_y_categoria
    cierres.py                # cerrar_mes, reabrir_mes (ambos toman _lock_mes antes de tocar el mes)
    rendicion.py                 # saldar
```

**Invariante commands↔queries (igual que `specs`/`specs_ingesta`):** `commands/` puede
importar de `queries/`; `queries/` **nunca** de `commands/`. Ningún query del paquete
necesita nada de `commands/` — confirmado al hacer el split (2026-07-02): es un motor
mayormente de lectura, con 10 puntos de mutación reales.

Reglas que NO se rompen:

- **Los ingresos por alquiler DERIVAN de `alquiler_pagos`** (única fuente del cobro): el saldo de la
  caja de un cobrador se calcula sumando sus pagos por `destinatario`. **Nunca** recargar un movimiento
  por un cobro de cliente → cero doble-contabilización por construcción.
- **La plata no se borra:** anular un movimiento es **soft-delete** (deja de contar para los saldos
  pero queda trazable). Auditoría `created_by/updated_by/anulado_por`. **El `motivo` es OPCIONAL
  desde 2026-08** (decisión del dueño, confirmada tras nombrarle la regla anterior): el libro de
  `movimientos` son sus propios asientos y exigir una justificación escrita para corregir un tipeo
  propio era fricción sin contraparte — el riesgo que el motivo mitigaba (otra persona ensuciando el
  libro) no existe con un solo operador. Lo que NO cambió: sigue siendo soft-delete (es lo que
  permite reconstruir si el banco no cuadra), sigue pasando por `_exigir_mes_abierto`, y de cara a
  la UI la fila desaparece (`listar_movimientos` excluye anulados por default). **`alquiler_pagos`
  espeja el mismo patrón** (`created_by`/`anulado`/`anulado_por`/`anulado_at`/`anulado_motivo`,
  2026-07-02): anular un pago es `POST .../anular`, nunca `DELETE` — su `motivo` también pasó a
  OPCIONAL en 2026-08, por el mismo criterio y en el mismo acto que el de un movimiento (arriba);
  los 7 SELECT que suman
  `alquiler_pagos` (incluido `SALDADO_CTE` de `reportes/liquidacion.py`) filtran `NOT anulado`.
- **`editar_movimiento` revalida lo mismo que `crear_movimiento`** (existencia/actividad de cuenta,
  misma moneda origen↔destino, categoría activa) vía el helper compartido
  `_validar_cuentas_y_categoria` — editar NO es un camino más laxo que crear.
- **Enteros ARS** en todo el cálculo (no `NUMERIC`).
- **Multi-moneda no se mezcla:** cada caja tiene `moneda` (ARS/USD); saldos por moneda; transferencia/
  ajuste exigen misma moneda (sin conversión automática); P&L en ARS. La **moneda es inmutable tras
  crear** — NO "arreglar" eso como si fuera bug. **Cambio de divisa (comprar/vender USD con ARS)** pasa
  por `commands/movimientos.py::crear_cambio_divisa` — NO un tipo de movimiento nuevo: dos `ajuste`
  atados por `movimiento_par_id`, con `cotizacion` (pesos por dólar) guardada de forma informativa en
  ambas filas. Acepta 2 de {monto en pesos, monto en la otra moneda, cotización} y deriva el tercero.
  Una de las dos cuentas tiene que ser ARS (hoy solo hay ARS/USD). No reimplementar esta cuenta fuera
  de la puerta única.
- **Devengado (P&L) ≠ percibido (saldo de caja)** a propósito: pueden no coincidir mes a mes.
- **Cobradores en la constante única `COBRADORES`** (Pablo/Tincho/Rental/**Estudio**; Rental = cobrador
  por defecto) + `SOCIOS_HUMANOS` (Pablo/Tincho, sin cambios). **No duplicar** esos valores fuera de la
  constante. **`PARTES`** (rendición) es el mismo universo de 4. **Estudio** (economía separada del
  Estudio de grabación, iniciativa #1283) es una **caja real** (`Caja Estudio`, `tipo='fondo'`,
  `socio='Estudio'` — mismo puente 1:1 que Fondo Rental), NO un socio humano: `es_cc=False` sale solo
  de `socio not in SOCIOS_HUMANOS`, sin tocar `queries/saldos.py`. Un `tipo='fondo'` solo puede
  representar a un cobrador NO-humano (`_SOCIOS_FONDO` en `commands/cuentas.py` = COBRADORES menos
  SOCIOS_HUMANOS = Rental/Estudio); `crear_cuenta` persiste `socio` para `tipo in ("socio","fondo")`
  (antes solo para `"socio"` — un fondo nuevo lo perdía en silencio, fix 2026-07-23).
- **Socios (Pablo/Tincho) = cuenta corriente, NO caja:** su saldo es `arranque + cobró − su parte ±
  rendiciones` (>0 DEUDOR le debe a Rental, <0 ACREEDOR Rental le debe, 0 saldado); `su parte` sale de
  la liquidación (`reportes/`). **No** suman al total disponible y una **negativa (acreedor) NO es
  error** de reconciliación. Solo **Rental/Fondo Rental y Estudio/Caja Estudio** son cajas de plata real
  (su parte no se resta). Un socio humano tiene su plata real en un banco propio, fuera del sistema — su
  cuenta acá es **puro balance de deuda**, nunca plata física. Por eso (2026-07-02, `_validar_cuentas_y_categoria`):
  **`retiro`/`aporte` están BLOQUEADOS contra una cuenta de socio** (representan plata entrando/
  saliendo de una caja real, sin sentido contra un balance de deuda); **`transferencia`/`ajuste`
  siguen permitidos** (`saldar()` los necesita); **`gasto` está PERMITIDO a propósito** — "el socio
  pagó un gasto de Rental con su plata": un solo movimiento cuenta en el P&L categorizado (
  `gastos_por_categoria` no filtra por tipo de cuenta origen) y a la vez baja su deuda.
- **"Quién le debe a quién" tiene DOS lecturas, y hay que saber cuál mirar.** `queries/rendicion.py`
  es la foto de **UN MES** (`ya_transferido` filtra `rendicion_mes` → **arranca de cero cada mes por
  construcción**: un reparto parcial de julio es invisible en agosto). `queries/posiciones.py` es el
  **ACUMULADO** desde el clean start — la que dice si mover plata tiene sentido. Pueden apuntar en
  direcciones opuestas y las dos estar bien en su marco (agosto 2026: el mes decía "Rental → Tincho
  $110.500" mientras el acumulado decía que Tincho debía $734.088). **La acumulada manda para
  decidir.** Para un socio humano vale `posicion == −saldo_cc` (misma cantidad, signo opuesto) — lo
  fija el candado `test_contabilidad_posiciones.py::test_posicion_de_socio_es_el_negativo_de_su_cc`.
  Desde 2026-08 la acumulada además **parte el número en dos lecturas por parte**: `repartible`
  (solo pedidos CERRADOS, vía `cobrado_por_socio`/`SALDADO_CTE` — el número para DECIDIR un reparto)
  y `en_curso` (cobros de pedidos abiertos, que se reparten recién cuando el pedido cierre);
  identidad `pendiente == repartible − en_curso`. **Las transferencias sugeridas salen de
  `repartible`, no de `pendiente`** (sugerir mover el float de un pedido abierto sería repartir
  plata que no devengó — incidente 2026-08-03), y **un socio humano nunca aparece como pagador
  sugerido** (`excluir_pagadores=SOCIOS_HUMANOS`): su deuda se salda sola con su parte, no se le
  pide cash (decisión del dueño). Como receptor sí entra.
- **La posición NO es `saldo − su_parte`.** El saldo de una caja se mueve por cosas que no son un
  reparto: si Rental paga un gasto con la plata del Fondo, su cash baja pero **no cambia lo que le
  debe a los demás** (la parte de cada uno es un % de lo FACTURADO, no de lo que sobra tras los
  gastos). Por eso el flujo se clasifica (`clasificar_flujo`): **la cuenta corriente de un socio
  humano no tiene caja, así que todo lo que la toca es un reparto con el negocio; una caja real solo
  reparte cuando del otro lado hay otra parte.** El clasificador **no mira `es_rendicion`** —
  defensa en profundidad: la posición acumulada cuenta bien un reparto aunque, por lo que sea, no
  haya quedado marcado. `crear_movimiento` (2026-08) **auto-detecta y marca `es_rendicion`** cuando
  el caller no lo pidió explícito y las dos cuentas resuelven a partes DISTINTAS
  (`_es_reparto_entre_partes`, misma condición que la rama 1 de `clasificar_flujo`) — así un
  "Repartimos" del form general o un "Me pagó / Le cargué" de la ficha del socio quedan visibles
  para `ya_transferido`/la lista mensual "Movimientos de rendición", sin que el caller tenga que
  saber que esa marca existe.
- **Una caja real tiene DOS números y los dos son verdad:** su `saldo` (cash, tiene que cuadrar con
  el banco — **no se le resta su parte**) y su `pendiente` en `posiciones` (cuánto de eso es suyo).
  El crédito del Estudio contra Rental vive ahí; antes no existía en ninguna vista de saldos.
- **Candado de mes cerrado:** crear/editar/anular/`actualizar_comprobante` pasa por el motor
  (`_exigir_mes_abierto`) — un endpoint que escriba `movimientos` por fuera se saltearía el candado
  (era el bug de `subir_comprobante`, corregido 2026-07-02). La rendición reusa `SALDADO_CTE` (mismo
  universo de pedidos que el reporte). Esquema en dos capas (`init_db()` + migración) para toda tabla nueva.
- **Concurrencia (2026-07-02, verificado con test de dos conexiones reales):** `_exigir_mes_abierto`
  toma `pg_advisory_xact_lock(_ADVISORY_NS_CONTAB_MES, mes)` (mismo patrón que
  `services/facturacion/engine.py`/`routes/talleres.py`) — serializa `cerrar_mes`/`reabrir_mes` contra
  cualquier escritura del mismo mes, para que un `cerrar_mes` no ignore un movimiento creado a mitad de
  camino. `desactivar_cuenta` toma `SELECT ... FOR UPDATE` sobre la cuenta antes de desactivarla, para
  que un `crear_movimiento` concurrente contra esa cuenta espere el lock en vez de correr una carrera.
