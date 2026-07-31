import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  CheckCircle2,
  Clock,
  Download,
  ExternalLink,
  Send,
  Trash2,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import { talleresAdminApi } from "@/lib/admin/api/talleres";
import type { EdicionAdmin, Inscripcion, TallerConcepto } from "@/lib/admin/api/types";
import { Button } from "@/design-system/ui/button";
import { Textarea } from "@/design-system/ui/textarea";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/design-system/ui/dialog";
import { Spinner } from "@/design-system/ui/spinner";
import { useConfirm } from "@/components/admin/useConfirm";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { ListSkeleton } from "@/components/admin/skeletons";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { KpisStrip } from "./KpisStrip";

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("es-AR", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function InscripcionesSection({
  edicion,
  concepto,
  inscripciones,
  loading,
}: {
  edicion: EdicionAdmin;
  concepto: TallerConcepto;
  inscripciones: Inscripcion[];
  loading: boolean;
}) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [notifMsg, setNotifMsg] = useState("");
  const [notifOpen, setNotifOpen] = useState(false);

  const confirmadas = inscripciones.filter((i) => !i.en_lista_espera);
  const espera = inscripciones.filter((i) => i.en_lista_espera);

  const eliminarMut = useMutation({
    mutationFn: (insId: number) => talleresAdminApi.eliminarInscripcion(concepto.id, insId),
    onSuccess: () => {
      toast.success("Inscripción eliminada");
      qc.invalidateQueries({ queryKey: ["admin", "ediciones", edicion.id, "inscripciones"] });
      qc.invalidateQueries({ queryKey: ["admin", "talleres"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const confirmarMut = useMutation({
    mutationFn: (insId: number) => talleresAdminApi.confirmarInscripcion(concepto.id, insId),
    onSuccess: () => {
      toast.success("Inscripción confirmada");
      qc.invalidateQueries({ queryKey: ["admin", "ediciones", edicion.id, "inscripciones"] });
      qc.invalidateQueries({ queryKey: ["admin", "talleres"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  // F4b: seña + ofrecer cupo al siguiente.
  const verificarSenaMut = useMutation({
    mutationFn: (insId: number) => talleresAdminApi.verificarSena(concepto.id, insId),
    onSuccess: () => {
      toast.success("Seña verificada — mail de confirmación enviado");
      qc.invalidateQueries({ queryKey: ["admin", "ediciones", edicion.id, "inscripciones"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const ofrecerCupoMut = useMutation({
    mutationFn: (insId: number) => talleresAdminApi.ofrecerCupo(concepto.id, insId),
    onSuccess: () => {
      toast.success("Cupo ofrecido — mail con el link enviado");
      qc.invalidateQueries({ queryKey: ["admin", "ediciones", edicion.id, "inscripciones"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const notificarMut = useMutation({
    mutationFn: (mensaje: string) => talleresAdminApi.notificarCambios(concepto.id, mensaje),
    onSuccess: (r) => {
      toast.success(`Notificaciones enviadas: ${r.enviados} ok, ${r.fallidos} fallidas`);
      setNotifOpen(false);
      setNotifMsg("");
    },
    onError: (e) => toast.error((e as Error).message),
  });

  async function handleCsvDownload() {
    try {
      const res = await talleresAdminApi.exportInscripcionesCsv(concepto.id);
      if (!res.ok) throw new Error(`Error ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `inscripciones-${concepto.slug_base}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function handleEliminar(ins: Inscripcion) {
    const label = ins.en_lista_espera ? "de lista de espera" : "confirmada";
    if (
      !(await confirm({
        title: "¿Eliminar inscripción?",
        description: `Se eliminará la inscripción ${label} de ${ins.nombre}.`,
        danger: true,
        confirmLabel: "Eliminar",
      }))
    )
      return;
    eliminarMut.mutate(ins.id);
  }

  if (loading) return <ListSkeleton rows={4} />;

  if (inscripciones.length === 0) {
    return <EmptyState icon={<Users className="h-6 w-6" />} title="No hay inscripciones todavía" />;
  }

  const insTable = (rows: Inscripcion[], showConfirmar: boolean) => {
    const columns: Column<Inscripcion>[] = [
      {
        header: "Nombre",
        cell: (ins) => ins.nombre,
        className: "font-medium text-ink",
      },
      {
        header: "Email",
        cell: (ins) => (
          <a href={`mailto:${ins.email}`} className="hover:text-ink transition">
            {ins.email}
          </a>
        ),
        className: "text-muted-foreground",
      },
      {
        header: "Teléfono",
        cell: (ins) => ins.telefono,
        className: "text-muted-foreground hidden sm:table-cell",
        headClassName: "hidden sm:table-cell",
      },
      {
        header: "Experiencia",
        cell: (ins) => ins.experiencia || "—",
        className: "text-muted-foreground hidden lg:table-cell max-w-[180px] truncate",
        headClassName: "hidden lg:table-cell",
      },
      {
        header: "Comp.",
        cell: (ins) =>
          ins.comprobante_url ? (
            <a
              href={ins.comprobante_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-ink hover:text-ink transition"
            >
              <CheckCircle2 className="h-3.5 w-3.5 text-verde-ink" strokeWidth={1.5} />
              <ExternalLink className="h-3 w-3" />
            </a>
          ) : (
            <span className="text-muted-foreground/50 text-xs">—</span>
          ),
      },
      {
        header: "Fecha",
        cell: (ins) => (
          <span className="inline-flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {fmtDate(ins.created_at)}
          </span>
        ),
        className: "text-muted-foreground text-xs",
      },
      {
        header: "",
        cell: (ins) => (
          <div className="flex items-center gap-1">
            {!showConfirmar && ins.estado === "pendiente_sena" && (
              <Button
                variant="outline"
                size="sm"
                className="h-7 px-2 text-xs"
                disabled={verificarSenaMut.isPending}
                onClick={() => verificarSenaMut.mutate(ins.id)}
              >
                Verificar seña
              </Button>
            )}
            {showConfirmar && ins.estado === "cupo_ofrecido" ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-muted/50 px-2 py-1 text-2xs text-muted-foreground">
                <Send className="h-3 w-3" />
                Oferta enviada
              </span>
            ) : (
              showConfirmar && (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    disabled={confirmarMut.isPending}
                    onClick={() => confirmarMut.mutate(ins.id)}
                  >
                    Confirmar
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    disabled={ofrecerCupoMut.isPending}
                    onClick={() => ofrecerCupoMut.mutate(ins.id)}
                  >
                    Ofrecer cupo
                  </Button>
                </>
              )
            )}
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
              disabled={eliminarMut.isPending}
              onClick={() => handleEliminar(ins)}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        ),
      },
    ];
    return <AdminTable columns={columns} rows={rows} getRowKey={(ins) => ins.id} />;
  };

  return (
    <>
      <div className="mb-5">
        <KpisStrip edicionId={edicion.id} />
      </div>

      {confirmadas.length > 0 && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
              Confirmadas ({confirmadas.length})
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 h-7 text-xs"
                onClick={handleCsvDownload}
              >
                <Download className="h-3 w-3" />
                CSV
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 h-7 text-xs"
                onClick={() => setNotifOpen(true)}
              >
                <Bell className="h-3 w-3" />
                Notificar cambios
              </Button>
            </div>
          </div>
          {insTable(confirmadas, false)}
        </div>
      )}

      {espera.length > 0 && (
        <div
          className={`flex flex-col gap-3${confirmadas.length > 0 ? " border-t border-border/40 pt-5 mt-2" : ""}`}
        >
          <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
            Lista de espera ({espera.length})
          </p>
          {insTable(espera, true)}
        </div>
      )}

      <Dialog open={notifOpen} onOpenChange={setNotifOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Notificar cambios a inscriptos</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-2">
            <p className="text-sm text-muted-foreground">
              Se enviará un email a los {confirmadas.length} inscriptos confirmados.
            </p>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Mensaje (opcional)
              </label>
              <Textarea
                rows={4}
                value={notifMsg}
                onChange={(e) => setNotifMsg(e.target.value)}
                placeholder="Ej: Cambiamos el horario a las 10 hs."
                className="resize-none"
              />
            </div>
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="ghost">Cancelar</Button>
            </DialogClose>
            <Button
              onClick={() => notificarMut.mutate(notifMsg)}
              disabled={notificarMut.isPending}
              className="gap-2"
            >
              {notificarMut.isPending ? <Spinner size="sm" /> : <Bell className="h-4 w-4" />}
              Enviar notificaciones
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
