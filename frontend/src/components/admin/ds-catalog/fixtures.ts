/**
 * fixtures — dataset demo CANÓNICO de la vitrina del DS.
 *
 * Una sola fuente de "datos de ejemplo" para todos los specimens: en vez de que
 * cada sección invente su propio mock, todas importan de acá. Así la vitrina
 * muestra **los mismos escenarios** en todas partes (un equipo simple, un kit,
 * un combo; un cliente verificado y uno sin verificar; un pedido sin iniciar,
 * presupuestado, confirmado y pagado; una lista guardada) y se ve de un vistazo
 * cómo se comporta cada organismo ante cada estado.
 *
 * Tipado contra los tipos REALES del dominio (no formas inventadas) → si un tipo
 * cambia, el typecheck rompe acá y se actualiza en un solo lugar.
 *
 * NO es para producción: son datos ficticios con ids fuera del rango real. La
 * idea es que mañana un `seed_demo.py` siembre estos mismos escenarios en un
 * Postgres local — mismas variantes, dos representaciones (TS para la vitrina,
 * SQL para el server local).
 */
import { type Equipment, type IncludedItem } from "@/data/equipment";
import {
  type Pedido,
  type Item,
  type Pago,
  type Perfil,
} from "@/components/cliente/ClientePortalTypes";
import { type ListaPersonal } from "@/lib/cliente/api";
// El back-office tiene su PROPIA forma del pedido (numero_pedido numérico, items
// con id/pedido_id, plata desglosada) — distinta de la del portal del cliente.
// Mismo nombre de tipo → se aliasa para que convivan en el mismo módulo.
import { type Pedido as AdminPedido, type PedidoItem as AdminPedidoItem } from "@/lib/admin/api";

/** Callback vacío para specimens que no necesitan reaccionar. */
export const noop = () => {};

/** Callback async vacío — para props que esperan `() => Promise<unknown>`. */
export const noopAsync = async () => {};

// ────────────────────────────────────────────────────────────────────────────
// EQUIPOS — las tres formas del producto (A1 #635: simple · kit · combo)
// ────────────────────────────────────────────────────────────────────────────

/** Lo que trae el kit FX6 — reusado por IncludesLine / AddonPills / el card. */
export const includesDemo: IncludedItem[] = [
  { name: "Cuerpo FX6" },
  { name: "Batería BP-U60", qty: 2 },
  { name: "Cargador" },
  { name: "Asa XLR" },
  { name: "Correa" },
];

/**
 * Equipo SIMPLE — un solo ítem, sin composición. Sin foto a propósito, para
 * que el card muestre el EmptyImage (placeholder de categoría).
 */
export const equipoSimple: Equipment = {
  id: "9001",
  slug: "demo-sigma-24-70",
  name: "Sigma 24-70 f/2.8 DG DN",
  brand: "Sigma",
  category: "Lentes",
  pricePerDay: 18500,
  description: "Zoom estándar profesional para montura E. Equipo de muestra (simple).",
  tipo: "simple",
  cantidad: 3,
  fotoUrl: null,
  specs: [
    { label: "Distancia focal", value: "24-70mm" },
    { label: "Apertura", value: "f/2.8" },
    { label: "Montura", value: "Sony E" },
  ],
  specsDestacados: [
    { label: "Apertura", value: "f/2.8" },
    { label: "Focal", value: "24-70mm" },
  ],
  _backendId: 9001,
};

/**
 * Equipo KIT — un cuerpo armado con sus accesorios (`includes`). Destacado
 * (badge "destacado") y con dos specs marcadas para que SpecsGrid las cure.
 */
export const equipoKit: Equipment = {
  id: "9002",
  slug: "demo-sony-fx6",
  name: "FX6 Cinema Line",
  brand: "Sony",
  category: "Cámaras",
  pricePerDay: 38000,
  description: "Cámara cine full-frame, armada como kit listo para rodar. Equipo de muestra (kit).",
  tipo: "kit",
  cantidad: 2,
  destacado: true,
  relevanciaManual: 20,
  includes: includesDemo,
  specs: [
    { label: "Sensor", value: "Full-frame 10.2MP" },
    { label: "Montura", value: "E-mount" },
    { label: "ISO", value: "409600" },
    { label: "Formato", value: "4K 120p" },
  ],
  specsRaw: {
    sensor: {
      label: "Sensor",
      value: "Full-frame 10.2MP",
      tipo: "texto",
      unidad: null,
      prioridad: 1,
      en_card: true,
      en_filtros: false,
      destacado: true,
    },
    formato: {
      label: "Formato",
      value: "4K 120p",
      tipo: "texto",
      unidad: null,
      prioridad: 2,
      en_card: true,
      en_filtros: false,
      destacado: true,
    },
  },
  _backendId: 9002,
};

