# Sistema de identidad — manual técnico

> **Fuente única de "cómo funciona la identidad" en Rambla Rental.** Describe la arquitectura y el flujo
> (estable); los **paths** son los puntos de entrada al código. Las **reglas de criterio + el porqué** NO
> se duplican acá — viven en [`MEMORIA.md`](MEMORIA.md) / [`DECISIONES.md`](DECISIONES.md) y se linkean.
> Si tocás el motor y este manual queda viejo, actualizalo en el mismo cambio (el supervisor lo marca).
>
> Hermano de [`SISTEMA_AUTH.md`](SISTEMA_AUTH.md): **auth = "¿podés entrar?" · identity = "¿quién sos?"**.
> Historia: Fase 2 de la iniciativa de identidad passwordless ([#1098](https://github.com/tixenre/rental/issues/1098)).

## El panorama: un motor "quién sos", separado de "podés entrar"

Toda la identidad de un cliente vive en el **paquete-motor único `backend/identity/`** (como `auth/`,
`reservas/` o `contabilidad/`). La idea central es una **frontera** entre tres piezas que se tocan **solo
en `clientes.id`**:

```
  auth/  ── "¿podés entrar?"          identity/ ── "¿quién sos?"          services/didit/ ── el proveedor KYC
  llaves + sesión + cookie            persona: ancla CUIL, KYC,           DNI+selfie → RENAPER.
  (jti, revocación)                   contactos, estado, dedup            El payload CRUDO muere acá.
        │                                    │                                    │
        └────────────── clientes.id ─────────┴──────── datos normalizados ────────┘
   auth/ NUNCA ve un CUIL          identity/ NUNCA ve una cookie       identity/kyc lo USA, no al revés
```

- **`auth/` nunca ve un CUIL.** Mintea/lee la sesión; no sabe de identidad legal.
- **`identity/` nunca ve una cookie.** Sabe quién es la persona (RENAPER, CUIL, contactos, estado); no
  mintea sesión. Recibe datos **ya normalizados**.
- **`services/didit/` es el proveedor.** Verifica DNI+selfie contra RENAPER y devuelve datos. El **payload
  crudo de Didit muere ahí** (Ley 25.326); `identity/kyc` lo consume normalizado. Cambiar de proveedor =
  cambiar este boundary, sin tocar `identity/`.

```
backend/identity/
  __init__.py    # API de salida: get_validated_identity (lector ÚNICO) + ValidatedIdentity + helpers de display
  anchor.py      # el ancla CUIL: normalizar (solo dígitos) + validar (mod-11)
  contacts.py    # verified_contacts: upsert + email/teléfono de comunicación (Google preferido → Didit)
  kyc.py         # orquestación del KYC: aprobar / actualizar_estado / consentimiento — la ÚNICA pluma de *_renaper
  merge.py       # fusión PESADA de dos cuentas con datos (dedup) — reasigna FKs + borra source
```

`services/didit/` (el proveedor, aparte): `decision.py` (parser puro: RENAPER + contactos), `webhook.py`
(verificación HMAC), `client.py` (retrieve_decision por API). Lo orquesta `routes/didit.py` (transporte fino).

---

## 1 · El lector único — `get_validated_identity` (`identity/__init__.py`)

**La API de salida.** El **único** lector de la identidad validada + estado. Contrato, factura y remito
consultan ESTO; **nadie copia ni tipea estos campos en otra tabla** (cero drift por construcción).

| Símbolo | Rol |
|---|---|
| `get_validated_identity(cliente_id, conn=None) -> ValidatedIdentity\|None` | Lee `clientes` + deriva estado + arma la foto. Acepta `conn` (corre en la transacción del request) o abre el suyo. `None` si el cliente no existe. |
| `ValidatedIdentity` (dataclass) | La foto: `estado`/`verificado` · identidad legal (`nombre_legal`/`dni`/`cuil`/`direccion`/…, **None si no verificado**) · contacto (`email`/`telefono`, disponible aún sin verificar) · detalle (`didit_status`/`verificado_at`). |
| `_estado(c)` | Estado derivado: **`conflicto`** (si `identidad_conflicto`) › **`verificado`** (si `dni_validado_at`) › **`no_verificado`**. La verdad vive en esas dos columnas, no en una columna de estado que pudiera desincronizarse. |

**Honesto sobre el estado:** si la cuenta NO está verificada, los campos de identidad legal quedan `None`
(no se inventa con el nombre base/Google). El contrato/factura exigen `verificado`; el gate de pedidos
(`require_cliente_verificado`, en `auth/guards.py`) ya bloquea pedir sin verificar.

### Helpers de display sobre una fila ya leída (sin N+1)
Los lectores que **ya tienen la fila** del cliente (contrato/remito en `routes/cliente_portal/documentos.py`,
enriquecido de pedidos en vivo en `routes/alquileres/core.py`) usan helpers **puros** en vez de duplicar el
`if nombre_renaper …` o pegar un `get_validated_identity` por pedido:

- `nombre_validado(c)` → `"<nombre_renaper> <apellido_renaper>"` si está verificado; `None` si no (el lector
  cae a su propio fallback al nombre base).
- `direccion_validada(c)` → `direccion_renaper` o `None`.

Fuente ÚNICA de la regla "preferí RENAPER si está verificado". El supervisor marca esa derivación duplicada
fuera de acá.

---

## 2 · El ancla CUIL — `identity/anchor.py` + índice único parcial

El **CUIL** es el ancla de identidad: "una persona verificada = una cuenta". No es la llave de login (eso es
`auth/`); es un **atributo único verificado**.

| Pieza | Rol |
|---|---|
| `normalizar_cuil(raw)` | Deja solo dígitos; devuelve 11 dígitos o `None`. |
| `cuil_valido(cuil)` | Validación **mod-11** (dígito verificador). Un CUIL mal formado de Didit **no se ancla** (`kyc.aprobar` lo descarta con COALESCE-None). |

**Índice único PARCIAL** (`uniq_cliente_cuil_verificado`, en `init_db` + migración `f2cu1lun1qx01`):
```sql
UNIQUE (cuil) WHERE cuil IS NOT NULL AND dni_validado_at IS NOT NULL
```
Solo aplica a **verificados** → no rompe a no-verificados ni a extranjeros sin CUIL (`cuil NULL` nunca entra
al índice). Lo escribe **solo** `identity/kyc` al aprobar Didit; nunca el usuario. Va **al final** del
rollout, tras deduplicar lo existente (ver §5). En `init_db` la creación es **resiliente** (try/except
`UniqueViolation` → no rompe el boot si quedan duplicados legacy); la migración es **fail-loud** (señal de
"deduplicá primero").

---

## 3 · Contactos verificados — `identity/contacts.py` + tabla `verified_contacts`

Mail/teléfono **verificados** (por Google OAuth, código de Didit, u OTP) = factores de **comunicación +
recuperación**. NO son llaves de login (el teléfono nunca lo es).

**Tabla `verified_contacts`** (en `init_db` + migración `1d3nt1dadf2a`): `cliente_id` (FK CASCADE) · `kind`
(`email`/`phone`) · `value` · `source` (`google`/`didit`/`otp`/`manual`) · `verified_at` · señales anti-fraude
de Didit (`is_disposable`/`is_virtual`/`is_breached`) · **`UNIQUE(cliente_id, kind, value)`** (re-verificar
refresca metadata vía `ON CONFLICT DO UPDATE`).

| Función | Rol |
|---|---|
| `upsert_contacto(conn, …)` | Inserta/actualiza un contacto (owner-scoped). |
| `guardar_contactos_didit(conn, cliente_id, contactos)` | Persiste lo que devolvió Didit (mail + teléfono). |
| `email_comunicacion(conn, cliente_id)` | Mail de comunicación: **Google preferido** (`clientes.email`, verificado por OAuth + disponible desde el alta) → fallback al verificado por Didit (cuentas passkey-only). |
| `telefono_contacto(conn, cliente_id)` | Teléfono: el verificado (E.164, de Didit) preferido → fallback al base `clientes.telefono`. |
| `contactos_verificados_batch(conn, cliente_ids)` | Versión batch de los dos de arriba (2026-08-14): `{cliente_id: {"email":..,"phone":..}}` en 1 query `IN (...)` — para listados que no pueden pagar 2 queries por cliente (`services.pedidos_enriquecimiento`). Sin fallback a columnas base a propósito (responsabilidad del caller aplicar la misma prioridad que las versiones singulares). |

El teléfono se guarda en **E.164** (de Didit) → listo para WhatsApp futuro (notificaciones, no auth).

---

## 4 · La orquestación del KYC — `identity/kyc.py`

El **ÚNICO** lugar que escribe la identidad validada (las columnas `*_renaper` + el ancla CUIL). Recibe los
datos ya normalizados de `services/didit/` (`DatosRenaper`, `ContactosVerificados`); nunca ve el payload crudo.

| Función | Rol |
|---|---|
| `aprobar(*, cliente_id, session_id, datos, contactos=None, conn=None)` | Persiste una verificación **Approved**: `UPDATE clientes` con **COALESCE** de cada `*_renaper` (la única pluma; no pisa con NULL ni con input del usuario) + ancla CUIL (validado mod-11) + `dni_validado_at` + `guardar_contactos_didit` + evento. **Atómico** (`conn.transaction()`). **Guard (2026-08-14):** si `datos.tiene_datos` es `False` (Didit dijo "Approved" pero sin datos del documento — webhook liviano + el fallback a `retrieve_decision` también vino vacío), NO marca `dni_validado_at`/verificado — deja `dni_verificacion_estado='en_revision'` (para que `jobs/recheck_didit_pendientes.py` lo agarre, su query exige ese estado) y registra el evento `'approved_sin_datos'` (no `'approved'`, para no bloquear un reintento futuro con datos reales vía `_ya_registrado`). Devuelve `False`. |
| `actualizar_estado(*, cliente_id, session_id, estado, motivo=None, conn=None)` | Estado intermedio (`rechazado`/`en_revision`) + evento. |
| `registrar_consentimiento(cliente_id, *, conn=None)` | Marca `kyc_consent_at` (el cliente consintió el KYC + el guardado, Ley 25.326). Idempotente. |
| `registrar_evento(conn, cliente_id, evento, detalle=, session_id=)` | Bitácora `kyc_events`. **SOLO texto** (`detalle` = presencia de campos, nunca valores). |

**Defensas (defensa en profundidad sobre el HMAC del webhook):**
- **Scopeo por `session_id`** (`_session_coincide`): el `UPDATE` exige `WHERE id=… AND didit_session_id=…`.
  Si el `session_id` no coincide con el guardado al crear la sesión → no aplica (vendor_data forjado / carrera).
- **Idempotencia** (`_ya_registrado`, keyeada en `(session_id, evento)` sobre `kyc_events`): Didit **re-entrega**
  el webhook (reintenta ante cualquier no-200); sin esto, una 2ª `approved` re-pisaría `dni_validado_at` con un
  timestamp nuevo y duplicaría la fila de auditoría. La bitácora ES la fuente de verdad de "qué ya se ingirió".

**Columnas de identidad = SOLO LECTURA para el usuario.** Las escribe solo `kyc.aprobar`; van a las columnas
`*_renaper` (con COALESCE). El usuario edita apodo/teléfono/avatar/perfil fiscal, **nunca** nombre/DNI/CUIL/dirección.

---

## 5 · Fusión de cuentas (dedup) — `identity/merge.py`

Dos motores de merge, por peso:

| Quién | Qué hace | Cuándo |
|---|---|---|
| `auth/account_merge.py` (Fase 1B) | Absorbe una cuenta **liviana SIN datos** (sin verificar, sin pedidos): mueve sus llaves y la borra. | Auto, al vincular una llave que prueba "misma persona". |
| `identity/merge.py` (Fase 2) | Fusión **PESADA**: ambas cuentas pueden tener pedidos/plata/historia. **Reasigna todas las FKs** de `source` a `target` y borra `source`, transaccional. | **Admin**, tras un diagnóstico — NUNCA auto-merge en migración. |

| Función | Rol |
|---|---|
| `candidatos_duplicados(conn=None)` | Diagnóstico: grupos de cuentas que comparten un CUIL verificado — lo que el índice único va a rechazar. El admin lo usa para encontrar duplicados antes de mergear (y de crear el índice). |
| `merge_accounts(*, source, target, conn=None)` | Reasigna + dedup + borra `source`. **Rehúsa** (`ValueError`) si: `source` verificado y `target` no (perderíamos la identidad RENAPER → mergeá al revés); ambos verificados con CUIL **distinto** (dos personas, no un duplicado); alguna cuenta no existe. `source == target` = no-op. |

**Quién sobrevive:** el **`target`**, con SU identidad intacta. Por eso se rehúsa perder un RENAPER verificado.

**Cobertura de FKs (anti-drift):** TODA columna que referencia `clientes(id)` está clasificada —
`TABLAS_REASIGNADAS` (datos que se mueven: pedidos, listas, contactos, llaves, bitácora, **perfiles
fiscales y membresía de productoras**, 2026-07-05) ∪ `TABLAS_DESCARTADAS`
(efímeras + sesiones que mueren con el `source`: la cookie lleva el id viejo → re-login). El test estático
`test_identity_merge_cobertura` cruza esta clasificación contra `schema.py` y **falla si aparece una FK nueva
sin clasificar**. Las tablas con `UNIQUE` por-cuenta (`verified_contacts`, `login_identities`,
**`cliente_perfiles_fiscales`, `productora_miembros`**) se reasignan **deduplicando** (por CUIT / por
`productora_id`, promoviendo un nuevo default si hace falta — la fila sobrante muere con el `source`).
`account_is_absorbable` suma el chequeo de perfiles fiscales/productoras a "sin datos que perder" — antes
una cuenta liviana vinculada a una productora podía absorberse igual, perdiendo el vínculo en silencio.

---

## 6 · El proveedor Didit — `services/didit/` (aislado)

El boundary del KYC. El payload crudo **muere acá**; `identity/` recibe datos normalizados.

| Pieza | Rol |
|---|---|
| `decision.py` | Parser **puro**: `extraer_datos_renaper(decision)` → `DatosRenaper` (DNI/CUIL/nombre legal/dirección/…); `extraer_contactos(decision)` → `ContactosVerificados` (mail de `email_verifications[]`, teléfono E.164 de `phone_verifications[]`, con `is_disposable`/`is_virtual`/`is_breached`). |
| `webhook.py` | Verifica la firma **HMAC-SHA256** (`X-Signature` sobre el body crudo + freshness por `X-Timestamp`). |
| `client.py` | `retrieve_decision(session_id)` — GET por API (respaldo si el webhook llega 'liviano'; también fuente del re-chequeo admin). |
| `routes/didit.py` | Transporte fino: crea sesión (admin/cliente, guarda `didit_session_id`), recibe el webhook y **delega** en `identity/kyc`. |

**Re-chequeo admin (`POST /api/admin/verificacion/recheck/{cliente_id}`):** para el caso "Didit rechazó
por algo menor (foto oscura) y el admin lo revisó/aprobó a mano *en el dashboard de Didit*, pero ese
cambio no llegó a Rambla" — re-consulta `retrieve_decision(session_id)` (el mismo GET, fuente canónica; el
objeto trae un **`status` top-level** — Approved/Declined/In Review/… — distinto del `id_verifications[].status`
por-feature) y aplica el resultado por la pluma única `identity.kyc.aprobar`/`actualizar_estado`. **Nunca
aprueba a mano**: solo refleja lo que Didit devuelve ahora. 409 si el cliente no tiene ninguna sesión conocida.

**Historial, no solo la sesión actual:** un cliente puede reintentar la verificación varias veces
*mientras* el admin revisa una sesión anterior en el dashboard de Didit — cada reintento pisa
`clientes.didit_session_id` con la sesión nueva, así que la que terminó aprobada deja de ser la "actual".
`_sesiones_conocidas` junta todos los `session_id` con al menos un evento propio en `kyc_events`
(ya scopeado a `cliente_id`) y el recheck los revisa del más reciente al más viejo hasta encontrar una
Aprobada (o se queda con la respuesta de la sesión actual, sin nada mejor que ofrecer). Si la aprobada no
es la que se venía rastreando, el endpoint **mueve el puntero** (`UPDATE clientes SET didit_session_id=…`)
antes de llamar a `kyc.aprobar` — así `_session_coincide` la sigue validando contra ese mismo campo, sin
relajar esa defensa. Una sesión del historial que ya expiró/no existe en Didit (404) no aborta la
búsqueda: se saltea y sigue con las demás.

**El historial depende de que la sesión haya dejado un rastro** en `kyc_events` — y antes solo se
registraba un evento ahí cuando un *webhook* se procesaba (approved/rechazado/en_revision/consent). Una
sesión sin ningún webhook (ni siquiera el inicial) quedaba invisible para `_sesiones_conocidas` aunque
Didit la hubiera decidido — exactamente la falla de origen de todo este endpoint, aplicada también al
registro. Por eso `iniciar_verificacion`/`cliente_iniciar_verificacion` ahora registran un evento
**"iniciado"** (`kyc.registrar_evento(..., session_id=...)`) en el momento mismo de crear la sesión, sin
esperar a ningún webhook. **Override manual** (`POST recheck` con body `{session_id}`): salta la búsqueda
por historial y re-chequea esa sesión puntual directo — para sesiones creadas *antes* del fix de
"iniciado" (o fuera de nuestro flujo) que el historial nunca podría encontrar solo; el admin la pega
copiándola del dashboard de Didit.

**`vendor_data`** (lo que el route pasa a Didit al crear la sesión) = hoy `str(cliente_id)`, protegido por el
**HMAC del webhook + el binding de `session_id`**. El **token opaco server-side** (no el `cliente_id` crudo) es
una mejora de **Fase 3** (la recuperación nuclear lo necesita: ahí no hay `cliente_id` que anclar).

---

## 7 · El flujo end-to-end (verificación al primer pedido)

```
Cliente inicia verificación              Didit                          Webhook → identity
  POST /cliente/verificacion/sesion       DNI + selfie → RENAPER           POST /api/webhooks/didit
   → create_session(vendor_data=id)        verifica identidad               1. verify_webhook (HMAC)
   → guarda clientes.didit_session_id      + mail/teléfono                  2. status=Approved →
   → kyc.registrar_consentimiento          → status.updated (webhook)          extraer_datos_renaper + extraer_contactos
                                                                            3. kyc.aprobar(cliente_id, session_id, datos, contactos)
                                                                                 · _session_coincide  · _ya_registrado (idempotente)
                                                                                 · UPDATE *_renaper (COALESCE) + ancla CUIL + dni_validado_at
                                                                                 · guardar_contactos_didit + registrar_evento
```
A partir de ahí `get_validated_identity` devuelve `estado="verificado"` y la identidad legal; el gate de
pedidos deja pedir; el contrato/remito usan el nombre/dirección de RENAPER.

**Estados de la cuenta:** `liviana` (passwordless, sin datos, inerte) → al verificar, identidad anclada
(`dni_validado_at` + CUIL). Estados de Didit visibles en el portal: `en_revision` / `rechazado` (en
`dni_verificacion_estado`). `conflicto` = dedup pendiente de mano del admin.

---

## Privacidad (Ley 25.326)

- **Nada de biometría guardada.** La foto del DNI nunca llega a nuestra base (Didit la procesa internamente).
- **Solo texto.** `verified_contacts` y `clientes.*_renaper` son texto; `kyc_events.detalle` es **presencia de
  campos (bool)**, nunca valores.
- **Logs por presencia.** Los logs del KYC registran `dni=True cuil=True …`, no los valores. El merge loguea
  `absorbió cliente_id=N` (solo el id).
- **Consentimiento + borrado.** `kyc_consent_at` marca el consentimiento; el cliente puede pedir el borrado.

---

## El porqué (no se duplica acá — se linkea)

- **Frontera auth↔identity / motor único auth** → MEMORIA _2026-06-29 — `backend/auth/` motor único_.
- **Contacto en vivo, plata congelada** (de dónde sale `cliente_nombre`/`direccion`) → MEMORIA _2026-06-06_.
- **Esquema en dos capas** (`init_db` + Alembic) → MEMORIA _2026-06-03_.
- **DAL `%s` / guardas SQL** → MEMORIA _2026-06-27 — DAL wrapper fino_.
- **Cuentas livianas / alta passwordless** → MEMORIA _2026-06-29 — Cuentas livianas_.
- **Merge por link autenticado** (el hermano liviano) → MEMORIA _2026-06-29 — Merge de cuentas por link_.
