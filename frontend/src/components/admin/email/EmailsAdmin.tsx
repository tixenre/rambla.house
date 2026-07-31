/**
 * Administración de mails — vive dentro de /admin/settings (sección "Emails").
 *
 * Reúne todo lo de mails en un solo lugar (Fase B):
 *  - Estado del canal (banner verde/ámbar).
 *  - Plantillas: lista con on/off por plantilla + editor (Editar/Preview/Test).
 *  - Recordatorio de retiro: encendido / hora / días-antes (app_settings, con
 *    override por env — ver backend/jobs/recordatorios_config.py).
 *  - Log de envíos: visor read-only de `emails_log` para diagnosticar entregas.
 *
 * Antes era la página aparte /admin/email-templates (ahora redirige acá).
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Send, Eye, Pencil, CheckCircle2, AlertTriangle, RefreshCw, Mail } from "lucide-react";
import { Spinner } from "@/design-system/ui/spinner";

import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { ErrorState } from "@/components/admin/ErrorState";
import { ListSkeleton, TableSkeleton } from "@/components/admin/skeletons";
import { Button } from "@/design-system/ui/button";
import { Pill } from "@/design-system/ui/Pill";
import { ModalBackdrop } from "@/design-system/ui/modal-backdrop";
import { Input } from "@/design-system/ui/input";
import { Textarea } from "@/design-system/ui/textarea";
import { Label } from "@/design-system/ui/label";
import { Switch } from "@/design-system/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/design-system/ui/tabs";

import {
  adminApi,
  type EmailTemplate,
  type EmailTemplateInput,
  type EmailChannelStatus,
  type EmailLogEntry,
} from "@/lib/admin/api";

// Labels y descripción amigable de cada template. Si se agrega un template
// nuevo en backend, agregar acá también — los que no tengan entry se muestran
// con la `key` cruda.
const TEMPLATE_META: Record<string, { label: string; description: string }> = {
  pedido_creado_cliente: {
    label: "Pedido creado — cliente",
    description: "Confirmación automática al cliente cuando entra un pedido nuevo.",
  },
  pedido_creado_admin: {
    label: "Pedido creado — admin",
    description: "Notificación al equipo cuando entra un pedido nuevo.",
  },
  pedido_confirmado_cliente: {
    label: "Pedido confirmado — cliente",
    description: "Aviso al cliente cuando el admin pasa el pedido a 'confirmado'.",
  },
  recordatorio_retiro: {
    label: "Recordatorio de retiro",
    description: "Recordatorio automático al cliente antes del retiro (ver controles abajo).",
  },
};

// Variables comunes de los mails de pedido. Mantener en sincronía con
// `_pedido_email_context()` en backend/routes/alquileres.py.
const AVAILABLE_VARS: { name: string; help: string }[] = [
  { name: "cliente_nombre", help: "Nombre completo del cliente" },
  { name: "cliente_email", help: "Email del cliente" },
  { name: "cliente_telefono", help: "Teléfono del cliente" },
  { name: "numero_pedido", help: "Número público del pedido" },
  { name: "fecha_desde", help: "Fecha de retiro" },
  { name: "fecha_hasta", help: "Fecha de devolución" },
  { name: "total", help: "Monto total del pedido" },
  { name: "notas", help: "Notas que dejó el cliente" },
  { name: "items_html", help: "Lista de equipos como tabla HTML" },
  { name: "items_text", help: "Lista de equipos como texto plano" },
  { name: "admin_url", help: "Link al pedido en el back-office (solo admin)" },
  { name: "portal_url", help: "Link al portal del cliente (seguir el pedido)" },
  { name: "dias_antes", help: "Días de anticipación (solo recordatorio)" },
];

export function EmailsAdmin() {
  const [editingKey, setEditingKey] = useState<string | null>(null);

  const listQ = useQuery({
    queryKey: ["admin", "email-templates"],
    queryFn: () => adminApi.listEmailTemplates(),
    staleTime: 0,
  });
  const statusQ = useQuery({
    queryKey: ["admin", "email-status"],
    queryFn: () => adminApi.getEmailStatus(),
    staleTime: 0,
  });

  const items = listQ.data?.items ?? [];

  return (
    <div className="space-y-6">
      {statusQ.data && <EmailChannelBanner status={statusQ.data} />}

      {/* Plantillas */}
      <section className="card p-4 space-y-3">
        <div>
          <h2 className="font-display text-lg text-ink">Plantillas</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Prendé/apagá cada mail automático y editá su contenido (subject + HTML + texto).
          </p>
        </div>

        {listQ.isLoading && <ListSkeleton rows={5} />}

        {!listQ.isLoading && items.length === 0 && (
          <EmptyState
            icon={<Mail className="h-6 w-6" />}
            title="No hay templates"
            sub="Si recién corriste la migración, refrescá."
          />
        )}

        {!listQ.isLoading && items.length > 0 && (
          <div className="divide-y hairline border hairline rounded-md overflow-hidden">
            {items.map((t) => (
              <TemplateRow key={t.key} tpl={t} onEdit={() => setEditingKey(t.key)} />
            ))}
          </div>
        )}
      </section>

      {/* Recordatorio de retiro */}
      <RecordatorioControls />

      {/* Log de envíos */}
      <EmailsLog />

      {editingKey && (
        <TemplateEditorModal
          key={editingKey}
          tplKey={editingKey}
          onClose={() => setEditingKey(null)}
        />
      )}
    </div>
  );
}

