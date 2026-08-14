/**
 * ClienteDetalleDialog — ficha única de cliente: ver + editar en una sola
 * pantalla (no modal, no BottomSheet full-screen). Reemplaza el par
 * ClienteFormDialog (edición) + ClienteHistorialSheet (vista, en
 * clientes.lazy.tsx) que antes vivían separados y duplicaban el bloque
 * RENAPER — pedido del dueño 2026-07-05: "no me gusta que sea pantalla
 * completa" + "unificalas".
 *
 * Con identidad verificada (Didit/RENAPER), el nombre/apellido dejan de ser
 * editables — el cliente nunca los edita a mano y un nombre cargado a mano
 * ("freya -") no aporta nada frente al legal ya verificado. La ficha muestra
 * `nombre_legal`/`direccion_legal` (resueltos server-side, mismo criterio que
 * GET /api/cliente/me). Teléfono/email/dirección de contacto pasan a
 * solo-lectura cuando está verificado (decisión del dueño); CUIT/DNI sigue
 * editable — tiene su propio circuito de verificación (lookup AFIP), aparte
 * de la identidad personal RENAPER.
 */
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";

import {
  BadgeCheck,
  Check,
  ChevronDown,
  Copy,
  Plus,
  Search,
  ShieldAlert,
  ShieldCheck,
  Users,
} from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/design-system/ui/dialog";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Label } from "@/design-system/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/design-system/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/design-system/ui/dropdown-menu";
import { EstadoBadge } from "@/design-system/ui/EstadoBadge";
import { WhatsAppLinkButton } from "@/components/admin/WhatsAppLinkButton";
import { GrupoCard } from "@/components/admin/ClientesDuplicadosDialog";

import { adminApi, ESTADO_LABEL, type Cliente, type ClienteInput } from "@/lib/admin/api";
import { usePadronLookup } from "@/lib/admin/usePadronLookup";
import { AuthedHttpError } from "@/lib/authedFetch";
import { fmtArs, formatFechaDisplay } from "@/lib/format";
import { etiquetaPedido } from "@/lib/pedido-estados";
import { PERFIL_IMPUESTOS_LABEL, type PerfilImpuestos } from "@/lib/iva";

type Props = {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  cliente?: Cliente | null;
  onSaved?: (c: Cliente) => void;
};

const PERFILES = [
  { value: "consumidor_final", label: "Consumidor final" },
  { value: "monotributo", label: "Monotributo" },
  { value: "responsable_inscripto", label: "Responsable inscripto" },
  { value: "exento", label: "Exento" },
];

// El label visible sale de la fuente única `ESTADO_LABEL`.
const estadoLabel = (e: string) => ESTADO_LABEL[e as keyof typeof ESTADO_LABEL] ?? e;
const fmtFecha = (s: string | null) => formatFechaDisplay(s);

