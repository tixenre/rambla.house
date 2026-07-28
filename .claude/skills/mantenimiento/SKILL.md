---
name: mantenimiento
model: opus
last-reviewed: 2026-07-26
version: 1.0
description: El go-to para AUDITAR y MEJORAR el repo sin romper nada. Flujo completo de salud del repositorio — diagnosticar (rúbrica de calidad) → rutear por riesgo → ejecutar en 5 frentes con la misma disciplina — (A) código muerto/imports/archivos/deps/DRY/optimizar; (B) seguridad + bugs; (C) ramas; (D) issues; (E) modularización / split de god-modules (move-verbatim, gateado). Úsalo cuando el dueño pida "auditá", "mejorá el repo", "está bien hecho?", "es profesional?", "hay deuda?", "limpiá / housekeeping", "sacá lo que no se usa", "código muerto", "hay legacy", "revisá seguridad/bugs", "está todo seguro?", "limpiá ramas", "ordená los issues", "modularizá / partí ese god-module", o cuando detectes cruft/drift mientras trabajás. El corazón NO es una lista de ítems, sino el MÉTODO seguro: diagnosticar con rúbrica → verificar antes de ACTUAR (borrar/cerrar/afirmar — las herramientas Y la intuición mienten) → red de tests → no perder tracking → commits atómicos → supervisor. Los cortes grandes (Frente E, core sagrado) NO son barridos rápidos: van como iniciativa gateada, UNA PR por corte.
---

# mantenimiento — auditar y mejorar el repo, sin romper nada

Codifica **cómo** se mantiene Rambla sano y se sube su calidad: no la lista de lo ya hecho, sino la
**lógica, el cuidado y los tests** para que cada pasada futura sea segura. Materializa la _Barra de
calidad_ (MEMORIA *2026-05-25*): modularidad a prueba de balas, nada de hotfixes, y **el core de
reservas es sagrado**.

## El flujo: diagnosticar → rutear → ejecutar

1. **DIAGNOSTICAR (read-only).** Antes de tocar, mapear la deuda con la **rúbrica de auditoría**
   (ejes A-O + scorecard + método de dispatch en paralelo) que vive en
   [`docs/PROTOCOLO.md`](../../../docs/PROTOCOLO.md). La rúbrica es _el qué mirar_; este skill es _el
   cómo arreglar sin romper_. El diagnóstico produce hallazgos `archivo:línea / eje / severidad /
   propuesta` — esa es la entrada de los frentes de abajo.
2. **RUTEAR por riesgo.** Cada hallazgo se clasifica (tabla de la fase 4): borrado puro / refactor
   DRY / cambio de conducta / **core sagrado o split grande**. El cuidado es proporcional al radio
   de explosión.
3. **EJECUTAR por frente**, cada uno con su método + red de tests:

| Frente | Qué barre | Acción que arriesga | Verificación antes de actuar |
|---|---|---|---|
| **A · Código** | muerto / imports / archivos / deps / DRY / optimizar | borrar | grep repo-wide + suite verde |
| **B · Seguridad + bugs** | authz/IDOR, injection, SSRF/XSS, overlap de reservas, plata | afirmar "está OK" / parchar | reproducir el exploit + test de regresión |
| **C · Ramas** | ramas que no son `dev`/`main` ya mergeadas | borrar la rama | confirmar que su PR está mergeado |
| **D · Issues** | triagear, cerrar lo hecho, consolidar trackers/umbrellas | cerrar el issue | evidencia (PR/commit) de que está hecho |
| **E · Modularización** | partir god-modules en paquetes de concerns (move-verbatim) | mover/romper la superficie pública | set de rutas idéntico + suite + gate test, **1 PR por corte** |

**CIERRE (todos los frentes):** commits atómicos + body con "lo que se dejó" → **supervisor** → plan
de prueba en lenguaje claro para el dueño (que prueba en staging).

