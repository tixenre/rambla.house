import { authedFetch, authedJson, authedPostJson } from "@/lib/authedFetch";
import type {
  EstudioConfig,
  EstudioInput,
  EstudioFoto,
  EstudioSlotFijo,
  EstudioSlotInput,
  EstudioPackEquipoCurado,
  EstudioTrabajo,
  EstudioTrabajoInput,
  TrabajoOrdenItem,
  FotoOrdenItem,
  DescuentoJornada,
  CalendarioBloqueo,
} from "./types";

// ── Estudio (singleton E1) ───────────────────────────────────────────────────

export const estudioAdminApi = {
  get: () => authedJson<EstudioConfig>("/api/admin/estudio"),
  listPack: () => authedJson<{ pack: EstudioPackEquipoCurado[] }>("/api/admin/estudio/pack"),
  addPackEquipo: (equipo_id: number) =>
    authedPostJson<{ pack: EstudioPackEquipoCurado[] }>("/api/admin/estudio/pack", { equipo_id }),
  removePackEquipo: (equipo_id: number) =>
    authedFetch(`/api/admin/estudio/pack/${equipo_id}`, { method: "DELETE" }).then(async (r) => {
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d?.detail ?? `DELETE pack → ${r.status}`);
      }
      return r.json() as Promise<{ pack: EstudioPackEquipoCurado[] }>;
    }),
  // Bloqueos no-pedido en [desde, hasta] (slots fijos + clases de taller) —
  // overlay del calendario del dashboard admin (get_calendario no los ve).
  getOcupacion: (desde: string, hasta: string) => {
    const sp = new URLSearchParams({ desde, hasta });
    return authedJson<{ bloqueos: CalendarioBloqueo[] }>(
      `/api/admin/estudio/ocupacion?${sp.toString()}`,
    );
  },
  listSlots: () => authedJson<{ slots: EstudioSlotFijo[] }>("/api/admin/estudio/slots"),
  createSlot: (data: EstudioSlotInput) =>
    authedPostJson<EstudioSlotFijo>("/api/admin/estudio/slots", data),
  updateSlot: (id: number, data: Partial<EstudioSlotInput>) =>
    authedFetch(`/api/admin/estudio/slots/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }).then(async (r) => {
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d?.detail ?? `PATCH slot → ${r.status}`);
      }
      return r.json() as Promise<EstudioSlotFijo>;
    }),
  deleteSlot: (id: number) =>
    authedFetch(`/api/admin/estudio/slots/${id}`, { method: "DELETE" }).then(async (r) => {
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d?.detail ?? `DELETE slot → ${r.status}`);
      }
      return r.json() as Promise<{ ok: boolean }>;
    }),
  update: (data: EstudioInput) =>
    authedFetch("/api/admin/estudio", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }).then(async (r) => {
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d?.detail ?? `PATCH estudio → ${r.status}`);
      }
      return r.json() as Promise<EstudioConfig>;
    }),
  deleteFoto: (fotoId: number) =>
    authedFetch(`/api/admin/estudio/fotos/${fotoId}`, { method: "DELETE" }).then(async (r) => {
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d?.detail ?? `DELETE foto → ${r.status}`);
      }
      return r.json() as Promise<{ ok: boolean }>;
    }),
  reorderFotos: (fotos: FotoOrdenItem[]) =>
    authedFetch("/api/admin/estudio/fotos/orden", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fotos }),
    }).then(async (r) => {
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d?.detail ?? `PATCH fotos/orden → ${r.status}`);
      }
      return r.json() as Promise<{ fotos: EstudioFoto[] }>;
    }),
};

// ── Trabajos / producciones ──────────────────────────────────────────────────

async function _ok<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error((d as { detail?: string }).detail ?? `Error ${r.status}`);
  }
  return r.json() as Promise<T>;
}

export const trabajosAdminApi = {
  list: () => authedJson<{ trabajos: EstudioTrabajo[] }>("/api/admin/estudio/trabajos"),

  fetchMeta: (url: string) =>
    authedFetch("/api/admin/estudio/trabajos/fetch-meta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }).then((r) =>
      _ok<{
        titulo?: string | null;
        realizador?: string | null;
        thumbnail_url?: string | null;
        descripcion?: string | null;
        fuente?: string;
      }>(r),
    ),

  create: (data: EstudioTrabajoInput) =>
    authedPostJson<EstudioTrabajo>("/api/admin/estudio/trabajos", data),

  update: (id: number, data: EstudioTrabajoInput) =>
    authedFetch(`/api/admin/estudio/trabajos/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }).then((r) => _ok<EstudioTrabajo>(r)),

  delete: (id: number) =>
    authedFetch(`/api/admin/estudio/trabajos/${id}`, { method: "DELETE" }).then((r) =>
      _ok<{ ok: boolean }>(r),
    ),

  reorder: (trabajos: TrabajoOrdenItem[]) =>
    authedFetch("/api/admin/estudio/trabajos/orden", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ trabajos }),
    }).then((r) => _ok<{ trabajos: EstudioTrabajo[] }>(r)),

  uploadFoto: (id: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return authedFetch(`/api/admin/estudio/trabajos/${id}/upload-foto`, {
      method: "POST",
      body: fd,
    }).then((r) => _ok<EstudioTrabajo>(r));
  },

  deleteFoto: (id: number, fotoIdx: number) =>
    authedFetch(`/api/admin/estudio/trabajos/${id}/fotos/${fotoIdx}`, {
      method: "DELETE",
    }).then((r) => _ok<EstudioTrabajo>(r)),

  uploadLogo: (id: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return authedFetch(`/api/admin/estudio/trabajos/${id}/upload-logo`, {
      method: "POST",
      body: fd,
    }).then((r) => _ok<EstudioTrabajo>(r));
  },
};

// ── Descuentos por jornadas ──────────────────────────────────────────────────

export const descuentosJornadaApi = {
  list: () => authedJson<DescuentoJornada[]>("/api/descuentos-jornada"),
  create: (data: { jornadas: number; pct: number }) =>
    authedPostJson<DescuentoJornada>("/api/admin/descuentos-jornada", data),
  delete: (id: number) => authedFetch(`/api/admin/descuentos-jornada/${id}`, { method: "DELETE" }),
  /** % interpolado para cada cantidad de jornadas pedida — la fuente ÚNICA
   *  (misma que /api/cotizar). El front NO reimplementa la interpolación
   *  (#1219: la preview local podía redondear distinto al backend). */
  interpolar: (jornadasList: number[]) => {
    const qs = jornadasList.map((j) => `jornadas=${j}`).join("&");
    return authedJson<{ jornadas: number; pct: number }[]>(
      `/api/descuentos-jornada/interpolar?${qs}`,
    );
  },
};
