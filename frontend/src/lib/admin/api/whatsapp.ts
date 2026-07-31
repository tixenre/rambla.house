/**
 * API del canal WhatsApp (Meta Cloud API) para el back-office.
 *
 * Espeja `facturacion.ts`: un `estado` agregador (readiness sin secretos) + las
 * acciones de prueba. El token NUNCA viaja por acá — vive en variables de entorno
 * del ambiente (`WHATSAPP_ACCESS_TOKEN`), no en la BD ni en la UI.
 */
import { authedJson, authedPostJson } from "@/lib/authedFetch";

/** Un chequeo de readiness — mismo shape que el diagnóstico de ARCA (`Chequeos`). */
export type ChequeoWhatsApp = {
  check: string;
  ok: boolean;
  bloqueante: boolean;
  mensaje: string;
};

/** Un template pre-aprobado en Meta, tal como lo declara el registro del backend. */
export type PlantillaWhatsApp = {
  key: string;
  meta_name: string;
  lang: string;
  categoria: string;
  descripcion: string;
  copy_ejemplo: string;
  parametros: string[];
};

export type EstadoWhatsApp = {
  chequeos: ChequeoWhatsApp[];
  listo: boolean;
  ambiente: "produccion" | "no_produccion";
  graph_version: string;
  plantillas: PlantillaWhatsApp[];
};

/** Resultado de una ventana del barrido de recordatorios de devolución. */
export type VentanaDevolucion = {
  candidatos: number;
  enviados: number;
  fallidos: number;
  saltados: number;
  pedidos: Array<{
    id: number;
    numero_pedido: number | string;
    status: string;
    reason?: string;
    error?: string;
  }>;
};

export type CorridaDevolucion = {
  fecha: string;
  dry_run: boolean;
  ventanas: Record<string, VentanaDevolucion>;
};

export const whatsappApi = {
  /** Readiness del canal + los templates a dar de alta en Meta (con su copy). */
  getEstado: () => authedJson<EstadoWhatsApp>("/api/admin/whatsapp/estado"),

  /**
   * Envía un template de prueba a un número E.164. Valida el pipeline de punta a
   * punta sin tocar un pedido real: no chequea opt-in y no escribe en `whatsapp_log`.
   * Fuera de producción solo acepta números de `WHATSAPP_TEST_RECIPIENTS`.
   */
  enviarPrueba: (to: string, plantilla: string) =>
    authedPostJson<{ ok: boolean; wamid: string; to: string; template: string }>(
      "/api/admin/whatsapp/test",
      { to, plantilla },
    ),

  /**
   * Corre el barrido de recordatorios de devolución on-demand. `dryRun` (default)
   * solo lista candidatos — preview seguro, no manda nada.
   */
  correrDevolucion: (dryRun = true) =>
    authedPostJson<CorridaDevolucion>("/api/admin/whatsapp/recordatorios-devolucion/run", {
      dry_run: dryRun,
    }),
};