> ## Regla de oro (vale para los 5 frentes)
>
> **Verificá antes de ACTUAR — y "actuar" es borrar, cerrar, afirmar o mover.** Esas acciones son
> irreversibles en la práctica (un issue cerrado se entierra, una rama borrada se olvida, un "está
> todo seguro" tranquiliza de más, una ruta movida-mal rompe en silencio). Nada se ejecuta sin
> evidencia: las **herramientas dan candidatos, nunca sentencias** (knip/ruff/vulture mienten); **la
> intuición del dueño también se equivoca** ("casi todos los issues se pueden cerrar" → varios eran
> backlog real; "¿está todo seguro?" → había un agujero de authz crítico). El gate del dueño es
> *probar en staging*, no leer diffs → **"no romper nada / no enterrar nada" pesa más que "cuánto
> mejoramos"**. Ante la duda, se **deja, se deja abierto y se reporta** — nunca se borra/cierra/mueve
> a ciegas. **Honestidad > actividad:** si está limpio, la respuesta correcta es decirlo, no fabricar
> churn.

Casos testigo (de por qué la regla existe):

- **knip mintió:** marcó `categories`/`brands` como exports sin usar — tienen **30+ usos reales**; y
  `trackEvent` (uso dinámico desde cart-store/orders).
- **ruff mintió:** marcó `reservas.ESTADOS_RESERVADO` en `routes/alquileres.py` como import sin usar
  → es un **re-export canónico que un test exige** (`test_reservas_sql_safety`). Lo cazó el suite.
- **La intuición mintió:** "casi todos los issues se pueden cerrar" — al triagear con evidencia,
  varios eran trabajo pendiente real (ej. #476, lint promovible a bloqueante) → se dejaron abiertos.
- **El "todo OK" mintió:** ante "¿está todo seguro?", la auditoría destapó **escrituras de `/api/equipos`
  sin `require_admin`** (cualquier anónimo creaba/borraba equipos) → fix #795. No era cosmético. Y la
  variante sutil: un `require_admin` **local** que solo chequea sesión (no `is_admin_email`) →
  escalada cliente→admin (specs/settings/calendar/unidades). El guard tiene que ser el de `admin_guard`.

La moraleja: la herramienta (o la corazonada) arranca el trabajo, **el suite, el grep y la evidencia
lo terminan**.

---

## Frente A — Código (el método, 6 fases)

### 1 · Inventario con herramientas (no grep ciego)

`ruff` ya corre pineado como gate de CI (job "Python lint + syntax", `backend/ruff.toml`) — pero **solo
con el ruleset conservador de ese gate** (bugs/imports, no las reglas F401/F811/F841 completas que usa
este barrido); `vulture`/`knip` no corren solos → se instalan para el barrido. Dan una **lista de
candidatos**.

| Capa | Herramienta | Qué caza | Comando |
|---|---|---|---|
| Backend (Python) | **ruff** | imports / redefiniciones / variables sin usar | `ruff check . --select F401,F811,F841 --no-cache --exclude "migrations,tests"` |
| Backend (Python) | **vulture** | funciones / clases / atributos muertos | `vulture . --min-confidence 80 --exclude "tests/,migrations/"` |
| Frontend (TS/TSX) | **knip** | archivos, exports y dependencias sin usar | `npx --yes knip --no-progress` |

```bash
# Setup del barrido (efímero, no se commitea):
python -m venv /tmp/venv && . /tmp/venv/bin/activate
pip install -q -r backend/requirements-dev.txt vulture ruff
# (knip se baja con npx; el front necesita `npm ci` para tsc/eslint/build)
# ruff/vulture NO están pineados: una versión nueva puede traer reglas distintas →
# si querés reproducir un barrido viejo, fijá la versión (ruff==X, vulture==Y).
```

> **`migrations/` se excluye SIEMPRE.** Es historia congelada (decisión _esquema en dos capas_,
> MEMORIA *2026-06-03*); sus "imports sin usar" (`op`, `sa`) son convención de Alembic, no cruft.

> **vulture: quedate en `--min-confidence 80`.** A 60 **inunda** de falsos positivos: marca todos
> los handlers de ruta FastAPI y los validators Pydantic (no ve los decoradores). Más ruido que señal.

> **No confíes en RUF100** ("unused noqa directive") corriendo ruff **ad-hoc**: como el repo no tiene
> config de ruff, RUF100 marca como "sin usar" `# noqa` que SÍ hacen falta cuando se corre el ruleset
> real (`E402` de scripts con path-setup antes del import, `E501`, y los `# noqa: F401` que protegen
> re-exports como `ESTADOS_RESERVADO`). **No saques noqas** basándote en un run ad-hoc.

> **Señales extra de ruff** (corré `--select F` para verlas además de las tres de arriba): **F541**
> (f-string sin placeholder) = micro-limpieza segura (`--fix`). **F601** (clave de dict repetida) =
> **bug smell, NO limpieza**: si los dos valores **coinciden** es una dup inocua (cleanup); si
> **difieren** es un bug de conducta (una clave pisa a la otra) → **reportar**, no "arreglar" a
> ciegas. Caso testigo: `"lens mount"` mapeaba a `"Montura"` y una dup lo pisaba con `"Lens mount"`
> (inglés sin traducir) — la "limpieza" de la dup es en realidad una decisión de qué label se muestra.

> **Ángulos extra cuando las herramientas principales ya no encuentran nada:** (1) **comentarios
> huérfanos** — tras una tanda de borrados, grepeá los símbolos eliminados en comentarios (`grep -rn
> WhatsappPill`) y actualizalos (caso testigo: un docstring seguía nombrando `WhatsappPill` ya borrado);
> (2) **código duplicado** con `npx jscpd src backend --min-tokens 80 --min-lines 15` → un % bajo
> (≤0.5) es sano; solo vale extraer un clon **grande e idéntico** (refactor DRY, no borrado). Cuando
> estos ángulos tampoco dan nada, el repo está limpio: **parar es la respuesta correcta**, no forzar.

### 2 · Triage — separar muerto real de falso positivo

Por cada candidato, preguntarse **por qué la herramienta lo marcó** y si es legítimo. Falsos
positivos típicos (**NO borrar**):

- **Re-exports** intencionales: barrels (`index.ts`), `__all__`, constantes canónicas re-expuestas.
  Si un **test** los exige, se conservan con `# noqa: F401` + comentario que apunte al test.
- **Uso dinámico / por string:** eventos de analytics, registries, factories, rutas lazy.
- **Funciones registradas por decorador:** las herramientas Python NO ven los decoradores → marcan
  como muertos los **handlers de ruta** (`@router.get`/`@app.get`) y los **validators Pydantic**
  (`@field_validator`/`@classmethod`). Es la fuente #1 de falsos positivos de vulture. Un handler,
  además, puede ser consumido por el front por **string de URL** (`fetch('/api/...')`) → grepear la
  **ruta** (`/api/...`) en el front, no el nombre de la función.
- **`__init__.py` vacíos:** son markers de paquete obligatorios, no archivos a borrar.
- **Helper que se autodescribe "fuente única"/canónico pero con 0 consumidores** (caso testigo:
  `pdf._a4_page`): es la baranda del barrel a menor escala → **reportar**, no borrar (suele ser
  intención sin cablear; borrarlo pierde el diseño, cablearlo es un refactor aparte).
- **Miembro suelto de una API simétrica / compound-component / toolkit curado:** un export sin usar
  que es parte de una familia coherente cuya mayoría sí se usa → dejar (borrar el miembro suelto
  rompe la simetría y empeora la legibilidad). Casos testigo: `refresh`/`refresh_equipos` en la
  familia `refresh_*`; `AdminCardActions` en el compound `AdminCard.*` (Header/Meta/Footer/Price/
  Actions); `PageHeader` en el barrel de primitivos mobile (`components/mobile/`: FAB, BottomSheet,
  ActionMenu…). Si dudás si es toolkit deliberado o muerto → **reportar**, no borrar.
- **Export con marcador de intención:** un `// eslint-disable-next-line react-refresh/only-export-components`
  con comentario ("a propósito", "coexiste con el componente") marca un export **deliberado** → dejar
  (casos testigo: `PLANTILLAS_MAIL`, `Illustrations`). El marcador ES la decisión registrada en el código.
- **Assets referenciados por string:** imágenes/íconos/templates cargados por path armado en runtime
  (no `import` estático) → knip no los ve. Grepear el nombre del archivo en TODO el repo. Y ojo: un
  asset de `public/` puede estar apuntado por un **setting administrable en la BD de prod** (ej.
  `app_settings.email_logo_url` → `/email-logo.png`) que NO podés inspeccionar → con 0 refs en código
  pero "seteable desde el back-office", **reportá, no borres** (caso testigo: `public/email-logo.png`).
- **Código de un job/cron:** una función llamada solo desde un scheduled job de Railway (ej. los
  slots fijos del estudio que generan pedidos mensuales, MEMORIA *2026-05-27*) parece muerta y no lo está.
- **Feature flags / settings administrables:** código detrás de un flag de `app_settings` apagado
  hoy NO es muerto (se enciende desde el back-office).
- **Parámetros de interfaz:** firmas que un framework exige (ej. `attrs` en `HTMLParser.handle_starttag`,
  params con default usados por keyword). Quitar un parámetro **cambia la firma** → no es limpieza.
- **Imports/llamadas con efecto secundario:** `client.fetch_token(...)` guarda estado; `import x`
  que registra algo. La **llamada se queda**; en F841 se tira solo la **asignación** sin usar.
- **Tooling / scripts CLI:** skills (`.claude/skills/**`), `scripts/*.mjs`, migraciones de imports.
  No los importa nadie a propósito (se corren a mano) → knip los marca, pero **se quedan**.
- **Librería mantenida a propósito:** primitivos shadcn (`src/design-system/ui/*`) y sus deps `radix`
  son la caja de herramientas del design system → se conservan aunque estén sin consumir hoy.

> **Respetar la MEMORIA.** Antes de borrar, chequear que no contradiga una decisión registrada.
> **Nunca** se borra: el barrel documentado `equipment/index.ts` (*2026-05-29*), los motores únicos
> `backend/{reservas,reportes,busqueda,services/branding,contabilidad,services/contenido}/` ni el
> sistema de analytics (*2026-06-02*).
> Si algo "parece muerto" pero está documentado como vivo → se **deja y se reporta** (baranda de
> "mirar el target antes de borrar").

### 3 · Verificar cada candidato (grep en TODO el repo)

La herramienta mira su dominio; vos mirás el repo entero. Antes de tocar:

```bash
# ¿Se usa en CUALQUIER lado? (no solo src/ o routes/ — incluir .mjs, tests, public, index.html)
grep -rn "NOMBRE" src packages backend .claude --include=*.ts --include=*.tsx --include=*.py --include=*.mjs
# Para un endpoint backend: grepeá la RUTA, no la función (el front la llama por string):
grep -rn "/api/la-ruta" src
```

Distinguir tres situaciones (cambian qué se borra):

- **Archivo huérfano:** 0 imports en todo el repo → se borra el archivo (`git rm`).
- **Export sin usar pero usado adentro de su módulo:** se quita solo la palabra `export` (o se deja);
  borrar la función rompería su uso interno.
- **Cascada:** borrar `X` deja huérfano a su helper privado o su import (ej. quitar `fuzzySameLabel`
  dejó muerta a su `normalize` privada; quitar `businessWhatsappLink` dejó sin uso el `import
  whatsappLink`). Hay que seguir la cascada hasta el fondo — `eslint`/`ruff` la confirman.

⚠️ **Cuidado con nombres comunes.** `grep` sobre-cuenta palabras genéricas (`categories`, `brands`,
`token`). Para esos, ni knip ni grep alcanzan: confiar en el **suite** y en `tsc` (que resuelven
bindings reales), o dejarlos.

### 4 · Clasificar el tipo de cambio (cuidado proporcional)

| Tipo | Qué es | Red mínima | Riesgo |
|---|---|---|---|
| **Borrado puro** | archivo / import / var muerta | tsc + eslint + build / pytest | bajo |
| **Refactor DRY** | unificar duplicación vía helper (ej. `MARCA_SUBQUERY`) | **salida byte-idéntica** (verificada) + suite + Postgres real | medio |
| **Cambio de conducta** | migrar a otra implementación (ej. normalizers a otro motor) | NO es limpieza pura → análisis de impacto + plan de prueba + **avisar antes** | alto |
| **Split de god-module** | partir en paquete (Frente E) | move-verbatim + set de rutas idéntico + suite + gate, **1 PR/corte + supervisor** | alto |
| **Core sagrado** | reservas / plata (`backend/reservas`, `reportes`) | **NO se toca en un barrido** → iniciativa propia, Opus | máximo |

> **Refactor DRY = byte-idéntico.** Si extraés un helper, probá que genera **exactamente** la misma
> salida que el código viejo (ej. imprimir el SQL resultante y comparar carácter por carácter). Un
> refactor de limpieza no debe cambiar ninguna conducta.

> **Conditional siempre-verdadero** (`if True:` envolviendo un bloque grande; vulture lo marca como
> _redundant if-condition_): se elimina dedentando el bloque, pero **nunca a mano** si son muchas
> líneas → **script de dedent uniforme** (-4 espacios) **después** de verificar que TODA línea no-vacía
> del bloque tiene ≥ ese indent (si una no, el dedent rompe la estructura). Red: `py_compile` + suite
> + **ejecutar la función real** (caso testigo: `compute_estadisticas`, 175 líneas de SQL, dedentadas
> por script y verificadas contra Postgres real).

### 5 · La red de tests (esto es el "cuidado")

**Nada se da por bueno sin verlo verde.** El suite es la red que caza lo que el ojo no ve
(el re-export `ESTADOS_RESERVADO` lo cazó un test, no la revisión).

**Backend:**
```bash
. /tmp/venv/bin/activate
export SECRET_KEY=ci-test-secret-not-for-production ADMIN_EMAILS=admin@test.com
unset DATABASE_URL
cd backend && python -m pytest tests/ -q     # corré DESDE backend/ (toma pytest.ini: asyncio_mode, markers)
```
> Los tests de DB se saltan **solos**: cada archivo exige su opt-in (`RESERVAS_DB_TEST=1` /
> `ALEMBIC_DB_TEST=1` + `DATABASE_URL` a una base con `test` en el nombre) vía `skipif`. Sin eso no
> corren — **no** es un marker por default. Por eso este comando es paridad real con el job de CI.

**SQL / refactors de DB → Postgres REAL.** CI corre contra Postgres real **solo** las migraciones
(`test_alembic_upgrade_db.py`) y el SQL de liquidación (`test_reportes_liquidacion_db.py`); el resto
de las queries de rutas **no** tiene cobertura DB en CI → si tu refactor toca SQL de otra ruta,
**ejercelo a mano**. Receta:
```bash
pg_ctlcluster 16 main start
su - postgres -c "psql -c \"ALTER USER postgres WITH PASSWORD 'postgres';\""
su - postgres -c "psql -c 'CREATE DATABASE rambla_rental_test;'"
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rambla_rental_test
# bootstrap (init_db() + alembic upgrade head + base limpia) YA está escrito como harness copiable
# en backend/tests/test_alembic_upgrade_db.py (fixture clean_db) → usalo de base.
# Después: sembrar datos mínimos y EJECUTAR los caminos reales (TestClient sobre endpoints públicos
# + llamadas directas a helpers).
```
El objetivo: que **cada forma distinta de query** y cada **alias** se ejecute contra Postgres y
devuelva lo esperado (no solo que compile).

**Frontend:**
```bash
npx prettier --check <archivos>     # gate BLOQUEANTE de CI
npx tsc --noEmit -p tsconfig.json   # tipos (caza imports/exports rotos y cascadas)
npx eslint <archivos>               # unused tras cascada
npm run build                       # job `build` de CI
```

**Dependencias:** sacar con `npm uninstall <dep>` (sincroniza `package-lock.json`); si hay
`bun.lock`, además `bun install`. Nunca editar `package.json` a mano sin actualizar los lockfiles
(rompe `npm ci` de CI).

### 6 · Empaquetar + revisar

- **Commits atómicos por categoría**, Conventional Commits en español: `chore(backend): …`,
  `chore(frontend): …`, `refactor(scope): …`, `fix(scope): …`.
- En el body, **documentar qué se dejó a propósito y por qué** (params, código sensible, falsos
  positivos, documentado en MEMORIA). El "se dejó a propósito" es parte del valor.
- **Despachar el `supervisor`** antes de abrir/mergear la PR (instrucción de `CLAUDE.md`).
- Acompañar con **plan de prueba en lenguaje claro** para que el dueño verifique conducta en staging
  (foco: los lugares que más código perdieron).

---

## Más allá del código muerto: modularizar y optimizar

Cuando el código muerto ya está barrido, el dueño suele pedir "¿y modularizar? ¿optimizar?".
Son lentes distintos: **no es borrado puro, cambia estructura/comportamiento** → red de tests sí o sí,
y clasificá por riesgo (tabla de la fase 4). Reglas:

- **Distinguí duplicación real-y-peligrosa de trivial/intencional.** Vale extraer cuando el patrón es
  largo, copiado en muchos lados y propenso a fallar (caso testigo: `MARCA_SUBQUERY`, una subquery de
  60 chars copiada 37× que ya había causado 500s en prod, #499). **NO** vale "DRY-ear" un one-liner
  (ej. el chequeo de rango `0 ≤ descuento ≤ 100`, repetido 3× pero con manejo de `None`/mensaje
  **distintos a propósito** por sitio) → forzarlo es over-engineering y arriesga pisar la diferencia
  intencional. La herramienta de detección de clones (`jscpd`) ayuda; un % bajo es sano.
- **N+1 de escritura** (`for x: conn.execute(INSERT …)`) → `conn.executemany(sql, [tuplas])`
  (behavior-idéntico; lista vacía = no-op; mismo orden de filas). Caso testigo: `duplicate_equipo`
  (categorías/etiquetas/kit) y `bulk_action` (insert anidado equipo×categoría). Verificá con suite +
  **ejercicio real contra Postgres** (forjá sesión admin con `signer.dumps({"email": <ADMIN_EMAILS>})`
  y pegale a la ruta con TestClient). **Pero ojo:** a veces el N+1 caro no es el INSERT sino una
  **llamada adentro del loop** (ej. `regenerate_auto_tags(conn, eid)` por equipo) → batchear eso toca
  el helper interno = refactor propio, no sweep.
- **Optimización sin problema medido = no tocar.** Memoización de React sin lag reportado, índices sin
  un `EXPLAIN` que muestre el cuello → es optimización prematura (deuda, no calidad). Reportá el
  candidato, no lo fuerces.
- **Boilerplate cross-cutting** (ej. `conn = get_db(); try/finally: close()` en ~37 rutas) → unificarlo
  (context-manager / FastAPI `Depends`) toca el manejo transaccional de **cada** endpoint = alto radio
  de explosión → **iniciativa propia con plan + supervisor**, jamás en un barrido.
- **Honestidad > actividad.** Si tras el análisis el código ya está bien modularizado (motores únicos
  presentes, clones ≤0.5%), la respuesta correcta es **decirlo**, no fabricar churn de bajo valor.
- **Decidir qué consolidar en un módulo fuente-única (no a ojo).** Cuando el candidato es "una regla
  o helper repetido en varios motores" (ej. lógica de fechas dispersa en reservas/precios/reportes),
  no lo cortes por intuición: despachá un **workflow de lectores paralelos** (uno por motor
  consumidor) que clasifique cada uso en una de 4 categorías — **PRIMITIVA-DAL** (ya vive en el DAL,
  no se toca), **DOMINIO-MOTOR** (lógica propia del motor, se queda ahí aunque "parezca" el mismo
  tema), **DISPLAY-FORMATO** (solo formatea para mostrar, no decide), **CANDIDATO-CONSOLIDAR** (la
  misma decisión repetida sin dueño claro). Solo se mueven los `CANDIDATO-CONSOLIDAR`. Caso testigo
  (#1136, `services/fechas.py`): 4 lectores sobre reservas/precios/alquileres/portal/jobs/
  reportes/contabilidad/auth/ical/pdf cazaron los candidatos reales (ventana de modificación,
  horarios) y **descartaron con fundamento** los falsos (buffer → se queda en `reservas`, jornadas →
  se queda en `precios`) — evitó mover lógica de dominio por "parece la misma fecha". La
  clasificación hace el corte objetivo en vez de a ojo; repetible para cualquier consolidación grande.

---

## Frente E — Modularización / split de god-modules (move-verbatim)

Cuando un módulo se volvió **god-module** (un `.py` de routes o `database.py` de >~1000 líneas que
mezcla varios concerns), se parte en un **paquete de submódulos por concern**. Probado en `equipos`,
`specs`, `cliente_portal`, `alquileres` y `database` (epic #501). **NO es un barrido rápido:** es una
**iniciativa gateada — UN CORTE = UNA PR — con supervisor por corte.** El principio rector es
**move-verbatim: cero cambio de comportamiento** (se mueve código tal cual; mejorar el código interno
es un refactor aparte, después).

### El patrón

1. `git mv foo.py foo/core.py` → `core.py` = **spine**: el `router` único (o la conexión/pool) +
   los helpers/modelos **compartidos** + la lógica reusable que importan otros módulos.
2. Extraer **un concern** a `foo/concern.py`, que importa del spine
   (`from foo.core import router, _helper, …`). **`core` NO importa de los submódulos** (dirección
   única → sin ciclo). Cada submódulo de routes registra sus endpoints sobre el `router` compartido
   al importarse.
3. `foo/__init__.py` **re-exporta la superficie pública estable** → `from foo import X` (y
   `foo.X` por atributo) sigue igual para **todos** los callers y tests. Listá explícitamente en
   `__all__` lo que consumían `main`, otros routers y los tests.
4. **Podá imports huérfanos** del spine tras cada extracción (ruff F401 los marca).
5. Spine puro: cuando todos los concerns salieron, `core.py` puede quedar registrando **0 rutas**
   (solo modelos + helpers compartidos), como `cliente_portal/core.py`.

### Red de verificación — TODA, por cada corte

- **ruff limpio** (`--select F,E9`) en el paquete.
- **Set de rutas IDÉNTICO** — el invariante que prueba que no se perdió ni movió ninguna ruta:
  diffeá `sorted({(método, path) for r in main.app.routes})` contra el baseline de antes del corte.
  Byte-a-byte. (Se computa bajo el entorno de tests, que mockea la DB.)
- **Suite completa verde** (`pytest -m "not db"`). Para `database`, además el job de CI **"Migraciones
  Alembic (Postgres real)"** valida `init_db()` desde cero.
- **Gate de reservas** (`test_gate_not_bypassed`) si el módulo inserta en `alquiler_items`: el
  allowlist usa **path relativo a `routes/`** (`alquileres/core.py`) y el escaneo es **recursivo**
  (`os.walk`) para alcanzar los `core.py` de los paquetes. Los `INSERT INTO alquiler_items` y el gate
  `_check_stock` **se quedan en el spine** (no se mueven) → el path sagrado no se toca.
- **Byte-idéntico:** confirmá por AST que las funciones movidas son idénticas a las de `dev` (no
  "casi"). Es la prueba dura del move-verbatim.

### Gotchas (los que pegamos de verdad)

- **Colisión nombre submódulo ↔ función re-exportada:** un submódulo `cotizar.py` + una función
  `cotizar` re-exportada → el `from foo.cotizar import cotizar` del `__init__` **rebindea** el
  atributo del paquete `foo.cotizar` del módulo a la función → los tests que hacen
  `import foo.cotizar as m; monkeypatch.setattr(m, "get_db", …)` reciben la función, no el módulo, y
  rompen (`AttributeError`). **Solución:** nombrá el submódulo distinto de cualquier símbolo
  re-exportado (`cotizacion.py`).
- **Monkeypatch namespace:** un test que patchea `routes.foo.get_db` deja de tener efecto si la
  función se movió a un submódulo (la función usa el binding de **su** módulo). Fix: patchear
  `routes.foo.<submodulo>.get_db`, donde la función vive y se usa.
- **Glob no-recursivo:** un test que escanea `routes/*.py` (glob o `os.listdir`) **no ve**
  `routes/foo/core.py` tras la conversión a paquete → usar `rglob`/`os.walk` con el path relativo
  como identificador. (Mismo arreglo: el gate test y el de columna-marca.)
- **Test que lee el archivo por path:** un test que hace `(ROOT/"database.py").read_text()` rompe
  cuando `database.py` pasa a ser el paquete `database/` → leer el paquete entero (`rglob("*.py")`).
- **Import huérfano post-extracción:** mover un concern suele dejar imports sin uso en el spine
  (ej. `from pdf import …` cuando los PDFs salieron) → ruff F401, podarlos.
- **`tsc` con cache incremental puede dar OK falso al cambiar el contrato de props de un componente
  compartido:** no rechequea todo tras un merge → corré fresco (`rm tsconfig.tsbuildinfo` o
  `tsc -b --force`) antes de cantar verde. Además, **el CI de un PR mergea con el `dev` actual**, que
  puede tener **call-sites nuevos** del componente aparecidos después de tu último merge local → antes
  de cerrar, re-mergeá `dev` y re-verificá (no confíes en el último `tsc` local si pasó tiempo).
  Pasó dos veces en la misma sesión (#1136: un 3er call-site de `CartDrawerView` llegó de `dev` después
  del merge, `tsc` local pasó por cache pero el CI del PR falló, costó 2 vueltas). Mismo gotcha aplica
  en `pulido-frontend` cuando se toca un componente compartido, no solo en splits de Frente E.

### Promoción

Los cortes se mergean a `dev` (squash, 1 por PR) y se promueven en lote `dev→main` como **PR de
promoción** (merge commit) con plan de prueba — gate del dueño (MEMORIA *2026-06-08 — Workflow de
cambios*). Para un split sagrado-adyacente, la sesión puede **auto-probar en staging** los caminos
clave vía `staging-login` (MEMORIA *2026-06-19*) antes de pasárselo al dueño.

---

## Frente B — Seguridad + bugs

Se dispara con "¿está todo seguro?", "¿no hay ningún bug posta?", "revisá seguridad", o como pasada
propia. **La misma regla de oro: no se AFIRMA "está OK" ni se parcha sin verificar.** Un "todo bien"
sin auditar es la mentira más cara — tranquiliza al dueño sobre un agujero real.

**Cómo se barre:**

1. **Auditar con un agente read-only** (`Explore`/`general-purpose`) en paralelo a la revisión a mano
   — fan-out por superficie, sin tocar nada. Es la fase de **diagnóstico** con la rúbrica (eje A
   Seguridad de [`PROTOCOLO.md`](../../../docs/PROTOCOLO.md)). El barrido cubre estas superficies:
   - **Authz / IDOR:** ¿toda escritura sensible tiene su guard (`require_admin`/`require_cliente`)?
     ¿un endpoint lee/edita un recurso de **otro** cliente por id sin chequear dueño? Caso testigo
     **#795**: 12 handlers de escritura de `/api/equipos` (create/update/delete/ficha/mantenimiento/
     kit/etiquetas/categorías) **sin `require_admin`** → anónimo total. El gate de público vivía en
     `middleware.PUBLIC_API`; se partió en `PUBLIC_API_READONLY` (GET/HEAD) vs `PUBLIC_API_ANY`.
     **Variante sutil:** un guard **local más débil** que el canónico — un `require_admin`/`_require_admin`
     definido en el route que solo hace `if not session` y NO valida `is_admin_email`. Pasa cualquier
     sesión logueada (incluida la de un **cliente** del portal, que mintea la misma cookie `session`)
     → escalada de privilegios. Chequear que el guard sea **el de `admin_guard`**, no una copia floja.
   - **Injection:** SQL siempre parametrizado (`?`→`%s` vía el wrapper PGCursor), nunca f-strings con
     input. Command/template injection en lo que toque shell o render.
   - **SSRF:** todo `fetch`/descarga de URL externa (media, webhooks) con allowlist + `follow_redirects=False`
     (caso testigo: `services/media/security.py`). Un redirect a `169.254.169.254` roba credenciales de cloud.
   - **XSS / open-redirect:** todo lo que vuelva al DOM o a `Location`. Caso testigo: `_safe_next_path`
     en `auth.py` endurecido para rechazar `<>"'`\``, whitespace y control chars en el `?next=`.
   - **Core sagrado:** overlap de reservas (cero doble-booking) y cálculos de plata — un bug acá es
     de severidad máxima aunque no sea "seguridad" clásica.
2. **Verificar todo hallazgo 🔴 leyendo el código antes de reportarlo.** Los agentes exageran o se
   quedan cortos: confirmá el claim en la fuente (un weak-guard reportado resultó **más** grave al
   verificarlo; otros "críticos" eran falsa alarma). No se reporta de oídas.
3. **Triage por severidad** (crítico / alto / medio / bajo). El crítico se arregla ya; lo medio/bajo
   puede ir a issue con label si no es urgente.
4. **Verificar explotabilidad antes de tocar.** No parchar lo que no se reprodujo: confirmá el
   exploit (ej. `TestClient` haciendo la escritura anónima → debe dar 401 después del fix; GET sigue
   200; admin pasa). Un "fix" de algo no explotable puede romper conducta legítima.
5. **Test de regresión sí o sí.** Cada hallazgo arreglado deja un test que falla sin el fix (caso
   testigo: `test_auth_guards.py` parametrizado por los 12 endpoints + el test XSS de `_safe_next_path`).
   Sin el test, el agujero vuelve en el próximo refactor.

> **El core de reservas/plata sigue sagrado.** Un bug **se reporta** y se arregla con plan + Opus +
> test; no se parcha de apuro dentro de un barrido. Lo demás (la fase 4 de Frente A) aplica igual.

## Frente C — Ramas

"Limpiá las ramas que no sean `dev` ni `main`." El riesgo es **borrar trabajo no mergeado**.

1. **Mapear rama → PR.** Por cada rama remota, buscá su PR (`mcp__github__list_pull_requests` por
   `head`). Una rama es segura de borrar **solo si su PR está MERGED** (o el trabajo llegó a `dev` por
   otra vía verificable). Una rama **sin PR o con PR abierto/cerrado-sin-merge = se deja** y se reporta.
2. **`git branch --merged` NO alcanza:** el flujo mergea con **squash** a `dev` (MEMORIA *2026-06-08 — Workflow de cambios*),
   así que la rama squasheada **no aparece** como merged por ancestría aunque su contenido ya esté en
   `dev`. La verdad es el **estado del PR** (MERGED), no el grafo de commits.
3. **Limitación del entorno:** en el sandbox `git push origin --delete <rama>` da **HTTP 403** y no hay
   tool MCP de delete-ref → **no se pueden borrar ramas remotas desde acá**. Acción correcta: **reportar
   la lista** de ramas borrables (con su PR mergeado como evidencia) y recomendar al dueño activar
   **"Automatically delete head branches"** en Settings del repo (las borra solas al mergear, de ahí
   en más). Nunca afirmar "borré las ramas" si el entorno no lo permitió.

## Frente D — Issues → skill `pendientes` (fuente única)

La administración de la cola (reconciliar issues contra el código, triagear con evidencia, deduplicar
trackers, etiquetar, intake de brain-dumps, reporte "¿cómo están los pendientes?") **vive en su propio skill**,
[`pendientes`](../pendientes/SKILL.md) — para que tenga la atención **continua y liviana** que necesita, en vez de
correr solo cuando se audita el repo entero. Es la **fuente única**.

Cuando una pasada de mantenimiento toque issues (cerrar lo que el barrido shippeó, abrir issues de los
hallazgos), **delegá en `pendientes`**. La regla de oro vale igual: **cerrar es afirmar "esto está hecho"** →
solo con evidencia (PR/commit) o la orden del dueño; parciales = abiertos; no enterrar backlog real.

---

## Qué NO tocar (lista negra)

1. `backend/migrations/` — historia congelada.
2. Core sagrado: `backend/reservas/`, `backend/reportes/` (y todo cálculo de stock/overlap/plata).
3. Motores únicos: `backend/busqueda/`, `backend/services/branding/`.
4. Barrel documentado `src/components/rental/equipment/index.ts` (MEMORIA *2026-05-29*).
5. Primitivos shadcn `src/design-system/ui/*` + sus deps `@radix-ui/*` (librería del DS).
6. Analytics (`src/lib/analytics.ts`) — eventos dinámicos (MEMORIA *2026-06-02*).
7. Parámetros de funciones, imports/llamadas con efecto, scripts de tooling/skills.

## Anti-objetivos (cuándo NO es un barrido rápido)

- **Core sagrado** (consolidar `_check_stock_hipotetico` que reimplementa el gate, tocar cálculos de
  plata) → se **reporta** como follow-up; el fix va con plan + Opus + test, nunca dentro de un barrido.
- **Split de god-module** → es Frente E, pero como **iniciativa gateada** (1 PR/corte + supervisor +
  red de verificación), no un sweep de "borré tres cosas de paso".
- **Cambios de conducta** disfrazados de limpieza → requieren plan de prueba y aviso.
- **Borrar a ciegas** lo que diga la herramienta → la herramienta da candidatos, no sentencias.

## Cheatsheet (el flow — diagnosticar → 5 frentes → cierre)

```
0. DIAGNOSTICAR (read-only): rúbrica de PROTOCOLO (ejes A-O + scorecard, dispatch en paralelo)
   → hallazgos archivo:línea / eje / severidad / propuesta

A · CÓDIGO (6 fases)                      B · SEGURIDAD + BUGS
1. setup venv + deps + npm ci            1. agente read-only por superficie (authz/inject/SSRF/XSS/core)
2. ruff + vulture + knip → candidatos    2. VERIFICAR el 🔴 leyendo el código (los agentes exageran)
3. triage: cazar falsos positivos        3. triage por severidad
4. grep repo-wide por cada candidato     4. reproducir el exploit (no parchar lo no explotable)
5. clasificar (puro/DRY/conducta/split/sagrado)  5. fix + test de regresión que falla sin él
6. red de tests (pytest[+PG real] / prettier+tsc+eslint+build)

E · MODULARIZACIÓN (split, 1 PR/corte)    C · RAMAS
1. git mv foo.py foo/core.py (spine)      1. mapear rama → PR
2. extraer concern → submódulo            2. borrable solo si PR=MERGED (squash ≠ git branch --merged)
3. __init__ re-exporta superficie         3. sandbox no borra (403) → reportar lista + auto-delete
4. VERIFICAR: set de rutas idéntico +
   ruff + suite + gate test + byte-AST    D · ISSUES → skill `pendientes` (fuente única)
5. el INSERT/gate de reservas NO se mueve    reconciliar / triagear / deduplicar / etiquetar /
   (queda en el spine)                       reporte de salud → delegá en `pendientes` (regla de oro:
                                             cerrar solo con evidencia)

CIERRE (todos los frentes): commits atómicos + body con "lo que se dejó" → supervisor → plan de prueba
```

## Auto-mejora (correr al cerrar cada uso)

Preguntate, crítico: ¿alguna regla me desorientó o quedó vieja porque el repo cambió? ¿pegué un
gotcha que merece ser "caso testigo"? ¿overlap con otro skill? ¿repetí a mano un paso que debería
estar codificado acá?

Si **SÍ** → anotá la propuesta en [`docs/PROPUESTAS_SKILLS.md`](../../../docs/PROPUESTAS_SKILLS.md)
(formato: `fecha · skill · qué cambiar · por qué`). Proponés, no aplicás — el dueño aprueba, igual
que la memoria; el supervisor puede validar.

Si **NO** → no fabriques churn. **Honestidad > actividad.**
