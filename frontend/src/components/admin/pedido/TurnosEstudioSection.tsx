/**
 * TurnosEstudioSection — turnos del Estudio vinculados a un pedido de
 * alquiler normal (#1308: "quiero un solo modal, el de los pedidos... que
 * mantenga la función actual de equipos, pero también una sección para el
 * Estudio"; afinado dos veces más — "no quiero el modal... como si fuera el
 * listado de equipos" y después "quiero una lista para seleccionar, como con
 * los equipos" — hasta terminar en: el compose de un turno nuevo queda
 * SIEMPRE visible acá abajo, igual que el buscador de "Equipos" nunca está
 * escondido detrás de un botón). Un pedido de rental (equipos por rango de
 * días) y un turno del Estudio (franja horaria puntual) son registros
 * DISTINTOS — no pueden ser una sola fila (`fecha_desde`/`fecha_hasta`
 * significan cosas incompatibles, ver `lib/tipos-pedido.ts`) — pero se
 * administran en una sola pantalla: esta sección los lista inline (reusando
 * `ReservaEstudioSection`, la misma pieza que ya usa un pedido
 * `tipo='estudio'`) y deja componer uno nuevo sin salir de acá ni abrir un
 * diálogo (`NuevoTurnoEstudioForm chrome="inline"`, misma pieza que usa
 * `ReservaDialog` para el alta desde la agenda del Estudio, en modo
 * `chrome="dialog"`). El `key={composeKey}` fuerza un remount tras crear un
 * turno — así el compose vuelve limpio, listo para otro, sin estado colgado
 * del anterior. El backend garantiza que el turno nunca pueda mostrar un
 * cliente distinto al del pedido principal (`pedido_principal_id`, hereda
 * SIEMPRE el contacto de acá — ver `routes/estudio.py::_resolver_pedido_principal`).
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, Plus, X } from "lucide-react";
import { toast } from "sonner";

import { Section } from "@/design-system/composites/Section";
import { Spinner } from "@/design-system/ui/spinner";
import { adminApi, estudioAdminApi, type Pedido } from "@/lib/admin/api";
import { ReservaEstudioSection } from "@/components/admin/estudio/ReservaEstudioSection";
import { NuevoTurnoEstudioForm } from "@/components/admin/estudio/NuevoTurnoEstudioForm";

function TurnoVinculadoCard({
  turnoId,
  pedidoPrincipalId,
}: {
  turnoId: number;
  pedidoPrincipalId: number;
}) {
  const qc = useQueryClient();
  const estudioQ = useQuery({
    queryKey: ["admin", "estudio"],
    queryFn: () => estudioAdminApi.get(),
  });
  const turnoQ = useQuery({
    queryKey: ["admin", "pedido", turnoId],
    queryFn: () => adminApi.getPedido(turnoId),
  });

  // La ✕ BORRA el turno, no lo cancela (pedido del dueño: "que se comporte como
  // cuando saco un equipo, simplemente se borra y listo"). Un turno que se saca
  // del pedido no es una venta cancelada que haya que conservar en el historial
  // — es una línea que nunca terminó de existir, igual que un equipo que sumaste
  // y sacaste. Antes quedaba como una tarjeta "Cancelado" colgada en la sección.
  // Hard delete real, la misma primitiva que "Eliminar pedido"
  // (`DELETE /alquileres/{id}`, que ya borra ítems y pagos en cascada); el
  // backend lo frena si el turno tiene plata cobrada encima.
  const borrarMut = useMutation({
    mutationFn: () => adminApi.deletePedido(turnoId),
    onSuccess: () => {
      toast.success("Turno eliminado");
      qc.invalidateQueries({ queryKey: ["admin", "pedido", pedidoPrincipalId] });
      qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
    },
    onError: (e: Error) => toast.error("No se pudo eliminar el turno", { description: e.message }),
  });

  if (turnoQ.isLoading || estudioQ.isLoading || !turnoQ.data || !estudioQ.data) {
    return (
      <div className="flex items-center justify-center rounded-xl border hairline bg-surface p-6">
        <Spinner size="sm" />
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <ReservaEstudioSection
        pedido={turnoQ.data}
        estudio={estudioQ.data}
        onSaved={() => {
          qc.invalidateQueries({ queryKey: ["admin", "pedido", turnoId] });
        }}
      />
      {/* Sin badge de estado: el turno sigue el estado de su pedido (cascada +
          gate, #1308), así que mostrarlo era repetir lo que ya dice el rail. Y
          sin link a "su propia pantalla": el turno no es un pedido aparte. */}
      <div className="flex items-center px-1">
        <button
          type="button"
          onClick={() => borrarMut.mutate()}
          disabled={borrarMut.isPending}
          title="Quitar turno del pedido"
          className="ml-auto text-muted-foreground hover:text-destructive disabled:opacity-50"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

export function TurnosEstudioSection({ pedido }: { pedido: Pedido }) {
  const qc = useQueryClient();
  // Se incrementa tras cada alta exitosa para remontar NuevoTurnoEstudioForm
  // (vía `key`) y así resetear su estado interno — el compose queda limpio,
  // listo para otro turno, sin necesidad de que el form exponga un reset.
  const [composeKey, setComposeKey] = useState(0);
  const estudioQ = useQuery({
    queryKey: ["admin", "estudio"],
    queryFn: () => estudioAdminApi.get(),
  });
  const turnos = pedido.turnos_estudio_vinculados ?? [];
  // Con la sección vacía, el compose de un turno nuevo se ve IGUAL que un turno
  // ya cargado ("Espacio", su franja, su precio) → parecía que el pedido ya
  // tenía uno (lo reportó el dueño). Vacío ⇒ se muestra un estado vacío
  // explícito con su botón; recién ahí aparece el compose. Con al menos un
  // turno cargado el compose sigue SIEMPRE visible debajo, como se pidió
  // cuando se sacó el modal — ahí no hay ambigüedad posible.
  const [componiendo, setComponiendo] = useState(false);
  const mostrarCompose = turnos.length > 0 || componiendo;

  return (
    <Section variant="card" tone="elevated" icon={Clapperboard} title="Turnos del Estudio">
      <div className="space-y-4">
        {turnos.length > 0 && (
          <div className="space-y-4">
            {turnos.map((t) => (
              <TurnoVinculadoCard key={t.id} turnoId={t.id} pedidoPrincipalId={pedido.id} />
            ))}
          </div>
        )}

        {!mostrarCompose && (
          <button
            type="button"
            onClick={() => setComponiendo(true)}
            className="flex w-full items-center justify-center gap-2 rounded-md border border-dashed hairline px-3 py-4 text-sm text-muted-foreground transition hover:bg-muted/30 hover:text-ink"
          >
            <Plus className="h-4 w-4 shrink-0" />
            Agregar un turno del Estudio
          </button>
        )}

        {mostrarCompose && estudioQ.data && (
          <NuevoTurnoEstudioForm
            key={composeKey}
            chrome="inline"
            estudio={estudioQ.data}
            pedidoVinculado={{
              id: pedido.id,
              clienteNombre: pedido.cliente_nombre,
              estado: pedido.estado,
            }}
            onCreated={() => {
              qc.invalidateQueries({ queryKey: ["admin", "pedido", pedido.id] });
              setComposeKey((k) => k + 1);
            }}
            onCancel={() => setComponiendo(false)}
          />
        )}
      </div>
    </Section>
  );
}
