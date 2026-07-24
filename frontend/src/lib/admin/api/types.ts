/**
 * Tipos del admin API — todos los tipos exportados de api.ts, centralizados acá.
 */

import type { EstadoPedido } from "@/lib/pedido-estados";
export type { EstadoPedido };

// ── Dashboard ────────────────────────────────────────────────────────────

/** Campos que el dashboard de calidad sabe detectar como faltantes (#349, #350). */
export type FaltaField =
  | "foto"
  | "categoria"
  | "nombre_publico"
  | "descripcion"
  | "serie"
  | "valor_reposicion";

/** Sugerencia automática del sistema (#352). */
export type Sugerencia = {
  tipo: "marcas_duplicadas" | "precio_sin_usd" | "categoria_sospechosa";
  ref: string;
  titulo: string;
  detalle: string;
  accion: "fusionar" | "calcular_usd" | "asignar_categoria" | string;
  accion_label: string;
  // Payloads específicos por tipo.
  marcas?: Array<{ id: number; nombre: string; cant_pedidos: number; equipos: number }>;
  equipos?: Array<{ id: number; nombre: string; marca: string | null; precio_jornada: number }>;
  equipo_id?: number;
  categoria_sugerida?: string;
};

export type SugerenciasResp = {
  items: Sugerencia[];
  total: number;
};

export type CalidadInventario = {
  total: number;
  completos_pct: number;
  faltantes: {
    serie: number;
    valor_reposicion: number;
    foto: number;
    descripcion: number;
    nombre_publico: number;
    categoria: number;
  };
};

export type DashboardData = {
  pendientes: number;
  activos: number;
  ingresos_mes: number;
  total_clientes: number;
  salen_hoy: PedidoResumen[];
  devuelven_hoy: PedidoResumen[];
  devuelven_manana: PedidoResumen[];
  equipos_afuera: EquipoAfuera[];
};

export type PedidoResumen = {
  id: number;
  cliente_nombre: string;
  fecha_desde: string;
  fecha_hasta: string;
  monto_total: number;
};

export type EquipoAfuera = {
  nombre: string;
  marca: string | null;
  cantidad: number;
  cliente_nombre: string;
  fecha_hasta: string;
};

// ── Equipos ──────────────────────────────────────────────────────────────

export type Ficha = {
  descripcion: string | null;
  notas: string | null;
  keywords_json: string | null;
  nombre_publico_template?: string | null;
  // Listas / multimedia del enriquecimiento (no son specs estructuradas).
  // `incluye_json` (legacy) dropeado: el "qué incluye" deriva de la receta real.
  conectividad_json?: string | null;
  compatible_con_json?: string | null;
  video_url?: string | null;
  precio_bh_usd?: number | null;
  fuente_url?: string | null;
  fuente_titulo?: string | null;
  enriquecido_at?: string | null;
  enriquecido_fuente?: string | null;
  // Fase F: montura/formato/resolucion/peso/dimensiones/alimentacion
  // se droppearon de equipo_fichas. Las specs viven en equipo_specs.
  // B1 #635: contenido incluido (dim. 3) — [{nombre, cantidad, foto_url?}]
  contenido_incluido_json?: string | null;
};

export type CategoriaRef = {
  id: number;
  nombre: string;
  parent_id: number | null;
};

export type Equipo = {
  id: number;
  nombre: string;
  marca: string | null;
  modelo: string | null;
  cantidad: number;
  precio_jornada: number | null;
  /** True si el admin editó el precio a mano (no viene de la fórmula).
   *  El recálculo masivo en modo "auto" respeta estos precios. */
  precio_jornada_manual?: boolean;
  precio_usd: number | null;
  roi_pct: number | null;
  valor_reposicion: number | null;
  foto_url: string | null;
  fecha_compra: string | null;
  serie: string | null;
  bh_url: string | null;
  dueno: string | null;
  visible_catalogo: number;
  estado: string;
  /** Flag manual del admin: ficha cargada y revisada (no requiere más trabajo). */
  ficha_completa?: boolean;
  /** Categoría de specs (1 de las 5 del registry): define qué specs aplican
   *  y el nombre público. Independiente del árbol de categorías de catálogo
   *  (`categorias`), que es solo agrupación para el front-office. */
  categoria_specs?: string | null;
  /** Tipo de producto. Gobierna precio, stock y disponibilidad.
   *  'simple' = equipo suelto · 'kit' = con accesorios compartidos · 'combo' = agrupación derivada. */
  tipo?: "simple" | "kit" | "combo";
  /** URL pública del HTML de producto guardado en R2 (para re-extracción futura). */
  html_source_url?: string | null;
  /** Timestamp ISO si el equipo está soft-deleted. null = activo (#206). */
  eliminado_at?: string | null;
  kit?: KitComponente[];
  categorias?: CategoriaRef[];
  ficha?: Ficha;
  /** Nombre público corto (catálogo / cards). Lo arma el backend a partir de specs. */
  nombre_publico?: string | null;
  /** Nombre público extendido (PDFs formales: albarán, contrato). */
  nombre_publico_largo?: string | null;
  /** Override manual del nombre público — gana sobre el molde de categoría
   *  siempre (ver services/nombre_builder.py). Se edita vía `aprobarNombre`. */
  nombre_publico_override?: string | null;
  /** true = nombre aprobado/editado a mano; false = pendiente de revisión. */
  nombre_publico_revisado?: boolean;
  /** Relevancia manual (1=más destacado, 100=neutro). */
  relevancia_manual?: number;
  /** Score de popularidad (0..100, normalizado por categoría). */
  popularidad_score?: number;
};

export type KitComponente = {
  componente_id: number;
  cantidad: number;
  orden: number;
  nombre: string;
  marca?: string | null;
  foto_url?: string | null;
  /** Descuento % por línea (para combos — fase C3). */
  descuento_pct?: number | null;
  /** True = esencial (falta → combo no disponible); False = best-effort (fase C2). */
  esencial?: boolean | null;
};

export type EquiposListResp = {
  total: number;
  page: number;
  per_page: number;
  items: Equipo[];
};

export type EquipoInput = Partial<Omit<Equipo, "id" | "kit" | "categorias" | "ficha">> & {
  nombre: string;
};