function TemplateRow({
  tpl,
  onEdit,
}: {
  tpl: {
    key: string;
    subject: string;
    enabled: boolean;
    updated_by: string | null;
    updated_at: string;
  };
  onEdit: () => void;
}) {
  const qc = useQueryClient();
  const meta = TEMPLATE_META[tpl.key];
  const toggleMut = useMutation({
    mutationFn: (enabled: boolean) => adminApi.setEmailTemplateEnabled(tpl.key, enabled),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["admin", "email-templates"] });
      toast.success(data.enabled ? "Mail activado" : "Mail apagado");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="flex items-center gap-3 px-4 py-3 hover:bg-muted/20 transition">
      <Switch
        checked={tpl.enabled}
        disabled={toggleMut.isPending}
        onCheckedChange={(v) => toggleMut.mutate(v)}
        aria-label={tpl.enabled ? "Apagar este mail" : "Activar este mail"}
      />
      <button
        type="button"
        onClick={onEdit}
        className="min-w-0 flex-1 text-left flex items-start gap-3"
      >
        <div className="min-w-0 flex-1">
          <div className="font-display text-base text-ink">
            {meta?.label ?? tpl.key}
            {!tpl.enabled && (
              <span className="ml-2 font-mono text-2xs uppercase tracking-wide text-muted-foreground">
                apagado
              </span>
            )}
          </div>
          <div className="text-xs text-muted-foreground mt-0.5 truncate">{tpl.subject}</div>
          {meta && (
            <div className="text-xs text-muted-foreground/70 mt-0.5">{meta.description}</div>
          )}
        </div>
        <Pencil className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-1" />
      </button>
    </div>
  );
}

// ── Recordatorio de retiro: encendido / hora / días-antes ────────────────────