/**
 * Equipo COMBO — paquete de varios equipos con ítems `esencial` (true) y
 * best-effort (false). Sin stock múltiple (cantidad 1).
 */
export const equipoCombo: Equipment = {
  id: "9003",
  slug: "demo-combo-entrevista",
  name: "Combo Entrevista · 2 Cámaras",
  brand: "Rambla",
  category: "Cámaras",
  pricePerDay: 92000,
  description: "Combo listo para entrevista: 2 cuerpos + luces + audio. Equipo de muestra (combo).",
  tipo: "combo",
  cantidad: 1,
  destacado: true,
  includes: [
    { name: "Sony FX3 Cuerpo", qty: 2, esencial: true },
    { name: "Aputure 300X Bi-color", qty: 2, esencial: true },
    { name: "Rode Wireless GO II", esencial: true },
    { name: "Trípode Manfrotto 504X", qty: 2, esencial: false },
    { name: "CFexpress 512GB", qty: 2, esencial: false },
  ],
  specs: [
    { label: "Incluye", value: "2 cuerpos + luces + audio" },
    { label: "Ideal para", value: "Entrevistas / contenido" },
  ],
  _backendId: 9003,
};

/** Las tres variantes juntas — para grids que muestran "las tres formas". */
export const equiposDemo: Equipment[] = [equipoSimple, equipoKit, equipoCombo];

// ────────────────────────────────────────────────────────────────────────────
// PEDIDOS — el mismo pedido en tres momentos de plata (sin iniciar · debe · pago)
// Los ítems espejan los equipos demo (mismos nombres/precios) → coherencia visual.
// ────────────────────────────────────────────────────────────────────────────

/** Las dos líneas del pedido demo (3 jornadas). Reusan los equipos demo. */
export const itemsPedidoDemo: Item[] = [
  {
    equipo_id: 9002,
    nombre: "FX6 Cinema Line",
    marca: "Sony",
    cantidad: 1,
    precio_jornada: 38000,
    subtotal: 114000,
  },
  {
    equipo_id: 9003,
    nombre: "Combo Entrevista · 2 Cámaras",
    marca: "Rambla",
    cantidad: 1,
    precio_jornada: 92000,
    subtotal: 276000,
  },
];

const FECHAS_PEDIDO = {
  fecha_desde: "2026-07-10T10:00:00",
  fecha_hasta: "2026-07-12T18:00:00",
  cantidad_jornadas: 3,
  monto_total: 390000,
} as const;

const SIN_DOCS = {
  remito: false,
  contrato: false,
  albaran: false,
  factura: false,
  "packing-list": false,
};
const DOCS_PARCIAL = {
  remito: true,
  contrato: true,
  albaran: false,
  factura: false,
  "packing-list": true,
};
const DOCS_COMPLETOS = {
  remito: true,
  contrato: true,
  albaran: true,
  factura: true,
  "packing-list": true,
};

/** Pedido SIN INICIAR — recién solicitado: presupuesto, nada pagado, sin docs. */
export const pedidoPresupuesto: Pedido = {
  id: 9101,
  numero_pedido: "R-1042",
  estado: "solicitado",
  ...FECHAS_PEDIDO,
  monto_pagado: 0,
  items: itemsPedidoDemo,
  pagos: [],
  documentos_disponibles: SIN_DOCS,
};

/** Pedido CON SEÑA (debe) — confirmado, pagó parte, remito + contrato listos. */
export const pedidoDebe: Pedido = {
  id: 9102,
  numero_pedido: "R-1039",
  estado: "confirmado",
  ...FECHAS_PEDIDO,
  monto_pagado: 150000,
  items: itemsPedidoDemo,
  pagos: [{ id: 1, monto: 150000, concepto: "Seña", fecha: "2026-07-01T12:00:00" }],
  documentos_disponibles: DOCS_PARCIAL,
};