// Categoría: vive en su propia taxonomía (tabla `categorias`).
export type CategoriaAdmin = {
  id: number;
  nombre: string;
  prioridad: number;
  parent_id: number | null;
  /** Si false, la categoría no se muestra en el catálogo público. */
  visible: boolean;
  /** Plantilla para generar nombre público de equipos en esta categoría.
   *  Sintaxis: {marca} {modelo} {tipo} {spec:Label}. NULL = sin template. */
  nombre_publico_template?: string | null;
  total: number;
};

// Árbol público para filtros del catálogo.
export type Categoria = {
  id?: number;
  nombre: string;
  total: number;
  prioridad: number;
  parent_id?: number | null;
  children?: Categoria[];
  // legacy flat
  subtags?: { nombre: string; total: number }[];
};

// ── Mantenimiento por equipo ─────────────────────────────────────────────

export type MantenimientoEvento = {
  id: number;
  equipo_id: number;
  fecha: string;
  tipo: string; // revision / reparacion / limpieza / otro
  descripcion: string | null;
  costo: number | null;
  proxima_revision: string | null;
  fecha_hasta: string | null;
  cantidad: number;
  bloquea_stock: boolean;
  created_at?: string;
};

export type MantenimientoInput = {
  fecha: string;
  tipo?: string;
  descripcion?: string | null;
  costo?: number | null;
  proxima_revision?: string | null;
  fecha_hasta?: string | null;
  cantidad?: number;
  bloquea_stock?: boolean;
};

export type MarcaAdmin = {
  id: number;
  nombre: string;
  logo_url?: string | null;
  visible: boolean;
  /** Flag para destacar en el BrandCarousel del home. #288 */
  destacada: boolean;
  orden: number;
  total: number;
};

// ── Templates de specs por categoría (CRUD admin) ────────────────────────

export type SpecTipo =
  | "string"
  | "number"
  | "enum"
  | "bool"
  | "rango"
  | "wxh"
  | "wxhxd"
  | "multi_enum"
  | "tabla";

/** Tipo de una columna individual cuando spec_definitions.tipo='tabla'.
 *  - `valor_unidad`: la celda tiene 2 sub-campos (número + unidad), permite
 *    que la unidad varíe por fila (ej. 10000 lumen / 8000 lumen). */
export type SpecTablaColTipo = "string" | "number" | "enum" | "bool" | "valor_unidad";

/** Una columna de una spec tipo tabla. Define qué se carga en cada celda
 *  y cómo se renderiza el input. */
export type SpecTablaColumna = {
  key: string;
  label: string;
  tipo: SpecTablaColTipo;
  /** Para tipo='enum': opciones permitidas. */
  options?: string[];
  /** Sufijo visual (lm, °C, etc.). Solo para tipos escalares. */
  unidad?: string | null;
  /** Para tipo='valor_unidad': lista cerrada de unidades permitidas. Si está
   *  definida, el input de unidad se renderiza como select. Si no, input libre. */
  unidades_opciones?: string[];
  /** Texto fijo que aparece ANTES del valor — sirve como conector textual
   *  entre columnas. Ej. col2.prefijo="a" → "10000 lm a 5700 K". */
  prefijo?: string | null;
};

/** Definición global de una spec (post refactor unificar_specs_definitions).
 *  Cada spec_key existe UNA sola vez en el sistema. Sus categorías la
 *  referencian via spec_def_id en la asignación. */
export type CompatibilidadModo = "exacta" | "jerarquia";
export type RolCompatibilidad = "contenedor" | "contenido" | null;

/** Config declarativa de cómo se rinde la spec en un placeholder {spec:Label}.
 *  Aplicada por backend/services/spec_render.py y mirroreada en
 *  src/lib/equipment/nombre-template.ts. */
export type SpecRowStrategy = "all" | "first" | "last";
export type SpecOutputConfig = {
  /** Solo aplica a tipo='tabla'. Default 'all'. */
  row_strategy?: SpecRowStrategy;
};

/** Asignación de una spec a una categoría (con su template_id para poder
 *  desasignar desde el modal de edición). */
export type SpecDefinitionCategoriaAsign = {
  id: number;
  nombre: string;
  template_id: number;
  /** Flags por categoría — el detalle vive en "Specs por categoría". Solo
   *  los exponemos acá para que el modal global muestre inline si tienen
   *  override por categoría (read-only). */
  destacado: boolean;
  prioridad: number;
  ayuda: string | null;
};

export type SpecDefinition = {
  id: number;
  spec_key: string;
  label: string;
  tipo: SpecTipo;
  unidad: string | null;
  /** FK al catálogo `unidades` (sync con el string `unidad` por el backend).
   *  null si la spec no tiene unidad asociada. */
  unidad_id: number | null;
  enum_options: string[] | null;
  ayuda: string | null;
  es_compatibilidad: boolean;
  compatibilidad_modo: CompatibilidadModo;
  /** Flag manual: el dueño la revisó y aprobó. Se ordenan arriba. */
  validado: boolean;
  /** Solo para tipo='tabla': shape de las columnas. */
  tabla_columnas: SpecTablaColumna[] | null;
  /** Config declarativa de render del placeholder. Solo `row_strategy` por ahora. */
  output_config: SpecOutputConfig | null;
  /** Solo en GET /admin/spec-definitions: cuántas categorías la asignaron. */
  uso_categorias?: number;
  /** Solo en GET /admin/spec-definitions: cuántos equipos tienen value. */
  uso_equipos?: number;
  /** Solo en GET: categorías que la asignan (con id + nombre + template_id). */
  categorias?: SpecDefinitionCategoriaAsign[];
};

/** Una unidad del catálogo global (lm, K, V…). */
export type Unidad = {
  id: number;
  simbolo: string;
  nombre: string;
  dimension: string | null;
};

export type UnidadInput = {
  simbolo: string;
  nombre: string;
  dimension?: string | null;
};

export type SpecDefinitionInput = {
  spec_key: string;
  label: string;
  tipo: SpecTipo;
  unidad?: string | null;
  enum_options?: string[] | null;
  ayuda?: string | null;
  es_compatibilidad?: boolean;
  compatibilidad_modo?: CompatibilidadModo;
  validado?: boolean;
  tabla_columnas?: SpecTablaColumna[] | null;
  output_config?: SpecOutputConfig | null;
};

