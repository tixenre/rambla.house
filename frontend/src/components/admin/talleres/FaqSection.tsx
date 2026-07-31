import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";

import type { FaqItem, TallerConcepto } from "@/lib/admin/api/types";
import { talleresAdminApi } from "@/lib/admin/api/talleres";
import { Button } from "@/design-system/ui/button";
import { IconButton } from "@/design-system/ui/icon-button";
import { Input } from "@/design-system/ui/input";
import { Textarea } from "@/design-system/ui/textarea";
import { Spinner } from "@/design-system/ui/spinner";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/design-system/ui/select";
import { updateConceptoInCache } from "./cache";

// F4c: preguntas sugeridas para que el FAQ quede completo y profesional — el
// dueño las agrega de a una y completa la respuesta. Ninguna es obligatoria.
const PREGUNTAS_SUGERIDAS = [
  "¿Necesito experiencia previa?",
  "¿Los equipos están incluidos? ¿Qué tengo que llevar?",
  "¿Cómo reservo mi lugar?",
  "¿Qué formas de pago tienen? ¿Puedo pagar en cuotas?",
  "¿Qué pasa si no puedo asistir o me arrepiento?",
  "¿Qué pasa si falto a una clase?",
  "¿Entregan certificado?",
  "¿Dónde se cursa y cómo llego?",
  "¿Hay lista de espera si no hay cupos?",
  "¿Emiten factura?",
];

export function FaqSection({ concepto }: { concepto: TallerConcepto }) {
  const qc = useQueryClient();
  const [faqs, setFaqs] = useState<FaqItem[]>(concepto.faqs);

  useEffect(() => {
    setFaqs(concepto.faqs);
  }, [concepto.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const mut = useMutation({
    mutationFn: (body: { faqs: FaqItem[] }) => talleresAdminApi.updateConcepto(concepto.id, body),
    onSuccess: (updated) => {
      toast.success("FAQ guardada");
      updateConceptoInCache(qc, updated);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const disponibles = PREGUNTAS_SUGERIDAS.filter((p) => !faqs.some((f) => f.pregunta === p));

  function agregarSugerida(pregunta: string) {
    setFaqs((f) => [...f, { pregunta, respuesta: "" }]);
  }

  function agregarVacia() {
    setFaqs((f) => [...f, { pregunta: "", respuesta: "" }]);
  }

  function actualizar(idx: number, patch: Partial<FaqItem>) {
    setFaqs((f) => f.map((item, i) => (i === idx ? { ...item, ...patch } : item)));
  }

  function quitar(idx: number) {
    setFaqs((f) => f.filter((_, i) => i !== idx));
  }

  return (
    <div className="flex flex-col gap-4">
      {faqs.length === 0 && (
        <p className="text-sm text-muted-foreground italic">
          Sin preguntas todavía — agregá una sugerida o escribí la tuya.
        </p>
      )}
      {faqs.map((faq, idx) => (
        <div
          key={idx}
          className="flex flex-col gap-2 rounded-xl border border-border/50 bg-muted/10 p-3"
        >
          <div className="flex items-center gap-2">
            <Input
              value={faq.pregunta}
              onChange={(e) => actualizar(idx, { pregunta: e.target.value })}
              placeholder="Pregunta"
              className="flex-1"
            />
            <IconButton
              aria-label="Quitar pregunta"
              size="sm"
              onClick={() => quitar(idx)}
              className="text-muted-foreground hover:text-destructive shrink-0"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </IconButton>
          </div>
          <Textarea
            value={faq.respuesta}
            onChange={(e) => actualizar(idx, { respuesta: e.target.value })}
            placeholder="Respuesta"
            rows={2}
            className="resize-y"
          />
        </div>
      ))}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        {disponibles.length > 0 && (
          <Select onValueChange={agregarSugerida}>
            <SelectTrigger className="w-[260px]">
              <SelectValue placeholder="Agregar pregunta sugerida…" />
            </SelectTrigger>
            <SelectContent>
              {disponibles.map((p) => (
                <SelectItem key={p} value={p}>
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <Button variant="outline" size="sm" onClick={agregarVacia} className="gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          Pregunta propia
        </Button>
        <Button
          onClick={() => mut.mutate({ faqs })}
          disabled={mut.isPending}
          size="sm"
          className="gap-2 ml-auto"
        >
          {mut.isPending ? <Spinner size="sm" /> : <Save className="h-4 w-4" />}
          Guardar FAQ
        </Button>
      </div>
    </div>
  );
}