/** Pedido PAGO — finalizado, saldado, todos los documentos disponibles. */
export const pedidoPagado: Pedido = {
  id: 9103,
  numero_pedido: "R-1031",
  estado: "finalizado",
  ...FECHAS_PEDIDO,
  monto_pagado: 390000,
  items: itemsPedidoDemo,
  pagos: [
    { id: 1, monto: 150000, concepto: "Seña", fecha: "2026-06-20T12:00:00" },
    { id: 2, monto: 240000, concepto: "Saldo", fecha: "2026-07-10T09:30:00" },
  ] as Pago[],
  documentos_disponibles: DOCS_COMPLETOS,
};

/** Los tres momentos juntos — del más nuevo (sin iniciar) al cerrado (pago). */
export const pedidosDemo: Pedido[] = [pedidoPresupuesto, pedidoDebe, pedidoPagado];

// ────────────────────────────────────────────────────────────────────────────
// PERFILES — el cliente en tres estados de identidad (verificado · sin · rechazado)
// ────────────────────────────────────────────────────────────────────────────

/** Cliente VERIFICADO — DNI validado contra RENAPER. */
export const perfilVerificado: Perfil = {
  id: 9201,
  nombre: "Camila",
  apellido: "Rossi",
  email: "camila.rossi@demo.test",
  telefono: "11 5555-1042",
  direccion: "Av. Córdoba 1234, CABA",
  cuit: "27-35123456-4",
  perfil_impuestos: "responsable_inscripto",
  razon_social: "Camila Rossi Producciones",
  dni: "35.123.456",
  cuil: "27-35123456-4",
  dni_validado_at: "2026-06-15T14:22:00",
  dni_verificacion_estado: "aprobado",
  nombre_renaper: "CAMILA",
  apellido_renaper: "ROSSI",
};

/** Cliente SIN VERIFICAR — cuenta liviana, identidad pendiente de Didit. */
export const perfilSinVerificar: Perfil = {
  id: 9202,
  nombre: "Estudio",
  apellido: "Demo",
  email: "hola@estudiodemo.test",
  telefono: "11 5555-2010",
  direccion: "Thames 800, CABA",
  dni_validado_at: null,
  dni_verificacion_estado: "no_verificado",
};

/** Cliente RECHAZADO — la verificación no pasó (muestra el motivo). */
export const perfilRechazado: Perfil = {
  id: 9203,
  nombre: "Juan",
  apellido: "Pérez",
  email: "juan.perez@demo.test",
  telefono: "11 5555-3007",
  direccion: "Belgrano 450, CABA",
  dni_validado_at: null,
  dni_verificacion_estado: "rechazado",
  dni_verificacion_motivo: "Los datos del documento no coinciden con RENAPER.",
};

// ────────────────────────────────────────────────────────────────────────────
// LISTAS — composiciones guardadas. Apuntan a los equipos demo (resuelven contra
// equiposDemo, no contra el catálogo real) → la lista muestra los mismos productos.
// ────────────────────────────────────────────────────────────────────────────

export const listasDemo: ListaPersonal[] = [
  {
    id: 1,
    nombre: "Kit entrevista habitual",
    items: [
      { equipo_id: 9002, cantidad: 1 },
      { equipo_id: 9003, cantidad: 1 },
    ],
    created_at: "2026-05-02T10:00:00",
  },
  {
    id: 2,
    nombre: "Set de lentes",
    items: [{ equipo_id: 9001, cantidad: 2 }],
    created_at: "2026-06-18T16:30:00",
  },
];

// ────────────────────────────────────────────────────────────────────────────
// PEDIDOS (ADMIN) — el mismo pedido visto desde el back-office. Otra forma del
// tipo (numero_pedido numérico, items con id/pedido_id, plata sin desglosar acá).
// El listado del admin muestra varios estados de un vistazo → cuatro pedidos en
// cuatro estados (presupuesto · solicitado · confirmado con saldo · finalizado),
// reusando las mismas personas que los perfiles demo.
// ────────────────────────────────────────────────────────────────────────────

/** Las dos líneas estándar del pedido demo (FX6 + Combo) en forma admin. */
const itemsAdminPedido = (pedidoId: number): AdminPedidoItem[] => [
  {
    id: pedidoId * 10 + 1,
    pedido_id: pedidoId,
    equipo_id: 9002,
    cantidad: 1,
    precio_jornada: 38000,
    subtotal: 114000,
    nombre: "FX6 Cinema Line",
    marca: "Sony",
  },
  {
    id: pedidoId * 10 + 2,
    pedido_id: pedidoId,
    equipo_id: 9003,
    cantidad: 1,
    precio_jornada: 92000,
    subtotal: 276000,
    nombre: "Combo Entrevista · 2 Cámaras",
    marca: "Rambla",
  },
];

