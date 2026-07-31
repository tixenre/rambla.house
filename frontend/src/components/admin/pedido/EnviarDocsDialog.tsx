/**
 * EnviarDocsDialog — Modal para enviar documentos del pedido por email.
 * Extraído de PedidoPage.tsx para ser reutilizado en el editor v2.
 */

import { useEffect, useState } from "react";
import { FileText, FileSignature, Truck, ClipboardList, Eye } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Label } from "@/design-system/ui/label";
import { Textarea } from "@/design-system/ui/textarea";
import { Checkbox } from "@/design-system/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "@/design-system/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/design-system/ui/select";
import { adminApi } from "@/lib/admin/api";

// Plantillas de mail elegibles desde el modal. `simple` (sentinela; Radix no
// admite value="") = el cuerpo genérico de siempre; el resto son los mails ricos
// al cliente (deben estar en la whitelist `PLANTILLAS_ENVIO_CLIENTE` del backend).
const PLANTILLA_SIMPLE = "simple";
// eslint-disable-next-line react-refresh/only-export-components -- constante de datos, coexiste con el componente a propósito
export const PLANTILLAS_MAIL: { value: string; label: string }[] = [
  { value: PLANTILLA_SIMPLE, label: "Mensaje simple (solo documentos)" },
  { value: "pedido_confirmado_cliente", label: "Confirmación de pedido" },
  { value: "pedido_creado_cliente", label: "Recibimos tu pedido" },
];

// eslint-disable-next-line react-refresh/only-export-components -- constante de datos (no componente); coexiste con EnviarDocsDialog intencionalmente
export const DOCS_PEDIDO: {
  kind: "remito" | "detalle-seguro" | "contrato" | "checklist-retiro";
  label: string;
  Icon: LucideIcon;
}[] = [
  { kind: "contrato", label: "Contrato", Icon: FileSignature },
  { kind: "remito", label: "Remito", Icon: FileText },
  { kind: "detalle-seguro", label: "Detalle de seguro", Icon: Truck },
  { kind: "checklist-retiro", label: "Checklist de retiro", Icon: ClipboardList },
];

export function EnviarDocsDialog({
  pedidoId,
  clienteEmail,
  open,
  onOpenChange,
}: {
  pedidoId: number;
  clienteEmail: string;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [seleccion, setSeleccion] = useState<Record<string, boolean>>({ remito: true });
  const [to, setTo] = useState(clienteEmail);
  const [mensaje, setMensaje] = useState("");
  const [plantilla, setPlantilla] = useState(PLANTILLA_SIMPLE);
  const [preview, setPreview] = useState<{ subject: string; html: string } | null>(null);

  // Re-sincroniza el destinatario al abrir (por si cambió el cliente) y limpia
  // el preview viejo.
  useEffect(() => {
    if (open) {
      setTo(clienteEmail);
      setPreview(null);
    }
  }, [open, clienteEmail]);

  const esPlantillaRica = plantilla !== PLANTILLA_SIMPLE;

  const docsElegidos = () => DOCS_PEDIDO.filter((d) => seleccion[d.kind]).map((d) => d.kind);

  const enviarMut = useMutation({
    mutationFn: () =>
      adminApi.enviarDocumentos(pedidoId, {
        docs: docsElegidos(),
        to: to.trim() || undefined,
        mensaje: mensaje.trim() || undefined,
        template: esPlantillaRica ? plantilla : undefined,
      }),
    onSuccess: (r) => {
      toast.success(`Mail enviado a ${r.to}`);
      onOpenChange(false);
      setMensaje("");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  // Preview con los datos reales del pedido (no envía). Se genera a pedido para
  // reflejar la plantilla + nota + adjuntos elegidos en ese momento.
  const previewMut = useMutation({
    mutationFn: () =>
      adminApi.previewMailPedido(pedidoId, {
        docs: docsElegidos(),
        mensaje: mensaje.trim() || undefined,
        template: esPlantillaRica ? plantilla : undefined,
      }),
    onSuccess: (d) => setPreview({ subject: d.subject, html: d.html }),
    onError: (e: Error) => toast.error(e.message),
  });

  const algunoElegido = DOCS_PEDIDO.some((d) => seleccion[d.kind]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Enviar documentos por mail</DialogTitle>
          <DialogDescription>
            {esPlantillaRica
              ? "Se manda el mail con todos los datos de la reserva + los documentos adjuntos en PDF."
              : "Se mandan adjuntos en PDF al email del cliente. Elegí qué documentos incluir."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="enviar-docs-plantilla">Plantilla del mail</Label>
            <Select
              value={plantilla}
              onValueChange={(v) => {
                setPlantilla(v);
                setPreview(null);
              }}
            >
              <SelectTrigger id="enviar-docs-plantilla">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PLANTILLAS_MAIL.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Documentos adjuntos</Label>
            {DOCS_PEDIDO.map((d) => (
              <label key={d.kind} className="flex items-center gap-2 text-sm text-ink">
                <Checkbox
                  checked={!!seleccion[d.kind]}
                  onCheckedChange={(v) =>
                    setSeleccion((prev) => ({ ...prev, [d.kind]: v === true }))
                  }
                />
                <d.Icon className="h-4 w-4 text-muted-foreground" />
                {d.label}
              </label>
            ))}
          </div>

          <div className="space-y-1">
            <Label htmlFor="enviar-docs-to">Para</Label>
            <Input
              id="enviar-docs-to"
              type="email"
              value={to}
              placeholder="email del cliente"
              onChange={(e) => setTo(e.target.value)}
            />
          </div>

          <div className="space-y-1">
            <Label htmlFor="enviar-docs-msg">
              {esPlantillaRica ? "Nota para el cliente (opcional)" : "Mensaje (opcional)"}
            </Label>
            <Textarea
              id="enviar-docs-msg"
              value={mensaje}
              placeholder={
                esPlantillaRica
                  ? "Una nota que aparece destacada arriba del mail…"
                  : "Una nota para el cliente…"
              }
              rows={3}
              onChange={(e) => setMensaje(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Button
              type="button"
              variant="outline"
              className="h-11 w-full"
              onClick={() => previewMut.mutate()}
              disabled={!algunoElegido || previewMut.isPending}
            >
              <Eye className="h-4 w-4 mr-1" />
              {previewMut.isPending
                ? "Generando…"
                : preview
                  ? "Actualizar vista previa"
                  : "Ver vista previa"}
            </Button>

            {preview && (
              <div className="space-y-1 rounded-md border hairline bg-muted/20 p-2">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">Asunto</div>
                <div className="break-words text-sm font-medium text-ink">{preview.subject}</div>
                <iframe
                  srcDoc={preview.html}
                  sandbox=""
                  title="Vista previa del mail"
                  className="mt-1 h-64 w-full rounded border hairline bg-white"
                />
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button
            onClick={() => enviarMut.mutate()}
            disabled={!algunoElegido || !to.trim() || enviarMut.isPending}
          >
            {enviarMut.isPending ? "Enviando…" : "Enviar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
