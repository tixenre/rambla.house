"""Listas de estados de pedido para cláusulas SQL `IN (...)`.

Fuente ÚNICA de esas listas. Son constantes internas (nunca se derivan de input)
→ seguras para interpolar en SQL como `... p.estado IN {ESTADOS_RESERVADO}`.
Antes estaban duplicadas literal en varios routes.

**Hay DOS listas y NO son intercambiables:**

- `ESTADOS_RESERVADO` — los que reservan stock. Es la del **gate** (el core
  sagrado): si se afloja, hay SOBREVENTA.
- `ESTADOS_EN_CALENDARIO` — los que se MUESTRAN en un calendario. Es más
  ancha (incluye lo ya terminado) y es **solo de presentación**: no decide
  disponibilidad de nada.
"""

# Formato literal para cláusulas SQL `IN`. NO interpolar nada de fuera acá.
# `solicitado` (ex-`presupuesto`, renombrado 2026-07-14) reserva stock desde que
# el cliente lo solicita — igual que antes, solo cambió el nombre del estado.
ESTADOS_RESERVADO = "('solicitado','confirmado','retirado')"

# Qué pedidos SE VEN en un calendario/agenda: todo lo que pasó o va a pasar de
# verdad — es decir, todos MENOS `cancelado` (no ocurrió) y `borrador` (un
# presupuesto rápido, todavía no es una reserva).
#
# **Nunca usar esta lista en el gate ni en un cálculo de disponibilidad** —
# incluye `devuelto`/`finalizado`, que ya NO reservan stock: usarla ahí
# bloquearía equipos libres (y sugeriría que `ESTADOS_RESERVADO` "se puede
# ampliar", que es la puerta a la sobreventa). Lo verifica
# `test_reservas_sql_safety.py::test_el_motor_no_usa_la_lista_de_calendario`.
#
# Nace de un bug real (2026-08-02, reportado por el dueño): la agenda del
# Estudio filtraba por `ESTADOS_RESERVADO`, así que un mes ya pasado se veía
# VACÍO —sus turnos estaban finalizados— mientras el calendario general del
# Dashboard, que ya usaba esta lista más ancha (inline, duplicada), sí los
# mostraba. Dos calendarios de la misma plata contando cosas distintas.
#
# A propósito NO se re-exporta desde `reservas/__init__.py`: el barrel es la
# API pública del MOTOR, y esto no es semántica de reservas. Quien la quiera
# tiene que pedirla explícito (`from reservas.estados import ...`), no
# encontrarla al lado de `validar_stock`.
ESTADOS_EN_CALENDARIO = "('solicitado','confirmado','retirado','devuelto','finalizado')"
