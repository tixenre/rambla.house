"""dataio/schema.py — Pydantic models para cada entidad del catálogo.

Estos modelos definen la forma exacta de los JSONs en `/data/catalog/*.json`.
Sirven tanto para validar al importar como para serializar al exportar.

Reglas:
- NUNCA incluir `id` SERIAL.
- FKs siempre como claves naturales (nombre, slug, path).
- M2M de equipos (categorías) embebida dentro de `EquipoIn` para que
  `equipos.json` sea autosuficiente.
- `equipo_specs` y `equipo_fichas` viven en archivos aparte porque tienen
  más volumen y se editan independientemente de los datos básicos del equipo.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    """Base común — prohíbe campos extra para detectar typos en los JSONs."""

    model_config = ConfigDict(extra="forbid")


# ─────────────────────────────────────────────────────────────────────────────
# marcas.json
# ─────────────────────────────────────────────────────────────────────────────


class Marca(_Base):
    nombre: str
    logo_url: str | None = None
    visible: bool = True
    orden: int = 100
    destacada: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# categorias.json
# ─────────────────────────────────────────────────────────────────────────────


class Categoria(_Base):
    nombre: str
    parent_path: str | None = None  # Nombre del padre, None para raíces
    prioridad: int = 100
    visible: bool = True
    grupo_visual: str | None = None
    nombre_publico_template: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# spec_definitions.json
# ─────────────────────────────────────────────────────────────────────────────


class SpecRef(_Base):
    """Referencia composite a un spec_definition.

    `categoria_raiz_nombre` puede ser None para specs globales sin categoría
    (admin endpoint los crea como "free-floating").
    """

    categoria_raiz_nombre: str | None = None
    spec_key: str


class SpecDefinition(_Base):
    categoria_raiz_nombre: str | None = None  # FK → categorias.nombre
    spec_key: str
    label: str
    tipo: Literal["enum", "multi_enum", "number", "rango", "bool", "string"]
    unidad: str | None = None
    enum_options: list[Any] | None = None  # JSONB
    ayuda: str | None = None
    es_compatibilidad: bool = False
    compatibilidad_modo: Literal["exacta", "jerarquia"] = "exacta"
    rol_compatibilidad: str | None = None
    validado: bool = False
    tabla_columnas: list[dict[str, Any]] | dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None
    favorito: bool = False
    en_nombre: bool = False
    en_filtros: bool = False
    prioridad: int = 100


# ─────────────────────────────────────────────────────────────────────────────
# categoria_spec_templates.json
# ─────────────────────────────────────────────────────────────────────────────


class CategoriaSpecTemplate(_Base):
    categoria_nombre: str  # FK → categorias.nombre
    spec_ref: SpecRef  # FK → spec_definitions(categoria_raiz_nombre, spec_key)
    prioridad: int = 100
    destacado: bool = False
    obligatorio: bool = False
    visible_en_card: bool = False
    visible_en_filtros: bool = False
    visible_en_nombre: bool = False
    ayuda: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# equipos.json (M2M embebidas)
# ─────────────────────────────────────────────────────────────────────────────


class EquipoCategoriaRef(_Base):
    """Ref a una categoría dentro de un equipo (M2M embebida)."""

    nombre: str
    orden: int = 0


class Equipo(_Base):
    # Identidad
    slug: str  # clave natural (NEW: agregada por migración)
    nombre: str
    marca: str | None = None  # campo legacy TEXT, se mantiene
    modelo: str | None = None
    marca_nombre: str | None = None  # FK → marcas.nombre (resuelve brand_id)

    # Catálogo
    cantidad: int = 1
    precio_jornada: int | None = None
    precio_jornada_manual: bool = False
    precio_usd: float | None = None
    roi_pct: float | None = None
    valor_reposicion: float | None = None
    foto_url: str | None = None
    fecha_compra: str | None = None
    serie: str | None = None
    bh_url: str | None = None
    dueno: str | None = "Rambla"
    visible_catalogo: int = 1
    estado: str = "operativo"
    ficha_completa: bool = False
    eliminado_at: str | None = None  # ISO timestamp o null

    # Nombre público
    nombre_publico_override: str | None = None
    nombre_publico_revisado: bool = False

    # Ranking
    relevancia_manual: int = 100

    # M2M embebida
    categorias: list[EquipoCategoriaRef] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# equipo_specs.json
# ─────────────────────────────────────────────────────────────────────────────


class EquipoSpec(_Base):
    equipo_slug: str
    spec_ref: SpecRef
    value: str  # serializado igual que en DB (TEXT)


# ─────────────────────────────────────────────────────────────────────────────
# equipo_fichas.json
# ─────────────────────────────────────────────────────────────────────────────


class EquipoFicha(_Base):
    equipo_slug: str
    descripcion: str | None = None
    notas: str | None = None
    keywords_json: str | None = None
    nombre_publico_template: str | None = None
    conectividad_json: str | None = None
    compatible_con_json: str | None = None
    video_url: str | None = None
    precio_bh_usd: float | None = None
    fuente_url: str | None = None
    fuente_titulo: str | None = None
    enriquecido_at: str | None = None
    enriquecido_fuente: str | None = None
    # Fase F: montura/formato/resolucion/peso/dimensiones/alimentacion
    # se migraron a equipo_specs y se droppearon de equipo_fichas.
    # Fase E: specs_json y raw_json eliminados.


# ─────────────────────────────────────────────────────────────────────────────
# OPERATIONAL — clientes, alquileres (con items/pagos embebidos)
# ─────────────────────────────────────────────────────────────────────────────
#
# IMPORTANTE: estos JSONs NUNCA se commitean al repo (contienen datos
# personales y comerciales). Solo se generan ad-hoc vía /admin/dataio o
# CLI para backups o migración entre ambientes.


class Cliente(_Base):
    # Clave natural
    email: str  # UNIQUE en DB
    # Datos personales
    nombre: str
    apellido: str
    telefono: str | None = None
    direccion: str | None = None
    direccion_maps_url: str | None = None
    cuit: str | None = None
    notas: str | None = None
    # Comercial / fiscal
    descuento: float = 0.0
    perfil_impuestos: str = "consumidor_final"
    razon_social: str | None = None
    domicilio_fiscal: str | None = None
    email_facturacion: str | None = None
    # Link a Supabase Auth (opcional; no portable entre proyectos Supabase)
    supabase_uid: str | None = None


class AlquilerItemRef(_Base):
    """Item embebido dentro de un Alquiler (no es entidad top-level)."""
    equipo_slug: str  # FK → equipos.slug
    cantidad: int = 1
    precio_jornada: int = 0
    subtotal: int = 0


class AlquilerPagoRef(_Base):
    """Pago embebido dentro de un Alquiler. No tiene clave natural propia
    — la combinación (numero_pedido + fecha + monto + concepto) se trata
    como identidad para evitar duplicarlos en re-imports.

    `anulado` + sus columnas de auditoría viajan tal cual (#1184/#1209): un
    pago anulado es soft-delete y NO debe "revivir" activo tras un
    export→import — antes se perdían en el viaje y el import los reinsertaba
    con el default de la columna (`anulado=FALSE`).
    """
    monto: int
    concepto: str | None = None
    fecha: str  # ISO date string
    anulado: bool = False
    anulado_por: str | None = None
    anulado_at: str | None = None  # ISO datetime string
    anulado_motivo: str | None = None


class Alquiler(_Base):
    # Clave natural
    numero_pedido: int  # UNIQUE en DB
    # FK natural → cliente (puede ser null si cliente fue eliminado).
    # Los campos cliente_* denormalizados preservan el snapshot histórico.
    cliente_email: str | None = None
    cliente_nombre: str
    cliente_telefono: str | None = None
    # Estado y fechas
    estado: str = "solicitado"
    fecha_desde: str
    fecha_hasta: str
    # Familia del pedido (`tipos_pedido.py`) — sin esto, un ciclo export→import
    # devolvía TODO como 'diaria': un turno del Estudio o un pedido de taller
    # revivían como alquiler normal, con su rango contable leído como fechas
    # reales.
    tipo: str = "diaria"
    # Vínculo a un pedido principal (#1308) — por NÚMERO, no por id: los ids
    # difieren entre ambientes (mismo criterio que `equipo_slug` en los items).
    # Se resuelve en una segunda pasada del import, porque el principal puede
    # venir después que su turno en el archivo.
    pedido_principal_numero: int | None = None
    # Montos
    monto_total: int = 0
    monto_pagado: int = 0
    descuento_pct: float = 0.0
    # Metadata
    notas: str | None = None
    fuente: str = "sistema"
    # Embebidas para autosuficiencia
    items: list[AlquilerItemRef] = Field(default_factory=list)
    pagos: list[AlquilerPagoRef] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# estudio.json (singleton + listas embebidas)
# ─────────────────────────────────────────────────────────────────────────────


class EstudioFoto(_Base):
    url: str
    path: str | None = None
    orden: int = 0
    es_principal: bool = False


class EstudioPackEquipo(_Base):
    equipo_slug: str  # FK → equipos.slug
    orden: int = 0


class EstudioSlotFijo(_Base):
    cliente: str
    dia_semana: int
    hora_desde: int
    hora_hasta: int
    valor_mensual: int = 0
    mes_desde: str  # ISO date string "YYYY-MM-DD"
    mes_hasta: str
    activo: bool = True


class Estudio(_Base):
    # Singleton — equipo centinela que representa el espacio
    equipo_slug: str | None = None  # FK → equipos.slug
    nombre: str = "El Estudio"
    tagline: str = ""
    descripcion: str = ""
    precio_hora: int = 0
    min_horas: int = 2
    open_hour: int = 8
    close_hour: int = 22
    buffer_horas: int = 0
    pack_activo: bool = True
    pack_nombre: str = ""
    pack_descripcion: str = ""
    pack_precio: int = 0
    features_json: str | None = None
    faq_json: str | None = None
    direccion: str = ""
    como_llegar: str = ""
    testimonios_json: str | None = None
    anticipacion_min_horas: int = 0
    mapa_url: str = ""
    mapa_embed_url: str = ""
    # Listas embebidas — se reemplazan completas en cada import
    fotos: list[EstudioFoto] = Field(default_factory=list)
    pack_equipos: list[EstudioPackEquipo] = Field(default_factory=list)
    slots_fijos: list[EstudioSlotFijo] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — ajustes del sistema, plantillas de mail, descuentos
# (parte del grupo "configuración" del backup; sin datos personales)
# ─────────────────────────────────────────────────────────────────────────────


class AppSetting(_Base):
    key: str  # clave natural (PK)
    value: str


class EmailTemplate(_Base):
    key: str  # clave natural (PK)
    subject: str
    body_html: str
    body_text: str


class DescuentoJornada(_Base):
    jornadas: int  # clave natural (UNIQUE)
    pct: float


# ─────────────────────────────────────────────────────────────────────────────
# Mapping entity → model (usado por exporters/importers)
# ─────────────────────────────────────────────────────────────────────────────

ENTITY_MODELS: dict[str, type[_Base]] = {
    "marcas": Marca,
    "categorias": Categoria,
    "spec_definitions": SpecDefinition,
    "categoria_spec_templates": CategoriaSpecTemplate,
    "equipos": Equipo,
    "equipo_specs": EquipoSpec,
    "equipo_fichas": EquipoFicha,
    "estudio": Estudio,
    "app_settings": AppSetting,
    "email_templates": EmailTemplate,
    "descuentos_jornada": DescuentoJornada,
    "clientes": Cliente,
    "alquileres": Alquiler,
}
