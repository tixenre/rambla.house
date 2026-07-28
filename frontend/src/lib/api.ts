/**
 * API client para el backend rambla-rental (Python/FastAPI).
 *
 * VITE_API_URL:
 *   - Desarrollo: "http://localhost:5000"
 *   - Producción:  "" (el backend Python sirve el frontend en el mismo origen)
 */

import { authedPostJson } from "@/lib/authedFetch";
import { trackReservarEstudio } from "@/lib/analytics";

const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(API_BASE + path, window.location.href);
  if (params) {
    Object.entries(params).forEach(([k, v]) => v && url.searchParams.set(k, v));
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(API_BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail ?? `POST ${path} → ${res.status}`);
  }
  return res.json();
}

/* ─── Tipos del backend ─────────────────────────────────────────────── */

export type BackendFicha = {
  descripcion: string | null;
  notas: string | null;
  keywords_json: string | null;
  nombre_publico_template?: string | null;
  // Listas estructuradas que aún no son specs. `incluye_json` (legacy) dropeado:
  // el "qué incluye" sale de la receta real (kit), no del descriptivo.
  conectividad_json?: string | null;
  compatible_con_json?: string | null;
  // Multimedia y referencias (no son specs estructuradas)
  video_url?: string | null;
  precio_bh_usd?: number | null;
  fuente_url?: string | null;
  fuente_titulo?: string | null;
  enriquecido_at?: string | null;
  enriquecido_fuente?: string | null;
  // Columnas legacy montura/formato/resolucion/peso/dimensiones/alimentacion
  // se droppearon en Fase F — las specs viven en equipo_specs.
  // specs_json y raw_json se droppearon en Fase E.
  // B1 #635: contenido incluido (dim. 3) — [{nombre, cantidad, foto_url?}]
  contenido_incluido_json?: string | null;
};

export type BackendCategoriaRef = {
  id: number;
  nombre: string;
  parent_id: number | null;
};

export type BackendMarca = {
  id: number;
  nombre: string;
  logo_url?: string | null;
  /** Variante display-sm (800px max) para srcset. Solo en logos raster del motor. */
  logo_url_sm?: string | null;
  /** Curación manual del admin para BrandCarousel del home. #288 */
  destacada?: boolean;
  /** Orden manual del admin (drag-drop en /admin/equipos/marcas). */
  orden?: number;
  /** Score automático calculado por el ranking service (#131). */
  popularidad_score?: number;
};

export type BackendEquipo = {
  id: number;
  nombre: string;
  marca?: string;
  brand?: BackendMarca | null;
  modelo: string | null;
  cantidad: number;
  precio_jornada: number | null;
  precio_usd: number | null;
  foto_url: string | null;
  foto_url_sm?: string | null; // variante 600px de la principal para srcset (puede faltar)
  foto_url_thumb?: string | null; // variante 160px para thumbnails de ~48px (puede faltar)
  foto_url_avif?: string | null; // variante AVIF 1200px (puede faltar si sin backfill)
  foto_url_sm_avif?: string | null; // variante AVIF 600px (puede faltar)
  foto_url_thumb_avif?: string | null; // variante AVIF 160px (puede faltar)
  foto_lqip?: string | null; // data-URI 4×4 blur placeholder (puede faltar)
  estado: string;
  visible_catalogo: number;
  relevancia_manual?: number;
  kit: Array<{
    componente_id: number;
    nombre: string;
    cantidad: number;
    foto_url?: string | null;
    esencial?: boolean | null;
    descuento_pct?: number | null;
  }>;
  categorias?: BackendCategoriaRef[];
  /** Galería multi-foto (#125): fotos de equipo_fotos, principal primero.
   *  Solo presente en el detalle (`GET /equipos/{id}`), no en el listado. */
  fotos?: Array<{ url: string; es_principal?: boolean }>;
  ficha?: BackendFicha;
  specs_destacados?: { label: string; value: string }[];
  /** Specs estructuradas (Fase D): dict keyed por spec_key, fuente única
   *  post-migración. Reemplaza specs_json + columnas legacy de ficha. */
  specs?: Record<
    string,
    {
      label: string;
      value: string;
      /** Valor renderizado para display (mismo renderer que el nombre público).
       *  `value` queda crudo para filtros. */
      value_display?: string;
      tipo: string;
      unidad: string | null;
      prioridad: number;
      en_card: boolean;
      en_filtros: boolean;
      destacado: boolean;
    }
  >;
  /** Unidades disponibles para el rango desde/hasta. Solo presente si se pasan fechas. */
  disponible?: number;
  /** A1 #635: tipo de producto. */
  tipo?: "simple" | "kit" | "combo";
  /** Descuento GANADOR (cliente vs. jornadas, no acumulable) ya resuelto por el
   *  backend — solo presente si se piden fechas (`desde`/`hasta`). 0 para combos
   *  (Fase C-3, #1219: no acumulan el descuento global). El front NO recalcula
   *  esto, solo lo multiplica por jornadas/cantidad (MEMORIA 2026-07-05). */
  descuento_pct?: number;
  descuento_origen?: "cliente" | "jornadas" | null;
  /** Precio por jornada YA con `descuento_pct` aplicado. Igual a `precio_jornada`
   *  cuando no hay descuento o el equipo es un combo. */
  precio_jornada_final?: number;
  /** Nombre público calculado por el backend a partir del template de la categoría.
   *  Presente en la respuesta del catálogo cuando hay template configurado. */
  nombre_publico?: string | null;
};

