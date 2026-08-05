import { createLazyFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  TrendingUp,
  TrendingDown,
  Users,
  Package,
  DollarSign,
  Calendar,
  Calculator,
  Heart,
  Repeat,
  Search,
  SearchX,
  Clapperboard,
  Clock,
  Wallet,
} from "lucide-react";

import { adminApi } from "@/lib/admin/api";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { cn } from "@/lib/utils";
import { fmtArs } from "@/lib/format";
import { AdminPage } from "@/components/admin/AdminPage";
import { BarChart, RankList } from "@/components/admin/LiquidacionReporte";
import { CalendarioActividad } from "@/components/admin/CalendarioActividad";
import { Section } from "@/design-system/composites/Section";
import { StatCard } from "@/design-system/composites/StatCard";
import { SegmentedControl } from "@/design-system/ui/segmented-control";
import { CardGridSkeleton, TableSkeleton } from "@/components/admin/skeletons";
import { ErrorState } from "@/components/admin/ErrorState";

export const Route = createLazyFileRoute("/admin/estadisticas")({
  component: EstadisticasPage,
});

type Modo = "nominal" | "ajustado";

// "2026-06" → "junio de 2026". Mismo patrón local que ya usan
// contabilidad.movimientos/rendicion/estudio.lazy.tsx (sin extraerlo a un
// helper compartido — es un one-liner, no vale la indirección).
function mesLargo(mes: string): string {
  return new Date(`${mes}-01T00:00:00`).toLocaleDateString("es-AR", {
    month: "long",
    year: "numeric",
  });
}

