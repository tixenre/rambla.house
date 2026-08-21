/**
 * Helpers para la galería multi-foto de equipos (F2).
 *
 * Endpoints admin del backend:
 *   GET    /api/admin/equipos/{id}/fotos
 *   POST   /api/admin/equipos/{id}/fotos              (multipart/form-data)
 *   POST   /api/admin/equipos/{id}/fotos/from-url     (JSON {url})
 *   POST   /api/admin/equipos/{id}/fotos/from-urls    (JSON {urls: [...]}, hasta 20 — #1051 Stream B)
 *   DELETE /api/admin/equipos/{id}/fotos/{foto_id}
 *   PATCH  /api/admin/equipos/{id}/fotos/orden        (JSON {fotos: [...]})
 */

import { authedFetch } from "@/lib/authedFetch";

export type EquipoFoto = {
  id: number;
  url: string;
  path: string | null;
  media_id: number | null;
  orden: number;
  es_principal: boolean;
  created_at: string | null;
  size_bytes: number | null;
};

export type EquipoFotoOrdenItem = {
  id: number;
  orden: number;
  es_principal: boolean;
};

export async function getEquipoFotos(equipoId: number): Promise<EquipoFoto[]> {
  const res = await authedFetch(`/api/admin/equipos/${equipoId}/fotos`);
  if (!res.ok) throw new Error(`get-fotos → ${res.status}`);
  const data = (await res.json()) as { fotos: EquipoFoto[] };
  return data.fotos;
}

/** `orden` (opcional): ver el mismo parámetro en `uploadEdicionFile`
 * (lib/talleres/photos.ts) — evita que el upload concurrente desincronice
 * la galería del orden en que el usuario eligió los archivos. */
export async function uploadEquipoFoto(
  equipoId: number,
  file: File,
  orden?: number,
): Promise<EquipoFoto> {
  const fd = new FormData();
  fd.append("file", file);
  if (orden !== undefined) fd.append("orden", String(orden));
  const res = await authedFetch(`/api/admin/equipos/${equipoId}/fotos`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail ?? `upload-foto → ${res.status}`);
  }
  return res.json() as Promise<EquipoFoto>;
}

export async function uploadEquipoFotoFromUrl(equipoId: number, url: string): Promise<EquipoFoto> {
  const res = await authedFetch(`/api/admin/equipos/${equipoId}/fotos/from-url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail ?? `upload-foto-from-url → ${res.status}`);
  }
  return res.json() as Promise<EquipoFoto>;
}

export type EquipoFotosFromUrlsResult = {
  agregadas: EquipoFoto[];
  fallidas: { url: string; error: string }[];
};

/** Batch de `uploadEquipoFotoFromUrl` (hasta 20 URLs) — best-effort: una URL
 *  que falla no aborta el resto, viene reportada en `fallidas`. Pensado para
 *  agregar de un saque la galería que trae un HTML recién enriquecido
 *  (`adminApi.enriquecerFromHtml` → `foto_candidates`). */
export async function uploadEquipoFotosFromUrls(
  equipoId: number,
  urls: string[],
): Promise<EquipoFotosFromUrlsResult> {
  const res = await authedFetch(`/api/admin/equipos/${equipoId}/fotos/from-urls`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls }),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail ?? `fotos-from-urls → ${res.status}`);
  }
  return res.json() as Promise<EquipoFotosFromUrlsResult>;
}

export async function deleteEquipoFoto(equipoId: number, fotoId: number): Promise<void> {
  const res = await authedFetch(`/api/admin/equipos/${equipoId}/fotos/${fotoId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail ?? `delete-foto → ${res.status}`);
  }
}

export async function reorderEquipoFotos(
  equipoId: number,
  items: EquipoFotoOrdenItem[],
): Promise<{ fotos: EquipoFoto[] }> {
  const res = await authedFetch(`/api/admin/equipos/${equipoId}/fotos/orden`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fotos: items }),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail ?? `reorder-fotos → ${res.status}`);
  }
  return res.json() as Promise<{ fotos: EquipoFoto[] }>;
}
