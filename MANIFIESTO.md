# Manifiesto — Rambla Rental

> **Contexto del proyecto para Claude.** Acá vive lo que necesita saber para no
> arrancar desde cero: qué es el proyecto, cómo trabajamos, decisiones tomadas.
> No se pega a mano: lo apunta [`CLAUDE.md`](CLAUDE.md) (el front door que Claude Code
> auto-carga al inicio de cada sesión). El supervisor lo lee en su propia ventana.
>
> Si algo cambia (workflow, decisión, herramienta), se actualiza acá. Las **decisiones
> de criterio y preferencias nuevas** van a [`docs/MEMORIA.md`](docs/MEMORIA.md) (memoria
> viva, curada). El [`README.md`](README.md) cubre la cara de GitHub (setup, stack, links).

---

## 1. Qué es el proyecto

**Rambla Rental** — plataforma de alquiler de equipos audiovisuales.

3 superficies:

- **Catálogo público** (`/`) — clientes ven equipos, arman cotización.
- **Portal cliente** (`/cliente/*`) — login, ver mis pedidos, perfil.
- **Back-office admin** (`/admin/*`) — gestión total: equipos, pedidos, clientes, mantenimiento, dashboard de uso, etc.

Un único dueño/operador maneja el back-office. Inventario chico-mediano (cientos de equipos), volumen de alquileres mensual moderado.

### Líneas de negocio (todas en el mismo pedido)

3 líneas de negocio conviven en la misma tabla `alquileres` — **un pedido, no un sistema por línea**
(decisión _2026-05-27 — El Estudio: producto aparte que reusa el motor de reservas_, extendida a Talleres):

- **Rental** (`tipo='diaria'`) — alquiler de equipos por jornada. La línea original.
- **Estudio** (`tipo='estudio'` / `'estudio_fijo'`) — alquiler del espacio físico por franja horaria
  (turno puntual o slot fijo recurrente), con o sin equipos sueltos. Motor →
  `backend/services/estudio/` ([`CLAUDE.md`](backend/services/estudio/CLAUDE.md)).
- **Talleres** (`tipo='taller'`) — cursos con clases fechadas; el pedido es un **resumen contable
  mensual** de la edición, no un evento puntual. Motor → `backend/services/talleres/`
  ([`CLAUDE.md`](backend/services/talleres/CLAUDE.md)).

Qué significan las fechas de cada tipo, qué se edita dónde, y por qué "un pedido con 4 significados
de fecha" es a propósito y no drift → [`docs/FLUJO_PEDIDOS.md`](docs/FLUJO_PEDIDOS.md) §5 "Familias
de pedido" (fuente única del predicado: `backend/tipos_pedido.py`).

---

## 2. Stack

| Capa | Tech |
|---|---|
| Frontend | React 19 + Vite + TanStack Router (file-based) + TanStack Query + Tailwind v4 + shadcn/Radix UI |
| Backend | FastAPI + psycopg (psycopg3 sync) + PostgreSQL (pool de conexiones) |
| Auth | Google OAuth via Supabase Auth (admin + portal cliente) |
| Storage | Cloudflare R2 (S3-compatible) para fotos |
| Drag-and-drop | `@dnd-kit/*` |
| Form state | `react-hook-form` + `zod` para validación |
| Deploy | Railway (backend + frontend en un mismo servicio Docker) |

Detalles de setup en [`README.md`](README.md). Detalles de Railway en [`docs/DEPLOY_RAILWAY.md`](docs/DEPLOY_RAILWAY.md).

---

## 3. Cómo trabajamos

### Workflow

**Fuente única:** todo el flujo de cambios —routing por riesgo, `dev` = staging, quién mergea, los gates del dueño, métodos de merge— está definido en **una sola decisión**: `docs/MEMORIA.md` → _2026-06-08 — Workflow de cambios_ (con el _por qué_ en `docs/DECISIONES.md`). **No se repite acá.** Lo de abajo es solo el detalle de convención (nombres de rama, tipos de commit, formato de PR) que esa decisión usa.