export type BackendCategoria = {
  id?: number;
  nombre: string;
  total: number;
  prioridad?: number;
  /** Score automático calculado por el ranking service (#131). */
  popularidad_score?: number;
  parent_id?: number | null;
  children?: BackendCategoria[];
  // Compat con respuesta legacy ?flat=1
  subtags?: { nombre: string; total: number }[];
};

/* ─── Endpoints ─────────────────────────────────────────────────────── */

export function apiGetEquipos(opts?: { desde?: string; hasta?: string }) {
  return get<{ total: number; items: BackendEquipo[] }>("/api/equipos", {
    per_page: "500",
    solo_visibles: "true",
    sort: "ranking",
    ...(opts?.desde && opts?.hasta ? { desde: opts.desde, hasta: opts.hasta } : {}),
  });
}

export function apiGetCategorias() {
  return get<BackendCategoria[]>("/api/categorias");
}

/** Días (YYYY-MM-DD) sin disponibilidad para los equipos del carrito, en el
 *  rango pedido. `items` = "equipo_id:cantidad" separado por coma. */
export function apiGetDiasBloqueados(items: string, desde: string, hasta: string) {
  return get<{ dias_bloqueados: string[] }>("/api/disponibilidad-dias", {
    items,
    desde,
    hasta,
  });
}

export function apiGetMarcs() {
  return get<{ items: BackendMarca[] }>("/api/marcas");
}

/** Avisos del date picker (antelación mínima, horarios reducidos de fin de
 * semana) contextuales a la fecha elegida — la regla y el texto los decide
 * el backend (`services.fechas.disclaimers_retiro`, #1237); acá solo se pide
 * y se muestra `mensaje`, sin reimplementar la lógica en TS. */
export function apiGetDisclaimersRetiro(fechaDesde?: string, fechaHasta?: string) {
  return get<{ disclaimers: { check: string; mensaje: string }[] }>(
    "/api/public/rental/disclaimers",
    { fecha_desde: fechaDesde ?? "", fecha_hasta: fechaHasta ?? "" },
  );
}

/* ─── Estudio ────────────────────────────────────────────────────────── */

