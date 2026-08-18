/**
 * BackupCodesSection — códigos de respaldo del 2º factor admin (recovery
 * cuando se pierde el dispositivo con la passkey, ver `auth/backup_codes.py`).
 * Mismo patrón de "regenerar con confirmación" que `CalendarFeedSection`,
 * más el paso de "revelar una sola vez" (los códigos no se pueden volver a
 * ver después de generarlos — solo existen en claro en esta respuesta).
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/design-system/ui/button";
import { Spinner } from "@/design-system/ui/spinner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/design-system/ui/alert-dialog";
import { contarCodigosRespaldo, generarCodigosRespaldo } from "@/lib/backupCodes";

export function BackupCodesSection() {
  const qc = useQueryClient();
  const queryKey = ["admin", "backup-codes", "count"];
  const [confirmRegen, setConfirmRegen] = useState(false);
  // Los códigos SOLO existen en claro acá, en memoria, mientras dura esta
  // sesión de la pantalla — no se vuelven a poder leer después de cerrarlos.
  const [reveal, setReveal] = useState<string[] | null>(null);

  const countQ = useQuery({
    queryKey,
    queryFn: () => contarCodigosRespaldo(),
    staleTime: 0,
  });

  const genMut = useMutation({
    mutationFn: () => generarCodigosRespaldo(),
    onSuccess: (codigos) => {
      setReveal(codigos);
      qc.setQueryData(queryKey, codigos.length);
    },
    onError: (e: Error) => toast.error(e.message),
    onSettled: () => setConfirmRegen(false),
  });

  const disponibles = countQ.data ?? 0;

  const copiarTodos = async () => {
    if (!reveal) return;
    try {
      await navigator.clipboard.writeText(reveal.join("\n"));
      toast.success("Códigos copiados");
    } catch {
      toast.error("No se pudo copiar — anotalos a mano");
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground leading-relaxed">
        Si perdés el dispositivo con tu clave de acceso, Google solo <strong>ya no alcanza</strong>{" "}
        para entrar (tu cuenta tiene 2º factor obligatorio) — un código de respaldo es la única
        forma de recuperar el acceso y registrar una clave nueva. Guardalos en un gestor de
        contraseñas o anotados en un lugar seguro. <strong>Cada código sirve una sola vez.</strong>
      </p>

      {reveal ? (
        <div className="rounded-md border border-amber/30 bg-amber/10 p-3 space-y-3">
          <p className="text-sm font-medium text-ink">
            Guardalos ahora — no los vas a poder volver a ver.
          </p>
          <div className="grid grid-cols-2 gap-1.5 font-mono text-sm">
            {reveal.map((c) => (
              <div key={c} className="rounded bg-background px-2 py-1 text-center">
                {c}
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" onClick={copiarTodos}>
              Copiar todos
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setReveal(null)}>
              Ya los guardé — ocultar
            </Button>
          </div>
        </div>
      ) : countQ.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Cargando…
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-muted-foreground">
            {disponibles > 0
              ? `Te quedan ${disponibles} código${disponibles === 1 ? "" : "s"} sin usar.`
              : "Todavía no generaste códigos de respaldo."}
          </span>
          <Button
            type="button"
            size="sm"
            variant={disponibles > 0 ? "outline" : "primary"}
            onClick={() => (disponibles > 0 ? setConfirmRegen(true) : genMut.mutate())}
            loading={genMut.isPending}
            disabled={genMut.isPending}
          >
            {disponibles > 0 ? "Generar códigos nuevos" : "Generar códigos"}
          </Button>
        </div>
      )}

      <AlertDialog open={confirmRegen} onOpenChange={setConfirmRegen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Generar códigos nuevos?</AlertDialogTitle>
            <AlertDialogDescription>
              Los {disponibles} código{disponibles === 1 ? "" : "s"} sin usar que tenés ahora van a
              dejar de funcionar — si los guardaste en algún lado, quedan inválidos.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={genMut.isPending}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                genMut.mutate();
              }}
              disabled={genMut.isPending}
            >
              {genMut.isPending ? "Generando…" : "Generar"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
