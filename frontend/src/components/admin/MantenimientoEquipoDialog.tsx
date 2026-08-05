/**
 * Log de mantenimiento por equipo. CRUD inline: agregar nuevo evento (form
 * arriba), listar eventos pasados, editar/eliminar cada uno.
 *
 * Cuando proxima_revision está seteada, se muestra un badge. Si está vencida
 * (fecha pasada), badge en rojo.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, AlertCircle } from "lucide-react";
import { Spinner } from "@/design-system/ui/spinner";
import { StatCard } from "@/design-system/composites/StatCard";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/design-system/ui/dialog";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Label } from "@/design-system/ui/label";
import { Textarea } from "@/design-system/ui/textarea";
import { Badge } from "@/design-system/ui/badge";
import { Switch } from "@/design-system/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/design-system/ui/select";

import { adminApi, type Equipo, type MantenimientoInput } from "@/lib/admin/api";
import { useConfirm } from "@/components/admin/useConfirm";
import { formatARS } from "@/lib/format";
import { hoyAR } from "@/lib/rental-dates";

const TIPOS = [
  { value: "revision", label: "Revisión" },
  { value: "reparacion", label: "Reparación" },
  { value: "limpieza", label: "Limpieza" },
  { value: "otro", label: "Otro" },
];

const fmtFecha = (iso: string) => {
  try {
    return new Date(iso + "T00:00:00").toLocaleDateString("es-AR", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
};

const fmtMoneda = (n: number) => formatARS(n);

/** Hoy en hora de Argentina — helper único (`lib/rental-dates`). Acá vivía una
 *  copia local del mismo fix; se retiró al centralizarlo (2026-08-02). */
const hoyISO = hoyAR;

