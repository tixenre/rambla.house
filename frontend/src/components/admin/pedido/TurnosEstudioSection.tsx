/**
 * TurnosEstudioSection — turnos del Estudio administrados desde un pedido de
 * alquiler normal (#1308: "quiero un solo modal, el de los pedidos... que
 * mantenga la función actual de equipos, pero también una sección para el
 * Estudio"; afinado dos veces más — "no quiero el modal... como si fuera el
 * listado de equipos" y después "quiero una lista para seleccionar, como con
 * los equipos" — hasta terminar en: el compose de un turno nuevo queda
 * SIEMPRE visible acá abajo, igual que el buscador de "Equipos" nunca está
 * escondido detrás de un botón). Un pedido de rental (equipos por rango de
 * días) y un turno del Estudio (franja horaria puntual) son registros
 * DISTINTOS — no pueden ser una sola FILA (`fecha_desde`/`fecha_hasta`
 * significan cosas incompatibles, ver `lib/tipos-pedido.ts`) — pero se
 * administran en una sola pantalla, y desde #1308 Fase 4 en un solo PEDIDO
 * (un `numero_pedido`, sin fila `alquileres` aparte): esta sección los lista
 * inline reusando `ReservaEstudioSection`, la misma pieza que ya usa un
 * pedido `tipo='estudio'`.
 *
 * DOS mecanismos conviven mientras la Fase 5 (migración) no corrió:
 * `turnos_estudio_embebidos` (NUEVO, `TurnoEmbebidoCard` — un ÍTEM MÁS de
 * ESTE pedido, sin fila propia) es el único camino para un turno CREADO
 * desde acá; `turnos_estudio_vinculados` (VIEJO, `TurnoVinculadoCard` — una
 * fila `alquileres` aparte con `pedido_principal_id`) solo sigue
 * mostrándose para lo que ya existía antes de este deploy — nada nuevo lo
 * usa. Las dos listas se renderizan una debajo de la otra (sin intercalar
 * por fecha: es un puñado de filas, transitorio, no vale la complejidad de
 * un merge-sort) hasta que la Fase 5 retire la vieja.
 *
 * El compose de un turno nuevo (`NuevoTurnoEstudioForm chrome="inline"`,
 * misma pieza que usa `ReservaDialog` para el alta desde la agenda del
 * Estudio en modo `chrome="dialog"`) SIEMPRE crea EMBEBIDO — `pedidoContenedor`
 * apunta a este mismo pedido, `POST /alquileres/{id}/turnos-estudio`. El
 * `key={composeKey}` fuerza un remount tras crear un turno — así el compose
 * vuelve limpio, listo para otro, sin estado colgado del anterior. El
 * backend garantiza que el turno embebido nunca pueda mostrar un cliente
 * distinto al de este pedido (no tiene cliente propio que copiar — vive
 * `pedido.items` con `turno_estudio_id`, ver
 * `services/estudio/commands/reserva.py::agregar_turno_embebido`).
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Clapperboard, Plus, X } from "lucide-react";
import { toast } from "sonner";

import { Section } from "@/design-system/composites/Section";
import { Button } from "@/design-system/ui/button";
import { IconButton } from "@/design-system/ui/icon-button";
import { Spinner } from "@/design-system/ui/spinner";
import { fmtArs } from "@/lib/format";
import {
  adminApi,
  estudioAdminApi,
  type EstudioConfig,
  type Pedido,
  type TurnoEstudioEmbebido,
} from "@/lib/admin/api";
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
      // Igual que al guardar (ver `ReservaEstudioSection`): el total combinado
      // del rail sale de `/api/cotizar`, cuya caché no sabe de este turno.
      qc.invalidateQueries({ queryKey: ["cotizar"] });
      onEliminado();
    },
    onError: (e: Error) => toast.error("No se pudo eliminar el turno", { description: e.message }),
  });

  // El error va ANTES del spinner: con `isError`, `isLoading` es false y
  // `data` undefined, así que el guard de abajo daba true y la tarjeta giraba
  // para siempre, sin mensaje ni forma de reintentar.
  if (turnoQ.isError || estudioQ.isError) {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm">
        <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" />
        <span className="text-destructive">No se pudo cargar este turno.</span>
        <Button
          variant="outline"
          size="sm"
          className="ml-auto"
          onClick={() => {
            void turnoQ.refetch();
            void estudioQ.refetch();
          }}
        >
          Reintentar
        </Button>
      </div>
    );
  }

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
      // Sin encabezado propio: el de la sección ("Turnos del Estudio") ya lo
      // dice, y dos títulos iguales pegados es ruido. El ✕ cae arriba a la
      // derecha de la banda de tiempo — el mismo lugar que en un turno todavía
      // sin crear, así la ✕ está siempre donde uno la busca.
      anidada
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

/** Turno EMBEBIDO (#1308 Fase 4, el mecanismo nuevo) — a diferencia de
 *  `TurnoVinculadoCard`, SIN fetch propio: no es una fila `alquileres`
 *  aparte, así que sus datos ya están completos en la respuesta del pedido
 *  contenedor (`turno` = su metadata en `turnos_estudio_embebidos`,
 *  `contenedor.items` filtrados por `turno_estudio_id` = sus líneas). Arma
 *  un pedido SINTÉTICO para `ReservaEstudioSection` e inyecta `cotizar`/
 *  `guardar` apuntando a `.../alquileres/{contenedorId}/turnos-estudio/...`
 *  (ver el docstring de `ReservaEstudioSection` — es la pieza que sabe leer
 *  esta forma sin saber que es "embebida"). */
