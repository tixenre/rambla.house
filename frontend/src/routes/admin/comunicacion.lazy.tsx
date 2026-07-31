/**
 * comunicacion.lazy.tsx — Módulo de Comunicación del back-office.
 *
 * Una tarjeta por EVENTO, y adentro TODO lo que hace falta para comunicarlo: el
 * texto que sale por cada canal (la plantilla de WhatsApp con su estado en Meta y
 * la de mail, editable), a quién le llega, y las perillas de ese aviso (horario,
 * antelación, destinatarios internos). Criterio del dueño: la configuración vive
 * en el mensaje que corresponde — no los eventos por un lado, las plantillas por
 * otro y el recordatorio de retiro por otro.
 *
 * La lista de eventos y sus opciones NO se duplican acá: las pide al backend
 * (`services/comunicacion/eventos.py` + `opciones.py`, fuente única).
 */
import { createLazyFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Copy,
  Mail,
  MessageCircle,
  Paperclip,
  PlayCircle,
  Send,
  SlidersHorizontal,
  UploadCloud,
} from "lucide-react";

import {
  comunicacionApi,
  type EstadoCanales,
  type EventoComunicacion,
  type OpcionEvento,
  type OtroMail,
  type WhatsAppDeEvento,
} from "@/lib/admin/api/comunicacion";
import { whatsappApi } from "@/lib/admin/api/whatsapp";
import { adminApi } from "@/lib/admin/api";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { AdminPage } from "@/components/admin/AdminPage";
import { EmailsLog } from "@/components/admin/email/EmailsLog";
import { MailTemplateRow, TemplateEditorModal } from "@/components/admin/email/EmailTemplateEditor";
import { Section } from "@/design-system/composites/Section";
import { Chequeos } from "@/design-system/composites/Chequeos";
import { Pill } from "@/design-system/ui/Pill";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Switch } from "@/design-system/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/design-system/ui/select";

export const Route = createLazyFileRoute("/admin/comunicacion")({
  component: ComunicacionPage,
});

/** Color del pill según por dónde sale el evento. */
const TONO_ESTRATEGIA = {
  fallback: "info",
  ambos: "success",
  solo_mail: "neutral",
  solo_whatsapp: "warning",
} as const;

/** Cómo se ve cada estado de aprobación de Meta. */
const ESTADO_META: Record<
  string,
  { tone: "success" | "warning" | "danger" | "neutral"; label: string }
> = {
  APPROVED: { tone: "success", label: "Aprobada" },
  PENDING: { tone: "warning", label: "En revisión" },
  REJECTED: { tone: "danger", label: "Rechazada" },
  PAUSED: { tone: "warning", label: "Pausada" },
  DISABLED: { tone: "danger", label: "Deshabilitada" },
  NO_CREADA: { tone: "neutral", label: "Sin crear en Meta" },
};

/** De la key del evento a la ventana del barrido de devolución (para simularla). */
const VENTANA_DE_EVENTO: Record<string, string> = {
  recordatorio_devolucion_d1: "d1",
  recordatorio_devolucion_d0: "d0",
  recordatorio_devolucion_vencido: "vencido",
};

function ComunicacionPage() {
  useDocumentTitle("Comunicación · Back Office");
  const [editando, setEditando] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["comunicacion", "eventos"],
    queryFn: comunicacionApi.getEventos,
  });

  return (
    <AdminPage
      title="Comunicación"
      description="Qué le avisamos al cliente en cada momento del pedido, con qué texto y por qué medio sale."
    >
      {q.isLoading && <p className="text-sm text-muted-foreground">Cargando…</p>}
      {q.isError && (
        <p className="text-sm text-destructive">No se pudo cargar el módulo de comunicación.</p>
      )}

      {q.data && (
        <div className="space-y-6">
          <Canales canales={q.data.canales} eventos={q.data.eventos} />

          {q.data.eventos.map((ev) => (
            <EventoCard key={ev.key} ev={ev} onEditarMail={setEditando} />
          ))}

          <OtrosMails items={q.data.otros_mails} onEditar={setEditando} />

          <Section
            title="Registro de envíos"
            subtitle="Qué mail salió, a quién y cuál falló (con el error)."
          >
            <EmailsLog />
          </Section>
        </div>
      )}

      {editando && (
        <TemplateEditorModal key={editando} tplKey={editando} onClose={() => setEditando(null)} />
      )}
    </AdminPage>
  );
}

