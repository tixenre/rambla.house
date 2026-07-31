/**
 * API del módulo de Comunicación — qué le comunicamos al cliente y por dónde sale.
 *
 * Espeja el `REGISTRO` de `services/comunicacion/eventos.py` (fuente única): la
 * pantalla NO tiene su propia lista de eventos, la pide. Si alguien agrega un
 * evento en el backend, aparece acá solo.
 */
import { authedJson } from "@/lib/authedFetch";

import type { ChequeoWhatsApp } from "./whatsapp";

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

export type EventoComunicacion = {
  key: string;
  descripcion: string;
  estrategia: EstrategiaComunicacion;
  estrategia_label: string;
  estrategia_detalle: string;
  mail_cliente: MailDeEvento | null;
  mail_admin: MailDeEvento | null;
  con_adjunto_ics: boolean;
  whatsapp: {
    key: string;
    meta_name: string;
    lang: string;
    copy_ejemplo: string;
    parametros: string[];
  } | null;
};

export type EstadoCanales = {
  mail: { provider: string; activo: boolean; from_addr: string; admin_to: string };
  whatsapp: { listo: boolean; chequeos: ChequeoWhatsApp[]; ambiente: string };
};

export const comunicacionApi = {
  getEventos: () =>
    authedJson<{ eventos: EventoComunicacion[]; canales: EstadoCanales }>(
      "/api/admin/comunicacion/eventos",
    ),
};