export function ClienteDetalleDialog({ open, onOpenChange, cliente, onSaved }: Props) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const editing = !!cliente?.id;
  const verificado = editing && !!cliente?.dni_validado_at;

  const form = useForm<ClienteInput>({
    defaultValues: {
      nombre: "",
      apellido: "",
      telefono: "",
      email: "",
      direccion: "",
      cuit: "",
      descuento: 0,
      perfil_impuestos: "consumidor_final",
    },
  });

  useEffect(() => {
    if (open) {
      form.reset({
        nombre: cliente?.nombre ?? "",
        apellido: cliente?.apellido ?? "",
        telefono: cliente?.telefono ?? "",
        email: cliente?.email ?? "",
        direccion: cliente?.direccion ?? "",
        cuit: cliente?.cuit ?? "",
        descuento: cliente?.descuento ?? 0,
        perfil_impuestos: cliente?.perfil_impuestos ?? "consumidor_final",
      });
    }
  }, [open, cliente, form]);

  const mut = useMutation({
    mutationFn: async (data: ClienteInput) =>
      editing ? adminApi.updateCliente(cliente!.id, data) : adminApi.createCliente(data),
    onSuccess: (c) => {
      toast.success(editing ? "Cliente actualizado" : "Cliente creado");
      qc.invalidateQueries({ queryKey: ["admin", "clientes"] });
      onSaved?.(c);
      onOpenChange(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const submit = form.handleSubmit((data) => {
    // Verificado: nombre/apellido no se tocan desde acá (solo-lectura, RENAPER
    // manda) — se mandan los ya guardados para no pisarlos con el default vacío.
    const payload = verificado
      ? { ...data, nombre: cliente!.nombre, apellido: cliente!.apellido }
      : data;
    if (!verificado && !payload.nombre.trim()) {
      toast.error("Nombre requerido");
      return;
    }
    mut.mutate({ ...payload, descuento: Number(payload.descuento) || 0 });
  });

  const perfil = form.watch("perfil_impuestos");
  const cuit = form.watch("cuit");

  const padron = usePadronLookup((datos) => {
    if (!verificado && !form.getValues("nombre").trim()) {
      if (datos.nombre || datos.apellido) {
        if (datos.nombre) form.setValue("nombre", datos.nombre);
        if (datos.apellido) form.setValue("apellido", datos.apellido);
      } else if (datos.razon_social) {
        form.setValue("nombre", datos.razon_social);
      }
    }
    if (datos.domicilio) form.setValue("direccion", datos.domicilio);
    if (datos.condicion_iva) form.setValue("perfil_impuestos", datos.condicion_iva);
  });

  // ── Historial de pedidos + perfiles fiscales (#1240) — solo con cliente existente ──
  const pedidosQ = useQuery({
    queryKey: ["admin", "cliente-pedidos", cliente?.id],
    queryFn: () => adminApi.getClientePedidos(cliente!.id),
    enabled: !!cliente?.id && open,
  });
  const pedidos = pedidosQ.data ?? [];
  // Los borradores se listan (el admin quiere verlos) pero NO cuentan como
  // pedidos ni como plata gastada: son presupuestos rápidos, no ventas.
  const pedidosReales = pedidos.filter((p) => p.estado !== "borrador");
  const totalGastado = pedidosReales.reduce((acc, p) => acc + (p.monto_total ?? 0), 0);

  const perfilesFiscalesQ = useQuery({
    queryKey: ["admin", "cliente-perfiles-fiscales", cliente?.id],
    queryFn: () => adminApi.getClientePerfilesFiscales(cliente!.id),
    enabled: !!cliente?.id && open,
  });

  // Sugerencia de fusión (#1251 Fase 2) — si este cliente comparte CUIL
  // verificado con otro, mostrar el mismo picker que la vista global de
  // "Duplicados", pero inline en su propia ficha (antes solo se encontraba
  // desde el botón global, desconectado de acá).
  const duplicadosQ = useQuery({
    queryKey: ["admin", "cliente-duplicados", cliente?.id],
    queryFn: () => adminApi.getClienteDuplicados(cliente!.id),
    enabled: !!cliente?.id && open,
  });

  // ── Verificación de identidad (re-chequeo Didit / link) ──────────────────────
  const [linkVerif, setLinkVerif] = useState<string | null>(null);
  const [generando, setGenerando] = useState(false);
  const [copiado, setCopiado] = useState(false);
  const [rechequeando, setRechequeando] = useState(false);
  const [sessionIdManual, setSessionIdManual] = useState("");

  useEffect(() => {
    setLinkVerif(null);
    setCopiado(false);
    setSessionIdManual("");
  }, [cliente?.id]);

  async function rechequearVerificacion(sessionIdOverride?: string) {
    if (!cliente) return;
    setRechequeando(true);
    try {
      const r = await adminApi.rechequearVerificacion(cliente.id, sessionIdOverride);
      const actualizado = await adminApi.getCliente(cliente.id);
      onSaved?.(actualizado);
      qc.invalidateQueries({ queryKey: ["admin", "clientes"] });
      const sesionCorta = r.session_id ? ` (sesión ${r.session_id.slice(0, 8)}…)` : "";
      if (actualizado.dni_validado_at) {
        toast.success("Didit ya lo tiene aprobado — identidad verificada.");
      } else if (r.status === "Declined") {
        toast.error(`Didit lo sigue mostrando rechazado${sesionCorta}.`);
      } else {
        toast.message(`Didit responde: ${r.status || "sin novedades"}${sesionCorta}.`);
      }
    } catch (err) {
      toast.error(
        err instanceof AuthedHttpError && err.status === 409
          ? "Este cliente todavía no inició una verificación con Didit."
          : "No se pudo re-chequear con Didit",
      );
    } finally {
      setRechequeando(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-full sm:max-w-2xl max-h-[92vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <DialogTitle>
                {editing ? cliente!.nombre_legal || "Cliente" : "Nuevo cliente"}
              </DialogTitle>
              <DialogDescription>Datos de contacto y condiciones fiscales.</DialogDescription>
            </div>
            {editing && (
              <div className="flex shrink-0 gap-1.5 pr-6">
                <WhatsAppLinkButton phone={cliente!.telefono_contacto ?? cliente!.telefono} />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="gap-1.5"
                  onClick={() =>
                    navigate({
                      to: "/admin/pedidos/nuevo",
                      search: { cliente_id: cliente!.id } as never,
                    })
                  }
                >
                  <Plus className="h-3.5 w-3.5" />
                  Nuevo pedido
                </Button>
              </div>
            )}
          </div>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4">
          {verificado ? (
            <IdentidadVerificada cliente={cliente!} />
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Nombre *</Label>
                <Input {...form.register("nombre", { required: true })} />
              </div>
              <div className="space-y-1">
                <Label>Apellido</Label>
                <Input {...form.register("apellido")} />
              </div>
            </div>
          )}

          {editing && !verificado && (
            <IdentidadSinVerificar
              cliente={cliente!}
              rechequeando={rechequeando}
              onRechequear={rechequearVerificacion}
              sessionIdManual={sessionIdManual}
              onSessionIdManualChange={setSessionIdManual}
              linkVerif={linkVerif}
              copiado={copiado}
              onCopiar={() => {
                if (!linkVerif) return;
                navigator.clipboard.writeText(linkVerif);
                setCopiado(true);
                setTimeout(() => setCopiado(false), 2000);
              }}
              generando={generando}
              onGenerarLink={async () => {
                setGenerando(true);
                try {
                  const r = await adminApi.generarLinkVerificacion(cliente!.id);
                  setLinkVerif(r.url);
                } catch {
                  toast.error("No se pudo generar el link de verificación");
                } finally {
                  setGenerando(false);
                }
              }}
            />
          )}

          {editing && duplicadosQ.data && (
            <div className="space-y-2 rounded-lg border border-amber/40 bg-amber/8 p-3">
              <div className="flex items-center gap-1.5 text-sm font-semibold text-ink">
                <Users className="h-4 w-4 shrink-0" />
                Posible cuenta duplicada — mismo CUIL verificado
              </div>
              <GrupoCard
                grupo={duplicadosQ.data}
                onMerged={() => {
                  qc.invalidateQueries({ queryKey: ["admin", "clientes"] });
                  onOpenChange(false);
                }}
              />
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            {verificado ? (
              <>
                <ReadOnlyField
                  label="Teléfono"
                  value={cliente!.telefono_contacto ?? cliente!.telefono}
                />
                <ReadOnlyField
                  label="Email"
                  value={cliente!.email_comunicacion ?? cliente!.email}
                />
                <ReadOnlyField
                  label="Dirección"
                  value={cliente!.direccion_legal}
                  className="col-span-2"
                />
              </>
            ) : (
              <>
                <div className="space-y-1">
                  <Label>Teléfono</Label>
                  <Input {...form.register("telefono")} />
                </div>
                <div className="space-y-1">
                  <Label>Email</Label>
                  <Input type="email" {...form.register("email")} />
                </div>
                <div className="space-y-1 col-span-2">
                  <Label>Dirección</Label>
                  <Input {...form.register("direccion")} />
                </div>
              </>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>CUIT / DNI</Label>
              <div className="flex gap-1.5">
                <Input {...form.register("cuit")} />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={padron.buscando || (cuit ?? "").replace(/\D/g, "").length !== 11}
                  onClick={() => padron.buscar(cuit ?? "")}
                  title="Autocompletar nombre/dirección/perfil fiscal desde ARCA"
                  className="shrink-0"
                >
                  <Search className="h-4 w-4" />
                </Button>
              </div>
              {verificado && cliente!.cuil && cliente!.cuil !== cuit && (
                <p className="text-2xs text-muted-foreground font-mono">
                  CUIL verificado (RENAPER): {cliente!.cuil}
                </p>
              )}
              {padron.motivo && (
                <div className="mt-1 rounded border border-destructive/20 bg-destructive/5 px-2 py-1.5 text-xs text-destructive">
                  {padron.motivo}
                </div>
              )}
              {!padron.motivo && padron.noEncontrado && (
                <p className="text-xs text-muted-foreground">
                  ARCA no tiene datos para este CUIT — cargá a mano.
                </p>
              )}
              {!padron.motivo && padron.inactivo && (
                <div className="mt-1 rounded border border-destructive/20 bg-destructive/5 px-2 py-1.5 text-xs text-destructive">
                  Este CUIT figura inactivo en AFIP.
                </div>
              )}
            </div>
            <div className="space-y-1">
              <Label>Descuento %</Label>
              <Input
                type="number"
                step="0.01"
                {...form.register("descuento", { valueAsNumber: true })}
              />
            </div>
            <div className="space-y-1 col-span-2">
              <Label>Perfil de impuestos</Label>
              <Select
                value={perfil ?? "consumidor_final"}
                onValueChange={(v) => form.setValue("perfil_impuestos", v)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PERFILES.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* #1240: perfiles fiscales personales + productoras vinculadas — solo
              lectura (la gestión real vive en el self-service del cliente y en
              /admin/productoras). Misma tarjeta que el portal
              (ClientePortalHelpers.tsx::FacturacionForm) — BadgeCheck + pill
              default + condición IVA + domicilio, no una lista pelada. */}
          {!!(
            perfilesFiscalesQ.data?.perfiles.length || perfilesFiscalesQ.data?.productoras.length
          ) && (
            <div className="space-y-4">
              {!!perfilesFiscalesQ.data?.perfiles.length && (
                <div className="space-y-2">
                  <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Perfiles fiscales personales
                  </div>
                  {perfilesFiscalesQ.data.perfiles.map((p) => (
                    <div key={p.id} className="rounded-md border hairline p-3">
                      <div className="flex items-center gap-1.5 text-sm font-medium text-ink">
                        <BadgeCheck className="h-3.5 w-3.5 shrink-0 text-verde-ink" />
                        {p.etiqueta || p.razon_social || p.cuit}
                        {p.es_default && (
                          <span className="rounded-full bg-verde/15 px-2 py-0.5 text-3xs font-semibold uppercase tracking-wider text-verde-ink">
                            Default
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {p.cuit} ·{" "}
                        {PERFIL_IMPUESTOS_LABEL[p.perfil_impuestos as PerfilImpuestos] ??
                          p.perfil_impuestos}
                      </div>
                      {p.domicilio_fiscal && (
                        <div className="text-xs text-muted-foreground">{p.domicilio_fiscal}</div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {!!perfilesFiscalesQ.data?.productoras.length && (
                <div className="space-y-2">
                  <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Productoras vinculadas
                  </div>
                  {perfilesFiscalesQ.data.productoras.map((pr) => (
                    <div key={pr.id} className="rounded-md border hairline p-3">
                      <div className="flex items-center gap-1.5 text-sm font-medium text-ink">
                        <Users className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        {pr.nombre || pr.razon_social || pr.cuit}
                        {!pr.cuit && (
                          <span className="rounded-full bg-amber px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide text-ink">
                            Borrador
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {pr.cuit
                          ? `${pr.cuit} · ${
                              PERFIL_IMPUESTOS_LABEL[pr.perfil_impuestos as PerfilImpuestos] ??
                              pr.perfil_impuestos
                            }`
                          : "Sin CUIT — no facturable todavía"}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={mut.isPending}>
              {mut.isPending ? "Guardando…" : editing ? "Guardar cambios" : "Crear cliente"}
            </Button>
          </DialogFooter>
        </form>

        {editing && (
          <div className="border-t hairline pt-4">
            <div className="flex items-baseline justify-between mb-2">
              <h3 className="font-display text-lg text-ink">Historial de pedidos</h3>
              <div className="font-mono text-xs text-muted-foreground">
                {pedidosReales.length} pedidos · {fmtArs(totalGastado)}
                {pedidos.length > pedidosReales.length &&
                  ` · ${pedidos.length - pedidosReales.length} borrador${
                    pedidos.length - pedidosReales.length === 1 ? "" : "es"
                  }`}
              </div>
            </div>

            {pedidosQ.isLoading && <div className="text-sm text-muted-foreground">Cargando…</div>}
            {!pedidosQ.isLoading && pedidos.length === 0 && (
              <div className="text-sm text-muted-foreground">Sin pedidos.</div>
            )}

            <div className="space-y-2">
              {pedidos.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() =>
                    navigate({ to: "/admin/pedidos/$id", params: { id: String(p.id) } })
                  }
                  className="w-full text-left rounded-md border hairline p-3 hover:bg-accent/30 transition-colors"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-mono text-xs text-muted-foreground">
                      {etiquetaPedido(p)}
                    </div>
                    <EstadoBadge estado={p.estado} label={estadoLabel(p.estado)} />
                  </div>
                  <div className="text-sm mt-1">
                    {fmtFecha(p.fecha_desde)} → {fmtFecha(p.fecha_hasta)}
                  </div>
                  {p.equipos && (
                    <div className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                      {p.equipos}
                    </div>
                  )}
                  <div className="flex justify-between mt-1.5 text-sm tabular-nums">
                    <span className="text-muted-foreground">{fmtArs(p.monto_pagado)} pagado</span>
                    <span className="text-ink">{fmtArs(p.monto_total)}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ReadOnlyField({
  label,
  value,
  className = "",
}: {
  label: string;
  value: string | null | undefined;
  className?: string;
}) {
  const [copiado, setCopiado] = useState(false);
  return (
    <div className={`space-y-1 ${className}`}>
      <Label className="text-muted-foreground">{label}</Label>
      <div className="flex items-center gap-2 rounded-md border border-border/50 bg-muted/40 px-3 py-2 text-sm text-ink">
        <span className="flex-1 truncate">{value || "—"}</span>
        {value && (
          <button
            type="button"
            aria-label={`Copiar ${label.toLowerCase()}`}
            title={`Copiar ${label.toLowerCase()}`}
            onClick={() => {
              navigator.clipboard.writeText(value);
              setCopiado(true);
              setTimeout(() => setCopiado(false), 2000);
            }}
            className="shrink-0 text-muted-foreground transition-colors hover:text-ink"
          >
            {copiado ? (
              <Check className="h-3.5 w-3.5 text-verde-ink" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </button>
        )}
      </div>
    </div>
  );
}

function IdentidadVerificada({ cliente }: { cliente: Cliente }) {
  return (
    <div className="rounded-lg border border-verde/30 bg-verde/8 px-3 py-2.5 space-y-1.5">
      <div className="flex items-center gap-1.5 text-verde-ink text-sm font-semibold">
        <ShieldCheck className="h-4 w-4 shrink-0" />
        Identidad verificada
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-ink">
        <div className="col-span-2">
          <span className="text-muted-foreground">Nombre legal: </span>
          {cliente.nombre_legal}
        </div>
        {cliente.dni && (
          <div>
            <span className="text-muted-foreground">DNI: </span>
            <span className="font-mono">{cliente.dni}</span>
          </div>
        )}
        {cliente.cuil && (
          <div>
            <span className="text-muted-foreground">CUIL: </span>
            <span className="font-mono">{cliente.cuil}</span>
          </div>
        )}
        {cliente.fecha_nacimiento_renaper && (
          <div>
            <span className="text-muted-foreground">Nacimiento: </span>
            {cliente.fecha_nacimiento_renaper}
          </div>
        )}
        {cliente.genero_renaper && (
          <div>
            <span className="text-muted-foreground">Género: </span>
            {cliente.genero_renaper === "M"
              ? "Masculino"
              : cliente.genero_renaper === "F"
                ? "Femenino"
                : cliente.genero_renaper}
          </div>
        )}
        {cliente.nacionalidad_renaper && (
          <div>
            <span className="text-muted-foreground">Nacionalidad: </span>
            {cliente.nacionalidad_renaper}
          </div>
        )}
        {cliente.lugar_nacimiento_renaper && (
          <div>
            <span className="text-muted-foreground">Lugar de nacimiento: </span>
            {cliente.lugar_nacimiento_renaper}
          </div>
        )}
        {cliente.estado_civil_renaper && (
          <div>
            <span className="text-muted-foreground">Estado civil: </span>
            {cliente.estado_civil_renaper}
          </div>
        )}
        {cliente.tipo_documento_renaper && (
          <div>
            <span className="text-muted-foreground">Tipo doc.: </span>
            {cliente.tipo_documento_renaper}
          </div>
        )}
        {cliente.emision_documento_renaper && (
          <div>
            <span className="text-muted-foreground">Emisión: </span>
            {cliente.emision_documento_renaper}
          </div>
        )}
        {cliente.vencimiento_documento_renaper && (
          <div>
            <span className="text-muted-foreground">Vencimiento: </span>
            {cliente.vencimiento_documento_renaper}
          </div>
        )}
      </div>
      <div className="text-2xs text-muted-foreground font-mono">
        Verificado {fmtFecha(cliente.dni_validado_at)}
      </div>
    </div>
  );
}

function IdentidadSinVerificar({
  cliente,
  rechequeando,
  onRechequear,
  sessionIdManual,
  onSessionIdManualChange,
  linkVerif,
  copiado,
  onCopiar,
  generando,
  onGenerarLink,
}: {
  cliente: Cliente;
  rechequeando: boolean;
  onRechequear: (sessionIdOverride?: string) => void;
  sessionIdManual: string;
  onSessionIdManualChange: (v: string) => void;
  linkVerif: string | null;
  copiado: boolean;
  onCopiar: () => void;
  generando: boolean;
  onGenerarLink: () => void;
}) {
  return (
    <div className="rounded-lg border hairline px-3 py-2.5 space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <ShieldAlert className="h-4 w-4 shrink-0" />
          Identidad sin verificar
          {cliente.dni_verificacion_estado === "rechazado" && " — rechazada por Didit"}
          {cliente.dni_verificacion_estado === "en_revision" && " — en revisión en Didit"}
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={rechequeando || generando}
              className="shrink-0"
            >
              Acciones
              <ChevronDown className="h-3.5 w-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem
              disabled={rechequeando}
              onClick={() => onRechequear()}
              title="Le vuelve a preguntar a Didit — revisa todo el historial de intentos del cliente, no solo el último."
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              {rechequeando ? "Consultando a Didit…" : "Re-chequear con Didit"}
            </DropdownMenuItem>
            <DropdownMenuItem disabled={generando} onClick={onGenerarLink}>
              <ShieldCheck className="h-3.5 w-3.5" />
              {generando ? "Generando…" : "Generar link de verificación"}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {cliente.dni_verificacion_motivo && (
        <p className="text-xs text-muted-foreground">{cliente.dni_verificacion_motivo}</p>
      )}
      <details className="text-2xs">
        <summary className="cursor-pointer text-muted-foreground select-none">
          ¿Sabés el session_id exacto de Didit? Consultalo directo
        </summary>
        <div className="mt-1.5 flex items-center gap-2">
          <Input
            value={sessionIdManual}
            onChange={(e) => onSessionIdManualChange(e.target.value)}
            placeholder="session_id de Didit (ej. de una sesión sin historial acá)"
            className="flex-1 font-mono text-xs"
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={rechequeando || !sessionIdManual.trim()}
            onClick={() => onRechequear(sessionIdManual.trim())}
            className="shrink-0"
          >
            Consultar
          </Button>
        </div>
      </details>
      {linkVerif && (
        <div className="space-y-1.5">
          <p className="text-xs text-muted-foreground">
            Mandále este link al cliente (WhatsApp, mail, etc.):
          </p>
          <div className="flex items-center gap-2">
            <Input
              readOnly
              value={linkVerif}
              className="flex-1 truncate font-mono text-xs text-ink"
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onCopiar}
              className="shrink-0"
            >
              {copiado ? (
                <Check className="h-3.5 w-3.5 text-verde-ink" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
              {copiado ? "Copiado" : "Copiar"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
