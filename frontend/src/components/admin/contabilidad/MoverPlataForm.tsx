/**
 * MoverPlataForm.tsx — la ÚNICA entrada para mover plata entre cuentas.
 *
 * Reemplaza los 5 botones de tipo (`gasto`/`transferencia`/`retiro`/`aporte`/
 * `ajuste`) + el toggle aparte de "Cambio de divisa": 6 decisiones sobre
 * vocabulario contable antes de poder cargar un peso. Acá se pregunta lo que el
 * dueño ya sabe —qué pasó, de dónde salió, a dónde fue— y el `tipo` lo deriva
 * `lib/admin/mover-plata.ts` (puro, con su tabla de verdad testeada).
 *
 * Este archivo es SOLO layout. El estado (los 13 campos, las listas, el envío)
 * vive en `useMoverPlata.ts`; la derivación del `tipo`, en el módulo puro.
 *
 * El backend no se toca: `crear_movimiento`/`crear_cambio_divisa` siguen siendo la
 * única puerta, con todas sus validaciones. Esto es la entrada, no el libro.
 */
import { Button } from "@/design-system/ui/button";
import { Checkbox } from "@/design-system/ui/checkbox";
import { Input } from "@/design-system/ui/input";
import { CuentaSelect, Field } from "@/components/admin/contabilidad/fields";
import { useMoverPlata } from "@/components/admin/contabilidad/useMoverPlata";
import { QUE_PASO, type QuePaso, type RespuestasMoverPlata } from "@/lib/admin/mover-plata";
import { cn } from "@/lib/utils";

