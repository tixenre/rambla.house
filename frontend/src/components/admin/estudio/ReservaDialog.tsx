/**
 * ReservaDialog — alta/edición de un turno del Estudio desde el back-office
 * (#1283 Fase 6). Sin sesión de cliente ni Didit ni anticipación mínima (eso
 * es del flujo público) — acá el admin carga a mano: cliente real o texto
 * libre, promo, equipos sueltos, override del precio del espacio.
 *
 * El modo EDICIÓN delega en `ReservaEstudioSection` (Fase 2, #1308) — la
 * misma sección que usa la página del pedido, una sola forma de editar un
 * turno existente (franja, tarifa, promo, sueltos, guardado). Este diálogo
 * conserva solo lo propio del ALTA (cliente + estado inicial), que no aplica
 * a un pedido ya creado.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
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
import { Spinner } from "@/design-system/ui/spinner";
import { formatARS } from "@/lib/format";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { buildTimeSlots } from "@/lib/estudio-slots";
import {
  adminApi,
  estudioAdminApi,
  type Cliente,
  type Equipo,
  type EstudioConfig,
  type EstudioReservaListItem,
} from "@/lib/admin/api";
import { nombreCliente } from "@/lib/cliente-nombre";
import { ClienteAutocomplete } from "@/components/admin/pedido/ClienteAutocomplete";
import { Field } from "./shared";
import { ReservaEstudioSection } from "./ReservaEstudioSection";
import { EstudioIncluyeList, type SueltoLocal } from "./EstudioIncluyeList";

function todayYmd(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function ReservaDialog({
  open,
  onOpenChange,
  reserva,
  estudio,
  onSaved,
  pedidoVinculado,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** null = alta nueva. Presente = editar este turno existente. */
  reserva: EstudioReservaListItem | null;
  estudio: EstudioConfig;
  onSaved: () => void;
  /** Alta de un turno DESDE la página de un pedido de alquiler normal
   *  (#1308, sección "Reserva del Estudio"): el cliente se hereda de ese
   *  pedido — oculta el picker y manda `pedido_principal_id` en vez de
   *  cliente_id/nombre. Solo aplica al modo alta (`reserva == null`). */
  pedidoVinculado?: { id: number; clienteNombre: string | null };
}) {
  const editando = !!reserva;

  // El detalle completo (items) solo hace falta para editar — hidrata
  // `ReservaEstudioSection`; la lista no trae con_promo/sueltos.
  const detalleQ = useQuery({
    queryKey: ["admin", "pedido", reserva?.id],
    queryFn: () => adminApi.getPedido(reserva!.id),
    enabled: open && editando,
  });

  // Todo lo de acá en más es EXCLUSIVO del alta — el modo edición delega
  // por completo en `ReservaEstudioSection` (ver el render, abajo).
  const [fecha, setFecha] = useState(todayYmd());
  const [start, setStart] = useState("");
  const [horas, setHoras] = useState(estudio.min_horas || 2);
  const [clienteId, setClienteId] = useState<number | null>(null);
  const [clienteNombreElegido, setClienteNombreElegido] = useState<string | null>(null);
  const [clienteNombreLibre, setClienteNombreLibre] = useState("");
  const [conPromo, setConPromo] = useState(false);
  const [pinturaReciente, setPinturaReciente] = useState(false);
  const [sueltos, setSueltos] = useState<SueltoLocal[]>([]);
  const [espacioOverride, setEspacioOverride] = useState<string>("");
  const [estadoAlta, setEstadoAlta] = useState<"solicitado" | "confirmado" | "retirado">(
    "confirmado",
  );

  const slots = useMemo(
    () => buildTimeSlots(estudio.open_hour, estudio.close_hour, estudio.min_horas || 1),
    [estudio.open_hour, estudio.close_hour, estudio.min_horas],
  );

  // Reset al abrir un alta nueva (editar hidrata su propia sección, no acá).
  useEffect(() => {
    if (!open || editando) return;
    setFecha(todayYmd());
    setStart(slots[0]?.value ?? "");
    setHoras(estudio.min_horas || 2);
    setClienteId(null);
    setClienteNombreElegido(null);
    setClienteNombreLibre("");
    setConPromo(false);
    setPinturaReciente(false);
    setSueltos([]);
    setEspacioOverride("");
    setEstadoAlta("confirmado");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- solo al abrir, no en cada cambio de campo
  }, [open, editando]);

  const sueltosInput = useMemo(
    () => sueltos.map((s) => ({ equipo_id: s.equipo_id, cantidad: s.cantidad })),
    [sueltos],
  );

  const cotizarParams = useMemo(
    () => ({
      fecha,
      start,
      horas,
      con_promo: conPromo,
      pintura_reciente: pinturaReciente,
      sueltos: sueltosInput,
    }),
    [fecha, start, horas, conPromo, pinturaReciente, sueltosInput],
  );
  const cotizarDebounced = useDebouncedValue(cotizarParams, 400);

  const cotizarQ = useQuery({
    queryKey: ["admin", "estudio", "cotizar", cotizarDebounced],
    // Solo el alta cotiza acá — editar cotiza dentro de `ReservaEstudioSection`.
    enabled: open && !editando && !!fecha && !!start && horas >= (estudio.min_horas || 1),
    queryFn: () => estudioAdminApi.cotizarReserva(cotizarDebounced),
  });

  const mutation = useMutation({
    mutationFn: () =>
      estudioAdminApi.createReserva({
        fecha,
        start,
        horas,
        // Vinculado: el cliente lo resuelve el backend desde el pedido
        // principal — no mandamos cliente_id/nombre de acá (el picker ni
        // siquiera se muestra en ese caso, ver el render).
        ...(pedidoVinculado
          ? { pedido_principal_id: pedidoVinculado.id }
          : {
              cliente_id: clienteId,
              cliente_nombre: clienteId ? null : clienteNombreLibre.trim() || null,
            }),
        con_promo: conPromo,
        pintura_reciente: pinturaReciente,
        sueltos: sueltosInput,
        espacio_monto: espacioOverride.trim() ? Number(espacioOverride) : null,
        estado: estadoAlta,
      }),
    onSuccess: (pedido) => {
      toast.success("Turno creado");
      if (pedido.promo_advertencia) {
        toast.warning("La promo se reservó incompleta", {
          description: pedido.promo_advertencia,
          duration: 7000,
        });
      }
      onSaved();
      onOpenChange(false);
    },
    onError: (e) => toast.error("No se pudo guardar", { description: (e as Error).message }),
  });

  const handleAddSuelto = (eq: Equipo) => {
    setSueltos((prev) => {
      const existing = prev.find((s) => s.equipo_id === eq.id);
      if (existing) {
        return prev.map((s) => (s.equipo_id === eq.id ? { ...s, cantidad: s.cantidad + 1 } : s));
      }
      return [
        ...prev,
        {
          equipo_id: eq.id,
          nombre: eq.nombre,
          marca: eq.marca,
          nombre_publico: eq.nombre_publico,
          foto_url: eq.foto_url,
          precio_jornada: eq.precio_jornada,
          cantidad: 1,
        },
      ];
    });
  };
  const handleRemoveSuelto = (equipoId: number) =>
    setSueltos((prev) => prev.filter((x) => x.equipo_id !== equipoId));
  const handleChangeSueltoCantidad = (equipoId: number, cantidad: number) =>
    setSueltos((prev) => prev.map((x) => (x.equipo_id === equipoId ? { ...x, cantidad } : x)));

  const puedeGuardar = !!fecha && !!start && horas >= (estudio.min_horas || 1);
  const cotiz = cotizarQ.data;
  const cargandoDetalle = editando && detalleQ.isLoading;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {editando
              ? `Editar turno #${reserva?.numero_pedido ?? reserva?.id}`
              : pedidoVinculado
                ? "Nuevo turno del Estudio"
                : "Nuevo turno"}
          </DialogTitle>
        </DialogHeader>

        {editando ? (
          cargandoDetalle ? (
            <div className="flex justify-center py-10">
              <Spinner />
            </div>
          ) : detalleQ.data ? (
            <ReservaEstudioSection
              pedido={detalleQ.data}
              estudio={estudio}
              onSaved={() => {
                onSaved();
                onOpenChange(false);
              }}
            />
          ) : null
        ) : (
          <div className="space-y-4 py-2">
            <div className="grid grid-cols-3 gap-3">
              <Field label="Fecha">
                <Input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />
              </Field>
              <Field label="Hora">
                <select
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                  className="h-9 w-full rounded-md border hairline bg-background px-2 text-sm"
                >
                  {slots.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={`Horas · mín ${estudio.min_horas}`}>
                <Input
                  type="number"
                  min={estudio.min_horas || 1}
                  value={horas}
                  onChange={(e) => setHoras(Number(e.target.value) || 0)}
                />
              </Field>
            </div>

            {pedidoVinculado ? (
              <Field label="Cliente" hint="Heredado del pedido al que se vincula este turno.">
                <div className="rounded-md border hairline bg-muted/20 px-2.5 py-1.5 text-sm text-muted-foreground">
                  {pedidoVinculado.clienteNombre || "Sin cliente"}
                </div>
              </Field>
            ) : (
              <Field label="Cliente (ficha o texto libre)">
                {clienteId ? (
                  <div className="flex items-center gap-2 rounded-md border hairline px-2.5 py-1.5 text-sm">
                    <span className="flex-1 truncate">{clienteNombreElegido}</span>
                    <button
                      type="button"
                      onClick={() => {
                        setClienteId(null);
                        setClienteNombreElegido(null);
                      }}
                      className="text-muted-foreground hover:text-ink"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <ClienteAutocomplete
                      onPick={(c: Cliente) => {
                        setClienteId(c.id);
                        setClienteNombreElegido(nombreCliente(c));
                      }}
                    />
                    <Input
                      value={clienteNombreLibre}
                      onChange={(e) => setClienteNombreLibre(e.target.value)}
                      placeholder="…o nombre sin ficha (alguien que llamó)"
                    />
                  </div>
                )}
              </Field>
            )}

            <EstudioIncluyeList
              estudio={estudio}
              horas={horas}
              conPromo={conPromo}
              onTogglePromo={setConPromo}
              pinturaReciente={pinturaReciente}
              onTogglePintura={setPinturaReciente}
              sueltos={sueltos}
              onAddSuelto={handleAddSuelto}
              onRemoveSuelto={handleRemoveSuelto}
              onChangeSueltoCantidad={handleChangeSueltoCantidad}
              espacioOverride={espacioOverride}
              onChangeEspacioOverride={setEspacioOverride}
              cotiz={cotiz}
            />

            <Field label="Estado inicial">
              <select
                value={estadoAlta}
                onChange={(e) => setEstadoAlta(e.target.value as typeof estadoAlta)}
                className="h-9 w-full rounded-md border hairline bg-background px-2 text-sm"
              >
                <option value="solicitado">Solicitado</option>
                <option value="confirmado">Confirmado</option>
                <option value="retirado">Retirado</option>
              </select>
            </Field>

            {/* Total en vivo — el front no calcula, solo muestra (2026-06-29). */}
            <div className="rounded-lg border hairline bg-muted/20 p-3 text-sm">
              {cotizarQ.isLoading ? (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Spinner size="sm" /> Calculando…
                </div>
              ) : cotiz ? (
                <div className="space-y-1">
                  <div className="flex justify-between font-semibold text-ink">
                    <span>Total</span>
                    <span>{formatARS(cotiz.monto_total)}</span>
                  </div>
                  {!cotiz.espacio_disponible && (
                    <p className="mt-1 text-xs text-destructive">
                      El espacio no está disponible: {cotiz.espacio_motivo}
                    </p>
                  )}
                </div>
              ) : null}
            </div>
          </div>
        )}

        <DialogFooter>
          {editando ? (
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cerrar
            </Button>
          ) : (
            <>
              <Button variant="ghost" onClick={() => onOpenChange(false)}>
                Cancelar
              </Button>
              <Button
                onClick={() => mutation.mutate()}
                disabled={!puedeGuardar || mutation.isPending}
              >
                {mutation.isPending ? <Spinner size="sm" className="mr-1.5" /> : null}
                Crear turno
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