/** Asignación de una spec_def a una categoría + flags propios. El backend
 *  hace JOIN con spec_definitions y proyecta los campos descriptivos
 *  (spec_key/label/tipo/unidad/enum_options) acá para que el frontend
 *  los use sin un fetch extra. */
export type SpecTemplate = {
  id: number;
  categoria_id: number;
  spec_def_id: number;
  // Proyectados desde spec_definitions:
  spec_key: string;
  label: string;
  tipo: SpecTipo;
  unidad: string | null;
  unidad_id: number | null;
  enum_options: string[] | null;
  tabla_columnas: SpecTablaColumna[] | null;
  output_config: SpecOutputConfig | null;
  es_compatibilidad: boolean;
  compatibilidad_modo: CompatibilidadModo;
  // Per-categoría: (los flags aplicados por la asignación)
  prioridad: number;
  visible_en_card: boolean;
  visible_en_filtros: boolean;
  visible_en_nombre: boolean;
  obligatorio: boolean;
  ayuda: string | null;
  destacado: boolean;
  rol_compatibilidad: RolCompatibilidad;
};

/** Grupo de specs sin match del panel admin (#1203) — un label sin
 *  reconocer, agregado a través de todos los equipos que lo encontraron. */
export type NoReconocidoGrupo = {
  categoria: string;
  label: string;
  label_normalizado: string;
  ejemplos: string[];
  propuesta_ids: number[];
  equipo_ids: number[];
  equipo_nombres: string[];
  ultima_vez: string;
};

/** Body para asignar una spec ya existente a una categoría. */
export type SpecAssignmentInput = {
  spec_def_id: number;
  prioridad?: number;
  destacado?: boolean;
  obligatorio?: boolean;
  visible_en_card?: boolean;
  visible_en_filtros?: boolean;
  visible_en_nombre?: boolean;
  ayuda?: string | null;
  rol_compatibilidad?: RolCompatibilidad;
};

/** Body para editar los flags de una asignación. */
export type SpecAssignmentUpdate = {
  prioridad?: number;
  destacado?: boolean;
  obligatorio?: boolean;
  visible_en_card?: boolean;
  visible_en_filtros?: boolean;
  visible_en_nombre?: boolean;
  ayuda?: string | null;
  rol_compatibilidad?: RolCompatibilidad;
};

/** Compat alias: el SpecTemplatesSection viejo usaba SpecTemplateInput. Lo
 *  mantengo como alias para no romper imports — pero los nuevos callers
 *  deben usar SpecAssignmentInput o SpecDefinitionInput según contexto. */
export type SpecTemplateInput = SpecAssignmentInput;

// Dashboard de uso (#205)
export type DashboardUsoEquipo = {
  id: number;
  nombre: string;
  marca: string | null;
  modelo: string | null;
  foto_url: string | null;
  cant_pedidos: number;
  revenue_total: number | null;
};

export type DashboardUsoSinUso = {
  id: number;
  nombre: string;
  marca: string | null;
  modelo: string | null;
  foto_url: string | null;
  valor_reposicion: number | null;
  ultimo_alquiler: string | null;
  total_alquileres: number;
};

export type DashboardUsoCategoria = {
  id: number;
  nombre: string;
  cant_pedidos: number;
  revenue_total: number | null;
};

export type DashboardUsoPorCobrarItem = {
  id: number;
  numero_pedido: string | number | null;
  estado: string;
  cliente: string;
  fecha_desde: string;
  fecha_hasta: string;
  monto_total: number;
  monto_pagado: number;
  pendiente: number;
};

export type DashboardUso = {
  totales: {
    total_equipos: number;
    total_visibles: number;
    total_pedidos: number;
    revenue_total: number | null;
  };
  top_alquilados: DashboardUsoEquipo[];
  sin_uso: DashboardUsoSinUso[];
  por_categoria: DashboardUsoCategoria[];
  por_cobrar: {
    total: number;
    count: number;
    items: DashboardUsoPorCobrarItem[];
  };
  dias_sin_uso_threshold: number;
};

export type OrphanSpec = {
  spec_def_id: number;
  spec_key: string;
  label: string;
  count_equipos: number;
  sample_values: string[];
};

/** Overall status de la compatibilidad automática.
 *  - compatible: todas las specs comparten valor exacto.
 *  - compatible_con_crop: jerárquica donde el contenedor proyecta más grande
 *    que el contenido (lente FF en sensor APS-C ⇒ crop central, usable).
 *  - parcial: viñetea u otra mismatch jerárquica con roles definidos.
 *  - incompatible: alguna spec exacta no matchea, o manual override negativo.
 *  - requiere_adaptador: manual `equipo_compatibilidad` con adaptador linkeado.
 *  - sin_relacion: no comparten specs con es_compatibilidad=true. */
export type CompatibleOverall =
  | "compatible"
  | "compatible_con_crop"
  | "parcial"
  | "incompatible"
  | "requiere_adaptador"
  | "sin_relacion";

export type CompatibleRazon = {
  spec: string;
  status: "match" | "match_con_crop" | "mismatch" | "partial_vignette" | "partial";
  mensaje: string;
};

export type CompatibleEquipo = {
  equipo_id: number;
  nombre: string;
  foto_url: string | null;
  marca: string | null;
  overall: CompatibleOverall;
  razones: CompatibleRazon[];
  adaptador?: { id: number; nombre: string } | null;
};

// ── Propuestas IA del skill gear-compatibility ──────────────────────
export type PropuestaTipo = "enum_option" | "spec_nueva" | "merge_specs" | "assign_spec";

/** Una propuesta pendiente generada por el skill `gear-compatibility`.
 *  Hasta aplicarla, no afecta el catálogo. El payload varía por tipo. */
export type PropuestaPendiente = {
  id: number;
  tipo: PropuestaTipo;
  payload: Record<string, unknown>;
  origen: string | null;
  confianza: number | null;
  created_at: string;
  aplicado_at: string | null;
  descartado_at: string | null;
};

/** Equipo pendiente de análisis de compatibilidad. Lo lista el skill
 *  cuando se invoca `/gear-compat new`. */
export type EquipoPendienteCompat = {
  id: number;
  nombre: string;
  marca: string | null;
  modelo: string | null;
  categorias: string[];
  compat_analizado_at: string | null;
  motivo: "nunca_analizado" | "modificado" | "al_dia";
};

