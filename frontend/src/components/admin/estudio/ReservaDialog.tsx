/**
 * ReservaDialog — edición de un turno del Estudio desde el back-office
 * (#1283 Fase 6). Sin sesión de cliente ni Didit ni anticipación mínima (eso
 * es del flujo público) — acá el admin carga a mano: cliente real o texto
 * libre, promo, equipos sueltos, override del precio del espacio.
 *
 * El modo EDICIÓN delega en `ReservaEstudioSection` (Fase 2, #1308). El modo
 * ALTA (`reserva == null`) sigue soportado acá abajo por si vuelve a hacer
 * falta, pero HOY no tiene ningún caller real: `ReservasSection` (único
 * consumidor de este Dialog) solo lo abre para editar, y la agenda del
 * Estudio ya NO tiene un botón "Nuevo turno" — el turno se carga desde un
 * pedido de alquiler (`TurnosEstudioSection`, que monta `NuevoTurnoEstudioForm`
 * directo, sin este Dialog) — decisión del dueño, 2026-07-30, una sola forma
 * de crear un turno. Un turno "solo estudio" arranca de un pedido vacío
 * (sin equipos, soportado desde #1313/#1314).
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