```
Edit → verificar → (lo chico: push directo a `dev`=staging) | (lo grande/sensible: rama + PR → supervisor + CI → merge a `dev`) → el dueño prueba en staging → PR `dev → main` (su gate a prod)
```

**La memoria del proyecto vive en capas** (detalle en §8):

- **[`docs/MEMORIA.md`](docs/MEMORIA.md)** — decisiones de criterio + preferencias, **digest enforceable** (la regla de cada una, auto-cargado). Lo que el supervisor hace cumplir. El **_por qué_ completo** (el desarrollo ADR) vive en [`docs/DECISIONES.md`](docs/DECISIONES.md), on-demand, bajo el mismo `fecha — título`.
- **Commit history** — registro de cambios. Conventional Commits en español; `git log --grep="^fix"` / `"^feat"` son el log buscable.
- **GitHub Issues** — trabajo pendiente (la cola). No es obligatorio por commit.

### Modus operandi durable, sesión efímera

El **cómo se trabaja acá** es durable y vive en estos docs + `docs/MEMORIA.md`. La sesión es efímera: carga la forma establecida vía `CLAUDE.md` y **ejecuta**. No re-discute el modus operandi.

El **plan de una tarea** depende del alcance:

- **Cabe en una sesión** → se planea en la sesión (plan mode) y se ejecuta. No necesita persistencia.
- **Iniciativa que cruza varias sesiones** → un **issue de tracking por iniciativa** (con checklist de fases adentro — **NO un issue por fase**), **auto-mantenido por la sesión** que ejecuta (marca fases hechas, anota desvíos). Así una sesión nueva la retoma sin perder contexto. El supervisor verifica que esté actualizado antes de mergear.

### Una iniciativa = una rama = una PR

**Default**: el trabajo de una iniciativa entera (aunque tenga N fases / N issues) va en **una sola rama con N commits adentro**, y se mergea como **una sola PR** que cierra todos los issues con varios `Closes #N`.

Por qué: minimiza el costo de review + merge + deploy. Una iniciativa = 1 review, 1 merge, 1 deploy — no N.

Cada commit dentro de la rama es atómico y revertible. La PR los publica en bloque.

Esto aplica a **lo grande** (iniciativas). Lo **chico y aislado** (typo, label puntual, fix acotado) no lleva rama ni PR: va **directo a `dev`** según el routing por riesgo de la decisión _Workflow de cambios_.

### Branches

- `main` — siempre estable, deployable.
- `claude/<descripcion>` — una rama por **iniciativa** (no por fase / no por commit). Múltiples commits dentro.

Después de mergear: **borrar la branch local** (`git branch -d`) **y remota** (`git push origin --delete`). Sin colgadas.

### Commits

Estilo `tipo(scope): descripción en español, lowercase, sin punto final`.

Tipos: `feat`, `fix`, `refactor`, `chore`, `docs`, `perf`, `test`.

Body explica el **por qué**, no el **qué**. Bullets si hay varios efectos.

### PRs

- Título: igual al commit principal.
- Body: 3 secciones — Summary / Cambios / **Test plan en lenguaje claro** (el dueño testea, no lee código: "andá a /X, hacé Y, tenés que ver Z").
- Si la iniciativa tiene issue de tracking: linkear con `Closes #N`.
- **CI verde antes de mergear** (TypeScript typecheck, Python tests, Build frontend, mobile-smoke). La sesión **no propone merge con CI en rojo**.
- **Antes de abrir/mergear: despachar el agente `supervisor`** — revisión read-only de scope / forma / drift, que resume en claro y deja el plan de prueba. (Instrucción, no gate de sistema: en las apps no hay hooks.)
- **Quién mergea y cuándo** (la sesión a `dev`, los gates del dueño, auto-merge, opt-out): definido en la decisión _Workflow de cambios_ del digest. No se repite acá.
- Conflicts con main: rebase / merge desde el branch (no force-push a main).

