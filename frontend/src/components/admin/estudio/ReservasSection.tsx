/**
 * ReservasSection — alta/gestión de turnos del Estudio desde el back-office
 * (#1283 Fase 6). Vive en su propia ruta (`/admin/estudio/reservas`, no
 * dentro de la página de configuración) porque es uso DIARIO/operativo, a
 * diferencia del resto de `/admin/estudio` (config, se toca rara vez).
 *
 * Agenda semanal (ocupación) + lista (todos los turnos, cualquier fecha) —
 * ambas vistas del mismo `GET /admin/estudio/reservas`. Editar horario/
 * promo/sueltos pasa por `ReservaDialog`; pagos/documentos/estado del
 * pedido siguen en `/admin/pedidos/$id` (el editor genérico bloquea items/
 * fechas para tipo estudio, Fase 1 — no se reimplementa acá).
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { CalendarDays, ExternalLink, Plus, Rows3 } from "lucide-react";

import { Button } from "@/design-system/ui/button";
import { Spinner } from "@/design-system/ui/spinner";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { EstadoBadge } from "@/design-system/ui/EstadoBadge";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { formatARS } from "@/lib/format";
import { cn } from "@/lib/utils";
import { estudioAdminApi, type EstudioConfig, type EstudioReservaListItem } from "@/lib/admin/api";
import { Agenda } from "./Agenda";
import { ReservaDialog } from "./ReservaDialog";

function fmtFechaHora(iso: string): string {
  const [f, h] = iso.split("T");
  const [, m, d] = f.split("-");
  return `${d}/${m} · ${h.slice(0, 5)}`;
}

function horasDe(desde: string, hasta: string): number {
  return Math.round((new Date(hasta).getTime() - new Date(desde).getTime()) / 3_600_000);
}

export function ReservasSection({ estudio }: { estudio: EstudioConfig }) {
  const [vista, setVista] = useState<"agenda" | "lista">("agenda");
  const [dialogAbierto, setDialogAbierto] = useState(false);
  const [reservaEditando, setReservaEditando] = useState<EstudioReservaListItem | null>(null);

  const reservasQ = useQuery({
    queryKey: ["admin", "estudio", "reservas"],
    queryFn: () => estudioAdminApi.listReservas(),
  });
  const reservas = useMemo(() => reservasQ.data?.reservas ?? [], [reservasQ.data]);

  const abrirNuevo = () => {
    setReservaEditando(null);
    setDialogAbierto(true);
  };
  const abrirEdicion = (r: EstudioReservaListItem) => {
    setReservaEditando(r);
    setDialogAbierto(true);
  };
  const onNavigatePedido = (id: number) => {
    const r = reservas.find((x) => x.id === id);
    if (r) abrirEdicion(r);
  };

  const columns: Column<EstudioReservaListItem>[] = [
    {
      header: "#",
      cell: (r) => r.numero_pedido ?? r.id,
      className: "font-mono text-xs text-muted-foreground",
    },
    { header: "Cliente", cell: (r) => r.cliente_nombre || "Sin cliente" },
    {
      header: "Cuándo",
      cell: (r) => `${fmtFechaHora(r.fecha_desde)} → ${r.fecha_hasta.slice(11, 16)}`,
      className: "font-mono text-xs",
    },
    { header: "Horas", cell: (r) => `${horasDe(r.fecha_desde, r.fecha_hasta)}h` },
    {
      header: "Total",
      cell: (r) => (
        <>
          {formatARS(r.monto_total)}
          {r.monto_pagado < r.monto_total && (
            <span className="ml-1 text-xs text-muted-foreground">
              (pagado {formatARS(r.monto_pagado)})
            </span>
          )}
        </>
      ),
    },
    { header: "Estado", cell: (r) => <EstadoBadge estado={r.estado} /> },
    {
      header: "",
      align: "right",
      cell: (r) => (
        <div className="flex items-center justify-end gap-1">
          <Button variant="outline" size="sm" onClick={() => abrirEdicion(r)}>
            Editar
          </Button>
          <Button asChild variant="ghost" size="sm">
            <Link to="/admin/pedidos/$id" params={{ id: String(r.id) }}>
              <ExternalLink className="h-3.5 w-3.5" />
            </Link>
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="inline-flex rounded-lg border hairline p-0.5">
          <button
            type="button"
            onClick={() => setVista("agenda")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition",
              vista === "agenda"
                ? "bg-ink text-background"
                : "text-muted-foreground hover:text-ink",
            )}
          >
            <CalendarDays className="h-4 w-4" /> Agenda
          </button>
          <button
            type="button"
            onClick={() => setVista("lista")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition",
              vista === "lista" ? "bg-ink text-background" : "text-muted-foreground hover:text-ink",
            )}
          >
            <Rows3 className="h-4 w-4" /> Lista
          </button>
        </div>
        <Button onClick={abrirNuevo}>
          <Plus className="mr-1.5 h-4 w-4" /> Nuevo turno
        </Button>
      </div>

      {vista === "agenda" ? (
        <Agenda
          openHour={estudio.open_hour}
          closeHour={estudio.close_hour}
          onNavigatePedido={onNavigatePedido}
        />
      ) : reservasQ.isLoading ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : reservas.length === 0 ? (
        <EmptyState
          icon={<CalendarDays className="h-6 w-6" />}
          title="Sin turnos todavía"
          sub="Creá el primero con el botón de arriba."
        />
      ) : (
        <AdminTable columns={columns} rows={reservas} getRowKey={(r) => r.id} />
      )}

      <ReservaDialog
        open={dialogAbierto}
        onOpenChange={setDialogAbierto}
        reserva={reservaEditando}
        estudio={estudio}
        onSaved={() => reservasQ.refetch()}
      />
    </div>
  );
}
