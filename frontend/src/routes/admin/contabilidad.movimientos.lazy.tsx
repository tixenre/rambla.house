/**
 * contabilidad.movimientos.lazy.tsx — Libro de movimientos (#809, Fase 2/3).
 *
 * Registra y lista los movimientos manuales de plata: gastos, transferencias
 * entre cajas, retiros y aportes de socios. Los cobros de pedidos aparecen como
 * una línea mensual read-only (derivan de los pagos de alquiler, no se cargan a
 * mano) que se DESPLIEGA para ver los pagos individuales del mes inline — misma
 * fuente única que /admin/pagos (el "ver ledger completo"). Cada movimiento se
 * puede editar (incluida la fecha) y borrar sin justificar — son los asientos
 * propios del dueño (2026-08). Por debajo el borrado sigue siendo soft-delete,
 * invisible desde acá: `listar_movimientos` no devuelve los anulados.
 */
import { createLazyFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Wallet } from "lucide-react";
import { toast } from "sonner";

import {
  adminApi,
  TIPOS_MOVIMIENTO,
  type CobroMensual,
  type Cuenta,
  type Movimiento,
} from "@/lib/admin/api";
import { MoverPlataForm } from "@/components/admin/contabilidad/MoverPlataForm";
import { CorregirSaldoForm } from "@/components/admin/contabilidad/CorregirSaldoForm";
import { CuentaSelect, Field } from "@/components/admin/contabilidad/fields";
import { useConfirm } from "@/components/admin/useConfirm";
import { AdminPage } from "@/components/admin/AdminPage";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { QueryState } from "@/components/admin/QueryState";
import { TableSkeleton } from "@/components/admin/skeletons";
import { EmptyState } from "@/design-system/composites/EmptyState";
import { formatMoney, formatFechaDisplay } from "@/lib/format";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { Badge } from "@/design-system/ui/badge";
import { Button } from "@/design-system/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/design-system/ui/dialog";
import { Input } from "@/design-system/ui/input";
import { TipoMovimientoBadge, TIPO_MOVIMIENTO_META } from "@/components/admin/badges";
import { cn } from "@/lib/utils";

export const Route = createLazyFileRoute("/admin/contabilidad/movimientos")({
  component: MovimientosPage,
});

function descMovimiento(m: Movimiento): string {
  const o = m.cuenta_origen_nombre ?? "—";
  const d = m.cuenta_destino_nombre ?? "—";
  switch (m.tipo) {
    case "gasto":
      return `${m.categoria_nombre ?? "Sin categoría"} · sale de ${o}`;
    case "transferencia":
      return `${o} → ${d}`;
    case "retiro":
      return `Retiro de ${o}`;
    case "aporte":
      return `Aporte a ${d}`;
    default: {
      // Cambio de divisa: cada pata es un `ajuste` con una sola cuenta y
      // `cotizacion` seteada (ver mover-plata.ts / commands/movimientos.py).
      if (m.cotizacion != null) {
        const cta = o !== "—" ? o : d;
        return `Cambio de divisa · ${o !== "—" ? "sale de" : "entra a"} ${cta} (cotización ${m.cotizacion})`;
      }
      return [o !== "—" ? o : null, d !== "—" ? d : null].filter(Boolean).join(" → ") || "Ajuste";
    }
  }
}

type Fila =
  | { kind: "mov"; fecha: string; mov: Movimiento }
  | { kind: "cobro"; fecha: string; cobro: CobroMensual };

// Fecha del último día del mes (para ordenar la línea de cobro al cierre del mes).
function finDeMes(mes: string): string {
  const [y, m] = mes.split("-").map(Number);
  const dia = new Date(y, m, 0).getDate();
  return `${mes}-${String(dia).padStart(2, "0")}`;
}

function mesLabel(mes: string): string {
  return new Date(`${mes}-01T00:00:00`).toLocaleDateString("es-AR", {
    month: "long",
    year: "numeric",
  });
}

// Dirección de la plata (guía visual estilo debe/haber): entra (haber, verde +),
// sale (debe, rojo −) o interno (transferencia/ajuste entre dos cajas, neutro).
type Direccion = "in" | "out" | "neutral";
function direccionMov(m: Movimiento): Direccion {
  const origen = !!m.cuenta_origen_id;
  const destino = !!m.cuenta_destino_id;
  if (origen && !destino) return "out";
  if (destino && !origen) return "in";
  return "neutral";
}
function montoClass(dir: Direccion): string {
  return dir === "in" ? "text-verde-ink" : dir === "out" ? "text-destructive" : "text-ink";
}
function montoSigno(dir: Direccion): string {
  return dir === "in" ? "+ " : dir === "out" ? "− " : "";
}