El método de mantenimiento (auditar/fixear/commits/PR) vive en el skill [`mantenimiento`](.claude/skills/mantenimiento/SKILL.md); el **mobile gate** + la rúbrica de auditoría, en [`docs/PROTOCOLO.md`](docs/PROTOCOLO.md).

### Issues — labels

**Cada issue se etiqueta en 3 dimensiones** + opcionales cross-cutting. Sin las 3 dimensiones la issue queda incompleta y no se prioriza.

1. **Tipo** (1, obligatoria): `bug` / `feature` / `design` / `refactor` / `documentation` / `security`.
2. **Prioridad** (1, obligatoria): `priority:critical` / `priority:high` / `priority:medium` / `priority:low`.
3. **Complejidad** (1, obligatoria): `complexity:trivial` / `complexity:small` / `complexity:medium` / `complexity:large` / `complexity:epic`.

**Cross-cutting** (0+, opcionales): `mobile`, `dx`, `infrastructure`, `performance`, `launch-blocker`, `backend`, `admin`.

Regla del `mobile`: aplicar **además** del tipo, no en lugar de. Aplica si la issue afecta rutas cliente o admin prioritario (`/admin/pedidos`, `/admin/dashboard`). Resto del admin = desktop-first.

Convención completa + cómo elegir issues por capacidad de la sesión en [`docs/ISSUE_LABELS.md`](docs/ISSUE_LABELS.md).

**Al crear un issue nuevo**: aplicar las 3 dimensiones siempre. Si no estás seguro de la prioridad, `priority:medium`. Si no estás seguro de la complejidad, mirar el body — > 1 día = `complexity:medium`, sino `complexity:small`.

### Mobile como criterio

**Cada ruta debe tener un layout mobile pensado a propósito, no solo un escalado responsive automático.** No alcanza con "se ve más o menos OK en celu" — necesitamos un patrón visible (dual render `md:hidden`/`hidden md:block`, sticky bar, sheet fullscreen, lista card-based) y validación manual en viewport 375×667 (iPhone SE).

Gate de merge: cualquier PR que toque rutas de cliente (`/`, `/equipo/*`, `/cliente/*`, `/estudio`) o admin prioritario (`/admin/pedidos`, `/admin/dashboard`) requiere mobile pass antes de mergear.

El wrapper [`<PublicLayout>`](src/components/rental/PublicLayout.tsx) provee TopBar + Footer mobile-aware, pero **no garantiza el criterio** — el contenido de cada ruta tiene que cumplirlo por su cuenta.

Definición completa del criterio, checklist y status por ruta en [`docs/MOBILE_AUDIT.md`](docs/MOBILE_AUDIT.md). Procedimiento en [`docs/PROTOCOLO.md`](docs/PROTOCOLO.md).

### Iterar local con datos reales

**Para iterar UI o flujos que necesitan sesión / datos reales (portal cliente, back-office, cualquier cosa con assets del admin), no alcanza con los fixtures.** Los bugs de theming/datos no aparecen con mocks — el wordmark custom del admin se veía amber sobre los topbars de color en staging/prod pero nunca con el SVG bundleado local. El **loop render-compare se valida con datos/assets reales**, no solo mocks.

Montaje del entorno local con datos reales:
1. **Backend local** — `uvicorn main:app --port 8000` con un `.env` (gitignored): `SECRET_KEY`, `STAGING_LOGIN_SECRET`, `DATABASE_URL` apuntando a tu **Postgres local**.
2. **BD de staging clonada a local** — `pg_dump` **read-only** de la base de staging → restore en tu Postgres local (cuidar versiones de pg). **Nunca** apuntes el backend local a la base remota: `init_db()` corre al startup y le escribiría el esquema, y es PII real. El clon es solo lectura sobre la remota.
3. **Login programático** — `POST /auth/staging-login {secret, target:"cliente"|"admin"}` mintea la cookie; el cliente se resuelve por `STAGING_CLIENTE_EMAIL` o un `cliente_id`. Desde el navegador en `localhost:3000` (así guarda la cookie HttpOnly del proxy).