function TurnoEmbebidoCard({
  turno,
  contenedor,
  estudio,
  onEliminado,
}: {
  turno: TurnoEstudioEmbebido;
  contenedor: Pedido;
  estudio: EstudioConfig;
  /** Ver el mismo prop en `TurnoVinculadoCard`. */
  onEliminado: () => void;
}) {
  const qc = useQueryClient();

  const pedidoSintetico = useMemo(
    () => ({
      id: turno.id,
      fecha_desde: turno.fecha_desde,
      fecha_hasta: turno.fecha_hasta,
      items: contenedor.items.filter((it) => it.turno_estudio_id === turno.id),
      descuento_pct: turno.descuento_pct,
      descuento_manual_tipo: turno.descuento_manual_tipo,
      descuento_manual_monto: turno.descuento_manual_monto,
    }),
    [turno, contenedor.items],
  );

  // Mismo criterio que `TurnoVinculadoCard`: hard delete real, sin confirmar
  // ("que se comporte como cuando saco un equipo"). Acá es más simple
  // todavía — no hay una fila `alquileres` aparte que borrar, el cascade de
  // `alquiler_turnos_estudio` se lleva sus ítems y listo.
  const borrarMut = useMutation({
    mutationFn: () => adminApi.eliminarTurnoEstudio(contenedor.id, turno.id),
    onSuccess: (actualizado) => {
      toast.success("Turno eliminado");
      // La respuesta YA ES el pedido contenedor completo — se reemplaza la
      // cache entera en vez de reconciliar un array a mano (a diferencia del
      // turno vinculado, que solo devolvía SU PROPIO pedido).
      qc.setQueryData(["admin", "pedido", contenedor.id], actualizado);
      qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
      qc.invalidateQueries({ queryKey: ["admin", "estudio", "reservas"] });
      qc.invalidateQueries({ queryKey: ["admin", "estudio", "agenda"] });
      qc.invalidateQueries({ queryKey: ["cotizar"] });
      onEliminado();
    },
    onError: (e: Error) => toast.error("No se pudo eliminar el turno", { description: e.message }),
  });

  return (
    <ReservaEstudioSection
      pedido={pedidoSintetico}
      estudio={estudio}
      anidada
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
      // Excluye este turno del chequeo de disponibilidad por su PROPIO id de
      // grupo — no por `pedido_id` (que escondería un conflicto real contra
      // un turno hermano del mismo pedido, ver el docstring de `estudio.ts`).
      cotizar={(params) =>
        estudioAdminApi.cotizarReserva({ ...params, exclude_turno_estudio_id: turno.id })
      }
      guardar={(payload) => adminApi.editarTurnoEstudio(contenedor.id, turno.id, payload)}
      onSaved={(actualizado) => {
        qc.setQueryData(["admin", "pedido", contenedor.id], actualizado);
        qc.invalidateQueries({ queryKey: ["cotizar"] });
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
  // VIEJO (`pedido_principal_id`, fila `alquileres` aparte) + NUEVO (ítem de
  // ESTE pedido) — ver el docstring del módulo. Ambos se muestran mientras
  // conviven; solo el nuevo es alcanzable desde el compose de acá abajo.
  const turnosVinculados = pedido.turnos_estudio_vinculados ?? [];
  const turnosEmbebidos = pedido.turnos_estudio_embebidos ?? [];
  const totalTurnosCount = turnosVinculados.length + turnosEmbebidos.length;
  // El compose NO vive fijo al pie: se abre con el botón y se cierra solo
  // apenas el turno queda creado (el alta ya no tiene botón de confirmar —
  // "que sea como los equipos: si está en el listado, se cotiza"). Dejarlo
  // permanente sería una fila fantasma que se lee como un turno más y que,
  // con el alta automática, se pondría a crear turnos sola.
  const [componiendo, setComponiendo] = useState(false);
  // Total agregado — solo con 2+ turnos: con uno solo, su propia tarjeta ya
  // muestra el total y repetirlo acá sería el mismo número dos veces (mismo
  // criterio que "Equipos · N" no se convierte en "Total $X" salvo que sume
  // más de una línea con montos distintos que valga la pena agregar).
  const totalTurnosMonto =
    turnosVinculados.reduce((acc, t) => acc + (t.monto_total || 0), 0) +
    turnosEmbebidos.reduce((acc, t) => acc + (t.monto_total || 0), 0);

  return (
    <Section
      variant="card"
      tone="elevated"
      icon={Clapperboard}
      title="Turnos del Estudio"
      actions={
        totalTurnosCount > 1 ? (
          <span className="font-mono text-xs text-muted-foreground">
            {totalTurnosCount} turnos · {fmtArs(totalTurnosMonto)}
          </span>
        ) : undefined
      }
    >
      <div className="space-y-4">
        {totalTurnosCount > 0 && (
          <div className="space-y-4">
            {/* "Turnos · N" — mismo eyebrow que "Equipos · N" en la sección
                gemela; con 2+ también arriba (`actions`) el total agregado.
                Un solo conteo para las dos listas: la distinción vieja/nuevo
                es interna, el dueño solo ve "turnos de este pedido". */}
            <div className="t-eyebrow">Turnos · {totalTurnosCount}</div>
            {turnosVinculados.map((t) => (
              <TurnoVinculadoCard
                key={`vinculado-${t.id}`}
                turnoId={t.id}
                pedidoPrincipalId={pedido.id}
                onEliminado={() => setComponiendo(false)}
              />
            ))}
            {estudioQ.data &&
              turnosEmbebidos.map((t) => (
                <TurnoEmbebidoCard
                  key={`embebido-${t.id}`}
                  turno={t}
                  contenedor={pedido}
                  estudio={estudioQ.data!}
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
            pedidoContenedor={{ id: pedido.id, clienteNombre: pedido.cliente_nombre }}
            onCreated={(actualizado) => {
              // El alta embebida devuelve el pedido CONTENEDOR completo (mismo
              // id que `pedido.id`, con el turno nuevo ya adentro de
              // `turnos_estudio_embebidos`/`items`) — se reemplaza la cache
              // entera, no hay un segundo pedido que sembrar.
              qc.setQueryData(["admin", "pedido", pedido.id], actualizado);
              // Otra pantalla (la lista de pedidos, cuyo monto_total ahora
              // incluye el turno): no está montada acá, invalidarla no
              // dispara nada ahora.
              qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
              qc.invalidateQueries({ queryKey: ["admin", "estudio", "reservas"] });
              qc.invalidateQueries({ queryKey: ["admin", "estudio", "agenda"] });
              // El total del rail sí está montado: sale de `/api/cotizar`,
              // cuya caché no sabe que apareció este turno.
              qc.invalidateQueries({ queryKey: ["cotizar"] });
              setComposeKey((k) => k + 1);
              // El turno ya existe y se administra en su propia tarjeta: acá no
              // queda nada abierto (si no, el alta automática crearía otro).
              setComponiendo(false);
            }}
            onCancel={() => setComponiendo(false)}
          />
        ) : estudioQ.isError ? (
          // Sin esta rama el botón quedaba MUERTO: clickearlo ponía
          // `componiendo=true` y, como `estudioQ.data` era undefined, volvía a
          // renderizar el mismo botón — sin formulario, sin error, sin nada.
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-3 text-sm">
            <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" />
            <span className="text-destructive">
              No se pudo cargar la configuración del Estudio — no se puede agregar un turno ahora.
            </span>
            <Button
              variant="outline"
              size="sm"
              className="ml-auto"
              onClick={() => void estudioQ.refetch()}
            >
              Reintentar
            </Button>
          </div>
        ) : (
          /* Mismo lugar y forma que "Agregar línea personalizada" de Equipos. */
          <button
            type="button"
            onClick={() => setComponiendo(true)}
            className="flex w-full items-center justify-center gap-2 rounded-md border border-dashed hairline px-3 py-4 text-sm text-muted-foreground transition hover:bg-muted/30 hover:text-ink"
          >
            <Plus className="h-4 w-4 shrink-0" />
            {totalTurnosCount > 0
              ? "Agregar otro turno del Estudio"
              : "Agregar un turno del Estudio"}
          </button>
        )}
      </div>
    </Section>
  );
}
