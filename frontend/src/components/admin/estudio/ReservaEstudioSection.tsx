/**
 * ReservaEstudioSection — franja/tarifa/promo/sueltos de un turno YA
 * EXISTENTE del Estudio (`tipo='estudio'`). Fase 2, #1308: extraída del modo
 * edición de `ReservaDialog` para que la página del pedido pueda administrar
 * el turno inline, sin un diálogo aparte — una sola forma de editar un
 * turno. El modo alta (cliente + estado inicial) sigue solo en
 * `ReservaDialog`, no reusa esta sección.
 *
 * Autocontenida (estado + cotización en vivo + guardado): hidrata desde
 * `pedido`, cotiza vía `GET /admin/estudio/reservas/cotizar` y guarda con
 * `PATCH /admin/estudio/reservas/{id}` — mismos endpoints que el diálogo, sin
 * superficie nueva. El front no calcula plata (MEMORIA 2026-06-29): el
 * desglose se pide en vivo y solo se muestra. El listado "qué incluye"
 * (Espacio/Pack/Pintura/sueltos) vive en `EstudioIncluyeList`, compartido con
 * el modo alta de `ReservaDialog` — incluida la franja horaria, que
 * `EstudioIncluyeList` absorbe como parte de la fila "Espacio" (#1308: ya no
 * hay un grid Fecha/Hora/Horas aparte acá, quedaba duplicado con el del alta).
 *
 * `cotizar`/`guardar` (#1308 Fase 4.4, rediseño "turno como ítem") son
 * INYECTABLES: por default pegan contra el turno STANDALONE
 * (`GET .../reservas/cotizar` + `PATCH .../reservas/{pedido.id}`, el
 * comportamiento de siempre, cero cambio para `ReservaDialog`/la página de un
 * pedido `tipo='estudio'`). Un turno EMBEBIDO (grupo de ítems de OTRO pedido,
 * `alquiler_turnos_estudio`) no comparte id con su contenedor — el caller
 * (`TurnoEmbebidoCard`, `TurnosEstudioSection.tsx`) inyecta versiones que
 * pegan a `POST/PATCH .../alquileres/{contenedorId}/turnos-estudio[/{turnoId}]`
 * y arma un `pedido` SINTÉTICO (franja + ítems propios del turno, filtrados
 * de `contenedor.items` por `turno_estudio_id`) — la sección en sí no sabe ni
 * le importa cuál mecanismo es, solo pide/guarda por las funciones que le dan.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Clapperboard } from "lucide-react";
import { toast } from "sonner";

import { Section } from "@/design-system/composites/Section";
import { Button } from "@/design-system/ui/button";
import { Spinner } from "@/design-system/ui/spinner";
import { SaveIndicator } from "@/components/admin/pedido/PedidoPageHelpers";
import { TotalSeccion } from "@/components/admin/pedido/TotalSeccion";
import { DescuentoControl, type DescuentoManual } from "@/components/admin/pedido/DescuentoControl";
import { formatARS } from "@/lib/format";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { espacioOverrideInicial } from "@/lib/estudio-slots";
import {
  estudioAdminApi,
  type Equipo,
  type EstudioConfig,
  type EstudioCotizacion,
  type EstudioReservaUpdateInput,
  type Pedido,
} from "@/lib/admin/api";
import { EstudioIncluyeList, type SueltoLocal } from "./EstudioIncluyeList";

// Debe coincidir con `NOMBRE_ITEM_PINTURA_RECIENTE`
// (backend/services/estudio/commands/reserva.py) — mismo criterio que
// ReservaDialog para detectar la línea al hidratar.
const NOMBRE_ITEM_PINTURA_RECIENTE = "Recién pintado";

function horasEntre(desde?: string | null, hasta?: string | null, fallback = 2): number {
  if (!desde || !hasta) return fallback;
  const ms = new Date(hasta).getTime() - new Date(desde).getTime();
  return Math.max(1, Math.round(ms / 3_600_000));
}

/** El override inicial del precio del Espacio — factorizado para poder
 *  usarse tanto en el `useState` inicial de `espacioOverride` como en la
 *  hidratación de abajo (misma fórmula, un solo lugar). Que el `useState`
 *  arranque YA con este valor (en vez de `""`) es lo que evita una carrera
 *  real: si arranca vacío y la hidratación lo cambia recién en su primer
 *  efecto, el autosave — que registra como "línea de base" el PRIMER
 *  `payloadKey` que ve — toma el `""` como base y lee el cambio de la
 *  hidratación como una edición real del admin, disparando un PATCH
 *  espontáneo apenas carga la página. Con un turno cuyo descuento YA está
 *  horneado en su `precio_jornada` (el caso normal tras usar el ledger
 *  combinado de `TurnosEstudioSection`) esto pasaba en CADA carga, no solo
 *  la primera vez — detectado en vivo (Postgres real, dos turnos
 *  autoguardándose a la vez) como un deadlock real entre las dos tarjetas. */