Setup detallado en [`docs/DEPLOY_RAILWAY.md`](docs/DEPLOY_RAILWAY.md). Regla viva: _Iteración local con datos reales (2026-06-20)_ en [`docs/MEMORIA.md`](docs/MEMORIA.md).

---

## 4. Glossary

Cuatro nociones que se cruzan a lo largo del producto. Distinguirlas evita confusión:

- **Categoría** — árbol jerárquico de hasta 3 niveles (ej. Cámara → Cinema → FX3). Cada equipo pertenece a una o más. Determina el filtro principal del catálogo público y dispara el spec template + plantilla de nombre.
- **Etiqueta** — tag libre, plano (sin jerarquía). Atraviesa categorías (ej. "Sony E mount" puede aplicar a cámaras y a lentes). Filtro secundario.
- **Spec** — fila clave-valor adjunta a un equipo (`Sensor: Full Frame`). Lo técnico que se ve en la ficha. Tipo `text` o `number` (con unidad).
- **Spec Template** — norma de specs **por categoría**. Define qué labels deben existir en cada equipo de esa categoría, en qué orden, con qué tipo y unidad. Heredan automáticamente al crear un equipo nuevo. "AI sugiere, humano cura" → el autocompletar respeta el template como hint.

---

## 5. Mapa del código

Puntos de entrada para no grepear:

| Qué | Dónde |
|---|---|
| Rutas frontend (file-based) | `src/routes/` |
| Componentes admin | `src/components/admin/` |
| Form de equipos | `src/components/admin/equipo-form/` |
| Lógica reusable / utilities UI | `src/lib/` |
| Endpoints backend | `backend/routes/` (`equipos.py`, `clientes.py`, `dashboard.py`, etc.) |
| **Motor de reservas (sagrado)** | `backend/reservas/` (`estados.py`, `semantics.py`, `disponibilidad.py`, `gate.py`) — disponibilidad + gate `_check_stock`. Ver MEMORIA 2026-05-30 |
| Familias de pedido (fuente única) | `backend/tipos_pedido.py` — `TIPOS_DERIVADOS`/`TIPOS_SIN_RETIRO`, predicados `es_pedido_derivado()`/`es_pedido_taller()`; espejo `frontend/src/lib/tipos-pedido.ts` |
| Motor de pedidos | `backend/services/alquileres/` (`queries/`+`commands/`) — crear, editar ítems/datos, cotizar, pagar, transicionar de estado, documentos. `routes/alquileres/` es puro transporte/re-export. Ver su `CLAUDE.md` |
| Motor del Estudio | `backend/services/estudio/` (`queries/`+`commands/`) — disponibilidad, promo, reserva. Ver su `CLAUDE.md` |
| Motor de Talleres | `backend/services/talleres/` (`queries/`+`commands/`) — gate de conflicto con Estudio, economía. Ver su `CLAUDE.md` |
| Configuración (Settings) | `backend/config.py` (fuente de `ADMIN_EMAILS`, etc.) |
| Procesamiento/upload de imágenes + anti-SSRF | `backend/services/image_upload.py` |
| Schema base + pool DB | `backend/database.py` |
| Schema de specs / categorías | `backend/specs/` (`__init__.py` define `REGISTRY`; una cat por archivo en `categorias/`) |
| Migrations Alembic | `backend/migrations/versions/` |
| Auth admin | `backend/admin_guard.py` |
| Auth cliente | `backend/routes/auth.py` |

---

## 6. Decisiones del proyecto

