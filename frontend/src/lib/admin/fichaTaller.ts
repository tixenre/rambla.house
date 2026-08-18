import type { ClaseBody, ModalidadPagoBody } from "@/lib/admin/api/types";

// Ficha de importación (ver `backend/scripts/importar_taller.py` — mismo
// esquema, así una ficha que Claude armó para el script sirve tal cual acá).
// Fuente única: la usan `NuevoConceptoDialog` (alta) y `ActualizarPorJsonDialog`
// (completar un taller ya existente) — no duplicar el tipo/parser en cada uno.
// `instructor.foto`/`clases[].portada` (paths locales) NO se leen en este
// modo — el navegador no tiene acceso a paths relativos del filesystem de
// quien armó la ficha; las fotos se suben después, desde el taller ya creado.
export type FichaTaller = {
  nombre: string;
  subtitulo?: string;
  descripcion?: string;
  // Teaser corto para la tarjeta de /escuelas (mezcla "para quién" + "de qué
  // trata") — no lo pisa la descripción completa truncada.
  resumen?: string;
  publico_objetivo?: string;
  notif_email?: string;
  terminos?: string;
  beneficios?: string;
  pregunta_experiencia?: string;
  mensaje_confirmacion?: string;
  instructor?: {
    nombre: string;
    rol?: string;
    descripcion?: string;
    instagram?: string;
    web?: string;
    proyectos?: string;
  };
  edicion: {
    tipo_taller?: string;
    horario?: string;
    cupos_total?: number;
    precio_total?: number;
    precio_sena?: number;
    direccion?: string | null;
    pago_alias?: string;
    pago_cbu?: string;
    pago_banco?: string;
    usa_estudio?: boolean;
    valor_estudio?: number;
    valor_estudio_modo?: "mensual" | "total";
    usa_equipos?: boolean;
    valor_equipos?: number;
    valor_equipos_modo?: "mensual" | "total";
    clases: ClaseBody[];
    // Opcional — `EdicionCreateBody` no las acepta en la creación, se cargan
    // aparte por PATCH (mismo campo que `PreciosSection` en el admin).
    // El público las ve en `ModalidadSelector` (form de inscripción); con
    // 2+ es un selector real, con 1 sola muestra el monto sin radio (nada
    // que elegir). `PrecioCard`, que mostraba el precio sin depender del
    // form, se retiró — 2026-08-12.
    modalidades?: ModalidadPagoBody[];
  };
};

export function parseFicha(raw: string): FichaTaller {
  const data = JSON.parse(raw);
  if (!data?.nombre || !data?.edicion?.clases?.length) {
    throw new Error("La ficha necesita al menos 'nombre' y 'edicion.clases'");
  }
  return data as FichaTaller;
}
