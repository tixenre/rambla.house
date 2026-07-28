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
import { Clapperboard, X } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";

import { Section } from "@/design-system/composites/Section";
import { Button } from "@/design-system/ui/button";
import { Spinner } from "@/design-system/ui/spinner";
import { EstadoBadge } from "@/design-system/ui/EstadoBadge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/design-system/ui/alert-dialog";
import { adminApi, estudioAdminApi, type Pedido } from "@/lib/admin/api";
import { transiciones } from "@/lib/pedido-estados";
import { ReservaEstudioSection } from "@/components/admin/estudio/ReservaEstudioSection";
import { NuevoTurnoEstudioForm } from "@/components/admin/estudio/NuevoTurnoEstudioForm";

function TurnoVinculadoCard({ turnoId }: { turnoId: number }) {
  const qc = useQueryClient();
  const [askCancel, setAskCancel] = useState(false);
  const estudioQ = useQuery({
    queryKey: ["admin", "estudio"],
    queryFn: () => estudioAdminApi.get(),
  });
  const turnoQ = useQuery({
    queryKey: ["admin", "pedido", turnoId],
    queryFn: () => adminApi.getPedido(turnoId),
  });

  // Cancelar un turno vinculado no tenía atajo acá — obligaba a abrir el
  // turno en su propia pantalla y buscar "Zona peligrosa". Misma primitiva
  // que usa esa pantalla (setPedidoEstado → cambiar_estado), sin endpoint
  // nuevo: el motor ya excluye un turno cancelado de la cascada de estado y
  // del reparto de pago combinado (#1308, D4/D6).
  const cancelarMut = useMutation({
    mutationFn: () => adminApi.setPedidoEstado(turnoId, "cancelado"),
    onSuccess: (t) => {
      toast.success("Turno cancelado");
      qc.invalidateQueries({ queryKey: ["admin", "pedido", turnoId] });
      if (t.pedido_principal_id) {
        qc.invalidateQueries({ queryKey: ["admin", "pedido", t.pedido_principal_id] });
      }
      qc.invalidateQueries({ queryKey: ["admin", "pedidos"] });
      setAskCancel(false);
    },
    onError: (e: Error) => toast.error("No se pudo cancelar", { description: e.message }),
  });

  if (turnoQ.isLoading || estudioQ.isLoading || !turnoQ.data || !estudioQ.data) {
    return (
      <div className="flex items-center justify-center rounded-xl border hairline bg-surface p-6">
        <Spinner size="sm" />
      </div>
    );
  }

  const puedeCancelar = transiciones(turnoQ.data.estado).includes("cancelado");

  return (
    <div className="space-y-1.5">
      <ReservaEstudioSection
        pedido={turnoQ.data}
        estudio={estudioQ.data}
        onSaved={() => {
          qc.invalidateQueries({ queryKey: ["admin", "pedido", turnoId] });
        }}
      />
      <div className="flex items-center gap-2 px-1">
        {/* El estado puede haber cambiado SOLO (cascada #1308, "avanzan
            juntos" desde el pedido principal) sin que el admin haya tocado
            esta tarjeta — visible acá para no depender de abrir la pantalla
            propia del turno. `ReservaEstudioSection` no lo muestra (la
            página standalone del turno ya tiene su propio FlowStrip). */}
        <EstadoBadge estado={turnoQ.data.estado} />
        <Link
          to="/admin/pedidos/$id"
          params={{ id: String(turnoId) }}
          className="text-xs text-muted-foreground underline hover:text-ink"
        >
          Abrir turno #{turnoQ.data.numero_pedido ?? turnoId} en su propia pantalla ↗
        </Link>
        {puedeCancelar && (
          <Button
            variant="outline"
            size="sm"
            className="ml-auto border-destructive/30 text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={() => setAskCancel(true)}
          >
            <X className="h-4 w-4 mr-1" /> Cancelar turno
          </Button>
        )}
      </div>

      <AlertDialog open={askCancel} onOpenChange={setAskCancel}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Cancelar turno #{turnoQ.data.numero_pedido ?? turnoId}
            </AlertDialogTitle>
            <AlertDialogDescription>
              El turno pasa a estado <strong>Cancelado</strong> y libera el espacio reservado. Queda
              en el historial (no se borra).
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Volver</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => cancelarMut.mutate()}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Cancelar turno
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
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

  return (
    <Section variant="card" tone="elevated" icon={Clapperboard} title="Turnos del Estudio">
      <div className="space-y-4">
        {turnos.length > 0 && (
          <div className="space-y-4">
            {turnos.map((t) => (
              <TurnoVinculadoCard key={t.id} turnoId={t.id} />
            ))}
          </div>
        )}

        {estudioQ.data && (
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
            onCancel={() => {}}
          />
        )}
      </div>
    </Section>
  );
}
