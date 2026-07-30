/**
 * contabilidad.cuentas.lazy.tsx — Cuentas/cajas con saldo (#809).
 *
 * Dos secciones, porque son dos cosas distintas:
 *  - **Socios · Cuenta corriente** (Pablo/Tincho): NO son cajas de plata, son el
 *    saldo de la rendición acumulada — DEUDOR (le debe a Rental) / ACREEDOR (Rental
 *    le debe). Sale de: arranque + cobró − su parte ± rendiciones.
 *  - **Cajas · Plata del negocio** (Efectivo/Banco/Fondo Rental/Dólares…): plata
 *    real; suben/bajan con movimientos. Se pueden crear, editar y dar de baja.
 */
import { createLazyFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { adminApi, type CuentaSaldo, type TipoCuenta } from "@/lib/admin/api";
import { AdminPage } from "@/components/admin/AdminPage";
import { TableSkeleton } from "@/components/admin/skeletons";
import { ErrorState } from "@/components/admin/ErrorState";
import { useConfirm } from "@/components/admin/useConfirm";
import { formatMoney } from "@/lib/format";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { Badge } from "@/design-system/ui/badge";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Pill, type PillTone } from "@/design-system/ui/Pill";
import { cn } from "@/lib/utils";

// El socio se crea desde el sistema (seed); acá solo cajas/cuentas genéricas.
const TIPOS_CREABLES: TipoCuenta[] = ["caja", "banco", "fondo"];

export const Route = createLazyFileRoute("/admin/contabilidad/cuentas")({
  component: CuentasPage,
});

