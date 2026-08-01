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
import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Clapperboard, Plus, X } from "lucide-react";
import { toast } from "sonner";

import { Section } from "@/design-system/composites/Section";
import { Button } from "@/design-system/ui/button";
import { IconButton } from "@/design-system/ui/icon-button";
import { Spinner } from "@/design-system/ui/spinner";
import {
  adminApi,
  estudioAdminApi,
  type EstudioConfig,
  type EstudioCotizacion,
  type Pedido,
  type TurnoEstudioEmbebido,
} from "@/lib/admin/api";
import {
  ReservaEstudioSection,
  type CotizTurnoEstado,
} from "@/components/admin/estudio/ReservaEstudioSection";
import { NuevoTurnoEstudioForm } from "@/components/admin/estudio/NuevoTurnoEstudioForm";
import { TotalSeccion } from "@/components/admin/pedido/TotalSeccion";
import { DescuentoControl } from "@/components/admin/pedido/DescuentoControl";

function TurnoVinculadoCard({
  turnoId,
  pedidoPrincipalId,
  onEliminado,
  descuentoPctOverride,
  onCotizacion,
}: {
  turnoId: number;
  pedidoPrincipalId: number;
  /** Avisa al padre que este turno ya no está — así, si era el último, la
   *  sección vuelve a su estado vacío explícito en vez de dejar abierto el
   *  compose (que se lee como "ya hay un turno", justo lo que se quería
   *  evitar). */
  onEliminado: () => void;
  /** Ver el mismo prop en `ReservaEstudioSection` — el ledger combinado de
   *  abajo lo aplica igual a un turno vinculado o embebido. */
  descuentoPctOverride?: number;
  onCotizacion?: (estado: CotizTurnoEstado) => void;
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
      // El ledger propio se apaga: con 2+ turnos, el combinado de abajo de
      // `TurnosEstudioSection` es el único que se ve (y el único editable).
      mostrarTotal={false}
      descuentoPctOverride={descuentoPctOverride}
      onCotizacion={onCotizacion}
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
  descuentoPctOverride,
  onCotizacion,
}: {
  turno: TurnoEstudioEmbebido;
  contenedor: Pedido;
  estudio: EstudioConfig;
  /** Ver el mismo prop en `TurnoVinculadoCard`. */
  onEliminado: () => void;
  /** Ver el mismo prop en `ReservaEstudioSection`. */
  descuentoPctOverride?: number;
  onCotizacion?: (estado: CotizTurnoEstado) => void;
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
      // Ver el comentario en `TurnoVinculadoCard` — mismo tratamiento para
      // los dos mecanismos.
      mostrarTotal={false}
      descuentoPctOverride={descuentoPctOverride}
      onCotizacion={onCotizacion}
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

  // Ledger COMBINADO (pedido del dueño: "no quiero los subtotales en cada
  // turno, quiero un total parcial que abarque todos, y ahí el descuento").
  // Cada tarjeta apaga su propio ledger (`mostrarTotal={false}`) y reporta
  // acá su cotización en vivo vía `onCotizacion` — este bloque suma bruto/
  // descuento/total de TODOS los turnos y es el único lugar donde se edita
  // el %. `cotizaciones` mapea `turnoKey` ("v-<id>"/"e-<id>", los mismos
  // prefijos que las `key` de los `.map()` de abajo, para que un id de
  // vinculado y uno de embebido nunca puedan chocar) → el último estado que
  // reportó esa tarjeta.
  const [cotizaciones, setCotizaciones] = useState<Record<string, CotizTurnoEstado>>({});
  // `null` = el admin TODAVÍA no tocó el control combinado — ningún turno
  // recibe `descuentoPctOverride` (ver los `.map()` de abajo) y cada uno
  // sigue cotizando/autoguardando con SU PROPIO % real, exactamente como
  // antes de este cambio. Recién se vuelve un número real cuando el admin
  // edita el control — desde ahí sí se empuja parejo a todos.
  //
  // ¡Importante! Se probó (y se descartó) derivar este valor automáticamente
  // de lo que YA tienen los turnos apenas cargan (ej. "si los dos están en
  // 10%, arrancar ahí"): en la práctica, un turno cuyo autosave falla por
  // cualquier motivo transitorio (ej. una carrera de guardado ajena a este
  // cambio) queda con su % real desincronizado del resto — y como el % de
  // ese turno YA aparecía como override activo, la próxima vez que la
  // sección detectaba "no coinciden, caigo a 0%" ESE 0% se empujaba como
  // override y el autosave de la tarjeta lo persistía, BORRANDO un
  // descuento real que estaba bien. Detectado en vivo (Postgres real, 2
  // turnos con precios distintos) antes de shippear. Por eso el override
  // solo nace de una acción explícita del admin, nunca de lo que ya había.
  const [combinedPctOverride, setCombinedPctOverride] = useState<number | null>(null);

  useEffect(() => {
    setCotizaciones({});
    setCombinedPctOverride(null);
  }, [pedido.id]);

  // Bail-out: si el estado reportado es IGUAL al que ya había para ese turno,
  // devuelve la MISMA referencia de `prev` — así React no re-renderiza en
  // cascada cada vez que una tarjeta hermana reporta la suya.
  const handleCotizacion = useCallback((turnoKey: string, estado: CotizTurnoEstado) => {
    setCotizaciones((prev) => {
      const anterior = prev[turnoKey];
      if (anterior?.status === estado.status) {
        if (estado.status !== "ok") return prev;
        if (anterior.status === "ok" && anterior.cotiz === estado.cotiz) return prev;
      }
      return { ...prev, [turnoKey]: estado };
    });
  }, []);

  const cotizacionesList = useMemo(() => Object.values(cotizaciones), [cotizaciones]);
  const cotizacionesOk = useMemo(
    () =>
      cotizacionesList.filter(
        (e): e is { status: "ok"; cotiz: EstudioCotizacion } => e.status === "ok",
      ),
    [cotizacionesList],
  );
  const combinedListo = totalTurnosCount > 0 && cotizacionesOk.length >= totalTurnosCount;
  const combinedError = cotizacionesList.some((e) => e.status === "error");
  const combinedBruto = cotizacionesOk.reduce((acc, e) => acc + e.cotiz.bruto, 0);
  const combinedDescuentoMonto = cotizacionesOk.reduce(
    (acc, e) => acc + e.cotiz.descuento_monto,
    0,
  );
  const combinedNeto = cotizacionesOk.reduce((acc, e) => acc + e.cotiz.monto_total, 0);
  // Solo para MOSTRAR el número dentro del control antes de tocarlo — nunca
  // se empuja como override (ver el comentario de `combinedPctOverride`
  // arriba). Si todos los turnos ya cotizados comparten el mismo %, ese es
  // el que se ve; si divergen, se ve 0% (no hay un número combinado real que
  // mostrar) hasta que el admin fije uno.
  const pctMostrado =
    combinedPctOverride ??
    (() => {
      if (!combinedListo) return 0;
      const pcts = cotizacionesOk.map((e) => e.cotiz.descuento_pct ?? 0);
      return pcts.every((p) => p === pcts[0]) ? pcts[0] : 0;
    })();

  return (
    <Section variant="card" tone="elevated" icon={Clapperboard} title="Turnos del Estudio">
      <div className="space-y-4">
        {totalTurnosCount > 0 && (
          <div className="space-y-4">
            {/* "Turnos · N" — mismo eyebrow que "Equipos · N" en la sección
                gemela. Un solo conteo para las dos listas: la distinción
                vieja/nuevo es interna, el dueño solo ve "turnos de este
                pedido". */}
            <div className="t-eyebrow">Turnos · {totalTurnosCount}</div>
            {turnosVinculados.map((t) => (
              <TurnoVinculadoCard
                key={`vinculado-${t.id}`}
                turnoId={t.id}
                pedidoPrincipalId={pedido.id}
                onEliminado={() => setComponiendo(false)}
                descuentoPctOverride={combinedPctOverride ?? undefined}
                onCotizacion={(estado) => handleCotizacion(`v-${t.id}`, estado)}
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
                  descuentoPctOverride={combinedPctOverride ?? undefined}
                  onCotizacion={(estado) => handleCotizacion(`e-${t.id}`, estado)}
                />
              ))}
            {/* Ledger ÚNICO de la sección — antes cada tarjeta mostraba su
                propio Subtotal/Descuento/Total y acá abajo solo se sumaban
                los totales ya resueltos, sin control de descuento (lo
                reportó el dueño: "no quiero los subtotales en cada turno,
                quiero un total parcial que abarque todos, y ahí el
                descuento"). Se muestra con 1 turno o más — a diferencia del
                criterio viejo (2+), acá es el ÚNICO ledger visible de toda
                la sección: con 1 solo turno ya no hay otro lugar donde ver
                su Subtotal/Descuento/Total. */}
            {combinedError ? (
              <div className="flex flex-wrap items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-2 text-xs text-destructive">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>
                  No se pudo calcular el total de uno o más turnos — no es confiable hasta
                  recalcular.
                </span>
              </div>
            ) : !combinedListo && combinedPctOverride === null ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Spinner size="sm" /> Calculando…
              </div>
            ) : (
              <TotalSeccion
                bruto={combinedBruto}
                descuentoLabel="Descuento"
                descuentoPct={pctMostrado}
                descuentoMonto={combinedDescuentoMonto}
                total={combinedNeto}
                descuentoControl={
                  <DescuentoControl
                    soloPct
                    value={{ tipo: "pct", pct: pctMostrado, monto: 0 }}
                    onChange={(next) => setCombinedPctOverride(next.pct)}
                    maxMonto={combinedBruto}
                    efectivoPct={pctMostrado}
                    efectivoMonto={combinedDescuentoMonto}
                  />
                }
              />
            )}
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
              // El turno nuevo nace SIEMPRE en 0% (el backend no acepta
              // descuento al crear, ver `agregar_turno_embebido`) — si el
              // admin YA fijó un % combinado (`combinedPctOverride !== null`,
              // acción explícita — nunca un valor derivado en silencio, ver
              // el comentario de esa variable) y es > 0, se lo aplica acá con
              // un PATCH extra. Sin esto, el override lo MOSTRARÍA con el %
              // del grupo pero el valor persistido seguiría en 0% (el
              // autosave solo REGISTRA el primer payload, no lo guarda) — un
              // F5 lo regresaría a 0% en silencio.
              const nuevo = (actualizado.turnos_estudio_embebidos ?? []).find(
                (t) => !turnosEmbebidos.some((e) => e.id === t.id),
              );
              if (nuevo && combinedPctOverride != null && combinedPctOverride > 0) {
                adminApi
                  .editarTurnoEstudio(pedido.id, nuevo.id, {
                    descuento_pct: combinedPctOverride,
                    descuento_manual_tipo: "pct",
                  })
                  .then((actualizado2) => {
                    qc.setQueryData(["admin", "pedido", pedido.id], actualizado2);
                    qc.invalidateQueries({ queryKey: ["cotizar"] });
                  })
                  .catch((e: Error) =>
                    toast.error(
                      "El turno se creó, pero no se pudo aplicar el descuento del grupo",
                      {
                        description: e.message,
                      },
                    ),
                  );
              }
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