function espacioOverrideDe(pedido: PedidoParaReserva, estudio: EstudioConfig): string {
  const centinela = estudio.equipo_id;
  const horasIniciales = horasEntre(pedido.fecha_desde, pedido.fecha_hasta, estudio.min_horas || 2);
  const centinelaItem = pedido.items.find((it) => it.equipo_id === centinela);
  const autoEsperado = (estudio.precio_hora || 0) * horasIniciales;
  return espacioOverrideInicial(centinelaItem?.precio_jornada, autoEsperado);
}

/** Lo mínimo que la sección necesita del pedido para hidratarse — un turno
 *  STANDALONE (`Pedido` completo) y uno EMBEBIDO (objeto sintético armado por
 *  `TurnoEmbebidoCard`) satisfacen esto por igual. */
type PedidoParaReserva = Pick<
  Pedido,
  | "id"
  | "fecha_desde"
  | "fecha_hasta"
  | "items"
  | "descuento_pct"
  | "descuento_manual_tipo"
  | "descuento_manual_monto"
>;

type CotizarReservaFn = (
  params: Omit<Parameters<typeof estudioAdminApi.cotizarReserva>[0], "pedido_id">,
) => ReturnType<typeof estudioAdminApi.cotizarReserva>;

/** Estado de la cotización de UN turno, reportado hacia arriba vía `onCotizacion`
 *  (ver el prop, más abajo) — lo consume `TurnosEstudioSection` para armar el
 *  ledger COMBINADO de varios turnos. `undefined` no alcanza para distinguir
 *  "todavía no cargó" de "falló": sin esa distinción, un turno que erroró podía
 *  desaparecer en silencio de la suma combinada en vez de marcarla como no
 *  confiable. */
export type CotizTurnoEstado =
  | { status: "cargando" }
  | { status: "error" }
  | { status: "ok"; cotiz: EstudioCotizacion };