function CuentasPage() {
  useDocumentTitle("Cuentas · Finanzas");
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ["admin", "contabilidad", "saldos"],
    queryFn: () => adminApi.getSaldos(),
  });

  const invalidar = () => qc.invalidateQueries({ queryKey: ["admin", "contabilidad"] });

  const socios = q.data?.socios ?? [];
  const cajas = q.data?.cajas ?? [];

  return (
    <AdminPage
      title="Cuentas"
      maxW="detail"
      description="La cuenta corriente de cada socio (quién le debe a quién) y las cajas con la plata real del negocio."
      backTo={{ to: "/admin/contabilidad", label: "Tablero" }}
    >
      <div className="space-y-8">
        {q.isLoading && <TableSkeleton rows={5} cols={5} />}
        {q.isError && <ErrorState error={q.error} onRetry={q.refetch} />}

        {/* Socios · Cuenta corriente */}
        {socios.length > 0 && (
          <section className="space-y-3">
            <div className="t-eyebrow">Socios · Cuenta corriente</div>
            <div className="grid gap-3 sm:grid-cols-2">
              {socios.map((s) => (
                <SocioCard key={s.id} socio={s} cajas={cajas} onChanged={invalidar} />
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              El <strong>arranque</strong> es lo que cobró antes del sistema. Se va saldando con{" "}
              <strong>su parte</strong> de lo que se alquila: cuando llega a cero están a mano, y si
              se da vuelta, Rental le debe a él.
            </p>
          </section>
        )}

        {/* Cajas · Plata del negocio */}
        {q.data && (
          <section className="space-y-3">
            <div className="t-eyebrow">Cajas · Plata del negocio</div>
            <div className="overflow-x-auto rounded-lg border hairline">
              {/* eslint-disable-next-line no-restricted-syntax -- tabla de edición inline (CajaRow con estado propio + totales en tfoot), no es tabla de display; AdminTable no aplica */}
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b hairline text-left text-xs uppercase tracking-wider text-muted-foreground">
                    <th className="px-3 py-2 font-medium">Caja</th>
                    <th className="px-3 py-2 font-medium">Tipo</th>
                    <th className="px-3 py-2 font-medium text-right">Saldo inicial</th>
                    <th className="px-3 py-2 font-medium text-right">Saldo actual</th>
                    <th className="px-3 py-2 font-medium text-right">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {cajas.map((c) => (
                    <CajaRow key={c.id} cuenta={c} onChanged={invalidar} />
                  ))}
                </tbody>
                <tfoot>
                  {Object.entries(q.data.totales)
                    .sort(([a], [b]) => (a === "ARS" ? -1 : b === "ARS" ? 1 : a.localeCompare(b)))
                    .map(([moneda, total]) => (
                      <tr key={moneda} className="border-t hairline">
                        <td className="px-3 py-2 font-medium" colSpan={3}>
                          Total disponible {moneda !== "ARS" ? `(${moneda})` : ""}
                        </td>
                        <td className="px-3 py-2 text-right font-mono font-semibold tabular-nums">
                          {formatMoney(total, moneda)}
                        </td>
                        <td />
                      </tr>
                    ))}
                </tfoot>
              </table>
            </div>
          </section>
        )}

        <NuevaCuentaForm onCreated={invalidar} />
      </div>
    </AdminPage>
  );
}

function SocioCard({
  socio,
  cajas,
  onChanged,
}: {
  socio: CuentaSaldo;
  cajas: CuentaSaldo[];
  onChanged: () => void;
}) {
  const [editando, setEditando] = useState(false);
  const [arranque, setArranque] = useState(String(socio.saldo_inicial));

  // Cajas de la misma moneda que el socio (la transferencia no mezcla monedas).
  const cajasMov = cajas.filter((c) => c.moneda === socio.moneda);
  const [movAbierto, setMovAbierto] = useState(false);
  const [dir, setDir] = useState<"pago" | "cargo">("pago");
  const [montoMov, setMontoMov] = useState("");
  const [cajaId, setCajaId] = useState<number | "">("");
  const [notaMov, setNotaMov] = useState("");

  const cerrarMov = () => {
    setMovAbierto(false);
    setMontoMov("");
    setCajaId("");
    setNotaMov("");
    setDir("pago");
  };

  const registrarMov = useMutation({
    mutationFn: () => {
      const monto = Number(montoMov) || 0;
      const caja = Number(cajaId);
      // pago/rindió: el socio entrega → sale de su cuenta, entra a la caja (baja deuda).
      // cargo: Rental puso por él → sale de la caja, entra a su cuenta (sube deuda).
      const origen = dir === "pago" ? socio.id : caja;
      const destino = dir === "pago" ? caja : socio.id;
      return adminApi.createMovimiento({
        tipo: "transferencia",
        monto,
        cuenta_origen_id: origen,
        cuenta_destino_id: destino,
        nota: notaMov.trim() || null,
      });
    },
    onSuccess: () => {
      cerrarMov();
      toast.success(dir === "pago" ? "Pago registrado" : "Cargo registrado");
      onChanged();
    },
    onError: (e) => toast.error("No se pudo registrar", { description: (e as Error).message }),
  });

  const guardar = useMutation({
    mutationFn: () => adminApi.updateCuenta(socio.id, { saldo_inicial: Number(arranque) || 0 }),
    onSuccess: () => {
      setEditando(false);
      toast.success("Arranque actualizado");
      onChanged();
    },
    onError: (e) => toast.error("No se pudo actualizar", { description: (e as Error).message }),
  });

  const abs = Math.abs(socio.saldo);
  const frase =
    socio.estado === "deudor"
      ? `${socio.nombre} le debe a Rental`
      : socio.estado === "acreedor"
        ? `Rental le debe a ${socio.nombre}`
        : "A mano";
  const color =
    socio.estado === "deudor"
      ? "text-destructive"
      : socio.estado === "acreedor"
        ? "text-verde-ink"
        : "text-ink";
  const tag =
    socio.estado === "deudor" ? "Deudor" : socio.estado === "acreedor" ? "Acreedor" : "Saldado";
  const tagTone: PillTone =
    socio.estado === "deudor" ? "danger" : socio.estado === "acreedor" ? "success" : "neutral";

  return (
    <div className="rounded-lg border hairline p-4 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="font-medium text-ink">{socio.nombre}</div>
        <Pill tone={tagTone} className="font-mono uppercase tracking-wider">
          {tag}
        </Pill>
      </div>
      <div className={cn("font-mono text-2xl font-semibold tabular-nums", color)}>
        {formatMoney(abs, socio.moneda)}
      </div>
      <div className="text-sm text-muted-foreground">{frase}</div>
      <div className="font-mono text-xs text-muted-foreground tabular-nums">
        arranque {formatMoney(socio.saldo_inicial, socio.moneda)} · cobró{" "}
        {formatMoney(socio.ingresos_alquiler, socio.moneda)} · su parte{" "}
        {formatMoney(socio.su_parte, socio.moneda)}
      </div>
      {editando ? (
        <div className="flex items-center gap-1 pt-1">
          <Input
            type="number"
            value={arranque}
            onChange={(e) => setArranque(e.target.value)}
            className="w-32 text-right tabular-nums"
            aria-label="Arranque"
          />
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={() => guardar.mutate()}
            disabled={guardar.isPending}
          >
            Guardar
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setEditando(false);
              setArranque(String(socio.saldo_inicial));
            }}
          >
            Cancelar
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setMovAbierto((v) => !v)}
            className="text-xs text-ink underline hover:text-ink"
          >
            Registrar movimiento
          </button>
          <button
            type="button"
            onClick={() => setEditando(true)}
            className="text-xs text-muted-foreground underline hover:text-ink"
            title="Editar el arranque (lo que cobró antes del sistema)"
          >
            Editar arranque
          </button>
        </div>
      )}

      {movAbierto && (
        <div className="pt-2 mt-1 border-t hairline space-y-2">
          <div className="flex gap-1">
            {(["pago", "cargo"] as const).map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDir(d)}
                className={cn(
                  "flex-1 rounded-md border px-2 py-1.5 text-xs font-medium transition",
                  dir === d
                    ? "border-ink bg-ink text-background"
                    : "border-muted-foreground/30 text-muted-foreground hover:border-ink",
                )}
              >
                {d === "pago" ? "Me pagó / rindió" : "Le cargué"}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            {dir === "pago"
              ? `${socio.nombre} entrega plata → baja su deuda y entra a la caja.`
              : `Rental puso plata por ${socio.nombre} (ej. le compró algo) → sube su deuda y sale de la caja.`}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              type="number"
              value={montoMov}
              onChange={(e) => setMontoMov(e.target.value)}
              placeholder="Monto"
              className="w-28 text-right tabular-nums"
            />
            <select
              value={cajaId}
              onChange={(e) => setCajaId(e.target.value ? Number(e.target.value) : "")}
              className="h-8 rounded-md border hairline bg-surface-elevated px-2 text-sm"
            >
              <option value="">{dir === "pago" ? "¿A qué caja?" : "¿De qué caja?"}</option>
              {cajasMov.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nombre}
                </option>
              ))}
            </select>
          </div>
          <Input
            value={notaMov}
            onChange={(e) => setNotaMov(e.target.value)}
            placeholder="Nota (ej. adaptador de lente)"
          />
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={() => registrarMov.mutate()}
              disabled={registrarMov.isPending || !(Number(montoMov) > 0) || !cajaId}
            >
              Registrar
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={cerrarMov}>
              Cancelar
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function CajaRow({ cuenta, onChanged }: { cuenta: CuentaSaldo; onChanged: () => void }) {
  const confirm = useConfirm();
  const [editando, setEditando] = useState(false);
  const [nombre, setNombre] = useState(cuenta.nombre);
  const [valor, setValor] = useState(String(cuenta.saldo_inicial));

  const cerrar = () => {
    setEditando(false);
    setNombre(cuenta.nombre);
    setValor(String(cuenta.saldo_inicial));
  };

  const guardar = useMutation({
    mutationFn: () =>
      adminApi.updateCuenta(cuenta.id, {
        nombre: nombre.trim(),
        saldo_inicial: Number(valor) || 0,
      }),
    onSuccess: () => {
      setEditando(false);
      toast.success("Cuenta actualizada");
      onChanged();
    },
    onError: (e) => toast.error("No se pudo actualizar", { description: (e as Error).message }),
  });

  const baja = useMutation({
    mutationFn: () => adminApi.deactivateCuenta(cuenta.id),
    onSuccess: () => {
      toast.success("Cuenta dada de baja");
      onChanged();
    },
    onError: (e) => toast.error("No se pudo dar de baja", { description: (e as Error).message }),
  });

  // El Fondo Rental representa al cobrador Rental: recibe cobros, no se da de baja.
  const esCobrador = Boolean(cuenta.socio);

  return (
    <tr className="border-b hairline last:border-0">
      <td className="px-3 py-2 font-medium text-ink">
        {editando ? (
          <Input value={nombre} onChange={(e) => setNombre(e.target.value)} className="w-44" />
        ) : (
          cuenta.nombre
        )}
      </td>
      <td className="px-3 py-2">
        <Badge variant="secondary" className="capitalize">
          {cuenta.tipo}
        </Badge>
      </td>
      <td className="px-3 py-2 text-right">
        {editando ? (
          <Input
            type="number"
            value={valor}
            onChange={(e) => setValor(e.target.value)}
            className="w-28 text-right tabular-nums"
          />
        ) : (
          <span className="font-mono tabular-nums">
            {formatMoney(cuenta.saldo_inicial, cuenta.moneda)}
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-right font-mono font-semibold tabular-nums">
        {formatMoney(cuenta.saldo, cuenta.moneda)}
      </td>
      <td className="px-3 py-2 text-right">
        {editando ? (
          <div className="flex items-center justify-end gap-1">
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={() => guardar.mutate()}
              disabled={guardar.isPending || !nombre.trim()}
            >
              Guardar
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={cerrar}>
              Cancelar
            </Button>
          </div>
        ) : (
          <div className="flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={() => setEditando(true)}
              className="text-xs text-muted-foreground underline hover:text-ink"
              title="Editar nombre y saldo inicial"
            >
              Editar
            </button>
            <button
              type="button"
              onClick={async () => {
                if (
                  await confirm({
                    title: `¿Dar de baja "${cuenta.nombre}"?`,
                    description: "Solo se puede si su saldo es cero.",
                    danger: true,
                    confirmLabel: "Dar de baja",
                  })
                )
                  baja.mutate();
              }}
              disabled={baja.isPending || esCobrador}
              className={cn(
                "text-xs underline",
                esCobrador
                  ? "text-muted-foreground/40 cursor-not-allowed no-underline"
                  : "text-muted-foreground hover:text-destructive",
              )}
              title={esCobrador ? "El Fondo Rental no se da de baja" : "Dar de baja"}
            >
              Baja
            </button>
          </div>
        )}
      </td>
    </tr>
  );
}

function NuevaCuentaForm({ onCreated }: { onCreated: () => void }) {
  const [nombre, setNombre] = useState("");
  const [tipo, setTipo] = useState<TipoCuenta>("caja");
  const [moneda, setMoneda] = useState("ARS");
  const [saldoInicial, setSaldoInicial] = useState("0");

  const crear = useMutation({
    mutationFn: () =>
      adminApi.createCuenta({
        nombre: nombre.trim(),
        tipo,
        moneda,
        saldo_inicial: Number(saldoInicial) || 0,
      }),
    onSuccess: () => {
      setNombre("");
      setSaldoInicial("0");
      setTipo("caja");
      setMoneda("ARS");
      toast.success("Cuenta creada");
      onCreated();
    },
    onError: (e) =>
      toast.error("No se pudo crear la cuenta", { description: (e as Error).message }),
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!nombre.trim()) return;
        crear.mutate();
      }}
      className="rounded-lg border hairline p-4 space-y-3"
    >
      <div className="t-eyebrow">Nueva caja</div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1">
          <span className="block t-eyebrow">Nombre</span>
          <Input
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            placeholder="Ej. Mercado Pago"
            className="w-48"
          />
        </label>
        <label className="space-y-1">
          <span className="block t-eyebrow">Tipo</span>
          <select
            value={tipo}
            onChange={(e) => setTipo(e.target.value as TipoCuenta)}
            className="h-9 rounded-md border hairline bg-surface-elevated px-2 text-sm capitalize"
          >
            {TIPOS_CREABLES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="block t-eyebrow">Moneda</span>
          <select
            value={moneda}
            onChange={(e) => setMoneda(e.target.value)}
            className="h-9 rounded-md border hairline bg-surface-elevated px-2 text-sm"
          >
            <option value="ARS">Pesos (ARS)</option>
            <option value="USD">Dólares (USD)</option>
          </select>
        </label>
        <label className="space-y-1">
          <span className="block t-eyebrow">Saldo inicial</span>
          <Input
            type="number"
            value={saldoInicial}
            onChange={(e) => setSaldoInicial(e.target.value)}
            className="w-32 text-right tabular-nums"
          />
        </label>
        <Button type="submit" variant="primary" disabled={crear.isPending || !nombre.trim()}>
          {crear.isPending ? "Creando…" : "Crear"}
        </Button>
      </div>
    </form>
  );
}
