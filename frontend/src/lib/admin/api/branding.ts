import { authedFetch, authedJson } from "@/lib/authedFetch";
import type {
  EmailChannelStatus,
  EmailTemplateSummary,
  EmailTemplate,
  EmailTemplateInput,
  EmailLogEntry,
} from "./types";

export const brandingMethods = {
  uploadOgImage: async (file: File): Promise<{ ok: true; url: string }> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await authedFetch("/api/admin/settings/upload-og-image", {
      method: "POST",
      body: fd,
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(json?.detail ?? `Upload OG image → ${res.status}`);
    return json as { ok: true; url: string };
  },

  // ── Marca: subir SVG master → derivar assets (motor backend services/branding) ──
  uploadBrandSvg: async (
    kind: "wordmark" | "isologo",
    file: File,
  ): Promise<{ ok: true; settings: Record<string, string> }> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await authedFetch(`/api/admin/settings/upload-${kind}`, {
      method: "POST",
      body: fd,
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(json?.detail ?? `Upload ${kind} → ${res.status}`);
    return json as { ok: true; settings: Record<string, string> };
  },

  // ── Email templates ─────────────────────────────────────────────────
  getEmailStatus: () => authedJson<EmailChannelStatus>("/api/admin/email/status"),
  listEmailTemplates: () =>
    authedJson<{ items: EmailTemplateSummary[] }>("/api/admin/email-templates"),
  getEmailTemplate: (key: string) =>
    authedJson<EmailTemplate>(`/api/admin/email-templates/${encodeURIComponent(key)}`),
  updateEmailTemplate: (key: string, input: EmailTemplateInput) =>
    authedJson<EmailTemplate>(`/api/admin/email-templates/${encodeURIComponent(key)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  previewEmailTemplate: (key: string, context?: Record<string, unknown>) =>
    authedJson<{ subject: string; html: string; text: string }>(
      `/api/admin/email-templates/${encodeURIComponent(key)}/preview`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ context: context ?? null }),
      },
    ),
  testEmailTemplate: (key: string, to: string, context?: Record<string, unknown>) =>
    authedJson<{
      ok: boolean;
      provider?: string;
      provider_id?: string;
      error?: string;
      log_id?: number;
    }>(`/api/admin/email-templates/${encodeURIComponent(key)}/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to, context: context ?? null }),
    }),
  /** On/off del envío automático de una plantilla. */
  setEmailTemplateEnabled: (key: string, enabled: boolean) =>
    authedJson<{ key: string; enabled: boolean }>(
      `/api/admin/email-templates/${encodeURIComponent(key)}/enabled`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      },
    ),
  /** Log de envíos (read-only, paginado). Filtros opcionales por estado/plantilla/destinatario. */
  listEmailsLog: (params?: {
    status?: string;
    template_key?: string;
    q?: string;
    limit?: number;
    offset?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    if (params?.template_key) query.set("template_key", params.template_key);
    if (params?.q) query.set("q", params.q);
    if (params?.limit != null) query.set("limit", String(params.limit));
    if (params?.offset != null) query.set("offset", String(params.offset));
    const qs = query.toString();
    return authedJson<{
      items: EmailLogEntry[];
      total: number;
      limit: number;
      offset: number;
    }>(`/api/admin/emails-log${qs ? `?${qs}` : ""}`);
  },
};