/* ── Canales ─────────────────────────────────────────────────────────────── */

function Canales({ canales, eventos }: { canales: EstadoCanales; eventos: EventoComunicacion[] }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Section
        title="Mail"
        icon={Mail}
        subtitle="Proveedor y remitente del canal. El texto de cada mail se edita en su evento."
        actions={
          <Pill tone={canales.mail.activo ? "success" : "neutral"}>
            {canales.mail.activo ? "Activo" : "Modo prueba"}
          </Pill>
        }
      >
        <dl className="space-y-1 text-xs text-muted-foreground">
          <div className="flex gap-2">
            <dt className="w-20 shrink-0">Proveedor</dt>
            <dd className="text-ink">{canales.mail.provider}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-20 shrink-0">Remitente</dt>
            <dd className="break-all">{canales.mail.from_addr}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-20 shrink-0">Avisos a</dt>
            <dd className="break-all">{canales.mail.admin_to || "—"}</dd>
          </div>
        </dl>
      </Section>

      <Section
        title="WhatsApp"
        icon={MessageCircle}
        subtitle="Las plantillas las aprueba Meta; el texto no se edita acá."
        actions={
          <Pill tone={canales.whatsapp.listo ? "success" : "warning"}>
            {canales.whatsapp.listo ? "Listo" : "Falta configurar"}
          </Pill>
        }
      >
        <Chequeos items={canales.whatsapp.chequeos} />
        {canales.whatsapp.ambiente !== "produccion" && (
          <p className="mt-3 rounded-md bg-muted px-2 py-1.5 text-xs text-muted-foreground">
            Estás fuera de producción: solo se manda a los números de la lista de prueba.
          </p>
        )}
        <AltaDePlantillas gestion={canales.whatsapp.gestion_plantillas} />
        <EnvioDePrueba habilitado={canales.whatsapp.listo} eventos={eventos} />
      </Section>
    </div>
  );
}

function AltaDePlantillas({
  gestion,
}: {
  gestion: EstadoCanales["whatsapp"]["gestion_plantillas"];
}) {
  const qc = useQueryClient();
  const sincronizar = useMutation({
    mutationFn: whatsappApi.sincronizarPlantillas,
    onSuccess: (r) => {
      if (!r.ok && r.motivo) {
        toast.error("No se pudieron crear", { description: r.motivo });
        return;
      }
      const partes = [
        r.creadas ? `${r.creadas} creada(s)` : null,
        r.ya_existian ? `${r.ya_existian} ya existía(n)` : null,
        r.fallidas ? `${r.fallidas} con error` : null,
      ].filter(Boolean);
      const msg = r.fallidas ? toast.warning : toast.success;
      msg("Alta en Meta", {
        description: `${partes.join(" · ")}. Las nuevas quedan en revisión hasta que Meta las apruebe.`,
      });
      void qc.invalidateQueries({ queryKey: ["comunicacion", "eventos"] });
    },
    onError: (e: Error) => toast.error("No se pudieron crear", { description: e.message }),
  });

  return (
    <div className="mt-4 border-t pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-medium">Plantillas en Meta</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => sincronizar.mutate()}
          disabled={sincronizar.isPending || !gestion.disponible}
        >
          <UploadCloud className="mr-1 h-3.5 w-3.5" />
          {sincronizar.isPending ? "Creando…" : "Crear las que falten"}
        </Button>
      </div>
      <p className="mt-1 text-2xs text-muted-foreground">
        {gestion.disponible
          ? "Da de alta en Meta las plantillas de los eventos que todavía no existan. Meta las revisa antes de aprobarlas."
          : `Para darlas de alta automáticamente falta configurar el canal${gestion.motivo ? ` (${gestion.motivo})` : ""}. Mientras tanto podés copiar el texto de cada evento y pegarlo a mano en el WhatsApp Manager.`}
      </p>
    </div>
  );
}

