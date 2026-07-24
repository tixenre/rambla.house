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
                                   # cuenta_de_parte, rendicion
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
- **La plata no se borra:** anular un movimiento es **soft-delete con motivo** (deja de contar para los
  saldos pero queda trazable). Auditoría `created_by/updated_by/anulado_por`. **`alquiler_pagos`
  espeja el mismo patrón** (`created_by`/`anulado`/`anulado_por`/`anulado_at`/`anulado_motivo`,
  2026-07-02): anular un pago es `POST .../anular` con motivo, nunca `DELETE`; los 7 SELECT que suman
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
- **Cobradores en la constante única `COBRADORES`** (Pablo/Tincho/Rambla/**Estudio**; Rambla = cobrador
  por defecto) + `SOCIOS_HUMANOS` (Pablo/Tincho, sin cambios). **No duplicar** esos valores fuera de la
  constante. **`PARTES`** (rendición) es el mismo universo de 4. **Estudio** (economía separada del
  Estudio de grabación, iniciativa #1283) es una **caja real** (`Caja Estudio`, `tipo='fondo'`,
  `socio='Estudio'` — mismo puente 1:1 que Fondo Rambla), NO un socio humano: `es_cc=False` sale solo
  de `socio not in SOCIOS_HUMANOS`, sin tocar `queries/saldos.py`. Un `tipo='fondo'` solo puede
  representar a un cobrador NO-humano (`_SOCIOS_FONDO` en `commands/cuentas.py` = COBRADORES menos
  SOCIOS_HUMANOS = Rambla/Estudio); `crear_cuenta` persiste `socio` para `tipo in ("socio","fondo")`
  (antes solo para `"socio"` — un fondo nuevo lo perdía en silencio, fix 2026-07-23).
- **Socios (Pablo/Tincho) = cuenta corriente, NO caja:** su saldo es `arranque + cobró − su parte ±
  rendiciones` (>0 DEUDOR le debe a Rambla, <0 ACREEDOR Rambla le debe, 0 saldado); `su parte` sale de
  la liquidación (`reportes/`). **No** suman al total disponible y una **negativa (acreedor) NO es
  error** de reconciliación. Solo **Rambla/Fondo Rambla y Estudio/Caja Estudio** son cajas de plata real
  (su parte no se resta). Un socio humano tiene su plata real en un banco propio, fuera del sistema — su
  cuenta acá es **puro balance de deuda**, nunca plata física. Por eso (2026-07-02, `_validar_cuentas_y_categoria`):
  **`retiro`/`aporte` están BLOQUEADOS contra una cuenta de socio** (representan plata entrando/
  saliendo de una caja real, sin sentido contra un balance de deuda); **`transferencia`/`ajuste`
  siguen permitidos** (`saldar()` los necesita); **`gasto` está PERMITIDO a propósito** — "el socio
  pagó un gasto de Rambla con su plata": un solo movimiento cuenta en el P&L categorizado (
  `gastos_por_categoria` no filtra por tipo de cuenta origen) y a la vez baja su deuda.
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
