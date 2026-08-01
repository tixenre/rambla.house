/**
 * MoverPlataForm.tsx — la ÚNICA entrada para mover plata entre cuentas.
 *
 * Reemplaza los 5 botones de tipo (`gasto`/`transferencia`/`retiro`/`aporte`/
 * `ajuste`) + el toggle aparte de "Cambio de divisa": 6 decisiones sobre
 * vocabulario contable antes de poder cargar un peso. Acá se pregunta lo que el
 * dueño ya sabe —qué pasó, de dónde salió, a dónde fue— y el `tipo` lo deriva
 * `lib/admin/mover-plata.ts` (puro, con su tabla de verdad testeada).
 *
 * Este componente SOLO pinta y junta respuestas. Toda la lógica de derivación vive
 * en el módulo puro para poder testearla sin montar React — el riesgo real del
 * cambio es derivar un tipo con la semántica de P&L equivocada.
 *
 * El backend no se toca: `crear_movimiento`/`crear_cambio_divisa` siguen siendo la
 * única puerta, con todas sus validaciones. Esto es la entrada, no el libro.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/design-system/ui/button";
import { Checkbox } from "@/design-system/ui/checkbox";
import { Input } from "@/design-system/ui/input";
import { CuentaSelect, Field } from "@/components/admin/contabilidad/fields";
import { adminApi, type Cuenta } from "@/lib/admin/api";
import {
  camposVisibles,
  derivarMovimiento,
  esCambioDeDivisa,
  MoverPlataInvalido,
  QUE_PASO,
  type QuePaso,
  type RespuestasMoverPlata,
} from "@/lib/admin/mover-plata";
import { cn } from "@/lib/utils";

export function MoverPlataForm({
  onCreated,
  /** Precarga para el atajo desde Rendición ("Registrar la transferencia"). */
  inicial,
}: {
  onCreated: () => void;
  inicial?: Partial<RespuestasMoverPlata>;
}) {
  const [quePaso, setQuePaso] = useState<QuePaso>(inicial?.quePaso ?? "pague");
  const [monto, setMonto] = useState(inicial?.monto ? String(inicial.monto) : "");
  const [origen, setOrigen] = useState(
    inicial?.cuentaOrigenId ? String(inicial.cuentaOrigenId) : "",
  );
  const [destino, setDestino] = useState(
    inicial?.cuentaDestinoId ? String(inicial.cuentaDestinoId) : "",
  );
  const [categoria, setCategoria] = useState("");
  const [esDelSocio, setEsDelSocio] = useState(false);
  const [cotizacion, setCotizacion] = useState("");
  const [montoDestino, setMontoDestino] = useState("");
  const [metodo, setMetodo] = useState("");
  const [fecha, setFecha] = useState("");
  const [nota, setNota] = useState("");
  const [beneficiario, setBeneficiario] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const cuentasQ = useQuery({
    queryKey: ["admin", "contabilidad", "cuentas-list"],
    queryFn: () => adminApi.listCuentas(),
  });
  const catsQ = useQuery({
    queryKey: ["admin", "contabilidad", "categorias"],
    queryFn: () => adminApi.listGastoCategorias(),
  });
  const benQ = useQuery({
    queryKey: ["admin", "contabilidad", "beneficiarios"],
    queryFn: () => adminApi.listBeneficiarios(),
  });

  const cuentas: Cuenta[] = cuentasQ.data?.cuentas ?? [];
  const categorias = catsQ.data?.categorias ?? [];
  const beneficiarios = benQ.data?.beneficiarios ?? [];

  const monedaDe = (id: string) => cuentas.find((c) => String(c.id) === id)?.moneda ?? null;

  const respuestas: RespuestasMoverPlata = useMemo(
    () => ({
      quePaso,
      monto: Number(monto) || 0,
      cuentaOrigenId: origen ? Number(origen) : null,
      cuentaDestinoId: destino ? Number(destino) : null,
      categoriaId: categoria ? Number(categoria) : null,
      esDelSocio,
      monedaOrigen: monedaDe(origen),
      monedaDestino: monedaDe(destino),
      cotizacion: cotizacion ? Number(cotizacion) : null,
      montoDestino: montoDestino ? Number(montoDestino) : null,
      metodo: metodo || null,
      fecha: fecha || null,
      nota: nota || null,
      beneficiario: beneficiario || null,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `monedaDe` deriva de `cuentas`, ya en deps
    [
      quePaso,
      monto,
      origen,
      destino,
      categoria,
      esDelSocio,
      cotizacion,
      montoDestino,
      metodo,
      fecha,
      nota,
      beneficiario,
      cuentas,
    ],
  );

  const campos = camposVisibles(quePaso);
  const cambioDivisa = esCambioDeDivisa(respuestas);
  // A diferencia del form viejo, las cuentas destino NO se filtran por moneda: si
  // el admin elige dos monedas distintas, eso ES un cambio de divisa y el form se
  // adapta solo. Antes tenía que saber de antemano que existía esa categoría y
  // cambiar de pantalla.
  const reset = () => {
    setMonto("");
    setOrigen("");
    setDestino("");
    setCategoria("");
    setEsDelSocio(false);
    setCotizacion("");
    setMontoDestino("");
    setMetodo("");
    setFecha("");
    setNota("");
    setBeneficiario("");
    setFile(null);
  };

  const crear = useMutation({
    mutationFn: async () => {
      const d = derivarMovimiento(respuestas);
      if (d.kind === "cambio_divisa") return adminApi.createCambioDivisa(d.body);
      const mov = await adminApi.createMovimiento(d.body);
      if (file) await adminApi.uploadComprobante(mov.id, file);
      return mov;
    },
    onSuccess: () => {
      reset();
      toast.success("Movimiento registrado");
      onCreated();
    },
    onError: (e) => toast.error("No se pudo registrar", { description: (e as Error).message }),
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        // La validación en castellano vive en el módulo puro: se corre acá para
        // avisar antes de mandar un request que ya sabemos que falla.
        try {
          derivarMovimiento(respuestas);
        } catch (err) {
          if (err instanceof MoverPlataInvalido) return toast.error(err.message);
          throw err;
        }
        crear.mutate();
      }}
      className="rounded-lg border hairline p-4 space-y-3"
    >
      <div className="t-eyebrow">Mover plata</div>

      {/* La única pregunta de arranque, en castellano. */}
      <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
        {QUE_PASO.map((q) => (
          <button
            key={q.key}
            type="button"
            onClick={() => setQuePaso(q.key)}
            className={cn(
              "min-h-11 rounded-md border px-3 py-2 text-left transition",
              quePaso === q.key
                ? "border-ink bg-ink text-background"
                : "border-muted-foreground/30 hover:border-ink",
            )}
          >
            <span className="block text-sm font-medium">{q.label}</span>
            <span
              className={cn(
                "block text-xs",
                quePaso === q.key ? "text-background/70" : "text-muted-foreground",
              )}
            >
              {q.sub}
            </span>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <Field label={cambioDivisa ? "Monto que sale" : "Monto"}>
          <Input
            type="number"
            value={monto}
            onChange={(e) => setMonto(e.target.value)}
            className="w-32 text-right tabular-nums"
          />
        </Field>

        {campos.origen && (
          <Field label={quePaso === "pague" ? "Sale de" : "De qué cuenta"}>
            <CuentaSelect cuentas={cuentas} value={origen} onChange={setOrigen} />
          </Field>
        )}
        {campos.destino && (
          <Field label={quePaso === "entro" ? "Entra a" : "A qué cuenta"}>
            <CuentaSelect cuentas={cuentas} value={destino} onChange={setDestino} />
          </Field>
        )}

        {campos.categoria && !esDelSocio && (
          <Field label="¿De qué es?">
            <select
              value={categoria}
              onChange={(e) => setCategoria(e.target.value)}
              className="h-9 rounded-md border hairline bg-surface-elevated px-2 text-sm"
            >
              <option value="">Elegir…</option>
              {categorias.map((c) => (
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
        {cambioDivisa && (
          <>
            <Field label="Cotización (pesos por dólar)">
              <Input
                type="number"
                value={cotizacion}
                onChange={(e) => setCotizacion(e.target.value)}
                className="w-32 text-right tabular-nums"
                placeholder="Ej. 1400"
              />
            </Field>
            <Field label="…o monto que entra">
              <Input
                type="number"
                value={montoDestino}
                onChange={(e) => setMontoDestino(e.target.value)}
                className="w-32 text-right tabular-nums"
                placeholder="En la otra moneda"
              />
            </Field>
          </>
        )}

        {!cambioDivisa && (
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
        )}
        <Field label="Fecha">
          <Input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />
        </Field>
      </div>

      {/* La distinción gasto-vs-retiro, que antes eran dos palabras técnicas
          distintas en la fila de tipos. Es la única diferencia real entre las dos
          (el P&L cuenta `gasto` y no cuenta `retiro`), así que se pregunta así. */}
      {quePaso === "pague" && (
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <Checkbox checked={esDelSocio} onCheckedChange={(v) => setEsDelSocio(v === true)} />
          <span>
            Se lo llevó un socio para él — no es un gasto del negocio
            <span className="block text-xs text-muted-foreground">
              Marcado, no cuenta en la ganancia del mes.
            </span>
          </span>
        </label>
      )}

      {cambioDivisa && (
        <p className="text-xs text-muted-foreground">
          Las dos cuentas son de monedas distintas, así que esto se registra como un cambio de
          divisa (dos asientos atados, uno por caja).
        </p>
      )}

      <div className="flex flex-wrap items-end gap-3">
        {campos.beneficiario && (
          <Field label="Beneficiario (opcional)">
            <Input
              value={beneficiario}
              onChange={(e) => setBeneficiario(e.target.value)}
              list="benef-list"
              placeholder="Ej. Jimena (CM)"
              className="w-56"
            />
            <datalist id="benef-list">
              {beneficiarios.map((b) => (
                <option key={b} value={b} />
              ))}
            </datalist>
          </Field>
        )}
        <Field label="Nota (opcional)">
          <Input
            value={nota}
            onChange={(e) => setNota(e.target.value)}
            placeholder="Ej. factura 0001-…"
            className="w-64"
          />
        </Field>
        {!cambioDivisa && (
          <Field label="Comprobante (opcional)">
            {/* eslint-disable-next-line no-restricted-syntax -- input file: no hay componente DS */}
            <input
              type="file"
              accept="application/pdf,image/*"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="text-xs"
            />
          </Field>
        )}
        <Button
          type="submit"
          variant="primary"
          disabled={crear.isPending}
          loading={crear.isPending}
        >
          {crear.isPending ? "Guardando…" : "Registrar"}
        </Button>
      </div>
    </form>
  );
}