export function MoverPlataForm({
  onCreated,
  /** Precarga el form desde el contexto que lo abre — hoy, la ficha de un socio
   *  en Cuentas ("Repartimos" + el socio ya puesto de un lado). Solo alimenta los
   *  valores iniciales: quien lo monte para dos entidades distintas tiene que
   *  montarlo condicionalmente (o darle `key`) para que la precarga se refresque. */
  inicial,
  /** `"card"` = suelto en una página (borde + título). `"plain"` = adentro de un
   *  Dialog, que ya pone su propio marco. */
  chrome = "card",
}: {
  onCreated: () => void;
  inicial?: Partial<RespuestasMoverPlata>;
  chrome?: "card" | "plain";
}) {
  const f = useMoverPlata({ inicial, onCreated });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        f.enviar();
      }}
      className={cn("space-y-3", chrome === "card" && "rounded-lg border hairline p-4")}
    >
      {chrome === "card" && <div className="t-eyebrow">Mover plata</div>}

      <QuePasoPicker value={f.quePaso} onChange={f.setQuePaso} />

      <div className="flex flex-wrap items-end gap-3">
        <Field label={f.cambioDivisa ? "Monto que sale" : "Monto"}>
          <Input
            type="number"
            step="1"
            min="1"
            value={f.monto}
            onChange={(e) => f.setMonto(e.target.value)}
            className="w-32 text-right tabular-nums"
          />
        </Field>

        {f.campos.origen && (
          <Field label={f.quePaso === "pague" ? "Sale de" : "De qué cuenta"}>
            <CuentaSelect cuentas={f.cuentasOrigen} value={f.origen} onChange={f.setOrigen} />
          </Field>
        )}
        {f.campos.destino && (
          <Field label={f.quePaso === "entro" ? "Entra a" : "A qué cuenta"}>
            <CuentaSelect cuentas={f.cuentasDestino} value={f.destino} onChange={f.setDestino} />
          </Field>
        )}

        {f.campos.categoria && !f.esDelSocio && (
          <Field label="¿De qué es?">
            <select
              value={f.categoria}
              onChange={(e) => f.setCategoria(e.target.value)}
              className="h-9 rounded-md border hairline bg-surface-elevated px-2 text-sm"
            >
              <option value="">Elegir…</option>
              {f.categorias.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nombre}
                </option>
              ))}
            </select>
          </Field>
        )}

        {/* Cambio de divisa: alcanza con UNO de los dos (el backend deriva el otro,
            `derivar_cambio_divisa`). El form viejo hacía elegir entre dos modos —
            "tengo la cotización" / "tengo los dos montos"— antes de escribir nada;
            acá se completa el que se tenga a mano. */}
        {f.cambioDivisa && (
          <>
            <Field label="Cotización (pesos por dólar)">
              <Input
                type="number"
                value={f.cotizacion}
                onChange={(e) => f.setCotizacion(e.target.value)}
                className="w-32 text-right tabular-nums"
                placeholder="Ej. 1400"
              />
            </Field>
            <Field label="…o monto que entra">
              <Input
                type="number"
                value={f.montoDestino}
                onChange={(e) => f.setMontoDestino(e.target.value)}
                className="w-32 text-right tabular-nums"
                placeholder="En la otra moneda"
              />
            </Field>
          </>
        )}

        {!f.cambioDivisa && (
          <Field label="Método">
            <select
              value={f.metodo}
              onChange={(e) => f.setMetodo(e.target.value)}
              className="h-9 rounded-md border hairline bg-surface-elevated px-2 text-sm capitalize"
            >
              <option value="">—</option>
              <option value="transferencia">transferencia</option>
              <option value="efectivo">efectivo</option>
            </select>
          </Field>
        )}
        <Field label="Fecha">
          <Input type="date" value={f.fecha} onChange={(e) => f.setFecha(e.target.value)} />
        </Field>
      </div>

      {/* La distinción gasto-vs-retiro, que antes eran dos palabras técnicas
          distintas en la fila de tipos. Es la única diferencia real entre las dos
          (el P&L cuenta `gasto` y no cuenta `retiro`), así que se pregunta así.

          El label NO dice "se lo llevó un socio", aunque el `retiro` nació para
          eso: un `retiro` baja el cash y NO mueve la deuda de nadie, así que
          cargar ahí la plata que se llevó un socio la deja sin registrar en su
          cuenta — el mismo hecho cargado como "Repartimos" sí se la ajusta. Dos
          entradas del mismo form con contabilidades opuestas era justo la
          confusión que esto vino a matar (hallazgo del supervisor). */}
      {f.quePaso === "pague" && (
        <div className="space-y-1">
          <label className="flex min-h-11 items-center gap-2 text-sm">
            <Checkbox
              checked={f.esDelSocio}
              onCheckedChange={(v) => f.marcarEsDelSocio(v === true)}
            />
            <span>
              No es un gasto del negocio
              <span className="block text-xs text-muted-foreground">
                Marcado, no cuenta en la ganancia del mes.
              </span>
            </span>
          </label>
          {f.esDelSocio && (
            <p className="pl-6 text-xs text-muted-foreground">
              Ojo: esto baja la caja y no le queda registrado a nadie. Si la plata se la llevó un
              socio, cargala como <strong>Repartimos</strong> para que le ajuste la cuenta.
            </p>
          )}
        </div>
      )}

      {f.cambioDivisa && (
        <p className="text-xs text-muted-foreground">
          Las dos cuentas son de monedas distintas, así que esto se registra como un cambio de
          divisa (dos asientos atados, uno por caja).
        </p>
      )}

      <div className="flex flex-wrap items-end gap-3">
        {f.campos.beneficiario && (
          <Field label="Beneficiario (opcional)">
            <Input
              value={f.beneficiario}
              onChange={(e) => f.setBeneficiario(e.target.value)}
              list="benef-list"
              placeholder="Ej. Jimena (CM)"
              className="w-56"
            />
            <datalist id="benef-list">
              {f.beneficiarios.map((b) => (
                <option key={b} value={b} />
              ))}
            </datalist>
          </Field>
        )}
        <Field label="Nota (opcional)">
          <Input
            value={f.nota}
            onChange={(e) => f.setNota(e.target.value)}
            placeholder="Ej. factura 0001-…"
            className="w-64"
          />
        </Field>
        {!f.cambioDivisa && (
          <Field label="Comprobante (opcional)">
            {/* eslint-disable-next-line no-restricted-syntax -- input file: no hay componente DS */}
            <input
              type="file"
              accept="application/pdf,image/*"
              onChange={(e) => f.setFile(e.target.files?.[0] ?? null)}
              className="text-xs"
            />
          </Field>
        )}
        <Button type="submit" variant="primary" disabled={f.enviando} loading={f.enviando}>
          {f.enviando ? "Guardando…" : "Registrar"}
        </Button>
      </div>
    </form>
  );
}

/** La única pregunta de arranque, en castellano. Las 4 opciones y su copy viven
 *  en `QUE_PASO` (módulo puro) — acá solo se pintan. */
function QuePasoPicker({ value, onChange }: { value: QuePaso; onChange: (q: QuePaso) => void }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
      {QUE_PASO.map((q) => (
        <button
          key={q.key}
          type="button"
          onClick={() => onChange(q.key)}
          className={cn(
            "min-h-11 rounded-md border px-3 py-2 text-left transition",
            value === q.key
              ? "border-ink bg-ink text-background"
              : "border-muted-foreground/30 hover:border-ink",
          )}
        >
          <span className="block text-sm font-medium">{q.label}</span>
          <span
            className={cn(
              "block text-xs",
              value === q.key ? "text-background/70" : "text-muted-foreground",
            )}
          >
            {q.sub}
          </span>
        </button>
      ))}
    </div>
  );
}
