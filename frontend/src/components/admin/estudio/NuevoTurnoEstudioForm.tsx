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
import { useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/design-system/ui/button";
import { IconButton } from "@/design-system/ui/icon-button";
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
  /** Descartar el turno todavía sin crear. En "dialog" es el botón "Cancelar".
   *  En "inline" es un ✕ arriba a la derecha del bloque — y es OPCIONAL a
   *  propósito: cuando el pedido ya tiene turnos cargados, el compose queda
   *  fijo al pie de la lista (como el buscador de "Equipos") y no hay nada que
   *  cerrar; ahí el caller no lo pasa y el ✕ no se muestra, en vez de ofrecer
   *  un botón que no haría nada. */
  onCancel?: () => void;
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
      // Misma tarifa que se persiste al crear (más abajo) — la fila "Espacio" y
      // el Total muestran lo que se va a cobrar, no el precio de lista.
      espacio_monto: espacioOverride.trim() ? Number(espacioOverride) : null,
    }),
    [fecha, start, horas, conPromo, pinturaReciente, sueltosInput, espacioOverride],
  );
  const cotizarDebounced = useDebouncedValue(cotizarParams, 400);

  const cotizarQ = useQuery({
    queryKey: ["admin", "estudio", "cotizar", cotizarDebounced],
    enabled: !!fecha && !!start && horas >= (estudio.min_horas || 1),
    queryFn: () => estudioAdminApi.cotizarReserva(cotizarDebounced),
    // Mismo antiparpadeo que en `ReservaEstudioSection` (ver ahí el porqué):
    // la queryKey cambia con cada edición, así que sin esto la plata de la
    // sección se cae a "…" en cada tecla/toggle mientras viaja el request.
    placeholderData: keepPreviousData,
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

  // ── Alta sin botón (modo inline) ──────────────────────────────────────────
  // "Sacá ese Agregar, que sea como los equipos: si está en el listado, se
  // cotiza". En "Equipos" no hay un botón de confirmar: elegís del buscador y
  // la línea ya cuenta. Acá el equivalente es que el turno se cree SOLO apenas
  // la franja es válida Y el espacio está libre.
  //
  // Tres candados para no crear cualquier cosa:
  //  1. `espacio_disponible` de la cotización — es el MISMO `_centinela_libre`
  //     que valida la creación en el backend, así que en verde el POST no
  //     debería rebotar (y si hay carrera, el 409 la corta igual).
  //  2. la cotización tiene que ser de ESTOS valores, no de los anteriores: el
  //     query va con debounce, y crear con una disponibilidad vieja sería
  //     reservar a ciegas.
  //  3. `intentadoRef` — se intenta UNA vez por combinación de valores: si el
  //     backend rechaza, no se reintenta en loop; recién vuelve a intentar
  //     cuando se cambia algo.
  const claveAlta = JSON.stringify(cotizarParams);
  const cotizacionAlDia = JSON.stringify(cotizarDebounced) === claveAlta && !cotizarQ.isFetching;
  const intentadoRef = useRef<string | null>(null);

  useEffect(() => {
    if (chrome !== "inline") return;
    if (!puedeGuardar || !cotizacionAlDia || !cotiz?.espacio_disponible) return;
    if (mutation.isPending || mutation.isSuccess) return;
    if (intentadoRef.current === claveAlta) return;
    const t = setTimeout(() => {
      intentadoRef.current = claveAlta;
      mutation.mutate();
    }, 600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- dispara por los valores del turno; incluir `mutation` reiniciaría el timer en cada render
  }, [
    chrome,
    puedeGuardar,
    cotizacionAlDia,
    cotiz?.espacio_disponible,
    claveAlta,
    mutation.isPending,
    mutation.isSuccess,
  ]);

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
        // El ✕ que descarta el turno sin crear. Va acá arriba, no al pie: el
        // pie es "+ Agregar" (crear), y meter la salida al lado de la
        // confirmación invita a errarle. Sin esto, abrir "Agregar un turno del
        // Estudio" era un camino de ida — no había forma de volver al estado
        // vacío (lo reportó el dueño: "ahora no puedo quitar el turno").
        accion={
          chrome === "inline" && onCancel ? (
            <IconButton
              aria-label="Descartar este turno"
              title="Descartar este turno"
              onClick={onCancel}
              className="text-muted-foreground hover:text-destructive hover:bg-destructive/10"
            >
              <X className="h-4 w-4" />
            </IconButton>
          ) : undefined
        }
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
      {/* En "inline" no hay botón de crear (el turno se crea solo): lo único
          que va al pie es el motivo por el que TODAVÍA no se creó. */}
      {chrome === "inline" &&
        (cotiz && !cotiz.espacio_disponible ? (
          <p className="text-xs text-destructive">
            El espacio no está disponible: {cotiz.espacio_motivo}. Elegí otra franja.
          </p>
        ) : mutation.isPending ? (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Spinner size="sm" /> Agregando el turno…
          </p>
        ) : null)}

      {chrome === "dialog" && (
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
