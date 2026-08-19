import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileJson, Upload } from "lucide-react";
import { toast } from "sonner";

import { talleresAdminApi } from "@/lib/admin/api/talleres";
import type { TallerConcepto } from "@/lib/admin/api/types";
import { type FichaTaller, parseFicha } from "@/lib/admin/fichaTaller";
import { Button } from "@/design-system/ui/button";
import { Spinner } from "@/design-system/ui/spinner";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/design-system/ui/dialog";
import { updateConceptoInCache, updateEdicionInCache } from "./cache";

// Completa un taller YA EXISTENTE desde la misma ficha JSON que usa
// `NuevoConceptoDialog` para crear uno nuevo (mismo formato — no hace falta
// una ficha distinta). A diferencia del alta, esto es un REEMPLAZO: pisa
// nombre/descripción/subtítulo/resumen/público del concepto y
// horario/precio/seña/cupos/clases/modalidades/cuenta de pago de la PRIMERA
// edición — las clases que ya tuviera esa edición y no estén en la ficha se
// BORRAN (mismo upsert que usa el resto del admin al editar clases, no un
// delete+insert ciego, pero sin `id` en la ficha se tratan todas como
// nuevas). Pensado para completar un stub recién creado, no para un taller
// con inscriptos/clases reales ya cargadas — la tarjeta de confirmación lo
// avisa antes de aplicar.
export function ActualizarPorJsonDialog({
  concepto,
  open,
  onClose,
}: {
  concepto: TallerConcepto | null;
  open: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [ficha, setFicha] = useState<FichaTaller | null>(null);
  const [fichaError, setFichaError] = useState("");

  useEffect(() => {
    if (open) {
      setFicha(null);
      setFichaError("");
    }
  }, [open]);

  async function handleFichaFile(file: File) {
    setFichaError("");
    try {
      setFicha(parseFicha(await file.text()));
    } catch (e) {
      setFicha(null);
      setFichaError(e instanceof Error ? e.message : "JSON inválido");
    }
  }

  const edicion = concepto?.ediciones[0];

  const mut = useMutation({
    mutationFn: async (f: FichaTaller) => {
      if (!concepto) throw new Error("No hay taller seleccionado");
      if (!edicion) throw new Error("Este taller no tiene ninguna edición para completar");
      const ed = f.edicion;

      const updatedConcepto = await talleresAdminApi.updateConcepto(concepto.id, {
        nombre: f.nombre,
        subtitulo: f.subtitulo ?? "",
        descripcion: f.descripcion ?? "",
        resumen: f.resumen ?? "",
        publico_objetivo: f.publico_objetivo ?? "",
      });

      const cuentasPago =
        ed.pago_alias || ed.pago_cbu || ed.pago_banco
          ? [{ alias: ed.pago_alias ?? "", cbu: ed.pago_cbu ?? "", banco: ed.pago_banco ?? "" }]
          : undefined;
      const updatedEdicion = await talleresAdminApi.updateEdicion(edicion.id, {
        tipo_taller: ed.tipo_taller || "intensivo",
        horario: ed.horario ?? "",
        cupos_total: ed.cupos_total ?? 12,
        precio_total: ed.precio_total ?? 0,
        precio_sena: ed.precio_sena ?? 0,
        clases: ed.clases,
        ...(ed.direccion ? { direccion: ed.direccion } : {}),
        ...(ed.modalidades?.length ? { modalidades: ed.modalidades } : {}),
        ...(cuentasPago ? { cuentas_pago: cuentasPago } : {}),
      });

      return { updatedConcepto, updatedEdicion };
    },
    onSuccess: ({ updatedConcepto, updatedEdicion }) => {
      toast.success(`Taller actualizado: ${updatedConcepto.nombre}`);
      updateConceptoInCache(qc, updatedConcepto);
      updateEdicionInCache(qc, updatedEdicion);
      onClose();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  if (!concepto) return null;

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Actualizar “{concepto.nombre}” por JSON</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          <p className="text-xs text-muted-foreground">
            Sube la ficha JSON con los datos completos — mismo formato que el alta. Reemplaza el
            contenido del taller y de su primera edición
            {edicion ? ` (#${edicion.numero_edicion})` : ""}.
          </p>

          <div className="flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-border/60 px-6 py-10 text-center">
            <Upload className="h-6 w-6 text-muted-foreground/60" />
            <div className="flex flex-col gap-1">
              <p className="text-sm">Elegí el archivo .json de la ficha</p>
              <p className="text-2xs text-muted-foreground">
                Mismo formato que usa el importador — pedíselo a quien te lo arme.
              </p>
            </div>
            {/* eslint-disable-next-line no-restricted-syntax -- input file: no hay componente DS */}
            <input
              type="file"
              accept="application/json,.json"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void handleFichaFile(f);
              }}
              className="text-sm"
            />
          </div>

          {fichaError && (
            <p className="text-sm text-destructive" role="alert">
              {fichaError}
            </p>
          )}

          {!edicion && (
            <p className="text-sm text-destructive" role="alert">
              Este taller no tiene ninguna edición todavía — creá una primero desde “Nueva edición”.
            </p>
          )}

          {ficha && edicion && (
            <div className="flex flex-col gap-3 rounded-xl border border-border/50 bg-muted/10 p-4">
              <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Listo para actualizar
              </p>
              <div className="flex flex-col gap-1 text-sm">
                <p className="font-semibold text-ink">{ficha.nombre}</p>
                <p className="text-muted-foreground">
                  {ficha.edicion.clases.length} clase
                  {ficha.edicion.clases.length !== 1 ? "s" : ""}
                  {" · "}
                  {ficha.edicion.cupos_total ?? 12} cupos
                </p>
                {ficha.edicion.modalidades && ficha.edicion.modalidades.length > 0 && (
                  <p className="text-muted-foreground">
                    Modalidades: {ficha.edicion.modalidades.map((m) => m.label).join(" · ")}
                  </p>
                )}
              </div>
              <p className="text-2xs text-destructive/80 border-t border-border/40 pt-2">
                Ojo: las {edicion.clases.length} clase{edicion.clases.length !== 1 ? "s" : ""} que
                ya tiene esta edición se van a borrar y reemplazar por las de la ficha (la ficha no
                trae ids que matcheen). El instructor no se toca — se completa a mano.
              </p>
            </div>
          )}
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="ghost">Cancelar</Button>
          </DialogClose>
          <Button
            onClick={() => ficha && mut.mutate(ficha)}
            disabled={mut.isPending || !ficha || !edicion}
            className="gap-2"
          >
            {mut.isPending ? <Spinner size="sm" /> : <FileJson className="h-4 w-4" />}
            Actualizar taller
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
