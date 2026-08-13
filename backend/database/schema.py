"""database/schema.py — bootstrap idempotente del esquema (#501 Fase 5).

`init_db()` crea/asegura todas las tablas, índices y extensiones (capa 1 del
esquema en dos capas; Alembic es la capa 2 — decisión 2026-06-03). Move-verbatim
desde `database.py`; usa la conexión cruda + los wrappers del spine (`core`).
"""
import logging
import time

import psycopg

from busqueda.motor import CAMPO_PLANTILLA
from database.core import DATABASE_URL, PGConnection

logger = logging.getLogger(__name__)


def _ddl_retry(conn, sql: str, retries: int = 3) -> None:
    """Ejecuta `sql` reintentando si Postgres devuelve 'tuple concurrently updated'.

    Esa condición ocurre cuando autovacuum toca pg_catalog.pg_proc justo mientras
    CREATE OR REPLACE FUNCTION escribe ahí. Es transitorio y reintentar resuelve.
    """
    for attempt in range(retries):
        try:
            conn.execute(sql)
            return
        except psycopg.Error as exc:
            if "tuple concurrently updated" in str(exc) and attempt < retries - 1:
                time.sleep(0.2 * (2 ** attempt))
            else:
                raise


def init_db():
    """Crear todas las tablas si no existen."""
    raw_conn = psycopg.connect(DATABASE_URL, autocommit=True, cursor_factory=psycopg.ClientCursor)
    conn = PGConnection(raw_conn)
    try:
        _init_db_schema(conn)
    finally:
        conn.close()
    logger.info("Base de datos PostgreSQL inicializada")


