/**
 * TurnosEstudioSection — turnos del Estudio vinculados a un pedido de
 * alquiler normal (#1308: "quiero un solo modal, el de los pedidos... que
 * mantenga la función actual de equipos, pero también una sección para el
 * Estudio"). Un pedido de rental (equipos por rango de días) y un turno del
 * Estudio (franja horaria puntual) son registros DISTINTOS — no pueden ser
 * una sola fila (`fecha_desde`/`fecha_hasta` significan cosas incompatibles,
 * ver `lib/tipos-pedido.ts`) — pero se administran en una sola pantalla:
 * esta sección los lista inline (reusando `ReservaEstudioSection`, la misma
 * pieza que ya usa un pedido `tipo='estudio'`) y deja agregar uno nuevo sin
 * salir de acá. El backend garantiza que el turno nunca pueda mostrar un
 * cliente distinto al del pedido principal (`pedido_principal_id`, hereda
 * SIEMPRE el contacto de acá — ver `routes/estudio.py::_resolver_pedido_principal`).
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, Plus } from "lucide-react";
import { Link } from "@tanstack/react-router";

import { Section } from "@/design-system/composites/Section";
import { Spinner } from "@/design-system/ui/spinner";
import { adminApi, estudioAdminApi, type Pedido } from "@/lib/admin/api";
import { ReservaEstudioSection } from "@/components/admin/estudio/ReservaEstudioSection";
import { ReservaDialog } from "@/components/admin/estudio/ReservaDialog";

function TurnoVinculadoCard({ turnoId }: { turnoId: number }) {
  const qc = useQueryClient();
  const estudioQ = useQuery({
    queryKey: ["admin", "estudio"],
    queryFn: () => estudioAdminApi.get(),
  });
  const turnoQ = useQuery({
    queryKey: ["admin", "pedido", turnoId],
    queryFn: () => adminApi.getPedido(turnoId),
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
      <Link
        to="/admin/pedidos/$id"
        params={{ id: String(turnoId) }}
        className="inline-block px-1 text-xs text-muted-foreground underline hover:text-ink"
      >
        Abrir turno #{turnoQ.data.numero_pedido ?? turnoId} en su propia pantalla ↗
      </Link>
    </div>
  );
}

export function TurnosEstudioSection({ pedido }: { pedido: Pedido }) {
  const qc = useQueryClient();
  const [openAlta, setOpenAlta] = useState(false);
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

        <button
          type="button"
          disabled={!estudioQ.data}
          onClick={() => setOpenAlta(true)}
          className="flex w-full items-center justify-center gap-2 rounded-md border border-dashed hairline px-3 py-2.5 text-sm text-muted-foreground transition hover:bg-muted/30 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="h-4 w-4 shrink-0" />
          <span>Agregar turno del Estudio</span>
        </button>
      </div>

      {estudioQ.data && (
        <ReservaDialog
          open={openAlta}
          onOpenChange={setOpenAlta}
          reserva={null}
          estudio={estudioQ.data}
          pedidoVinculado={{ id: pedido.id, clienteNombre: pedido.cliente_nombre }}
          onSaved={() => qc.invalidateQueries({ queryKey: ["admin", "pedido", pedido.id] })}
        />
      )}
    </Section>
  );
}
