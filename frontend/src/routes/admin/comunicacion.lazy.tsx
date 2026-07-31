/**
 * comunicacion.lazy.tsx — Módulo de Comunicación del back-office.
 *
 * Una sola pantalla para "qué le decimos al cliente y por dónde": los EVENTOS
 * (fuente única `services/comunicacion/eventos.py`, pedidos al backend — acá no se
 * duplica la lista) y el estado de los dos CANALES (mail + WhatsApp), con las
 * plantillas que hay que dar de alta en Meta y el envío de prueba.
 *
 * WhatsApp es un canal de este módulo, no un menú aparte.
 */
import { createLazyFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Copy, Mail, MessageCircle, Paperclip, Send, PlayCircle, UploadCloud } from "lucide-react";

import { comunicacionApi, type EventoComunicacion } from "@/lib/admin/api/comunicacion";
import { whatsappApi } from "@/lib/admin/api/whatsapp";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { AdminPage } from "@/components/admin/AdminPage";
import { EmailsAdmin } from "@/components/admin/email/EmailsAdmin";
import { Section } from "@/design-system/composites/Section";
import { Chequeos } from "@/design-system/composites/Chequeos";
import { Pill } from "@/design-system/ui/Pill";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
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

function ComunicacionPage() {
  useDocumentTitle("Comunicación · Back Office");

  const q = useQuery({
    queryKey: ["comunicacion", "eventos"],
    queryFn: comunicacionApi.getEventos,
  });

  return (
    <AdminPage
      title="Comunicación"
      description="Qué le avisamos al cliente en cada momento del pedido, y por qué medio sale."
    >
      {q.isLoading && <p className="text-sm text-muted-foreground">Cargando…</p>}
      {q.isError && (
        <p className="text-sm text-destructive">No se pudo cargar el módulo de comunicación.</p>
      )}

      {q.data && (
        <div className="space-y-6">
          <Canales canales={q.data.canales} />
          <Eventos eventos={q.data.eventos} />
          <PlantillasMeta />
          {/* El editor de mails vivía dentro de Settings; se trae acá para que TODA
              la comunicación (los dos canales + los eventos) esté en un solo lugar. */}
          <Section
            title="Plantillas de mail"
            subtitle="El texto de cada mail, su on/off, la prueba de envío y el registro de lo enviado."
          >
            <EmailsAdmin />
          </Section>
        </div>
      )}
    </AdminPage>
  );
}

/* ── Canales ─────────────────────────────────────────────────────────────── */

function Canales({
  canales,
}: {
  canales: NonNullable<Awaited<ReturnType<typeof comunicacionApi.getEventos>>>["canales"];
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Section
        title="Mail"
        icon={Mail}
        subtitle="Proveedor y remitente del canal."
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
        <p className="mt-3 text-xs text-muted-foreground">
          Las plantillas se editan más abajo, en esta misma pantalla.
        </p>
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
        <EnvioDePrueba habilitado={canales.whatsapp.listo} />
      </Section>
    </div>
  );
}

function EnvioDePrueba({ habilitado }: { habilitado: boolean }) {
  const [to, setTo] = useState("");
  const [plantilla, setPlantilla] = useState("pedido_confirmado");

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
          <SelectTrigger className="h-9 w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="pedido_creado">Pedido creado</SelectItem>
            <SelectItem value="pedido_confirmado">Pedido confirmado</SelectItem>
            <SelectItem value="recordatorio_retiro">Recordatorio de retiro</SelectItem>
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

/* ── Eventos ─────────────────────────────────────────────────────────────── */

function Eventos({ eventos }: { eventos: EventoComunicacion[] }) {
  return (
    <Section
      title="Eventos"
      subtitle="Cada momento en que le hablamos al cliente, qué dice y por dónde sale."
    >
      <div className="divide-y">
        {eventos.map((ev) => (
          <EventoFila key={ev.key} ev={ev} />
        ))}
      </div>
    </Section>
  );
}

function EventoFila({ ev }: { ev: EventoComunicacion }) {
  return (
    <div className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">{ev.descripcion}</p>
          <p className="mt-0.5 font-mono text-2xs text-muted-foreground">{ev.key}</p>
        </div>
        <Pill tone={TONO_ESTRATEGIA[ev.estrategia] ?? "neutral"}>{ev.estrategia_label}</Pill>
      </div>

      <p className="mt-1.5 text-xs text-muted-foreground">{ev.estrategia_detalle}</p>

      <div className="mt-2.5 grid gap-2 sm:grid-cols-2">
        <CanalDelEvento
          icon={MessageCircle}
          label="WhatsApp"
          vacio="No sale por WhatsApp"
          contenido={ev.whatsapp?.copy_ejemplo}
          nota={
            ev.whatsapp ? `Plantilla “${ev.whatsapp.meta_name}” (${ev.whatsapp.lang})` : undefined
          }
        />
        <CanalDelEvento
          icon={Mail}
          label="Mail al cliente"
          vacio="No sale por mail"
          contenido={ev.mail_cliente?.asunto ?? undefined}
          nota={
            ev.mail_cliente
              ? ev.mail_cliente.existe
                ? `Plantilla “${ev.mail_cliente.template}”${ev.mail_cliente.activo === false ? " · APAGADA" : ""}`
                : `⚠ La plantilla “${ev.mail_cliente.template}” no existe`
              : undefined
          }
          alerta={
            ev.mail_cliente ? !ev.mail_cliente.existe || ev.mail_cliente.activo === false : false
          }
        />
      </div>

      <div className="mt-2 flex flex-wrap gap-3 text-2xs text-muted-foreground">
        {ev.con_adjunto_ics && (
          <span className="inline-flex items-center gap-1">
            <Paperclip className="h-3 w-3" /> El mail lleva el archivo de calendario
          </span>
        )}
        {ev.mail_admin && (
          <span className="inline-flex items-center gap-1">
            <Mail className="h-3 w-3" /> Además te avisa a vos por mail
          </span>
        )}
      </div>
    </div>
  );
}

function CanalDelEvento({
  icon: Icon,
  label,
  contenido,
  nota,
  vacio,
  alerta,
}: {
  icon: typeof Mail;
  label: string;
  contenido?: string;
  nota?: string;
  vacio: string;
  alerta?: boolean;
}) {
  return (
    <div className="rounded-md border bg-surface-elevated px-2.5 py-2">
      <p className="mb-1 inline-flex items-center gap-1 text-2xs font-medium text-muted-foreground">
        <Icon className="h-3 w-3" /> {label}
      </p>
      {contenido ? (
        <p className="text-xs text-ink">{contenido}</p>
      ) : (
        <p className="text-xs italic text-muted-foreground">{vacio}</p>
      )}
      {nota && (
        <p className={`mt-1 text-2xs ${alerta ? "text-destructive" : "text-muted-foreground"}`}>
          {nota}
        </p>
      )}
    </div>
  );
}

/* ── Plantillas a dar de alta en Meta ────────────────────────────────────── */

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
  NO_CREADA: { tone: "neutral", label: "Sin crear" },
};

