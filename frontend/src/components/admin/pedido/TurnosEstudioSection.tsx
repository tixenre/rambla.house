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
import { IconButton } from "@/design-system/ui/icon-button";
import { Spinner } from "@/design-system/ui/spinner";
import { adminApi, estudioAdminApi, type Pedido } from "@/lib/admin/api";
import { ReservaEstudioSection } from "@/components/admin/estudio/ReservaEstudioSection";
import { NuevoTurnoEstudioForm } from "@/components/admin/estudio/NuevoTurnoEstudioForm";

function TurnoVinculadoCard({
  turnoId,
  pedidoPrincipalId,
  onEliminado,
}: {
  turnoId: number;
  pedidoPrincipalId: number;
  /** Avisa al padre que este turno ya no está — así, si era el último, la
   *  sección vuelve a su estado vacío explícito en vez de dejar abierto el
   *  compose (que se lee como "ya hay un turno", justo lo que se quería
   *  evitar). */
  onEliminado: () => void;
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
      // Sacar la entrada de la caché en vez de repedir el pedido: la tarjeta se
      // va en el acto, sin el ida y vuelta que hacía parpadear la sección.
      qc.setQueryData(["admin", "pedido", pedidoPrincipalId], (prev?: Pedido) =>
        prev
          ? {
              ...prev,
              turnos_estudio_vinculados: (prev.turnos_estudio_vinculados ?? []).filter(
                (t) => t.id !== turnoId,
              ),
            }
          : prev,
      );
      qc.removeQueries({ queryKey: ["admin", "pedido", turnoId] });
      qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
      onEliminado();
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

  // Sin badge de estado: el turno sigue el estado de su pedido (cascada +
  // gate, #1308), así que mostrarlo era repetir lo que ya dice el rail. Y sin
  // link a "su propia pantalla": el turno no es un pedido aparte.
  return (
    <ReservaEstudioSection
      pedido={turnoQ.data}
      estudio={estudioQ.data}
      // El ✕ vive en el ENCABEZADO de la tarjeta del turno. Antes flotaba en
      // una fila propia debajo, sin nada que lo anclara — el dueño no lo
      // encontraba ("ahora no puedo quitar el turno").
      accion={
        <IconButton
          aria-label="Quitar el turno del pedido"
          title="Quitar el turno del pedido"
          onClick={() => borrarMut.mutate()}
          disabled={borrarMut.isPending}
          className="text-muted-foreground hover:text-destructive hover:bg-destructive/10"
        >
          <X className="h-4 w-4" />
        </IconButton>
      }
      // La plata del turno vive DUPLICADA en la pantalla: en su tarjeta y en el
      // rail del pedido (que suma el "Total combinado"). Al guardar, se parchea
      // la entrada de este turno dentro del pedido principal con lo que acaba
      // de contestar el servidor — así el rail queda al día EN EL ACTO y sin
      // pedir nada. Antes no se tocaba: editabas la tarifa a $333.000 y el rail
      // seguía diciendo $120.000 hasta recargar (plata mintiendo en pantalla).
      onSaved={(actualizado) => {
        qc.setQueryData(["admin", "pedido", pedidoPrincipalId], (prev?: Pedido) =>
          prev
            ? {
                ...prev,
                turnos_estudio_vinculados: (prev.turnos_estudio_vinculados ?? []).map((t) =>
                  t.id === turnoId
                    ? {
                        ...t,
                        estado: actualizado.estado,
                        fecha_desde: actualizado.fecha_desde,
                        fecha_hasta: actualizado.fecha_hasta,
                        monto_total: actualizado.monto_total,
                        monto_pagado: actualizado.monto_pagado,
                      }
                    : t,
                ),
              }
            : prev,
        );
      }}
    />
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
  // El compose NO vive fijo al pie: se abre con el botón y se cierra solo
  // apenas el turno queda creado (el alta ya no tiene botón de confirmar —
  // "que sea como los equipos: si está en el listado, se cotiza"). Dejarlo
  // permanente sería una fila fantasma que se lee como un turno más y que,
  // con el alta automática, se pondría a crear turnos sola.
  const [componiendo, setComponiendo] = useState(false);

  return (
    <Section variant="card" tone="elevated" icon={Clapperboard} title="Turnos del Estudio">
      <div className="space-y-4">
        {turnos.length > 0 && (
          <div className="space-y-4">
            {turnos.map((t) => (
              <TurnoVinculadoCard
                key={t.id}
                turnoId={t.id}
                pedidoPrincipalId={pedido.id}
                onEliminado={() => setComponiendo(false)}
              />
            ))}
          </div>
        )}

        {componiendo && estudioQ.data ? (
          <NuevoTurnoEstudioForm
            key={composeKey}
            chrome="inline"
            estudio={estudioQ.data}
            pedidoVinculado={{
              id: pedido.id,
              clienteNombre: pedido.cliente_nombre,
              estado: pedido.estado,
            }}
            onCreated={(nuevo) => {
              // El alta ya devolvió el turno COMPLETO (`_get_alquiler_detail`,
              // la misma función que sirve el GET). Se siembran las dos cachés
              // que la tarjeta necesita en vez de invalidar y esperar: sin esto
              // el compose desaparecía, la tarjeta arrancaba sin datos y se veía
              // ~90ms de spinner en el medio — el "se sale lo que hay, aparece
              // la pantalla de guardado y vuelve" que reportó el dueño.
              qc.setQueryData(["admin", "pedido", nuevo.id], nuevo);
              qc.setQueryData(["admin", "pedido", pedido.id], (prev?: Pedido) =>
                prev
                  ? {
                      ...prev,
                      turnos_estudio_vinculados: [
                        ...(prev.turnos_estudio_vinculados ?? []),
                        {
                          id: nuevo.id,
                          numero_pedido: nuevo.numero_pedido,
                          estado: nuevo.estado,
                          fecha_desde: nuevo.fecha_desde,
                          fecha_hasta: nuevo.fecha_hasta,
                          monto_total: nuevo.monto_total,
                          monto_pagado: nuevo.monto_pagado,
                        },
                      ],
                    }
                  : prev,
              );
              // Otra pantalla (la lista de pedidos muestra el badge 🎬): no está
              // montada acá, invalidarla no dispara nada ahora.
              qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
              setComposeKey((k) => k + 1);
              // El turno ya existe y se administra en su propia tarjeta: acá no
              // queda nada abierto (si no, el alta automática crearía otro).
              setComponiendo(false);
            }}
            onCancel={() => setComponiendo(false)}
          />
        ) : (
          /* Mismo lugar y forma que "Agregar línea personalizada" de Equipos. */
          <button
            type="button"
            onClick={() => setComponiendo(true)}
            className="flex w-full items-center justify-center gap-2 rounded-md border border-dashed hairline px-3 py-4 text-sm text-muted-foreground transition hover:bg-muted/30 hover:text-ink"
          >
            <Plus className="h-4 w-4 shrink-0" />
            {turnos.length > 0 ? "Agregar otro turno del Estudio" : "Agregar un turno del Estudio"}
          </button>
        )}
      </div>
    </Section>
  );
}
