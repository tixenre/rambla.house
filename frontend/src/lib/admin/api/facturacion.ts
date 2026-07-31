/**
 * API de facturación electrónica ARCA (#1139).
 */
import { authedFetch, authedJson, authedPostJson } from "@/lib/authedFetch";

export type EmisorArca = {
  id: number;
  nombre: string;
  cuit: string;
  pto_vta: number;
  condicion_iva: "responsable_inscripto" | "monotributo" | "exento";
  cert_cargado: boolean;
  activo: boolean;
  razon_social: string | null;
  domicilio: string | null;
  iibb: string | null;
  inicio_actividades: string | null;
  notas: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type EstadoFacturacion = {
  ambiente: "homologacion" | "produccion";
  emisores: EmisorArca[];
  catalogos_actualizados_at: string | null;
};

// Formato de renderizado de una factura — ver `arca_fe.LAYOUTS_INFO`. `advertencia` viene vacía
// ("") cuando no aplica; se muestra solo para "simplificada".
export type LayoutFactura = {
  id: "oficial" | "detallada" | "simplificada";
  nombre: string;
  descripcion: string;
  advertencia: string;
};

export type FacturaEstado = "pendiente" | "emitida" | "error" | "anulada";

export type Factura = {
  id: number;
  pedido_id: number;
  emisor: string;
  ambiente: "homologacion" | "produccion";
  cbte_tipo: number;
  pto_vta: number;
  cbte_nro: number | null;
  cae: string | null;
  cae_vto: string | null;
  doc_tipo: number | null;
  doc_nro: number | null;
  condicion_iva_receptor: number | null;
  imp_neto: number;
  imp_iva: number;
  imp_total: number;
  moneda: string;
  cliente_cuit: string | null;
  razon_social: string | null;
  qr_payload: string | null;
  pdf_key: string | null;
  estado: FacturaEstado;
  nota_credito_de: number | null;
  errores: string[] | null;
  fecha_emision: string | null;
  created_at: string | null;
  created_by: string | null;
};

export type FacturasListResp = {
  facturas: Factura[];
  total_imp_total: number;
  count: number;
};

export type PadronResult =
  | {
      encontrado: true;
      razon_social: string;
      nombre: string;
      apellido: string;
      domicilio: string;
      condicion_iva: string;
      estado_clave: string;
      tipo_persona: string;
      categoria_monotributo: string;
      actividades: string[];
      impuestos: { id_impuesto: number; descripcion: string; estado: string; periodo: number }[];
    }
  // `motivo` presente = no pudimos ni completar la consulta (WSAA/relación/
  // cert/red) — distinto de "ARCA no tiene datos para este CUIT" (sin motivo).
  | { encontrado: false; motivo?: string };

export type ChequeoPreview = { check: string; ok: boolean; bloqueante: boolean; mensaje: string };

export type PreviewFactura = {
  ambiente: "homologacion" | "produccion";
  emisor: { nombre: string; cuit: number; condicion_iva: string; condicion_iva_label: string };
  receptor: {
    doc_tipo: string;
    doc_nro: string;
    condicion_iva: string;
    condicion_iva_label: string;
    razon_social: string;
    domicilio: string;
  };
  comprobante: {
    letra: string;
    tipo_nro: number;
    numero_a_emitir: number;
    pto_vta: number;
    concepto: string;
    condicion_venta: string;
  };
  importes: { neto: number; iva: number; total: number };
  fechas: {
    emision: string;
    servicio_desde: string | null;
    servicio_hasta: string | null;
    vto_pago: string | null;
  };
  chequeos: ChequeoPreview[];
  listo: boolean;
};

export const facturacionApi = {
  getEstado: () => authedJson<EstadoFacturacion>("/api/admin/facturacion/estado"),
  // Layouts disponibles (nombre/descripción/advertencia) — fuente única, no hardcodear el copy acá.
  getLayouts: () => authedJson<LayoutFactura[]>("/api/admin/facturacion/layouts"),

  // Autocompletar razón social/domicilio/condición IVA desde el padrón ARCA.
  consultarPadron: (cuit: string) =>
    authedJson<PadronResult>(`/api/admin/arca/padron/${encodeURIComponent(cuit)}`),

  // Actualiza los catálogos de ARCA (doc_tipo/concepto/condición IVA
  // receptor) que se muestran en el PDF de la factura.
  refrescarCatalogos: () =>
    authedPostJson<{
      ok: boolean;
      doc_tipo: number;
      concepto: number;
      condicion_iva_receptor: number;
    }>("/api/admin/arca/catalogos/refrescar", {}),

  // Emisores
  listEmisores: () => authedJson<EmisorArca[]>("/api/admin/emisores-arca"),
  createEmisor: (body: Omit<EmisorArca, "id" | "cert_cargado" | "created_at" | "updated_at">) =>
    authedPostJson<EmisorArca>("/api/admin/emisores-arca", body),
  updateEmisor: (id: number, body: Partial<EmisorArca>) =>
    authedJson<EmisorArca>(`/api/admin/emisores-arca/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  cargarCert: (id: number, cert_pem: string, key_pem: string) =>
    authedPostJson<{ ok: boolean; cert_cargado: boolean }>(`/api/admin/emisores-arca/${id}/cert`, {
      cert_pem,
      key_pem,
    }),
  desactivarEmisor: (id: number) =>
    authedJson<void>(`/api/admin/emisores-arca/${id}`, { method: "DELETE" }),
  // Puntos de venta habilitados en ARCA para ESTE emisor (requiere cert cargado).
  // `excluidos` explica por qué un punto que ARCA sí devolvió no cuenta como
  // habilitado (bloqueado / dado de baja / no electrónico) — evita el mensaje
  // genérico "no hay nada" cuando en realidad ARCA tiene puntos, pero ninguno sirve.
  consultarPuntosVenta: (id: number) =>
    authedJson<{
      puntos_venta: { nro: number; emision_tipo?: string | null }[];
      excluidos: {
        nro: number;
        motivo: "bloqueado" | "dado_de_baja" | "no_electronico";
        raw_emision_tipo?: string | null;
      }[];
    }>(`/api/admin/emisores-arca/${id}/puntos-venta`),
  // Metadata del cert cargado (subject/serie/vigencia) — para comparar contra
  // el "Computador Fiscal" delegado en el Administrador de Relaciones de ARCA.
  consultarCertInfo: (id: number) =>
    authedJson<{
      subject: string;
      numero_serie: string;
      vigente_desde: string;
      vigente_hasta: string;
    }>(`/api/admin/emisores-arca/${id}/cert-info`),
  // Diagnóstico de configuración: capa local (CUIT/cert/punto de venta) +
  // capa AFIP (wsfe delegado, punto de venta habilitado, padrón delegado) —
  // solo pega contra AFIP si la capa local no garantiza ya el fracaso.
  diagnosticarEmisor: (id: number) =>
    authedJson<{ chequeos: ChequeoPreview[]; listo: boolean }>(
      `/api/admin/emisores-arca/${id}/diagnostico`,
    ),
  // Guía de trámites de AFIP — fuente única, lee arca_fe/TRAMITES_AFIP.md tal cual.
  getGuiaAfip: () => authedJson<{ markdown: string }>("/api/admin/emisores-arca/guia"),

  // Facturas
  // `emisorId`: override excepcional — factura con un emisor puntual distinto al que
  // resolvería automáticamente el perfil del cliente (ver services.facturacion.emisores.emisor_para).
  // Default (undefined) = automático, mismo comportamiento de siempre.
  previewFactura: (pedidoId: number, emisorId?: number) =>
    authedJson<PreviewFactura>(
      `/api/alquileres/${pedidoId}/facturar/preview${emisorId ? `?emisor_id=${emisorId}` : ""}`,
    ),
  // HTML completo del documento (mismo layout real, CAE/QR placeholder) — se embebe en un
  // <iframe src={blobUrl}>, mismo patrón que ContratoPreviewModal (obtenerContratoPreviewHtml).
  previewFacturaHtml: async (
    pedidoId: number,
    layout: string,
    emisorId?: number,
  ): Promise<string> => {
    const qs = new URLSearchParams({ layout });
    if (emisorId) qs.set("emisor_id", String(emisorId));
    const res = await authedFetch(`/api/alquileres/${pedidoId}/facturar/preview-html?${qs}`);
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      let message = "";
      try {
        message = JSON.parse(text)?.detail ?? "";
      } catch {
        /* no era JSON */
      }
      throw new Error(message || "No pudimos generar el preview de la factura.");
    }
    return res.text();
  },
  facturarPedido: (pedidoId: number, emisorId?: number) =>
    authedPostJson<Factura>(
      `/api/alquileres/${pedidoId}/facturar`,
      emisorId ? { emisor_id: emisorId } : {},
    ),
  listFacturasPedido: (pedidoId: number) =>
    authedJson<Factura[]>(`/api/alquileres/${pedidoId}/facturas`),
  notaCreditoFactura: (facturaId: number) =>
    authedPostJson<Factura>(`/api/facturas/${facturaId}/nota-credito`, {}),
  enviarMailFactura: (facturaId: number, layout?: string) =>
    authedPostJson<{ ok: boolean; to: string }>(
      `/api/facturas/${facturaId}/enviar-mail${layout ? `?layout=${layout}` : ""}`,
      {},
    ),
  listFacturas: (params?: { emisor?: string; estado?: string; desde?: string; hasta?: string }) => {
    const sp = new URLSearchParams();
    if (params?.emisor) sp.set("emisor", params.emisor);
    if (params?.estado) sp.set("estado", params.estado);
    if (params?.desde) sp.set("desde", params.desde);
    if (params?.hasta) sp.set("hasta", params.hasta);
    const qs = sp.toString();
    return authedJson<FacturasListResp>(`/api/admin/facturas${qs ? `?${qs}` : ""}`);
  },
};
