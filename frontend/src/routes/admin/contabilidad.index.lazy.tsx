/**
 * contabilidad.index.lazy.tsx — Finanzas: la pantalla única de la plata (#809).
 *
 * Funde el Tablero, Cuentas y Rendición en una sola página (decisión del dueño,
 * 2026-08-03: tres pantallas con fragmentos solapados no se podían leer). Cuatro
 * bloques, en orden de decisión:
 *
 * 1. **KPIs** — cuánta plata hay y cómo vino el mes.
 * 2. **Para repartir hoy** — SOLO pedidos ya cerrados (`repartible`). Lo cobrado
 *    de pedidos en curso se nombra aparte y no genera sugerencias: repartirlo
 *    sería adelantar plata que todavía no devengó (el incidente del 2026-08-03,
 *    "Rental tiene de más $1.647.753" que era float + arranques). Si no hay
 *    nada que mover, la sección lo dice y no muestra números que confundan.
 * 3. **Socios** — la deuda de cada uno (cuenta corriente). Se salda sola con su
 *    parte de lo que se alquila; no se sugieren pagos cash.
 * 4. **Cajas** — la plata real del negocio, editable + alta de cuentas.
 *
 * El bloque mensual "Lo que se generó en {mes}" murió con la página de
 * Rendición (arrancaba de cero cada mes y sugería lo contrario que el
 * acumulado); el endpoint `GET /rendicion/{mes}` sigue vivo en el backend.
 */
import { createLazyFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Scale, Users, Wallet } from "lucide-react";

import { adminApi, type PosicionParte, type SugeridoRendicion } from "@/lib/admin/api";
import { AdminPage } from "@/components/admin/AdminPage";
import { CardGridSkeleton, TableSkeleton } from "@/components/admin/skeletons";
import { ErrorState } from "@/components/admin/ErrorState";
import { QueryState } from "@/components/admin/QueryState";
import { CajaRow } from "@/components/admin/contabilidad/CajaRow";
import { NuevaCuentaForm } from "@/components/admin/contabilidad/NuevaCuentaForm";
import { SaldarDialog } from "@/components/admin/contabilidad/SaldarDialog";
import { SocioCard } from "@/components/admin/contabilidad/SocioCard";
import { formatARS, formatMoney } from "@/lib/format";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { Section } from "@/design-system/composites/Section";
import { Button } from "@/design-system/ui/button";
import { cn } from "@/lib/utils";

export const Route = createLazyFileRoute("/admin/contabilidad/")({
  component: FinanzasPage,
});