/** Campos de contacto/fechas comunes a los pedidos admin demo. */
const ADMIN_PEDIDO_BASE = {
  // Los 4 fixtures de abajo tienen ítems reales — mismo campo que calcula el
  // backend (`_pedido_tiene_contenido`), acá fijo en `true` porque ninguna
  // demo modela el caso "solo turno del Estudio, sin equipos".
  tiene_contenido: true,
  numero_remito: null,
  cliente_perfil_impuestos: null,
  fecha_desde: "2026-07-10T10:00:00",
  fecha_hasta: "2026-07-12T18:00:00",
  fuente: "portal",
  descuento_pct: null,
  descuento_jornadas_pct: null,
  notas: null,
} as const;

/** PRESUPUESTO — cotización abierta, todavía sin confirmar. */
export const adminPedidoPresupuesto: AdminPedido = {
  ...ADMIN_PEDIDO_BASE,
  id: 9104,
  numero_pedido: 1044,
  cliente_id: 9204,
  cliente_nombre: "Productora Norte",
  cliente_email: "hola@productoranorte.test",
  cliente_telefono: "11 5555-4044",
  estado: "solicitado",
  monto_total: 222000,
  monto_pagado: 0,
  items: [
    {
      id: 91041,
      pedido_id: 9104,
      equipo_id: 9001,
      cantidad: 4,
      precio_jornada: 18500,
      subtotal: 222000,
      nombre: "Sigma 24-70 f/2.8 DG DN",
      marca: "Sigma",
    },
  ],
  pagos: [],
};

/** SOLICITADO — entró desde el portal, sin pagar todavía. */
export const adminPedidoSolicitado: AdminPedido = {
  ...ADMIN_PEDIDO_BASE,
  id: 9101,
  numero_pedido: 1042,
  cliente_id: 9201,
  cliente_nombre: "Camila Rossi",
  cliente_email: "camila.rossi@demo.test",
  cliente_telefono: "11 5555-1042",
  cliente_perfil_impuestos: "responsable_inscripto",
  estado: "solicitado",
  monto_total: 390000,
  monto_pagado: 0,
  items: itemsAdminPedido(9101),
  pagos: [],
  tiene_solicitud_pendiente: true,
};

/** CONFIRMADO con saldo — pagó la seña, debe el resto. */
export const adminPedidoConfirmado: AdminPedido = {
  ...ADMIN_PEDIDO_BASE,
  id: 9102,
  numero_pedido: 1039,
  numero_remito: "0001-00001039",
  cliente_id: 9202,
  cliente_nombre: "Estudio Demo",
  cliente_email: "hola@estudiodemo.test",
  cliente_telefono: "11 5555-2010",
  estado: "confirmado",
  monto_total: 390000,
  monto_pagado: 150000,
  items: itemsAdminPedido(9102),
  pagos: [
    {
      id: 1,
      pedido_id: 9102,
      monto: 150000,
      concepto: "Seña",
      fecha: "2026-07-01T12:00:00",
    },
  ],
};

/** FINALIZADO — cerrado y saldado, todos los documentos emitidos. */
export const adminPedidoFinalizado: AdminPedido = {
  ...ADMIN_PEDIDO_BASE,
  id: 9103,
  numero_pedido: 1031,
  numero_remito: "0001-00001031",
  cliente_id: 9203,
  cliente_nombre: "Juan Pérez",
  cliente_email: "juan.perez@demo.test",
  cliente_telefono: "11 5555-3007",
  estado: "finalizado",
  monto_total: 390000,
  monto_pagado: 390000,
  items: itemsAdminPedido(9103),
  pagos: [
    {
      id: 1,
      pedido_id: 9103,
      monto: 150000,
      concepto: "Seña",
      fecha: "2026-06-20T12:00:00",
    },
    {
      id: 2,
      pedido_id: 9103,
      monto: 240000,
      concepto: "Saldo",
      fecha: "2026-07-10T09:30:00",
    },
  ],
};

/** Los cuatro pedidos admin juntos — para el listado / tabla del back-office. */
export const pedidosAdminDemo: AdminPedido[] = [
  adminPedidoPresupuesto,
  adminPedidoSolicitado,
  adminPedidoConfirmado,
  adminPedidoFinalizado,
];