function MovimientosPage() {
  useDocumentTitle("Movimientos · Finanzas");
  const qc = useQueryClient();
  const [tipoFiltro, setTipoFiltro] = useState<string>("");
  const [beneficiarioFiltro, setBeneficiarioFiltro] = useState<string>("");
  const [cuentaFiltro, setCuentaFiltro] = useState<string>("");
  // Mes del cobro expandido (muestra los pagos individuales inline). Uno a la vez.
  const [expandedMes, setExpandedMes] = useState<string | null>(null);

  const invalidar = () => qc.invalidateQueries({ queryKey: ["admin", "contabilidad"] });

  const cuentasQ = useQuery({
    queryKey: ["admin", "contabilidad", "cuentas-list"],
    queryFn: () => adminApi.listCuentas(),
  });
  const cuentas: Cuenta[] = cuentasQ.data?.cuentas ?? [];

  const movsQ = useQuery({
    queryKey: [
      "admin",
      "contabilidad",
      "movimientos",
      { tipo: tipoFiltro, ben: beneficiarioFiltro, cuenta: cuentaFiltro },
    ],
    queryFn: () =>
      adminApi.listMovimientos({
        tipo: tipoFiltro || undefined,
        beneficiario: beneficiarioFiltro || undefined,
        cuenta_id: cuentaFiltro ? Number(cuentaFiltro) : undefined,
      }),
  });

  // Vista unificada: movimientos manuales + cobros de pedidos (agregados por mes,
  // read-only), ordenados por fecha.
  const filas: Fila[] = [];
  if (movsQ.data) {
    for (const m of movsQ.data.movimientos) filas.push({ kind: "mov", fecha: m.fecha, mov: m });
    for (const c of movsQ.data.cobros ?? [])
      filas.push({ kind: "cobro", fecha: finDeMes(c.mes), cobro: c });
    filas.sort((a, b) => b.fecha.localeCompare(a.fecha));
  }

  const columns: Column<Fila>[] = [
    {
      header: "Fecha",
      cell: (f) =>
        f.kind === "mov" ? (
          formatFechaDisplay(f.mov.fecha)
        ) : (
          <span className="capitalize">{mesLabel(f.cobro.mes)}</span>
        ),
      className: "whitespace-nowrap text-muted-foreground",
    },
    {
      header: "Tipo",
      cell: (f) =>
        f.kind === "mov" ? (
          <TipoMovimientoBadge tipo={f.mov.tipo} />
        ) : (
          <Badge variant="secondary">Cobros</Badge>
        ),
    },
    {
      header: "Detalle",
      cell: (f) =>
        f.kind === "mov" ? (
          <>
            <span className={cn(f.mov.anulado && "line-through")}>{descMovimiento(f.mov)}</span>
            {f.mov.beneficiario && (
              <div>
                <button
                  type="button"
                  onClick={() => setBeneficiarioFiltro(f.mov.beneficiario!)}
                  className="text-xs text-ink underline decoration-amber/60 underline-offset-2 hover:decoration-amber"
                  title="Ver el historial de este beneficiario"
                >
                  {f.mov.beneficiario}
                </button>
              </div>
            )}
            {f.mov.nota && <div className="text-xs text-muted-foreground">{f.mov.nota}</div>}
            {f.mov.anulado && f.mov.anulado_motivo && (
              <div className="text-xs text-destructive">Anulado: {f.mov.anulado_motivo}</div>
            )}
            {f.mov.comprobante_url && (
              <a
                href={f.mov.comprobante_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-ink underline decoration-amber/60 underline-offset-2 hover:decoration-amber"
              >
                Ver comprobante
              </a>
            )}
          </>
        ) : (
          <>
            <span className="capitalize text-ink">Cobro alquileres · {mesLabel(f.cobro.mes)}</span>
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <ChevronDown
                className={cn(
                  "h-3.5 w-3.5 transition-transform",
                  expandedMes === f.cobro.mes && "rotate-180",
                )}
              />
              {f.cobro.cantidad} pago(s) — {expandedMes === f.cobro.mes ? "ocultar" : "ver detalle"}
            </div>
          </>
        ),
    },
    {
      header: "Monto",
      cell: (f) =>
        f.kind === "mov" ? (
          <span className={montoClass(direccionMov(f.mov))}>
            {montoSigno(direccionMov(f.mov))}
            {formatMoney(f.mov.monto, f.mov.moneda)}
          </span>
        ) : (
          <span className="text-verde-ink">+ {formatMoney(f.cobro.monto, "ARS")}</span>
        ),
      align: "right",
      className: "font-mono tabular-nums",
    },
    {
      header: "Acciones",
      cell: (f) =>
        f.kind === "mov" ? (
          <AccionesMovimiento mov={f.mov} onChanged={invalidar} />
        ) : (
          <span className="text-xs text-muted-foreground">automático</span>
        ),
      align: "right",
    },
  ];

  return (
    <AdminPage
      title="Movimientos"
      maxW="list"
      description="Toda la plata de las cajas: los cobros de pedidos (que entran solos, una línea por mes) más los gastos, transferencias, retiros y aportes."
      backTo={{ to: "/admin/contabilidad", label: "Finanzas" }}
    >
      <div className="space-y-6">
        {/* Una sola entrada. Antes había que elegir modo (movimiento / cambio de
            divisa) y después uno de 5 tipos contables — 6 decisiones de vocabulario
            antes de cargar un peso. `MoverPlataForm` pregunta qué pasó y deriva el
            tipo solo (`lib/admin/mover-plata.ts`). El `ajuste` queda aparte y
            colapsado, con nota obligatoria: es la puerta de "el modelo no captura
            la realidad", no una opción más. */}
        <MoverPlataForm onCreated={invalidar} />
        <CorregirSaldoForm onCreated={invalidar} />

        {/* Filtro por tipo + cuenta */}
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-wrap gap-1">
            {[
              ["", "Todos"],
              ["cobro", "Cobros"],
              ...TIPOS_MOVIMIENTO.map(
                (t) => [t, TIPO_MOVIMIENTO_META[t].label] as [string, string],
              ),
            ].map(([val, lbl]) => (
              <button
                key={val}
                type="button"
                onClick={() => setTipoFiltro(val)}
                className={cn(
                  "rounded-md border px-2.5 py-1.5 text-xs font-medium transition",
                  tipoFiltro === val
                    ? "border-ink bg-ink text-background"
                    : "border-muted-foreground/30 text-muted-foreground hover:border-ink hover:text-ink",
                )}
              >
                {lbl}
              </button>
            ))}
          </div>
          <Field label="Cuenta">
            <CuentaSelect
              cuentas={cuentas}
              value={cuentaFiltro}
              onChange={setCuentaFiltro}
              placeholder="Todas las cuentas"
            />
          </Field>
        </div>

        {beneficiarioFiltro && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Beneficiario:</span>
            <span className="rounded-md bg-ink px-2 py-0.5 text-xs text-background">
              {beneficiarioFiltro}
            </span>
            <button
              type="button"
              onClick={() => setBeneficiarioFiltro("")}
              className="text-xs text-muted-foreground hover:text-ink underline"
            >
              quitar
            </button>
          </div>
        )}

        <QueryState
          query={movsQ}
          isEmpty={(d) => d.movimientos.length === 0 && (d.cobros ?? []).length === 0}
          skeleton={<TableSkeleton rows={6} cols={5} />}
          empty={
            <EmptyState
              icon={<Wallet className="h-6 w-6" />}
              title="No hay movimientos"
              sub="Todavía no hay movimientos para este filtro."
            />
          }
        >
          {() => (
            <AdminTable
              columns={columns}
              rows={filas}
              getRowKey={(f) => (f.kind === "mov" ? `m${f.mov.id}` : `c${f.cobro.mes}`)}
              rowClassName={(f) =>
                f.kind === "mov"
                  ? cn("cursor-default", f.mov.anulado && "opacity-50")
                  : "bg-muted/10"
              }
              onRowClick={(f) => {
                if (f.kind === "cobro")
                  setExpandedMes((m) => (m === f.cobro.mes ? null : f.cobro.mes));
              }}
              isExpanded={(f) => f.kind === "cobro" && expandedMes === f.cobro.mes}
              renderExpanded={(f) =>
                f.kind === "cobro" ? <CobroDetalle mes={f.cobro.mes} /> : null
              }
            />
          )}
        </QueryState>
      </div>
    </AdminPage>
  );
}