// Pagos: destinatario (a quién se cobró) y método. Espeja las constantes del
// backend (`contabilidad/constants.py::COBRADORES`); los defaults se aplican en el modal.
export const DESTINATARIOS_PAGO = ["Rambla", "Tincho", "Pablo", "Estudio"] as const;
export const METODOS_PAGO = ["transferencia", "efectivo"] as const;

export interface PagoLogRow {
  id: number;
  pedido_id: number;
  monto: number;
  concepto: string | null;
  destinatario: string | null;
  metodo: string | null;
  fecha: string;
  created_by: string | null;
  anulado: boolean;
  anulado_por: string | null;
  anulado_at: string | null;
  anulado_motivo: string | null;
  numero_pedido: number | null;
  cliente_nombre: string | null;
}
export interface PagosLogResp {
  pagos: PagoLogRow[];
  total: number;
  count: number;
}

// Contabilidad (#809) — cuentas/cajas con saldo. Los ingresos por alquiler ya
// vienen DERIVADOS de alquiler_pagos (no se cargan a mano).
export const TIPOS_CUENTA = ["caja", "banco", "socio", "fondo"] as const;
export type TipoCuenta = (typeof TIPOS_CUENTA)[number];

export interface Cuenta {
  id: number;
  nombre: string;
  tipo: TipoCuenta;
  socio: string | null;
  moneda: string;
  saldo_inicial: number;
  fecha_apertura: string;
  activa: boolean;
  orden: number;
}
export type EstadoCuentaCorriente = "deudor" | "acreedor" | "saldado";
export interface CuentaSaldo {
  id: number;
  nombre: string;
  tipo: TipoCuenta;
  socio: string | null;
  moneda: string;
  saldo_inicial: number;
  ingresos_alquiler: number;
  entradas: number;
  egresos: number;
  saldo: number;
  /** Cuenta corriente de socio (Pablo/Tincho): deudor/acreedor, no caja de plata. */
  es_cuenta_corriente: boolean;
  /** Su parte (comisión devengada) — solo cuentas corrientes. */
  su_parte: number;
  estado: EstadoCuentaCorriente | null;
}
export interface SaldosData {
  /** Todas (compat). Para mostrar, usar `cajas` y `socios` por separado. */
  cuentas: CuentaSaldo[];
  /** Cajas de plata real del negocio (suman al total disponible). */
  cajas: CuentaSaldo[];
  /** Cuentas corrientes de socio (Pablo/Tincho) — deudor/acreedor. */
  socios: CuentaSaldo[];
  totales: Record<string, number>;
  total_disponible: number;
  as_of: string;
}
export interface SugeridoRendicion {
  de: string;
  a: string;
  monto: number;
}
export interface TableroData {
  mes: string;
  cierre: { cerrado: boolean; cerrado_por: string | null; cerrado_at: string | null };
  disponible: SaldosData;
  ganancia_mes: { mes: string; ingresos: number; gastos: number; neta: number };
}
export interface RendicionPersona {
  persona: string;
  le_corresponde: number;
  cobro: number;
  ya_rindio: number;
  pendiente: number;
}
export interface RendicionMovimiento {
  id: number;
  monto: number;
  fecha: string;
  metodo: string | null;
  nota: string | null;
  anulado: boolean;
  created_by: string | null;
  created_at: string;
  origen: string | null;
  destino: string | null;
}
export interface ReconciliacionContable {
  ok: boolean;
  saldos_negativos: { cantidad: number; cuentas: { cuenta: string; saldo: number }[] };
  pagos_sin_socio: { cantidad: number; monto: number };
  movimientos_cuenta_inactiva: { cantidad: number };
  reporte: {
    ok: boolean;
    pagados_sin_ledger?: { cantidad: number; ids: number[] } | null;
    sobrepagados?: { cantidad: number; ids: number[] } | null;
  };
}
export interface RendicionData {
  mes: string;
  desde: string;
  hasta: string;
  cerrado: boolean;
  cierre_contable: boolean;
  corresponde: Record<string, number>;
  cobrado: Record<string, number>;
  sin_asignar: number;
  ya_transferido: Record<string, number>;
  personas: RendicionPersona[];
  sugeridos: SugeridoRendicion[];
  total_reporte: number;
  total_cobrado: number;
  cuadra: boolean;
  advertencias: string[];
  movimientos: RendicionMovimiento[];
}
export interface CuentaInput {
  nombre: string;
  tipo: TipoCuenta;
  socio?: string | null;
  moneda?: string;
  saldo_inicial?: number;
  fecha_apertura?: string | null;
  orden?: number;
}

export const TIPOS_MOVIMIENTO = ["gasto", "transferencia", "retiro", "aporte", "ajuste"] as const;
export type TipoMovimiento = (typeof TIPOS_MOVIMIENTO)[number];

export interface GastoCategoria {
  id: number;
  nombre: string;
  activa: boolean;
  orden: number;
}
export interface Movimiento {
  id: number;
  tipo: TipoMovimiento;
  monto: number;
  cuenta_origen_id: number | null;
  cuenta_destino_id: number | null;
  categoria_id: number | null;
  metodo: string | null;
  fecha: string;
  nota: string | null;
  beneficiario: string | null;
  comprobante_url: string | null;
  es_rendicion: boolean;
  rendicion_mes: string | null;
  anulado: boolean;
  anulado_motivo: string | null;
  created_by: string | null;
  created_at: string;
  cuenta_origen_nombre: string | null;
  cuenta_destino_nombre: string | null;
  categoria_nombre: string | null;
  moneda: string;
  cotizacion: number | null;
  movimiento_par_id: number | null;
}
export interface MovimientoInput {
  tipo: TipoMovimiento;
  monto: number;
  cuenta_origen_id?: number | null;
  cuenta_destino_id?: number | null;
  categoria_id?: number | null;
  metodo?: string | null;
  fecha?: string | null;
  nota?: string | null;
  beneficiario?: string | null;
}
export interface CambioDivisaInput {
  cuenta_origen_id: number;
  cuenta_destino_id: number;
  monto_origen?: number | null;
  monto_destino?: number | null;
  cotizacion?: number | null;
  fecha?: string | null;
  nota?: string | null;
}
export interface CambioDivisaResult {
  origen: Movimiento;
  destino: Movimiento;
  cotizacion: number;
}
export interface GastosPorCategoria {
  por_categoria: { categoria: string; monto: number }[];
  total: number;
}
export interface ReporteMensual {
  mes: string;
  desde: string;
  hasta: string;
  cerrado: boolean;
  devengado: { total: number; pedidos: number; por_socio: Record<string, number> };
  cobrado: { por_socio: Record<string, number>; total: number };
  gastos: { total: number; por_categoria: { categoria: string; monto: number }[] };
  /** Lo facturado que NO es de Rambla (parte de los dueños): un costo, no ganancia. */
  comisiones_duenos: number;
  ganancia_neta: number;
  socios_mes: {
    cargos: Record<string, number>;
    pagos: Record<string, number>;
    cargos_total: number;
    pagos_total: number;
  };
  cuenta_corriente: CuentaSaldo[];
}
// Cobros de pedidos agregados por mes (read-only) para la vista unificada de movimientos.
export interface CobroMensual {
  mes: string;
  monto: number;
  cantidad: number;
}