function FinanzasPage() {
  useDocumentTitle("Finanzas · Back Office");
  const qc = useQueryClient();
  const [saldarSugerido, setSaldarSugerido] = useState<SugeridoRendicion | null>(null);

  const tableroQ = useQuery({
    queryKey: ["admin", "contabilidad", "tablero"],
    queryFn: () => adminApi.getTablero(),
  });

  // Query propia (no bloquea los KPIs): la posición acumulada recorre todos los
  // meses desde el clean start, así que es más cara que los saldos.
  const posicionesQ = useQuery({
    queryKey: ["admin", "contabilidad", "posiciones"],
    queryFn: () => adminApi.getPosiciones(),
  });

  const invalidar = () => qc.invalidateQueries({ queryKey: ["admin", "contabilidad"] });

  const data = tableroQ.data;
  const socios = data?.disponible.socios ?? [];
  const cajas = data?.disponible.cajas ?? [];
  // Las cajas del Estudio se listan aparte (otra economía). La clasificación es
  // por `socio`, el mismo puente caja↔cobrador que usa el backend; los totales
  // los manda él ya sumados (`disponible_por_economia`).
  const cajasEstudio = cajas.filter((c) => c.socio === "Estudio");
  const cajasRental = cajas.filter((c) => c.socio !== "Estudio");

  return (
    <AdminPage
      title="Finanzas"
      maxW="detail"
      description="Toda la plata en una pantalla: cuánto hay, qué se reparte hoy, cómo está cada socio y las cajas."
    >
      <div className="space-y-6">
        {tableroQ.isLoading && <CardGridSkeleton count={4} />}
        {tableroQ.isError && <ErrorState error={tableroQ.error} onRetry={tableroQ.refetch} />}

        {/* 1 · KPIs. Rental y el Estudio son DOS economías (#1283): no se
            mezclan en un mismo número. El de Rental es su parte de lo
            facturado menos sus gastos; el del Estudio va aparte, con su caja. */}
        {data && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="card-elevated p-5">
              <div className="t-eyebrow">Plata disponible · Rental</div>
              <div className="font-mono text-3xl font-semibold tabular-nums text-ink mt-1">
                {formatMoney(data.disponible_por_economia.rental, "ARS")}
              </div>
              {(data.disponible.totales.USD ?? 0) !== 0 && (
                <div className="font-mono text-lg font-semibold tabular-nums text-ink">
                  {formatMoney(data.disponible.totales.USD, "USD")}
                </div>
              )}
              <div className="text-xs text-muted-foreground mt-1">
                Sus cajas · al {data.disponible.as_of}
                {data.disponible_por_economia.estudio !== 0 && (
                  <>
                    {" · "}el Estudio tiene{" "}
                    {formatMoney(data.disponible_por_economia.estudio, "ARS")} aparte
                  </>
                )}
              </div>
            </div>

            <div className="card-elevated p-5">
              <div className="t-eyebrow">Ganancia neta · Rental · {data.ganancia_mes.mes}</div>
              <div
                className={`font-mono text-3xl font-semibold tabular-nums mt-1 ${
                  data.ganancia_mes.neta >= 0 ? "text-ink" : "text-destructive"
                }`}
              >
                {formatARS(data.ganancia_mes.neta)}
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                Su parte de lo facturado {formatARS(data.ganancia_mes.parte_rental)} − gastos{" "}
                {formatARS(data.ganancia_mes.gastos)}
              </div>
              {(data.ganancia_mes.comisiones_duenos !== 0 ||
                data.ganancia_mes.parte_estudio !== 0) && (
                <div className="text-xs text-muted-foreground mt-1">
                  Del total facturado ({formatARS(data.ganancia_mes.ingresos)}) se descuentan{" "}
                  {formatARS(data.ganancia_mes.comisiones_duenos)} de los dueños
                  {data.ganancia_mes.parte_estudio !== 0 && (
                    <> y {formatARS(data.ganancia_mes.parte_estudio)} del Estudio</>
                  )}
                  .
                </div>
              )}
            </div>
          </div>
        )}

        {/* 2 · Para repartir hoy — el acumulado de pedidos CERRADOS. */}
        <QueryState query={posicionesQ} skeleton={<TableSkeleton rows={1} cols={4} />}>
          {(pos) => {
            const enCursoTotal = pos.partes.reduce((acc, p) => acc + (p.en_curso ?? 0), 0);
            const alguienEspera = pos.partes.some((p) => p.repartible > 0);
            return (
              <Section
                title="Para repartir hoy"
                subtitle="Solo cuenta la plata de pedidos ya cerrados. Lo cobrado de pedidos en curso se reparte cuando cierren."
                icon={Scale}
              >
                {/* El estado "Al día" se decide por si ALGUIEN espera cobrar, no
                    por si hay sugerencias: un socio nunca aparece como pagador
                    sugerido (su deuda se salda sola), así que puede haber una
                    parte esperando sin ninguna transferencia sugerible. Ahí las
                    tarjetas se muestran igual — esconderlas diría "al día"
                    cuando no lo está. */}
                {!alguienEspera ? (
                  <EmptyState
                    icon={<Scale className="h-6 w-6" />}
                    title="Al día — nada para repartir hoy"
                    sub={
                      enCursoTotal > 0
                        ? `Hay ${formatARS(enCursoTotal)} cobrados de pedidos que todavía no cerraron — se reparten cuando cierren.`
                        : "Ninguna parte espera cobrar nada."
                    }
                  />
                ) : (
                  <>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      {pos.partes.map((p) => (
                        <PosicionCard key={p.parte} parte={p} alguienEspera={alguienEspera} />
                      ))}
                    </div>
                    <div className="mt-4 space-y-2 border-t hairline pt-4">
                      <p className="text-xs text-muted-foreground">
                        Para que quede repartido. Cada botón registra una transferencia REAL en el
                        libro — usalo cuando la plata se movió de verdad.
                      </p>
                      {pos.sugeridos.length === 0 && (
                        <p className="text-sm text-muted-foreground">
                          Sin transferencias para sugerir: la plata que falta no está hoy en una
                          caja del negocio (la deuda de un socio se salda sola con su parte, no se
                          le pide cash).
                        </p>
                      )}
                      {pos.sugeridos.map((s, i) => (
                        <div
                          key={i}
                          className="flex flex-wrap items-center gap-3 rounded-md border hairline px-3 py-2.5"
                        >
                          <span className="font-medium text-ink">{s.de}</span>
                          <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                          <span className="font-medium text-ink">{s.a}</span>
                          <span className="ml-auto font-mono text-sm tabular-nums text-ink">
                            {formatARS(s.monto)}
                          </span>
                          <Button variant="outline" size="sm" onClick={() => setSaldarSugerido(s)}>
                            Registrar la transferencia
                          </Button>
                        </div>
                      ))}
                    </div>
                    {enCursoTotal > 0 && (
                      <p className="mt-3 text-xs text-muted-foreground">
                        Aparte hay {formatARS(enCursoTotal)} cobrados de pedidos que todavía no
                        cerraron — se reparten cuando cierren.
                      </p>
                    )}
                  </>
                )}
              </Section>
            );
          }}
        </QueryState>

        {/* 3 · Socios — deuda que se salda sola con su parte. */}
        {socios.length > 0 && (
          <Section
            title="Socios"
            subtitle="La deuda de cada uno se salda sola con su parte de lo que se alquila — no hace falta transferir."
            icon={Users}
          >
            <div className="grid gap-3 sm:grid-cols-2">
              {socios.map((s) => (
                <SocioCard key={s.id} socio={s} onChanged={invalidar} />
              ))}
            </div>
            <p className="mt-3 text-xs text-muted-foreground">
              El <strong>arranque</strong> es lo que cobró antes del sistema. Se va saldando con{" "}
              <strong>su parte</strong> de lo que se alquila: cuando llega a cero están a mano, y si
              se da vuelta, Rental le debe a él.
            </p>
          </Section>
        )}

        {/* 4 · Cajas — plata real, editable. Las del Estudio van al final y con
            su propio total: es otra economía, no plata de Rental. */}
        {data && (
          <Section title="Cajas" subtitle="La plata real del negocio y dónde está." icon={Wallet}>
            <div className="overflow-x-auto rounded-lg border hairline">
              {/* eslint-disable-next-line no-restricted-syntax -- tabla de edición inline (CajaRow con estado propio + totales en tfoot), no es tabla de display; AdminTable no aplica */}
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b hairline text-left text-xs uppercase tracking-wider text-muted-foreground">
                    <th className="px-3 py-2 font-medium">Caja</th>
                    <th className="px-3 py-2 font-medium">Tipo</th>
                    <th className="px-3 py-2 font-medium text-right">Saldo actual</th>
                    <th className="px-3 py-2 font-medium text-right">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {cajasRental.map((c) => (
                    <CajaRow key={c.id} cuenta={c} onChanged={invalidar} />
                  ))}
                  <tr className="border-t hairline bg-muted/20">
                    <td className="px-3 py-2 font-medium" colSpan={2}>
                      Total Rental
                    </td>
                    <td className="px-3 py-2 text-right font-mono font-semibold tabular-nums">
                      {formatMoney(data.disponible_por_economia.rental, "ARS")}
                    </td>
                    <td />
                  </tr>
                  {cajasEstudio.map((c) => (
                    <CajaRow key={c.id} cuenta={c} onChanged={invalidar} />
                  ))}
                  {cajasEstudio.length > 0 && (
                    <tr className="border-t hairline bg-muted/20">
                      <td className="px-3 py-2 font-medium" colSpan={2}>
                        Total Estudio
                      </td>
                      <td className="px-3 py-2 text-right font-mono font-semibold tabular-nums">
                        {formatMoney(data.disponible_por_economia.estudio, "ARS")}
                      </td>
                      <td />
                    </tr>
                  )}
                </tbody>
                <tfoot>
                  {(data.disponible.totales.USD ?? 0) !== 0 && (
                    <tr className="border-t hairline">
                      <td className="px-3 py-2 font-medium" colSpan={2}>
                        Total disponible (USD)
                      </td>
                      <td className="px-3 py-2 text-right font-mono font-semibold tabular-nums">
                        {formatMoney(data.disponible.totales.USD, "USD")}
                      </td>
                      <td />
                    </tr>
                  )}
                </tfoot>
              </table>
            </div>
            <div className="mt-3">
              <NuevaCuentaForm onCreated={invalidar} />
            </div>
          </Section>
        )}

        <ReconciliacionPanel />
      </div>

      {saldarSugerido && (
        <SaldarDialog
          sugerido={saldarSugerido}
          onOpenChange={(open) => !open && setSaldarSugerido(null)}
          onSaldado={() => {
            invalidar();
            setSaldarSugerido(null);
          }}
        />
      )}
    </AdminPage>
  );
}

