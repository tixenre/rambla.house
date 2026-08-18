/**
 * Códigos de respaldo del 2º factor admin — recovery cuando se pierde el
 * dispositivo con la passkey (backend: `auth/backup_codes.py`). Solo admin:
 * el cliente no tiene 2º factor obligatorio, así que no necesita esto (ver
 * `auth/passkey/routes.py`: "perder el dispositivo = entrar por Google y
 * re-registrar" — cierto para cliente, no para admin).
 */
import { authedJson, authedPostJson } from "@/lib/authedFetch";

export async function generarCodigosRespaldo(): Promise<string[]> {
  const data = await authedPostJson<{ codigos: string[] }>("/auth/backup-code/generar", {});
  return data.codigos;
}

export async function contarCodigosRespaldo(): Promise<number> {
  const data = await authedJson<{ disponibles: number }>("/auth/backup-code/estado");
  return data.disponibles;
}

/** Login con código de respaldo — reemplaza a `loginWithPasskey()` cuando esta
 * falla en `?paso=passkey`. `authedPostJson` ya parsea el `{detail}` del 401/400
 * del backend en el mensaje del error — mismo patrón que `loginWithPasskey`. */
export async function loginConCodigoRespaldo(code: string): Promise<void> {
  await authedPostJson("/auth/backup-code/login", { code });
}
