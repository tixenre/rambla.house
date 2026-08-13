import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { talleresAdminApi } from "@/lib/admin/api/talleres";
import type { ClaseBody, EdicionAdmin, ModalidadPagoBody } from "@/lib/admin/api/types";
import { Button } from "@/design-system/ui/button";
import { EstadoBadge } from "@/design-system/ui/EstadoBadge";
import { IconButton } from "@/design-system/ui/icon-button";
import { Input } from "@/design-system/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/design-system/ui/select";
import { Spinner } from "@/design-system/ui/spinner";
import { Switch } from "@/design-system/ui/switch";
import { fmtArs, fmtMesAno } from "@/lib/format";
import { TallerCalendario } from "@/components/talleres/TallerCalendario";
import { ClasesAsistente } from "./ClasesAsistente";
import { updateEdicionInCache } from "./cache";

export function ClasesSection({ edicion }: { edicion: EdicionAdmin }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [clases, setClases] = useState<ClaseBody[]>(edicion.clases ?? []);
  const [numeroEdicion, setNumeroEdicion] = useState(String(edicion.numero_edicion));

  useEffect(() => {
    setClases(edicion.clases ?? []);
    setNumeroEdicion(String(edicion.numero_edicion));
  }, [edicion.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const mut = useMutation({
    mutationFn: (body: { tipo_taller: string; clases: ClaseBody[] }) =>
      talleresAdminApi.updateEdicionClases(edicion.id, body),
    onSuccess: (updated) => {
      toast.success("Clases guardadas");
      setEditing(false);
      updateEdicionInCache(qc, updated);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  // Corrige el número de edición (ej. taller con historia previa fuera de
  // Rambla — nace #1 y hay que pasarlo al número real). No re-deriva el slug.
  const numeroMut = useMutation({
    mutationFn: (numero_edicion: number) =>
      talleresAdminApi.updateEdicion(edicion.id, { numero_edicion }),
    onSuccess: (updated) => {
      toast.success("Número de edición actualizado");
      updateEdicionInCache(qc, updated);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  function handleSave() {
    if (clases.length === 0) {
      toast.error("Agregá al menos una clase");
      return;
    }
    // `tipo_taller` no tiene UI propia (Escuela v2): se preserva el valor ya
    // guardado de la edición, no se re-decide acá.
    mut.mutate({ tipo_taller: edicion.tipo_taller || "intensivo", clases });
  }

  function handleCancel() {
    setClases(edicion.clases ?? []);
    setEditing(false);
  }

  function handleSaveNumero() {
    const n = parseInt(numeroEdicion, 10);
    if (isNaN(n) || n < 1) {
      toast.error("El número de edición debe ser un entero positivo");
      return;
    }
    if (n !== edicion.numero_edicion) numeroMut.mutate(n);
  }

  return !editing ? (
    <div className="flex flex-col gap-4">
      <div className="flex items-end gap-2">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
            Número de edición
          </label>
          <Input
            type="number"
            min={1}
            value={numeroEdicion}
            onChange={(e) => setNumeroEdicion(e.target.value)}
            className="w-24"
          />
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleSaveNumero}
          disabled={numeroMut.isPending || numeroEdicion === String(edicion.numero_edicion)}
          className="gap-2"
        >
          {numeroMut.isPending ? <Spinner size="xs" /> : "Guardar"}
        </Button>
      </div>
      {edicion.clases && edicion.clases.length > 0 ? (
        <TallerCalendario sesiones={edicion.clases} horario={edicion.horario} />
      ) : (
        <p className="text-sm text-muted-foreground italic">Sin clases cargadas.</p>
      )}
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
          Editar clases
        </Button>
      </div>
    </div>
  ) : (
    <div className="flex flex-col gap-5">
      <ClasesAsistente clases={clases} onChange={setClases} />
      {clases.length > 0 && (
        <div className="pointer-events-none select-none">
          <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground mb-3">
            Preview
          </p>
          <TallerCalendario sesiones={clases} />
        </div>
      )}
      <div className="flex gap-2 justify-end pt-2">
        <Button variant="ghost" size="sm" onClick={handleCancel}>
          Cancelar
        </Button>
        <Button onClick={handleSave} disabled={mut.isPending} size="sm" className="gap-2">
          {mut.isPending ? <Spinner size="xs" /> : <Save className="h-3.5 w-3.5" />}
          Guardar clases
        </Button>
      </div>
    </div>
  );
}

export function PreciosSection({ edicion }: { edicion: EdicionAdmin }) {
  const qc = useQueryClient();
  const [precioTotal, setPrecioTotal] = useState(String(edicion.precio_total));
  const [precioSena, setPrecioSena] = useState(String(edicion.precio_sena));
  const [cuposTotal, setCuposTotal] = useState(String(edicion.cupos_total));
  const [usaEstudio, setUsaEstudio] = useState(edicion.usa_estudio);
  const [valorEstudio, setValorEstudio] = useState(String(edicion.valor_estudio));
  const [valorEstudioModo, setValorEstudioModo] = useState(edicion.valor_estudio_modo);
  const [usaEquipos, setUsaEquipos] = useState(edicion.usa_equipos);
  const [valorEquipos, setValorEquipos] = useState(String(edicion.valor_equipos));
  const [valorEquiposModo, setValorEquiposModo] = useState(edicion.valor_equipos_modo);
  // Formas de pagar: lista de planes (0+, el dueño puede ofrecer "pago único"
  // Y "en cuotas" a la vez para que el cliente elija) — pero NINGUNO tipea un
  // total: el monto de cada plan sale siempre del Precio total de arriba
  // ("por qué debería ponerle manualmente el valor de la cuota si ya tenemos
  // el total"), salvo el % de descuento opcional del pago único, que resta
  // sobre ese mismo total en vez de pedir un segundo número absoluto. El
  // monto por cuota lo sigue derivando el backend, nunca se tipea.
  const [planes, setPlanes] = useState<PlanForm[]>(
    (edicion.modalidades ?? []).map((m) => planToForm(m, edicion.precio_total)),
  );

  useEffect(() => {
    setPrecioTotal(String(edicion.precio_total));
    setPrecioSena(String(edicion.precio_sena));
    setCuposTotal(String(edicion.cupos_total));
    setUsaEstudio(edicion.usa_estudio);
    setValorEstudio(String(edicion.valor_estudio));
    setValorEstudioModo(edicion.valor_estudio_modo);
    setUsaEquipos(edicion.usa_equipos);
    setValorEquipos(String(edicion.valor_equipos));
    setValorEquiposModo(edicion.valor_equipos_modo);
    setPlanes((edicion.modalidades ?? []).map((m) => planToForm(m, edicion.precio_total)));
  }, [edicion.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const mut = useMutation({
    mutationFn: (body: object) => talleresAdminApi.updateEdicion(edicion.id, body),
    onSuccess: (updated) => {
      toast.success("Precio y forma de pago actualizados");
      updateEdicionInCache(qc, updated);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  function agregarPlan() {
    setPlanes((p) => [...p, { tipoPago: "unico", nCuotas: "2", descuentoPct: "", nota: "" }]);
  }

  function quitarPlan(idx: number) {
    setPlanes((p) => p.filter((_, i) => i !== idx));
  }

  function actualizarPlan(idx: number, patch: Partial<PlanForm>) {
    setPlanes((p) => p.map((plan, i) => (i === idx ? { ...plan, ...patch } : plan)));
  }

  function handleSave() {
    const total = parseInt(precioTotal, 10);
    const sena = parseInt(precioSena, 10);
    const cupos = parseInt(cuposTotal, 10);
    const valEstudio = parseInt(valorEstudio, 10);
    const valEquipos = parseInt(valorEquipos, 10);
    if (isNaN(total) || isNaN(sena) || isNaN(cupos) || cupos < 1) {
      toast.error("Ingresá números válidos");
      return;
    }
    if (cupos < edicion.cupos_confirmados) {
      toast.error(`No podés bajar cupos a ${cupos}: hay ${edicion.cupos_confirmados} confirmados`);
      return;
    }
    if ((usaEstudio && isNaN(valEstudio)) || (usaEquipos && isNaN(valEquipos))) {
      toast.error("Ingresá un valor válido para lo que usa el taller");
      return;
    }
    const modalidades: ModalidadPagoBody[] = [];
    for (const plan of planes) {
      if (plan.tipoPago === "unico") {
        const pct = plan.descuentoPct.trim() === "" ? 0 : parseFloat(plan.descuentoPct);
        if (isNaN(pct) || pct < 0 || pct >= 100) {
          toast.error("El % de descuento tiene que estar entre 0 y 99");
          return;
        }
        modalidades.push({
          id: plan.id ?? null,
          codigo: "total",
          label: "Pago único",
          nota: plan.nota.trim(),
          monto_total: pct > 0 ? Math.round(total * (1 - pct / 100)) : total,
          n_cuotas: 1,
        });
      } else {
        const cuotas = parseInt(plan.nCuotas, 10);
        if (isNaN(cuotas) || cuotas < 2) {
          toast.error("La cantidad de cuotas tiene que ser 2 o más");
          return;
        }
        modalidades.push({
          id: plan.id ?? null,
          codigo: `cuotas-${cuotas}`,
          label: `En ${cuotas} cuotas`,
          nota: plan.nota.trim(),
          monto_total: total,
          n_cuotas: cuotas,
        });
      }
    }
    const codigos = modalidades.map((m) => m.codigo);
    if (new Set(codigos).size !== codigos.length) {
      toast.error(
        "Hay dos formas de pago iguales — no repitas 'Pago único' o la misma cantidad de cuotas",
      );
      return;
    }
    mut.mutate({
      precio_total: total,
      precio_sena: sena,
      cupos_total: cupos,
      usa_estudio: usaEstudio,
      valor_estudio: isNaN(valEstudio) ? 0 : valEstudio,
      valor_estudio_modo: valorEstudioModo,
      usa_equipos: usaEquipos,
      valor_equipos: isNaN(valEquipos) ? 0 : valEquipos,
      valor_equipos_modo: valorEquiposModo,
      modalidades,
    });
  }

  return (
    <div className="flex flex-col gap-4">
      {edicion.cupos_confirmados >= edicion.cupos_total && (
        <div className="rounded-lg bg-amber/10 border border-amber/30 px-4 py-3 text-sm text-ink">
          ⚠ Edición completa — {edicion.cupos_confirmados}/{edicion.cupos_total} cupos ocupados
        </div>
      )}
      <div className="grid sm:grid-cols-3 gap-4">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
            Precio total (ARS)
          </label>
          <Input
            type="number"
            min={0}
            value={precioTotal}
            onChange={(e) => setPrecioTotal(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
            Seña (ARS)
          </label>
          <Input
            type="number"
            min={0}
            value={precioSena}
            onChange={(e) => setPrecioSena(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
            Cupos totales
          </label>
          <Input
            type="number"
            min={1}
            value={cuposTotal}
            onChange={(e) => setCuposTotal(e.target.value)}
          />
        </div>
      </div>

      <div className="border-t border-border/40 pt-5 flex flex-col gap-4">
        <div>
          <p className="text-sm font-medium text-ink">Formas de pagar</p>
          <p className="text-xs text-muted-foreground">
            El monto sale siempre del Precio total de arriba — podés ofrecer más de una forma (ej:
            pago único con descuento Y en cuotas) para que el cliente elija.
          </p>
        </div>
        {planes.length === 0 && (
          <p className="text-sm text-muted-foreground italic">
            Sin formas configuradas — el público paga el Precio total de arriba de una sola vez.
          </p>
        )}
        {planes.map((plan, idx) => (
          <div key={plan.id ?? `nuevo-${idx}`} className="flex flex-col gap-1.5">
            <div className="grid sm:grid-cols-[160px_120px_1fr_auto] gap-2 items-end">
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                  Modalidad
                </label>
                <Select
                  value={plan.tipoPago}
                  onValueChange={(v) => actualizarPlan(idx, { tipoPago: v as "unico" | "cuotas" })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="unico">Pago único</SelectItem>
                    <SelectItem value="cuotas">En cuotas</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {plan.tipoPago === "cuotas" ? (
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                    Cantidad
                  </label>
                  <Input
                    type="number"
                    min={2}
                    value={plan.nCuotas}
                    onChange={(e) => actualizarPlan(idx, { nCuotas: e.target.value })}
                  />
                </div>
              ) : (
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                    % descuento
                  </label>
                  <Input
                    type="number"
                    min={0}
                    max={99}
                    placeholder="0"
                    value={plan.descuentoPct}
                    onChange={(e) => actualizarPlan(idx, { descuentoPct: e.target.value })}
                  />
                </div>
              )}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                  Nota (opcional)
                </label>
                <Input
                  value={plan.nota}
                  onChange={(e) => actualizarPlan(idx, { nota: e.target.value })}
                  placeholder="ej: transferencia, efectivo"
                />
              </div>
              <IconButton
                aria-label="Quitar forma de pago"
                size="sm"
                onClick={() => quitarPlan(idx)}
                className="text-muted-foreground hover:text-destructive mb-0.5"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </IconButton>
            </div>
            {previewPlan(plan, precioTotal) && (
              <p className="text-xs text-rosa-ink pl-0.5">{previewPlan(plan, precioTotal)}</p>
            )}
          </div>
        ))}
        <div>
          <Button variant="outline" size="sm" onClick={agregarPlan} className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            Agregar forma de pago
          </Button>
        </div>
      </div>

      {/* Economía del taller: si usa el Estudio y/o equipos de alquiler, para
          que el pedido mensual auto-generado atribuya esa plata (Estudio →
          caja Estudio, equipos → Rental) — ver `_regenerar_pedidos_taller`. */}
      <div className="flex flex-col gap-3 rounded-xl border border-border/50 bg-muted/10 p-4">
        <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
          Economía del taller
        </p>
        <div className="flex items-center justify-between gap-3">
          <label className="text-sm">Usa el espacio del Estudio</label>
          <Switch checked={usaEstudio} onCheckedChange={setUsaEstudio} />
        </div>
        {usaEstudio && (
          <div className="flex items-end gap-3 pl-1">
            <div className="flex flex-col gap-1.5 flex-1">
              <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Valor Estudio (ARS)
              </label>
              <Input
                type="number"
                min={0}
                value={valorEstudio}
                onChange={(e) => setValorEstudio(e.target.value)}
              />
            </div>
            <Select
              value={valorEstudioModo}
              onValueChange={(v) => setValorEstudioModo(v as "mensual" | "total")}
            >
              <SelectTrigger className="w-[130px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="mensual">por mes</SelectItem>
                <SelectItem value="total">total</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}
        <div className="flex items-center justify-between gap-3 pt-2 border-t border-border/40">
          <label className="text-sm">Usa equipos de alquiler</label>
          <Switch checked={usaEquipos} onCheckedChange={setUsaEquipos} />
        </div>
        {usaEquipos && (
          <div className="flex items-end gap-3 pl-1">
            <div className="flex flex-col gap-1.5 flex-1">
              <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Valor equipos (ARS)
              </label>
              <Input
                type="number"
                min={0}
                value={valorEquipos}
                onChange={(e) => setValorEquipos(e.target.value)}
              />
            </div>
            <Select
              value={valorEquiposModo}
              onValueChange={(v) => setValorEquiposModo(v as "mensual" | "total")}
            >
              <SelectTrigger className="w-[130px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="mensual">por mes</SelectItem>
                <SelectItem value="total">total</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      <div className="flex justify-end">
        <Button onClick={handleSave} disabled={mut.isPending} className="gap-2">
          {mut.isPending ? <Spinner size="sm" /> : <Save className="h-4 w-4" />}
          Guardar
        </Button>
      </div>
    </div>
  );
}

export function PagosSection({ edicion }: { edicion: EdicionAdmin }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    pago_alias: edicion.pago_alias ?? "",
    pago_cbu: edicion.pago_cbu ?? "",
    pago_banco: edicion.pago_banco ?? "",
    direccion: edicion.direccion ?? "",
    fecha_cierre_inscripcion: edicion.fecha_cierre_inscripcion ?? "",
  });

  useEffect(() => {
    setForm({
      pago_alias: edicion.pago_alias ?? "",
      pago_cbu: edicion.pago_cbu ?? "",
      pago_banco: edicion.pago_banco ?? "",
      direccion: edicion.direccion ?? "",
      fecha_cierre_inscripcion: edicion.fecha_cierre_inscripcion ?? "",
    });
  }, [edicion.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const mut = useMutation({
    mutationFn: (body: typeof form) => talleresAdminApi.updateEdicion(edicion.id, body),
    onSuccess: (updated) => {
      toast.success("Guardado");
      updateEdicionInCache(qc, updated);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const tf = (label: string, key: keyof typeof form) => (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
        {label}
      </label>
      <Input
        value={form[key]}
        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
      />
    </div>
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="grid sm:grid-cols-2 gap-4">{tf("Dirección", "direccion")}</div>
      <div className="grid sm:grid-cols-3 gap-4">
        {tf("Alias de pago", "pago_alias")}
        {tf("CBU", "pago_cbu")}
        {tf("Banco", "pago_banco")}
      </div>
      <div className="border-t border-border/40 pt-4">
        <div className="grid sm:grid-cols-2 gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
              Cierre de inscripciones
            </label>
            <Input
              type="date"
              value={form.fecha_cierre_inscripcion}
              onChange={(e) => setForm((f) => ({ ...f, fecha_cierre_inscripcion: e.target.value }))}
            />
            <p className="text-2xs text-muted-foreground">
              Vacío = sin cierre, siempre abierto. Pasada esta fecha, la inscripción se rechaza.
            </p>
          </div>
        </div>
      </div>
      <div className="flex justify-end">
        <Button onClick={() => mut.mutate(form)} disabled={mut.isPending} className="gap-2">
          {mut.isPending ? <Spinner size="sm" /> : <Save className="h-4 w-4" />}
          Guardar datos de pago
        </Button>
      </div>
    </div>
  );
}

// F4a/F4b: formas de pagar — el monto de CADA plan sale del Precio total de
// la edición (una sola fuente, nunca un segundo campo a mano); el único
// número propio de un plan es el % de descuento del pago único (opcional,
// resta sobre ese mismo total). El monto POR cuota lo deriva el backend
// (`monto_total / n_cuotas`), nunca se tipea.
type PlanForm = {
  id?: number | null;
  tipoPago: "unico" | "cuotas";
  nCuotas: string;
  descuentoPct: string;
  nota: string;
};

/** Reconstruye el form de un plan ya guardado. Un pago único cuyo monto
 * quedó por debajo del Precio total se interpreta como "traía un % de
 * descuento" y se repuebla ese campo (redondeado) — nunca al revés, el
 * descuento no se persiste aparte, solo el monto ya resuelto. */
function planToForm(m: ModalidadPagoBody, precioTotalActual: number): PlanForm {
  const esUnico = (m.n_cuotas ?? 1) <= 1;
  let descuentoPct = "";
  if (esUnico && precioTotalActual > 0 && m.monto_total < precioTotalActual) {
    descuentoPct = String(Math.round((1 - m.monto_total / precioTotalActual) * 100));
  }
  return {
    id: m.id,
    tipoPago: esUnico ? "unico" : "cuotas",
    nCuotas: String(m.n_cuotas ?? 2),
    descuentoPct,
    nota: m.nota ?? "",
  };
}

/** Preview EN VIVO de qué va a ver el público con este plan — no se manda al
 * backend (es el que ya recalcula al guardar), es solo para que el admin vea
 * el resultado ANTES de guardar. */
function previewPlan(plan: PlanForm, precioTotalStr: string): string | null {
  const total = parseInt(precioTotalStr, 10);
  if (isNaN(total) || total <= 0) return null;
  if (plan.tipoPago === "unico") {
    const pct = plan.descuentoPct.trim() === "" ? 0 : parseFloat(plan.descuentoPct);
    const monto = !isNaN(pct) && pct > 0 && pct < 100 ? Math.round(total * (1 - pct / 100)) : total;
    return `El público ve: ${fmtArs(monto)}, un solo pago`;
  }
  const cuotas = parseInt(plan.nCuotas, 10);
  if (isNaN(cuotas) || cuotas < 2) return null;
  const porCuota = Math.round(total / cuotas);
  return `El público ve: ${cuotas} cuotas de ${fmtArs(porCuota)} (total ${fmtArs(total)})`;
}

// Puente Talleres → Pedidos (Fase 1, #1308): antes había que buscar a mano en
// /admin/pedidos qué pedidos generó una edición y si ya estaban pagados.
export function PedidosGeneradosSection({ edicion }: { edicion: EdicionAdmin }) {
  const { data: pedidos = [], isLoading } = useQuery({
    queryKey: ["admin", "ediciones", edicion.id, "pedidos"],
    queryFn: () => talleresAdminApi.listPedidosEdicion(edicion.id),
  });

  if (isLoading) {
    return (
      <div className="flex justify-center py-4">
        <Spinner size="sm" />
      </div>
    );
  }

  if (pedidos.length === 0) {
    return (
      <p className="text-sm text-muted-foreground italic">
        Todavía no se generó ningún pedido para esta edición.
      </p>
    );
  }

  return (
    <ul className="divide-y divide-border/40 rounded-lg border border-border/50">
      {pedidos.map((p) => (
        <li key={p.id}>
          <Link
            to="/admin/pedidos/$id"
            params={{ id: String(p.id) }}
            className="flex items-center gap-3 px-3 py-2.5 text-sm transition hover:bg-muted/20"
          >
            <span className="min-w-0 flex-1 truncate">
              {fmtMesAno(p.fecha_desde)}
              {p.numero_pedido ? ` · #${p.numero_pedido}` : ""}
            </span>
            <EstadoBadge estado={p.estado} />
            <span className="shrink-0 font-mono text-xs text-muted-foreground">
              {fmtArs(p.monto_pagado)} / {fmtArs(p.monto_total)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
