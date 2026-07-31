"""Talleres y taller_inscripciones: workshops públicos con formulario de inscripción.

Seed del primer taller: Workshop Dirección de Arte × Jime Troncoso (julio 2026).
Agrega los templates de email para notif al admin y confirmación al inscripto.

Espeja init_db() (esquema en dos capas, MEMORIA 2026-06-03).

Guard post-Escuela-v2-F6 (esc7l8i9m0p1): en una DB fresca, init_db() ya crea
`talleres` en su forma FINAL (sin instructor_nombre/programa_*/fecha_inicio/...,
retirados en F6) — el CREATE TABLE IF NOT EXISTS de acá es no-op, pero el INSERT
de abajo escribía a esas columnas incondicionalmente. Se saltea el seed entero
cuando `instructor_nombre` no existe (mismo criterio que el guard de
`e1d2c3i4o5n6` para `clases_taller`): un bootstrap post-F6 ya no modela un
taller como fila plana, y sembrar ese shape ahí no tiene sentido. En una DB que
SÍ tiene la columna (pre-F6, replay histórico) el seed corre igual que siempre.

Revision ID: t1a2l3l4e5r6
Revises: z0a1b2c3d4e5
Create Date: 2026-06-20
"""

import json
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "t1a2l3l4e5r6"
down_revision: Union[str, Sequence[str], None] = "z0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _q(s: str) -> str:
    """Escape para strings literales en SQL — duplica comillas simples."""
    return "'" + s.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS talleres (
            id                   SERIAL PRIMARY KEY,
            slug                 VARCHAR(120) NOT NULL UNIQUE,
            nombre               TEXT NOT NULL,
            subtitulo            TEXT NOT NULL DEFAULT '',
            instructor_nombre    TEXT NOT NULL,
            instructor_bio       TEXT NOT NULL DEFAULT '',
            instructor_proyectos TEXT NOT NULL DEFAULT '',
            descripcion          TEXT NOT NULL DEFAULT '',
            publico_objetivo     TEXT NOT NULL DEFAULT '',
            programa_teorica     JSONB NOT NULL DEFAULT '[]',
            programa_practica    JSONB NOT NULL DEFAULT '[]',
            fecha_inicio         DATE NOT NULL,
            fecha_fin            DATE NOT NULL,
            horario              TEXT NOT NULL DEFAULT '',
            cupos_total          INTEGER NOT NULL DEFAULT 12,
            cupos_confirmados    INTEGER NOT NULL DEFAULT 0,
            precio_total         INTEGER NOT NULL DEFAULT 0,
            precio_sena          INTEGER NOT NULL DEFAULT 0,
            pago_alias           TEXT NOT NULL DEFAULT '',
            pago_cbu             TEXT NOT NULL DEFAULT '',
            pago_banco           TEXT NOT NULL DEFAULT '',
            direccion            TEXT NOT NULL DEFAULT '',
            activo               BOOLEAN NOT NULL DEFAULT TRUE,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
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
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_taller_inscripciones_taller "
        "ON taller_inscripciones(taller_id)"
    )

    # ── Seed: Workshop Dirección de Arte × Jime Troncoso ─────────────────────
    # Guard post-F6: bootstrap fresco vía init_db() → `talleres` ya nace sin
    # esta columna (ver docstring del módulo) → el seed en shape legacy se
    # saltea entero (no tiene equivalente razonable a insertar acá).
    conn = op.get_bind()
    tiene_instructor_nombre = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'talleres' AND column_name = 'instructor_nombre'"
    )).fetchone() is not None

    if tiene_instructor_nombre:
        programa_teorica = _q(json.dumps([
            "Qué es la dirección de arte y cuál es su función dentro de un proyecto",
            "Cómo se compone y se coordina un equipo",
            "Análisis de proyectos reales: videoclip, publicidad, ambientación en evento y foto producto",
            "Armado de presupuesto (sí, vamos a hablar de números)",
            "Cómo mostrar tus proyectos y crecer dentro de la industria",
        ]))
        programa_practica = _q(json.dumps([
            "Crear el set: la clase práctica se construye sobre el proyecto elegido en la clase teórica",
            "Nos dividimos en equipos con 1 semana de preproducción previa",
            "Se suman el director de fotografía Pablo Isa y el gaffer Tincho Santini",
            "Rambla Rental provee el equipo técnico para que la práctica sea lo más real posible",
            "Vemos el resultado final juntos",
        ]))
        descripcion = _q(
            "Si llegaste hasta acá: gracias, estoy muy emocionada por hacer realidad este proyecto. "
            "El workshop incluye 2 clases en Rambla Estudio y son 12 cupos, porque quiero que sea "
            "un espacio donde podamos tener un intercambio de aprendizajes y conocimientos."
        )
        publico_objetivo = _q(
            "Directores/as, asistentes y ayudantes de arte · "
            "Creadores de contenido, fotógrafxs, filmmakers · "
            "Estudiantes de comunicación audiovisual, cine o fotografía · "
            "Personas que les interese trabajar sobre lo artístico y estético a la hora de crear proyectos"
        )
        instructor_bio = _q(
            "26 años, marplatense viviendo en CABA. Desde 2020 colabora con marcas, agencias y equipos "
            "creativos en proyectos artísticos, audiovisuales y fotográficos, pensados para entornos "
            "digitales y físicos."
        )
        instructor_proyectos = _q(
            "Universal LATAM, CheNetflix, Shorta, Spotify, Gancia, Skyy, Lucciano's, Atomik, Luigi Bosca, "
            "Shell, Las Pastillas del Abuelo, Los Pericos & El Plan de la Mariposa, Kevin Johansen, Bruto, "
            "Hops, entre otros."
        )
        op.execute(f"""
            INSERT INTO talleres (
                slug, nombre, subtitulo,
                instructor_nombre, instructor_bio, instructor_proyectos,
                descripcion, publico_objetivo,
                programa_teorica, programa_practica,
                fecha_inicio, fecha_fin, horario,
                cupos_total, precio_total, precio_sena,
                pago_alias, pago_cbu, pago_banco,
                direccion, activo
            )
            VALUES (
                'direccion-de-arte-jime-troncoso',
                'Workshop Dirección de Arte',
                'rambla × jime troncoso',
                'Jime Troncoso',
                {instructor_bio},
                {instructor_proyectos},
                {descripcion},
                {publico_objetivo},
                {programa_teorica}::jsonb,
                {programa_practica}::jsonb,
                '2026-07-11', '2026-07-18', '9 a 13 hs',
                12, 200000, 100000,
                'rambla.estudio', '0170239440000032889112', 'BBVA',
                'Chaco 1392 — Rambla Estudio',
                TRUE
            )
            ON CONFLICT (slug) DO NOTHING
        """)

    # ── Email templates ───────────────────────────────────────────────────────
    admin_html = (
        "<p style=\"margin:0 0 12px;font-size:19px;font-weight:bold;color:#1a1714;\">"
        "{% if en_lista_espera %}Nueva inscripción (lista de espera){% else %}Nueva inscripción{% endif %}</p>"
        "<p style=\"margin:0 0 8px;\"><strong>{{ nombre }}</strong> se inscribió al taller "
        "<strong>{{ taller_nombre }}</strong>.</p>"
        "{% if en_lista_espera %}"
        "<p style=\"margin:0 0 8px;color:#b45309;\"><strong>Lista de espera</strong> — los cupos están completos.</p>"
        "{% endif %}"
        "<p style=\"margin:18px 0 6px;font-size:11px;color:#6b6457;text-transform:uppercase;\">Contacto</p>"
        "<p style=\"margin:0 0 4px;\"><strong>Email:</strong> {{ email }}<br>"
        "<strong>Teléfono:</strong> {{ telefono }}</p>"
        "{% if experiencia %}"
        "<p style=\"margin:18px 0 6px;font-size:11px;color:#6b6457;text-transform:uppercase;\">Experiencia</p>"
        "<p style=\"margin:0 0 4px;\">{{ experiencia }}</p>"
        "{% endif %}"
        "{% if comprobante_url %}"
        "<p style=\"margin:18px 0 6px;font-size:11px;color:#6b6457;text-transform:uppercase;\">Comprobante</p>"
        "<p style=\"margin:0 0 4px;\"><a href=\"{{ comprobante_url }}\">Ver comprobante</a></p>"
        "{% endif %}"
        "<p style=\"margin:18px 0 0;color:#6b6457;font-size:14px;\">{{ fecha }}</p>"
    )
    admin_text = (
        "{% if en_lista_espera %}[LISTA DE ESPERA] {% endif %}"
        "Nueva inscripción — {{ taller_nombre }}\n\n"
        "Nombre: {{ nombre }}\nEmail: {{ email }}\nTeléfono: {{ telefono }}\n"
        "{% if experiencia %}Experiencia: {{ experiencia }}\n{% endif %}"
        "{% if comprobante_url %}Comprobante: {{ comprobante_url }}\n{% endif %}"
        "\nFecha: {{ fecha }}"
    )
    cliente_html = (
        "<p style=\"margin:0 0 12px;font-size:19px;font-weight:bold;color:#1a1714;\">"
        "{% if en_lista_espera %}Quedaste en lista de espera{% else %}¡Tu lugar está reservado!{% endif %}</p>"
        "<p style=\"margin:0 0 8px;\">Hola <strong>{{ nombre_pila }}</strong>, "
        "{% if en_lista_espera %}te anotamos en la lista de espera de <strong>{{ taller_nombre }}</strong>. "
        "Te avisamos si se libera un cupo.{% else %}"
        "recibimos tu inscripción a <strong>{{ taller_nombre }}</strong>. "
        "Tu seña queda confirmada cuando verifiquemos el pago.{% endif %}</p>"
        "{% if not en_lista_espera %}"
        "<p style=\"margin:18px 0 6px;font-size:11px;color:#6b6457;text-transform:uppercase;\">Fechas</p>"
        "<p style=\"margin:0 0 4px;\"><strong>Clase teórica:</strong> sábado 11 de julio, 9 a 13 hs<br>"
        "<strong>Clase práctica:</strong> sábado 18 de julio, 9 a 13 hs<br>"
        "<strong>Lugar:</strong> Chaco 1392 — Rambla Estudio</p>"
        "<p style=\"margin:18px 0 6px;font-size:11px;color:#6b6457;text-transform:uppercase;\">Datos de pago (seña 50%)</p>"
        "<p style=\"margin:0 0 4px;\"><strong>Alias:</strong> rambla.estudio<br>"
        "<strong>CBU:</strong> 0170239440000032889112<br>"
        "<strong>Banco:</strong> BBVA<br><strong>Monto:</strong> $100.000</p>"
        "{% endif %}"
        "<p style=\"margin:18px 0 0;color:#6b6457;font-size:14px;\">"
        "¿Preguntas? Respondé este mail o escribínos por WhatsApp.</p>"
        "<p style=\"margin:18px 0 0;\">— El equipo de Rambla</p>"
    )
    cliente_text = (
        "{% if en_lista_espera %}"
        "Hola {{ nombre_pila }}, te anotamos en la lista de espera de {{ taller_nombre }}.\n\n"
        "Te avisamos si se libera un cupo.\n"
        "{% else %}"
        "Hola {{ nombre_pila }}, recibimos tu inscripción a {{ taller_nombre }}.\n\n"
        "Clase teórica: sábado 11 de julio, 9 a 13 hs\n"
        "Clase práctica: sábado 18 de julio, 9 a 13 hs\n"
        "Lugar: Chaco 1392 — Rambla Estudio\n\n"
        "Datos de pago (seña 50%):\n"
        "  Alias: rambla.estudio\n"
        "  CBU: 0170239440000032889112\n"
        "  Banco: BBVA\n"
        "  Monto: $100.000\n"
        "{% endif %}\n"
        "¿Preguntas? Respondé este mail.\n\n— El equipo de Rambla"
    )
    for key, subject, body_html, body_text in [
        (
            "taller_inscripcion_admin",
            "Nueva inscripción{% if en_lista_espera %} (lista de espera){% endif %} — {{ taller_nombre }} ({{ nombre }})",
            admin_html,
            admin_text,
        ),
        (
            "taller_inscripcion_cliente",
            "{% if en_lista_espera %}Quedaste en lista de espera{% else %}¡Tu lugar está reservado!{% endif %} — {{ taller_nombre }}",
            cliente_html,
            cliente_text,
        ),
    ]:
        op.execute(f"""
            INSERT INTO email_templates (key, subject, body_html, body_text, updated_by)
            VALUES (
                {_q(key)}, {_q(subject)}, {_q(body_html)}, {_q(body_text)},
                'system:migration'
            )
            ON CONFLICT (key) DO NOTHING
        """)


def downgrade() -> None:
    op.execute("DELETE FROM email_templates WHERE key IN ('taller_inscripcion_admin', 'taller_inscripcion_cliente')")
    op.execute("DROP TABLE IF EXISTS taller_inscripciones CASCADE")
    op.execute("DROP TABLE IF EXISTS talleres CASCADE")
