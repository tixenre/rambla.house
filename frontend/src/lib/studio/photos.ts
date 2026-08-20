/**
 * Helpers para fotos del Estudio.
 *
 * Espejo de src/lib/equipment/photos.ts para el singleton Estudio.
 * Endpoints admin:
 *   POST /api/admin/estudio/upload-foto          (multipart/form-data)
 *   POST /api/admin/estudio/upload-foto-from-url  (JSON {url})
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

/** Sube un File del browser al backend. Devuelve los metadatos de la foto
 * creada. `orden` (opcional): ver el mismo parámetro en `uploadEdicionFile`
 * (lib/talleres/photos.ts) — evita que el upload concurrente desincronice
 * la galería del orden en que el usuario eligió los archivos. */
export async function uploadStudioFile(file: File, orden?: number): Promise<UploadResponse> {
  const fd = new FormData();
  fd.append("file", file);
  if (orden !== undefined) fd.append("orden", String(orden));

  const res = await authedFetch("/api/admin/estudio/upload-foto", {
    method: "POST",
    body: fd,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? `upload-foto → ${res.status}`);
  }
  return res.json() as Promise<UploadResponse>;
}

/** Descarga una URL externa vía backend y la sube a R2. */
export async function uploadStudioUrl(url: string): Promise<UploadResponse> {
  if (!url) throw new Error("URL vacía");

  const res = await authedFetch("/api/admin/estudio/upload-foto-from-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? `upload-foto-from-url → ${res.status}`);
  }
  return res.json() as Promise<UploadResponse>;
}
