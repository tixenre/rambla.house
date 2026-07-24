/**
 * AgendaMensual — vista mensual de ocupación del Estudio, hermana de
 * `AgendaSemanal` (misma fuente `GET /admin/estudio/agenda`, mismo
 * agrupamiento por día vía `agruparBloquesPorDia`). Acá no hay grilla de
 * horas: cada celda es un día del mes con chips compactos (hora + título) —
 * alcanza con ordenar por hora de inicio, sin posicionar por offset como en
 * la semana. Reusa `mesCells` (mismo cálculo de grilla de mes que
 * `CalendarioWidget`) y `minutosDelDia` (mismo helper que `calendario-horas`
 * usa para el eje de horas) — nada de esto se recalcula a mano de nuevo.
 * Color de turno vía `estadoClaseEstudio` (todo bloque acá es del Estudio,
 * a diferencia de `CalendarioWidget` que mezcla todos los tipos de pedido).
 */
import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/design-system/ui/button";
import { Spinner } from "@/design-system/ui/spinner";
import { Popover, PopoverContent, PopoverTrigger } from "@/design-system/ui/popover";
import { cn } from "@/lib/utils";
import { MESES, ymd, mesCells } from "@/lib/calendario-mes";
import { minutosDelDia } from "@/lib/calendario-horas";
import { estudioAdminApi, type EstudioAgendaBloque, type PedidoEstado } from "@/lib/admin/api";
import { estadoClaseEstudio } from "@/design-system/ui/estado-color";
import { agruparBloquesPorDia } from "./agendaUtils";

const DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const MAX_VISIBLES = 3;

function horaCorta(iso: string): string {
  return iso.slice(11, 16);
}

function Chip({
  bloque,
  onNavigatePedido,
}: {
  bloque: EstudioAgendaBloque;
  onNavigatePedido: (id: number) => void;
}) {
  const label = `${horaCorta(bloque.fecha_desde)} · ${bloque.titulo}`;
  const rango = `${horaCorta(bloque.fecha_desde)}–${horaCorta(bloque.fecha_hasta)}`;

  if (bloque.tipo === "turno") {
    return (
      <button
        type="button"
        onClick={() => onNavigatePedido(bloque.id)}
        title={`#${bloque.numero_pedido ?? bloque.id} · ${bloque.titulo} · ${rango}`}
        className={cn(
          "block w-full truncate rounded px-1 py-0.5 text-left text-2xs leading-tight transition hover:opacity-80",
          estadoClaseEstudio(bloque.estado as PedidoEstado),
        )}
      >
        {label}
      </button>
    );
  }

  return (
    <div
      title={`${bloque.titulo} · ${rango}`}
      className="block w-full truncate rounded border border-dashed border-muted-foreground/40 bg-muted/50 px-1 py-0.5 text-left text-2xs leading-tight text-muted-foreground"
    >
      {label}
    </div>
  );
}

export function AgendaMensual({
  onNavigatePedido,
  vistaSwitch,
}: {
  onNavigatePedido: (id: number) => void;
  /** Control Semana/Mes que arma `Agenda` — se pinta en la misma fila de
   * navegación para no sumar una fila entera solo para el toggle. */
  vistaSwitch?: ReactNode;
}) {
  const [cursor, setCursor] = useState(() => new Date());
  const { weeks, rangeStart, rangeEnd, headerLabel } = useMemo(() => mesCells(cursor), [cursor]);
  const hoy = ymd(new Date());
  const cursorMonth = cursor.getMonth();

  const agendaQ = useQuery({
    queryKey: ["admin", "estudio", "agenda", rangeStart, rangeEnd],
    queryFn: () => estudioAdminApi.getAgenda(rangeStart, rangeEnd),
  });

  const bloquesPorDia = useMemo(
    () => agruparBloquesPorDia(agendaQ.data?.bloques ?? []),
    [agendaQ.data],
  );

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCursor((c) => new Date(c.getFullYear(), c.getMonth() - 1, 1))}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm" onClick={() => setCursor(new Date())}>
              Hoy
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCursor((c) => new Date(c.getFullYear(), c.getMonth() + 1, 1))}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
          <span className="t-eyebrow">{headerLabel}</span>
        </div>
        {vistaSwitch}
      </div>

      {agendaQ.isLoading ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <div className="min-w-[720px] rounded-lg border hairline overflow-hidden bg-background">
            <div className="grid grid-cols-7 border-b hairline">
              {DIAS.map((d) => (
                <div key={d} className="px-2 py-1.5 t-eyebrow text-center">
                  {d}
                </div>
              ))}
            </div>
            {weeks.map((semana, wi) => (
              <div key={wi} className="grid grid-cols-7">
                {semana.map((d) => {
                  const key = ymd(d);
                  const inMonth = d.getMonth() === cursorMonth;
                  const bloques = [...(bloquesPorDia.get(key) ?? [])].sort(
                    (a, b) => minutosDelDia(a.fecha_desde) - minutosDelDia(b.fecha_desde),
                  );
                  const visibles = bloques.slice(0, MAX_VISIBLES);
                  const restantes = bloques.length - visibles.length;
                  return (
                    <div
                      key={key}
                      className={cn(
                        "min-h-[92px] border-r border-b hairline p-1.5",
                        inMonth ? "bg-background" : "bg-muted/30",
                      )}
                    >
                      <div
                        className={cn(
                          "mb-1 text-xs font-mono",
                          key === hoy
                            ? "inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-ink px-1 text-background"
                            : inMonth
                              ? "text-ink"
                              : "text-muted-foreground/60",
                        )}
                      >
                        {d.getDate()}
                      </div>
                      <div className="flex flex-col gap-0.5">
                        {visibles.map((b) => (
                          <Chip
                            key={`${b.tipo}-${b.id}`}
                            bloque={b}
                            onNavigatePedido={onNavigatePedido}
                          />
                        ))}
                        {restantes > 0 && (
                          <Popover>
                            <PopoverTrigger asChild>
                              <button
                                type="button"
                                className="px-1 text-left text-2xs text-muted-foreground transition hover:text-ink"
                              >
                                +{restantes} más
                              </button>
                            </PopoverTrigger>
                            <PopoverContent align="start" className="w-64 p-2">
                              <div className="mb-1.5 px-1 text-xs font-semibold text-ink">
                                {d.getDate()} {MESES[d.getMonth()].slice(0, 3)} · {bloques.length}{" "}
                                {bloques.length === 1 ? "evento" : "eventos"}
                              </div>
                              <div className="flex max-h-72 flex-col gap-0.5 overflow-auto">
                                {bloques.map((b) => (
                                  <Chip
                                    key={`${b.tipo}-${b.id}-pop`}
                                    bloque={b}
                                    onNavigatePedido={onNavigatePedido}
                                  />
                                ))}
                              </div>
                            </PopoverContent>
                          </Popover>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
