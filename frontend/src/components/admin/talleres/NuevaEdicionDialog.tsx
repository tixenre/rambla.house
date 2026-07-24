import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { toast } from "sonner";

import { talleresAdminApi } from "@/lib/admin/api/talleres";
import type { ClaseBody, EdicionAdmin, TallerConcepto } from "@/lib/admin/api/types";
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

export function NuevaEdicionDialog({
  concepto,
  open,
  onClose,
  onSuccess,
}: {
  concepto: TallerConcepto | null;
  open: boolean;
  onClose: () => void;
  onSuccess: (created: EdicionAdmin) => void;
}) {
  const nextNumero =
    concepto && concepto.ediciones.length > 0
      ? Math.max(...concepto.ediciones.map((e) => e.numero_edicion)) + 1
      : 1;

  const [clases, setClases] = useState<ClaseBody[]>([]);
  const [cupos, setCupos] = useState("12");
  const [precioTotal, setPrecioTotal] = useState("0");
  const [precioSena, setPrecioSena] = useState("0");

  useEffect(() => {
    if (open) {
      setClases([]);
      setCupos("12");
      setPrecioTotal("0");
      setPrecioSena("0");
    }
  }, [open]);

  const mut = useMutation({
    mutationFn: (body: object) => talleresAdminApi.createEdicion(concepto!.id, body),
    onSuccess: (created) => {
      toast.success(`Edición #${created.numero_edicion} creada (en borrador)`);
      onSuccess(created);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  // F2: precarga las clases de la última edición (contenido + portada
  // incluidos — viajan como clases NUEVAS, sin id, con su portada_media_id).
  // El admin ajusta las fechas y listo: no re-carga el temario.
  function copiarClasesAnterior() {
    const ultima = concepto?.ediciones[concepto.ediciones.length - 1];
    if (!ultima || ultima.clases.length === 0) {
      toast.error("La edición anterior no tiene clases");
      return;
    }
    setClases(
      ultima.clases.map((c) => ({
        fecha: c.fecha,
        hora_inicio_min: c.hora_inicio_min,
        hora_fin_min: c.hora_fin_min,
        titulo: c.titulo ?? "",
        descripcion: c.descripcion ?? "",
        nota: c.nota ?? "",
        portada_media_id: c.portada_media_id ?? null,
        portada_url: c.portada_url ?? "",
      })),
    );
    setCupos(String(ultima.cupos_total));
    setPrecioTotal(String(ultima.precio_total));
    setPrecioSena(String(ultima.precio_sena));
    toast.success(
      `${ultima.clases.length} clases copiadas de la edición #${ultima.numero_edicion} — ajustá las fechas`,
    );
  }

  function handleSubmit() {
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
      // `tipo_taller` no tiene UI propia (Escuela v2) — el backend igual lo
      // exige (NOT NULL), así que viaja fijo.
      tipo_taller: "intensivo",
      clases,
      cupos_total: c,
      precio_total: pt,
      precio_sena: ps,
      numero_edicion: nextNumero,
    });
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            Nueva edición — {concepto?.nombre}
            <span className="ml-2 text-sm font-normal text-muted-foreground">#{nextNumero}</span>
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-5 py-2">
          <div className="border-b border-border/50 pb-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Clases *
              </p>
              {concepto && concepto.ediciones.length > 0 && (
                <Button variant="outline" size="sm" onClick={copiarClasesAnterior}>
                  Copiar clases de la edición anterior
                </Button>
              )}
            </div>
            <ClasesAsistente clases={clases} onChange={setClases} />
            {clases.length > 0 && (
              <div className="mt-4 pointer-events-none select-none">
                <TallerCalendario sesiones={clases} />
              </div>
            )}
          </div>

          <div className="grid sm:grid-cols-3 gap-4">
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
            Crear edición
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
