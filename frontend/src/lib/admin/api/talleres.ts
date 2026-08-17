import { authedFetch, authedJson, authedPostJson } from "@/lib/authedFetch";
import type {
  BorradoresResp,
  ClaseBody,
  EdicionAdmin,
  EdicionFoto,
  EdicionFotoOrdenItem,
  EdicionKpis,
  TallerConcepto,
  Inscripcion,
  Institucion,
  Instructor,
  Interesado,
  PedidoGeneradoEdicion,
  Trabajo,
} from "./types";

async function _ok<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error((d as { detail?: string }).detail ?? `Error ${r.status}`);
  }
  return r.json() as Promise<T>;
}

export const talleresAdminApi = {
  list: () => authedJson<TallerConcepto[]>("/api/admin/talleres"),

  createConcepto: (body: object) => authedPostJson<TallerConcepto>("/api/admin/talleres", body),

  deleteConcepto: (conceptoId: number) =>
    authedJson<{ ok: boolean }>(`/api/admin/talleres/${conceptoId}`, { method: "DELETE" }),

  updateConcepto: (conceptoId: number, body: object) =>
    authedJson<TallerConcepto>(`/api/admin/talleres/${conceptoId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  createEdicion: (conceptoId: number, body: object) =>
    authedPostJson<EdicionAdmin>(`/api/admin/talleres/${conceptoId}/ediciones`, body),

  updateEdicion: (edicionId: number, body: object) =>
    authedJson<EdicionAdmin>(`/api/admin/ediciones/${edicionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  updateEdicionClases: (edicionId: number, body: { tipo_taller: string; clases: ClaseBody[] }) =>
    authedJson<EdicionAdmin>(`/api/admin/ediciones/${edicionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  deleteEdicion: (edicionId: number) =>
    authedJson<{ ok: boolean }>(`/api/admin/ediciones/${edicionId}`, { method: "DELETE" }),

  // Portada + galería de una EDICIÓN (mismo patrón que estudioAdminApi
  // deleteFoto/reorderFotos, scoped a edicionId). El upload en sí va por
  // uploadEdicionFile (src/lib/talleres/photos.ts) — mismo split que Estudio
  // (multipart no pasa por authedJson).
  deleteFotoEdicion: (fotoId: number) =>
    authedJson<{ ok: boolean }>(`/api/admin/ediciones/fotos/${fotoId}`, { method: "DELETE" }),

  reorderFotosEdicion: (edicionId: number, fotos: EdicionFotoOrdenItem[]) =>
    authedJson<{ fotos: EdicionFoto[] }>(`/api/admin/ediciones/${edicionId}/fotos/orden`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fotos }),
    }),

  // F2: portada de una clase (solo clases guardadas — necesitan id).
  uploadPortadaClase: (claseId: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return authedFetch(`/api/admin/clases/${claseId}/portada`, {
      method: "POST",
      body: fd,
    }).then((r) => _ok<{ ok: boolean; url: string; media_id: number }>(r));
  },

  deletePortadaClase: (claseId: number) =>
    authedJson<{ ok: boolean }>(`/api/admin/clases/${claseId}/portada`, { method: "DELETE" }),

  listInscripciones: (edicionId: number) =>
    authedJson<Inscripcion[]>(`/api/admin/ediciones/${edicionId}/inscripciones`),

  listBorradores: (edicionId: number) =>
    authedJson<BorradoresResp>(`/api/admin/ediciones/${edicionId}/borradores`),

  // F4c: mini-KPIs de una edición (señas + plata, ya resuelta por el backend).
  getEdicionKpis: (edicionId: number) =>
    authedJson<EdicionKpis>(`/api/admin/ediciones/${edicionId}/kpis`),

  // Puente Talleres → Pedidos (Fase 1, #1308): los pedidos mensuales que
  // _regenerar_pedidos_taller generó para esta edición.
  listPedidosEdicion: (edicionId: number) =>
    authedJson<PedidoGeneradoEdicion[]>(`/api/admin/ediciones/${edicionId}/pedidos`),

  eliminarInscripcion: (conceptoId: number, inscripcionId: number) =>
    authedJson<{ ok: boolean }>(
      `/api/admin/talleres/${conceptoId}/inscripciones/${inscripcionId}`,
      { method: "DELETE" },
    ),

  confirmarInscripcion: (conceptoId: number, inscripcionId: number) =>
    authedJson<{ ok: boolean }>(
      `/api/admin/talleres/${conceptoId}/inscripciones/${inscripcionId}/confirmar`,
      { method: "POST" },
    ),

  // F4b: seña + ofrecer cupo al siguiente.
  verificarSena: (conceptoId: number, inscripcionId: number) =>
    authedJson<{ ok: boolean }>(
      `/api/admin/talleres/${conceptoId}/inscripciones/${inscripcionId}/verificar-sena`,
      { method: "POST" },
    ),

  ofrecerCupo: (conceptoId: number, inscripcionId: number) =>
    authedJson<{ ok: boolean }>(
      `/api/admin/talleres/${conceptoId}/inscripciones/${inscripcionId}/ofrecer-cupo`,
      { method: "POST" },
    ),

  listInteresados: (conceptoId: number) =>
    authedJson<Interesado[]>(`/api/admin/talleres/${conceptoId}/interesados`),

  notificarInteresado: (conceptoId: number, interesadoId: number) =>
    authedJson<{ ok: boolean }>(
      `/api/admin/talleres/${conceptoId}/interesados/${interesadoId}/notificar`,
      { method: "POST" },
    ),

  notificarCambios: (conceptoId: number, mensaje: string) =>
    authedJson<{ enviados: number; fallidos: number }>(
      `/api/admin/talleres/${conceptoId}/notificar-cambios`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mensaje: mensaje || undefined }),
      },
    ),

  /** Devuelve el Response crudo — el consumidor arma el blob/URL de descarga. */
  exportInscripcionesCsv: (conceptoId: number) =>
    authedFetch(`/api/admin/talleres/${conceptoId}/inscripciones/export-csv`),

  // F3: instructores como entidad (mini-CRUD) + link N↔N con el taller.
  listInstructores: () => authedJson<Instructor[]>("/api/admin/instructores"),

  createInstructor: (body: {
    nombre: string;
    rol?: string;
    descripcion?: string;
    instagram?: string;
    web?: string;
    proyectos?: string;
  }) => authedPostJson<Instructor>("/api/admin/instructores", body),

  updateInstructor: (instructorId: number, body: object) =>
    authedJson<Instructor>(`/api/admin/instructores/${instructorId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  deleteInstructor: (instructorId: number) =>
    authedJson<{ ok: boolean }>(`/api/admin/instructores/${instructorId}`, { method: "DELETE" }),

  uploadFotoInstructorPerfil: (instructorId: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return authedFetch(`/api/admin/instructores/${instructorId}/upload-foto`, {
      method: "POST",
      body: fd,
    }).then((r) => _ok<{ ok: boolean; url: string; media_id: number }>(r));
  },

  setTallerInstructores: (conceptoId: number, instructorIds: number[]) =>
    authedJson<{ instructores: Instructor[] }>(`/api/admin/talleres/${conceptoId}/instructores`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instructor_ids: instructorIds }),
    }),

  // Instituciones co-presentadoras (ej. "Rambla" + "Filmar") — mismo patrón
  // que instructores: mini-CRUD + link N↔N con el taller.
  listInstituciones: () => authedJson<Institucion[]>("/api/admin/instituciones"),

  createInstitucion: (body: {
    nombre: string;
    descripcion?: string;
    instagram?: string;
    web?: string;
  }) => authedPostJson<Institucion>("/api/admin/instituciones", body),

  updateInstitucion: (institucionId: number, body: object) =>
    authedJson<Institucion>(`/api/admin/instituciones/${institucionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  deleteInstitucion: (institucionId: number) =>
    authedJson<{ ok: boolean }>(`/api/admin/instituciones/${institucionId}`, { method: "DELETE" }),

  uploadLogoInstitucion: (institucionId: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return authedFetch(`/api/admin/instituciones/${institucionId}/upload-logo`, {
      method: "POST",
      body: fd,
    }).then((r) => _ok<{ ok: boolean; url: string; media_id: number }>(r));
  },

  setTallerInstituciones: (conceptoId: number, institucionIds: number[]) =>
    authedJson<{ instituciones: Institucion[] }>(
      `/api/admin/talleres/${conceptoId}/instituciones`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ institucion_ids: institucionIds }),
      },
    ),

  // F4c: trabajos pasados (solo YouTube, sin testimonios).
  crearTrabajo: (conceptoId: number, body: { titulo?: string; youtube_url: string }) =>
    authedPostJson<Trabajo>(`/api/admin/talleres/${conceptoId}/trabajos`, body),

  editarTrabajo: (
    trabajoId: number,
    body: { titulo?: string; youtube_url?: string; orden?: number },
  ) =>
    authedJson<Trabajo>(`/api/admin/trabajos/${trabajoId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  eliminarTrabajo: (trabajoId: number) =>
    authedJson<{ ok: boolean }>(`/api/admin/trabajos/${trabajoId}`, { method: "DELETE" }),
};