function EnvioDePrueba({
  habilitado,
  eventos,
}: {
  habilitado: boolean;
  eventos: EventoComunicacion[];
}) {
  // Las plantillas probables salen de los eventos — no una lista aparte que se
  // desactualice cuando se agrega un evento.
  const plantillas = eventos.flatMap((ev) =>
    [ev.whatsapp, ev.whatsapp_admin].filter((p): p is WhatsAppDeEvento => Boolean(p)),
  );
  const [to, setTo] = useState("");
  const [plantilla, setPlantilla] = useState(plantillas[0]?.key ?? "pedido_confirmado");

  const enviar = useMutation({
    mutationFn: () => whatsappApi.enviarPrueba(to.trim(), plantilla),
    onSuccess: (r) => toast.success(`Enviado a ${r.to}`, { description: `Mensaje ${r.wamid}` }),
    onError: (e: Error) => toast.error("No se pudo enviar", { description: e.message }),
  });

  return (
    <div className="mt-4 border-t pt-3">
      <p className="mb-2 text-xs font-medium">Probar el envío</p>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={to}
          onChange={(e) => setTo(e.target.value)}
          placeholder="+5492235550000"
          className="h-9 w-44"
          inputMode="tel"
        />
        <Select value={plantilla} onValueChange={setPlantilla}>
          <SelectTrigger className="h-9 w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {plantillas.map((p) => (
              <SelectItem key={p.key} value={p.key}>
                {p.meta_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          size="sm"
          onClick={() => enviar.mutate()}
          disabled={!habilitado || !to.trim() || enviar.isPending}
        >
          <Send className="mr-1 h-3.5 w-3.5" />
          {enviar.isPending ? "Enviando…" : "Enviar"}
        </Button>
      </div>
      {!habilitado && (
        <p className="mt-2 text-xs text-muted-foreground">
          Se habilita cuando el canal esté configurado y prendido.
        </p>
      )}
    </div>
  );
}

/* ── Un evento, con TODO adentro ─────────────────────────────────────────── */

function EventoCard({
  ev,
  onEditarMail,
}: {
  ev: EventoComunicacion;
  onEditarMail: (tpl: string) => void;
}) {
  const tieneInterno = Boolean(ev.whatsapp_admin || ev.mail_admin);
  const ventana = VENTANA_DE_EVENTO[ev.key];

  return (
    <Section
      title={ev.titulo}
      subtitle={ev.descripcion}
      actions={
        <Pill tone={TONO_ESTRATEGIA[ev.estrategia] ?? "neutral"}>{ev.estrategia_label}</Pill>
      }
    >
      <p className="text-xs text-muted-foreground">{ev.estrategia_detalle}</p>

      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <p className="t-eyebrow">Al cliente</p>
          <BloqueWhatsApp wa={ev.whatsapp} />
          <BloqueMail
            mail={ev.mail_cliente}
            etiqueta="Mail"
            conIcs={ev.con_adjunto_ics}
            onEditar={onEditarMail}
          />
        </div>

        {tieneInterno && (
          <div className="space-y-2">
            <p className="t-eyebrow">Al equipo</p>
            <BloqueWhatsApp wa={ev.whatsapp_admin} />
            <BloqueMail mail={ev.mail_admin} etiqueta="Mail" onEditar={onEditarMail} />
          </div>
        )}
      </div>

      {ev.opciones.length > 0 && (
        <Opciones opciones={ev.opciones} extra={ventana ? <Simular ventana={ventana} /> : null} />
      )}
    </Section>
  );
}

function BloqueWhatsApp({ wa }: { wa: WhatsAppDeEvento | null }) {
  const estado = wa ? (ESTADO_META[wa.estado_meta ?? ""] ?? null) : null;

  return (
    <div className="rounded-md border bg-surface-elevated px-3 py-2.5">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <p className="inline-flex items-center gap-1 text-2xs font-medium text-muted-foreground">
          <MessageCircle className="h-3 w-3" /> WhatsApp
        </p>
        {wa && (
          <div className="flex items-center gap-1.5">
            {estado && (
              <Pill tone={estado.tone} size="compact">
                {estado.label}
              </Pill>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(wa.copy_ejemplo);
                toast.success(`Copiado el texto de “${wa.meta_name}”`);
              }}
            >
              <Copy className="mr-1 h-3.5 w-3.5" /> Copiar
            </Button>
          </div>
        )}
      </div>
      {wa ? (
        <>
          <p className="text-xs text-ink">{wa.copy_ejemplo}</p>
          <p className="mt-1 text-2xs text-muted-foreground">
            Plantilla “{wa.meta_name}” ({wa.lang}) · valores en orden:{" "}
            {wa.parametros.join(" · ") || "ninguno"}
          </p>
        </>
      ) : (
        <p className="text-xs italic text-muted-foreground">No sale por WhatsApp</p>
      )}
    </div>
  );
}

function BloqueMail({
  mail,
  etiqueta,
  conIcs,
  onEditar,
}: {
  mail: EventoComunicacion["mail_cliente"];
  etiqueta: string;
  conIcs?: boolean;
  onEditar: (tpl: string) => void;
}) {
  return (
    <div className="rounded-md border bg-surface-elevated px-3 py-2.5">
      <p className="mb-1.5 inline-flex items-center gap-1 text-2xs font-medium text-muted-foreground">
        <Mail className="h-3 w-3" /> {etiqueta}
      </p>
      {!mail && <p className="text-xs italic text-muted-foreground">No sale por mail</p>}
      {mail && !mail.existe && (
        <p className="text-xs text-destructive">
          ⚠ La plantilla “{mail.template}” no existe en la base: este mail no se puede mandar.
        </p>
      )}
      {mail && mail.existe && (
        <>
          <MailTemplateRow
            tplKey={mail.template}
            asunto={mail.asunto}
            activo={mail.activo}
            onEdit={() => onEditar(mail.template)}
          />
          {conIcs && (
            <p className="mt-1.5 inline-flex items-center gap-1 text-2xs text-muted-foreground">
              <Paperclip className="h-3 w-3" /> Lleva el archivo de calendario (.ics)
            </p>
          )}
        </>
      )}
    </div>
  );
}

/* ── Perillas del evento ─────────────────────────────────────────────────── */

function Opciones({ opciones, extra }: { opciones: OpcionEvento[]; extra?: React.ReactNode }) {
  const qc = useQueryClient();
  const [borrador, setBorrador] = useState<Record<string, string>>({});

  const guardar = useMutation({
    mutationFn: async (cambios: { setting: string; valor: string }[]) => {
      for (const c of cambios) await adminApi.updateSetting(c.setting, c.valor);
    },
    onSuccess: () => {
      setBorrador({});
      toast.success("Guardado");
      void qc.invalidateQueries({ queryKey: ["comunicacion", "eventos"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const valorDe = (o: OpcionEvento) => borrador[o.setting] ?? o.valor;
  const pendientes = opciones
    .filter((o) => o.tipo !== "switch" && borrador[o.setting] !== undefined)
    .filter((o) => borrador[o.setting] !== o.valor)
    .map((o) => ({ setting: o.setting, valor: borrador[o.setting] }));

  return (
    <div className="mt-4 rounded-md border border-dashed px-3 py-3">
      <p className="mb-2.5 inline-flex items-center gap-1 text-2xs font-medium text-muted-foreground">
        <SlidersHorizontal className="h-3 w-3" /> Cuándo y a quién
      </p>

      <div className="space-y-3">
        {opciones.map((o) => (
          <div key={o.setting} className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm text-ink">{o.label}</p>
              {o.ayuda && <p className="mt-0.5 text-xs text-muted-foreground">{o.ayuda}</p>}
              {o.bloqueada_por_env && (
                <p className="mt-0.5 text-2xs text-muted-foreground">
                  Lo fija la variable de entorno{" "}
                  <code className="font-mono">{o.bloqueada_por_env}</code> — para cambiarlo, tocá el
                  ambiente.
                </p>
              )}
            </div>

            {o.bloqueada_por_env ? (
              <span className="shrink-0 rounded-md bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">
                {o.tipo === "switch" ? (valorDe(o) === "1" ? "Encendido" : "Apagado") : valorDe(o)}
              </span>
            ) : o.tipo === "switch" ? (
              <Switch
                checked={valorDe(o) === "1"}
                disabled={guardar.isPending}
                onCheckedChange={(v) =>
                  guardar.mutate([{ setting: o.setting, valor: v ? "1" : "0" }])
                }
                aria-label={o.label}
              />
            ) : (
              <Input
                type={o.tipo === "numero" ? "number" : "text"}
                min={o.minimo ?? undefined}
                max={o.maximo ?? undefined}
                placeholder={o.placeholder || undefined}
                value={valorDe(o)}
                onChange={(e) => setBorrador((b) => ({ ...b, [o.setting]: e.target.value }))}
                className={o.tipo === "numero" ? "h-9 w-24 shrink-0" : "h-9 w-full sm:w-72"}
              />
            )}
          </div>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {pendientes.length > 0 && (
          <Button size="sm" onClick={() => guardar.mutate(pendientes)} disabled={guardar.isPending}>
            {guardar.isPending ? "Guardando…" : "Guardar"}
          </Button>
        )}
        {extra}
      </div>
    </div>
  );
}

/** Corre el barrido de este aviso en seco: lista a quién le llegaría, sin mandar. */
function Simular({ ventana }: { ventana: string }) {
  const correr = useMutation({
    mutationFn: () => whatsappApi.correrDevolucion(true, [ventana]),
    onSuccess: (r) => {
      const total = Object.values(r.ventanas).reduce((a, v) => a + v.candidatos, 0);
      toast.success("Simulación lista (no se envió nada)", {
        description: `${total} pedido(s) recibirían este aviso hoy.`,
      });
    },
    onError: (e: Error) => toast.error("No se pudo simular", { description: e.message }),
  });

  return (
    <Button variant="outline" size="sm" onClick={() => correr.mutate()} disabled={correr.isPending}>
      <PlayCircle className="mr-1 h-3.5 w-3.5" />
      {correr.isPending ? "Simulando…" : "Simular (no envía)"}
    </Button>
  );
}

/* ── Mails que no dispara ningún evento ──────────────────────────────────── */

function OtrosMails({ items, onEditar }: { items: OtroMail[]; onEditar: (tpl: string) => void }) {
  if (items.length === 0) return null;
  return (
    <Section
      title="Mails de Talleres"
      icon={Mail}
      subtitle="Los dispara el módulo de Talleres, no el pedido — por eso están acá y no adentro de un evento."
    >
      <div className="divide-y">
        {items.map((m) => (
          <div key={m.template} className="py-2.5 first:pt-0 last:pb-0">
            <MailTemplateRow
              tplKey={m.template}
              asunto={m.asunto}
              activo={m.activo}
              onEdit={() => onEditar(m.template)}
            />
          </div>
        ))}
      </div>
    </Section>
  );
}