export function MantenimientoEquipoDialog({
  equipo,
  open,
  onOpenChange,
}: {
  equipo: Equipo | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const queryKey = ["admin", "equipo-mantenimiento", equipo?.id];

  const logQ = useQuery({
    queryKey,
    queryFn: () => adminApi.listMantenimiento(equipo!.id),
    enabled: !!equipo?.id && open,
  });

  // Form state para agregar nuevo evento
  const [fecha, setFecha] = useState(hoyISO());
  const [tipo, setTipo] = useState("revision");
  const [descripcion, setDescripcion] = useState("");
  const [costo, setCosto] = useState<string>("");
  const [proximaRevision, setProximaRevision] = useState("");
  // Bloqueo de disponibilidad
  const [bloqueaStock, setBloqueaStock] = useState(false);
  const [fechaHasta, setFechaHasta] = useState("");
  const [cantidadBloqueo, setCantidadBloqueo] = useState<string>("1");

  const resetForm = () => {
    setFecha(hoyISO());
    setTipo("revision");
    setDescripcion("");
    setCosto("");
    setProximaRevision("");
    setBloqueaStock(false);
    setFechaHasta("");
    setCantidadBloqueo("1");
  };

  const addMut = useMutation({
    mutationFn: (input: MantenimientoInput) => adminApi.addMantenimiento(equipo!.id, input),
    onSuccess: () => {
      toast.success("Evento agregado");
      resetForm();
      qc.invalidateQueries({ queryKey });
    },
    onError: (e: Error) => toast.error(`No se pudo agregar: ${e.message}`),
  });

  const deleteMut = useMutation({
    mutationFn: (logId: number) => adminApi.deleteMantenimiento(equipo!.id, logId),
    onSuccess: () => {
      toast.success("Evento eliminado");
      qc.invalidateQueries({ queryKey });
    },
    onError: (e: Error) => toast.error(`No se pudo eliminar: ${e.message}`),
  });

  const handleAdd = () => {
    if (!fecha) {
      toast.error("Fecha requerida");
      return;
    }
    if (bloqueaStock && fechaHasta && fechaHasta < fecha) {
      toast.error("La fecha de fin del bloqueo no puede ser anterior a la fecha");
      return;
    }
    addMut.mutate({
      fecha,
      tipo,
      descripcion: descripcion.trim() || null,
      costo: costo.trim() ? Math.max(0, Math.floor(Number(costo))) : null,
      proxima_revision: proximaRevision.trim() || null,
      bloquea_stock: bloqueaStock,
      fecha_hasta: bloqueaStock ? fechaHasta.trim() || fecha : null,
      cantidad: bloqueaStock ? Math.max(1, Math.floor(Number(cantidadBloqueo) || 1)) : 1,
    });
  };

  const proxima = logQ.data?.stats.proxima_revision;
  const vencida = !!proxima && proxima < hoyISO();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-full sm:max-w-3xl max-h-[92vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display text-xl">Mantenimiento</DialogTitle>
          {equipo && <p className="text-sm text-muted-foreground">{equipo.nombre}</p>}
        </DialogHeader>

        {/* Stats */}
        {logQ.data && (
          <div className="grid grid-cols-3 gap-2">
            <StatCard label="Eventos" value={logQ.data.stats.total_eventos} size="md" />
            <StatCard
              label="Costo total"
              value={fmtMoneda(logQ.data.stats.total_costo)}
              size="md"
            />
            <StatCard
              label="Próxima revisión"
              value={proxima ? fmtFecha(proxima) : "—"}
              icon={vencida ? AlertCircle : undefined}
              tone={vencida ? "destructive" : "default"}
              size="md"
            />
          </div>
        )}

        {/* Form para agregar nuevo */}
        <section className="rounded-md border hairline bg-amber-soft/30 p-3 space-y-2">
          <p className="text-xs font-medium text-ink/80">Nuevo evento</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <div className="space-y-1">
              <Label className="text-2xs uppercase tracking-wide text-muted-foreground">
                Fecha
              </Label>
              <Input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label className="text-2xs uppercase tracking-wide text-muted-foreground">Tipo</Label>
              <Select value={tipo} onValueChange={setTipo}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TIPOS.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-2xs uppercase tracking-wide text-muted-foreground">
                Costo (ARS)
              </Label>
              <Input
                type="number"
                min={0}
                value={costo}
                onChange={(e) => setCosto(e.target.value)}
                placeholder="—"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-2xs uppercase tracking-wide text-muted-foreground">
                Próxima revisión
              </Label>
              <Input
                type="date"
                value={proximaRevision}
                onChange={(e) => setProximaRevision(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-1">
            <Label className="text-2xs uppercase tracking-wide text-muted-foreground">
              Descripción / Notas
            </Label>
            <Textarea
              rows={2}
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
              placeholder="Qué se hizo / qué pieza se cambió / qué hay que mirar la próxima…"
            />
          </div>

          {/* Bloqueo de disponibilidad */}
          <div className="rounded-md border hairline bg-background/60 p-2.5 space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div className="space-y-0.5">
                <Label className="text-xs font-medium text-ink/80">Bloquear disponibilidad</Label>
                <p className="text-2xs text-muted-foreground">
                  El equipo no se podrá alquilar mientras esté en mantenimiento.
                </p>
              </div>
              <Switch checked={bloqueaStock} onCheckedChange={setBloqueaStock} />
            </div>
            {bloqueaStock && (
              <div className="grid grid-cols-2 gap-2 pt-1">
                <div className="space-y-1">
                  <Label className="text-2xs uppercase tracking-wide text-muted-foreground">
                    Fuera de servicio hasta
                  </Label>
                  <Input
                    type="date"
                    min={fecha}
                    value={fechaHasta}
                    onChange={(e) => setFechaHasta(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-2xs uppercase tracking-wide text-muted-foreground">
                    Unidades afectadas
                  </Label>
                  <Input
                    type="number"
                    min={1}
                    value={cantidadBloqueo}
                    onChange={(e) => setCantidadBloqueo(e.target.value)}
                  />
                </div>
              </div>
            )}
          </div>

          <div className="flex justify-end">
            <Button size="sm" onClick={handleAdd} disabled={addMut.isPending}>
              {addMut.isPending ? (
                <>
                  <Spinner size="xs" className="mr-1" /> Guardando…
                </>
              ) : (
                <>
                  <Plus className="h-3.5 w-3.5 mr-1" /> Agregar evento
                </>
              )}
            </Button>
          </div>
        </section>

        {/* Lista */}
        {logQ.isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
            <Spinner size="sm" /> Cargando…
          </div>
        )}

        {logQ.data && logQ.data.items.length === 0 && (
          <p className="text-sm text-muted-foreground italic py-4 text-center">
            Sin eventos. Agregá el primero arriba.
          </p>
        )}

        {logQ.data && logQ.data.items.length > 0 && (
          <div className="space-y-1.5">
            {logQ.data.items.map((ev) => (
              <div key={ev.id} className="flex items-start gap-2 rounded-md border hairline p-2">
                <div className="flex-1 min-w-0 space-y-1">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-sm font-medium">{fmtFecha(ev.fecha)}</span>
                    <Badge variant="outline" className="text-2xs">
                      {TIPOS.find((t) => t.value === ev.tipo)?.label ?? ev.tipo}
                    </Badge>
                    {ev.costo != null && (
                      <Badge variant="secondary" className="text-2xs tabular-nums">
                        {fmtMoneda(ev.costo)}
                      </Badge>
                    )}
                    {ev.proxima_revision && (
                      <Badge
                        variant={ev.proxima_revision < hoyISO() ? "destructive" : "default"}
                        className="text-2xs"
                      >
                        próx. {fmtFecha(ev.proxima_revision)}
                      </Badge>
                    )}
                    {ev.bloquea_stock && (
                      <Badge variant="destructive" className="text-2xs">
                        bloquea stock{ev.fecha_hasta ? ` → ${fmtFecha(ev.fecha_hasta)}` : ""}
                        {ev.cantidad > 1 ? ` (×${ev.cantidad})` : ""}
                      </Badge>
                    )}
                  </div>
                  {ev.descripcion && (
                    <p className="text-xs text-muted-foreground whitespace-pre-wrap">
                      {ev.descripcion}
                    </p>
                  )}
                </div>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={async () => {
                    if (
                      await confirm({
                        title: "¿Eliminar evento?",
                        description: `Se eliminará el evento del ${fmtFecha(ev.fecha)}.`,
                        danger: true,
                        confirmLabel: "Eliminar",
                      })
                    ) {
                      deleteMut.mutate(ev.id);
                    }
                  }}
                  disabled={deleteMut.isPending}
                  title="Eliminar"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cerrar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
