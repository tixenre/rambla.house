/**
 * Editor de una plantilla de mail (Editar / Preview / Test) + la fila con su on/off.
 *
 * Se abre desde el evento que la usa en /admin/comunicacion — la configuración de
 * un mail vive en el evento que lo dispara, no en una pantalla de plantillas suelta.
 * Los mails que no dispara ningún evento (los de Talleres) usan la misma fila.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Send, Eye, Pencil } from "lucide-react";

import { Spinner } from "@/design-system/ui/spinner";
import { Button } from "@/design-system/ui/button";
import { ModalBackdrop } from "@/design-system/ui/modal-backdrop";
import { Input } from "@/design-system/ui/input";
import { Textarea } from "@/design-system/ui/textarea";
import { Label } from "@/design-system/ui/label";
import { Switch } from "@/design-system/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/design-system/ui/tabs";

import { adminApi, type EmailTemplate, type EmailTemplateInput } from "@/lib/admin/api";
import { AVAILABLE_VARS, TEMPLATE_META } from "./templateMeta";

/** Fila de un mail: on/off + acceso al editor. */
export function MailTemplateRow({
  tplKey,
  asunto,
  activo,
  onEdit,
}: {
  tplKey: string;
  asunto: string | null;
  activo: boolean | null;
  onEdit: () => void;
}) {
  const qc = useQueryClient();
  const meta = TEMPLATE_META[tplKey];
  const toggleMut = useMutation({
    mutationFn: (enabled: boolean) => adminApi.setEmailTemplateEnabled(tplKey, enabled),
    onSuccess: (data) => {
      void qc.invalidateQueries({ queryKey: ["admin", "email-templates"] });
      void qc.invalidateQueries({ queryKey: ["comunicacion", "eventos"] });
      toast.success(data.enabled ? "Mail activado" : "Mail apagado");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="flex items-center gap-3">
      <Switch
        checked={activo ?? false}
        disabled={toggleMut.isPending || activo === null}
        onCheckedChange={(v) => toggleMut.mutate(v)}
        aria-label={activo ? "Apagar este mail" : "Activar este mail"}
      />
      <button type="button" onClick={onEdit} className="min-w-0 flex-1 text-left">
        <div className="truncate text-sm text-ink">{meta?.label ?? tplKey}</div>
        <div className="mt-0.5 truncate text-xs text-muted-foreground">{asunto ?? "—"}</div>
      </button>
      <Button variant="ghost" size="sm" onClick={onEdit}>
        <Pencil className="mr-1 h-3.5 w-3.5" /> Editar
      </Button>
    </div>
  );
}

// ── Editor (Editar / Preview / Test) ─────────────────────────────────────────

export function TemplateEditorModal({ tplKey, onClose }: { tplKey: string; onClose: () => void }) {
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
      void qc.invalidateQueries({ queryKey: ["admin", "email-templates"] });
      void qc.invalidateQueries({ queryKey: ["comunicacion", "eventos"] });
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