/** Detalle desplegable de un cobro mensual: los pagos individuales de ese mes,
 *  traídos del ledger único de pagos (read-only, misma fuente que Cobros). */
function CobroDetalle({ mes }: { mes: string }) {
  const desde = `${mes}-01`;
  const hasta = finDeMes(mes);
  const q = useQuery({
    queryKey: ["admin", "pagos", "mes", mes],
    queryFn: () => adminApi.listPagosLog({ desde, hasta }),
  });

  if (q.isLoading) {
    return <div className="px-4 py-3 text-xs text-muted-foreground">Cargando pagos…</div>;
  }
  if (q.isError) {
    return (
      <div className="px-4 py-3 text-xs text-destructive">No se pudieron cargar los pagos.</div>
    );
  }
  const pagos = q.data?.pagos ?? [];
  if (pagos.length === 0) {
    return <div className="px-4 py-3 text-xs text-muted-foreground">Sin pagos en el mes.</div>;
  }

  return (
    <div className="space-y-1.5 px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="t-eyebrow">Pagos del mes</div>
        <Link
          to="/admin/pagos"
          className="text-xs text-ink underline decoration-amber/60 underline-offset-2 hover:decoration-amber"
        >
          ver ledger completo →
        </Link>
      </div>
      <div className="divide-y hairline card-elevated">
        {pagos.map((p) => (
          <div key={p.id} className="flex items-center gap-3 px-3 py-1.5 text-xs">
            <span className="whitespace-nowrap text-muted-foreground">
              {formatFechaDisplay(p.fecha)}
            </span>
            <Link
              to="/admin/pedidos/$id"
              params={{ id: String(p.pedido_id) }}
              className="whitespace-nowrap font-mono text-ink underline decoration-amber/60 underline-offset-2 hover:decoration-amber"
            >
              #{p.numero_pedido ?? p.pedido_id}
            </Link>
            <span className="flex-1 truncate text-muted-foreground">{p.cliente_nombre ?? "—"}</span>
            <span className="whitespace-nowrap capitalize text-muted-foreground">
              {p.metodo ?? "—"}
            </span>
            <span className="whitespace-nowrap font-mono tabular-nums text-ink">
              {formatMoney(p.monto, "ARS")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Editar / Borrar de una fila. Los cobros de alquiler no pasan por acá (son
 *  derivados, read-only). */
function AccionesMovimiento({ mov, onChanged }: { mov: Movimiento; onChanged: () => void }) {
  const confirm = useConfirm();
  const [editando, setEditando] = useState(false);

  const borrar = useMutation({
    // Sin motivo: son los asientos propios del dueño y pedir una justificación
    // escrita para corregir un tipeo era fricción sin contraparte (2026-08).
    mutationFn: () => adminApi.anularMovimiento(mov.id),
    onSuccess: () => {
      toast.success("Movimiento borrado");
      onChanged();
    },
    onError: (e) => toast.error("No se pudo borrar", { description: (e as Error).message }),
  });

  if (mov.anulado) return null;

  return (
    <div className="flex items-center justify-end gap-2">
      <button
        type="button"
        onClick={() => setEditando(true)}
        className="text-xs text-ink underline decoration-amber/60 underline-offset-2 hover:decoration-amber"
      >
        Editar
      </button>
      <button
        type="button"
        onClick={async () => {
          const ok = await confirm({
            title: "¿Borrar este movimiento?",
            description: `${descMovimiento(mov)} · ${formatMoney(mov.monto, mov.moneda)}. Deja de contar para los saldos.`,
            confirmLabel: "Borrar",
            danger: true,
          });
          if (ok) borrar.mutate();
        }}
        disabled={borrar.isPending}
        className="text-xs text-muted-foreground hover:text-destructive underline"
      >
        Borrar
      </button>
      {editando && (
        <EditarMovimientoDialog
          mov={mov}
          onClose={() => setEditando(false)}
          onSaved={() => {
            setEditando(false);
            onChanged();
          }}
        />
      )}
    </div>
  );
}

/** Edición de un movimiento ya cargado. El `tipo` NO se puede cambiar (pasar de
 *  gasto a transferencia es otro movimiento: se borra y se rehace) — el backend
 *  tampoco lo acepta (`_CAMPOS_EDITABLES`). El endpoint ya existía desde el
 *  arranque del módulo; lo que faltaba era esta pantalla. */
function EditarMovimientoDialog({
  mov,
  onClose,
  onSaved,
}: {
  mov: Movimiento;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [monto, setMonto] = useState(String(mov.monto));
  const [fecha, setFecha] = useState((mov.fecha ?? "").slice(0, 10));
  const [origen, setOrigen] = useState(mov.cuenta_origen_id ? String(mov.cuenta_origen_id) : "");
  const [destino, setDestino] = useState(
    mov.cuenta_destino_id ? String(mov.cuenta_destino_id) : "",
  );
  const [categoria, setCategoria] = useState(mov.categoria_id ? String(mov.categoria_id) : "");
  const [metodo, setMetodo] = useState(mov.metodo ?? "");
  const [nota, setNota] = useState(mov.nota ?? "");
  const [beneficiario, setBeneficiario] = useState(mov.beneficiario ?? "");

  const cuentasQ = useQuery({
    queryKey: ["admin", "contabilidad", "cuentas-list"],
    queryFn: () => adminApi.listCuentas(),
  });
  const catsQ = useQuery({
    queryKey: ["admin", "contabilidad", "categorias"],
    queryFn: () => adminApi.listGastoCategorias(),
  });
  const cuentas = cuentasQ.data?.cuentas ?? [];

  const guardar = useMutation({
    mutationFn: () =>
      adminApi.updateMovimiento(mov.id, {
        monto: Number(monto) || 0,
        // `fecha` se OMITE si el campo quedó vacío, no se manda `null`: la
        // columna es NOT NULL, así que `SET fecha = NULL` reventaba con un 500
        // (`map_pg_errors` no cubre ese caso) — vaciar el input con el mouse y
        // guardar alcanzaba para dispararlo. El backend trata un campo ausente
        // como "no tocar" (`_CAMPOS_EDITABLES` + `exclude_unset`), que además
        // es lo que uno espera al no haber elegido una fecha nueva.
        ...(fecha ? { fecha } : {}),
        cuenta_origen_id: origen ? Number(origen) : null,
        cuenta_destino_id: destino ? Number(destino) : null,
        categoria_id: categoria ? Number(categoria) : null,
        metodo: metodo || null,
        nota: nota || null,
        beneficiario: beneficiario || null,
      }),
    onSuccess: () => {
      toast.success("Movimiento actualizado");
      onSaved();
    },
    onError: (e) => toast.error("No se pudo guardar", { description: (e as Error).message }),
  });

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            Editar movimiento · <span className="capitalize">{mov.tipo}</span>
          </DialogTitle>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!(Number(monto) > 0)) return toast.error("Poné un monto mayor a cero.");
            guardar.mutate();
          }}
          className="space-y-3"
        >
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Monto">
              <Input
                type="number"
                step="1"
                min="1"
                value={monto}
                onChange={(e) => setMonto(e.target.value)}
                className="w-32 text-right tabular-nums"
              />
            </Field>
            <Field label="Fecha">
              <Input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />
            </Field>
            {mov.cuenta_origen_id != null && (
              <Field label="Sale de">
                <CuentaSelect cuentas={cuentas} value={origen} onChange={setOrigen} />
              </Field>
            )}
            {mov.cuenta_destino_id != null && (
              <Field label="Entra a">
                <CuentaSelect cuentas={cuentas} value={destino} onChange={setDestino} />
              </Field>
            )}
          </div>

          <div className="flex flex-wrap items-end gap-3">
            {mov.tipo === "gasto" && (
              <Field label="¿De qué es?">
                <select
                  value={categoria}
                  onChange={(e) => setCategoria(e.target.value)}
                  className="h-9 rounded-md border hairline bg-surface-elevated px-2 text-sm"
                >
                  <option value="">Elegir…</option>
                  {(catsQ.data?.categorias ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.nombre}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Field label="Método">
              <select
                value={metodo}
                onChange={(e) => setMetodo(e.target.value)}
                className="h-9 rounded-md border hairline bg-surface-elevated px-2 text-sm capitalize"
              >
                <option value="">—</option>
                <option value="transferencia">transferencia</option>
                <option value="efectivo">efectivo</option>
              </select>
            </Field>
            {mov.tipo === "gasto" && (
              <Field label="Beneficiario">
                <Input
                  value={beneficiario}
                  onChange={(e) => setBeneficiario(e.target.value)}
                  className="w-48"
                />
              </Field>
            )}
          </div>

          <Field label="Nota">
            <Input value={nota} onChange={(e) => setNota(e.target.value)} className="w-full" />
          </Field>

          {/* Un cambio de divisa son DOS `ajuste` atados por `movimiento_par_id`
              (uno por caja). Editar una sola pata deja pesos y dólares que no se
              corresponden y la cotización guardada pasa a ser mentira — el
              backend no los sincroniza. Avisar es lo barato y honesto; ligarlos
              de verdad es otra decisión (hallazgo del supervisor). */}
          {mov.movimiento_par_id != null && (
            <p className="text-xs text-muted-foreground">
              Ojo: esto es una de las dos patas de un cambio de divisa. Si le cambiás el monto, la
              otra pata no se ajusta sola y la cotización guardada deja de cerrar.
            </p>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancelar
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={guardar.isPending}
              loading={guardar.isPending}
            >
              Guardar
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