function PlantillasMeta() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["whatsapp", "estado"], queryFn: whatsappApi.getEstado });

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
      void qc.invalidateQueries({ queryKey: ["whatsapp", "estado"] });
    },
    onError: (e: Error) => toast.error("No se pudieron crear", { description: e.message }),
  });

  const correr = useMutation({
    mutationFn: () => whatsappApi.correrDevolucion(true),
    onSuccess: (r) => {
      const total = Object.values(r.ventanas).reduce((a, v) => a + v.candidatos, 0);
      toast.success("Simulación lista (no se envió nada)", {
        description: `${total} pedido(s) recibirían el aviso de devolución.`,
      });
    },
    onError: (e: Error) => toast.error("No se pudo simular", { description: e.message }),
  });

  const copiar = (texto: string, nombre: string) => {
    void navigator.clipboard.writeText(texto);
    toast.success(`Copiado el texto de “${nombre}”`);
  };

  return (
    <Section
      title="Plantillas en Meta"
      subtitle="Se dan de alta solas con el botón. Meta las revisa antes de aprobarlas."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => correr.mutate()}
            disabled={correr.isPending}
          >
            <PlayCircle className="mr-1 h-3.5 w-3.5" />
            {correr.isPending ? "Simulando…" : "Simular avisos de devolución"}
          </Button>
          <Button
            size="sm"
            onClick={() => sincronizar.mutate()}
            disabled={sincronizar.isPending || !q.data?.gestion_plantillas.disponible}
          >
            <UploadCloud className="mr-1 h-3.5 w-3.5" />
            {sincronizar.isPending ? "Creando…" : "Crear las que falten"}
          </Button>
        </div>
      }
    >
      {q.data && !q.data.gestion_plantillas.disponible && (
        <p className="mb-3 rounded-md bg-muted px-2 py-1.5 text-xs text-muted-foreground">
          Para darlas de alta automáticamente falta configurar el canal
          {q.data.gestion_plantillas.motivo ? ` (${q.data.gestion_plantillas.motivo})` : ""}.
          Mientras tanto podés copiar cada texto y pegarlo a mano en el WhatsApp Manager.
        </p>
      )}
      {q.isLoading && <p className="text-sm text-muted-foreground">Cargando…</p>}
      {q.data && (
        <div className="space-y-2">
          {q.data.plantillas.map((p) => (
            <div key={p.key} className="rounded-md border px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <code className="text-xs font-medium">{p.meta_name}</code>
                <div className="flex items-center gap-2">
                  {p.estado_meta && (
                    <Pill tone={ESTADO_META[p.estado_meta]?.tone ?? "neutral"} size="compact">
                      {ESTADO_META[p.estado_meta]?.label ?? p.estado_meta}
                    </Pill>
                  )}
                  <Pill tone="neutral" size="compact">
                    {p.lang}
                  </Pill>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => copiar(p.copy_ejemplo, p.meta_name)}
                  >
                    <Copy className="mr-1 h-3.5 w-3.5" /> Copiar texto
                  </Button>
                </div>
              </div>
              <p className="mt-1 text-xs text-ink">{p.copy_ejemplo}</p>
              <p className="mt-1 text-2xs text-muted-foreground">
                Valores de ejemplo, en orden: {p.parametros.join(" · ")}
              </p>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}