export type EmailChannelStatus = {
  /** Backend activo: "resend" | "smtp" | "test". */
  provider: string;
  /** false cuando provider === "test" (no manda, solo loggea). */
  activo: boolean;
  from_addr: string;
  admin_to: string;
};

export type EmailTemplateSummary = {
  key: string;
  subject: string;
  enabled: boolean;
  updated_at: string;
  updated_by: string | null;
};

export type EmailLogEntry = {
  id: number;
  to_addr: string;
  subject: string;
  template_key: string;
  alquiler_id: number | null;
  status: string;
  provider: string;
  provider_id: string | null;
  error: string | null;
  sent_at: string | null;
};

export type EmailTemplate = EmailTemplateSummary & {
  body_html: string;
  body_text: string;
};

export type EmailTemplateInput = {
  subject: string;
  body_html: string;
  body_text: string;
};

export type ClientePedidoRow = {
  id: number;
  numero_pedido: number | null;
  estado: PedidoEstado;
  fecha_desde: string | null;
  fecha_hasta: string | null;
  monto_total: number;
  monto_pagado: number;
  descuento_pct: number | null;
  equipos: string | null;
};

// Solo lectura (#1240): perfiles fiscales personales + productoras vinculadas
// del cliente, para la ficha admin. La gestión real vive en el self-service
// del cliente (perfiles) y en /admin/productoras (membership).
export type ClientePerfilFiscalRow = {
  id: number;
  cuit: string;
  perfil_impuestos: string;
  razon_social: string | null;
  domicilio_fiscal: string | null;
  etiqueta: string | null;
  es_default: boolean;
};

export type ClienteProductoraRow = {
  id: number;
  // Nullable (#1251 Fase 3): productora BORRADOR (creada solo con nombre, sin
  // CUIT todavía) — no facturable hasta que se le asigne uno.
  cuit: string | null;
  perfil_impuestos: string | null;
  razon_social: string | null;
  nombre: string | null;
};

export type ClientePerfilesFiscales = {
  perfiles: ClientePerfilFiscalRow[];
  productoras: ClienteProductoraRow[];
};

// Fusión de duplicados (Fase 2 identidad #1098): grupos de clientes que comparten un
// CUIL verificado, para que el admin elija cuál conservar y fusione los demás.
export type DuplicadoCliente = {
  id: number;
  nombre: string;
  apellido: string;
  email: string | null;
  telefono: string | null;
  nombre_completo_renaper: string | null;
  dni_validado_at: string | null;
  created_at: string | null;
  pedidos: number;
};
export type GrupoDuplicado = { cuil: string; clientes: DuplicadoCliente[] };

export type CalendarioPedido = {
  id: number;
  numero_pedido: number | null;
  cliente_nombre: string | null;
  estado: PedidoEstado;
  fecha_desde: string;
  fecha_hasta: string;
  monto_total: number;
  equipos: string | null;
};

/** Bloqueo del estudio que no es un pedido (slot fijo recurrente o clase de
 * taller publicada) — overlay del calendario admin, GET /admin/estudio/ocupacion. */
export type CalendarioBloqueo = {
  tipo: "slot_fijo" | "taller";
  label: string;
  fecha_desde: string;
  fecha_hasta: string;
};

/** Una fila agregada de búsquedas: un término normalizado con cuántas veces se
 *  buscó, un ejemplo del texto crudo, la última vez, y (en `top`) el máximo de
 *  resultados que llegó a dar. */
export type BusquedaRow = {
  query_norm: string;
  veces: number;
  texto: string;
  ultima: string | null;
  max_resultados?: number;
};

export type BusquedasData = {
  top: BusquedaRow[];
  zero: BusquedaRow[];
};

// Liquidación por dueño (#88): ingreso 100% pagado, atribuido al mes/día de
// saldado y repartido entre beneficiarios según el modelo de comisiones.
export type PorBeneficiario = Record<string, number>;
export type LiquidacionPunto = {
  total: number;
  por_beneficiario: PorBeneficiario;
};
export type LiquidacionMes = LiquidacionPunto & { mes: string };
export type LiquidacionDia = LiquidacionPunto & { dia: string };
export type LiquidacionDueno = {
  dueno: string;
  monto_generado: number;
  pedidos: number;
  reparto: PorBeneficiario;
  equipos: { equipo: string; monto: number; veces: number }[];
  // Detalle por PEDIDO (rentals), en vez de por equipo — # de pedido, cliente,
  // fecha de saldado, monto que ese pedido aportó a este dueño (2026-07-04).
  // Opcional: las fotos de meses cerrados ANTES de este cambio no lo tienen.
  pedidos_detalle?: {
    pedido_id: number;
    numero_pedido: number;
    cliente: string;
    fecha: string;
    monto: number;
  }[];
};
export type LiquidacionData = {
  desde: string;
  hasta: string;
  beneficiarios: string[];
  modelo: Record<string, Record<string, number>>;
  resumen: LiquidacionPunto & { pedidos: number };
  por_mes: LiquidacionMes[];
  por_dia: LiquidacionDia[];
  por_dueno: LiquidacionDueno[];
  // Cierre del mes (#721): presentes solo cuando el rango es exactamente un mes
  // calendario (la vista mensual). `cerrado` true → los números vienen de la foto
  // inmutable. `mes` es 'YYYY-MM'.
  mes?: string;
  cerrado?: boolean;
  cerrado_por?: string | null;
  cerrado_at?: string | null;
};