> Lecciones aprendidas y elecciones arquitectónicas. Útil para no re-discutir cosas.
>
> **Baseline fundacional.** Estas son las decisiones de arquitectura que vinieron con el
> proyecto. Las **decisiones nuevas y preferencias** van a [`docs/MEMORIA.md`](docs/MEMORIA.md)
> (fechadas, curadas) — no se agregan acá. El supervisor lee ambos.
>
> **Pre-lanzamiento (con disparador):** la web aún no es pública; el dueño es el único usuario
> de prueba, así que **probar en producción está OK** (no hay clientes que se crucen algo roto).
> **Disparador:** al salir al público, esto se vence → recién ahí hace falta preview/staging y
> dejar de probar en prod. El supervisor avisa al acercarse el lanzamiento. (Registrada en
> `docs/MEMORIA.md`.)

### Auth

- **Admin**: Google OAuth → sesión cookie firmada. `require_admin(request)` en cada endpoint admin.
- **Cliente**: Google OAuth separado → cookie `cliente_session` distinta. `require_cliente(request)` valida `role: "cliente"` (no acepta sesiones admin).
- **Dev mode**: `ADMIN_BYPASS_AUTH=1` en `.env.local` saltea la validación. Lo usan los tests E2E (con `PLAYWRIGHT_ADMIN=1`).

### Base de datos

- **Postgres puro** (migró de SQLite). El wrapper `PGConnection`/`PGCursor` es el DAL único: pool, rollback-al-devolver, y el chokepoint de guardas SQL mecánicas (`_assert_pct_safe` + `_assert_params_present`). Paramstyle: `%s` nativo de psycopg3 (la traducción `?`→`%s` fue retirada en Fase 6 de la migración).
- **Migraciones**: dos capas. (1) schema base con `CREATE IF NOT EXISTS` en `backend/database.py::init_db()` (idempotente, corre en cada arranque — es el bootstrap real). (2) cambios incrementales con Alembic (`backend/migrations/versions/`). Si el `upgrade head` del arranque falla, se loguea y la app sigue → puede quedar **drift silencioso** (BD trabada en una revisión vieja). **Convención: toda tabla/columna nueva va TAMBIÉN en `init_db()`** (no solo en una migración). Visibilidad en `GET /health/migrations`; modelo + runbook de reparación en [`docs/RUNBOOK_MIGRACIONES.md`](docs/RUNBOOK_MIGRACIONES.md).
- **Soft delete**: equipos tienen `eliminado_at TIMESTAMP NULL`. Las listas filtran `IS NULL` por default. Endpoint `POST /equipos/:id/restore`. Vista "papelera" en lista admin. Bulk delete en papelera = hard delete (action `delete_permanent`).

### Storage de fotos

