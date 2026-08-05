/**
 * MovimientoAcciones — Editar / Borrar de una fila del libro de movimientos,
 * con su diálogo de edición.
 *
 * Vive acá (y no en la página de Movimientos, donde nació) porque lo usan DOS
 * superficies: el libro completo (`/admin/contabilidad/movimientos`) y la Caja
 * Estudio (`/admin/contabilidad/estudio`), que antes era solo lectura y
 * mandaba al libro para corregir un asiento. Sigue habiendo **una sola forma
 * de escribir plata** —este componente, sobre los endpoints del motor— que es
 * lo que la decisión original protegía; lo que cambia es dónde se la ofrece.
 *
 * Los cobros de alquiler NO pasan por acá: son derivados de `alquiler_pagos`,
 * read-only (se anulan desde el pedido).
 */
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { adminApi, type Movimiento } from "@/lib/admin/api";
import { useConfirm } from "@/components/admin/useConfirm";
import { CuentaSelect, Field } from "@/components/admin/contabilidad/fields";
import { formatMoney } from "@/lib/format";
import { descMovimiento } from "@/lib/admin/movimiento-texto";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/design-system/ui/dialog";

/** Editar / Borrar de una fila. Los cobros de alquiler no pasan por acá (son
 *  derivados, read-only). */
export function AccionesMovimiento({ mov, onChanged }: { mov: Movimiento; onChanged: () => void }) {
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
