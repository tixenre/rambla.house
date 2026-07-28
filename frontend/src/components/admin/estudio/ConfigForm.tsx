import { useFieldArray, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation } from "@tanstack/react-query";
import { Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/design-system/ui/button";
import { IconButton } from "@/design-system/ui/icon-button";
import { Input } from "@/design-system/ui/input";
import { Textarea } from "@/design-system/ui/textarea";
import { Spinner } from "@/design-system/ui/spinner";
import { estudioAdminApi, type EstudioConfig } from "@/lib/admin/api";
import { Field, Section } from "./shared";

// El value puede estar vacío: features con value en blanco se ocultan en
// público (filtro en /estudio.tsx) y quedan listadas en admin para que el
// dueño las complete cuando quiera. Si forzamos `min(1)` acá, el submit
// silenciosamente falla validación (button "Guardar" no dispara nada).
const featureSchema = z.object({
  label: z.string().min(1, "Requerido"),
  value: z.string(),
});

// FAQ y testimonios: schemas permisivos. Si el dueño hace "Añadir" y deja la
// fila vacía sin completar, NO bloqueamos el guardado — las filas totalmente
// vacías se filtran en el handler de submit (`stripEmpty`). El filtro defensivo
// también vive en `/estudio.tsx` (front público) por si llegara algo basura.
const faqSchema = z.object({
  q: z.string(),
  a: z.string(),
});

const testimonioSchema = z.object({
  autor: z.string(),
  texto: z.string(),
});

const schema = z.object({
  nombre: z.string().min(1, "Requerido"),
  tagline: z.string(),
  descripcion: z.string(),
  precio_hora: z.coerce.number().int().min(0),
  precio_pintura_reciente: z.coerce.number().int().min(0),
  min_horas: z.coerce.number().int().min(1),
  open_hour: z.coerce.number().int().min(0).max(23),
  close_hour: z.coerce.number().int().min(1).max(24),
  buffer_horas: z.coerce.number().int().min(0),
  anticipacion_min_horas: z.coerce.number().int().min(0),
  anticipacion_pintura_horas: z.coerce.number().int().min(0),
  features: z.array(featureSchema),
  faq: z.array(faqSchema),
  direccion: z.string(),
  como_llegar: z.string(),
  mapa_url: z.string(),
  testimonios: z.array(testimonioSchema),
});

type FormValues = z.infer<typeof schema>;

function configToForm(c: EstudioConfig): FormValues {
  return {
    nombre: c.nombre,
    tagline: c.tagline,
    descripcion: c.descripcion,
    precio_hora: c.precio_hora,
    precio_pintura_reciente: c.precio_pintura_reciente,
    min_horas: c.min_horas,
    open_hour: c.open_hour,
    close_hour: c.close_hour,
    buffer_horas: c.buffer_horas,
    anticipacion_min_horas: c.anticipacion_min_horas,
    anticipacion_pintura_horas: c.anticipacion_pintura_horas,
    features: c.features ?? [],
    faq: c.faq ?? [],
    direccion: c.direccion,
    como_llegar: c.como_llegar,
    mapa_url: c.mapa_url,
    testimonios: c.testimonios ?? [],
  };
}

export function ConfigForm({ config, onSaved }: { config: EstudioConfig; onSaved: () => void }) {
  const {
    register,
    handleSubmit,
    control,
    formState: { errors, isDirty },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: configToForm(config),
  });

  const featuresArr = useFieldArray({ control, name: "features" });
  const faqArr = useFieldArray({ control, name: "faq" });
  const testimoniosArr = useFieldArray({ control, name: "testimonios" });

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      // Filtramos filas totalmente vacías antes de guardar — si el dueño hizo
      // "Añadir" y dejó la fila sin completar (caso típico cuando se arrepiente
      // o se distrae), no la persistimos. Features tienen seed canónico con
      // value vacío a propósito (admin las muestra; público las filtra), así
      // que ahí solo dropeamos las que tienen el label vacío también.
      const faqLimpio = values.faq.filter((f) => f.q.trim() || f.a.trim());
      const testimoniosLimpio = values.testimonios.filter((t) => t.autor.trim() || t.texto.trim());
      const featuresLimpio = values.features.filter((f) => f.label.trim());
      return estudioAdminApi.update({
        ...values,
        features_json: JSON.stringify(featuresLimpio),
        faq_json: JSON.stringify(faqLimpio),
        testimonios_json: JSON.stringify(testimoniosLimpio),
      });
    },
    onSuccess: () => {
      toast.success("Estudio guardado");
      onSaved();
    },
    onError: (e) => toast.error("Error guardando", { description: (e as Error).message }),
  });

  // Si la validación falla, react-hook-form NO llama al success-handler — el
  // submit "no hace nada". Surfaciamos un toast para que no se sienta roto.
  const onInvalid = (errs: typeof errors) => {
    const fields = Object.keys(errs).join(", ");
    toast.error("Revisá los campos marcados", {
      description: fields ? `Campos con error: ${fields}` : undefined,
    });
  };

  return (
    <form onSubmit={handleSubmit((v) => mutation.mutate(v), onInvalid)} className="space-y-8">
      {/* ── Datos generales ── */}
      <Section title="Datos generales">
        <Field label="Nombre" error={errors.nombre?.message}>
          <Input {...register("nombre")} placeholder="El Estudio" />
        </Field>
        <Field label="Tagline" error={errors.tagline?.message}>
          <Input {...register("tagline")} placeholder="Foto y video en Mar del Plata" />
        </Field>
        <Field label="Descripción" error={errors.descripcion?.message}>
          <Textarea {...register("descripcion")} rows={3} />
        </Field>
      </Section>

      {/* ── Ubicación ── */}
      <Section title="Ubicación">
        <p className="-mt-1 text-xs text-muted-foreground">
          Si pegás un link de Google Maps, mostramos un mapa en la página pública. Sin link y sin
          dirección, el bloque entero se oculta.
        </p>
        <Field
          label="Mapa de Google (link o código embed)"
          error={errors.mapa_url?.message}
          hint='Pegá el link que da "Compartir" en la app de Google Maps (ej. https://maps.app.goo.gl/...) o el código iframe de "Compartir → Insertar mapa". Dejalo vacío para no mostrar mapa.'
        >
          <Textarea {...register("mapa_url")} rows={2} placeholder="https://maps.app.goo.gl/..." />
        </Field>
        <Field label="Dirección (texto)" error={errors.direccion?.message}>
          <Input {...register("direccion")} placeholder="Av. Colón 1234, Mar del Plata" />
        </Field>
        <Field label="Cómo llegar / estacionamiento" error={errors.como_llegar?.message}>
          <Textarea
            {...register("como_llegar")}
            rows={2}
            placeholder="Entrada de autos por el frente, estacionamiento sobre la calle…"
          />
        </Field>
      </Section>

      {/* ── Precios y horarios ── */}
      <Section title="Precios y horarios">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Field label="Precio por hora ($)" error={errors.precio_hora?.message}>
            <Input type="number" min={0} {...register("precio_hora")} />
          </Field>
          <Field
            label="Precio recién pintado ($)"
            error={errors.precio_pintura_reciente?.message}
            hint="Add-on opcional que el cliente tilda en el checkout. 0 = todavía sin cargar."
          >
            <Input type="number" min={0} {...register("precio_pintura_reciente")} />
          </Field>
          <Field label="Mínimo de horas" error={errors.min_horas?.message}>
            <Input type="number" min={1} {...register("min_horas")} />
          </Field>
          <Field label="Buffer entre reservas (h)" error={errors.buffer_horas?.message}>
            <Input type="number" min={0} {...register("buffer_horas")} />
          </Field>
          <Field label="Anticipación mínima (h)" error={errors.anticipacion_min_horas?.message}>
            <Input type="number" min={0} {...register("anticipacion_min_horas")} />
          </Field>
          <Field
            label="Anticipación recién pintado (h)"
            error={errors.anticipacion_pintura_horas?.message}
            hint="Se exige ADEMÁS de la anticipación mínima (pintar/secar el ciclorama lleva más tiempo). 0 = sin restricción extra."
          >
            <Input type="number" min={0} {...register("anticipacion_pintura_horas")} />
          </Field>
          <Field label="Apertura (hora)" error={errors.open_hour?.message}>
            <Input type="number" min={0} max={23} {...register("open_hour")} />
          </Field>
          <Field label="Cierre (hora)" error={errors.close_hour?.message}>
            <Input type="number" min={1} max={24} {...register("close_hour")} />
          </Field>
        </div>
      </Section>

      {/* ── Características ── */}
      <Section title="Características">
        <p className="text-xs text-muted-foreground mb-3">
          Aparecen en el grid de la página pública.
        </p>
        <div className="space-y-2">
          {featuresArr.fields.map((f, i) => (
            <div key={f.id} className="flex gap-2 items-start">
              <Input
                {...register(`features.${i}.label`)}
                placeholder="Superficie"
                className="w-36 shrink-0"
              />
              <Input {...register(`features.${i}.value`)} placeholder="— m²" />
              <IconButton
                aria-label="Eliminar característica"
                size="xs"
                onClick={() => featuresArr.remove(i)}
                className="mt-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
              >
                <Trash2 className="h-4 w-4" />
              </IconButton>
            </div>
          ))}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-2"
          onClick={() => featuresArr.append({ label: "", value: "" })}
        >
          <Plus className="h-3.5 w-3.5 mr-1" /> Añadir característica
        </Button>
      </Section>

      {/* ── FAQ ── */}
      <Section title="Preguntas frecuentes">
        <div className="space-y-3">
          {faqArr.fields.map((f, i) => (
            <div key={f.id} className="rounded-xl border hairline p-3 space-y-2">
              <div className="flex items-start gap-2">
                <Input {...register(`faq.${i}.q`)} placeholder="Pregunta" className="flex-1" />
                <IconButton
                  aria-label="Eliminar pregunta"
                  size="xs"
                  onClick={() => faqArr.remove(i)}
                  className="mt-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                >
                  <Trash2 className="h-4 w-4" />
                </IconButton>
              </div>
              <Textarea {...register(`faq.${i}.a`)} placeholder="Respuesta" rows={2} />
            </div>
          ))}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-2"
          onClick={() => faqArr.append({ q: "", a: "" })}
        >
          <Plus className="h-3.5 w-3.5 mr-1" /> Añadir pregunta
        </Button>
      </Section>

      {/* ── Testimonios / prueba social ── */}
      <Section title="Testimonios (prueba social)">
        <p className="text-xs text-muted-foreground mb-3">
          Aparecen en la página pública. Si no hay ninguno, la sección no se muestra.
        </p>
        <div className="space-y-3">
          {testimoniosArr.fields.map((f, i) => (
            <div key={f.id} className="rounded-xl border hairline p-3 space-y-2">
              <div className="flex items-start gap-2">
                <Input
                  {...register(`testimonios.${i}.autor`)}
                  placeholder="Autor (ej. Productora X)"
                  className="flex-1"
                />
                <IconButton
                  aria-label="Eliminar testimonio"
                  size="xs"
                  onClick={() => testimoniosArr.remove(i)}
                  className="mt-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                >
                  <Trash2 className="h-4 w-4" />
                </IconButton>
              </div>
              <Textarea
                {...register(`testimonios.${i}.texto`)}
                placeholder="Lo que dijeron del estudio"
                rows={2}
              />
            </div>
          ))}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-2"
          onClick={() => testimoniosArr.append({ autor: "", texto: "" })}
        >
          <Plus className="h-3.5 w-3.5 mr-1" /> Añadir testimonio
        </Button>
      </Section>

      {/* ── Submit ── */}
      <div className="sticky bottom-0 bg-background border-t hairline -mx-4 md:-mx-6 px-4 md:px-6 py-3 flex justify-end gap-3">
        <Button type="submit" variant="primary" disabled={mutation.isPending || !isDirty}>
          {mutation.isPending ? (
            <Spinner size="sm" className="mr-2" />
          ) : (
            <Save className="h-4 w-4 mr-2" />
          )}
          Guardar
        </Button>
      </div>
    </form>
  );
}