// Reconciliación de datos de liquidación (#88, hardening): semáforo de confianza.
export type ReconciliacionData = {
  ok: boolean;
  pagados_sin_ledger: { cantidad: number; ids: number[] };
  monto_pagado_divergente: { cantidad: number; ids: number[] };
  sobrepagados: { cantidad: number; ids: number[] };
  // Mes cerrado desactualizado (#721): pedidos saldados en un mes ya cerrado que
  // recibieron actividad después del cierre → la foto quedó vieja, hay que reabrir.
  mes_cerrado_desactualizado: { cantidad: number; ids: number[]; meses: string[] };
  duenos_no_canonicos: string[];
};

export type EstadisticasData = {
  totales: {
    total_pedidos: number;
    total_clientes: number;
    total_ars: number;
    desde: string | null;
    hasta: string | null;
  };
  por_mes: { mes: string; pedidos: number; total_ars: number }[];
  crecimiento: { mes: string; total_ars: number; crecimiento_pct: number }[];
  top_equipos: { equipo: string; total_ars: number; veces: number }[];
  top_clientes: { cliente: string; total_ars: number; pedidos: number }[];
  clientes_recurrentes: { cliente: string; veces_alquiladas: number; total_ars: number }[];
  mejor_peor_mes: {
    mejor_mes: string | null;
    mejor_total: number | null;
    peor_mes: string | null;
    peor_total: number | null;
  };
  por_dueno: { dueno: string; total_ars: number; items: number }[];
  favoritos_equipo?: { equipo: string; total_favoritos: number; clientes_unicos: number }[];
};

export type Cliente = {
  id: number;
  nombre: string;
  apellido: string;
  telefono: string | null;
  email: string | null;
  direccion: string | null;
  cuit: string | null;
  descuento: number | null;
  perfil_impuestos: string | null;
  // Verificación de identidad Didit
  dni_validado_at: string | null;
  dni_verificacion_estado?: string | null;
  dni_verificacion_motivo?: string | null;
  dni: string | null;
  cuil: string | null;
  nombre_renaper: string | null;
  apellido_renaper: string | null;
  nombre_completo_renaper: string | null;
  fecha_nacimiento_renaper: string | null;
  direccion_renaper: string | null;
  genero_renaper: string | null;
  nacionalidad_renaper: string | null;
  lugar_nacimiento_renaper: string | null;
  vencimiento_documento_renaper: string | null;
  emision_documento_renaper: string | null;
  tipo_documento_renaper: string | null;
  estado_civil_renaper: string | null;
  apodo: string | null;
  // Resueltos server-side (mismo criterio que GET /api/cliente/me): RENAPER
  // si está verificado, si no el nombre/dirección base — no recomponer en TS.
  nombre_legal: string;
  direccion_legal: string | null;
};
export type ClientesListResp = {
  total: number;
  page: number;
  per_page: number;
  items: Cliente[];
};
export type ClienteInput = {
  nombre: string;
  apellido: string;
  telefono?: string;
  email?: string;
  direccion?: string;
  cuit?: string;
  descuento?: number;
  perfil_impuestos?: string;
};

export type PedidoCreateInput = {
  cliente_id?: number | null;
  cliente_nombre?: string;
  cliente_email?: string | null;
  cliente_telefono?: string | null;
  notas?: string | null;
  fecha_desde?: string | null;
  fecha_hasta?: string | null;
  items: { equipo_id: number; cantidad: number; precio_jornada: number }[];
  estado?: "borrador" | "solicitado";
};

// ── Tipos pedidos ────────────────────────────────────────────────────────────

/** @deprecated Usar EstadoPedido importado de @/lib/pedido-estados */
export type PedidoEstado = EstadoPedido;

export type CobroModo = "jornada" | "fijo";

export type PedidoItem = {
  id: number;
  pedido_id: number;
  /** null = línea personalizada (#805): no es del catálogo, no reserva stock. */
  equipo_id: number | null;
  cantidad: number;
  precio_jornada: number;
  subtotal: number;
  nombre: string;
  marca: string | null;
  nombre_publico?: string | null;
  nombre_publico_largo?: string | null;
  foto_url?: string | null;
  /** Línea personalizada (#805): nombre libre + modo de cobro por línea. */
  nombre_libre?: string | null;
  cobro_modo?: CobroModo;
};

export type PedidoPago = {
  id: number;
  pedido_id: number;
  monto: number;
  concepto: string | null;
  fecha: string;
  created_at?: string;
  created_by?: string | null;
  anulado?: boolean;
  anulado_por?: string | null;
  anulado_at?: string | null;
  anulado_motivo?: string | null;
};

export type Pedido = {
  id: number;
  numero_pedido: number | null;
  numero_remito: string | null;
  cliente_id: number | null;
  cliente_nombre: string | null;
  cliente_email: string | null;
  cliente_telefono: string | null;
  cliente_perfil_impuestos: string | null;
  cliente_dni_validado_at?: string | null;
  /** A nombre de quién se factura este pedido (#1251) — mutuamente excluyentes,
   *  NULL/NULL = perfil default de la cuenta. El renter sigue siendo `cliente_id`. */
  perfil_fiscal_id?: number | null;
  productora_id?: number | null;
  fecha_desde: string | null;
  fecha_hasta: string | null;
  estado: PedidoEstado;
  fuente: string | null;
  monto_total: number;
  monto_pagado: number;
  /** true si el pedido tiene una factura emitida (no anulada). Lo resuelve el
   *  backend en `list_pedidos` (EXISTS sobre `facturas`); el front lo muestra. */
  facturado?: boolean;
  descuento_pct: number | null;
  descuento_jornadas_pct: number | null;
  /** Fase C-2 (#1219): tipo del override manual — "pct" (default) o "monto". */
  descuento_manual_tipo?: "pct" | "monto" | null;
  descuento_manual_monto?: number | null;
  /** % y fuente del descuento GANADOR (jerarquía manual > cliente > jornadas) —
   *  distinto de `descuento_pct` crudo (solo el override). Ver `desglose_de_pedido`. */
  descuento_efectivo_pct?: number | null;
  descuento_origen?: "manual" | "cliente" | "jornadas" | "ninguno" | null;
  notas: string | null;
  created_at?: string;
  items: PedidoItem[];
  pagos?: PedidoPago[];
  /** True si hay una `solicitudes_modificacion` con estado='pendiente' para
   * este pedido. Sólo viene en el listado, no en el detalle. */
  tiene_solicitud_pendiente?: boolean;
  /** Solo presente en el detalle (`getPedido`). Timeline de cambios del
   * cliente desde el portal. */
  historial_modificaciones?: PedidoHistorialItem[];
  // Desglose canónico del total — viene del backend
  // (services/precios.calcular_total). El frontend lo lee directo sin
  // reimplementar la fórmula (#496).
  bruto?: number;
  descuento_monto?: number;
  monto_neto?: number;
  iva_pct?: number;
  iva_monto?: number;
  total_con_iva?: number;
  con_iva?: boolean;
  cantidad_jornadas?: number;
};

