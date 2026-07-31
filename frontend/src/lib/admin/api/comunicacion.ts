/**
 * API del módulo de Comunicación — qué le comunicamos al cliente y por dónde sale.
 *
 * Espeja el `REGISTRO` de `services/comunicacion/eventos.py` (fuente única): la
 * pantalla NO tiene su propia lista de eventos, la pide. Si alguien agrega un
 * evento en el backend, aparece acá solo.
 */
import { authedJson } from "@/lib/authedFetch";

import type { ChequeoWhatsApp, EstadoMeta } from "./whatsapp";

/** Estrategia de despacho: por dónde sale un evento (plan A/B). */
export type EstrategiaComunicacion = "fallback" | "ambos" | "solo_mail" | "solo_whatsapp";

/** El mail de un evento, con el estado del template que usa. */
export type MailDeEvento = {
  template: string;
  asunto: string | null;
  activo: boolean | null;
  /** false = el registro apunta a un template que no existe en la tabla. */
  existe: boolean;
};

/** La plantilla de WhatsApp de un evento, con su estado de aprobación en Meta. */
export type WhatsAppDeEvento = {
  key: string;
  meta_name: string;
  lang: string;
  copy_ejemplo: string;
  parametros: string[];
  /** null = no se pudo consultar (canal sin configurar / Meta no respondió). */
  estado_meta: EstadoMeta | null;
};

/**
 * Una perilla configurable de un evento (horario, antelación, destinatarios).
 * Se guarda con `PUT /api/admin/settings/{setting}` — la misma puerta de siempre.
 */
export type OpcionEvento = {
  setting: string;
  label: string;
  tipo: "switch" | "numero" | "texto";
  ayuda: string;
  valor: string;
  default: string;
  minimo: number | null;
  maximo: number | null;
  placeholder: string;
  /** Nombre de la env var que la está pisando → no se puede editar desde acá. */
  bloqueada_por_env: string | null;
};

export type EventoComunicacion = {
  key: string;
  /** Nombre corto del evento (título de su tarjeta). */
  titulo: string;
  descripcion: string;
  /** Por dónde sale HOY: lo que eligió el dueño o, si no eligió, el default del código. */
  estrategia: EstrategiaComunicacion;
  estrategia_label: string;
  estrategia_detalle: string;
  /** Dónde se guarda la elección (`PUT /api/admin/settings/{key}`). */
  estrategia_setting: string;
  /** Lo que declara el registro — a lo que se vuelve si se vacía la elección. */
  estrategia_default: EstrategiaComunicacion;
  /** Solo las formas que ESTE evento puede tener (según los canales que tiene). */
  estrategias_posibles: {
    valor: EstrategiaComunicacion;
    label: string;
    detalle: string;
  }[];
  mail_cliente: MailDeEvento | null;
  mail_admin: MailDeEvento | null;
  con_adjunto_ics: boolean;
  whatsapp: WhatsAppDeEvento | null;
  /** Aviso interno al equipo por WhatsApp (independiente del canal del cliente). */
  whatsapp_admin: WhatsAppDeEvento | null;
  opciones: OpcionEvento[];
};

/** Un mail que no dispara ningún evento del registro (hoy, los de Talleres). */
export type OtroMail = { template: string; asunto: string | null; activo: boolean };

export type EstadoCanales = {
  mail: { provider: string; activo: boolean; from_addr: string; admin_to: string };
  whatsapp: {
    listo: boolean;
    chequeos: ChequeoWhatsApp[];
    ambiente: string;
    gestion_plantillas: { disponible: boolean; motivo: string | null };
  };
};

export type ModuloComunicacion = {
  eventos: EventoComunicacion[];
  otros_mails: OtroMail[];
  canales: EstadoCanales;
};

export const comunicacionApi = {
  getEventos: () => authedJson<ModuloComunicacion>("/api/admin/comunicacion/eventos"),
};
