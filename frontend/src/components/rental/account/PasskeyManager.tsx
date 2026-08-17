/**
 * PasskeyManager — gestión de passkeys (listar / agregar / renombrar / borrar).
 *
 * Compartido por el back-office (settings) y el portal del cliente, parametrizado
 * por `scope` (resuelve los paths de la API). Una sola forma de la gestión —
 * `pulido-frontend`/DS: usa los primitivos del kit (Button/Input), sin one-offs.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import {
  deletePasskey,
  listPasskeys,
  passkeyErrorMessage,
  passkeySupported,
  registerPasskey,
  renamePasskey,
  type PasskeyCredential,
  type PasskeyScope,
} from "@/lib/passkey";

export function PasskeyManager({ scope }: { scope: PasskeyScope }) {
  const qc = useQueryClient();
  const queryKey = ["passkeys", scope];
  const [supported] = useState(() => passkeySupported());

  const q = useQuery({
    queryKey,
    queryFn: () => listPasskeys(scope),
    enabled: supported,
    retry: false,
  });

  const addMut = useMutation({
    mutationFn: () => registerPasskey(scope),
    onSuccess: () => {
      toast.success("Clave de acceso agregada");
      qc.invalidateQueries({ queryKey });
    },
    onError: (e) => toast.error(passkeyErrorMessage(e)),
  });

  const creds = q.data ?? [];

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground leading-relaxed">
        Entrá sin contraseña con la huella, el rostro o el PIN de tu dispositivo.{" "}
        {scope === "cliente"
          ? // Cliente: Google es co-primario, sin 2º factor obligatorio — perder el
            // dispositivo es trivial (entrás con Google y registrás una passkey nueva).
            "Tu cuenta de Google sigue disponible como respaldo si perdés el dispositivo."
          : // Admin: una vez que hay una passkey, Google SOLO ya no alcanza (2º factor
            // obligatorio, auth/google.py::auth_callback) — decía lo mismo que arriba y
            // era falso acá, justo el bug que dejó a un admin sin poder entrar desde un
            // dispositivo nuevo. Los códigos de respaldo (más abajo) son el recovery real.
            "Guardá los códigos de respaldo (más abajo) — sin ellos, perder este dispositivo te deja sin poder entrar."}
      </p>

      {!supported ? (
        <div className="rounded-md border border-amber/30 bg-amber/10 px-3 py-2 text-xs text-ink">
          Tu navegador no soporta claves de acceso. Probá con Chrome, Safari o Edge actualizados.
        </div>
      ) : (
        <>
          {q.isLoading ? (
            <div className="text-sm text-muted-foreground">Cargando…</div>
          ) : creds.length === 0 ? (
            <div className="rounded-md border border-dashed hairline px-3 py-4 text-sm text-muted-foreground">
              Todavía no registraste ninguna clave de acceso.
            </div>
          ) : (
            <ul className="space-y-2">
              {creds.map((c) => (
                <PasskeyRow key={c.id} scope={scope} cred={c} queryKey={queryKey} />
              ))}
            </ul>
          )}

          <Button
            type="button"
            size="sm"
            onClick={() => addMut.mutate()}
            loading={addMut.isPending}
            disabled={addMut.isPending}
          >
            <KeyRound /> Agregar clave de acceso
          </Button>
        </>
      )}
    </div>
  );
}

function PasskeyRow({
  scope,
  cred,
  queryKey,
}: {
  scope: PasskeyScope;
  cred: PasskeyCredential;
  queryKey: string[];
}) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(cred.device_name ?? "Clave de acceso");
  const [confirmDel, setConfirmDel] = useState(false);

  const renameMut = useMutation({
    mutationFn: (n: string) => renamePasskey(scope, cred.id, n),
    onSuccess: () => {
      setEditing(false);
      toast.success("Nombre actualizado");
      qc.invalidateQueries({ queryKey });
    },
    onError: (e) => toast.error(passkeyErrorMessage(e)),
  });

  const delMut = useMutation({
    mutationFn: () => deletePasskey(scope, cred.id),
    onSuccess: () => {
      toast.success("Clave de acceso eliminada");
      qc.invalidateQueries({ queryKey });
    },
    onError: (e) => toast.error(passkeyErrorMessage(e)),
  });

  return (
    <li className="flex items-center gap-3 card px-3 py-2.5">
      <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        {editing ? (
          <div className="flex items-center gap-2">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-8 text-sm"
              maxLength={40}
              autoFocus
            />
            <Button
              type="button"
              size="sm"
              onClick={() => renameMut.mutate(name.trim())}
              loading={renameMut.isPending}
              disabled={!name.trim()}
            >
              Guardar
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => {
                setEditing(false);
                setName(cred.device_name ?? "Clave de acceso");
              }}
            >
              Cancelar
            </Button>
          </div>
        ) : (
          <>
            <div className="truncate text-sm font-medium text-ink">
              {cred.device_name || "Clave de acceso"}
            </div>
            <div className="font-mono text-2xs uppercase tracking-wider text-muted-foreground">
              {fmtFecha(cred.created_at, cred.last_used_at)}
            </div>
          </>
        )}
      </div>

      {!editing && (
        <div className="flex shrink-0 items-center gap-1">
          <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(true)}>
            Renombrar
          </Button>
          {confirmDel ? (
            <>
              <Button
                type="button"
                size="sm"
                variant="destructive"
                onClick={() => delMut.mutate()}
                loading={delMut.isPending}
              >
                Eliminar
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setConfirmDel(false)}>
                No
              </Button>
            </>
          ) : (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setConfirmDel(true)}
              aria-label="Eliminar clave de acceso"
            >
              <Trash2 />
            </Button>
          )}
        </div>
      )}
    </li>
  );
}

function fmtFecha(created: string | null, lastUsed: string | null): string {
  const d = lastUsed ?? created;
  if (!d) return "—";
  const label = lastUsed ? "Último uso" : "Creada";
  try {
    return `${label} ${new Date(d).toLocaleDateString("es-AR", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    })}`;
  } catch {
    return label;
  }
}