export type PedidoCambiosSnapshot = {
  fecha_desde?: string | null;
  fecha_hasta?: string | null;
  items?: { equipo_id: number; cantidad: number }[];
  mensaje?: string | null;
};

export type PedidoHistorialItem = {
  id: number;
  mensaje: string | null;
  estado: "pendiente" | "aprobada" | "rechazada" | "cancelada";
  respuesta: string | null;
  cambios_json: PedidoCambiosSnapshot | null;
  /** Lo que efectivamente se aplicó al aprobar (≠ cambios_json si admin
   *  envió contrapropuesta). null si la solicitud no se aprobó. */
  cambios_aplicados: PedidoCambiosSnapshot | null;
  tipo: "directo" | "aprobacion";
  resolved_at: string | null;
  resolved_by: string | null;
  created_at: string;
};

export type PedidosListResp = {
  total: number;
  page: number;
  per_page: number;
  items: Pedido[];
};

export type PedidoDatosInput = {
  cliente_id: number | null;
  cliente_nombre: string | null;
  cliente_email: string | null;
  cliente_telefono: string | null;
  fecha_desde: string | null;
  fecha_hasta: string | null;
  notas: string | null;
  descuento_pct: number | null;
  descuento_manual_tipo?: "pct" | "monto" | null;
  descuento_manual_monto?: number | null;
  perfil_fiscal_id?: number | null;
  productora_id?: number | null;
};

// ── Estudio (singleton E1) ───────────────────────────────────────────────────

export type EstudioFoto = {
  id: number;
  url: string;
  path: string | null;
  orden: number;
  es_principal: boolean;
  created_at: string | null;
};

export type EstudioConfig = {
  id: number;
  equipo_id: number | null;
  nombre: string;
  tagline: string;
  descripcion: string;
  precio_hora: number;
  min_horas: number;
  open_hour: number;
  close_hour: number;
  buffer_horas: number;
  anticipacion_min_horas: number;
  pack_activo: boolean;
  pack_nombre: string;
  pack_descripcion: string;
  pack_precio: number;
  features: Array<{ label: string; value: string }> | null;
  faq: Array<{ q: string; a: string }> | null;
  direccion: string;
  como_llegar: string;
  testimonios: Array<{ autor: string; texto: string }> | null;
  mapa_url: string;
  mapa_embed_url: string;
  updated_at: string | null;
  fotos: EstudioFoto[];
  trabajos: EstudioTrabajo[];
};

export type EstudioTrabajoFoto = {
  url: string;
  url_sm: string | null;
  url_avif: string | null;
  url_sm_avif: string | null;
  path: string | null;
};

/** Un medio del carrusel: link externo (YouTube/Instagram) o foto subida. */
export type EstudioMedia =
  | {
      kind: "youtube" | "instagram";
      url: string;
      thumbnail: string | null;
      w: number | null;
      h: number | null;
    }
  | {
      kind: "foto";
      url: string;
      url_sm: string | null;
      url_avif: string | null;
      url_sm_avif: string | null;
      w: number | null;
      h: number | null;
    };

export type EstudioTrabajoLink = {
  tipo: "youtube" | "instagram";
  url: string;
  thumbnail_url: string | null;
};

export type EstudioTrabajo = {
  id: number;
  titulo: string;
  realizador: string;
  realizador_logo_url: string | null;
  realizador_instagram: string | null;
  realizador_web: string | null;
  categoria: string;
  categorias: string[];
  descripcion: string;
  tipo: "fotos" | "video";
  media: EstudioMedia[];
  links: EstudioTrabajoLink[];
  fotos: EstudioTrabajoFoto[];
  orden: number;
  activo: boolean;
  created_at: string | null;
  updated_at: string | null;
};

export type EstudioTrabajoInput = {
  titulo?: string;
  realizador?: string;
  realizador_instagram?: string | null;
  realizador_web?: string | null;
  /** Tags del trabajo. El backend deduplica y deriva la columna legacy. */
  categorias?: string[];
  descripcion?: string;
  /** Lista ordenada de links externos. El backend deriva el tipo y el thumbnail.
   *  `thumbnail_url` es un override manual: el backend lo descarga y reemplaza el og:image. */
  links?: Array<{ url: string; tipo?: string | null; thumbnail_url?: string | null }>;
  activo?: boolean;
};

export type TrabajoOrdenItem = { id: number; orden: number };

export type EstudioInput = {
  nombre?: string;
  tagline?: string;
  descripcion?: string;
  precio_hora?: number;
  min_horas?: number;
  open_hour?: number;
  close_hour?: number;
  buffer_horas?: number;
  anticipacion_min_horas?: number;
  pack_activo?: boolean;
  pack_nombre?: string;
  pack_descripcion?: string;
  pack_precio?: number;
  features_json?: string;
  faq_json?: string;
  direccion?: string;
  como_llegar?: string;
  testimonios_json?: string;
  mapa_url?: string;
};

export type FotoOrdenItem = { id: number; orden: number; es_principal: boolean };

export type EstudioSlotFijo = {
  id: number;
  cliente: string;
  dia_semana: number; // 0=Lun .. 6=Dom
  hora_desde: number;
  hora_hasta: number;
  valor_mensual: number;
  mes_desde: string; // YYYY-MM
  mes_hasta: string; // YYYY-MM
  activo: boolean;
};

export type EstudioSlotInput = Omit<EstudioSlotFijo, "id">;