export type EstudioFoto = {
  id: number;
  url: string;
  url_sm?: string | null; // variante 800px (keep-aspect) para srcset; null = sin backfill aún
  url_avif?: string | null; // variante AVIF full-size; null = foto anterior al backfill
  url_sm_avif?: string | null; // variante AVIF 800px; null = foto anterior al backfill
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
  // pack_nombre/pack_precio: defaults de una-vez leídos por
  // crear_promo_desde_pack, sin UI de edición (Fase 8, #1283). pack_descripcion
  // SIGUE viva: es la descripción EN VIVO de la promo actual (`_promo_info`).
  pack_nombre: string;
  pack_descripcion: string;
  pack_precio: number;
  features: Array<{ label: string; value: string }> | null;
  faq: Array<{ q: string; a: string }> | null;
  direccion: string;
  como_llegar: string;
  testimonios: Array<{ autor: string; texto: string }> | null;
  // Lo que pegó el dueño en el admin (shortlink, URL larga o iframe HTML).
  // Usado para el botón "Ver en Google Maps".
  mapa_url: string;
  // URL embebible derivada por el backend — la usamos como src del <iframe>.
  mapa_embed_url: string;
  updated_at: string | null;
  fotos: EstudioFoto[];
  promo_combo_id?: number | null;
  promo?: EstudioPromo | null;
  /** Add-on independiente "recién pintado" — cargo fijo opcional, se suma a
   *  cualquier elección de con_promo (no la reemplaza). 0 = sin cargar todavía. */
  precio_pintura_reciente: number;
  trabajos?: EstudioTrabajo[];
};

/** La promo de equipos (combo real que reemplaza al pack, #1283 Fase 5).
 *  `disponible` solo viene presente cuando se consultó con una franja
 *  (fecha/start/horas) — en `GET /api/estudio` sin fechas no viene. */
export type EstudioPromo = {
  equipo_id: number;
  nombre: string;
  descripcion: string;
  foto_url: string | null;
  precio: number;
  disponible?: boolean;
  /** Listado público "qué incluye" — misma fuente que el catálogo
   *  (services.contenido), nunca se puede desincronizar de lo que la promo
   *  realmente reserva. */
  componentes: Array<{ nombre: string; cantidad: number; foto_url: string | null }>;
};

/** Un medio del carrusel de un trabajo: link externo (YouTube/Instagram) o foto
 *  subida. El backend une links_json + fotos_json en esta lista ordenada. */
export type EstudioMedia =
  | {
      kind: "youtube" | "instagram";
      url: string;
      thumbnail: string | null;
      /** Dimensiones del thumbnail (para mostrar la card en su proporción real). */
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
  /** Primer tag (legacy/compat). Para filtrar/mostrar usar `categorias`. */
  categoria: string;
  categorias: string[];
  descripcion: string;
  tipo: "fotos" | "video";
  /** Fuente única para mostrar: lista ordenada de medios (links + fotos). */
  media: EstudioMedia[];
  /** Links crudos (para el admin). */
  links: EstudioTrabajoLink[];
  fotos: Array<{
    url: string;
    url_sm: string | null;
    url_avif: string | null;
    url_sm_avif: string | null;
    path: string | null;
  }>;
  orden: number;
  activo: boolean;
};

export function apiGetEstudio() {
  return get<EstudioConfig>("/api/estudio");
}

/** Config pública de analítica. El backend devuelve el Measurement ID de GA4
 *  solo en producción (null en staging/local) para no contaminar las métricas
 *  de prod con tráfico de prueba. */
export function apiGetAnalyticsConfig() {
  return get<{ ga4_id: string | null }>("/api/analytics-config");
}

/** Registra una búsqueda del catálogo público (analítica interna). Best-effort:
 *  el wrapper con debounce vive en `src/lib/search-log.ts`. Devuelve el `id` del
 *  registro para poder ligar el click-through posterior. */
export function apiLogSearch(query: string, resultCount: number) {
  return post<{ ok: boolean; logged: boolean; id: number | null }>("/api/search-log", {
    query,
    result_count: resultCount,
  });
}

/** Registra que, tras la búsqueda `queryId`, el usuario abrió `equipoId`
 *  (click-through). Best-effort: la analítica nunca rompe la navegación. */
export function apiLogSearchClick(queryId: number, equipoId: number | null) {
  return post<{ ok: boolean; logged: boolean }>("/api/search-click", {
    query_id: queryId,
    equipo_id: equipoId,
  });
}

