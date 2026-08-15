/**
 * authedFetch — wrapper de fetch que envía la cookie `session` del backend.
 */

// En dev el proxy de Vite reenvía /api y /auth a localhost:8000, así que
// usamos ruta relativa (API_BASE vacío). En prod VITE_API_URL apunta al dominio.
const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

export class AuthedHttpError extends Error {
  status: number;
  // `message` lleva el prefijo técnico "METHOD /path → status" (útil en consola/
  // debug); `detail` es SOLO el texto que mandó el backend (o vacío) — lo que
  // corresponde mostrarle a un usuario en vez del string de log completo.
  detail: string;
  constructor(message: string, status: number, detail: string = "") {
    super(message);
    this.name = "AuthedHttpError";
    this.status = status;
    this.detail = detail;
  }
}

export type AuthedFetchInit = Omit<RequestInit, "headers"> & {
  headers?: Record<string, string>;
};

export async function authedFetch(path: string, init: AuthedFetchInit = {}): Promise<Response> {
  const { headers = {}, ...rest } = init;
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  return fetch(url, { ...rest, headers, credentials: "include" });
}

export async function authedJson<T>(path: string, init: AuthedFetchInit = {}): Promise<T> {
  const res = await authedFetch(path, {
    ...init,
    headers: { Accept: "application/json", ...(init.headers ?? {}) },
  });
  const method = init.method ?? "GET";
  if (!res.ok) {
    // Intentar parsear como JSON (FastAPI devuelve {detail}); si la
    // respuesta es HTML/text (proxy de Vite, Cloudflare, error genérico
    // de uvicorn), leerla como text y mostrar un fragmento. Sin esto el
    // toast queda como "GET /path → 500" sin contexto y el debugging es
    // a ciegas.
    const text = await res.text().catch(() => "");
    let message = "";
    try {
      const parsed = JSON.parse(text);
      const detail = parsed?.detail ?? parsed?.message ?? "";
      // FastAPI a veces devuelve detail como string, otras como objeto
      // estructurado (ej. {"errores": [...]}). Sin esto el toast queda
      // como "[object Object]" y no se ve el error real.
      if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(detail)) {
        message = detail
          .map((e: unknown) =>
            e && typeof e === "object" && "msg" in e
              ? String((e as { msg: unknown }).msg)
              : JSON.stringify(e),
          )
          .join("; ");
      } else if (detail && typeof detail === "object") {
        const errs = (detail as { errores?: unknown }).errores;
        if (Array.isArray(errs)) {
          message = errs.join("; ");
        } else {
          message = JSON.stringify(detail);
        }
      }
    } catch {
      // No era JSON. Tomar las primeras líneas, sin tags HTML, y truncar.
      message = text
        .replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 200);
    }
    const prefix = `${method} ${path} → ${res.status}`;
    throw new AuthedHttpError(message ? `${prefix}: ${message}` : prefix, res.status, message);
  }
  // 204 No Content y respuestas sin body: devolver undefined cast a T para
  // no romper con `Unexpected end of JSON input`.
  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

export async function authedPostJson<T>(
  path: string,
  body: unknown,
  init: AuthedFetchInit = {},
): Promise<T> {
  return authedJson<T>(path, {
    ...init,
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
    body: JSON.stringify(body),
  });
}