/** La posición REPARTIBLE de una parte (solo pedidos cerrados). Solo se muestra
 *  cuando hay transferencias sugeridas — si no hay nada que mover, la sección
 *  entera lo dice con un estado vacío en vez de 4 tarjetas de números. */
function PosicionCard({ parte, alguienEspera }: { parte: PosicionParte; alguienEspera: boolean }) {
  const r = parte.repartible;
  const espera = r > 0;
  // "Retiene" solo si alguien del otro lado espera esa plata: un negativo sin
  // receptor (ej. el espejo de la deuda de los socios) no es algo a resolver
  // moviendo cash — se salda solo con su parte (sección Socios).
  const retiene = r < 0 && alguienEspera;
  const tono = espera
    ? "border-amber/50 bg-amber/10"
    : retiene
      ? "border-amber/40 bg-amber/5"
      : "hairline bg-surface";

  return (
    <div className={cn("rounded-lg border p-3.5", tono)}>
      <div className="t-eyebrow">{parte.parte}</div>
      <div className="mt-1.5 font-mono text-xl font-semibold tabular-nums text-ink">
        {formatARS(Math.abs(r))}
      </div>
      <div className="text-sm text-muted-foreground">
        {espera ? "le falta recibir" : retiene ? "retiene plata de otros" : "al día"}
      </div>
      <div className="mt-2 border-t hairline pt-1.5 font-mono text-xs tabular-nums text-muted-foreground">
        le corresponde {formatARS(parte.le_corresponde)} · cobró {formatARS(parte.cobro_cerrados)}
        {parte.arranque !== 0 && <> · arranque {formatARS(parte.arranque)}</>}
        {parte.repartido !== 0 && <> · repartido {formatARS(parte.repartido)}</>}
        {parte.en_curso !== 0 && <> · en curso {formatARS(parte.en_curso)}</>}
      </div>
    </div>
  );
}

