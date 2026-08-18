import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { toast } from "sonner";

import { talleresAdminApi } from "@/lib/admin/api/talleres";
import type { TallerConcepto } from "@/lib/admin/api/types";
import { Button } from "@/design-system/ui/button";
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

// Sentinel de Radix Select (no admite value="" para una opción) — se mapea
// a `null` (sin pareja) al leer/escribir el form.
const SIN_HERMANO = "__sin_hermano__";

export function ContenidoSection({ concepto }: { concepto: TallerConcepto }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    nombre: concepto.nombre,
    subtitulo: concepto.subtitulo,
    descripcion: concepto.descripcion,
    resumen: concepto.resumen ?? "",
    publico_objetivo: concepto.publico_objetivo,
    notif_email: concepto.notif_email ?? "",
    terminos: concepto.terminos ?? "",
    beneficios: concepto.beneficios ?? "",
    pregunta_experiencia: concepto.pregunta_experiencia ?? "",
    mensaje_confirmacion: concepto.mensaje_confirmacion ?? "",
    video_url: concepto.video_url ?? "",
    taller_hermano_id: concepto.taller_hermano_id,
    taller_hermano_titulo: concepto.taller_hermano_titulo ?? "",
  });

  useEffect(() => {
    setForm({
      nombre: concepto.nombre,
      subtitulo: concepto.subtitulo,
      descripcion: concepto.descripcion,
      resumen: concepto.resumen ?? "",
      publico_objetivo: concepto.publico_objetivo,
      notif_email: concepto.notif_email ?? "",
      terminos: concepto.terminos ?? "",
      beneficios: concepto.beneficios ?? "",
      pregunta_experiencia: concepto.pregunta_experiencia ?? "",
      mensaje_confirmacion: concepto.mensaje_confirmacion ?? "",
      video_url: concepto.video_url ?? "",
      taller_hermano_id: concepto.taller_hermano_id,
      taller_hermano_titulo: concepto.taller_hermano_titulo ?? "",
    });
  }, [concepto.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Mismo queryKey que la lista admin (talleres.index.lazy.tsx) — comparte
  // caché, no dispara un fetch nuevo (la página ya la tiene cargada).
  const { data: todosLosTalleres = [] } = useQuery({
    queryKey: ["admin", "talleres"],
    queryFn: talleresAdminApi.list,
  });
  const opcionesHermano = todosLosTalleres.filter((t) => t.id !== concepto.id);

  const mut = useMutation({
    mutationFn: (body: object) => talleresAdminApi.updateConcepto(concepto.id, body),
    onSuccess: (updated) => {
      toast.success("Guardado");
      updateConceptoInCache(qc, updated);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  function handleSave() {
    const body: Record<string, unknown> = {
      nombre: form.nombre,
      subtitulo: form.subtitulo,
      descripcion: form.descripcion,
      resumen: form.resumen,
      publico_objetivo: form.publico_objetivo,
      notif_email: form.notif_email,
      terminos: form.terminos,
      beneficios: form.beneficios,
      pregunta_experiencia: form.pregunta_experiencia,
      mensaje_confirmacion: form.mensaje_confirmacion,
      // Siempre presente (incluso null) — el backend distingue "sacale la
      // pareja" de "no lo mandaron" por si la CLAVE vino en el JSON, no por
      // si el valor es None (ver admin_update_concepto).
      taller_hermano_id: form.taller_hermano_id,
      taller_hermano_titulo: form.taller_hermano_titulo,
    };
    // F4a: solo se manda si CAMBIÓ — el backend, al recibirlo, descarga y
    // guarda el poster de YouTube; mandarlo sin cambios en cada guardado
    // re-descargaría el poster de nuevo por nada.
    if (form.video_url !== (concepto.video_url ?? "")) {
      body.video_url = form.video_url;
    }
    mut.mutate(body);
  }

  const field = (
    label: string,
    key: keyof typeof form,
    opts?: { rows?: number; hint?: string; type?: string },
  ) => (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
        {label}
      </label>
      {opts?.hint && <p className="text-xs text-muted-foreground/70 -mt-1">{opts.hint}</p>}
      {(opts?.rows ?? 1) === 1 ? (
        <Input
          type={opts?.type ?? "text"}
          value={form[key] as string}
          onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
        />
      ) : (
        <Textarea
          rows={opts?.rows}
          value={form[key] as string}
          onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
          className="resize-y"
        />
      )}
    </div>
  );

  return (
    <div className="flex flex-col gap-5">
      <div className="grid sm:grid-cols-2 gap-4">
        {field("Nombre", "nombre")}
        {field("Subtítulo", "subtitulo")}
      </div>
      {field("Descripción", "descripcion", { rows: 4 })}
      {field("¿Para quiénes?", "publico_objetivo", {
        rows: 3,
        hint: "Texto que aparece en el box 'Orientado a'",
      })}
      {field("Resumen (listado)", "resumen", {
        rows: 2,
        hint: "Aparece en la tarjeta de /escuelas — mezcla a quién está orientado + de qué trata, en 1-2 líneas. Vacío → se usa la descripción completa truncada.",
      })}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
          Video hero (YouTube)
        </label>
        <p className="text-xs text-muted-foreground/70 -mt-1">
          Pegá el link del video — se muestra arriba de todo en la landing. Vacío → hero de texto
          (sin video).
        </p>
        <div className="flex items-start gap-3">
          <Input
            value={form.video_url}
            onChange={(e) => setForm((f) => ({ ...f, video_url: e.target.value }))}
            placeholder="https://www.youtube.com/watch?v=..."
            className="flex-1"
          />
          {concepto.video_poster_url && form.video_url === concepto.video_url && (
            <img
              src={concepto.video_poster_url}
              alt=""
              className="h-12 w-20 rounded-md object-cover border border-border/40 shrink-0"
            />
          )}
        </div>
      </div>
      {field("Email del instructor/a", "notif_email", {
        type: "email",
        hint: "Recibe las notificaciones de inscripción.",
      })}
      {field("Beneficios", "beneficios", {
        rows: 2,
        hint: "Ej: 15% off en alquiler de equipos y estudio para alumnos.",
      })}
      {field("Términos y condiciones del taller", "terminos", {
        rows: 5,
        hint: "Vacío → el form linkea a los términos generales de la web.",
      })}
      {field("Pregunta del formulario", "pregunta_experiencia", {
        hint: "Vacío → '¿Tenés algún tipo de experiencia en arte?' (default).",
      })}
      {field("Mensaje de confirmación", "mensaje_confirmacion", {
        rows: 2,
        hint: "Se muestra al inscribirse (ej: link al grupo, qué llevar).",
      })}
      <div className="flex flex-col gap-3 rounded-lg border hairline p-4">
        <div>
          <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
            Taller hermano
          </label>
          <p className="text-xs text-muted-foreground/70 mt-0.5">
            Dos talleres lanzados juntos, un solo link — el Hero de los dos muestra un selector
            hacia el otro. No hace falta configurarlo en los dos lados.
          </p>
        </div>
        <Select
          value={form.taller_hermano_id === null ? SIN_HERMANO : String(form.taller_hermano_id)}
          onValueChange={(v) =>
            setForm((f) => ({ ...f, taller_hermano_id: v === SIN_HERMANO ? null : Number(v) }))
          }
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={SIN_HERMANO}>— Sin pareja —</SelectItem>
            {opcionesHermano.map((t) => (
              <SelectItem key={t.id} value={String(t.id)}>
                {t.nombre}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {form.taller_hermano_id !== null && (
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
              Título de campaña (opcional)
            </label>
            <p className="text-xs text-muted-foreground/70 -mt-1">
              Ej: "Dos talleres, un solo viaje". Vacío → el header muestra solo los 2 nombres.
            </p>
            <Input
              value={form.taller_hermano_titulo}
              onChange={(e) => setForm((f) => ({ ...f, taller_hermano_titulo: e.target.value }))}
            />
          </div>
        )}
      </div>
      <div className="flex justify-end pt-2">
        <Button onClick={handleSave} disabled={mut.isPending} className="gap-2">
          {mut.isPending ? <Spinner size="sm" /> : <Save className="h-4 w-4" />}
          Guardar cambios
        </Button>
      </div>
    </div>
  );
}
