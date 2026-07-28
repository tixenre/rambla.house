/**
 * NuevoTurnoEstudioForm — alta de un turno del Estudio: franja + cliente (o
 * heredado de un pedido) + "qué incluye" (`EstudioIncluyeList`, que absorbe
 * la franja horaria como una fila más) + estado inicial. Extraído de
 * `ReservaDialog` (#1308 — pedido explícito del dueño: "no quiero el modal,
 * en el formulario de los pedidos poder agregar... como si fuera el listado
 * de equipos") para que el alta también pueda vivir INLINE en la página del
 * pedido (`TurnosEstudioSection`), sin popup — y sin sentirse "un form"
 * (segunda vuelta del mismo pedido: "quiero una lista para seleccionar, como
 * con los equipos").
 *
 * Sin Dialog/Section propios — el prop `chrome` decide qué chrome extra le
 * hace falta a cada caller: `ReservaDialog` sigue envolviéndolo en su propio
 * Dialog para el alta "suelta" desde la agenda del Estudio (`chrome="dialog"`,
 * default — cliente picker real + Total propio, sin pedido que herede);
 * `TurnosEstudioSection` lo monta directo en la página del pedido
 * (`chrome="inline"`, con `pedidoVinculado` — sin cliente ni Total, ya se ven
 * arriba/en el rail combinado).
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Spinner } from "@/design-system/ui/spinner";
import { formatARS } from "@/lib/format";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { buildTimeSlots } from "@/lib/estudio-slots";
import {
  estudioAdminApi,
  type Cliente,
  type Equipo,
  type EstudioConfig,
  type Pedido,
} from "@/lib/admin/api";
import { nombreCliente } from "@/lib/cliente-nombre";
import { ClienteAutocomplete } from "@/components/admin/pedido/ClienteAutocomplete";
import { Field } from "./shared";
import { EstudioIncluyeList, type SueltoLocal } from "./EstudioIncluyeList";

function todayYmd(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// Estados con los que se puede CREAR una reserva — mismo universo que el
// backend (`_ESTADOS_ADMIN_CREACION`, services/estudio/commands/reserva.py).
// Un pedido vinculado ya más avanzado (entregado/devuelto/finalizado/
// cancelado) no tiene un análogo válido acá — el turno arranca "confirmado".
const ESTADOS_ADMIN_CREACION = ["solicitado", "confirmado", "retirado"] as const;
type EstadoAlta = (typeof ESTADOS_ADMIN_CREACION)[number];

export function NuevoTurnoEstudioForm({
  estudio,
  pedidoVinculado,
  chrome = "dialog",
  onCreated,
  onCancel,
}: {
  estudio: EstudioConfig;
  /** Alta DESDE la página de un pedido de alquiler normal (#1308): el
   *  cliente se hereda de ese pedido — oculta el picker y manda
   *  `pedido_principal_id` en vez de cliente_id/nombre. También hereda el
   *  ESTADO inicial del pedido principal (oculta el selector — el pedido ya
   *  tiene su propio control de estado, no hace falta uno redundante acá).
   *  Ausente = alta suelta desde la agenda del Estudio, con picker de
   *  cliente y selector de estado propios. */
  pedidoVinculado?: { id: number; clienteNombre: string | null; estado: string };
  /** "dialog" (default, cero cambio para `ReservaDialog`): cliente picker
   *  real + Total propio + Cancelar/Crear turno. "inline" (montado en
   *  `TurnosEstudioSection`): sin cliente (ya se ve arriba, en el pedido) ni
   *  Total (el combinado vive en el rail) — un solo botón "+ Agregar" al pie
   *  de la lista, mismo lugar/estilo que "Agregar línea personalizada" de
   *  Equipos. */
  chrome?: "dialog" | "inline";
  onCreated: (pedido: Pedido) => void;
  onCancel: () => void;
}) {
  const estadoHeredado: EstadoAlta =
    pedidoVinculado &&
    (ESTADOS_ADMIN_CREACION as readonly string[]).includes(pedidoVinculado.estado)
      ? (pedidoVinculado.estado as EstadoAlta)
      : "confirmado";

  const slots = useMemo(
    () => buildTimeSlots(estudio.open_hour, estudio.close_hour, estudio.min_horas || 1),
    [estudio.open_hour, estudio.close_hour, estudio.min_horas],
  );

  const [fecha, setFecha] = useState(todayYmd());
  const [start, setStart] = useState(() => slots[0]?.value ?? "");
  const [horas, setHoras] = useState(estudio.min_horas || 2);
  const [clienteId, setClienteId] = useState<number | null>(null);
  const [clienteNombreElegido, setClienteNombreElegido] = useState<string | null>(null);
  const [clienteNombreLibre, setClienteNombreLibre] = useState("");
  const [conPromo, setConPromo] = useState(false);
  const [pinturaReciente, setPinturaReciente] = useState(false);
  const [sueltos, setSueltos] = useState<SueltoLocal[]>([]);
  const [espacioOverride, setEspacioOverride] = useState("");
  const [estadoAlta, setEstadoAlta] = useState<EstadoAlta>("confirmado");

  const sueltosInput = useMemo(
    () => sueltos.map((s) => ({ equipo_id: s.equipo_id, cantidad: s.cantidad })),
    [sueltos],
  );

  const cotizarParams = useMemo(
    () => ({
      fecha,
      start,
      horas,
      con_promo: conPromo,
      pintura_reciente: pinturaReciente,
      sueltos: sueltosInput,
    }),
    [fecha, start, horas, conPromo, pinturaReciente, sueltosInput],
  );
  const cotizarDebounced = useDebouncedValue(cotizarParams, 400);

  const cotizarQ = useQuery({
    queryKey: ["admin", "estudio", "cotizar", cotizarDebounced],
    enabled: !!fecha && !!start && horas >= (estudio.min_horas || 1),
    queryFn: () => estudioAdminApi.cotizarReserva(cotizarDebounced),
  });

  const mutation = useMutation({
    mutationFn: () =>
      estudioAdminApi.createReserva({
        fecha,
        start,
        horas,
        // Vinculado: el cliente lo resuelve el backend desde el pedido
        // principal — no mandamos cliente_id/nombre de acá (el picker ni
        // siquiera se muestra en ese caso, ver el render).
        ...(pedidoVinculado
          ? { pedido_principal_id: pedidoVinculado.id }
          : {
              cliente_id: clienteId,
              cliente_nombre: clienteId ? null : clienteNombreLibre.trim() || null,
            }),
        con_promo: conPromo,
        pintura_reciente: pinturaReciente,
        sueltos: sueltosInput,
        espacio_monto: espacioOverride.trim() ? Number(espacioOverride) : null,
        estado: pedidoVinculado ? estadoHeredado : estadoAlta,
      }),
    onSuccess: (pedido) => {
      toast.success("Turno creado");
      if (pedido.promo_advertencia) {
        toast.warning("La promo se reservó incompleta", {
          description: pedido.promo_advertencia,
          duration: 7000,
        });
      }
      onCreated(pedido);
    },
    onError: (e) => toast.error("No se pudo guardar", { description: (e as Error).message }),
  });

  const handleAddSuelto = (eq: Equipo) => {
    setSueltos((prev) => {
      const existing = prev.find((s) => s.equipo_id === eq.id);
      if (existing) {
        return prev.map((s) => (s.equipo_id === eq.id ? { ...s, cantidad: s.cantidad + 1 } : s));
      }
      return [
        ...prev,
        {
          equipo_id: eq.id,
          nombre: eq.nombre,
          marca: eq.marca,
          nombre_publico: eq.nombre_publico,
          foto_url: eq.foto_url,
          precio_jornada: eq.precio_jornada,
          cantidad: 1,
        },
      ];
    });
  };
  const handleRemoveSuelto = (equipoId: number) =>
    setSueltos((prev) => prev.filter((x) => x.equipo_id !== equipoId));
  const handleChangeSueltoCantidad = (equipoId: number, cantidad: number) =>
    setSueltos((prev) => prev.map((x) => (x.equipo_id === equipoId ? { ...x, cantidad } : x)));

  const puedeGuardar = !!fecha && !!start && horas >= (estudio.min_horas || 1);
  const cotiz = cotizarQ.data;

  return (
    <div className="space-y-4">
      {chrome === "dialog" &&
        (pedidoVinculado ? (
          <Field label="Cliente" hint="Heredado del pedido al que se vincula este turno.">
            <div className="rounded-md border hairline bg-muted/20 px-2.5 py-1.5 text-sm text-muted-foreground">
              {pedidoVinculado.clienteNombre || "Sin cliente"}
            </div>
          </Field>
        ) : (
          <Field label="Cliente (ficha o texto libre)">
            {clienteId ? (
              <div className="flex items-center gap-2 rounded-md border hairline px-2.5 py-1.5 text-sm">
                <span className="flex-1 truncate">{clienteNombreElegido}</span>
                <button
                  type="button"
                  onClick={() => {
                    setClienteId(null);
                    setClienteNombreElegido(null);
                  }}
                  className="text-muted-foreground hover:text-ink"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ) : (
              <div className="space-y-1.5">
                <ClienteAutocomplete
                  onPick={(c: Cliente) => {
                    setClienteId(c.id);
                    setClienteNombreElegido(nombreCliente(c));
                  }}
                />
                <Input
                  value={clienteNombreLibre}
                  onChange={(e) => setClienteNombreLibre(e.target.value)}
                  placeholder="…o nombre sin ficha (alguien que llamó)"
                />
              </div>
            )}
          </Field>
        ))}

      <EstudioIncluyeList
        estudio={estudio}
        fecha={fecha}
        onChangeFecha={setFecha}
        start={start}
        onChangeStart={setStart}
        horas={horas}
        onChangeHoras={setHoras}
        conPromo={conPromo}
        onTogglePromo={setConPromo}
        pinturaReciente={pinturaReciente}
        onTogglePintura={setPinturaReciente}
        sueltos={sueltos}
        onAddSuelto={handleAddSuelto}
        onRemoveSuelto={handleRemoveSuelto}
        onChangeSueltoCantidad={handleChangeSueltoCantidad}
        espacioOverride={espacioOverride}
        onChangeEspacioOverride={setEspacioOverride}
        cotiz={cotiz}
      />

      {!pedidoVinculado && (
        <Field label="Estado inicial">
          <select
            value={estadoAlta}
            onChange={(e) => setEstadoAlta(e.target.value as EstadoAlta)}
            className="h-9 w-full rounded-md border hairline bg-background px-2 text-sm"
          >
            <option value="solicitado">Solicitado</option>
            <option value="confirmado">Confirmado</option>
            <option value="retirado">Retirado</option>
          </select>
        </Field>
      )}

      {/* Total en vivo — el front no calcula, solo muestra (2026-06-29). Solo
          en modo "dialog": en "inline" el combinado ya vive en el rail del
          pedido, un segundo Total acá sería el mismo tipo de redundancia que
          motivó sacar el grid de fecha/hora/horas. Si no está disponible, el
          aviso SÍ se muestra en los dos modos — es información accionable,
          no un número de plata redundante. */}
      {chrome === "dialog" && (
        <div className="rounded-lg border hairline bg-muted/20 p-3 text-sm">
          {cotizarQ.isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Spinner size="sm" /> Calculando…
            </div>
          ) : cotiz ? (
            <div className="space-y-1">
              <div className="flex justify-between font-semibold text-ink">
                <span>Total</span>
                <span>{formatARS(cotiz.monto_total)}</span>
              </div>
              {!cotiz.espacio_disponible && (
                <p className="mt-1 text-xs text-destructive">
                  El espacio no está disponible: {cotiz.espacio_motivo}
                </p>
              )}
            </div>
          ) : null}
        </div>
      )}
      {chrome === "inline" && cotiz && !cotiz.espacio_disponible && (
        <p className="text-xs text-destructive">
          El espacio no está disponible: {cotiz.espacio_motivo}
        </p>
      )}

      {chrome === "inline" ? (
        <button
          type="button"
          onClick={() => mutation.mutate()}
          disabled={!puedeGuardar || mutation.isPending}
          className="flex w-full items-center justify-center gap-2 rounded-md border border-dashed hairline px-3 py-2.5 text-sm text-muted-foreground transition hover:bg-muted/30 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {mutation.isPending ? <Spinner size="sm" /> : <Plus className="h-4 w-4 shrink-0" />}
          <span>Agregar</span>
        </button>
      ) : (
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            Cancelar
          </Button>
          <Button onClick={() => mutation.mutate()} disabled={!puedeGuardar || mutation.isPending}>
            {mutation.isPending ? <Spinner size="sm" className="mr-1.5" /> : null}
            Crear turno
          </Button>
        </div>
      )}
    </div>
  );
}