function ReconciliacionPanel() {
  const q = useQuery({
    queryKey: ["admin", "contabilidad", "reconciliacion"],
    queryFn: () => adminApi.getReconciliacionContable(),
  });
  const r = q.data;
  if (!r) return null;

  const problemas: string[] = [];
  if (r.saldos_negativos.cantidad > 0)
    problemas.push(`${r.saldos_negativos.cantidad} caja(s) con saldo negativo`);
  if (r.pagos_sin_socio.cantidad > 0)
    problemas.push(
      `${r.pagos_sin_socio.cantidad} cobro(s) sin socio asignado (${formatARS(r.pagos_sin_socio.monto)})`,
    );
  if (r.movimientos_cuenta_inactiva.cantidad > 0)
    problemas.push(
      `${r.movimientos_cuenta_inactiva.cantidad} movimiento(s) en cuentas dadas de baja`,
    );
  // Este chequeo BAJA el semáforo, así que tiene que poder explicarse: sin esta
  // línea la caja se pintaba roja con la lista vacía.
  if (r.devengado_sin_cuenta && r.devengado_sin_cuenta.cantidad > 0)
    problemas.push(
      `${formatARS(r.devengado_sin_cuenta.monto)} devengados para ` +
        `${r.devengado_sin_cuenta.beneficiarios.map((b) => b.beneficiario).join(", ")} — ` +
        `no tienen caja donde verse (revisá el modelo de comisiones o creá la cuenta)`,
    );
  if (!r.reporte.ok) {
    const sl = r.reporte.pagados_sin_ledger;
    const sp = r.reporte.sobrepagados;
    if (sl && sl.cantidad > 0)
      problemas.push(
        `${sl.cantidad} pedido(s) marcados pagados pero sin pagos registrados ` +
          `(no entran al reporte): #${sl.ids.join(", #")}`,
      );
    if (sp && sp.cantidad > 0)
      problemas.push(
        `${sp.cantidad} pedido(s) con más cobrado que su total (¿se editó el pedido ` +
          `después de cobrar?): #${sp.ids.join(", #")}`,
      );
    if (!(sl && sl.cantidad > 0) && !(sp && sp.cantidad > 0))
      problemas.push("el reporte de liquidación tiene observaciones — revisalas en Liquidación");
  }

  // Informativo, NO baja el semáforo (a diferencia de los `problemas` de arriba):
  // la divergencia `liquidar` vs `liquidar_rango` es conocida y esperada mientras
  // las dos fórmulas convivan (`contabilidad/CLAUDE.md`). Sin esto, el número que
  // ya calcula `reconciliar()` no se veía en ningún lado — nadie se enteraba salvo
  // greppeando la API.
  const divergencias = r.cc_vs_posicion_divergente?.partes ?? [];

  return (
    <div
      className={`rounded-lg border p-4 ${
        r.ok ? "hairline bg-muted/10" : "border-destructive/40 bg-destructive/5"
      }`}
    >
      <div className="t-eyebrow mb-1">Reconciliación</div>
      {r.ok ? (
        <div className="text-sm text-ink">✓ Todo cuadra.</div>
      ) : (
        <ul className="text-sm text-destructive list-disc pl-5 space-y-0.5">
          {problemas.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      )}
      {divergencias.length > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          Nota: {divergencias.map((d) => `${d.parte} ${formatARS(d.diferencia)}`).join(", ")} de
          diferencia entre cuenta corriente y posición acumulada — esperado mientras un mes cerrado
          use la foto congelada y la cuenta corriente recalcule en vivo; no afecta este semáforo.
        </p>
      )}
    </div>
  );
}