/** ¿El estudio está libre en [fecha start, +horas]? El backend aplica el buffer
 *  propio del estudio. `promo` = disponibilidad del combo real de equipos. */
export function apiGetEstudioDisponibilidad(fecha: string, start: string, horas: number) {
  return get<{
    libre: boolean;
    motivo?: string | null;
    promo?: EstudioPromo | null;
  }>("/api/estudio/disponibilidad", { fecha, start, horas: String(horas) });
}

/** Bloques ocupados del estudio en [desde, hasta] (YYYY-MM-DD, inclusive) —
 *  vista pública y anónima (sin cliente/nombre/número de pedido) para la
 *  grilla semanal del selector de fechas. Es un atajo visual: la franja
 *  elegida igual se re-valida con `apiGetEstudioDisponibilidad` antes de
 *  confirmar la reserva. */
export function apiGetEstudioOcupacionPublica(desde: string, hasta: string) {
  return get<{
    bloques: { fecha_desde: string; fecha_hasta: string }[];
  }>("/api/estudio/ocupacion-publica", { desde, hasta });
}

export type EstudioReservaBody = {
  fecha: string;
  start: string;
  horas: number;
  con_promo?: boolean;
  /** Add-on independiente "recién pintado" — se suma sea cual sea con_promo. */
  pintura_reciente?: boolean;
  // Datos del cliente: NO van en el body, salen de la sesión (login obligatorio).
};

/** Crea una reserva real del estudio (entra como solicitud, estado='solicitado').
 *  Requiere cliente logueado: usa authedPostJson (manda la cookie de sesión). */
export async function apiCrearReservaEstudio(body: EstudioReservaBody) {
  const res = await authedPostJson<{
    id: number;
    numero_pedido: number | null;
    /** Si la promo se reservó con algún componente sin stock (best-effort,
     *  nunca bloquea) — ver `routes/estudio.py::_crear_pedido_estudio`. */
    promo_advertencia?: string | null;
  }>("/api/estudio/reservas", body);
  // Analytics: estudio reservado (no-op si GA no está activo).
  trackReservarEstudio({
    horas: body.horas,
    conPromo: body.con_promo ?? false,
  });
  return res;
}

// NOTA: la creación de pedidos se movió a `src/lib/orders.ts → createOrder()`
// usando el endpoint autenticado /api/cliente/pedidos del backend FastAPI.

// ── Talleres ─────────────────────────────────────────────────────────────────

/** Datos mínimos de una edición hermana (para mostrar en la página de otra edición). */
export type EdicionLite = {
  slug: string;
  numero_edicion: number;
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
};

// Horas en MINUTOS desde medianoche (510 = 8:30, Escuela v2 F1); los `_str`
// ("08:30") vienen resueltos del backend — el front no formatea horarios a mano.
export type Sesion = {
  fecha: string;
  hora_inicio_min: number;
  hora_fin_min: number;
  hora_inicio_str: string;
  hora_fin_str: string;
  // F2: clases ricas — talleres sin estos datos cargados los reciben en "".
  titulo: string;
  descripcion: string;
  nota: string;
  portada_url: string;
};