function EstadisticasPage() {
  useDocumentTitle("Estadísticas · Back Office");
  const [modo, setModo] = useState<Modo>("nominal");
  const statsQ = useQuery({
    queryKey: ["admin", "estadisticas"],
    queryFn: () => adminApi.getEstadisticas(),
  });

  // Calendario de actividad: query propia (no parte de `statsQ`) porque tiene
  // su propio eje — año o "todos" — y cambiarlo no debe refetchear el resto
  // de la página. `anioCal=undefined` en la primera carga → el backend elige
  // el año más reciente con datos (mismo criterio "último año" que un
  // selector vacío). `modoCalendario="todos"` ignora `anioCal` y apila TODOS
  // los años en una sola respuesta (ver CalendarioActividad).
  const [modoCalendario, setModoCalendario] = useState<"anio" | "todos">("anio");
  const [anioCal, setAnioCal] = useState<number | undefined>(undefined);
  const calQ = useQuery({
    queryKey: [
      "admin",
      "estadisticas",
      "actividad-calendario",
      modoCalendario === "todos" ? "todos" : (anioCal ?? "ultimo"),
    ],
    queryFn: () => adminApi.getActividadCalendario(anioCal, modoCalendario === "todos"),
  });

  // Distribución por período cíclico ("todos los lunes sumados contra todos
  // los martes") — sobre TODO el historial, sin eje de año: query propia,
  // fija (sin params que la invaliden — nunca refetchea sola).
  const distQ = useQuery({
    queryKey: ["admin", "estadisticas", "actividad-distribucion"],
    queryFn: () => adminApi.getActividadDistribucion(),
  });

  const data = statsQ.data;
  const ajustado = modo === "ajustado";
  // Elige nominal o ajustado según el toggle — el backend ya manda los dos
  // números resueltos (`services/ipc.py`, ajuste EN ORIGEN); el front solo
  // elige cuál mostrar, nunca calcula el ajuste (MEMORIA 2026-06-29 — "el
  // front no calcula plata", generalizado acá al ajuste por inflación).
  const val = (nominal: number, ajustadoVal: number) => (ajustado ? ajustadoVal : nominal);

  return (
    <AdminPage
      title="Estadísticas"
      description="Métricas del negocio. El reporte de liquidación ahora vive en Finanzas."
    >
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">
            Solo se contabilizan pedidos confirmados, retirados y finalizados.
          </p>
          <div className="flex items-center gap-2">
            {ajustado && data?.ipc.mes_referencia && (
              <span className="text-2xs font-mono uppercase tracking-[0.1em] text-muted-foreground">
                pesos de {mesLargo(data.ipc.mes_referencia)}
              </span>
            )}
            <SegmentedControl
              variant="pill"
              ariaLabel="Pesos nominales o ajustados por IPC"
              value={modo}
              onChange={(v) => setModo(v as Modo)}
              options={[
                { value: "nominal", label: "Pesos" },
                { value: "ajustado", label: "Ajustado por IPC" },
              ]}
            />
          </div>
        </div>

        {statsQ.isLoading && <CardGridSkeleton count={4} className="md:grid-cols-4" />}
        {statsQ.error && <ErrorState error={statsQ.error} onRetry={statsQ.refetch} />}

        {data && (
          <>
            {/* KPIs */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard
                icon={DollarSign}
                label="Facturado total"
                value={fmtArs(val(data.totales.total_ars, data.totales.total_ars_ajustado))}
              />
              <StatCard
                icon={Calendar}
                label="Pedidos"
                value={String(data.totales.total_pedidos ?? 0)}
              />
              <StatCard
                icon={Users}
                label="Clientes"
                value={String(data.totales.total_clientes ?? 0)}
              />
              <StatCard
                icon={TrendingUp}
                label="Mejor mes"
                value={data.mejor_peor_mes.mejor_mes ?? "—"}
                meta={fmtArs(
                  val(
                    data.mejor_peor_mes.mejor_total ?? 0,
                    data.mejor_peor_mes.mejor_total_ajustado ?? 0,
                  ),
                )}
              />
            </div>

            {/* KPIs derivados: ticket promedio + LTV. Calculados en frontend
            porque ya tenemos todos los totales — no hace falta backend (son un
            cociente de dos números que el backend YA resolvió, no una regla de
            precio/descuento/IVA nueva). */}
            {(() => {
              const t = data.totales;
              const totalMostrado = val(t.total_ars, t.total_ars_ajustado);
              const ticket = t.total_pedidos ? Math.round(totalMostrado / t.total_pedidos) : 0;
              const ltv = t.total_clientes ? Math.round(totalMostrado / t.total_clientes) : 0;
              const pedidosPorCliente = t.total_clientes
                ? (t.total_pedidos / t.total_clientes).toFixed(1)
                : "0";
              return (
                <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                  <StatCard
                    icon={Calculator}
                    label="Ticket promedio"
                    value={fmtArs(ticket)}
                    meta="Facturado / Pedidos"
                  />
                  <StatCard
                    icon={Heart}
                    label="LTV cliente"
                    value={fmtArs(ltv)}
                    meta="Facturado / Clientes"
                  />
                  <StatCard
                    icon={Repeat}
                    label="Pedidos / cliente"
                    value={pedidosPorCliente}
                    meta="Frecuencia promedio"
                  />
                </div>
              );
            })()}

            <div className="grid lg:grid-cols-2 gap-6">
              {/* Por mes (sparkline) */}
              <Section title="Facturación por mes" subtitle="Últimos 24 meses">
                <BarChart
                  data={[...data.por_mes]
                    .slice(0, 12)
                    .reverse()
                    .map((m) => ({
                      label: m.mes,
                      value: Number(val(m.total_ars, m.total_ars_ajustado)) || 0,
                    }))}
                />
              </Section>

              {/* Crecimiento — en modo ajustado usa crecimiento_pct_ajustado,
                  que puede diferir MUCHO del nominal (un mes puede crecer en
                  pesos corrientes y caer en términos reales: eso es lo que
                  este toggle existe para mostrar). */}
              <Section title="Crecimiento mes a mes" subtitle="% vs mes anterior">
                <div className="space-y-1.5">
                  {data.crecimiento.slice(0, 8).map((c) => {
                    const pct = val(c.crecimiento_pct, c.crecimiento_pct_ajustado);
                    return (
                      <div key={c.mes} className="flex items-center justify-between text-sm">
                        <span className="font-mono text-xs text-muted-foreground">{c.mes}</span>
                        <span className="tabular-nums text-ink">
                          {fmtArs(val(c.total_ars, c.total_ars_ajustado))}
                        </span>
                        <span
                          className={`inline-flex items-center gap-1 font-mono text-xs tabular-nums w-20 justify-end ${
                            pct >= 0 ? "text-verde-ink" : "text-destructive"
                          }`}
                        >
                          {pct >= 0 ? (
                            <TrendingUp className="h-3 w-3" />
                          ) : (
                            <TrendingDown className="h-3 w-3" />
                          )}
                          {pct >= 0 ? "+" : ""}
                          {pct}%
                        </span>
                      </div>
                    );
                  })}
                </div>
              </Section>

              {/* Top equipos */}
              <Section title="Top equipos" subtitle="Por facturación">
                <RankList
                  items={data.top_equipos.map((e) => ({
                    primary: e.equipo,
                    secondary: `${e.veces}× alquilado`,
                    value: fmtArs(val(e.total_ars, e.total_ars_ajustado)),
                  }))}
                  icon={Package}
                />
              </Section>

              {/* Top equipos por rentabilidad neta (ingreso − costo de compra)
                  — pedido del dueño: un equipo caro puede facturar más y
                  rentabilizar menos que uno barato. Solo cuenta equipos con
                  `costo_compra` cargado (se completa en la ficha del equipo).
                  SIN toggle de IPC a propósito: `costo_compra` es un
                  desembolso puntual, no una serie mensual — ajustarlo
                  necesitaría además la fecha de compra, otra pregunta. */}
              {data.top_equipos_rentabilidad.length > 0 && (
                <Section
                  title="Top equipos por rentabilidad neta"
                  subtitle={
                    ajustado
                      ? "Ingreso menos costo de compra — siempre en pesos nominales"
                      : "Ingreso menos costo de compra — solo equipos con el costo cargado"
                  }
                >
                  <RankList
                    items={data.top_equipos_rentabilidad.map((e) => ({
                      primary: e.equipo,
                      secondary: `${e.veces}× · costo ${fmtArs(e.costo_compra)}`,
                      value: fmtArs(e.rentabilidad_neta),
                    }))}
                    icon={Wallet}
                  />
                </Section>
              )}

              {/* Top clientes */}
              <Section title="Top clientes" subtitle="Por facturación">
                <RankList
                  items={data.top_clientes.map((c) => ({
                    primary: c.cliente,
                    secondary: `${c.pedidos} pedidos`,
                    value: fmtArs(val(c.total_ars, c.total_ars_ajustado)),
                  }))}
                  icon={Users}
                />
              </Section>

              {/* Equipos más guardados como favoritos */}
              {(data.favoritos_equipo?.length ?? 0) > 0 && (
                <Section
                  title="Equipos más guardados"
                  subtitle="Equipos que los clientes marcan como favoritos"
                >
                  <RankList
                    items={(data.favoritos_equipo ?? []).map((e) => ({
                      primary: e.equipo,
                      secondary: `${e.clientes_unicos} cliente${e.clientes_unicos !== 1 ? "s" : ""}`,
                      value: `${e.total_favoritos}×`,
                    }))}
                    icon={Heart}
                  />
                </Section>
              )}

              {/* Recurrentes */}
              <Section title="Clientes recurrentes" subtitle="Más de 1 alquiler">
                <RankList
                  items={data.clientes_recurrentes.map((c) => ({
                    primary: c.cliente,
                    secondary: `${c.veces_alquiladas}× alquilado`,
                    value: fmtArs(val(c.total_ars, c.total_ars_ajustado)),
                  }))}
                  icon={Users}
                />
              </Section>

              {/* Por dueño */}
              <Section title="Por dueño" subtitle="Reparto de equipos">
                <RankList
                  items={data.por_dueno.map((d) => ({
                    primary: d.dueno,
                    secondary: `${d.items} ítems`,
                    value: fmtArs(val(d.total_ars, d.total_ars_ajustado)),
                  }))}
                  icon={Package}
                />
              </Section>

              {/* Gastos por categoría — Mantenimiento/Servicios/etc, histórico
                  completo (backend/contabilidad, motor único de la plata "de
                  adentro"; ya alimenta el P&L mensual, acá se reusa tal cual). */}
              <Section
                title="Gastos por categoría"
                subtitle="Mantenimiento, servicios y el resto — histórico completo"
              >
                <RankList
                  items={(() => {
                    const montos = data.gastos_por_categoria.map((g) =>
                      val(g.monto, g.monto_ajustado),
                    );
                    const total = montos.reduce((acc, m) => acc + m, 0);
                    return data.gastos_por_categoria.map((g, i) => ({
                      primary: g.categoria,
                      secondary:
                        total > 0 ? `${Math.round((montos[i] / total) * 100)}% del total` : "",
                      value: fmtArs(montos[i]),
                    }));
                  })()}
                  icon={Wallet}
                />
              </Section>
            </div>

            {/* Estudio: economía separada (#1283) — las tarjetas/rankings de
                arriba ya la excluyen (backend filtra tipo NOT IN ('estudio',
                'estudio_fijo')); acá se muestra aparte, no mezclada. */}
            <Section title="Estudio" subtitle="Economía separada — no se mezcla con el resto">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                <StatCard
                  icon={Clapperboard}
                  label="Turnos"
                  value={String(data.estudio.totales.total_turnos ?? 0)}
                />
                <StatCard
                  icon={Calendar}
                  label="Slots fijos (meses)"
                  value={String(data.estudio.totales.total_meses_slot_fijo ?? 0)}
                />
                <StatCard
                  icon={Clock}
                  label="Horas vendidas"
                  value={String(Math.round(data.estudio.totales.horas_vendidas ?? 0))}
                />
                <StatCard
                  icon={DollarSign}
                  label="Facturado"
                  value={fmtArs(
                    val(data.estudio.totales.total_ars, data.estudio.totales.total_ars_ajustado) ??
                      0,
                  )}
                />
              </div>
              <BarChart
                data={[...data.estudio.por_mes]
                  .slice(0, 12)
                  .reverse()
                  .map((m) => ({
                    label: m.mes,
                    value: Number(val(m.total_ars, m.total_ars_ajustado)) || 0,
                  }))}
              />
            </Section>

            {/* Calendario de actividad — heatmap estilo GitHub/Apple Fitness.
                Métrica = pedidos con equipo AFUERA ese día (no solo el día de
                retiro), mismo universo rental-only que el resto de la página. */}
            <Section title="Actividad" subtitle="Calendario de días con equipo afuera">
              <CalendarioActividad
                data={calQ.data}
                loading={calQ.isLoading}
                modo={modoCalendario}
                anioSeleccionado={anioCal}
                onSeleccionarAnio={(a) => {
                  setModoCalendario("anio");
                  setAnioCal(a);
                }}
                onSeleccionarTodos={() => setModoCalendario("todos")}
              />
            </Section>

            {/* Distribución por período cíclico — "¿todos los lunes suman más
                que todos los martes?" — complementa el calendario de arriba
                (que muestra fechas concretas) revelando si hay un patrón
                sistemático. Misma métrica (equipo afuera), sobre TODO el
                historial, sin eje de año. */}
            {distQ.data && (
              <Section
                title="Distribución"
                subtitle="Suma de equipo afuera por período — todo el historial"
              >
                <div className="grid md:grid-cols-2 gap-6 mb-6">
                  <div>
                    <p className="text-xs text-muted-foreground mb-2">Por día de semana</p>
                    <BarChart
                      data={distQ.data.dia_semana.map((d) => ({
                        label: d.label,
                        value: d.total,
                      }))}
                      labelFn={(l) => l}
                      valueFormat={(v) => `${v}×`}
                    />
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground mb-2">Por mes del año</p>
                    <BarChart
                      data={distQ.data.mes.map((m) => ({ label: m.label, value: m.total }))}
                      labelFn={(l) => l}
                      valueFormat={(v) => `${v}×`}
                    />
                  </div>
                </div>
                {/* 31 barras — su propia fila, no encaja en 2/3 columnas. */}
                <div>
                  <p className="text-xs text-muted-foreground mb-2">
                    Por día del mes
                    <span className="text-3xs"> (suma cruda — el 31 solo lo tienen 7 meses)</span>
                  </p>
                  <BarChart
                    data={distQ.data.dia_mes.map((d) => ({
                      label: String(d.dia),
                      value: d.total,
                    }))}
                    labelFn={(l) => l}
                    valueFormat={(v) => `${v}×`}
                  />
                </div>
              </Section>
            )}
          </>
        )}

        <BusquedasSection />
      </div>
    </AdminPage>
  );
}

const VENTANAS: { label: string; dias?: number }[] = [
  { label: "30 días", dias: 30 },
  { label: "90 días", dias: 90 },
  { label: "Todo" },
];

function BusquedasSection() {
  const [dias, setDias] = useState<number | undefined>(30);
  const q = useQuery({
    queryKey: ["admin", "busquedas", dias ?? "all"],
    queryFn: () => adminApi.getBusquedas(dias),
  });
  const data = q.data;
  const fmtFecha = (s: string | null) => (s ? new Date(s).toLocaleDateString("es-AR") : "—");

  return (
    <section className="space-y-3 border-t hairline pt-6">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-display text-2xl text-ink">Qué busca la gente</h2>
          <p className="text-sm text-muted-foreground">
            Términos del buscador del catálogo. Lo que buscan y da <strong>0 resultados</strong> es
            demanda que todavía no estás cubriendo.
          </p>
        </div>
        <div className="flex gap-1">
          {VENTANAS.map((v) => (
            <button
              key={v.label}
              onClick={() => setDias(v.dias)}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium border hairline transition",
                dias === v.dias ? "bg-ink text-background" : "text-muted-foreground hover:text-ink",
              )}
            >
              {v.label}
            </button>
          ))}
        </div>
      </div>

      {q.isLoading && <TableSkeleton rows={5} cols={2} />}
      {q.error && <ErrorState error={q.error} onRetry={q.refetch} />}

      {data && (
        <div className="grid gap-4 md:grid-cols-2">
          <Section title="Más buscado" subtitle="Ordenado por cantidad de búsquedas">
            <RankList
              items={data.top.map((r) => ({
                primary: r.texto,
                secondary: `${fmtFecha(r.ultima)} · ${r.max_resultados ?? 0} resultados`,
                value: `${r.veces}×`,
              }))}
              icon={Search}
            />
          </Section>
          <Section title="Buscado sin resultados" subtitle="Demanda no cubierta (0 resultados)">
            <RankList
              items={data.zero.map((r) => ({
                primary: r.texto,
                secondary: `última vez: ${fmtFecha(r.ultima)}`,
                value: `${r.veces}×`,
              }))}
              icon={SearchX}
            />
          </Section>
        </div>
      )}
    </section>
  );
}
