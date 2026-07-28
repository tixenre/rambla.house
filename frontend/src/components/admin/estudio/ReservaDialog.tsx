/**
 * ReservaDialog — alta/edición de un turno del Estudio desde el back-office
 * (#1283 Fase 6). Sin sesión de cliente ni Didit ni anticipación mínima (eso
 * es del flujo público) — acá el admin carga a mano: cliente real o texto
 * libre, promo, equipos sueltos, override del precio del espacio.
 *
 * El modo EDICIÓN delega en `ReservaEstudioSection` (Fase 2, #1308) y el
 * modo ALTA en `NuevoTurnoEstudioForm` (#1308, ask del dueño de sacar el
 * modal de la página del pedido) — ambos, la misma pieza que usan otras
 * superficies; este diálogo es solo el Dialog-chrome + el detalle a editar.
 * Sigue siendo el punto de entrada de la agenda del Estudio
 * (`ReservasSection`), donde SÍ tiene sentido un popup (alta/edición desde
 * un calendario) — la página del pedido (`TurnosEstudioSection`) monta
 * `NuevoTurnoEstudioForm` directo, sin este Dialog.
 */
import { useQuery } from "@tanstack/react-query";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/design-system/ui/dialog";
import { Button } from "@/design-system/ui/button";
import { Spinner } from "@/design-system/ui/spinner";
import { adminApi, type EstudioConfig, type EstudioReservaListItem } from "@/lib/admin/api";
import { ReservaEstudioSection } from "./ReservaEstudioSection";
import { NuevoTurnoEstudioForm } from "./NuevoTurnoEstudioForm";

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
   *  (#1308, sección "Turnos del Estudio"): el cliente Y el estado inicial
   *  se heredan de ese pedido. Solo aplica al modo alta (`reserva == null`)
   *  — hoy este caso ya no pasa por acá (`TurnosEstudioSection` monta
   *  `NuevoTurnoEstudioForm` directo), pero el prop se conserva por si otro
   *  caller futuro sí necesita el alta vinculada dentro de un Dialog. */
  pedidoVinculado?: { id: number; clienteNombre: string | null; estado: string };
}) {
  const editando = !!reserva;

  // El detalle completo (items) solo hace falta para editar — hidrata
  // `ReservaEstudioSection`; la lista no trae con_promo/sueltos.
  const detalleQ = useQuery({
    queryKey: ["admin", "pedido", reserva?.id],
    queryFn: () => adminApi.getPedido(reserva!.id),
    enabled: open && editando,
  });

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
          open && (
            <NuevoTurnoEstudioForm
              estudio={estudio}
              pedidoVinculado={pedidoVinculado}
              onCreated={() => {
                onSaved();
                onOpenChange(false);
              }}
              onCancel={() => onOpenChange(false)}
            />
          )
        )}

        {editando && (
          <DialogFooter>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cerrar
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