export function ReservaEstudioSection({
  pedido,
  estudio,
  accion,
  anidada = false,
  onSaved,
  cotizar,
  guardar,
  mostrarTotal = true,
  descuentoPctOverride,
  onCotizacion,
}: {
  pedido: PedidoParaReserva;
  estudio: EstudioConfig;
  /** El ✕ que saca el turno del pedido. Dónde cae depende de `anidada`: en el
   *  encabezado propio, o —si no lo hay— arriba a la derecha de la banda de
   *  tiempo, el mismo lugar donde lo tiene un turno todavía sin crear. */
  accion?: ReactNode;
  /** Montada DENTRO de "Turnos del Estudio" (la página de un pedido de
   *  alquiler): sin encabezado propio. Con él se veían dos títulos pegados
   *  diciendo lo mismo, con el mismo ícono — "Turnos del Estudio" arriba y
   *  "Reserva del Estudio" adentro (lo reportó el dueño: "esto lo veo
   *  redundante"). El recuadro queda: separa un turno del siguiente. */
  anidada?: boolean;
  onSaved?: (pedido: Pedido) => void;
  /** Ver el docstring del módulo — default: turno STANDALONE. */
  cotizar?: CotizarReservaFn;
  guardar?: (payload: EstudioReservaUpdateInput) => Promise<Pedido>;
  /** `false` cuando el caller arma un ledger COMBINADO de varios turnos (p.ej.
   *  `TurnosEstudioSection` con 2+ turnos) — oculta SOLO el `TotalSeccion`
   *  propio; el spinner/error de cotización y el aviso "espacio no disponible"
   *  siguen siempre visibles (son señales operativas de ESTE turno, no ledger). */
  mostrarTotal?: boolean;
  /** Cuando viene, reemplaza el % de descuento propio del turno para la
   *  cotización/el guardado — lo usa el ledger combinado para aplicar el MISMO
   *  % a cada turno. El estado/hidratación interna de `descuento` sigue
   *  intacta, simplemente deja de leerse mientras el override está activo. */
  descuentoPctOverride?: number;
  /** Reporta el estado de la cotización YA calculada acá adentro — no agrega
   *  ningún cálculo nuevo, solo relee `cotizarQ` para que el caller pueda sumar
   *  el bruto/descuento/total de varios turnos sin recalcular nada él mismo. */
  onCotizacion?: (estado: CotizTurnoEstado) => void;
}) {
  // `false` = un turno EMBEBIDO (el caller inyectó `cotizar`/`guardar`) — ver
  // el uso en `mutation.onSuccess` abajo.
  const esStandalone = !guardar;
  const cotizarFn: CotizarReservaFn =
    cotizar ?? ((params) => estudioAdminApi.cotizarReserva({ ...params, pedido_id: pedido.id }));
  const guardarFn = guardar ?? ((payload) => estudioAdminApi.updateReserva(pedido.id, payload));
  const qc = useQueryClient();

  const [fecha, setFecha] = useState(() => pedido.fecha_desde?.slice(0, 10) ?? "");
  const [start, setStart] = useState(() => pedido.fecha_desde?.slice(11, 16) ?? "");
  const [horas, setHoras] = useState(() =>
    horasEntre(pedido.fecha_desde, pedido.fecha_hasta, estudio.min_horas || 2),
  );
  const [conPromo, setConPromo] = useState(false);
  const [pinturaReciente, setPinturaReciente] = useState(false);
  const [sueltos, setSueltos] = useState<SueltoLocal[]>([]);
  const [espacioOverride, setEspacioOverride] = useState(() => espacioOverrideDe(pedido, estudio));
  // Descuento PROPIO del turno (#1308, decisión del dueño): aparte del de los
  // equipos, editable acá adentro. Persiste en las columnas de descuento manual
  // que la fila de `alquileres` ya tiene — un turno ES un pedido, no hace falta
  // una columna paralela (ver `total_turno_estudio` en el backend).
  const [descuento, setDescuento] = useState<DescuentoManual>({
    tipo: "pct",
    pct: 0,
    monto: 0,
  });

  // Hidratación — solo al cambiar de pedido, no en cada tecla (mismo criterio
  // que `ReservaDialog`).
  useEffect(() => {
    const centinela = estudio.equipo_id;
    const promoId = estudio.promo_combo_id;
    const otros = pedido.items.filter((it) => it.equipo_id !== centinela);
    setConPromo(!!promoId && otros.some((it) => it.equipo_id === promoId));
    setPinturaReciente(
      otros.some((it) => it.equipo_id === null && it.nombre_libre === NOMBRE_ITEM_PINTURA_RECIENTE),
    );
    setSueltos(
      otros
        .filter((it) => it.equipo_id !== null && it.equipo_id !== promoId)
        .map((it) => ({
          equipo_id: it.equipo_id!,
          nombre: it.nombre,
          marca: it.marca,
          nombre_publico: it.nombre_publico,
          foto_url: it.foto_url ?? null,
          precio_jornada: it.precio_jornada,
          cantidad: it.cantidad,
        })),
    );
    const horasActuales = horasEntre(
      pedido.fecha_desde,
      pedido.fecha_hasta,
      estudio.min_horas || 2,
    );
    setEspacioOverride(espacioOverrideDe(pedido, estudio));
    setFecha(pedido.fecha_desde?.slice(0, 10) ?? "");
    setStart(pedido.fecha_desde?.slice(11, 16) ?? "");
    setHoras(horasActuales);
    setDescuento({
      tipo: pedido.descuento_manual_tipo === "monto" ? "monto" : "pct",
      pct: pedido.descuento_pct ?? 0,
      monto: pedido.descuento_manual_monto ?? 0,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- solo al cambiar de pedido, no en cada campo
  }, [pedido.id]);

  const sueltosInput = useMemo(
    () => sueltos.map((s) => ({ equipo_id: s.equipo_id, cantidad: s.cantidad })),
    [sueltos],
  );

  // Memoizado: un objeto nuevo sin memoizar en cada render (p.ej. un literal
  // `override != null ? {...} : descuento` inline) rompería el debounce de
  // `cotizarDebounced` de abajo, que compara por REFERENCIA — reiniciaría el
  // timer de 400ms en cada render del padre, no solo cuando el % realmente
  // cambia.
  const descuentoEfectivo = useMemo(
    () =>
      descuentoPctOverride != null
        ? { tipo: "pct" as const, pct: descuentoPctOverride, monto: 0 }
        : descuento,
    [descuentoPctOverride, descuento],
  );

  const cotizarParams = useMemo(
    () => ({
      fecha,
      start,
      horas,
      con_promo: conPromo,
      pintura_reciente: pinturaReciente,
      sueltos: sueltosInput,
      // La MISMA tarifa que se va a persistir al guardar (línea de abajo) —
      // así lo que muestra la fila "Espacio" y el Total es lo que se cobra, no
      // el precio de lista.
      espacio_monto: espacioOverride.trim() ? Number(espacioOverride) : null,
      descuento_pct: descuentoEfectivo.pct,
      descuento_manual_tipo: descuentoEfectivo.tipo,
      descuento_manual_monto: descuentoEfectivo.monto,
    }),
    [
      fecha,
      start,
      horas,
      conPromo,
      pinturaReciente,
      sueltosInput,
      espacioOverride,
      descuentoEfectivo,
    ],
  );
  const cotizarDebounced = useDebouncedValue(cotizarParams, 400);

  const cotizarQ = useQuery({
    // `pedido.id` (aparte de `cotizarDebounced`, que YA NO trae el
    // pedido_id/exclude_turno_estudio_id — eso lo agrega `cotizarFn`) separa
    // la cache entre turnos hermanos montados a la vez (varios turnos en
    // "Turnos del Estudio") que por un instante compartan los mismos
    // fecha/start/horas/sueltos — sin esto, dos turnos recién creados con los
    // mismos defaults pisarían la cotización en pantalla del otro.
    queryKey: ["admin", "estudio", "cotizar", pedido.id, cotizarDebounced],
    queryFn: () => cotizarFn(cotizarDebounced),
    enabled: !!fecha && !!start && horas >= (estudio.min_horas || 1),
    // Sin esto los números PESTAÑEAN al tocar cualquier cosa (lo reportó el
    // dueño al agregar/sacar un add-on): cada cambio arma una queryKey NUEVA,
    // así que `data` vuelve a `undefined` mientras viaja el request y toda la
    // plata de la sección (Espacio, el "+ $X" del add-on, el Total) se cae a
    // "…" y vuelve. Con `keepPreviousData` se muestra el último valor bueno
    // hasta que llega el nuevo — el MISMO patrón que ya usa `useCotizacion`
    // para el pedido (lib/cotizacion.ts).
    placeholderData: keepPreviousData,
  });

  // Lo que se persiste, serializado — la unidad de comparación del autosave.
  const payload = useMemo(
    () => ({
      fecha,
      start,
      horas,
      con_promo: conPromo,
      pintura_reciente: pinturaReciente,
      sueltos: sueltosInput,
      espacio_monto: espacioOverride.trim() ? Number(espacioOverride) : null,
      descuento_pct: descuentoEfectivo.pct,
      descuento_manual_tipo: descuentoEfectivo.tipo,
      descuento_manual_monto: descuentoEfectivo.monto,
    }),
    [
      fecha,
      start,
      horas,
      conPromo,
      pinturaReciente,
      sueltosInput,
      espacioOverride,
      descuentoEfectivo,
    ],
  );
  const payloadKey = useMemo(() => JSON.stringify(payload), [payload]);
  /** Último payload que la base ya tiene. `null` = recién hidratado, todavía no
   *  sabemos cuál es (lo fija el primer pase del efecto de autosave). */
  const guardadoRef = useRef<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => guardarFn(payload),
    onSuccess: (actualizado) => {
      guardadoRef.current = payloadKey;
      if (actualizado.promo_advertencia) {
        toast.warning("La promo se reservó incompleta", {
          description: actualizado.promo_advertencia,
          duration: 7000,
        });
      }
      // El PATCH ya devolvió el turno actualizado: se ESCRIBE en la caché en
      // vez de invalidar. Invalidar disparaba un GET del pedido entero por cada
      // guardado —y como el caller invalidaba la misma key, salían dos— y con
      // él un re-render de toda la pantalla: eso es lo que se sentía como que
      // "se recarga la página". SOLO para un turno STANDALONE: ahí `pedido.id`
      // es el id REAL de la query `["admin","pedido",id]` que ve su propia
      // página. Para un turno EMBEBIDO `pedido.id` es el id SINTÉTICO del
      // turno (ver el docstring del módulo) — escribir acá pisaría una cache
      // key que no corresponde a ningún pedido real (o, peor, una que sí, por
      // coincidencia numérica). Ese caso lo resuelve el CALLER (`onSaved`,
      // `TurnoEmbebidoCard`), que sabe cuál es el id del pedido contenedor.
      if (esStandalone) qc.setQueryData(["admin", "pedido", pedido.id], actualizado);
      // Estas son de OTRAS pantallas (agenda/lista del Estudio): no están
      // montadas acá, así que invalidarlas no dispara ningún fetch ahora —
      // solo marca que están viejas para cuando se abran.
      qc.invalidateQueries({ queryKey: ["admin", "estudio", "reservas"] });
      qc.invalidateQueries({ queryKey: ["admin", "estudio", "agenda"] });
      // El TOTAL COMBINADO del rail (pedido + turnos, con el IVA sobre el neto
      // de los dos) lo resuelve `/api/cotizar`, cacheado por el BODY de la
      // cotización — que solo describe al pedido principal. Editar este turno
      // no cambia ese body, así que sin invalidar el rail se quedaba mostrando
      // el total viejo hasta 30s (`staleTime`): medido en el navegador, sumar
      // un add-on de $35.000 dejaba el Total en $435.600 en vez de $478.550.
      qc.invalidateQueries({ queryKey: ["cotizar"] });
      onSaved?.(actualizado);
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

  const cotiz = cotizarQ.data;
  const puedeGuardar = !!fecha && !!start && horas >= (estudio.min_horas || 1);

  // Relee lo que `cotizarQ` YA calculó — no agrega ningún cómputo nuevo, solo
  // lo relaya hacia el caller (el ledger combinado de `TurnosEstudioSection`).
  useEffect(() => {
    if (!onCotizacion) return;
    if (cotizarQ.isError) onCotizacion({ status: "error" });
    else if (cotiz) onCotizacion({ status: "ok", cotiz });
    else onCotizacion({ status: "cargando" });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `onCotizacion` es responsabilidad del caller memoizarlo (bail-out); incluirlo acá no cambia qué se reporta
  }, [cotiz, cotizarQ.isError]);

  // Autosave con debounce — TODO lo demás del pedido se guarda solo (decisión
  // del dueño: "todo en el pedido se autosalva, creo que es mejor así"), así
  // que un botón "Guardar cambios" acá era la única cosa de la pantalla que
  // había que acordarse de apretar. Mismo patrón que `usePedidoDraft`: se
  // compara contra lo último que la base confirmó y se dispara pasado el
  // debounce. El primer pase tras hidratar solo REGISTRA el estado actual (no
  // guarda): venía de la base, ya está guardado.
  useEffect(() => {
    if (!puedeGuardar) return;
    if (guardadoRef.current === null) {
      guardadoRef.current = payloadKey;
      return;
    }
    if (guardadoRef.current === payloadKey) return;
    const t = setTimeout(() => mutation.mutate(), 700);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- autosave con debounce: dispara por el payload; incluir `mutation` reiniciaría el timer en cada render
  }, [payloadKey, puedeGuardar]);

  const saveStatus = mutation.isPending
    ? "saving"
    : mutation.isError
      ? "error"
      : guardadoRef.current !== null && guardadoRef.current !== payloadKey
        ? "dirty"
        : "saved";

  // Sin `mostrarTotal`, el `SaveIndicator` de error que vivía como `trailing`
  // del `TotalSeccion` (más abajo) se queda sin lugar — se suma acá, al lado
  // de la ✕, para no perder la señal de "esta tarjeta puntual no se guardó"
  // cuando el ledger combinado es el único que se ve.
  const accionConEstado = mostrarTotal ? (
    accion
  ) : (
    <div className="flex items-center gap-1.5">
      <SaveIndicator status={saveStatus} onlyError />
      {accion}
    </div>
  );

  // Con `mostrarTotal=false` (ledger combinado en el caller) el `TotalSeccion`
  // de acá abajo no se dibuja — pero el spinner/error de la cotización y el
  // aviso de "espacio no disponible" son señales de ESTE turno puntual y
  // siguen siempre visibles. Sin este gate explícito, además, un turno sin
  // nada que mostrar (todo bien, `mostrarTotal=false`) dejaba un divisor
  // (`border-t-2 pt-4`) vacío al pie de la tarjeta, sin motivo.
  const hayAlgoAbajo =
    cotizarQ.isLoading ||
    cotizarQ.isError ||
    (!!cotiz && (mostrarTotal || !cotiz.espacio_disponible));

  return (
    <Section
      variant="card"
      tone="elevated"
      // Anidada: sin ícono ni título → el `Section` no dibuja encabezado (solo
      // el recuadro), y el ✕ baja a la banda de tiempo.
      icon={anidada ? undefined : Clapperboard}
      title={anidada ? "" : "Reserva del Estudio"}
      actions={anidada ? undefined : accionConEstado}
    >
      <div className="space-y-4">
        <EstudioIncluyeList
          accion={anidada ? accionConEstado : undefined}
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

        {/* Descuento + total del turno, separados de "Qué incluye" por una
            línea más marcada — misma frontera (`border-t-2 border-ink/15`)
            que "Alquiler de equipos" usa entre sus equipos y su parte
            contable (pedido del dueño: "una línea horizontal más ancha para
            separar los equipos de la parte contable"); las dos secciones son
            gemelas, la frontera tiene que leerse igual en las dos. */}
        {hayAlgoAbajo && (
          <div className="border-t-2 border-ink/35 pt-4">
            {/* Total en vivo — el front no calcula, solo muestra (2026-06-29).
                Sin wrapper propio: `TotalSeccion` ya pone su propio recuadro;
                acá arriba había un `<div>` viejo con ESA MISMA caja, sobrante
                de antes de extraer el componente — quedaba una caja adentro de
                otra caja (lo vio el dueño: "veo doble recuadro"). El descuento
                propio del turno (#1308) va COMO PROP, dentro de la fila
                "Descuento del turno" del ledger — antes era un bloque suelto
                arriba, o sea el control y su resultado separados diciendo lo
                mismo ("¿podemos unificar esos dos campos? ... y el modificador
                de descuento, in place"). Es la MISMA pieza que usa "Alquiler de
                equipos", no una copia. Con `mostrarTotal=false` (ledger
                combinado de varios turnos, ver `TurnosEstudioSection`) este
                bloque se apaga — el aviso de "espacio no disponible" de más
                abajo sigue mostrándose igual, es independiente del ledger. */}
            {cotizarQ.isLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Spinner size="sm" /> Calculando…
              </div>
            ) : cotizarQ.isError ? (
              // Antes `cotizarQ.isError` no se leía acá: un fallo de red dejaba
              // el bloque mostrando el ÚLTIMO total bueno (`keepPreviousData`)
              // sin ningún aviso de que ya no es de fiar — el Total del turno
              // podía estar mintiendo en silencio.
              <div className="flex flex-wrap items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-2 text-xs text-destructive">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>
                  No se pudo calcular el total del turno — no es confiable hasta recalcular.
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  className="ml-auto"
                  onClick={() => void cotizarQ.refetch()}
                >
                  Reintentar
                </Button>
              </div>
            ) : cotiz ? (
              <>
                {mostrarTotal && (
                  <TotalSeccion
                    bruto={cotiz.bruto ?? 0}
                    descuentoLabel="Descuento del turno"
                    descuentoPct={cotiz.descuento_pct}
                    descuentoMonto={cotiz.descuento_monto}
                    total={cotiz.monto_total}
                    descuentoControl={
                      <DescuentoControl
                        value={descuento}
                        onChange={setDescuento}
                        maxMonto={cotiz.bruto_descontable ?? cotiz.monto_total ?? 0}
                        efectivoPct={cotiz.descuento_pct ?? 0}
                        efectivoMonto={cotiz.descuento_monto ?? 0}
                        disabled={mutation.isPending}
                      />
                    }
                    // onlyError: el indicador general de arriba a la derecha ya
                    // cubre "está todo guardado" — repetir "Guardado"/"Sin
                    // guardar"/"Guardando…" acá abajo leía como el mismo aviso,
                    // dos veces (el dueño lo notó dos veces seguidas: primero por
                    // "Guardado" en reposo, después por "Sin guardar" mientras
                    // tipeaba). Son técnicamente autosaves DISTINTOS (este
                    // PATCHea el turno, no el pedido) — pero esas transiciones
                    // duran bien menos de un segundo, no hace falta narrarlas.
                    // Lo único que el general NO puede avisar es un error real de
                    // ESTE PATCH, así que es lo único que sigue en pantalla.
                    trailing={<SaveIndicator status={saveStatus} onlyError />}
                  />
                )}
                {!cotiz.espacio_disponible && (
                  <p className="text-xs text-destructive">
                    El espacio no está disponible: {cotiz.espacio_motivo}
                  </p>
                )}
              </>
            ) : null}
          </div>
        )}
      </div>
    </Section>
  );
}
