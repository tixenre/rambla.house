/**
 * equipo-form-schema.ts — schema (zod) y constantes del form de equipos.
 *
 * Extraído verbatim de `EquipoFormDialog.tsx` (split de god-module, Frente E
 * del skill `mantenimiento`): piezas puras sin estado de componente. Cero cambio
 * de comportamiento.
 */
import { z } from "zod";

// Schema dinámico: en creación validamos campos mínimos obligatorios
// (#351). En edición todo queda opcional para no romper flujos de
// completado parcial — el dashboard de calidad ya visibiliza los huecos.
export function buildSchema(isEdit: boolean) {
  const requiredStr = (name: string) =>
    isEdit ? z.string().optional().nullable() : z.string().min(1, `${name} requerido`);
  const requiredNum = (name: string) =>
    isEdit
      ? z.coerce.number().min(0).optional().nullable()
      : z.coerce.number().min(1, `${name} requerido`);

  return z.object({
    nombre: z.string().min(1, "Nombre requerido"),
    marca: requiredStr("Marca"),
    modelo: z.string().optional().nullable(),
    cantidad: z.coerce.number().int().min(1, "Cantidad requerida").default(1),
    precio_jornada: requiredNum("Precio/jornada"),
    precio_usd: z.coerce.number().min(0).optional().nullable(),
    roi_pct: z.coerce.number().min(0).optional().nullable(),
    valor_reposicion: z.coerce.number().min(0).optional().nullable(),
    costo_compra: z.coerce.number().min(0).optional().nullable(),
    fecha_compra: z.string().optional().nullable(),
    serie: z.string().optional().nullable(),
    bh_url: z.string().optional().nullable(),
    foto_url: z.string().optional().nullable(),
    dueno: requiredStr("Dueño"),
    estado: z.enum(["operativo", "en_mantenimiento", "fuera_servicio"]).default("operativo"),
    visible_catalogo: z.boolean().default(true),
    ficha_completa: z.boolean().default(false),
    tipo: z.enum(["simple", "kit", "combo"]).default("simple"),
  });
}

export type FormValues = z.infer<ReturnType<typeof buildSchema>>;

/** Campos "recomendados" para un equipo (#351). Después del create, si
 *  alguno está vacío, mostramos un toast con CTA para completar. */
export const RECOMMENDED_FIELDS = ["foto", "descripcion", "serie", "valor_reposicion"] as const;
export type RecommendedField = (typeof RECOMMENDED_FIELDS)[number];
export const RECOMMENDED_LABELS: Record<RecommendedField, string> = {
  foto: "foto",
  descripcion: "descripción",
  serie: "número de serie",
  valor_reposicion: "valor de reposición",
};
