"""Constantes compartidas de `contabilidad/` — las usan `queries/` Y `commands/`.

Viven acá (no en `commands/cuentas.py` ni `commands/movimientos.py`) porque
`queries/` las necesita para leer/derivar (ej. `queries/saldos.py` filtra por
`SOCIOS_HUMANOS`, `queries/reconciliacion.py` filtra por `COBRADORES`) y
`queries/` nunca importa de `commands/` (invariante CQRS-lite del paquete).
"""

TIPOS_CUENTA = ("caja", "banco", "socio", "fondo")

# Cobradores = quiénes pueden cobrar un pago de cliente (el `destinatario` del
# pago). Fuente única — `routes.alquileres` importa de acá como DESTINATARIOS_PAGO.
# Cada uno se vincula a una caja (la columna `socio` de `cuentas` guarda a
# qué cobrador representa): Pablo/Tincho → su caja de socio; Rental → Fondo
# Rental (la cuenta real de MercadoPago del rental, a nombre de Tincho);
# Estudio → Caja Estudio (la cuenta real de MercadoPago del Estudio, a nombre
# de Pablo — economía separada, 2026-07-23: también un fondo — caja real de
# plata, no cuenta corriente — no un socio humano, por eso NO entra a
# SOCIOS_HUMANOS). "Rental" (ex "Rambla", renombrado 2026-07-29 para no
# confundir con la marca "Rambla Rental") es la parte/cobrador/dueño de la
# línea de negocio de alquiler de equipos — nada que ver con el nombre de la
# empresa, que sigue siendo "Rambla Rental" en todo el resto de la app.
COBRADORES = ("Rental", "Tincho", "Pablo", "Estudio")
# Socios humanos (subconjunto): los únicos válidos para una caja de tipo 'socio'.
SOCIOS_HUMANOS = ("Pablo", "Tincho")

# Monedas soportadas. Una caja es en pesos (default) o en dólares; los saldos NO
# se mezclan entre monedas y las transferencias deben ser de la misma moneda.
MONEDAS = ("ARS", "USD")

TIPOS_MOVIMIENTO = ("gasto", "transferencia", "retiro", "aporte", "ajuste")
METODOS_MOVIMIENTO = ("transferencia", "efectivo")

# Las partes de la rendición mensual (quién le debe a quién). Antes vivía
# duplicada, byte-idéntica, en `rendicion.py` Y `reporte_mensual.py` — consolidada
# acá al hacer el split CQRS-lite (una sola forma de cada cosa). "Estudio" suma
# como 4ta parte (2026-07-23): su economía es separada de la del rental, así
# que también necesita su propio neteo cobró-vs-corresponde.
PARTES = ("Pablo", "Tincho", "Rental", "Estudio")
