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

/** Sube un File del browser al backend, para la edición dada. `orden`
 * (opcional): la posición que el caller ya calculó a partir del orden de
 * SELECCIÓN del archivo — con upload concurrente (varios `File` a la vez),
 * dejar que el backend infiera la posición por orden de LLEGADA desincroniza
 * la galería del orden en que el usuario los eligió (bug real, ver
 * `_insert_edicion_foto`). */
export async function uploadEdicionFile(
  edicionId: number,
  file: File,
  orden?: number,
): Promise<UploadResponse> {
  const fd = new FormData();
  fd.append("file", file);
  if (orden !== undefined) fd.append("orden", String(orden));

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
  orden?: number,
): Promise<UploadResponse> {
  const fd = new FormData();
  fd.append("file", file);
  if (orden !== undefined) fd.append("orden", String(orden));

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
