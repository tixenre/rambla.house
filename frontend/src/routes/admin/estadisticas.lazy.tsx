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
import { Section } from "@/design-system/composites/Section";
import { StatCard } from "@/design-system/composites/StatCard";
import { CardGridSkeleton, TableSkeleton } from "@/components/admin/skeletons";
import { ErrorState } from "@/components/admin/ErrorState";

export const Route = createLazyFileRoute("/admin/estadisticas")({
  component: EstadisticasPage,
});

function EstadisticasPage() {
  useDocumentTitle("Estadísticas · Back Office");
  const statsQ = useQuery({
    queryKey: ["admin", "estadisticas"],
    queryFn: () => adminApi.getEstadisticas(),
  });

  const data = statsQ.data;

  return (
    <AdminPage
      title="Estadísticas"
      description="Métricas del negocio. El reporte de liquidación ahora vive en Finanzas."
    >
      <div className="space-y-6">
        <p className="text-xs text-muted-foreground">
          Solo se contabilizan pedidos confirmados, retirados y finalizados.
        </p>

        {statsQ.isLoading && <CardGridSkeleton count={4} className="md:grid-cols-4" />}
        {statsQ.error && <ErrorState error={statsQ.error} onRetry={statsQ.refetch} />}

        {data && (
          <>
            {/* KPIs */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard
                icon={DollarSign}
                label="Facturado total"
                value={fmtArs(data.totales.total_ars)}
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
                meta={fmtArs(data.mejor_peor_mes.mejor_total)}
              />
            </div>

            {/* KPIs derivados: ticket promedio + LTV. Calculados en frontend
            porque ya tenemos todos los totales — no hace falta backend. */}
            {(() => {
              const t = data.totales;
              const ticket = t.total_pedidos ? Math.round(t.total_ars / t.total_pedidos) : 0;
              const ltv = t.total_clientes ? Math.round(t.total_ars / t.total_clientes) : 0;
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
                      value: Number(m.total_ars) || 0,
                    }))}
                />
              </Section>

              {/* Crecimiento */}
              <Section title="Crecimiento mes a mes" subtitle="% vs mes anterior">
                <div className="space-y-1.5">
                  {data.crecimiento.slice(0, 8).map((c) => (
                    <div key={c.mes} className="flex items-center justify-between text-sm">
                      <span className="font-mono text-xs text-muted-foreground">{c.mes}</span>
                      <span className="tabular-nums text-ink">{fmtArs(c.total_ars)}</span>
                      <span
                        className={`inline-flex items-center gap-1 font-mono text-xs tabular-nums w-20 justify-end ${
                          c.crecimiento_pct >= 0 ? "text-verde-ink" : "text-destructive"
                        }`}
                      >
                        {c.crecimiento_pct >= 0 ? (
                          <TrendingUp className="h-3 w-3" />
                        ) : (
                          <TrendingDown className="h-3 w-3" />
                        )}
                        {c.crecimiento_pct >= 0 ? "+" : ""}
                        {c.crecimiento_pct}%
                      </span>
                    </div>
                  ))}
                </div>
              </Section>

              {/* Top equipos */}
              <Section title="Top equipos" subtitle="Por facturación">
                <RankList
                  items={data.top_equipos.map((e) => ({
                    primary: e.equipo,
                    secondary: `${e.veces}× alquilado`,
                    value: fmtArs(e.total_ars),
                  }))}
                  icon={Package}
                />
              </Section>

              {/* Top clientes */}
              <Section title="Top clientes" subtitle="Por facturación">
                <RankList
                  items={data.top_clientes.map((c) => ({
                    primary: c.cliente,
                    secondary: `${c.pedidos} pedidos`,
                    value: fmtArs(c.total_ars),
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
                    value: fmtArs(c.total_ars),
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
                    value: fmtArs(d.total_ars),
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
                    const total = data.gastos_por_categoria.reduce((acc, g) => acc + g.monto, 0);
                    return data.gastos_por_categoria.map((g) => ({
                      primary: g.categoria,
                      secondary:
                        total > 0 ? `${Math.round((g.monto / total) * 100)}% del total` : "",
                      value: fmtArs(g.monto),
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
                  value={fmtArs(data.estudio.totales.total_ars ?? 0)}
                />
              </div>
              <BarChart
                data={[...data.estudio.por_mes]
                  .slice(0, 12)
                  .reverse()
                  .map((m) => ({
                    label: m.mes,
                    value: Number(m.total_ars) || 0,
                  }))}
              />
            </Section>
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
