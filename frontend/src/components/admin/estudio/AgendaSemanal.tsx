/**
 * AgendaSemanal — vista semanal de ocupación del Estudio (#1283 Fase 6).
 *
 * Grilla día×hora con los bloques de `GET /admin/estudio/agenda` (turnos +
 * slots fijos + talleres — misma fuente que decide "¿está ocupado?" en
 * `_estudio_disponible`/`_slot_bloqueante`/`_taller_bloqueante`). NO reusa
 * `CalendarioWidget` (vista mes/semana de TODOS los pedidos, columnas=días
 * para eventos multi-día) — acá cada bloque vive DENTRO de un solo día, en un
 * rango de horas, así que la grilla es más simple: una columna por día,
 * bloques posicionados por offset de hora. Los turnos de un mismo espacio no
 * deberían solaparse nunca (lo impide el propio backend) — el split lado a
 * lado de abajo es una red defensiva, no el caso esperado.
 *
 * Horas SIEMPRE como string local "naive" (`"2026-07-20T14:00:00"`, sin
 * timezone) — igual que `CalendarioWidget.bloqueoHora`: parsear con `Date`
 * reinterpretaría en el timezone del browser. Se comparan como texto.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/design-system/ui/button";
import { Spinner } from "@/design-system/ui/spinner";
import { cn } from "@/lib/utils";
import { estudioAdminApi, type EstudioAgendaBloque } from "@/lib/admin/api";
import { estadoClaseEstudio } from "@/design-system/ui/estado-color";
import { ubicarEnCarriles } from "@/lib/calendario-horas";
import type { PedidoEstado } from "@/lib/admin/api";

const DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const PX_POR_HORA = 48;

function ymd(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function inicioDeSemana(d: Date): Date {
  const dow = (d.getDay() + 6) % 7; // Lunes = 0
  const start = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  start.setDate(start.getDate() - dow);
  return start;
}

function BloqueCard({
  seg,
  onNavigatePedido,
}: {
  seg: ReturnType<typeof ubicarEnCarriles<EstudioAgendaBloque>>[number];
  onNavigatePedido: (id: number) => void;
}) {
  const { item: b, carril, totalCarriles, top, height } = seg;
  const widthPct = 100 / totalCarriles;
  const style = {
    top,
    height,
    left: `${carril * widthPct}%`,
    width: `${widthPct}%`,
  };
  const horaLabel = `${b.fecha_desde.slice(11, 16)}–${b.fecha_hasta.slice(11, 16)}`;

  if (b.tipo === "turno") {
    return (
      <button
        type="button"
        onClick={() => onNavigatePedido(b.id)}
        style={style}
        className={cn(
          "absolute rounded-md border px-1.5 py-1 text-left text-2xs leading-tight transition hover:opacity-80 overflow-hidden",
          estadoClaseEstudio(b.estado as PedidoEstado),
        )}
      >
        <div className="truncate font-medium">
          #{b.numero_pedido ?? b.id} · {b.titulo}
        </div>
        <div className="truncate opacity-80">{horaLabel}</div>
      </button>
    );
  }

  return (
    <div
      style={style}
      title={`${b.titulo} · ${horaLabel}`}
      className="absolute overflow-hidden rounded-md border border-dashed border-muted-foreground/40 bg-muted/50 px-1.5 py-1 text-left text-2xs leading-tight text-muted-foreground"
    >
      <div className="truncate font-medium">{b.titulo}</div>
      <div className="truncate opacity-80">{horaLabel}</div>
    </div>
  );
}

export function AgendaSemanal({
  openHour,
  closeHour,
  onNavigatePedido,
}: {
  openHour: number;
  closeHour: number;
  onNavigatePedido: (id: number) => void;
}) {
  const [cursor, setCursor] = useState(() => new Date());
  const inicio = useMemo(() => inicioDeSemana(cursor), [cursor]);
  const dias = useMemo(
    () =>
      Array.from({ length: 7 }, (_, i) => {
        const d = new Date(inicio);
        d.setDate(inicio.getDate() + i);
        return d;
      }),
    [inicio],
  );
  const desde = ymd(dias[0]);
  const hasta = ymd(dias[6]);
  const hoy = ymd(new Date());

  const agendaQ = useQuery({
    queryKey: ["admin", "estudio", "agenda", desde, hasta],
    queryFn: () => estudioAdminApi.getAgenda(desde, hasta),
  });

  const bloquesPorDia = useMemo(() => {
    const map = new Map<string, EstudioAgendaBloque[]>();
    for (const b of agendaQ.data?.bloques ?? []) {
      const key = b.fecha_desde.slice(0, 10);
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(b);
    }
    return map;
  }, [agendaQ.data]);

  const horas = Array.from({ length: closeHour - openHour }, (_, i) => openHour + i);
  const alturaTotal = (closeHour - openHour) * PX_POR_HORA;

  const label = `${dias[0].getDate()} ${dias[0].toLocaleDateString("es-AR", { month: "short" })} – ${dias[6].getDate()} ${dias[6].toLocaleDateString("es-AR", { month: "short" })}`;

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              setCursor((c) => new Date(c.getFullYear(), c.getMonth(), c.getDate() - 7))
            }
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={() => setCursor(new Date())}>
            Hoy
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              setCursor((c) => new Date(c.getFullYear(), c.getMonth(), c.getDate() + 7))
            }
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
        <span className="t-eyebrow">{label}</span>
      </div>

      {agendaQ.isLoading ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <div className="grid min-w-[720px] grid-cols-[48px_repeat(7,1fr)]">
            <div />
            {dias.map((d) => (
              <div
                key={ymd(d)}
                className={cn(
                  "border-b hairline px-1 pb-1.5 text-center",
                  ymd(d) === hoy && "text-amber-ink",
                )}
              >
                <div className="t-eyebrow">{DIAS[(d.getDay() + 6) % 7]}</div>
                <div className="font-mono text-sm">{d.getDate()}</div>
              </div>
            ))}

            <div className="relative" style={{ height: alturaTotal }}>
              {horas.map((h) => (
                <div
                  key={h}
                  className="absolute right-1 -translate-y-1/2 font-mono text-2xs text-muted-foreground"
                  style={{ top: (h - openHour) * PX_POR_HORA }}
                >
                  {String(h).padStart(2, "0")}h
                </div>
              ))}
            </div>
            {dias.map((d) => {
              const key = ymd(d);
              const bloques = bloquesPorDia.get(key) ?? [];
              const segmentos = ubicarEnCarriles(bloques, openHour, PX_POR_HORA);
              return (
                <div
                  key={key}
                  className="relative border-l hairline"
                  style={{ height: alturaTotal }}
                >
                  {horas.map((h) => (
                    <div
                      key={h}
                      className="absolute left-0 right-0 border-t hairline"
                      style={{ top: (h - openHour) * PX_POR_HORA }}
                    />
                  ))}
                  {segmentos.map((seg) => (
                    <BloqueCard
                      key={`${seg.item.tipo}-${seg.item.id}`}
                      seg={seg}
                      onNavigatePedido={onNavigatePedido}
                    />
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
