import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { toast } from "sonner";

import { talleresAdminApi } from "@/lib/admin/api/talleres";
import type { ClaseBody, TallerConcepto } from "@/lib/admin/api/types";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Spinner } from "@/design-system/ui/spinner";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/design-system/ui/dialog";
import { TallerCalendario } from "@/components/talleres/TallerCalendario";
import { ClasesAsistente } from "./ClasesAsistente";

export function NuevoConceptoDialog({
  open,
  onClose,
  onSuccess,
}: {
  open: boolean;
  onClose: () => void;
  onSuccess: (created: TallerConcepto) => void;
}) {
  const [nombre, setNombre] = useState("");
  const [instructorNombre, setInstructorNombre] = useState("");
  const [clases, setClases] = useState<ClaseBody[]>([]);
  const [cupos, setCupos] = useState("12");
  const [precioTotal, setPrecioTotal] = useState("0");
  const [precioSena, setPrecioSena] = useState("0");

  useEffect(() => {
    if (open) {
      setNombre("");
      setInstructorNombre("");
      setClases([]);
      setCupos("12");
      setPrecioTotal("0");
      setPrecioSena("0");
    }
  }, [open]);

  const mut = useMutation({
    mutationFn: (body: object) => talleresAdminApi.createConcepto(body),
    onSuccess: (created) => {
      toast.success(`Taller creado: ${created.nombre}`);
      onSuccess(created);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  function handleSubmit() {
    if (!nombre.trim()) {
      toast.error("Ingresá el nombre del taller");
      return;
    }
    if (!instructorNombre.trim()) {
      toast.error("Ingresá el nombre del/la instructor/a");
      return;
    }
    if (clases.length === 0) {
      toast.error("Agregá al menos una clase");
      return;
    }
    const c = parseInt(cupos, 10);
    const pt = parseInt(precioTotal, 10);
    const ps = parseInt(precioSena, 10);
    if (isNaN(c) || c < 1) {
      toast.error("Cupos inválidos");
      return;
    }
    if (isNaN(pt) || isNaN(ps) || ps > pt) {
      toast.error("Precios inválidos (la seña no puede superar el total)");
      return;
    }
    mut.mutate({
      nombre: nombre.trim(),
      instructor_nombre: instructorNombre.trim(),
      edicion: {
        // `tipo_taller` no tiene UI propia (Escuela v2) — el backend igual lo
        // exige (NOT NULL), así que viaja fijo.
        tipo_taller: "intensivo",
        clases,
        cupos_total: c,
        precio_total: pt,
        precio_sena: ps,
        numero_edicion: 1,
      },
    });
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Nuevo taller</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-5 py-2">
          <div className="grid sm:grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Nombre del taller *
              </label>
              <Input
                value={nombre}
                onChange={(e) => setNombre(e.target.value)}
                placeholder="Ej: Dirección de arte"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Instructor/a *
              </label>
              <Input
                value={instructorNombre}
                onChange={(e) => setInstructorNombre(e.target.value)}
                placeholder="Ej: Jime Troncoso"
              />
            </div>
          </div>

          <div className="border-t border-border/50 pt-4">
            <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground mb-3">
              Clases — 1.ª edición *
            </p>
            <ClasesAsistente clases={clases} onChange={setClases} />
            {clases.length > 0 && (
              <div className="mt-4 pointer-events-none select-none">
                <TallerCalendario sesiones={clases} />
              </div>
            )}
          </div>

          <div className="grid sm:grid-cols-3 gap-4 border-t border-border/50 pt-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Cupos totales
              </label>
              <Input
                type="number"
                min={1}
                value={cupos}
                onChange={(e) => setCupos(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Precio total (ARS)
              </label>
              <Input
                type="number"
                min={0}
                value={precioTotal}
                onChange={(e) => setPrecioTotal(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Seña (ARS)
              </label>
              <Input
                type="number"
                min={0}
                value={precioSena}
                onChange={(e) => setPrecioSena(e.target.value)}
              />
            </div>
          </div>
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="ghost">Cancelar</Button>
          </DialogClose>
          <Button onClick={handleSubmit} disabled={mut.isPending} className="gap-2">
            {mut.isPending ? <Spinner size="sm" /> : <Plus className="h-4 w-4" />}
            Crear taller
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