- Vive en `backend/services/image_upload.py` (extraído de `routes/equipos.py` en #501 Fase 3; lo reusan equipos/marcas/estudio/settings).
- R2 (S3-compatible). Cada foto se sube con upload server-side desde una URL externa o un archivo local.
- Allowlist anti-SSRF para URLs externas (`_validate_external_image_url`). Hosts conocidos (B&H, Adorama, manufacturer domains, CDNs).
- Las fotos se procesan con `_optimize_image`: auto-crop de whitespace, padding 6%, resize a 1200×1200, ratio cuadrado.

### Form de equipos

- **EquipoFormDialog** es EL form (único — el sufijo "V2" se retiró el 2026-07-09; el form original que lo justificaba se había borrado en mayo, no resucitar). Sin tabs, scroll lineal con secciones colapsables. Mismo flow CREATE / EDIT.

### Sistema de specs / catálogo / datasets / autocompletar / compatibilidad

El detalle técnico de todo esto vive en **[`docs/SISTEMA_SPECS.md`](docs/SISTEMA_SPECS.md)**:
autocompletar (admin, por equipo), carga de datasets por categoría (seed bulk), motor de
compatibilidades cross-categoría, display templates de nombres, y los workflows para agregar
specs / sub-categorías. La fuente de verdad del schema es `backend/specs/__init__.py` (`REGISTRY`).

### Bulk actions en lista admin

- En vista normal: las bulk actions son soft (`delete` → marca `eliminado_at`).
- En vista papelera: `delete_permanent` hace hard delete. Es la única forma de borrar irreversible.

### Búsqueda fuzzy

- El parámetro `q` en `GET /equipos` busca en `nombre`, `marca`, `modelo`, `serie`, `descripcion`, `specs_json`, `keywords_json`. Aplicable a admin lista y catálogo público.
- Limitación: LIKE crudo sobre JSON → posibles falsos positivos si buscás field names tipo "label" o "value". Aceptable para inventario chico-mediano.

### Mantenimiento

- Log por equipo (`equipo_mantenimiento`) con tipo, costo y `proxima_revision`. Vencidas se marcan visualmente en la lista admin.

### Dashboard de uso

- Dialog desde la lista admin, no ruta separada — evita ediciones de `routeTree.gen.ts` auto-generado.
- "Por cobrar" excluye `cancelado` y `borrador`. Solo cuenta pedidos con compromiso real de pago.

### Naming conventions

- **Frontend**: ya migró a "autocompletar" como nombre del feature.
- **Backend**: endpoints canónicos `/autocompletar`. Los viejos `/enriquecer` quedan como aliases deprecated.
- **Nombres de funciones internas** (`aplicarEnriquecimiento`, `admin_enriquecer_equipo`, `EnriquecerInput`) siguen con el nombre viejo — rename completo es un follow-up cuando duela.
- **Columna DB `roi_pct`**: nombre técnicamente incorrecto. El valor es "% del valor del equipo cobrado por día" (tarifa diaria). **Label canónico en UI**: `% día` (decisión cerrada — #262). La columna DB sigue como `roi_pct` por costo de migración vs valor — solo lo ve dev en queries. El admin ve "% día".

---

## 7. Sistema de specs (manual técnico)

Movido a **[`docs/SISTEMA_SPECS.md`](docs/SISTEMA_SPECS.md)** — el registry como fuente única del
schema, specs por categoría, sub-categorías, keywords automáticas, merge dataset↔DB y el flow
operativo. Reemplaza al borrador histórico (ahora en `docs/archive/DISEÑO_SPECS.md`).

---

## 8. Dónde encontrar cosas

### Memoria en capas — cada cosa en su lugar

La memoria está separada por propósito (no se duplica):

| Querés saber… | Dónde |
|---|---|
| **Por qué decidimos algo / cómo quiere el dueño que se hagan las cosas** | [`docs/MEMORIA.md`](docs/MEMORIA.md) — digest enforceable de decisiones + preferencias (la regla de cada una). El *por qué* completo → [`docs/DECISIONES.md`](docs/DECISIONES.md). Curado y fechado. **El supervisor lo hace cumplir.** |
| Decisiones de arquitectura fundacionales | §6 de este manifiesto (baseline congelado) |
| Qué hay pendiente / en curso | GitHub Issues (la cola). `gh issue list` localmente, o las tools de GitHub en la nube |
| Qué cambió y cuándo | Commit history (`git log --grep="^feat"` / `"^fix"`) |

Regla: **trabajo pendiente** → Issues. **Registro de cambios** → commits/PRs. **Las reglas de criterio
y preferencias** → `docs/MEMORIA.md` (digest, auto-cargado); **su *por qué* completo** → `docs/DECISIONES.md`
(on-demand). Curado, no exhaustivo: solo lo que tiene consecuencia duradera o se repite. Si una
funcionalidad existe en código y no está trackeada, crear el issue.
Histórico: `docs/archive/` conserva auditorías viejas (`BUGS.md`, `MEJORAS.md`).

### Docs auxiliares

| Archivo | Cuándo |
|---|---|
| [`docs/MEMORIA.md`](docs/MEMORIA.md) | Digest enforceable de decisiones + preferencias (memoria viva, curada; auto-cargado) |
| [`docs/DECISIONES.md`](docs/DECISIONES.md) | Log ADR completo: el *por qué* de cada decisión (on-demand) |
| [`docs/PROTOCOLO.md`](docs/PROTOCOLO.md) | Rúbrica de auditoría + mobile gate (método de mantenimiento → skill `mantenimiento`) |
| [`docs/DEPLOY_RAILWAY.md`](docs/DEPLOY_RAILWAY.md) | Deploy y rollback |
| [`docs/SISTEMA_SPECS.md`](docs/SISTEMA_SPECS.md) | **Manual técnico del sistema de specs / catálogo / datasets / autocompletar / compat** |
| [`docs/SISTEMA_FACTURACION.md`](docs/SISTEMA_FACTURACION.md) | **Manual técnico del sistema de facturación electrónica ARCA** |
| [`docs/SISTEMA_FOTOS.md`](docs/SISTEMA_FOTOS.md) | **Manual técnico del sistema de fotos / media: motor (procesar) + componentes (mostrar)** |
| [`docs/SISTEMA_CONTENIDO.md`](docs/SISTEMA_CONTENIDO.md) | **Manual técnico del contenido de producto: puerta única "qué incluye un kit/combo" (`services/contenido`)** |
| [`docs/SISTEMA_CARRITO.md`](docs/SISTEMA_CARRITO.md) | **Manual técnico del carrito: módulo único de la lógica (`services/carrito`) — selección / activos / readiness; carrito = intención, gate = verdad** |
| [`docs/SISTEMA_AUTH.md`](docs/SISTEMA_AUTH.md) | **Manual técnico de la autenticación: motor `auth/` (sesión + jti/revocación), métodos (Google/passkey/staging), guards, middleware, seguridad** |
| [`docs/SISTEMA_IDENTITY.md`](docs/SISTEMA_IDENTITY.md) | **Manual técnico de la identidad: motor `identity/` (ancla CUIL, KYC sobre Didit, contactos verificados, lector único `get_validated_identity`, dedup/merge)** |
| [`docs/SISTEMA_FINANZAS_FLUJO.md`](docs/SISTEMA_FINANZAS_FLUJO.md) | **Manual cruzado de plata + módulo orquestador `services/finanzas_flujo/`: fuente única de cada número entre precios/reservas/pagos/liquidación/contabilidad/facturación + el semáforo de reconciliación** |
| [`docs/FLUJO_PEDIDOS.md`](docs/FLUJO_PEDIDOS.md) | Recorrido del pedido: estados, confirmación visible, mails, `id` vs `numero_pedido` |
| [`docs/MOBILE.md`](docs/MOBILE.md) | Componentes y patrones mobile |
| [`docs/MOBILE_AUDIT.md`](docs/MOBILE_AUDIT.md) | Criterio mobile + checklist + status por ruta |
| [`docs/DATASET_ILUMINACION.md`](docs/DATASET_ILUMINACION.md) | Dataset curado de luces + workflow seed por categoría |
| [`docs/ISSUE_LABELS.md`](docs/ISSUE_LABELS.md) | Convención de labels |

### Cosas que NO existen todavía

Aclaración para no buscarlas en vano: pagos online (Stripe/MercadoPago), multi-tenant, dark mode, app mobile nativa.

Las **notificaciones por email** sí están **construidas** (`backend/services/email/`, plantillas editables en `/admin/email-templates`) pero **no activadas** — caen al backend `test` hasta configurar el proveedor (`RESEND_API_KEY`/`SMTP_*`). Ver [`docs/FLUJO_PEDIDOS.md`](docs/FLUJO_PEDIDOS.md) §3.

### Sesión nueva pierde el rumbo

Si Claude se pierde a mitad de sesión: `Releé CLAUDE.md, MANIFIESTO.md, docs/MEMORIA.md y los issues abiertos en https://github.com/tixenre/rental/issues`.