function RecordatorioControls() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["admin", "settings", "recordatorios"],
    queryFn: () => adminApi.listSettings(),
    staleTime: 0,
  });

  const map = useMemo(() => {
    const m: Record<string, string> = {};
    (q.data?.items ?? []).forEach((s) => {
      m[s.key] = s.value;
    });
    return m;
  }, [q.data]);

  const enabled = (map["recordatorios_enabled"] ?? "0") === "1";
  const hora = map["recordatorios_hora"] ?? "9";
  const dias = map["recordatorios_dias_antes"] ?? "1";

  const [horaInput, setHoraInput] = useState(hora);
  const [diasInput, setDiasInput] = useState(dias);
  useEffect(() => {
    setHoraInput(hora);
    setDiasInput(dias);
  }, [hora, dias]);

  const mut = useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) =>
      adminApi.updateSetting(key, value),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "settings", "recordatorios"] });
      toast.success("Guardado");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const dirty = horaInput !== hora || diasInput !== dias;

  return (
    <section className="card p-4 space-y-3">
      <div>
        <h2 className="font-display text-lg text-ink">Recordatorio de retiro</h2>
        <p className="text-xs text-muted-foreground mt-0.5">
          El mail “mañana retirás”. Controlás si se manda, a qué hora corre el barrido diario (hora
          de Argentina) y con cuántos días de anticipación. Una variable de entorno, si está
          seteada, tiene prioridad sobre esto.
        </p>
      </div>

      <div className="flex items-center justify-between border-t hairline pt-3">
        <div>
          <div className="text-sm text-ink">Enviar recordatorios automáticos</div>
          <div className="text-xs text-muted-foreground">
            {q.isLoading ? "Cargando…" : enabled ? "Activado" : "Apagado"}
          </div>
        </div>
        <Switch
          checked={enabled}
          disabled={q.isLoading || mut.isPending}
          onCheckedChange={(v) =>
            mut.mutate({ key: "recordatorios_enabled", value: v ? "1" : "0" })
          }
          aria-label="Activar o apagar el recordatorio"
        />
      </div>

      <div className="flex flex-wrap items-end gap-3 border-t hairline pt-3">
        <div className="space-y-1">
          <div className="text-2xs uppercase tracking-wide text-muted-foreground">
            Hora del barrido (0–23)
          </div>
          <Input
            type="number"
            min={0}
            max={23}
            className="w-24"
            value={horaInput}
            onChange={(e) => setHoraInput(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <div className="text-2xs uppercase tracking-wide text-muted-foreground">
            Días antes (1–14)
          </div>
          <Input
            type="number"
            min={1}
            max={14}
            className="w-24"
            value={diasInput}
            onChange={(e) => setDiasInput(e.target.value)}
          />
        </div>
        <Button
          size="sm"
          onClick={() => {
            if (horaInput !== hora) mut.mutate({ key: "recordatorios_hora", value: horaInput });
            if (diasInput !== dias)
              mut.mutate({ key: "recordatorios_dias_antes", value: diasInput });
          }}
          disabled={!dirty || mut.isPending}
        >
          {mut.isPending ? "Guardando…" : "Guardar"}
        </Button>
      </div>
    </section>
  );
}

// ── Log de envíos (read-only) ────────────────────────────────────────────────

const STATUS_FILTERS = [
  { value: "", label: "Todos" },
  { value: "sent", label: "Enviados" },
  { value: "failed", label: "Fallidos" },
];
const PAGE = 25;

function EmailsLog() {
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);

  const q = useQuery({
    queryKey: ["admin", "emails-log", status, offset],
    queryFn: () => adminApi.listEmailsLog({ status: status || undefined, limit: PAGE, offset }),
  });

  const data = q.data;
  const total = data?.total ?? 0;
  const items = data?.items ?? [];

  return (
    <section className="card p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="font-display text-lg text-ink">Log de envíos</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Qué salió, a quién, y cuáles fallaron (con el error). Lo más útil para diagnosticar
            entregabilidad.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => q.refetch()} disabled={q.isFetching}>
          <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${q.isFetching ? "animate-spin" : ""}`} />
          Refrescar
        </Button>
      </div>

      <div className="flex items-center gap-1.5">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => {
              setStatus(f.value);
              setOffset(0);
            }}
            className={`rounded-full px-3 py-1 text-xs transition ${
              status === f.value
                ? "bg-ink text-background"
                : "border hairline text-muted-foreground hover:bg-muted/30"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {q.isLoading && <TableSkeleton rows={6} cols={5} />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}

      {!q.isLoading && !q.isError && items.length === 0 && (
        <EmptyState
          icon={<Send className="h-6 w-6" />}
          title="No hay envíos registrados todavía"
          sub="Cuando se mande un mail va a aparecer acá."
        />
      )}

      {!q.isError && items.length > 0 && (
        <AdminTable
          columns={EMAIL_LOG_COLUMNS}
          rows={items}
          getRowKey={(e) => e.id}
          rowClassName={() => "align-top"}
        />
      )}

      {total > PAGE && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {offset + 1}–{Math.min(offset + PAGE, total)} de {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setOffset((o) => Math.max(0, o - PAGE))}
              disabled={offset === 0 || q.isFetching}
            >
              Anterior
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setOffset((o) => o + PAGE)}
              disabled={offset + PAGE >= total || q.isFetching}
            >
              Siguiente
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}

const EMAIL_LOG_COLUMNS: Column<EmailLogEntry>[] = [
  {
    header: "Fecha",
    className: "whitespace-nowrap font-mono text-xs text-muted-foreground",
    cell: (entry) =>
      entry.sent_at
        ? new Date(entry.sent_at).toLocaleString("es-AR", {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })
        : "—",
  },
  {
    header: "Estado",
    className: "whitespace-nowrap",
    cell: (entry) => {
      const tone =
        entry.status === "sent" ? "success" : entry.status === "failed" ? "danger" : "neutral";
      return <Pill tone={tone}>{entry.status}</Pill>;
    },
  },
  {
    header: "Plantilla",
    cell: (entry) => TEMPLATE_META[entry.template_key]?.label ?? entry.template_key,
  },
  {
    header: "Destinatario",
    className: "font-mono text-xs",
    cell: (entry) => entry.to_addr,
  },
  {
    header: "Detalle",
    className: "text-muted-foreground",
    cell: (entry) =>
      entry.error ? (
        <span className="text-destructive">{entry.error}</span>
      ) : (
        <span className="font-mono text-xs text-muted-foreground/70">
          {entry.provider}
          {entry.provider_id ? ` · ${entry.provider_id}` : ""}
        </span>
      ),
  },
];

// ── Banner de estado del canal ───────────────────────────────────────────────

function EmailChannelBanner({ status }: { status: EmailChannelStatus }) {
  const provLabel: Record<string, string> = {
    resend: "Resend",
    smtp: "SMTP",
    test: "Test (no envía)",
  };
  if (!status.activo) {
    return (
      <div className="rounded-md border border-amber/40 bg-amber/10 p-4 flex items-start gap-3">
        <AlertTriangle className="h-5 w-5 text-ink shrink-0 mt-0.5" />
        <div className="text-sm">
          <div className="font-display text-ink">El canal de mail está apagado</div>
          <p className="text-muted-foreground mt-0.5">
            Backend actual: <strong>{provLabel[status.provider] ?? status.provider}</strong>. No se
            envía ningún mail (solo se registra). Para activarlo, seteá{" "}
            <code className="font-mono text-xs">RESEND_API_KEY</code> en las variables del ambiente
            y volvé a desplegar.
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className="rounded-md border border-verde/30 bg-verde/10 p-4 flex items-start gap-3">
      <CheckCircle2 className="h-5 w-5 text-verde-ink shrink-0 mt-0.5" />
      <div className="text-sm">
        <div className="font-display text-ink">
          Canal de mail activo · {provLabel[status.provider] ?? status.provider}
        </div>
        <p className="text-muted-foreground mt-0.5">
          Enviando como <strong>{status.from_addr}</strong>
          {status.admin_to && (
            <>
              {" "}
              · avisos al admin a <strong>{status.admin_to}</strong>
            </>
          )}
          . Probá un envío real desde el tab <em>Test</em> de cualquier plantilla.
        </p>
      </div>
    </div>
  );
}

// ── Editor (Editar / Preview / Test) ─────────────────────────────────────────

function TemplateEditorModal({ tplKey, onClose }: { tplKey: string; onClose: () => void }) {
  const qc = useQueryClient();
  const meta = TEMPLATE_META[tplKey];
  const [tab, setTab] = useState<"edit" | "preview" | "test">("edit");

  const tplQ = useQuery({
    queryKey: ["admin", "email-templates", tplKey],
    queryFn: () => adminApi.getEmailTemplate(tplKey),
  });

  const [form, setForm] = useState<EmailTemplateInput | null>(null);
  useMemo(() => {
    if (tplQ.data && form === null) {
      setForm({
        subject: tplQ.data.subject,
        body_html: tplQ.data.body_html,
        body_text: tplQ.data.body_text,
      });
    }
  }, [tplQ.data, form]);

  const saveMut = useMutation({
    mutationFn: (input: EmailTemplateInput) => adminApi.updateEmailTemplate(tplKey, input),
    onSuccess: (data: EmailTemplate) => {
      toast.success("Template guardado");
      qc.setQueryData(["admin", "email-templates", tplKey], data);
      qc.invalidateQueries({ queryKey: ["admin", "email-templates"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <ModalBackdrop
      onClose={onClose}
      className="z-50 bg-black/60 flex items-center justify-center p-4"
    >
      <div className="w-full max-w-4xl max-h-[92vh] rounded-lg bg-background border hairline shadow-lg flex flex-col">
        <header className="border-b hairline px-4 py-3 shrink-0">
          <div className="font-display text-base text-ink">{meta?.label ?? tplKey}</div>
          <div className="font-mono text-2xs text-muted-foreground mt-0.5">key: {tplKey}</div>
        </header>

        <Tabs
          value={tab}
          onValueChange={(v) => setTab(v as typeof tab)}
          className="flex-1 flex flex-col min-h-0"
        >
          <TabsList className="mx-4 mt-3 shrink-0 w-fit">
            <TabsTrigger value="edit">
              <Pencil className="h-3.5 w-3.5 mr-1.5" />
              Editar
            </TabsTrigger>
            <TabsTrigger value="preview">
              <Eye className="h-3.5 w-3.5 mr-1.5" />
              Preview
            </TabsTrigger>
            <TabsTrigger value="test">
              <Send className="h-3.5 w-3.5 mr-1.5" />
              Test
            </TabsTrigger>
          </TabsList>

          {tplQ.isLoading && <div className="p-6 text-sm text-muted-foreground">Cargando…</div>}

          {form && tplQ.data && (
            <>
              <TabsContent value="edit" className="flex-1 overflow-y-auto p-4 m-0">
                <EditTab form={form} setForm={setForm} />
              </TabsContent>
              <TabsContent value="preview" className="flex-1 overflow-y-auto p-4 m-0">
                <PreviewTab tplKey={tplKey} />
              </TabsContent>
              <TabsContent value="test" className="flex-1 overflow-y-auto p-4 m-0">
                <TestTab tplKey={tplKey} />
              </TabsContent>
            </>
          )}
        </Tabs>

        <footer className="border-t hairline px-4 py-3 flex justify-end gap-2 shrink-0">
          <Button variant="outline" onClick={onClose} disabled={saveMut.isPending}>
            Cerrar
          </Button>
          {tab === "edit" && form && (
            <Button onClick={() => saveMut.mutate(form)} disabled={saveMut.isPending}>
              {saveMut.isPending ? "Guardando…" : "Guardar"}
            </Button>
          )}
        </footer>
      </div>
    </ModalBackdrop>
  );
}

function EditTab({
  form,
  setForm,
}: {
  form: EmailTemplateInput;
  setForm: (f: EmailTemplateInput) => void;
}) {
  return (
    <div className="grid grid-cols-[1fr_220px] gap-4">
      <div className="space-y-3 min-w-0">
        <div>
          <Label className="text-xs">Subject</Label>
          <Input
            value={form.subject}
            onChange={(e) => setForm({ ...form, subject: e.target.value })}
            placeholder="ej. Tu pedido #{{ numero_pedido }}"
          />
        </div>
        <div>
          <Label className="text-xs">Body HTML</Label>
          <Textarea
            value={form.body_html}
            onChange={(e) => setForm({ ...form, body_html: e.target.value })}
            rows={12}
            className="text-xs font-mono leading-relaxed"
            placeholder="<p>Hola {{ cliente_nombre }}…</p>"
          />
        </div>
        <div>
          <Label className="text-xs">Body texto plano</Label>
          <Textarea
            value={form.body_text}
            onChange={(e) => setForm({ ...form, body_text: e.target.value })}
            rows={8}
            className="text-xs font-mono leading-relaxed"
            placeholder="Hola {{ cliente_nombre }}…"
          />
        </div>
      </div>
      <aside className="border-l hairline pl-4">
        <div className="t-eyebrow mb-2">Variables</div>
        <ul className="space-y-1.5 text-xs">
          {AVAILABLE_VARS.map((v) => (
            <li key={v.name}>
              <code className="font-mono text-ink">{`{{ ${v.name} }}`}</code>
              <div className="text-2xs text-muted-foreground/70">{v.help}</div>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}

function PreviewTab({ tplKey }: { tplKey: string }) {
  const previewQ = useQuery({
    queryKey: ["admin", "email-templates", tplKey, "preview"],
    queryFn: () => adminApi.previewEmailTemplate(tplKey),
  });

  if (previewQ.isLoading) {
    return <div className="text-sm text-muted-foreground">Renderizando…</div>;
  }
  if (previewQ.isError) {
    return (
      <div className="text-sm text-destructive">Error: {(previewQ.error as Error).message}</div>
    );
  }
  const d = previewQ.data!;
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        Renderizado con datos de ejemplo. Después de guardar cambios refrescá esta pestaña.
      </p>
      <div>
        <Label className="text-xs">Subject</Label>
        <div className="border hairline rounded-md bg-muted/20 px-3 py-2 text-sm">{d.subject}</div>
      </div>
      <div>
        <Label className="text-xs">HTML</Label>
        <div className="flex justify-center rounded-md border hairline bg-muted/30 p-4">
          <iframe
            srcDoc={d.html}
            sandbox=""
            className="w-full max-w-[600px] h-96 rounded-md bg-white shadow-sm border hairline"
            title="preview html"
          />
        </div>
      </div>
      <div>
        <Label className="text-xs">Texto plano</Label>
        <pre className="border hairline rounded-md bg-muted/20 px-3 py-2 text-xs whitespace-pre-wrap font-mono">
          {d.text}
        </pre>
      </div>
    </div>
  );
}

function TestTab({ tplKey }: { tplKey: string }) {
  const [to, setTo] = useState("");
  const sendMut = useMutation({
    mutationFn: () => adminApi.testEmailTemplate(tplKey, to),
    onSuccess: (data) => {
      if (data.ok) {
        toast.success(
          `Enviado (provider ${data.provider}${data.provider_id ? ` · id ${data.provider_id}` : ""})`,
        );
      } else {
        toast.error(data.error ?? "Falló el envío");
      }
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="space-y-3 max-w-md">
      <p className="text-xs text-muted-foreground">
        Envía un mail real al destinatario que pongas. Se loggea en
        <code className="font-mono ml-1">emails_log</code> con el resto. Usa los cambios{" "}
        <strong>guardados</strong> del template (no los del editor). El test ignora el on/off, así
        podés probar un mail apagado.
      </p>
      <div>
        <Label className="text-xs">Enviar a</Label>
        <Input
          type="email"
          value={to}
          onChange={(e) => setTo(e.target.value)}
          placeholder="tu@email.com"
        />
      </div>
      <Button
        onClick={() => sendMut.mutate()}
        disabled={!to || !to.includes("@") || sendMut.isPending}
      >
        {sendMut.isPending ? (
          <>
            <Spinner size="xs" className="mr-1.5" />
            Enviando…
          </>
        ) : (
          <>
            <Send className="h-3.5 w-3.5 mr-1.5" />
            Enviar test
          </>
        )}
      </Button>
    </div>
  );
}
