/**
 * Helpers para fotos de una EDICIÓN de taller (portada + galería pública).
 *
 * Espejo de src/lib/studio/photos.ts, scoped a una edición en vez del
 * singleton Estudio.
 * Endpoint admin: POST /api/admin/ediciones/{edicionId}/upload-foto (multipart/form-data)
 */

import { authedFetch } from "@/lib/authedFetch";

type UploadResponse = {
  id: number;
  public_url: string;
  path: string | null;
  size?: number;
  size_original?: number;
  content_type?: string;
  width?: number | null;
  height?: number | null;
};

/** Sube un File del browser al backend, para la edición dada. */
export async function uploadEdicionFile(edicionId: number, file: File): Promise<UploadResponse> {
  const fd = new FormData();
  fd.append("file", file);

  const res = await authedFetch(`/api/admin/ediciones/${edicionId}/upload-foto`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? `upload-foto → ${res.status}`);
  }
  return res.json() as Promise<UploadResponse>;
}

/** Espejo de `uploadEdicionFile`, scoped a la galería propia de una
 * institución (endpoint: POST /api/admin/instituciones/{institucionId}/upload-foto). */
export async function uploadInstitucionFile(
  institucionId: number,
  file: File,
): Promise<UploadResponse> {
  const fd = new FormData();
  fd.append("file", file);

  const res = await authedFetch(`/api/admin/instituciones/${institucionId}/upload-foto`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? `upload-foto → ${res.status}`);
  }
  return res.json() as Promise<UploadResponse>;
}