def _init_db_schema(conn):
    """Aplica todo el DDL idempotente sobre `conn`. La conexión y su cierre los
    maneja `init_db` con try/finally — separar el cuerpo evita re-indentar ~1500
    líneas y garantiza que `conn.close()` corra aunque un DDL falle (sin leak)."""
    # ── Búsqueda fuzzy: extensiones + helper inmutable ────────────────────────
    # `pg_trgm` (similitud por trigramas → typos + ranking) y `unaccent` (folding
    # de acentos: "bateria" = "Batería"). El motor único vive en backend/busqueda;
    # acá garantizamos que la infra de BD que necesita exista. `unaccent()` es
    # STABLE (no indexable); `f_unaccent` la envuelve IMMUTABLE — la forma
    # canónica que usan tanto las queries (busqueda.campo_sql) como los índices
    # GIN trigram de abajo. Idempotente. Ver decisión 2026-06-06 (motor de búsqueda).
    conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    # CREATE OR REPLACE FUNCTION toca pg_proc y puede colisionar con autovacuum
    # corriendo sobre el catálogo en CI. Reintentamos hasta 3 veces con backoff
    # exponencial corto — en prod este DDL nunca corre en caliente.
    _ddl_retry(
        conn,
        "CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text AS "
        "$$ SELECT public.unaccent('public.unaccent', $1) $$ "
        "LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT",
    )

    # Crear tablas
    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipos (
            id               SERIAL PRIMARY KEY,
            nombre           TEXT NOT NULL,
            modelo           TEXT,
            cantidad         INTEGER NOT NULL DEFAULT 1,
            precio_jornada   INTEGER,
            precio_usd       FLOAT,
            roi_pct          FLOAT,
            valor_reposicion FLOAT,
            foto_url         TEXT,
            foto_url_sm      TEXT,   -- variante 600px de la foto principal para srcset (NULL = sin variante → el front usa foto_url)
            foto_url_thumb   TEXT,   -- variante 160px para thumbnails de ~48px (NULL = sin variante → el front usa foto_url_sm)
            fecha_compra     DATE,
            serie            TEXT,
            bh_url           TEXT,
            dueno            TEXT DEFAULT 'Rental',
            visible_catalogo INTEGER DEFAULT 1,
            estado           TEXT DEFAULT 'operativo',
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migration: flag para distinguir precios manuales (admin tipeó un valor
    # que no sale de la fórmula) vs automáticos (calculados desde
    # precio_usd × usd_rate × roi_pct/100). Cuando se hace recálculo masivo
    # al actualizar el USD rate, los manuales se respetan por default.
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS precio_jornada_manual BOOLEAN NOT NULL DEFAULT FALSE")

    # Migration: flag manual que el admin marca cuando termina de cargar la
    # ficha de un equipo. Permite filtrar "equipos pendientes" en el workflow
    # de carga incremental de inventario.
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS ficha_completa BOOLEAN NOT NULL DEFAULT FALSE")

    # Migration: soft delete. NULL = activo. Timestamp = eliminado.
    # Las listas filtran eliminado_at IS NULL por default. Preserva historial
    # de alquileres de equipos dados de baja (#206).
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS eliminado_at TIMESTAMP")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_equipos_eliminado_at ON equipos(eliminado_at) WHERE eliminado_at IS NOT NULL")

    # Migration: categoría de SPECS del equipo (1 de las 5 del registry:
    # Cámaras/Lentes/Iluminación/Adaptadores/Filtros). Define qué specs aplican
    # y el nombre público, desacoplado del árbol de categorías de catálogo
    # (equipo_categorias), que es una agrupación manual web-managed para el
    # front-office. NULL = sin specs asignadas.
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS categoria_specs TEXT")

    # Migration: variantes AVIF + LQIP denormalizadas de la foto principal (perf
    # del catálogo). Acompañan a foto_url/foto_url_sm/foto_url_thumb: el front sirve
    # <picture> con AVIF (~20-30% menos bytes que webp) + blur-up LQIP sin inflar el
    # payload del listado (127 equipos × ~250 bytes). Todas nullable: legacy = NULL
    # → fallback seguro a la variante webp. Por ahora quedan vacías: las puebla un
    # PR posterior (ingesta/sync de la foto principal); mientras tanto la web usa webp.
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS foto_url_avif TEXT")
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS foto_url_sm_avif TEXT")
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS foto_url_thumb_avif TEXT")
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS foto_lqip TEXT")

    # Migration: URL pública del HTML de producto guardado (B&H Webpage Complete).
    # Permite re-extraer specs en el futuro sin volver a pedir el HTML al dueño.
    # Mismo patrón que foto_url — almacena URL pública R2, blob en equipos/{id}/source.html.
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS html_source_url TEXT")

    # Migration: recurso interno (no es un producto del catálogo). Lo usa el
    # centinela del Estudio (E2): un equipo de cantidad=1 que representa el
    # espacio físico para que las reservas por hora pasen por el mismo motor de
    # stock/overlap. Se excluye SIEMPRE de catálogo público, filtros, listado
    # admin, ranking y specs — no es un producto alquilable suelto. Es distinto
    # de visible_catalogo=0 (un producto real oculto sigue siendo producto).
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS es_recurso_interno BOOLEAN NOT NULL DEFAULT FALSE")

    # Migration (#637): el default histórico del schema era 'ok', un valor que no
    # existe en el enum de la app (operativo / en_mantenimiento / fuera_servicio).
    # Un equipo creado sin estado explícito quedaba en 'ok' y el dropdown del admin
    # no matcheaba ninguna opción. Se alinea el default y se normalizan las filas
    # viejas que hayan quedado en 'ok'. Idempotente: el UPDATE es no-op tras la 1ra corrida.
    conn.execute("ALTER TABLE equipos ALTER COLUMN estado SET DEFAULT 'operativo'")
    conn.execute("UPDATE equipos SET estado = 'operativo' WHERE estado = 'ok'")

    # Tabla de marcas (brands)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS marcas (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL UNIQUE,
            logo_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # idx_marcas_nombre (índice plano sobre `nombre`) se retiró: `nombre` ya es
    # UNIQUE arriba, Postgres ya crea su propio índice de soporte — era 100%
    # redundante (ver migración q4r5s6t7u8v9_drop_redundant_plain_indexes).

    # Migration: agregar columnas visible y orden para admin settings
    conn.execute("ALTER TABLE marcas ADD COLUMN IF NOT EXISTS visible BOOLEAN NOT NULL DEFAULT TRUE")
    conn.execute("ALTER TABLE marcas ADD COLUMN IF NOT EXISTS orden INTEGER NOT NULL DEFAULT 100")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_marcas_orden ON marcas(orden ASC)")
    # Migration: ranking automático de marcas (#131). Mismo concepto que equipos.
    conn.execute("ALTER TABLE marcas ADD COLUMN IF NOT EXISTS popularidad_score INT NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE marcas ADD COLUMN IF NOT EXISTS cant_pedidos INT NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE marcas ADD COLUMN IF NOT EXISTS ingreso_total_ars BIGINT NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE marcas ADD COLUMN IF NOT EXISTS ranking_actualizado TIMESTAMP")
    conn.execute("ALTER TABLE marcas ADD COLUMN IF NOT EXISTS destacada BOOLEAN NOT NULL DEFAULT FALSE")
    conn.execute("ALTER TABLE marcas ADD COLUMN IF NOT EXISTS logo_url_sm TEXT")

    # FK a marcas. brand_id es la fuente única del nombre de marca
    # (vía marcas.nombre). El backfill desde la columna legacy `marca` y su
    # DROP viven en la migración d5a8f2c4b6e9 (corre una sola vez).
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS brand_id INTEGER REFERENCES marcas(id)")

    # Migration: costo de COMPRA del equipo (no confundir con `valor_reposicion`,
    # que es para seguros/remitos). Nullable a propósito — NULL = todavía no
    # cargado (distinto de $0); habilita el ranking "rentabilidad neta" de
    # Estadísticas (ingreso − costo), que solo cuenta los equipos con el dato
    # cargado. Se carga a mano, sin fuente que lo derive.
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS costo_compra INTEGER")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id                SERIAL PRIMARY KEY,
            nombre            TEXT NOT NULL,
            apellido          TEXT NOT NULL,
            telefono          TEXT NOT NULL,
            email             TEXT NOT NULL UNIQUE,
            direccion         TEXT NOT NULL,
            cuit              TEXT NOT NULL,
            descuento         NUMERIC(5,2) DEFAULT 0,
            perfil_impuestos  TEXT DEFAULT 'consumidor_final',
            razon_social      TEXT,
            domicilio_fiscal  TEXT,
            email_facturacion TEXT,
            notas             TEXT,
            created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migration: add maps URL column if not present
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS direccion_maps_url TEXT")
    # Migration: link clientes to Supabase Auth users (Phase 1 of unified backend)
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS supabase_uid UUID UNIQUE")
    # idx_clientes_supabase_uid (índice plano) se retiró: `supabase_uid` ya es
    # UNIQUE arriba, era 100% redundante (ver migración
    # q4r5s6t7u8v9_drop_redundant_plain_indexes).
    # Cuentas livianas (alta passwordless con passkey): la cuenta NACE sin datos
    # (solo id + passkey); Didit completa identidad/contacto al primer pedido —y los
    # escribe en `*_renaper`, no en estos campos base— así que se relajan los NOT NULL.
    # El `UNIQUE` de email se mantiene (Postgres permite múltiples NULL). `cuenta_estado`
    # = 'liviana' marca la cuenta vacía. Espejo idempotente de la migración a7f3e1c9d2b4.
    conn.execute("ALTER TABLE clientes ALTER COLUMN nombre DROP NOT NULL")
    conn.execute("ALTER TABLE clientes ALTER COLUMN apellido DROP NOT NULL")
    conn.execute("ALTER TABLE clientes ALTER COLUMN telefono DROP NOT NULL")
    conn.execute("ALTER TABLE clientes ALTER COLUMN email DROP NOT NULL")
    conn.execute("ALTER TABLE clientes ALTER COLUMN direccion DROP NOT NULL")
    conn.execute("ALTER TABLE clientes ALTER COLUMN cuit DROP NOT NULL")
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS cuenta_estado TEXT NOT NULL DEFAULT 'completa'")
    # Functional index sobre LOWER(email): el UNIQUE no se usa porque las
    # queries hacen WHERE LOWER(email) = LOWER(?) (auth.py, cliente_portal.py).
    conn.execute("CREATE INDEX IF NOT EXISTS idx_clientes_email_lower ON clientes(LOWER(email))")
    # Índices GIN trigram para la búsqueda fuzzy (backend/busqueda). La expresión
    # es la canónica única (CAMPO_PLANTILLA) — la misma que arma busqueda.campo_sql
    # en las queries, para que el planner los pueda usar. El combinado
    # nombre+apellido permite que "santiago perez" rankee por prefijo.
    _nombre_apellido = CAMPO_PLANTILLA.format(expr="(nombre || ' ' || apellido)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_clientes_nombre_apellido_trgm ON clientes USING gin ({_nombre_apellido} gin_trgm_ops)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_clientes_email_trgm ON clientes USING gin ({CAMPO_PLANTILLA.format(expr='email')} gin_trgm_ops)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_clientes_cuit_trgm ON clientes USING gin ({CAMPO_PLANTILLA.format(expr='cuit')} gin_trgm_ops)")
    # Verificación de identidad Didit (DNI + selfie → RENAPER). Esquema en dos
    # capas (MEMORIA 2026-06-03): espejo idempotente de la migración v6w7x8y9z0a1.
    # — dni: número de documento validado (sin foto — Didit no la entrega).
    # — cuil: CUIL personal confirmado por RENAPER (puede diferir del `cuit` de
    #   facturación, que puede ser la razón social de una empresa).
    # — dni_validado_at: timestamp de la aprobación (NULL = no verificado todavía).
    # — didit_session_id: ID de la sesión de Didit para auditoría y trazabilidad.
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS dni TEXT")
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS cuil TEXT")
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS dni_validado_at TIMESTAMP")
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS didit_session_id TEXT")
    # Datos completos de RENAPER (extraídos por Didit del documento + base RENAPER).
    # Solo se persiste texto — no hay imagen ni biométrico (Ley 25.326).
    # Todos los campos son NULL hasta completar la verificación.
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS nombre_renaper TEXT")
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS apellido_renaper TEXT")
    # nombre_completo_renaper: nombre legal autoritativo tal cual lo devuelve
    # RENAPER (full_name), sin reconstruirlo de nombre+apellido — importa para
    # los contratos, donde el string legal exacto cuenta.
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS nombre_completo_renaper TEXT")
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS fecha_nacimiento_renaper TEXT")
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS direccion_renaper TEXT")
    # Datos adicionales del documento (todos solo texto — Ley 25.326).
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS genero_renaper TEXT")
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS nacionalidad_renaper TEXT")
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS lugar_nacimiento_renaper TEXT")
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS vencimiento_documento_renaper TEXT")
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS emision_documento_renaper TEXT")
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS tipo_documento_renaper TEXT")
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS estado_civil_renaper TEXT")
    # apodo: alias opcional para saludos informales en mails (siempre editable).
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS apodo TEXT")
    # Estado del flujo de verificación Didit (PR2). El gate de pedidos sigue usando
    # `dni_validado_at IS NOT NULL` como criterio — este campo añade visibilidad de
    # estados intermedios para el portal (rechazado, en_revision).
    # Espejo de la migración i9j0k1l2m3n4 (esquema en dos capas, MEMORIA 2026-06-03).
    conn.execute(
        "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS "
        "dni_verificacion_estado TEXT NOT NULL DEFAULT 'no_verificado'"
    )
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS dni_verificacion_motivo TEXT")

    # ── Identidad (Fase 2): contactos verificados + bitácora KYC + consentimiento ──
    # Base del motor `backend/identity/` ("quién sos"). El payload crudo de Didit muere
    # en `services/didit/`; acá viven los datos normalizados. Espejo idempotente de la
    # migración 1d3nt1dadf2a. El índice único parcial de CUIL va aparte, AL FINAL (tras
    # limpiar duplicados legacy).
    #   — kyc_consent_at: el cliente consintió el KYC + el guardado (Ley 25.326).
    #   — identidad_conflicto: conflicto de dedup (dos cuentas mismo CUIL) que necesita
    #     resolución manual del admin → estado derivado 'conflicto'.
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS kyc_consent_at TIMESTAMP")
    conn.execute(
        "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS "
        "identidad_conflicto BOOLEAN NOT NULL DEFAULT FALSE"
    )
    # Soft delete (backend/clientes/, #1251 Fase 2): NULL = activo, timestamp = eliminado.
    # Mismo patrón que equipos (#206) — sin actor/motivo (el dueño es único admin hoy; no
    # se justifica el log de auditoría completo). `eliminar` ya no hace DELETE físico.
    # Trade-off consciente: `email UNIQUE` de la tabla sigue siendo global (no
    # `WHERE eliminado_at IS NULL`) — un cliente borrado sigue "reservando" su
    # email. No se tocó: convertir un UNIQUE inline existente en una base viva
    # es cirugía de constraint innecesaria para un caso borde de bajo volumen
    # (pocas bajas de cliente). Revisar si algún día un alta choca con un
    # email de una cuenta ya eliminada.
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS eliminado_at TIMESTAMP")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_clientes_eliminado_at ON clientes(eliminado_at) "
        "WHERE eliminado_at IS NOT NULL"
    )
    # verified_contacts: mail/teléfono VERIFICADOS (Google OAuth / código Didit / OTP) —
    # factores de comunicación y recuperación. El teléfono se guarda en E.164. Owner-scoped
    # (FK CASCADE). Trae las señales anti-fraude de Didit (is_disposable/is_virtual/is_breached).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS verified_contacts (
            id            SERIAL PRIMARY KEY,
            cliente_id    INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            kind          TEXT NOT NULL CHECK (kind IN ('email', 'phone')),
            value         TEXT NOT NULL,
            source        TEXT NOT NULL CHECK (source IN ('google', 'didit', 'otp', 'manual')),
            verified_at   TIMESTAMP,
            is_disposable BOOLEAN,
            is_virtual    BOOLEAN,
            is_breached   BOOLEAN,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (cliente_id, kind, value)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_verified_contacts_cliente ON verified_contacts(cliente_id)"
    )
    # kyc_events: bitácora de auditoría del KYC (started / approved / declined / reverify /
    # anchor_set / merge / conflict). SOLO TEXTO (Ley 25.326: nada de biometría; `detalle`
    # es para diagnóstico, no para PII).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kyc_events (
            id          SERIAL PRIMARY KEY,
            cliente_id  INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            evento      TEXT NOT NULL,
            detalle     TEXT,
            session_id  TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kyc_events_cliente ON kyc_events(cliente_id)")

    # Índice único de CUIL — "una persona verificada = una cuenta". PARCIAL: solo cuenta a
    # los verificados (CUIL NULL o no-verificado nunca bloquea; extranjeros sin CUIL tampoco).
    # Lo escribe SOLO identity/kyc al aprobar Didit; jamás el usuario. Va AL FINAL: si quedan
    # duplicados legacy, la creación falla con UniqueViolation → NO rompemos el boot (init_db
    # corre en autocommit, cada DDL es atómico). Logueamos un aviso accionable y seguimos; el
    # operador corre el dedup (identity.merge.candidatos_duplicados → merge_accounts) y en el
    # próximo boot el índice se crea. El gate anti-duplicado lo da el merge + este candado a
    # nivel DB. Espejo de la migración f2cu1lun1qx01. (MEMORIA: ancla CUIL, Fase 2 #1098.)
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uniq_cliente_cuil_verificado "
            "ON clientes (cuil) WHERE cuil IS NOT NULL AND dni_validado_at IS NOT NULL"
        )
    except psycopg.errors.UniqueViolation:
        logger.warning(
            "Índice único de CUIL no creado: hay clientes verificados con CUIL duplicado. "
            "Corré el dedup (identity.merge.candidatos_duplicados → merge_accounts) y reiniciá."
        )

    # Passkeys (WebAuthn/FIDO2) — login aditivo a Google OAuth. Una sola tabla
    # para admin (owner_email, cliente_id NULL) y
    # cliente (cliente_id seteado), con discriminador `owner_type`. credential_id /
    # public_key en base64url TEXT (el browser manda el id en base64url → lookup
    # de texto directo). Esquema en dos capas (MEMORIA 2026-06-03): espejo
    # idempotente de la migración a1f2b3c4d5e6.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS passkey_credentials (
            id             SERIAL PRIMARY KEY,
            owner_type     TEXT NOT NULL CHECK (owner_type IN ('admin', 'cliente')),
            owner_email    TEXT NOT NULL,
            cliente_id     INTEGER REFERENCES clientes(id) ON DELETE CASCADE,
            credential_id  TEXT NOT NULL UNIQUE,
            public_key     TEXT NOT NULL,
            sign_count     BIGINT NOT NULL DEFAULT 0,
            transports     TEXT,
            aaguid         TEXT,
            device_name    TEXT,
            user_handle    TEXT NOT NULL,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at   TIMESTAMP,
            CHECK ((owner_type = 'cliente' AND cliente_id IS NOT NULL)
                OR (owner_type = 'admin'   AND cliente_id IS NULL))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_passkey_cred_cliente "
        "ON passkey_credentials(cliente_id) WHERE owner_type = 'cliente'"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_passkey_cred_admin "
        "ON passkey_credentials(LOWER(owner_email)) WHERE owner_type = 'admin'"
    )

    # ── Sesiones server-side: allowlist para revocación (logout real + "cerrar mis
    # otras sesiones"). La cookie firmada lleva un `jti` opaco; esta tabla decide si
    # sigue viva. Espeja `passkey_credentials` (mismo discriminador owner_type +
    # CHECK de dos lados). `expires_at` materializa el TTL de la cookie; `revoked_at`
    # NULL = activa. Toda sesión válida lleva `jti` y vive acá; una cookie sin jti
    # (viejas pre-deploy) se rechaza → re-login.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auth_sessions (
            jti           TEXT PRIMARY KEY,
            owner_type    TEXT NOT NULL CHECK (owner_type IN ('admin', 'cliente')),
            owner_email   TEXT NOT NULL,
            cliente_id    INTEGER REFERENCES clientes(id) ON DELETE CASCADE,
            user_agent    TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at    TIMESTAMP NOT NULL,
            revoked_at    TIMESTAMP,
            CHECK ((owner_type = 'cliente' AND cliente_id IS NOT NULL)
                OR (owner_type = 'admin'   AND cliente_id IS NULL))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_sessions_cliente "
        "ON auth_sessions(cliente_id) WHERE owner_type = 'cliente'"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_sessions_admin "
        "ON auth_sessions(LOWER(owner_email)) WHERE owner_type = 'admin'"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires "
        "ON auth_sessions(expires_at)"
    )

    # ── Identidades de login del cliente: las N llaves (Google `sub` / mail) que
    # apuntan a UNA cuenta (clientes.id). Generaliza "método de login → cuenta".
    # 'google' → identifier = el `sub` estable (no el mail, que cambia); 'email' →
    # el mail (handle de magic-link). Passkey NO se escribe acá (vive en
    # passkey_credentials con sus columnas WebAuthn); "mis llaves" une las dos en
    # lectura. UNIQUE(method, identifier) = una llave → una sola cuenta (anti-duplicado
    # de persona). Espejo idempotente de la migración f3b8d1a6c9e2 (MEMORIA 2026-06-03).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS login_identities (
            id           SERIAL PRIMARY KEY,
            cliente_id   INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            method       TEXT NOT NULL CHECK (method IN ('google', 'passkey', 'email')),
            identifier   TEXT NOT NULL,
            verified_at  TIMESTAMP,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (method, identifier)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_login_identities_cliente "
        "ON login_identities(cliente_id)"
    )
    # `email`: el mail asociado a la identidad al vincularla (el del Google, o el del
    # propio método 'email'). Solo display — el ancla sigue siendo `identifier` (el `sub`
    # para Google). Nullable; espejo de la migración b8e2f4a6c1d3.
    conn.execute("ALTER TABLE login_identities ADD COLUMN IF NOT EXISTS email TEXT")

    # ── Challenges de magic-link por mail (auth/otp): backing store del link de un
    # solo uso (cruza dispositivos/requests → no entra en una cookie como el challenge
    # de passkey). `token_hash` = sha256 del nonce firmado (no se guarda el token
    # crudo); `used_at` NULL = sin usar; `expires_at` materializa el TTL. Espejo
    # idempotente de la migración f3b8d1a6c9e2.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auth_challenges (
            id           SERIAL PRIMARY KEY,
            kind         TEXT NOT NULL CHECK (kind IN ('magic_link')),
            email        TEXT NOT NULL,
            token_hash   TEXT NOT NULL UNIQUE,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at   TIMESTAMP NOT NULL,
            used_at      TIMESTAMP,
            attempts     INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_challenges_email "
        "ON auth_challenges(LOWER(email))"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS alquileres (
            id               SERIAL PRIMARY KEY,
            cliente_id       INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
            cliente_nombre   TEXT NOT NULL,
            cliente_email    TEXT,
            cliente_telefono TEXT,
            notas            TEXT,
            estado           TEXT NOT NULL DEFAULT 'solicitado',
            fecha_desde      TIMESTAMP,
            fecha_hasta      TIMESTAMP,
            monto_total      INTEGER DEFAULT 0,
            monto_pagado     INTEGER DEFAULT 0,
            descuento_pct    NUMERIC(5,2) DEFAULT 0,
            fuente           TEXT DEFAULT 'sistema',
            numero_pedido    INTEGER,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Estudio E2: tipo de alquiler ('diaria' = pedido normal por jornada;
    # 'estudio'/'estudio_fijo' = reserva del espacio por horas / slot mensual;
    # 'taller' = resumen mensual de una edición de taller, ver
    # `_regenerar_pedidos_taller`). El DEFAULT 'diaria' es clave: las reservas
    # existentes y las queries de overlap (que NO filtran por tipo) quedan
    # idénticas. `estudio_con_pack` se reserva para E3 (pack Grip/Luz). Sin
    # CHECK constraint — cualquier texto es válido, el enum vive en el código.
    conn.execute("ALTER TABLE alquileres ADD COLUMN IF NOT EXISTS tipo TEXT NOT NULL DEFAULT 'diaria'")
    conn.execute("ALTER TABLE alquileres ADD COLUMN IF NOT EXISTS estudio_con_pack BOOLEAN NOT NULL DEFAULT FALSE")

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pedidos_estado ON alquileres(estado)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pedidos_fechas ON alquileres(fecha_desde, fecha_hasta)
    """)
    # Portal del cliente trae sus pedidos con WHERE cliente_id = ? en cada carga.
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pedidos_cliente ON alquileres(cliente_id)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS alquiler_items (
            id             SERIAL PRIMARY KEY,
            pedido_id      INTEGER NOT NULL REFERENCES alquileres(id) ON DELETE CASCADE,
            -- equipo_id NULL = línea personalizada (texto libre, #805): no es del
            -- catálogo, no reserva stock. Su nombre vive en `nombre_libre`.
            equipo_id      INTEGER REFERENCES equipos(id),
            cantidad       INTEGER NOT NULL DEFAULT 1,
            precio_jornada INTEGER NOT NULL DEFAULT 0,
            subtotal       INTEGER NOT NULL DEFAULT 0,
            -- Orden manual de las líneas dentro del pedido (drag-reorder, #806).
            -- Se asigna por posición al guardar; los displays ordenan por `orden, id`.
            orden          INTEGER NOT NULL DEFAULT 0,
            -- Línea personalizada (#805): nombre libre + modo de cobro por línea.
            -- `cobro_modo`: 'jornada' (× jornadas, default = equipos) | 'fijo' (monto único).
            nombre_libre   TEXT,
            cobro_modo     TEXT NOT NULL DEFAULT 'jornada'
        )
    """)
    # Idempotente para tablas ya creadas antes de estas features (esquema en dos capas).
    conn.execute("ALTER TABLE alquiler_items ADD COLUMN IF NOT EXISTS orden INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE alquiler_items ADD COLUMN IF NOT EXISTS nombre_libre TEXT")
    conn.execute("ALTER TABLE alquiler_items ADD COLUMN IF NOT EXISTS cobro_modo TEXT NOT NULL DEFAULT 'jornada'")
    # Línea personalizada (#805): equipo_id deja de ser NOT NULL para permitir
    # líneas libres. Idempotente para tablas viejas con la constraint.
    conn.execute("ALTER TABLE alquiler_items ALTER COLUMN equipo_id DROP NOT NULL")

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pedido_items_pedido ON alquiler_items(pedido_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pedido_items_equipo ON alquiler_items(equipo_id)
    """)

    # Un turno del Estudio embebido en un pedido de alquiler normal (tipo='diaria') es un GRUPO de
    # alquiler_items (centinela + opcional promo/sueltos/pintura) colgando de la MISMA fila de
    # alquileres, en vez de una fila `alquileres` aparte vinculada por pedido_principal_id. Aditivo
    # puro: ninguna fila existente tiene turno_estudio_id poblado (cero cambio de comportamiento).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alquiler_turnos_estudio (
            id                      SERIAL PRIMARY KEY,
            pedido_id               INTEGER NOT NULL REFERENCES alquileres(id) ON DELETE CASCADE,
            fecha_desde             TIMESTAMP NOT NULL,
            fecha_hasta             TIMESTAMP NOT NULL,
            descuento_pct           NUMERIC(7,4) NOT NULL DEFAULT 0,
            descuento_manual_tipo   VARCHAR(10) NOT NULL DEFAULT 'pct',
            descuento_manual_monto  INTEGER NOT NULL DEFAULT 0,
            created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_turnos_estudio_pedido ON alquiler_turnos_estudio(pedido_id)
    """)
    conn.execute(
        "ALTER TABLE alquiler_items ADD COLUMN IF NOT EXISTS turno_estudio_id "
        "INTEGER REFERENCES alquiler_turnos_estudio(id) ON DELETE CASCADE"
    )
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pedido_items_turno_estudio ON alquiler_items(turno_estudio_id)
    """)

    # NOTA: tabla `usuarios` (auth email+password legacy) removida en #76.
    # Auth ahora es 100% Google OAuth + Supabase. La migración Alembic
    # `322b...drop_tabla_usuarios_legacy_76` hace el DROP en prod.

    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipo_fichas (
            equipo_id   INTEGER PRIMARY KEY REFERENCES equipos(id) ON DELETE CASCADE,
            descripcion TEXT,
            notas       TEXT,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # specs_json + raw_json fueron droppeados en Fase E (d7e9b3c5a8f2).
    # montura/formato/resolucion/peso/dimensiones/alimentacion fueron
    # droppeados en Fase F (a1b3c5e7f9d2). Las specs viven en equipo_specs.
    # Keywords/palabras clave libres por equipo (array JSON de strings).
    # Distintas de las etiquetas de búsqueda: estas son selling-points editoriales
    # ("bicolor", "silenciosa", "V-mount", "global shutter") visibles en la ficha.
    conn.execute("ALTER TABLE equipo_fichas ADD COLUMN IF NOT EXISTS keywords_json TEXT")
    # Template editable para el "nombre público" (con placeholders {marca}, {montura}, etc.).
    # Si está NULL/vacío, se usa el auto-build del frontend.
    conn.execute("ALTER TABLE equipo_fichas ADD COLUMN IF NOT EXISTS nombre_publico_template TEXT")

    # ── Ficha extendida (enriquecimiento con IA + scraping) ─────────────
    # Las specs físicas (peso/dimensiones/alimentacion/montura/formato/
    # resolucion) viven en equipo_specs desde Fase F. Acá quedan solo
    # las listas y multimedia que aún no son specs estructuradas.
    # Listas estructuradas (TEXT con JSON, igual que keywords_json).
    # `incluye_json` (legacy enriquecimiento IA) fue DROPEADO (F5): el "qué incluye"
    # deriva de kit_componentes vía la puerta única `services.contenido`. La columna
    # se elimina en su migración Alembic; acá ya no se crea en BDs nuevas.
    conn.execute("ALTER TABLE equipo_fichas ADD COLUMN IF NOT EXISTS conectividad_json TEXT")    # ["USB-C", "HDMI Type-A", "XLR x2"]
    conn.execute("ALTER TABLE equipo_fichas ADD COLUMN IF NOT EXISTS compatible_con_json TEXT")  # ["Sony E-mount", "Full-frame"]
    # Multimedia y referencias
    conn.execute("ALTER TABLE equipo_fichas ADD COLUMN IF NOT EXISTS video_url TEXT")             # YouTube demo
    conn.execute("ALTER TABLE equipo_fichas ADD COLUMN IF NOT EXISTS precio_bh_usd FLOAT")        # precio listado en B&H (referencia)
    conn.execute("ALTER TABLE equipo_fichas ADD COLUMN IF NOT EXISTS fuente_url TEXT")            # canonical (B&H si hubo)
    conn.execute("ALTER TABLE equipo_fichas ADD COLUMN IF NOT EXISTS fuente_titulo TEXT")
    # raw_json eliminada en Fase E (migration d7e9b3c5a8f2).
    conn.execute("ALTER TABLE equipo_fichas ADD COLUMN IF NOT EXISTS enriquecido_at TIMESTAMP")
    conn.execute("ALTER TABLE equipo_fichas ADD COLUMN IF NOT EXISTS enriquecido_fuente TEXT")    # 'firecrawl-bh' | 'firecrawl-oficial' | 'manual'
    # B1 #635: contenido incluido (dim. 3) — [{nombre, cantidad, foto_url?}] editado a mano
    conn.execute("ALTER TABLE equipo_fichas ADD COLUMN IF NOT EXISTS contenido_incluido_json TEXT")

    # ── Etiquetas (bolsa libre / índice de búsqueda) ─────────────────────
    # Las etiquetas son strings libres: incluyen marca, modelo, palabras del
    # nombre, nombres de categorías asignadas y lo que el admin agregue.
    # NO son jerárquicas — la jerarquía vive en la tabla `categorias`.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS etiquetas (
            id     SERIAL PRIMARY KEY,
            nombre TEXT UNIQUE NOT NULL
        )
    """)
    # Columna prioridad legacy — se mantiene pero ya no se usa para ordenar
    # categorías. Queda por compat con datos viejos.
    conn.execute("""
        ALTER TABLE etiquetas
        ADD COLUMN IF NOT EXISTS prioridad INTEGER NOT NULL DEFAULT 100
    """)
    # parent_id legacy: se va a dropear más abajo, después de migrar a `categorias`.
    conn.execute("""
        ALTER TABLE etiquetas
        ADD COLUMN IF NOT EXISTS parent_id INTEGER
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipo_etiquetas (
            equipo_id   INTEGER NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
            etiqueta_id INTEGER NOT NULL REFERENCES etiquetas(id) ON DELETE CASCADE,
            orden       INTEGER DEFAULT 0,
            PRIMARY KEY (equipo_id, etiqueta_id)
        )
    """)
    # `origen` distingue etiquetas auto-generadas (a partir de categorías,
    # marca, modelo, nombre) de las puestas a mano por el admin. Permite
    # regenerar las auto sin tocar las manuales.
    conn.execute("""
        ALTER TABLE equipo_etiquetas
        ADD COLUMN IF NOT EXISTS origen TEXT NOT NULL DEFAULT 'manual'
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_eq_etiq ON equipo_etiquetas(equipo_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_eq_etiq_origen
            ON equipo_etiquetas(equipo_id, origen)
    """)
    # Mismo razonamiento que idx_eq_cat_categoria: el PK no sirve para
    # WHERE etiqueta_id = ? (queries reversas de "qué equipos tienen tag X").
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_eq_etiq_etiqueta ON equipo_etiquetas(etiqueta_id)
    """)

    # ── Categorías (taxonomía dedicada, árbol de 2 niveles) ──────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            id        SERIAL PRIMARY KEY,
            nombre    TEXT UNIQUE NOT NULL,
            prioridad INTEGER NOT NULL DEFAULT 100,
            parent_id INTEGER REFERENCES categorias(id) ON DELETE SET NULL
        )
    """)
    # Idempotente: agregar `visible` para installs viejos sin migration aplicada.
    conn.execute("""
        ALTER TABLE categorias ADD COLUMN IF NOT EXISTS visible BOOLEAN NOT NULL DEFAULT TRUE
    """)
    # Idempotente: plantilla de nombre público por categoría (PR #333).
    conn.execute("""
        ALTER TABLE categorias ADD COLUMN IF NOT EXISTS nombre_publico_template TEXT
    """)
    # `grupo_visual` agrupa varias categorías raíz en un bloque visual del
    # catálogo (ej. Lentes / Adaptadores / Filtros → "Óptica") sin nidos en
    # el modelo de datos. Single source of truth: registry.py.
    conn.execute("""
        ALTER TABLE categorias ADD COLUMN IF NOT EXISTS grupo_visual VARCHAR(64)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cat_prioridad ON categorias(prioridad, nombre)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cat_parent ON categorias(parent_id, prioridad, nombre)
    """)
    # Ranking automático de categorías (#131). Mismo concepto que equipos.
    conn.execute("ALTER TABLE categorias ADD COLUMN IF NOT EXISTS total INT DEFAULT 0")
    conn.execute("ALTER TABLE categorias ADD COLUMN IF NOT EXISTS popularidad_score INT NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE categorias ADD COLUMN IF NOT EXISTS cant_pedidos INT NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE categorias ADD COLUMN IF NOT EXISTS ingreso_total_ars BIGINT NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE categorias ADD COLUMN IF NOT EXISTS ranking_actualizado TIMESTAMP")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipo_categorias (
            equipo_id    INTEGER NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
            categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
            orden        INTEGER DEFAULT 0,
            PRIMARY KEY (equipo_id, categoria_id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_eq_cat ON equipo_categorias(equipo_id)
    """)
    # El PK (equipo_id, categoria_id) sirve para queries por equipo_id, pero no
    # para WHERE categoria_id = ? que se hace en equipos.py:1203,1219,234,248.
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_eq_cat_categoria ON equipo_categorias(categoria_id)
    """)



    # ── Migración: mover nodos del árbol que viven en `etiquetas` → `categorias` ──
    # Esta migración corre una sola vez por el ciclo de vida de cada nombre:
    # busca etiquetas cuyo nombre coincide con un nodo del árbol, mueve sus
    # asignaciones desde `equipo_etiquetas` → `equipo_categorias`, y borra
    # la etiqueta original. Idempotente: si ya está migrada, no encuentra nada.
    legacy_rows = conn.execute("""
        SELECT et.id AS etiq_id, et.nombre, c.id AS cat_id
        FROM etiquetas et
        JOIN categorias c ON c.nombre = et.nombre
    """).fetchall()
    for r in legacy_rows:
        # LEGACY MIGRATION — ver AUD-001: refactorizar a asignar_categorias()
        # del módulo gobernanza_categorias, o borrar si ya no corre.
        conn.execute("""
            INSERT INTO equipo_categorias (equipo_id, categoria_id, orden)
            SELECT equipo_id, %s, orden
            FROM equipo_etiquetas
            WHERE etiqueta_id = %s
            ON CONFLICT (equipo_id, categoria_id) DO NOTHING
        """, (r["cat_id"], r["etiq_id"]))
        # Borrar la etiqueta vieja (CASCADE elimina equipo_etiquetas).
        conn.execute("DELETE FROM etiquetas WHERE id = %s", (r["etiq_id"],))

    # Nota: NO dropeamos `etiquetas.parent_id` (queda como columna legacy
    # ignorada). Eso permite que los endpoints admin viejos sigan funcionando
    # mientras migramos la UI al nuevo CRUD de `categorias`.

    # ── Specs estructurados por categoría (rediseño docs/DISEÑO_SPECS.md - PR A) ──
    #
    # Modelo de specs (registry-driven, composite key por categoría):
    #
    # 1) `spec_definitions` — UNIQUE(categoria_raiz_id, spec_key). Cada cat
    #    raíz es dueña de sus filas; los keys "shared" (lens_mount, formato,
    #    diametro_filtro, peso_g) están duplicados por cat. El motor de
    #    compat matchea por string-equality del spec_key + value.
    #    Single source of truth: `backend/services/specs/registry/`.
    #
    # 2) `categoria_spec_templates` — asigna spec_def a una sub-categoría
    #    con flags overriding (prioridad, destacado, en_card/filtros/nombre).
    #
    # 3) `equipo_specs` — valores concretos por equipo, FK a spec_def.

    conn.execute("""
        CREATE TABLE IF NOT EXISTS spec_definitions (
            id                  SERIAL PRIMARY KEY,
            categoria_raiz_id   INTEGER REFERENCES categorias(id) ON DELETE CASCADE,
            spec_key            VARCHAR(64) NOT NULL,
            label               VARCHAR(120) NOT NULL,
            tipo                VARCHAR(16) NOT NULL,
            unidad              VARCHAR(32),
            enum_options        JSONB,
            ayuda               TEXT,
            es_compatibilidad   BOOLEAN NOT NULL DEFAULT FALSE,
            compatibilidad_modo VARCHAR(16) NOT NULL DEFAULT 'exacta',
            rol_compatibilidad  VARCHAR(16),
            validado            BOOLEAN NOT NULL DEFAULT FALSE,
            tabla_columnas      JSONB,
            output_config       JSONB,
            favorito            BOOLEAN NOT NULL DEFAULT FALSE,
            en_nombre           BOOLEAN NOT NULL DEFAULT FALSE,
            en_filtros          BOOLEAN NOT NULL DEFAULT FALSE,
            prioridad           INTEGER NOT NULL DEFAULT 100,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (categoria_raiz_id, spec_key)
        )
    """)
    # idx_spec_def_categoria se retiró: mismas 2 columnas y mismo orden que el
    # UNIQUE (categoria_raiz_id, spec_key) de arriba — era 100% redundante (ver
    # migración q4r5s6t7u8v9_drop_redundant_plain_indexes).
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_spec_def_compat "
        "ON spec_definitions(spec_key) WHERE es_compatibilidad"
    )
    # Specs free-floating (admin endpoint sin categoría) — partial unique.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_spec_def_global_unique "
        "ON spec_definitions(spec_key) WHERE categoria_raiz_id IS NULL"
    )

    # Catálogo global de unidades (lm, K, V, A, W…). Referenciado por specs
    # tabla con columnas `valor_unidad` para listas cerradas de opciones.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS unidades (
            id          SERIAL PRIMARY KEY,
            simbolo     VARCHAR(16) UNIQUE NOT NULL,
            nombre      VARCHAR(64) NOT NULL,
            dimension   VARCHAR(32),
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_unidades_dimension ON unidades(dimension)"
    )
    # FK al catálogo unidades. El `unidad` VARCHAR de spec_definitions se
    # mantiene como cache denormalizado para evitar JOINs en el hot path
    # (render, listing). El sync `unidad ↔ unidad_id` lo cuida el endpoint
    # PATCH/POST en routes/specs.py.
    conn.execute(
        "ALTER TABLE spec_definitions "
        "ADD COLUMN IF NOT EXISTS unidad_id INTEGER "
        "REFERENCES unidades(id) ON DELETE SET NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_spec_def_unidad_id "
        "ON spec_definitions(unidad_id) WHERE unidad_id IS NOT NULL"
    )
    # Nombre distinto del de arriba (`idx_spec_def_compat`, sobre spec_key): antes
    # ambos se llamaban igual → con IF NOT EXISTS este nunca se creaba (#921).
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_spec_def_es_compat "
        "ON spec_definitions(es_compatibilidad) WHERE es_compatibilidad"
    )
    # aliases: lista de strings usados para match de columnas B&H/CSV.
    # Agregado por migración b3d5e7f9a1c2; lo replicamos en init_db para
    # garantizar la columna pase lo que pase con la cadena de Alembic.
    conn.execute(
        "ALTER TABLE spec_definitions "
        "ADD COLUMN IF NOT EXISTS aliases JSONB NOT NULL DEFAULT '[]'::jsonb"
    )

    # Familias jerárquicas para specs multi_enum (HDMI 1.4 < 2.0 < 2.1, SDI
    # 3G < 6G < 12G, sensor formats, etc.). Editable desde UI admin —
    # antes vivían hardcodeadas en routes/specs.py.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spec_familia_jerarquia (
            id          SERIAL PRIMARY KEY,
            familia     VARCHAR(64) NOT NULL,
            valor       VARCHAR(64) NOT NULL,
            posicion    INTEGER NOT NULL,
            spec_def_id INTEGER REFERENCES spec_definitions(id) ON DELETE CASCADE,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (familia, valor)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fam_jer_familia_pos "
        "ON spec_familia_jerarquia (familia, posicion)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS categoria_spec_templates (
            id                  SERIAL PRIMARY KEY,
            categoria_id        INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
            spec_def_id         INTEGER NOT NULL REFERENCES spec_definitions(id) ON DELETE CASCADE,
            prioridad           INTEGER DEFAULT 100,
            destacado           BOOLEAN DEFAULT FALSE,
            obligatorio         BOOLEAN DEFAULT FALSE,
            visible_en_card     BOOLEAN DEFAULT FALSE,
            visible_en_filtros  BOOLEAN DEFAULT FALSE,
            visible_en_nombre   BOOLEAN DEFAULT FALSE,
            ayuda               TEXT,
            UNIQUE (categoria_id, spec_def_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cst_categoria "
        "ON categoria_spec_templates(categoria_id, prioridad)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cst_def "
        "ON categoria_spec_templates(spec_def_id)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipo_specs (
            equipo_id   INTEGER NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
            spec_def_id INTEGER NOT NULL REFERENCES spec_definitions(id) ON DELETE CASCADE,
            value       TEXT NOT NULL,
            PRIMARY KEY (equipo_id, spec_def_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_equipo_specs_def_value "
        "ON equipo_specs(spec_def_id, value)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_equipo_specs_equipo "
        "ON equipo_specs(equipo_id)"
    )

    # Embudo de alias de valor (rediseño de specs, #1163, Fase 2). Sinónimos
    # que apuntan a un value canónico de un spec enum/multi_enum (ej. "FF" →
    # "Full-frame"). Sirve cuádruple: normaliza al persistir, valida
    # mapeando, alimenta la búsqueda, y de paso arregla la compatibilidad
    # (el motor matchea por igualdad exacta de value — con el embudo, dos
    # equipos que dijeron "FF" y "Full-frame" terminan guardando lo mismo).
    # Tabla (no columna JSONB en spec_definitions): se consulta en las dos
    # direcciones (alias→canónico al persistir, canónico→[alias] al
    # buscar). Todavía sin consumidor (Fase 2, el embudo está apagado) —
    # services/specs/normalize/value_funnel.py la lee, pero coerce/validation
    # no lo llaman hasta la Fase 3. Ver docs/PLAN_SPECS_REDISENO.md.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spec_value_aliases (
            spec_def_id    INTEGER NOT NULL REFERENCES spec_definitions(id) ON DELETE CASCADE,
            alias          TEXT NOT NULL,
            valor_canonico TEXT NOT NULL,
            PRIMARY KEY (spec_def_id, alias)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_value_alias_canon "
        "ON spec_value_aliases(spec_def_id, valor_canonico)"
    )

    # ── Mantenimiento log por equipo ─────────────────────────────────────
    # Una fila por evento de mantenimiento (revisión, reparación, limpieza,
    # etc.). proxima_revision opcional para recordatorios.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipo_mantenimiento (
            id                SERIAL PRIMARY KEY,
            equipo_id         INTEGER NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
            fecha             TIMESTAMP NOT NULL,
            tipo              VARCHAR(32) NOT NULL DEFAULT 'revision',
            descripcion       TEXT,
            costo             INTEGER,
            proxima_revision  TIMESTAMP,
            created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mantenimiento_equipo "
        "ON equipo_mantenimiento(equipo_id, fecha DESC)"
    )
    # Mantenimiento que bloquea disponibilidad: una entrada con bloquea_stock=true
    # y fecha/fecha_hasta saca `cantidad` unidades del equipo durante ese rango.
    # Si fecha_hasta es NULL o bloquea_stock=false, es solo log histórico.
    conn.execute("ALTER TABLE equipo_mantenimiento ADD COLUMN IF NOT EXISTS fecha_hasta TIMESTAMP")
    conn.execute("ALTER TABLE equipo_mantenimiento ADD COLUMN IF NOT EXISTS cantidad INTEGER NOT NULL DEFAULT 1")
    conn.execute("ALTER TABLE equipo_mantenimiento ADD COLUMN IF NOT EXISTS bloquea_stock BOOLEAN NOT NULL DEFAULT FALSE")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mantenimiento_bloqueo "
        "ON equipo_mantenimiento(equipo_id, fecha, fecha_hasta) WHERE bloquea_stock = TRUE"
    )

    # ── Compatibilidades entre equipos (FX3 + Sigma EF → requiere MC-11) ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipo_compatibilidad (
            id            SERIAL PRIMARY KEY,
            equipo_a_id   INTEGER NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
            equipo_b_id   INTEGER NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
            tipo          VARCHAR(32) NOT NULL,
            nota          TEXT,
            adaptador_id  INTEGER REFERENCES equipos(id) ON DELETE SET NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (equipo_a_id, equipo_b_id, tipo),
            CHECK (equipo_a_id != equipo_b_id),
            CHECK (tipo IN ('compatible', 'incompatible', 'requiere_adaptador'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_compat_a ON equipo_compatibilidad(equipo_a_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_compat_b ON equipo_compatibilidad(equipo_b_id)"
    )
    # Metadata para distinguir compat generadas por el skill IA vs manuales
    # del dueño. Las auto se borran/reemplazan en cada regen; manuales nunca.
    conn.execute("ALTER TABLE equipo_compatibilidad ADD COLUMN IF NOT EXISTS auto_generado BOOLEAN NOT NULL DEFAULT FALSE")
    conn.execute("ALTER TABLE equipo_compatibilidad ADD COLUMN IF NOT EXISTS razon_ia TEXT")
    conn.execute("ALTER TABLE equipo_compatibilidad ADD COLUMN IF NOT EXISTS confianza REAL")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_compat_auto "
        "ON equipo_compatibilidad(auto_generado) WHERE auto_generado = TRUE"
    )
    # Timestamp de última pasada del skill por equipo (para encolar pendientes).
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS compat_analizado_at TIMESTAMP")

    # Propuestas IA generadas por el skill gear-compatibility. NUNCA se aplican
    # automáticamente — el dueño las aprueba/descarta desde la UI.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spec_propuestas_pendientes (
            id            SERIAL PRIMARY KEY,
            tipo          VARCHAR(20) NOT NULL,
            payload       JSONB       NOT NULL,
            origen        VARCHAR(64),
            confianza     REAL,
            created_at    TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
            aplicado_at   TIMESTAMP,
            descartado_at TIMESTAMP,
            CHECK (tipo IN ('enum_option', 'spec_nueva', 'merge_specs', 'assign_spec'))
        )
    """)
    # Migration idempotente: si la tabla existe con el CHECK viejo, lo
    # reemplazamos por uno que incluye 'assign_spec'.
    conn.execute("ALTER TABLE spec_propuestas_pendientes DROP CONSTRAINT IF EXISTS spec_propuestas_pendientes_tipo_check")
    conn.execute(
        "ALTER TABLE spec_propuestas_pendientes ADD CONSTRAINT spec_propuestas_pendientes_tipo_check "
        "CHECK (tipo IN ('enum_option', 'spec_nueva', 'merge_specs', 'assign_spec'))"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_propuestas_pendientes "
        "ON spec_propuestas_pendientes(created_at DESC) "
        "WHERE aplicado_at IS NULL AND descartado_at IS NULL"
    )

    # Migration: atribución por equipo (#1203). El productor original (skill
    # gear-compatibility) nunca llegó a escribir acá — el primer productor
    # real fue specs_ingesta (F7, umbral ≥3 HTMLs, agregado sin equipo_id).
    # Este campo habilita un segundo productor: el upload en vivo, que encola
    # CADA par sin match (sin esperar repetición) atribuido al equipo que lo
    # encontró — así el panel admin puede agrupar por label y mostrar qué
    # equipos la tienen, en vez de perder todo lo que ocurre 1-2 veces.
    conn.execute(
        "ALTER TABLE spec_propuestas_pendientes ADD COLUMN IF NOT EXISTS "
        "equipo_id INT REFERENCES equipos(id) ON DELETE CASCADE"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_propuestas_pendientes_equipo "
        "ON spec_propuestas_pendientes(equipo_id) WHERE equipo_id IS NOT NULL"
    )

    # ── Relevancia + ranking + nombre público calculado ────────────────
    # `relevancia_manual`: lo que el admin pone a mano (10=flagship, 100=default).
    # `popularidad_score`: calculado nightly desde historial de pedidos + ingreso.
    # `cant_pedidos` + `ingreso_total_ars`: snapshots para el cálculo y stats.
    # `nombre_publico` + `nombre_publico_largo`: cacheados desde el builder
    # (PR B implementa el builder y los rellena).
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS relevancia_manual INT NOT NULL DEFAULT 100")
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS popularidad_score INT NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS cant_pedidos INT NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS ingreso_total_ars BIGINT NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS ranking_actualizado TIMESTAMP")
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS nombre_publico TEXT")
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS nombre_publico_largo TEXT")
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS nombre_publico_override TEXT")
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS nombre_publico_revisado BOOLEAN DEFAULT FALSE")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_equipos_ranking "
        "ON equipos(relevancia_manual ASC, popularidad_score DESC, nombre ASC)"
    )
    # Índices GIN trigram para la búsqueda fuzzy (backend/busqueda). La expresión
    # es la canónica única (CAMPO_PLANTILLA), la misma que arma busqueda.campo_sql.
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_equipos_nombre_trgm ON equipos USING gin ({CAMPO_PLANTILLA.format(expr='nombre')} gin_trgm_ops)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_equipos_modelo_trgm ON equipos USING gin ({CAMPO_PLANTILLA.format(expr='modelo')} gin_trgm_ops)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_equipos_serie_trgm ON equipos USING gin ({CAMPO_PLANTILLA.format(expr='serie')} gin_trgm_ops)")

    # NOTA: el seed de spec_templates se movió a `seed_spec_templates_after_migrations`
    # invocado desde main.py después de alembic upgrade. El motivo: la migración
    # `unificar_specs_definitions` dropea categoria_spec_templates y equipo_specs
    # y los recrea con un schema nuevo (con spec_def_id). Si el seed corriera
    # antes de alembic en una BD con schema viejo, fallaría con "column
    # spec_def_id does not exist".

    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipo_precio_historial (
            id             SERIAL PRIMARY KEY,
            equipo_id      INTEGER NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
            precio_jornada INTEGER,
            changed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_precio_hist_eq ON equipo_precio_historial(equipo_id)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS kit_componentes (
            id             SERIAL PRIMARY KEY,
            equipo_id      INTEGER NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
            componente_id  INTEGER NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
            cantidad       INTEGER NOT NULL DEFAULT 1,
            UNIQUE(equipo_id, componente_id)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_kit_eq ON kit_componentes(equipo_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_kit_comp ON kit_componentes(componente_id)
    """)
    # Columna orden para kit (migración idempotente)
    conn.execute("""
        ALTER TABLE kit_componentes ADD COLUMN IF NOT EXISTS orden INTEGER NOT NULL DEFAULT 0
    """)
    # A1 #635: columnas para combos (descuento por línea + esencial/best-effort).
    # Schema en init_db (idempotente); el backfill del tipo vive en la migración a1c3b5f7e9d2.
    conn.execute("ALTER TABLE kit_componentes ADD COLUMN IF NOT EXISTS descuento_pct FLOAT NOT NULL DEFAULT 0.0")
    conn.execute("ALTER TABLE kit_componentes ADD COLUMN IF NOT EXISTS esencial BOOLEAN NOT NULL DEFAULT TRUE")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS alquiler_pagos (
            id           SERIAL PRIMARY KEY,
            pedido_id    INTEGER NOT NULL REFERENCES alquileres(id) ON DELETE CASCADE,
            monto        INTEGER NOT NULL,
            concepto     TEXT,
            destinatario TEXT,
            metodo       TEXT,
            fecha        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pagos_pedido ON alquiler_pagos(pedido_id)
    """)

    # destinatario (a quién se cobró: Tincho/Pablo) + metodo (transferencia/
    # efectivo) — esquema en dos capas (MEMORIA 2026-06-03): también en la
    # migración u5v6w7x8y9z0. Nullable a propósito: los pagos previos a junio
    # 2026 son import del sistema anterior y quedan sin especificar ("—").
    conn.execute("ALTER TABLE alquiler_pagos ADD COLUMN IF NOT EXISTS destinatario TEXT")
    conn.execute("ALTER TABLE alquiler_pagos ADD COLUMN IF NOT EXISTS metodo TEXT")

    # Actor + soft-delete con motivo — mismo patrón que `movimientos` (#809),
    # esquema en dos capas (también en la migración a3b4c5d6e7f8). Auditoría
    # 2026-07-02 (#1184): la tabla que alimenta todo el motor contable no
    # respetaba "la plata no se borra" que el resto del motor sí respeta.
    conn.execute("ALTER TABLE alquiler_pagos ADD COLUMN IF NOT EXISTS created_by TEXT")
    conn.execute("ALTER TABLE alquiler_pagos ADD COLUMN IF NOT EXISTS anulado BOOLEAN NOT NULL DEFAULT FALSE")
    conn.execute("ALTER TABLE alquiler_pagos ADD COLUMN IF NOT EXISTS anulado_por TEXT")
    conn.execute("ALTER TABLE alquiler_pagos ADD COLUMN IF NOT EXISTS anulado_at TIMESTAMP")
    conn.execute("ALTER TABLE alquiler_pagos ADD COLUMN IF NOT EXISTS anulado_motivo TEXT")

    # Configuración global de la app (tipo de cambio, defaults, etc.).
    # Es un key-value simple: clave única + valor (string serializado).
    # Se accede vía /api/settings/:key (público read) y PUT /api/admin/settings/:key.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key         VARCHAR(64) PRIMARY KEY,
            value       TEXT NOT NULL,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by  VARCHAR(255)
        )
    """)
    # Seed inicial: tipo de cambio default si no existe.
    # 1000 ARS/USD es un placeholder razonable; el admin lo actualiza
    # cuando entra al panel.
    conn.execute("""
        INSERT INTO app_settings (key, value, updated_by)
        VALUES ('usd_rate', '1000', 'system-seed')
        ON CONFLICT (key) DO NOTHING
    """)
    # Horas mínimas de antelación para que el cliente pueda solicitar
    # una modificación al pedido desde el portal.
    conn.execute("""
        INSERT INTO app_settings (key, value, updated_by)
        VALUES ('modificacion_ventana_horas', '24', 'system-seed')
        ON CONFLICT (key) DO NOTHING
    """)
    # Antelación mínima (lead-time) para que el cliente reserve online (#1126).
    # 0 = apagado (default): el admin lo sube desde /admin/settings cuando quiere
    # exigir un mínimo de horas entre el pedido y el retiro.
    conn.execute("""
        INSERT INTO app_settings (key, value, updated_by)
        VALUES ('antelacion_minima_horas', '0', 'system-seed')
        ON CONFLICT (key) DO NOTHING
    """)
    conn.execute("""
        INSERT INTO app_settings (key, value, updated_by)
        VALUES ('hero_taglines', '[["rental, estudio,","rambla."],["en rambla,","en mardel."],["en rambla,","tu proyecto."],["en rambla,","tu rodaje."]]', 'system-seed')
        ON CONFLICT (key) DO NOTHING
    """)
    # Token del feed iCal de reservas (routes/calendar.py). Vacío = feed
    # deshabilitado; el admin lo genera desde /admin/settings (no se expone
    # por el GET /settings/{key} público).
    conn.execute("""
        INSERT INTO app_settings (key, value, updated_by)
        VALUES ('ical_feed_token', '', 'system-seed')
        ON CONFLICT (key) DO NOTHING
    """)

    # Sugerencias automáticas ignoradas (#352). Cuando el admin descarta una
    # sugerencia, la persistimos por (tipo, ref) para no volver a mostrarla.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sugerencias_ignoradas (
            tipo       TEXT NOT NULL,
            ref        TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (tipo, ref)
        )
    """)

    # Cierres de liquidación (#721). Cerrar un mes congela una FOTO inmutable del
    # reporte de ese mes (los números Y el modelo de comisiones con que se calculó)
    # → cambiar el modelo o editar un pedido viejo ya no reescribe un mes liquidado.
    # `mes` es 'YYYY-MM'. Reabrir = borrar la fila (vuelve a calcularse en vivo).
    # Motor: backend/reportes/cierres.py. Va TAMBIÉN en una migración (esquema en
    # dos capas, decisión 2026-06-03).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS liquidacion_cierres (
            mes           VARCHAR(7) PRIMARY KEY,
            snapshot_json TEXT NOT NULL,
            modelo_json   TEXT NOT NULL,
            cerrado_por   VARCHAR(255),
            cerrado_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Contabilidad (#809): cuentas + gasto_categorias + movimientos ───────
    # Módulo contable (backend/contabilidad/, espejo de reportes/): el libro
    # único de movimientos entre cuentas/cajas con saldos. El ingreso por
    # alquiler NO vive acá — DERIVA de alquiler_pagos (única fuente del cobro,
    # #722); el saldo de la caja de un socio se calcula sumando sus pagos. Acá
    # solo van los movimientos manuales (gasto/transferencia/retiro/aporte) y las
    # cuentas con su saldo inicial. Esquema en dos capas (decisión 2026-06-03):
    # también en la migración x8y9z0a1b2c3.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cuentas (
            id             SERIAL PRIMARY KEY,
            nombre         TEXT NOT NULL,
            tipo           TEXT NOT NULL DEFAULT 'caja',
            socio          TEXT,
            moneda         VARCHAR(3) NOT NULL DEFAULT 'ARS',
            saldo_inicial  INTEGER NOT NULL DEFAULT 0,
            fecha_apertura DATE NOT NULL DEFAULT '2026-06-01',
            activa         BOOLEAN NOT NULL DEFAULT TRUE,
            orden          INTEGER NOT NULL DEFAULT 0,
            created_by     TEXT,
            created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_by     TEXT,
            updated_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # moneda por cuenta (ARS/USD) — a veces se guardan dólares. ADD COLUMN para
    # BDs que ya tenían la tabla (migración d4e5f6a7b8c9).
    conn.execute("ALTER TABLE cuentas ADD COLUMN IF NOT EXISTS moneda VARCHAR(3) NOT NULL DEFAULT 'ARS'")
    # El nombre es único SOLO entre cuentas activas: una cuenta dada de baja
    # (activa=FALSE) deja de bloquear su nombre, así se puede reusar (migración
    # f6a7b8c9d0e1). Se baja el único global viejo y se crea el parcial.
    conn.execute("ALTER TABLE cuentas DROP CONSTRAINT IF EXISTS cuentas_nombre_key")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS cuentas_nombre_activa_uq "
        "ON cuentas(nombre) WHERE activa"
    )
    # Un socio = exactamente una caja ACTIVA (puente 1:1 con
    # alquiler_pagos.destinatario) — único solo entre activas, simétrico con
    # cuentas_nombre_activa_uq: antes (sin `AND activa`) una cuenta de socio
    # desactivada bloqueaba para siempre crear una nueva activa con el mismo
    # socio (auditoría 2026-07-02, migración a4c5d6e7f8g9). El target-less
    # `ON CONFLICT DO NOTHING` del seed de abajo (#932) sigue siendo necesario
    # igual: cubre el caso de una cuenta ACTIVA renombrada que conserva su
    # `socio`, sin depender de cuál de los dos índices la atrape.
    conn.execute("DROP INDEX IF EXISTS idx_cuentas_socio")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_cuentas_socio "
        "ON cuentas(socio) WHERE socio IS NOT NULL AND activa"
    )
    conn.execute("""
        INSERT INTO cuentas (nombre, tipo, socio, moneda, orden) VALUES
            ('Caja Tincho', 'socio', 'Tincho', 'ARS', 1),
            ('Caja Pablo',  'socio', 'Pablo',  'ARS', 2),
            ('Fondo Rental','fondo', 'Rental',  'ARS', 5),
            ('Caja Estudio','fondo', 'Estudio', 'ARS', 6)
        ON CONFLICT DO NOTHING
    """)
    # `ON CONFLICT DO NOTHING` SIN target (no `(nombre) WHERE activa`): la tabla
    # tiene DOS unique (nombre-activo + idx_cuentas_socio sobre socio). Si una
    # cuenta de socio se renombró/desactivó, su nombre sale del índice parcial
    # pero su socio sigue en idx_cuentas_socio → el ON CONFLICT (nombre) no lo
    # atrapaba y el seed reventaba con UniqueViolation en cada boot (#932). Sin
    # target, salta ante CUALQUIER choque → idempotente de verdad.
    # Rental también cobra (default): la caja Fondo Rental representa al cobrador
    # 'Rental'. Backfill para BDs que ya tenían la caja con socio NULL (migración
    # c3d4e5f6a7b8). Idempotente.
    conn.execute(
        "UPDATE cuentas SET socio = 'Rental' WHERE nombre = 'Fondo Rental' AND socio IS NULL"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gasto_categorias (
            id     SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL UNIQUE,
            activa BOOLEAN NOT NULL DEFAULT TRUE,
            orden  INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        INSERT INTO gasto_categorias (nombre, orden) VALUES
            ('Alquiler local', 1), ('Sueldos', 2), ('Equipos', 3),
            ('Mantenimiento', 4), ('Impuestos', 5), ('Servicios', 6),
            ('Otros', 99)
        ON CONFLICT (nombre) DO NOTHING
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS movimientos (
            id                SERIAL PRIMARY KEY,
            tipo              TEXT NOT NULL,
            monto             INTEGER NOT NULL CHECK (monto > 0),
            cuenta_origen_id  INTEGER REFERENCES cuentas(id),
            cuenta_destino_id INTEGER REFERENCES cuentas(id),
            categoria_id      INTEGER REFERENCES gasto_categorias(id),
            metodo            TEXT,
            fecha             DATE NOT NULL DEFAULT CURRENT_DATE,
            nota              TEXT,
            comprobante_url   TEXT,
            comprobante_key   TEXT,
            rendicion_mes     VARCHAR(7),
            es_rendicion      BOOLEAN NOT NULL DEFAULT FALSE,
            created_by        TEXT,
            created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_by        TEXT,
            updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            anulado           BOOLEAN NOT NULL DEFAULT FALSE,
            anulado_por       TEXT,
            anulado_at        TIMESTAMP,
            anulado_motivo    TEXT,
            CONSTRAINT mov_tiene_cuenta CHECK (cuenta_origen_id IS NOT NULL OR cuenta_destino_id IS NOT NULL),
            CONSTRAINT mov_cuentas_distintas CHECK (cuenta_origen_id IS DISTINCT FROM cuenta_destino_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mov_fecha ON movimientos(fecha)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mov_origen ON movimientos(cuenta_origen_id) WHERE NOT anulado"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mov_destino ON movimientos(cuenta_destino_id) WHERE NOT anulado"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mov_rendicion ON movimientos(rendicion_mes) WHERE es_rendicion"
    )
    # beneficiario: a quién / para qué es el movimiento (ej. "Jimena") — etiqueta
    # parseable y reutilizable (migración e5f6a7b8c9d0).
    conn.execute("ALTER TABLE movimientos ADD COLUMN IF NOT EXISTS beneficiario TEXT")
    # Cambio de divisa (comprar/vender USD con ARS): dos `ajuste` atados. `cotizacion`
    # guarda los pesos por dólar usados (informativo, no recalculado); `movimiento_par_id`
    # linkea la pata origen↔destino entre sí (self-FK, se completa después de insertar
    # ambas filas — no hay forma de conocer el id de la otra pata al insertar la primera).
    # `commands/movimientos.py::crear_cambio_divisa` es la única puerta que las escribe
    # (migración z9y8x7w6v5u4).
    conn.execute("ALTER TABLE movimientos ADD COLUMN IF NOT EXISTS cotizacion NUMERIC(12,4)")
    conn.execute(
        "ALTER TABLE movimientos ADD COLUMN IF NOT EXISTS movimiento_par_id INTEGER "
        "REFERENCES movimientos(id)"
    )
    # Cierres contables (#809, Fase 6): congelan un mes (foto + traba la edición de
    # movimientos de ese mes). Espejo de la migración b2c3d4e5f6a7.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contabilidad_cierres (
            mes           VARCHAR(7) PRIMARY KEY,
            snapshot_json TEXT NOT NULL,
            cerrado_por   VARCHAR(255),
            cerrado_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Reconciliación con migraciones ──────────────────────────────────────
    # Estas tablas/columnas históricamente vivían SOLO en migraciones Alembic.
    # Las replicamos acá (idempotente) para que init_db produzca un esquema
    # COMPLETO aunque `alembic upgrade` falle (paso defensivo: ya ocurrió una
    # falla silenciosa con equipos.slug). Mantener en sync con migrations/.

    # descuentos por jornada (migración a3e7f1d2b8c4)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS descuentos_jornada (
            id         SERIAL PRIMARY KEY,
            jornadas   INTEGER NOT NULL UNIQUE,
            pct        NUMERIC(5,2) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # NUMERIC(5,2), no FLOAT — mismo tipo que la migración g1a2b3c4d5e6 le dio a las
    # otras 3 columnas de descuento (drift detectado en la Fase B de #1219: un bootstrap
    # 100% vía init_db(), sin Alembic, quedaba con esta columna en un tipo distinto).
    conn.execute("ALTER TABLE alquileres ADD COLUMN IF NOT EXISTS descuento_jornadas_pct NUMERIC(5,2) DEFAULT 0")
    # Snapshot del descuento del CLIENTE al momento del último recálculo (Fase
    # C-1, #1219) — mismo patrón que descuento_jornadas_pct de arriba: sin esto,
    # `desglose_de_pedido` tendría que leer `clientes.descuento` EN VIVO para
    # mostrar el desglose de un pedido ya confirmado, y si el cliente cambia su
    # descuento después de confirmar, el desglose (bruto/neto mostrados)
    # divergiría de `monto_total` ya persistido — la clase de bug "dos cálculos
    # del mismo número" (#405). `alquileres.descuento_pct` es el override MANUAL
    # (0 = sin override); esta columna es la contribución del cliente, congelada
    # igual que jornadas — se refresca en cada recálculo real (edición del admin,
    # o el presupuesto siguiendo al cliente en vivo).
    conn.execute("ALTER TABLE alquileres ADD COLUMN IF NOT EXISTS descuento_cliente_pct NUMERIC(5,2) DEFAULT 0")
    # Override manual en % o en $ fijo (Fase C-2, #1219): `descuento_manual_tipo`
    # decide cómo se interpreta el override de ESTE pedido — 'pct' (de siempre,
    # usa `descuento_pct`) o 'monto' (usa `descuento_manual_monto`, pesos fijos,
    # capeado a `bruto` en `descuentos.queries.decision.resolver_descuento_monto_pedido`
    # para que el neto nunca sea negativo). Mismo campo de la UI, un selector al
    # lado. Default 'pct' + monto=0 → comportamiento IDÉNTICO a antes de C-2.
    conn.execute("ALTER TABLE alquileres ADD COLUMN IF NOT EXISTS descuento_manual_tipo VARCHAR(10) DEFAULT 'pct'")
    conn.execute("ALTER TABLE alquileres ADD COLUMN IF NOT EXISTS descuento_manual_monto INTEGER DEFAULT 0")
    # descuento_pct NUMERIC(5,2) → NUMERIC(7,4): el toggle %/$ del builder
    # convierte el override manual al equivalente de la otra unidad — con solo
    # 2 decimales, la ida y vuelta %→$→% perdía unos pesos en el redondeo
    # intermedio (#1219). Idempotente (no-op si ya está migrado); también en
    # migración w1x2y3z4a5b6.
    conn.execute("""
        DO $$
        BEGIN
            IF (SELECT numeric_scale FROM information_schema.columns
                WHERE table_name = 'alquileres' AND column_name = 'descuento_pct') = 2 THEN
                ALTER TABLE alquileres ALTER COLUMN descuento_pct TYPE NUMERIC(7,4)
                    USING descuento_pct::NUMERIC(7,4);
            END IF;
        END $$;
    """)
    # ⏰ LEGACY: columna HUÉRFANA — el feature "forzar 0%" (Fase C-4, #1231, el
    # toggle "Forzar este valor") se removió porque el override manual ya gana
    # outright cuando está puesto y no hay descuentos fijos por cliente, así que
    # forzar 0% nunca hacía falta. La columna se DEJA (nada la lee/escribe, queda
    # en su default FALSE) en vez de droparla en el mismo release: las migraciones
    # corren al startup y el contenedor viejo podría leer una columna ya borrada
    # durante el solapamiento del deploy. Droppear en una migración futura, una vez
    # que esta remoción esté 100% en prod.
    conn.execute("ALTER TABLE alquileres ADD COLUMN IF NOT EXISTS descuento_manual_activo BOOLEAN NOT NULL DEFAULT FALSE")

    # email infra (migración a4e8c2b9d710)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_templates (
            key        TEXT PRIMARY KEY,
            subject    TEXT NOT NULL,
            body_html  TEXT NOT NULL,
            body_text  TEXT NOT NULL,
            enabled    BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT
        )
    """)
    # On/off por plantilla (Fase B mails): apagar un mail automático sin tocar
    # código. `send_email` lo respeta. ADD COLUMN idempotente para BDs que ya
    # tenían la tabla (CREATE IF NOT EXISTS no agrega columnas nuevas). Espeja la
    # migración r2s3t4u5v6w7.
    conn.execute(
        "ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE"
    )
    # Seed idempotente de las plantillas del sistema (esquema en dos capas, MEMORIA
    # 2026-06-03): el contenido vivía SOLO en migraciones, así que con las
    # migraciones trabadas la tabla quedaba vacía y la sección /admin/email-templates
    # no tenía nada que abrir ni previsualizar. La fuente única forward del copy
    # es services/email/default_templates.py. ON CONFLICT DO NOTHING respeta lo
    # que ya exista (filas migradas o editadas por un admin).
    from services.email.default_templates import DEFAULT_TEMPLATES
    for _key, _tpl in DEFAULT_TEMPLATES.items():
        conn.execute(
            """
            INSERT INTO email_templates (key, subject, body_html, body_text, updated_by)
            VALUES (%s, %s, %s, %s, 'system:migration')
            ON CONFLICT (key) DO NOTHING
            """,
            (_key, _tpl["subject"], _tpl["body_html"], _tpl["body_text"]),
        )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS emails_log (
            id           BIGSERIAL PRIMARY KEY,
            to_addr      TEXT NOT NULL,
            subject      TEXT NOT NULL,
            template_key TEXT NOT NULL,
            alquiler_id  INTEGER REFERENCES alquileres(id) ON DELETE SET NULL,
            status       TEXT NOT NULL,
            provider     TEXT NOT NULL,
            provider_id  TEXT,
            error        TEXT,
            sent_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_log_alquiler ON emails_log(alquiler_id)")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_emails_log_recordatorio
        ON emails_log(alquiler_id, template_key)
        WHERE template_key = 'recordatorio_retiro' AND status = 'sent'
    """)

    # whatsapp_log: bitácora de envíos del canal WhatsApp (migración
    # w1h2a3t4s5a6). Espeja emails_log; su índice único parcial da idempotencia
    # por pedido (un envío 'sent' por (alquiler_id, template_key)) — clave porque
    # el gate de los jobs es una var en memoria que se resetea en cada restart.
    # Sin `cliente_id`: espeja emails_log (que tampoco lo tiene) — keyea por
    # alquiler_id, que sobrevive un merge de cuentas con el pedido; así NO suma
    # una FK a `clientes` que habría que clasificar en identity/merge (el cliente
    # se deriva por join a alquileres si hace falta).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_log (
            id           BIGSERIAL PRIMARY KEY,
            to_phone     TEXT NOT NULL,
            template_key TEXT NOT NULL,
            alquiler_id  INTEGER REFERENCES alquileres(id) ON DELETE SET NULL,
            status       TEXT NOT NULL,
            wamid        TEXT,
            error        TEXT,
            sent_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_whatsapp_log_alquiler ON whatsapp_log(alquiler_id)")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_log_idempotente
        ON whatsapp_log(alquiler_id, template_key, to_phone)
        WHERE status = 'sent'
    """)
    # Estado de entrega REAL, que llega por webhook (delivered/read/failed) —
    # `status` NO se toca (sostiene el índice único de arriba); son columnas
    # aparte, siempre nullable, que el webhook completa best-effort (migración
    # w3bh00k1nb0x). `wamid` (ya existe) es la clave para cruzar el evento con
    # la fila.
    conn.execute("ALTER TABLE whatsapp_log ADD COLUMN IF NOT EXISTS delivery_status TEXT")
    conn.execute("ALTER TABLE whatsapp_log ADD COLUMN IF NOT EXISTS delivery_error TEXT")
    conn.execute("ALTER TABLE whatsapp_log ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ")
    # Opt-in de WhatsApp por cliente (Meta exige consentimiento demostrable para
    # utility templates). Default FALSE: no se le manda a nadie hasta que acepta.
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS whatsapp_opt_in BOOLEAN NOT NULL DEFAULT FALSE")
    conn.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS whatsapp_opt_in_at TIMESTAMPTZ")

    # equipos.slug (migraciones e4a7c1f8d6b2 + f5b8d2e4a9c1): columna + UNIQUE
    # constraint completo (no partial index — ese era transicional).
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS slug VARCHAR(80)")
    # A1 #635: tipo de producto (simple/kit/combo). DEFAULT 'simple'; el backfill
    # (kits con componentes → 'kit') y el CHECK viven en la migración a1c3b5f7e9d2.
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS tipo TEXT NOT NULL DEFAULT 'simple'")
    conn.execute("ALTER TABLE equipos ADD COLUMN IF NOT EXISTS destacado BOOLEAN DEFAULT FALSE")
    conn.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'equipos_slug_key' AND conrelid = 'equipos'::regclass
            ) AND NOT EXISTS (
                SELECT 1 FROM equipos WHERE slug IS NOT NULL
                GROUP BY slug HAVING COUNT(*) > 1
            ) THEN
                ALTER TABLE equipos ADD CONSTRAINT equipos_slug_key UNIQUE (slug);
            END IF;
        END $$;
    """)
    # Backfill de slugs faltantes (fuente única; idempotente). Acá, en el
    # bootstrap, en vez del viejo self-heal que vivía dentro del export (#922).
    from dataio.slug import backfill_equipos_slug
    backfill_equipos_slug(conn)

    # JSONB agregadas por migraciones (d7c9e1f3a8b2)
    conn.execute("ALTER TABLE spec_definitions ADD COLUMN IF NOT EXISTS tabla_columnas JSONB")

    # Canonización de spec_keys (#535): renombres idempotentes en spec_definitions.
    # ORDEN CRÍTICO: esto corre en init_db (siempre, antes del seeder y sin depender
    # de Alembic) para que el seeder NO purgue la key vieja con CASCADE — eso borraría
    # los equipo_specs de esos specs. El rename preserva la MISMA fila (mismo id), así
    # que equipo_specs y categoria_spec_templates quedan intactos (FK por id, no por key).
    # Guard NOT EXISTS: evita violar UNIQUE(categoria_raiz_id, spec_key) si la canónica
    # ya existiera (un merge real se resolvería en migración, no acá).
    from services.categorias.queries.ancestry import buscar_id_por_nombre
    camaras_id = buscar_id_por_nombre(conn, 'Cámaras')
    lentes_id = buscar_id_por_nombre(conn, 'Lentes')
    conn.execute("""
        UPDATE spec_definitions sd
           SET spec_key = 'consumo_w', label = 'Consumo eléctrico', updated_at = NOW()
         WHERE sd.spec_key = 'power_consumption_w'
           AND sd.categoria_raiz_id = %s
           AND NOT EXISTS (
               SELECT 1 FROM spec_definitions x
                WHERE x.categoria_raiz_id = sd.categoria_raiz_id AND x.spec_key = 'consumo_w'
           )
    """, (camaras_id,))
    conn.execute("""
        UPDATE spec_definitions sd
           SET spec_key = 'distancia_minima_cm', updated_at = NOW()
         WHERE sd.spec_key = 'distancia_minima_m'
           AND sd.categoria_raiz_id = %s
           AND NOT EXISTS (
               SELECT 1 FROM spec_definitions x
                WHERE x.categoria_raiz_id = sd.categoria_raiz_id AND x.spec_key = 'distancia_minima_cm'
           )
    """, (lentes_id,))

    # Fechas TEXT → tipo nativo (migración e2c6f4a8b1d7). Las fechas se
    # guardaban como strings ISO; ahora son TIMESTAMP/DATE. Idempotente: solo
    # convierte si la columna sigue siendo 'text'. Defensivo: limpia valores
    # no-ISO a NULL antes del cast y re-aplica NOT NULL solo si quedó limpio.
    for tabla, col, tipo, not_null in (
        ("alquileres", "fecha_desde", "timestamp", False),
        ("alquileres", "fecha_hasta", "timestamp", False),
        ("equipo_mantenimiento", "fecha", "timestamp", True),
        ("equipo_mantenimiento", "fecha_hasta", "timestamp", False),
        ("equipo_mantenimiento", "proxima_revision", "timestamp", False),
        ("alquiler_pagos", "fecha", "timestamp", False),
        ("equipos", "fecha_compra", "date", False),
    ):
        renotnull = (
            f"IF NOT EXISTS (SELECT 1 FROM {tabla} WHERE {col} IS NULL) THEN "
            f"ALTER TABLE {tabla} ALTER COLUMN {col} SET NOT NULL; END IF;"
            if not_null else ""
        )
        conn.execute(f"""
            DO $$
            BEGIN
                IF (SELECT data_type FROM information_schema.columns
                    WHERE table_name = '{tabla}' AND column_name = '{col}') = 'text' THEN
                    ALTER TABLE {tabla} ALTER COLUMN {col} DROP NOT NULL;
                    UPDATE {tabla} SET {col} = NULL
                        WHERE {col} !~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}';
                    ALTER TABLE {tabla} ALTER COLUMN {col} TYPE {tipo}
                        USING NULLIF(TRIM({col}), '')::{tipo};
                    {renotnull}
                END IF;
            END $$;
        """)

    # ── Estudio (singleton E1) ──────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS estudio (
            id             SERIAL PRIMARY KEY,
            equipo_id      INTEGER,
            nombre         TEXT NOT NULL DEFAULT 'El Estudio',
            tagline        TEXT NOT NULL DEFAULT '',
            descripcion    TEXT NOT NULL DEFAULT '',
            precio_hora    INTEGER NOT NULL DEFAULT 0,
            min_horas      INTEGER NOT NULL DEFAULT 2,
            open_hour      INTEGER NOT NULL DEFAULT 8,
            close_hour     INTEGER NOT NULL DEFAULT 22,
            buffer_horas   INTEGER NOT NULL DEFAULT 0,
            pack_activo    BOOLEAN NOT NULL DEFAULT TRUE,
            pack_nombre    TEXT NOT NULL DEFAULT '',
            pack_descripcion TEXT NOT NULL DEFAULT '',
            pack_precio    INTEGER NOT NULL DEFAULT 0,
            features_json  TEXT,
            faq_json       TEXT,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS estudio_fotos (
            id           SERIAL PRIMARY KEY,
            estudio_id   INTEGER NOT NULL REFERENCES estudio(id) ON DELETE CASCADE,
            url          TEXT NOT NULL,
            path         TEXT,
            orden        INTEGER NOT NULL DEFAULT 0,
            es_principal BOOLEAN NOT NULL DEFAULT FALSE,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_estudio_fotos_estudio_orden
        ON estudio_fotos(estudio_id, orden)
    """)
    # E2.1: anticipación mínima de reserva del estudio (en horas). Solo aplica
    # al espacio (no a equipos). 0 = sin tope.
    conn.execute("ALTER TABLE estudio ADD COLUMN IF NOT EXISTS anticipacion_min_horas INTEGER NOT NULL DEFAULT 0")
    # Ficha pública: ubicación + prueba social (editables desde el back-office).
    conn.execute("ALTER TABLE estudio ADD COLUMN IF NOT EXISTS direccion TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE estudio ADD COLUMN IF NOT EXISTS como_llegar TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE estudio ADD COLUMN IF NOT EXISTS testimonios_json TEXT")
    # Mapa: el dueño pega un link/iframe; el backend lo parsea y guarda ambos.
    conn.execute("ALTER TABLE estudio ADD COLUMN IF NOT EXISTS mapa_url TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE estudio ADD COLUMN IF NOT EXISTS mapa_embed_url TEXT NOT NULL DEFAULT ''")
    # E4: slots fijos recurrentes mensuales (ej. "miércoles 8-20 Filmar $X jun-dic").
    # Bloquean su franja para el público mientras el rango de meses esté activo y
    # generan un pedido por mes (tipo='estudio_fijo') para estadísticas + pagos.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS estudio_slots_fijos (
            id            SERIAL PRIMARY KEY,
            cliente       TEXT NOT NULL,
            dia_semana    INTEGER NOT NULL,        -- 0=Lunes .. 6=Domingo (date.weekday())
            hora_desde    INTEGER NOT NULL,        -- hora entera 0-24
            hora_hasta    INTEGER NOT NULL,
            valor_mensual INTEGER NOT NULL DEFAULT 0,
            mes_desde     TEXT NOT NULL,           -- 'YYYY-MM'
            mes_hasta     TEXT NOT NULL,           -- 'YYYY-MM'
            activo        BOOLEAN NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Vincula cada pedido mensual generado con su slot, para regenerar futuros sin
    # tocar pasados/pagados. NULL en todo pedido normal → cero impacto.
    conn.execute("ALTER TABLE alquileres ADD COLUMN IF NOT EXISTS estudio_slot_id INTEGER REFERENCES estudio_slots_fijos(id) ON DELETE SET NULL")
    # v2-C: pack curado. El admin elige a mano qué equipos integran el pack
    # (reemplaza "todo lo de las categorías Grip/Iluminación/Modificadores"). La
    # disponibilidad de la franja sigue saliendo del motor sagrado.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS estudio_pack_equipos (
            id          SERIAL PRIMARY KEY,
            estudio_id  INTEGER NOT NULL REFERENCES estudio(id) ON DELETE CASCADE,
            equipo_id   INTEGER NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
            orden       INTEGER NOT NULL DEFAULT 0,
            UNIQUE (estudio_id, equipo_id)
        )
    """)
    # Promo combo (#1283 Fase 5): reemplaza al pack curado por un equipo real
    # tipo='combo' (dueno='Rental', oculto del catálogo) — el precio deriva de
    # sus componentes (precio_combo) en vez de un `pack_precio` fijo suelto.
    # NULL = todavía no se creó (el pack sigue siendo el mecanismo vigente,
    # ⏰ LEGACY hasta que la Fase 8 lo retire). ON DELETE SET NULL: si el combo
    # se borra, el estudio no rompe — vuelve al estado "sin promo".
    conn.execute("ALTER TABLE estudio ADD COLUMN IF NOT EXISTS promo_combo_id INTEGER REFERENCES equipos(id) ON DELETE SET NULL")
    # Add-on "recién pintado" (#1300 seguimiento): cargo fijo opcional, independiente
    # de la promo/sueltos — el cliente lo tilda aparte, no reemplaza ninguna opción.
    # 0 = todavía no lo cargó el dueño (el checkbox sigue disponible, sin costo).
    conn.execute("ALTER TABLE estudio ADD COLUMN IF NOT EXISTS precio_pintura_reciente INTEGER NOT NULL DEFAULT 0")
    # Anticipación PROPIA del add-on "recién pintado" (#1300 seguimiento): pintar/
    # secar el ciclorama necesita más lead time que una reserva común —
    # independiente de `anticipacion_min_horas` (se exige ADEMÁS, no en su lugar).
    # 0 = sin restricción extra (mismo criterio "apagado por default" que el resto
    # de las anticipaciones del repo).
    conn.execute("ALTER TABLE estudio ADD COLUMN IF NOT EXISTS anticipacion_pintura_horas INTEGER NOT NULL DEFAULT 0")

    # Registro de búsquedas del catálogo público (analítica interna). Acompaña a
    # la migración i1c2d3e4f5a6 — acá garantizamos su creación en cada boot
    # (init_db corre siempre y es idempotente), sin depender de la cadena de
    # alembic. query_text = término crudo; query_norm = normalizado para agrupar.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS search_queries (
            id           SERIAL PRIMARY KEY,
            query_text   VARCHAR(120) NOT NULL,
            query_norm   VARCHAR(120) NOT NULL,
            result_count INTEGER NOT NULL DEFAULT 0,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_search_queries_norm ON search_queries(query_norm)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_search_queries_created ON search_queries(created_at)"
    )
    # Click-through: qué resultado abre el usuario tras una búsqueda. Es la señal
    # que faltaba para, a futuro, aprender qué encontró la gente (ranking por
    # comportamiento, sinónimos). Cada fila liga una search_queries con el equipo
    # que se abrió. Acompaña a la migración s3t4u5v6w7x8 (esquema en dos capas).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS search_clicks (
            id           SERIAL PRIMARY KEY,
            query_id     INTEGER NOT NULL REFERENCES search_queries(id) ON DELETE CASCADE,
            equipo_id    INTEGER REFERENCES equipos(id) ON DELETE SET NULL,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_search_clicks_query ON search_clicks(query_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_search_clicks_equipo ON search_clicks(equipo_id)"
    )
    # Seed idempotente: inserta la fila singleton si no existe, con los valores
    # del copy original de src/data/studio.ts. Precios en 0 (el dueño los setea).
    import json as _json
    # Lista canónica de 16 features. Las con value="" se ocultan del público
    # (filtro en src/routes/estudio.tsx) y solo aparecen en /admin/estudio
    # como casilleros para que el dueño los complete a medida.
    _features_seed = _json.dumps([
        {"label": "Superficie", "value": ""},
        {"label": "Altura", "value": ""},
        {"label": "Ciclorama", "value": "6×6 m"},
        {"label": "Climatización", "value": "Sí"},
        {"label": "Living", "value": "Sí"},
        {"label": "Área de trabajo", "value": "Sí"},
        {"label": "Entrada para autos", "value": "Sí"},
        {"label": "Cocina", "value": "Sí"},
        {"label": "WiFi", "value": ""},
        {"label": "Camarín / vestuario", "value": ""},
        {"label": "Potencia eléctrica", "value": ""},
        {"label": "Insonorización", "value": ""},
        {"label": "Pet friendly", "value": ""},
        {"label": "Acceso 24h", "value": ""},
        {"label": "Estacionamiento", "value": ""},
        {"label": "Rigging / tomas de techo", "value": ""},
    ])
    _faq_seed = _json.dumps([
        {"q": "¿Cuál es el mínimo de reserva?",
         "a": "El mínimo es de 2 horas. Para producciones más cortas, escribínos por WhatsApp y vemos."},
        {"q": "¿Cómo se abona?",
         "a": "Aceptamos transferencia bancaria, MercadoPago y efectivo. Se reserva con un 50% del total al confirmar la fecha."},
        {"q": "¿Puedo llevar equipo extra?",
         "a": "Sí, podés traer cualquier equipo propio. Si necesás algo puntual también podés alquilarlo en Rambla y armar todo en un único pedido."},
        {"q": "¿Tienen estacionamiento?",
         "a": "Estacionamiento sobre la calle (zona azul gratuita los fines de semana). Para descarga rápida de equipos hay acceso directo."},
        {"q": "¿Incluye asistente / iluminador?",
         "a": "Por defecto el estudio se reserva sin staff. Si necesás un asistente o iluminador, lo coordinamos aparte — escribínos antes."},
        {"q": "¿Puedo cancelar o reagendar?",
         "a": "Hasta 48 hs antes del shoot podés reagendar sin costo. Cancelaciones con menos aviso pierden la seña."},
    ])
    conn.execute("""
        INSERT INTO estudio (
            id, nombre, tagline, descripcion,
            precio_hora, min_horas, open_hour, close_hour, buffer_horas,
            pack_activo, pack_nombre, pack_descripcion, pack_precio,
            features_json, faq_json
        )
        SELECT
            1,
            'El Estudio',
            'Foto y video en Mar del Plata',
            'Un espacio para producciones audiovisuales con todos los equipos de Rambla Rental a mano. '
            'Ideal para rodajes grandes — flexible para los chicos.',
            0, 2, 8, 22, 0,
            TRUE,
            'Pack Todo Incluido',
            'Todas las luces y griperías del estudio sin pensar en sumar ítem por ítem. '
            'Llegás con la cámara y filmás.',
            0,
            %s,
            %s
        WHERE NOT EXISTS (SELECT 1 FROM estudio WHERE id = 1)
    """, (_features_seed, _faq_seed))

    # Centinela del Estudio (E2): el espacio físico modelado como un equipo de
    # cantidad=1, para que las reservas por hora reusen el motor de stock/overlap
    # SAGRADO sin lógica nueva. Es un recurso interno: invisible al catálogo,
    # filtros, listado admin, ranking y specs (es_recurso_interno=TRUE). Idempotente:
    # solo se crea si el estudio todavía no tiene un equipo asociado.
    # `dueno='Estudio'` (economía separada, Fase 4 de #1283 — antes 'Rambla'): las
    # horas del espacio se atribuyen al Estudio en la liquidación/P&L, no a Rambla
    # rental. Una BD que YA tenía el centinela con dueno='Rambla' la migra la
    # migración de backfill (esquema en dos capas para este dato puntual).
    est_row = conn.execute("SELECT equipo_id FROM estudio WHERE id = 1").fetchone()
    if est_row is not None and est_row["equipo_id"] is None:
        cur_cent = conn.execute("""
            INSERT INTO equipos (nombre, cantidad, visible_catalogo, dueno, es_recurso_interno)
            VALUES ('Estudio (espacio)', 1, 0, 'Estudio', TRUE)
            RETURNING id
        """)
        centinela_id = cur_cent.fetchone()["id"]
        conn.execute("UPDATE estudio SET equipo_id = %s WHERE id = 1", (centinela_id,))

    # ── Media pipeline no-destructivo (F1 — i1j2k3l4m5n6) ──────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS media_assets (
            id           BIGSERIAL PRIMARY KEY,
            kind         TEXT NOT NULL,
            original_key TEXT,
            original_ct  TEXT,
            width        INTEGER,
            height       INTEGER,
            bytes        INTEGER,
            content_hash TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        ALTER TABLE media_assets
        ADD COLUMN IF NOT EXISTS content_hash TEXT
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_media_assets_kind_hash
        ON media_assets(kind, content_hash)
        WHERE content_hash IS NOT NULL
    """)
    conn.execute("ALTER TABLE media_assets ADD COLUMN IF NOT EXISTS lqip TEXT")
    conn.execute("ALTER TABLE media_assets ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'ready'")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS media_variants (
            id           BIGSERIAL PRIMARY KEY,
            asset_id     BIGINT NOT NULL REFERENCES media_assets(id) ON DELETE CASCADE,
            name         TEXT NOT NULL,
            key          TEXT,
            url          TEXT,
            content_type TEXT NOT NULL DEFAULT 'image/webp',
            width        INTEGER,
            height       INTEGER,
            bytes        INTEGER,
            params       JSONB DEFAULT '{}',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(asset_id, name)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_media_variants_asset
        ON media_variants(asset_id)
    """)
    conn.execute("ALTER TABLE estudio_fotos ADD COLUMN IF NOT EXISTS media_id BIGINT REFERENCES media_assets(id) ON DELETE SET NULL")
    conn.execute("ALTER TABLE estudio_fotos ADD COLUMN IF NOT EXISTS url_sm TEXT")
    conn.execute("ALTER TABLE estudio_fotos ADD COLUMN IF NOT EXISTS url_avif TEXT")
    conn.execute("ALTER TABLE estudio_fotos ADD COLUMN IF NOT EXISTS url_sm_avif TEXT")

    # ── Galería multi-foto de equipos (F2 — k1l2m3n4o5p6) ───────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipo_fotos (
            id           SERIAL PRIMARY KEY,
            equipo_id    INTEGER NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
            media_id     BIGINT REFERENCES media_assets(id) ON DELETE SET NULL,
            url          TEXT NOT NULL,
            path         TEXT,
            orden        INTEGER NOT NULL DEFAULT 0,
            es_principal BOOLEAN NOT NULL DEFAULT FALSE,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_equipo_fotos_equipo_orden
        ON equipo_fotos(equipo_id, orden)
    """)
    conn.execute("ALTER TABLE marcas ADD COLUMN IF NOT EXISTS media_id BIGINT REFERENCES media_assets(id) ON DELETE SET NULL")

    # ── Talleres (workshops públicos con formulario de inscripción) ──────────
    # Concepto (F1-F3 lo redujeron a datos estables): fechas/precio/cupos/pago/
    # dirección/tipo viven en `ediciones_taller`; instructor(es) en `instructores`
    # + `taller_instructores`; el contenido de clase en `clases_taller`. Escuela
    # v2 F6 retiró las columnas legacy que las duplicaban acá (ver migración
    # esc7l8i9m0p1 + docs/MEMORIA.md 2026-07-23 — Escuela v2 F6).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS talleres (
            id                   SERIAL PRIMARY KEY,
            slug                 VARCHAR(120) NOT NULL UNIQUE,
            nombre               TEXT NOT NULL,
            subtitulo            TEXT NOT NULL DEFAULT '',
            descripcion          TEXT NOT NULL DEFAULT '',
            publico_objetivo     TEXT NOT NULL DEFAULT '',
            notif_email          TEXT NOT NULL DEFAULT '',
            activo               BOOLEAN NOT NULL DEFAULT TRUE,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS taller_inscripciones (
            id              SERIAL PRIMARY KEY,
            taller_id       INTEGER NOT NULL REFERENCES talleres(id) ON DELETE CASCADE,
            nombre          TEXT NOT NULL,
            email           TEXT NOT NULL,
            telefono        TEXT NOT NULL,
            experiencia     TEXT,
            comprobante_url TEXT,
            en_lista_espera BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_taller_inscripciones_taller "
        "ON taller_inscripciones(taller_id)"
    )
    conn.execute("ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS comprobante_key TEXT")
    # Escuela v2 F2: T&C propios del taller ('' → linkea /terminos general),
    # beneficios ("15% off en rental..."), pregunta del form configurable
    # ('' → default actual) y mensaje de confirmación post-inscripción.
    conn.execute("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS terminos TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS beneficios TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS pregunta_experiencia TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS mensaje_confirmacion TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS tyc_aceptado_at TIMESTAMPTZ")
    # Escuela v2 F4c: FAQ editable del taller — [{pregunta, respuesta}]. El
    # admin arma la lista de a una (hay preguntas sugeridas precargables en
    # el front); ninguna es obligatoria.
    conn.execute("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS faqs JSONB NOT NULL DEFAULT '[]'")
    # Escuela v2 F7: resumen corto para la TARJETA del listado (mezcla "para
    # quién es" + "de qué trata") — `descripcion` es el texto largo de la
    # página propia, pensado para leerse completo, no truncado a 2 líneas.
    # '' → el front cae a `descripcion` truncada (cero ruptura para talleres
    # que nunca lo cargan).
    conn.execute("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS resumen TEXT NOT NULL DEFAULT ''")

    # ── Modelo de ediciones (F1): talleres → concepto + ediciones_taller + clases_taller ──
    conn.execute("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS slug_base VARCHAR(120)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ediciones_taller (
            id                SERIAL PRIMARY KEY,
            taller_id         INTEGER NOT NULL REFERENCES talleres(id) ON DELETE CASCADE,
            numero_edicion    INTEGER NOT NULL DEFAULT 1,
            slug              VARCHAR(120) NOT NULL UNIQUE,
            tipo_taller       TEXT NOT NULL DEFAULT 'intensivo',
            fecha_inicio      DATE NOT NULL,
            fecha_fin         DATE NOT NULL,
            horario           TEXT NOT NULL DEFAULT '',
            cupos_total       INTEGER NOT NULL DEFAULT 12,
            cupos_confirmados INTEGER NOT NULL DEFAULT 0,
            precio_total      INTEGER NOT NULL DEFAULT 0,
            precio_sena       INTEGER NOT NULL DEFAULT 0,
            pago_alias        TEXT NOT NULL DEFAULT '',
            pago_cbu          TEXT NOT NULL DEFAULT '',
            pago_banco        TEXT NOT NULL DEFAULT '',
            direccion         TEXT NOT NULL DEFAULT '',
            activo            BOOLEAN NOT NULL DEFAULT TRUE,
            snapshot          JSONB,
            frozen_at         TIMESTAMPTZ,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(taller_id, numero_edicion)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ediciones_taller_taller "
        "ON ediciones_taller(taller_id)"
    )
    # idx_ediciones_taller_slug se retiró: `slug` ya es UNIQUE en el CREATE
    # TABLE de arriba — era 100% redundante (ver migración
    # q4r5s6t7u8v9_drop_redundant_plain_indexes).

    # Economía del taller (#1283-adjacent): si la edición usa el espacio del
    # Estudio y/o equipos de alquiler, con un valor que el admin tipea a mano
    # (no se deriva de asistencia real) — `_regenerar_pedidos_taller` los
    # traduce en ítems del pedido mensual, atribuidos automático vía
    # `equipos.dueno` (Estudio / Rental), igual que hace el Estudio con sus
    # slots fijos. La matrícula/curso en sí NO tiene columna — se tipea como
    # línea personalizada dentro del pedido ya generado.
    conn.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS usa_estudio BOOLEAN NOT NULL DEFAULT FALSE")
    conn.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_estudio INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_estudio_modo TEXT NOT NULL DEFAULT 'mensual'")
    conn.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS usa_equipos BOOLEAN NOT NULL DEFAULT FALSE")
    conn.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_equipos INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_equipos_modo TEXT NOT NULL DEFAULT 'mensual'")
    # Migración idempotente (mismo patrón que spec_propuestas_pendientes_tipo_check):
    # dropear+re-crear en vez de "ADD CONSTRAINT IF NOT EXISTS" (Postgres no lo soporta para CHECK).
    conn.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_estudio_modo_check")
    conn.execute(
        "ALTER TABLE ediciones_taller ADD CONSTRAINT ediciones_taller_valor_estudio_modo_check "
        "CHECK (valor_estudio_modo IN ('mensual','total'))"
    )
    conn.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_equipos_modo_check")
    conn.execute(
        "ALTER TABLE ediciones_taller ADD CONSTRAINT ediciones_taller_valor_equipos_modo_check "
        "CHECK (valor_equipos_modo IN ('mensual','total'))"
    )
    # `_tipo` ('fijo'|'porcentaje') es un eje NUEVO y ortogonal a `_modo`
    # (mensual/total sigue siendo "cómo se reparte entre los meses" — esto es
    # "cómo se determina el valor"). 'fijo' = el admin tipea el monto directo
    # (comportamiento de siempre, `valor_estudio`/`valor_equipos`). 'porcentaje'
    # = el admin tipea un % (`valor_estudio_pct`/`valor_equipos_pct`, 0-100) y
    # `_regenerar_pedidos_taller` deriva el monto de ESE % sobre el total que
    # los inscriptos (no en lista de espera) de la edición van a pagar —
    # `SUM(modalidad_monto)`, nunca un número tipeado a mano. Pedido explícito
    # del dueño: "si se anotan 6 vamos al 50%".
    conn.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_estudio_tipo TEXT NOT NULL DEFAULT 'fijo'")
    conn.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_estudio_pct INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_equipos_tipo TEXT NOT NULL DEFAULT 'fijo'")
    conn.execute("ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS valor_equipos_pct INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_estudio_tipo_check")
    conn.execute(
        "ALTER TABLE ediciones_taller ADD CONSTRAINT ediciones_taller_valor_estudio_tipo_check "
        "CHECK (valor_estudio_tipo IN ('fijo','porcentaje'))"
    )
    conn.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_equipos_tipo_check")
    conn.execute(
        "ALTER TABLE ediciones_taller ADD CONSTRAINT ediciones_taller_valor_equipos_tipo_check "
        "CHECK (valor_equipos_tipo IN ('fijo','porcentaje'))"
    )
    conn.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_estudio_pct_check")
    conn.execute(
        "ALTER TABLE ediciones_taller ADD CONSTRAINT ediciones_taller_valor_estudio_pct_check "
        "CHECK (valor_estudio_pct BETWEEN 0 AND 100)"
    )
    conn.execute("ALTER TABLE ediciones_taller DROP CONSTRAINT IF EXISTS ediciones_taller_valor_equipos_pct_check")
    conn.execute(
        "ALTER TABLE ediciones_taller ADD CONSTRAINT ediciones_taller_valor_equipos_pct_check "
        "CHECK (valor_equipos_pct BETWEEN 0 AND 100)"
    )
    # Vincula cada pedido mensual generado con su edición, para regenerar
    # futuros sin tocar pasados/pagados (mismo patrón que `estudio_slot_id`).
    # NULL en todo pedido normal → cero impacto.
    conn.execute("ALTER TABLE alquileres ADD COLUMN IF NOT EXISTS taller_edicion_id INTEGER REFERENCES ediciones_taller(id) ON DELETE SET NULL")

    # Horas en MINUTOS desde medianoche (0..1440) — soporta medias horas (8:30).
    # El sufijo _min es deliberado: un lector legacy que espere horas enteras
    # falla ruidoso en SQL en vez de comparar horas contra minutos en silencio.
    # (Migración esc1m2i3n4t5 convirtió los datos existentes ×60.)
    # Escuela v2 F2: la clase es RICA — titulo/descripcion/nota/portada son el
    # contenido de marketing que muestra la landing (colapsables por clase).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clases_taller (
            id              SERIAL PRIMARY KEY,
            edicion_id      INTEGER NOT NULL REFERENCES ediciones_taller(id) ON DELETE CASCADE,
            fecha           DATE    NOT NULL,
            hora_inicio_min INTEGER NOT NULL,
            hora_fin_min    INTEGER NOT NULL,
            titulo          TEXT NOT NULL DEFAULT '',
            descripcion     TEXT NOT NULL DEFAULT '',
            nota            TEXT NOT NULL DEFAULT '',
            portada_media_id BIGINT REFERENCES media_assets(id) ON DELETE SET NULL,
            portada_url     TEXT NOT NULL DEFAULT '',
            orden           INTEGER NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_clases_taller_edicion "
        "ON clases_taller(edicion_id)"
    )
    conn.execute("ALTER TABLE clases_taller ADD COLUMN IF NOT EXISTS titulo TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE clases_taller ADD COLUMN IF NOT EXISTS descripcion TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE clases_taller ADD COLUMN IF NOT EXISTS nota TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE clases_taller ADD COLUMN IF NOT EXISTS portada_media_id BIGINT REFERENCES media_assets(id) ON DELETE SET NULL")
    conn.execute("ALTER TABLE clases_taller ADD COLUMN IF NOT EXISTS portada_url TEXT NOT NULL DEFAULT ''")
    # Orden manual (independiente de fecha) — el backfill de datos existentes
    # vive SOLO en la migración Alembic (y3z4a5b6c7d8), no acá: repetirlo en
    # cada arranque pisaría cualquier reorden manual ya guardado.
    conn.execute("ALTER TABLE clases_taller ADD COLUMN IF NOT EXISTS orden INTEGER NOT NULL DEFAULT 0")

    # Escuela v2 F3: instructores como ENTIDAD propia (antes solo texto suelto en
    # `talleres.instructor_*`) — un taller puede tener varios, un instructor puede
    # dar varios talleres (caso Filmar: mismo instructor en Principiante y
    # Avanzado). Fuente única desde F6 (las columnas legacy de `talleres` que
    # las precedían ya no existen).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS instructores (
            id            SERIAL PRIMARY KEY,
            nombre        TEXT NOT NULL,
            rol           TEXT NOT NULL DEFAULT '',
            descripcion   TEXT NOT NULL DEFAULT '',
            instagram     TEXT NOT NULL DEFAULT '',
            web           TEXT NOT NULL DEFAULT '',
            foto_media_id BIGINT REFERENCES media_assets(id) ON DELETE SET NULL,
            foto_url      TEXT NOT NULL DEFAULT '',
            activo        BOOLEAN NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS taller_instructores (
            taller_id     INTEGER NOT NULL REFERENCES talleres(id) ON DELETE CASCADE,
            instructor_id INTEGER NOT NULL REFERENCES instructores(id) ON DELETE CASCADE,
            orden         INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (taller_id, instructor_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_taller_instructores_taller "
        "ON taller_instructores(taller_id, orden)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_taller_instructores_instructor "
        "ON taller_instructores(instructor_id)"
    )
    # Escuela v2 F6: proyectos por-instructor (reemplaza `talleres.instructor_proyectos`,
    # dropeada en la misma fase) — "Trabajó con" ahora lee de acá.
    conn.execute("ALTER TABLE instructores ADD COLUMN IF NOT EXISTS proyectos TEXT NOT NULL DEFAULT ''")

    # Instituciones (co-presentadoras de un taller, ej. "Rambla" + "Filmar") —
    # mismo patrón que instructores (entidad propia + N↔N con talleres, un
    # taller puede tener varias, una institución puede co-presentar varios
    # talleres). A propósito SIN `rol`/`proyectos` (no aplican a una
    # organización) y SIN `activo` (en instructores quedó vestigial — nadie lo
    # lee ni lo filtra — no se copia un campo que no rinde).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS instituciones (
            id            SERIAL PRIMARY KEY,
            nombre        TEXT NOT NULL,
            descripcion   TEXT NOT NULL DEFAULT '',
            instagram     TEXT NOT NULL DEFAULT '',
            web           TEXT NOT NULL DEFAULT '',
            logo_media_id BIGINT REFERENCES media_assets(id) ON DELETE SET NULL,
            logo_url      TEXT NOT NULL DEFAULT '',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS taller_instituciones (
            taller_id      INTEGER NOT NULL REFERENCES talleres(id) ON DELETE CASCADE,
            institucion_id INTEGER NOT NULL REFERENCES instituciones(id) ON DELETE CASCADE,
            orden          INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (taller_id, institucion_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_taller_instituciones_taller "
        "ON taller_instituciones(taller_id, orden)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_taller_instituciones_institucion "
        "ON taller_instituciones(institucion_id)"
    )

    # Escuela v2 F4a: video hero (YouTube) del concepto. Mismo extractor que
    # estudio_trabajos (services.media.youtube.extract_video_id), pero acá SÍ
    # se descarga y guarda el poster en R2 (store_youtube_poster) — es
    # contenido sobre-el-pliegue (hero de la landing), no una card en un grid
    # más abajo: vale la mejora de LCP de no pegarle a img.youtube.com.
    conn.execute("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS video_url TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS video_poster_media_id BIGINT REFERENCES media_assets(id) ON DELETE SET NULL")
    conn.execute("ALTER TABLE talleres ADD COLUMN IF NOT EXISTS video_poster_url TEXT NOT NULL DEFAULT ''")

    # Escuela v2 F4a: modalidades de pago por edición — `monto_total` (costo
    # total del plan) y `n_cuotas` cargados a mano por el admin; el monto POR
    # cuota se deriva (`monto_total / n_cuotas`, redondeado) — nunca se tipea
    # a mano, así no puede desincronizarse del total (fix #: comunicación de
    # cuotas, antes el "N cuotas de $X" era texto libre en `label`/`nota` sin
    # ninguna relación aritmética con `monto_total`). `n_cuotas=1` = pago
    # único (default; el fallback sintético de abajo no lo setea, cae acá).
    # Sin modalidades configuradas, el público ve un fallback sintético de 1
    # sola opción ("Pago total" = precio_total) — cero ruptura para
    # ediciones que no las configuran.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS edicion_modalidades_pago (
            id          SERIAL PRIMARY KEY,
            edicion_id  INTEGER NOT NULL REFERENCES ediciones_taller(id) ON DELETE CASCADE,
            orden       INTEGER NOT NULL DEFAULT 0,
            codigo      TEXT NOT NULL,
            label       TEXT NOT NULL,
            nota        TEXT NOT NULL DEFAULT '',
            monto_total INTEGER NOT NULL,
            n_cuotas    INTEGER NOT NULL DEFAULT 1,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(edicion_id, codigo)
        )
    """)
    conn.execute(
        "ALTER TABLE edicion_modalidades_pago ADD COLUMN IF NOT EXISTS n_cuotas INTEGER NOT NULL DEFAULT 1"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_edicion_modalidades_pago_edicion "
        "ON edicion_modalidades_pago(edicion_id, orden)"
    )

    # Cuentas de cobro por edición — lista (0+), mismo patrón que
    # edicion_modalidades_pago pero SIN atarse a una forma de pago en
    # particular: el cliente ve todas las opciones y elige a cuál
    # transferir (pedido explícito del dueño, taller de Ariel). Reemplaza a
    # ediciones_taller.pago_alias/pago_cbu/pago_banco (esas 3 columnas
    # quedan sin tocar por compatibilidad — ver migración cu3nt4sp4g0 para
    # el traspaso de datos existentes — pero el admin ya no las edita).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS edicion_cuentas_pago (
            id          SERIAL PRIMARY KEY,
            edicion_id  INTEGER NOT NULL REFERENCES ediciones_taller(id) ON DELETE CASCADE,
            orden       INTEGER NOT NULL DEFAULT 0,
            alias       TEXT NOT NULL DEFAULT '',
            cbu         TEXT NOT NULL DEFAULT '',
            banco       TEXT NOT NULL DEFAULT '',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_edicion_cuentas_pago_edicion "
        "ON edicion_cuentas_pago(edicion_id, orden)"
    )

    # Escuela v2 F4c: cierre de inscripciones por fecha. NULL = sin cierre
    # (comportamiento actual, siempre abierto). Pasada la fecha, el público
    # ve "inscripciones cerradas" y el POST de inscripción rechaza con 400.
    conn.execute(
        "ALTER TABLE ediciones_taller ADD COLUMN IF NOT EXISTS fecha_cierre_inscripcion DATE"
    )

    # Escuela v2 F4c: trabajos pasados del taller — SOLO links de YouTube (sin
    # testimonios/reseñas, decisión del dueño), mismo patrón de poster que el
    # video hero del concepto (F4a: se descarga y guarda en R2).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS taller_trabajos (
            id                SERIAL PRIMARY KEY,
            taller_id         INTEGER NOT NULL REFERENCES talleres(id) ON DELETE CASCADE,
            titulo            TEXT NOT NULL DEFAULT '',
            youtube_url       TEXT NOT NULL,
            poster_media_id   BIGINT REFERENCES media_assets(id) ON DELETE SET NULL,
            poster_url        TEXT NOT NULL DEFAULT '',
            orden             INTEGER NOT NULL DEFAULT 0,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_taller_trabajos_taller "
        "ON taller_trabajos(taller_id, orden)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS interesados_taller (
            id            SERIAL PRIMARY KEY,
            taller_id     INTEGER NOT NULL REFERENCES talleres(id) ON DELETE CASCADE,
            nombre        TEXT NOT NULL,
            email         TEXT NOT NULL,
            telefono      TEXT NOT NULL DEFAULT '',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            notificado_at TIMESTAMPTZ
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_interesados_taller_taller "
        "ON interesados_taller(taller_id)"
    )

    # Extender taller_inscripciones para el nuevo modelo
    conn.execute(
        "ALTER TABLE taller_inscripciones "
        "ADD COLUMN IF NOT EXISTS edicion_id INTEGER REFERENCES ediciones_taller(id)"
    )
    # Sirve la query de `_revenue_inscriptos` (WHERE edicion_id = ... AND
    # en_lista_espera = FALSE) — antes solo había índice por `taller_id`. Va
    # ACÁ (no arriba, junto a `valor_estudio_pct`) porque `edicion_id` recién
    # existe en la tabla desde la línea anterior — un CREATE INDEX que la
    # referencie antes de esa ALTER TABLE rompe `init_db()` en una base
    # nueva (bug real, cazado por `test_alembic_upgrade_db.py` en CI).
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_taller_inscripciones_edicion_lista "
        "ON taller_inscripciones(edicion_id, en_lista_espera)"
    )
    conn.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS estado TEXT"
    )
    conn.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS comprobante_resto_url TEXT"
    )
    conn.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS comprobante_resto_key TEXT"
    )
    conn.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS notas_admin TEXT"
    )
    conn.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ"
    )
    conn.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS sena_verificada_at TIMESTAMPTZ"
    )
    conn.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS pago_completo_at TIMESTAMPTZ"
    )
    # Escuela v2 F4a: snapshot de la modalidad de pago elegida al inscribirse
    # (mismo criterio que el precio de línea de un pedido: congelado, no en
    # vivo — si el admin edita las modalidades después, esta inscripción ya
    # hecha no cambia retroactivamente). NULL = inscripción anterior a F4a.
    conn.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS modalidad_codigo TEXT"
    )
    conn.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS modalidad_label TEXT"
    )
    conn.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS modalidad_monto INTEGER"
    )
    # Escuela v2 F4b: "ofrecer cupo al siguiente" — cuando se libera un cupo
    # (baja de un confirmado), el admin le manda al primero de la lista un
    # link tokenizado para completar la seña. NO toca cupos_confirmados ni
    # en_lista_espera hasta que la persona efectivamente reclama el cupo
    # (POST /talleres/sena/{token}) — así el admin puede re-ofrecer a otro si
    # no responde, sin tener que "devolver" nada.
    conn.execute(
        "ALTER TABLE taller_inscripciones ADD COLUMN IF NOT EXISTS cupo_ofrecido_at TIMESTAMPTZ"
    )

    # ── Carritos activos (#280 Fase 1): persistencia server-side ──────────────
    # Cada heartbeat del frontend hace upsert por session_id (UUID v4 generado
    # en el cliente). cliente_id se asocia automáticamente si hay sesión activa.
    # items_json incluye nombre del equipo para el dashboard sin joins adicionales.
    # confirmado=TRUE cuando el cliente confirma el pedido (cierre del funnel).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS carritos_activos (
            id              SERIAL PRIMARY KEY,
            session_id      TEXT NOT NULL UNIQUE,
            cliente_id      INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
            items_json      JSONB NOT NULL DEFAULT '[]',
            fecha_desde     DATE,
            fecha_hasta     DATE,
            hora_desde      TEXT,
            hora_hasta      TEXT,
            total_items     INTEGER NOT NULL DEFAULT 0,
            monto_estimado  INTEGER NOT NULL DEFAULT 0,
            confirmado      BOOLEAN NOT NULL DEFAULT FALSE,
            abandonado_en   TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_carritos_updated "
        "ON carritos_activos(updated_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_carritos_cliente "
        "ON carritos_activos(cliente_id) WHERE cliente_id IS NOT NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_carritos_activos_no_conf "
        "ON carritos_activos(updated_at DESC) WHERE NOT confirmado"
    )

    # ── Registro de errores del servidor ──────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS server_errors (
            id          SERIAL PRIMARY KEY,
            route       TEXT NOT NULL,
            error_type  TEXT NOT NULL,
            message     TEXT NOT NULL DEFAULT '',
            traceback   TEXT NOT NULL DEFAULT '',
            request_id  TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_server_errors_created "
        "ON server_errors(created_at DESC)"
    )

    conn.execute("CREATE SEQUENCE IF NOT EXISTS numero_pedido_seq")

    # Seed the sequence to the current max so nextval never collides with existing data.
    # GREATEST ensures we never decrease an already-advanced sequence on restart.
    conn.execute("""
        SELECT setval('numero_pedido_seq',
            GREATEST(
                (SELECT COALESCE(MAX(numero_pedido), 0) FROM alquileres WHERE numero_pedido IS NOT NULL),
                (SELECT last_value FROM numero_pedido_seq)
            ), true)
    """)

    # ── Facturación electrónica ARCA (#1139) ─────────────────────────────────
    # Motor portable en `backend/arca_fe/`; adapter en `backend/services/facturacion/`.
    # Esquema en dos capas (MEMORIA 2026-06-03): también en migración a2b3c4d5e6f7.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS facturas (
            id                      SERIAL PRIMARY KEY,
            pedido_id               INTEGER NOT NULL REFERENCES alquileres(id) ON DELETE CASCADE,
            emisor                  TEXT NOT NULL,
            ambiente                TEXT NOT NULL,
            cbte_tipo               INTEGER NOT NULL,
            pto_vta                 INTEGER NOT NULL,
            cbte_nro                INTEGER,
            cae                     TEXT,
            cae_vto                 DATE,
            doc_tipo                INTEGER NOT NULL,
            doc_nro                 TEXT NOT NULL,
            condicion_iva_receptor  INTEGER NOT NULL,
            concepto                INTEGER NOT NULL,
            imp_neto                NUMERIC(12,2) NOT NULL,
            imp_iva                 NUMERIC(12,2) NOT NULL DEFAULT 0,
            imp_total               NUMERIC(12,2) NOT NULL,
            moneda                  TEXT NOT NULL DEFAULT 'PES',
            cliente_cuit            TEXT,
            razon_social            TEXT,
            domicilio               TEXT,
            qr_payload              TEXT,
            pdf_key                 TEXT,
            estado                  TEXT NOT NULL DEFAULT 'pendiente',
            nota_credito_de         INTEGER REFERENCES facturas(id),
            raw_request             JSONB,
            raw_response            JSONB,
            errores                 JSONB,
            fecha_emision           TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by              TEXT
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_factura_vigente_por_pedido
        ON facturas (pedido_id) WHERE estado IN ('pendiente','emitida')
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_facturas_pedido ON facturas (pedido_id)
    """)
    # imp_neto/imp_iva/imp_total INTEGER → NUMERIC(12,2) (bug #1209): el CAE/QR de
    # ARCA autorizan el importe EXACTO al centavo; truncarlo a entero acá dejaba el
    # PDF impreso por debajo de lo que el comprobante fiscal autorizó. Idempotente
    # (no-op si ya está migrado); también en migración h3i4j5k6l7m8.
    conn.execute("""
        DO $$
        BEGIN
            IF (SELECT data_type FROM information_schema.columns
                WHERE table_name = 'facturas' AND column_name = 'imp_neto') = 'integer' THEN
                ALTER TABLE facturas ALTER COLUMN imp_neto TYPE NUMERIC(12,2)
                    USING imp_neto::NUMERIC(12,2);
                ALTER TABLE facturas ALTER COLUMN imp_iva TYPE NUMERIC(12,2)
                    USING imp_iva::NUMERIC(12,2);
                ALTER TABLE facturas ALTER COLUMN imp_total TYPE NUMERIC(12,2)
                    USING imp_total::NUMERIC(12,2);
            END IF;
        END $$;
    """)
    # `domicilio` del receptor — congelado al emitir (razón social/CUIT ya lo
    # estaban; domicilio antes se leía en vivo de la ficha del cliente en cada
    # reimpresión, por lo que podía "cambiar" retroactivamente si el cliente
    # editaba su domicilio después de facturado). NULL en facturas viejas: el
    # PDF cae al valor en vivo de siempre para esas (backward-compatible).
    conn.execute("ALTER TABLE facturas ADD COLUMN IF NOT EXISTS domicilio TEXT")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS afip_ta (
            ambiente   TEXT NOT NULL,
            emisor     TEXT NOT NULL,
            servicio   TEXT NOT NULL DEFAULT 'wsfe',
            token      TEXT NOT NULL,
            sign       TEXT NOT NULL,
            expira_at  TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (ambiente, emisor, servicio)
        )
    """)
    conn.execute("""
        ALTER TABLE afip_ta
            ADD COLUMN IF NOT EXISTS servicio TEXT NOT NULL DEFAULT 'wsfe'
    """)
    conn.execute("ALTER TABLE afip_ta DROP CONSTRAINT IF EXISTS afip_ta_pkey")
    conn.execute("""
        ALTER TABLE afip_ta
            ADD CONSTRAINT afip_ta_pkey PRIMARY KEY (ambiente, emisor, servicio)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS emisores_arca (
            id                  SERIAL PRIMARY KEY,
            nombre              TEXT NOT NULL UNIQUE,
            cuit                TEXT NOT NULL,
            pto_vta             INTEGER NOT NULL,
            condicion_iva       TEXT NOT NULL,
            cert_enc            BYTEA,
            key_enc             BYTEA,
            activo              BOOLEAN NOT NULL DEFAULT true,
            razon_social        TEXT,
            domicilio           TEXT,
            iibb                TEXT,
            inicio_actividades  TEXT,
            notas               TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.execute("""
        ALTER TABLE emisores_arca
            ADD COLUMN IF NOT EXISTS razon_social TEXT
    """)
    conn.execute("""
        ALTER TABLE emisores_arca
            ADD COLUMN IF NOT EXISTS domicilio TEXT
    """)
    conn.execute("""
        ALTER TABLE emisores_arca
            ADD COLUMN IF NOT EXISTS iibb TEXT
    """)
    conn.execute("""
        ALTER TABLE emisores_arca
            ADD COLUMN IF NOT EXISTS inicio_actividades TEXT
    """)

    # ── Perfiles fiscales múltiples + productoras (#1240) ────────────────────
    # Refina la regla "facturación siempre usa el dato de AFIP verificado" (2026-07-05):
    # `clientes.cuit/perfil_impuestos/razon_social/domicilio_fiscal/email_facturacion`
    # se mantienen intactas (siguen siendo "el perfil default" que leen ~10 call sites
    # sin cambios) — estas 3 tablas son ADITIVAS, no reemplazan nada.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cliente_perfiles_fiscales (
            id                SERIAL PRIMARY KEY,
            cliente_id        INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            cuit              TEXT NOT NULL,
            perfil_impuestos  TEXT NOT NULL,
            razon_social      TEXT,
            domicilio_fiscal  TEXT,
            email_facturacion TEXT,
            etiqueta          TEXT,
            verificado_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            es_default        BOOLEAN NOT NULL DEFAULT FALSE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cliente_perfiles_fiscales_cliente_id
        ON cliente_perfiles_fiscales(cliente_id)
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_cliente_perfiles_fiscales_default
        ON cliente_perfiles_fiscales(cliente_id) WHERE es_default
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_cliente_perfiles_fiscales_cuit
        ON cliente_perfiles_fiscales(cliente_id, cuit)
    """)

    # Productoras: entidad fiscal SIN login propio, administrada por el admin (crea +
    # verifica CUIT contra ARCA + vincula/desvincula cuentas de cliente). Sin roles ni
    # invitaciones — el admin es el único que gestiona la membresía.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS productoras (
            id                SERIAL PRIMARY KEY,
            cuit              TEXT UNIQUE,
            perfil_impuestos  TEXT,
            razon_social      TEXT,
            domicilio_fiscal  TEXT,
            email_facturacion TEXT,
            notas             TEXT,
            verificado_at     TIMESTAMPTZ,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # nombre/redes_sociales (#1251 Fase 2): manuales, no vienen de AFIP. `nombre` es
    # el label amigable que siempre queda disponible aunque razon_social venga vacía
    # de AFIP para cierto tipo de CUIT.
    conn.execute("ALTER TABLE productoras ADD COLUMN IF NOT EXISTS nombre TEXT")
    conn.execute("ALTER TABLE productoras ADD COLUMN IF NOT EXISTS redes_sociales TEXT")
    # Borrador sin CUIT (#1251 Fase 3): "podemos crear una productora sin el CUIT,
    # solo el nombre" — cuit/perfil_impuestos/verificado_at pasan a NULLABLE (antes
    # NOT NULL). Una productora sin CUIT NO es facturable — la excluye
    # `clientes.queries.fiscal.productoras_vinculadas(solo_facturables=True)`, que
    # alimenta el selector de checkout; la ficha admin sigue viendo el borrador.
    conn.execute("ALTER TABLE productoras ALTER COLUMN cuit DROP NOT NULL")
    conn.execute("ALTER TABLE productoras ALTER COLUMN perfil_impuestos DROP NOT NULL")
    conn.execute("ALTER TABLE productoras ALTER COLUMN verificado_at DROP NOT NULL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS productora_miembros (
            productora_id  INTEGER NOT NULL REFERENCES productoras(id) ON DELETE CASCADE,
            cliente_id     INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (productora_id, cliente_id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_productora_miembros_cliente_id
        ON productora_miembros(cliente_id)
    """)

    # Pedido: a nombre de quién se factura (mutuamente excluyentes; NULL/NULL = default de
    # la cuenta, comportamiento de siempre). Se resuelve EN VIVO (solo se congela el
    # puntero, no razón social/domicilio) — coherente con "Datos del pedido: contacto en
    # vivo, plata congelada" (2026-06-06).
    conn.execute("""
        ALTER TABLE alquileres
            ADD COLUMN IF NOT EXISTS perfil_fiscal_id INTEGER REFERENCES cliente_perfiles_fiscales(id)
    """)
    conn.execute("""
        ALTER TABLE alquileres
            ADD COLUMN IF NOT EXISTS productora_id INTEGER REFERENCES productoras(id)
    """)
    conn.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'chk_alquileres_facturacion_target'
            ) THEN
                ALTER TABLE alquileres ADD CONSTRAINT chk_alquileres_facturacion_target
                    CHECK (perfil_fiscal_id IS NULL OR productora_id IS NULL);
            END IF;
        END $$;
    """)

    # ── Estudio: trabajos / producciones (galería "en acción") ───────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS estudio_trabajos (
            id                  SERIAL PRIMARY KEY,
            titulo              TEXT NOT NULL DEFAULT '',
            realizador          TEXT NOT NULL DEFAULT '',
            realizador_logo_url TEXT,
            tipo                TEXT NOT NULL DEFAULT 'fotos'
                                CHECK (tipo IN ('fotos', 'video')),
            youtube_url         TEXT,
            fotos_json          TEXT NOT NULL DEFAULT '[]',
            orden               INTEGER NOT NULL DEFAULT 0,
            activo              BOOLEAN NOT NULL DEFAULT TRUE,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_estudio_trabajos_orden ON estudio_trabajos(orden)"
    )
    conn.execute(
        "ALTER TABLE estudio_trabajos ADD COLUMN IF NOT EXISTS realizador_instagram TEXT"
    )
    conn.execute(
        "ALTER TABLE estudio_trabajos ADD COLUMN IF NOT EXISTS realizador_web TEXT"
    )
    conn.execute(
        "ALTER TABLE estudio_trabajos ADD COLUMN IF NOT EXISTS categoria TEXT NOT NULL DEFAULT ''"
    )
    conn.execute(
        "ALTER TABLE estudio_trabajos ADD COLUMN IF NOT EXISTS descripcion TEXT NOT NULL DEFAULT ''"
    )
    conn.execute(
        "ALTER TABLE estudio_trabajos ADD COLUMN IF NOT EXISTS instagram_reel_url TEXT"
    )
    conn.execute(
        "ALTER TABLE estudio_trabajos ADD COLUMN IF NOT EXISTS thumbnail_url TEXT"
    )
    # Lista ordenada de links externos (YouTube/Instagram) por trabajo:
    # [{tipo, url, thumbnail_url}]. Fuente única de medios externos; las
    # columnas youtube_url/instagram_reel_url quedan como fallback legacy de
    # lectura (migración on-write). El motor une links_json + fotos_json en el
    # carrusel `media` que consume el front.
    conn.execute(
        "ALTER TABLE estudio_trabajos ADD COLUMN IF NOT EXISTS links_json TEXT NOT NULL DEFAULT '[]'"
    )
    # Un trabajo puede tener varios tags. categorias_json es la fuente única; la
    # columna `categoria` (singular) queda como legacy de lectura (= primer tag).
    conn.execute(
        "ALTER TABLE estudio_trabajos ADD COLUMN IF NOT EXISTS categorias_json TEXT NOT NULL DEFAULT '[]'"
    )

    # Listas / kits personales del cliente (#1092 — habilitado por la puerta de
    # contenido). El cliente guarda una composición de equipos que alquila
    # seguido y la reserva de un toque (rearma el carrito y RE-COTIZA contra el
    # catálogo actual — NO es un snapshot de precios; respeta plata/ítems
    # congelados 2026-06-06). Se guarda SOLO la composición (equipo_id +
    # cantidad); nombre/foto/precio se resuelven en vivo desde el catálogo.
    # Server-only (acción logueada deliberada — sin sync de localStorage, a
    # diferencia de favoritos). Esquema en dos capas (MEMORIA 2026-06-03):
    # también en la migración c1a5d7e9f3b2.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cliente_listas (
            id          SERIAL PRIMARY KEY,
            cliente_id  INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            nombre      TEXT NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cliente_listas_cliente ON cliente_listas(cliente_id)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cliente_listas_items (
            id         SERIAL PRIMARY KEY,
            lista_id   INTEGER NOT NULL REFERENCES cliente_listas(id) ON DELETE CASCADE,
            equipo_id  INTEGER NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
            cantidad   INTEGER NOT NULL DEFAULT 1 CHECK (cantidad > 0),
            UNIQUE (lista_id, equipo_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cliente_listas_items_lista ON cliente_listas_items(lista_id)"
    )

    # ── Carritos compartidos (#1092 feature #4): link gaffer → productor ───────
    # Un cliente (logueado o anónimo) comparte una composición de equipos por un
    # link público corto (/c/<token>). El destinatario la abre y la rearma en SU
    # carrito (re-cotiza contra el catálogo ACTUAL — NO un snapshot de precios;
    # respeta plata/ítems congelados 2026-06-06, igual que listas/repetir-pedido).
    # Se guarda SOLO la composición (equipo_id + cantidad) en items_json + un
    # título opcional. token UNIQUE = índice implícito para el lookup. cliente_id
    # es atribución opcional (anónimo puede compartir). Esquema en dos capas
    # (MEMORIA 2026-06-03): también en la migración d4f2a8b1c6e3.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS carritos_compartidos (
            id          SERIAL PRIMARY KEY,
            token       TEXT NOT NULL UNIQUE,
            titulo      TEXT,
            items_json  JSONB NOT NULL DEFAULT '[]',
            cliente_id  INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
            vistas      INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ── Aceptaciones de Términos y Condiciones (checkout portero) ─────────────
    # Registro inmutable de qué versión de T&C aceptó cada cliente y cuándo.
    # La versión actual es `TYC_VERSION_ACTUAL` en `services/checkout/tyc.py`;
    # sube junto al texto cuando cambian. ON CONFLICT DO NOTHING → idempotente.
    # Esquema en dos capas (MEMORIA 2026-06-03): también en la migración
    # b1a2c3d4e5f6_checkout_aceptaciones_tyc.py.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS aceptaciones_tyc (
            id          SERIAL PRIMARY KEY,
            cliente_id  INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
            version     TEXT NOT NULL,
            aceptado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (cliente_id, version)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_aceptaciones_tyc_cliente "
        "ON aceptaciones_tyc(cliente_id)"
    )

    # Vincula un turno del Estudio (tipo='estudio') a un pedido de alquiler
    # normal (tipo='diaria') del que "cuelga" — el pedido de rental de varios
    # días y el turno puntual del Estudio son registros distintos (fechas con
    # significado incompatible: rango vs. franja horaria, ver `tipos_pedido.py`)
    # pero se administran en una sola pantalla (el pedido principal muestra sus
    # turnos vinculados inline, el turno muestra un link de vuelta). Self-FK
    # nullable, ON DELETE SET NULL: si se borra el pedido principal, el turno
    # sobrevive como turno normal (no huérfano, no se re-elimina en cascada).
    # NULL en todo pedido existente → cero impacto. Esquema en dos capas
    # (MEMORIA 2026-06-03): también en la migración pv1nc2l3a4d5.
    conn.execute(
        "ALTER TABLE alquileres ADD COLUMN IF NOT EXISTS pedido_principal_id "
        "INTEGER REFERENCES alquileres(id) ON DELETE SET NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pedidos_principal ON alquileres(pedido_principal_id)"
    )

    # ── Serie de IPC (INDEC) para ajustar Estadísticas por inflación ────────
    # Cache local de la API pública de INDEC; se refresca 1×/día desde el
    # scheduler in-process (jobs/ipc.py). `mes` es 'YYYY-MM'. Esquema en dos
    # capas (MEMORIA 2026-06-03): también en la migración ipcseries.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ipc_series (
            mes           VARCHAR(7) PRIMARY KEY,
            indice        NUMERIC(14,4) NOT NULL,
            actualizado_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Galería de fotos por EDICIÓN de taller (portada + galería pública) ──
    # Espejo exacto de `estudio_fotos` (2026-05-E1) pero scoped a `edicion_id`
    # en vez de al singleton Estudio — una edición puntual tiene su propia
    # tanda de fotos (no el concepto `talleres`, a diferencia de `video_url`/
    # `video_poster_url` que sí viven a nivel taller): confirmado con el dueño,
    # cada edición (fechas/instructor/grupo distintos) amerita su propia
    # portada+galería. `es_principal` marca la portada del hero público.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS edicion_fotos (
            id           SERIAL PRIMARY KEY,
            edicion_id   INTEGER NOT NULL REFERENCES ediciones_taller(id) ON DELETE CASCADE,
            url          TEXT NOT NULL,
            url_sm       TEXT,
            url_avif     TEXT,
            url_sm_avif  TEXT,
            path         TEXT,
            media_id     BIGINT REFERENCES media_assets(id) ON DELETE SET NULL,
            orden        INTEGER NOT NULL DEFAULT 0,
            es_principal BOOLEAN NOT NULL DEFAULT FALSE,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_edicion_fotos_edicion_orden "
        "ON edicion_fotos(edicion_id, orden)"
    )

    conn.commit()