export type EstudioPackEquipoCurado = {
  id: number;
  nombre: string;
  marca: string | null;
  foto_url: string | null;
  orden: number;
};

// ── Descuentos por jornadas ──────────────────────────────────────────────────

export type DescuentoJornada = { id: number; jornadas: number; pct: number };

// ── Talleres ──────────────────────────────────────────────────────────────────

// Horas en MINUTOS desde medianoche (510 = 8:30). Los `_str` vienen resueltos
// del backend en las lecturas; al ESCRIBIR solo viajan los `_min` + contenido.
// F2 (clase rica): `id` presente al escribir = actualizar esa clase (preserva
// su portada); ausente = clase nueva. La portada solo cambia por sus endpoints.
export type ClaseBody = {
  id?: number | null;
  fecha: string;
  hora_inicio_min: number;
  hora_fin_min: number;
  hora_inicio_str?: string;
  hora_fin_str?: string;
  titulo?: string;
  descripcion?: string;
  nota?: string;
  portada_media_id?: number | null;
  portada_url?: string;
};

// F4a: modalidad de pago de una edición. `id` presente al escribir = editar
// esa fila (preserva su posición salvo reorden); ausente = nueva. Sin motor
// de descuentos: `monto_total` lo carga el admin a mano, los "%" son texto
// libre en `nota`. `monto_total_str` viene resuelto del backend en lecturas.
export type ModalidadPagoBody = {
  id?: number | null;
  codigo: string;
  label: string;
  nota?: string;
  monto_total: number;
  monto_total_str?: string;
};

export type EdicionAdmin = {
  id: number;
  taller_id: number;
  numero_edicion: number;
  slug: string;
  tipo_taller: string;
  fecha_inicio: string;
  fecha_fin: string;
  horario: string;
  cupos_total: number;
  cupos_confirmados: number;
  cupos_disponibles: number;
  precio_total: number;
  precio_sena: number;
  pago_alias: string;
  pago_cbu: string;
  pago_banco: string;
  direccion: string;
  activo: boolean;
  frozen_at: string | null;
  clases: ClaseBody[];
  // F4a: RAW (sin fallback sintético — [] = "no configuradas todavía").
  modalidades: ModalidadPagoBody[];
  // F4c: NULL = sin cierre (siempre abierto).
  fecha_cierre_inscripcion: string | null;
};

// F4c: mini-KPIs de una edición — plata ya resuelta por el backend (el front
// solo la muestra, nunca la calcula).
export type EdicionKpis = {
  senas_verificadas: number;
  senas_pendientes: number;
  en_espera: number;
  cupo_ofrecido: number;
  plata_recibida_str: string;
  plata_esperada_str: string;
};

// F4c: FAQ del concepto — ninguna pregunta es obligatoria.
export type FaqItem = { pregunta: string; respuesta: string };

// F4c: trabajo pasado del taller (link de YouTube, sin testimonios/reseñas).
export type Trabajo = {
  id: number;
  titulo: string;
  youtube_url: string;
  poster_url: string;
  poster_media_id: number | null;
};

export type TallerConcepto = {
  id: number;
  slug_base: string;
  nombre: string;
  subtitulo: string;
  descripcion: string;
  publico_objetivo: string;
  notif_email: string;
  // F2: T&C propios ('' → /terminos general), beneficios, pregunta del form
  // configurable y mensaje post-inscripción.
  terminos: string;
  beneficios: string;
  pregunta_experiencia: string;
  mensaje_confirmacion: string;
  // F4a: video hero (YouTube). '' → sin video.
  video_url: string;
  video_poster_url: string;
  // F3: instructores como entidad (además de instructor_* legacy arriba).
  instructores: Instructor[];
  ediciones: EdicionAdmin[];
  // F4c: FAQ del concepto + trabajos pasados (solo YouTube).
  faqs: FaqItem[];
  trabajos: Trabajo[];
};

// F3: instructor como entidad propia (N↔N con talleres — fuente única desde
// F6, reemplazó a los campos instructor_* legacy del concepto).
export type Instructor = {
  id: number;
  nombre: string;
  rol: string;
  descripcion: string;
  instagram: string;
  web: string;
  foto_url: string;
  foto_media_id: number | null;
  // F6: "Trabajó con" — reemplaza el legacy `instructor_proyectos` (1 por taller).
  proyectos: string;
};

export type Inscripcion = {
  id: number;
  nombre: string;
  email: string;
  telefono: string;
  experiencia: string | null;
  comprobante_url: string | null;
  en_lista_espera: boolean;
  estado: string | null;
  edicion_id: number | null;
  numero_edicion: number | null;
  edicion_slug: string | null;
  created_at: string | null;
  tyc_aceptado_at: string | null;
  // F4a: snapshot de la modalidad de pago elegida (null = inscripción previa a F4a).
  modalidad_codigo: string | null;
  modalidad_label: string | null;
  modalidad_monto: number | null;
};

// F4b: interesado (lead sin cupo en su momento). notificado_at = ya se le avisó
// de una nueva edición (el admin puede re-avisar, no queda bloqueado).
export type Interesado = {
  id: number;
  nombre: string;
  email: string;
  telefono: string;
  created_at: string | null;
  notificado_at: string | null;
};

// ── Solicitudes ───────────────────────────────────────────────────────────────
export type ModificacionItem = { equipo_id: number; cantidad: number };
export type CambiosJson = {
  fecha_desde?: string | null;
  fecha_hasta?: string | null;
  items: ModificacionItem[];
  mensaje?: string | null;
};
export type Solicitud = {
  id: number;
  pedido_id: number;
  cliente_nombre: string;
  cliente_apellido?: string | null;
  cliente_email: string | null;
  numero_pedido: number | null;
  mensaje: string | null;
  estado: "pendiente" | "aprobada" | "rechazada" | "cancelada";
  respuesta: string | null;
  cambios_json: CambiosJson | null;
  tipo: "directo" | "aprobacion";
  resolved_at: string | null;
  resolved_by: string | null;
  created_at: string;
  pedido_fecha_desde: string | null;
  pedido_fecha_hasta: string | null;
  monto_total: number;
};
export type PedidoLite = {
  id: number;
  numero_pedido: number | null;
  fecha_desde: string | null;
  fecha_hasta: string | null;
  items: { equipo_id: number; cantidad: number; nombre: string; nombre_publico?: string | null }[];
};