export type Taller = {
  id: number;
  slug: string;
  nombre: string;
  subtitulo: string;
  descripcion: string;
  publico_objetivo: string;
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
  numero_edicion: number;
  proxima_edicion?: EdicionLite | null;
  edicion_anterior?: EdicionLite | null;
  activo: boolean;
  tipo_taller: string;
  notif_email: string;
  frozen_at: string | null;
  // F2: textos configurables del taller + flag de preview admin.
  terminos: string;
  beneficios: string;
  pregunta_experiencia: string;
  mensaje_confirmacion: string;
  /** True solo cuando una sesión admin previsualiza una edición despublicada. */
  borrador: boolean;
  // F3: instructores como entidad.
  instructores: {
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
  }[];
  // Instituciones co-presentadoras (ej. "Rambla" + "Filmar").
  instituciones: {
    id: number;
    nombre: string;
    descripcion: string;
    instagram: string;
    web: string;
    logo_url: string;
    logo_media_id: number | null;
  }[];
  sesiones: Sesion[];
  // F4a: video hero (YouTube) — null si no hay video configurado o la URL no
  // se pudo interpretar. El embed es siempre youtube-nocookie.com.
  video: { youtube_id: string; embed_url: string; poster: string | null } | null;
  // F4a: modalidades de pago. NUNCA vacío para el público — sin configurar
  // ninguna, el backend sintetiza 1 sola opción ("Pago total" = precio_total).
  modalidades: {
    codigo: string;
    label: string;
    nota: string;
    monto_total: number;
    monto_total_str: string;
  }[];
  // F4c: FAQ del concepto, trabajos pasados (solo YouTube, sin testimonios) y
  // cierre de inscripciones de ESTA edición (null = sin cierre).
  faqs: { pregunta: string; respuesta: string }[];
  trabajos: { id: number; titulo: string; youtube_url: string; poster_url: string }[];
  fecha_cierre_inscripcion: string | null;
};

export type InscripcionBody = {
  nombre: string;
  email: string;
  telefono: string;
  experiencia?: string;
  comprobante_url?: string;
  comprobante_key?: string;
  /** F4a: código de la modalidad elegida (de `Taller.modalidades`). Cableado-
   *  apagado: el form v1 (pre-F5) no lo manda — default a la primera. */
  modalidad_codigo?: string;
  /** F2: checkbox "Acepto los términos" — el form v2 (F5) lo manda siempre. */
  acepta_terminos?: boolean;
};

export type InscripcionResult = {
  id: number;
  en_lista_espera: boolean;
  cupos_disponibles: number;
};

export function apiGetTalleres() {
  return get<Taller[]>("/api/talleres");
}

export function apiGetTaller(slug: string) {
  return get<Taller>(`/api/talleres/${slug}`);
}

export async function apiUploadComprobante(
  slug: string,
  file: File,
): Promise<{ url: string; key: string }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/api/talleres/${slug}/upload-comprobante`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail ?? `No se pudo subir el comprobante (${res.status})`);
  }
  return res.json() as Promise<{ url: string; key: string }>;
}

export function apiCrearInscripcion(slug: string, body: InscripcionBody) {
  return post<InscripcionResult>(`/api/talleres/${slug}/inscripcion`, body);
}

// ── F5: página pública "completá tu seña" (/escuela/sena/$token) ───────────

export type OfertaCupo = {
  taller_nombre: string;
  nombre_pila: string;
  fecha_inicio_str: string;
  fecha_fin_str: string;
  horario: string;
  direccion: string;
  precio_sena_str: string;
  pago_alias: string;
  pago_cbu: string;
  pago_banco: string;
};

class ApiStatusError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** 404 = link inválido/vencido; 410 = oferta ya no vigente (reclamada o
 *  nunca ofrecida) — el caller distingue por `err.status`, no por texto. */
export async function apiGetOfertaCupo(token: string): Promise<OfertaCupo> {
  const res = await fetch(`${API_BASE}/api/talleres/sena/${token}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new ApiStatusError(res.status, err?.detail ?? `Error ${res.status}`);
  }
  return res.json();
}

export async function apiUploadComprobanteSena(
  token: string,
  file: File,
): Promise<{ url: string; key: string }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/api/talleres/sena/${token}/upload-comprobante`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new ApiStatusError(
      res.status,
      err?.detail ?? `No se pudo subir el comprobante (${res.status})`,
    );
  }
  return res.json();
}

export async function apiClaimOfertaCupo(
  token: string,
  body: { comprobante_url?: string; comprobante_key?: string },
): Promise<{ ok: boolean }> {
  const res = await fetch(`${API_BASE}/api/talleres/sena/${token}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new ApiStatusError(res.status, err?.detail ?? `Error ${res.status}`);
  }
  return res.json();
}
