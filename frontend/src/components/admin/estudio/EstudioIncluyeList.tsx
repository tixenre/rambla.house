/**
 * EstudioIncluyeList — el turno en dos bloques, con la MISMA forma que la
 * sección "Alquiler" del pedido para que se lean como hermanas: arriba la
 * banda de tiempo (cuándo empieza y cuánto dura — espejo de la píldora
 * "Retiro → Devolución"), abajo "qué incluye" como UNA sola lista —Espacio
 * (siempre, con su tarifa editable) + Pack + Recién pintado + Equipos sueltos,
 * cada uno una fila, incluido lo que TODAVÍA NO está agregado (atenuado, bajo
 * su rótulo, con un + en la misma columna donde lo incluido tiene su ✕)— y el
 * buscador de equipos como última fila. Reemplaza los switches sueltos + el
 * campo de override separado + el desglose por-componente duplicado + los
 * chips dashed de add-on: una sola forma de ver y tocar cada línea, con su
 * precio al lado (el front no calcula plata, MEMORIA 2026-06-29: los precios
 * vienen de `cotiz` —o del config del Estudio para lo disponible—, resueltos
 * por el backend).
 *
 * El buscador de sueltos replica la misma lógica que "Equipos" del pedido:
 * SIEMPRE visible, sin colapsar detrás de ningún chip/toggle (el dueño lo
 * pidió así explícitamente, viendo esa sección como referencia). NO es
 * redundante con "Equipos": ese reserva/cobra por el rango de días completo,
 * un suelto reserva/cobra solo la franja horaria puntual del turno (cargo
 * fijo, stock duro) — y en una reserva standalone del Estudio es la ÚNICA
 * vía de sumar equipo.
 *
 * Historia de fecha/hora/horas (#1308, tres vueltas del mismo pedido): vivían
 * en un grid de 3 columnas suelto, duplicado en cada caller → se plegaron
 * adentro de la fila "Espacio" para que la lista fuera una sola cosa → y ahora
 * salieron de la fila a la `BandaFranja`, que NO es aquel grid: es una banda
 * con la forma de la del alquiler, dentro de la misma sección ("separar las
 * fechas a un coso arriba, como en el rental, y así visualmente están
 * hermanados"). Sigue habiendo UNA sola definición, compartida por los dos
 * callers.
 *
 * Presentacional puro — sin query/mutation propias. Compartido por
 * `ReservaEstudioSection` (editar) y `NuevoTurnoEstudioForm` (alta): cada uno
 * maneja su propio estado y le pasa acá los callbacks, así las dos
 * superficies se ven y comportan igual sin duplicar el layout.
 */
import { useMemo, type ReactNode } from "react";
import { Clapperboard, Package, Paintbrush, Plus, X } from "lucide-react";

import { IconButton } from "@/design-system/ui/icon-button";
import { Input } from "@/design-system/ui/input";
import { QtyInput } from "@/design-system/ui/qty-input";
import { cn } from "@/lib/utils";
import { formatARS } from "@/lib/format";
import { buildTimeSlots } from "@/lib/estudio-slots";
import { type Equipo, type EstudioConfig, type EstudioCotizacion } from "@/lib/admin/api";
import { EquipoComboSearch } from "@/components/admin/pedido/EquipoComboSearch";
import { EquipoThumb } from "@/components/admin/pedido/EquipoThumb";
import type { DraftItem } from "@/components/admin/pedido/usePedidoDraft";
import { Field } from "./shared";

/** Solo lo que la UI necesita mostrar de un suelto agregado — no un `Equipo`
 *  completo (evita fabricar campos que no vienen ni del picker ni del
 *  detalle del pedido, como `dueno`/`visible_catalogo`). Fuente única —
 *  antes duplicado byte a byte en `ReservaDialog` y `ReservaEstudioSection`. */
export type SueltoLocal = {
  equipo_id: number;
  nombre: string;
  marca: string | null;
  nombre_publico?: string | null;
  foto_url: string | null;
  precio_jornada: number | null;
  cantidad: number;
};

/** ✕ de una línea incluida — mismo `IconButton` del DS que usa el ✕ de una
 *  fila de "Equipos" (antes acá era un `<button>` pelado de 16px: otra forma de
 *  hacer lo mismo, con un tap target mucho más chico). */
function BotonQuitar({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <IconButton
      aria-label={`Quitar ${label}`}
      onClick={onClick}
      className="shrink-0 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
    >
      <X className="h-4 w-4" />
    </IconButton>
  );
}

/** + de una línea todavía NO incluida — ocupa exactamente la misma columna que
 *  el ✕, así una fila disponible y una incluida son la misma fila con la acción
 *  invertida (y el ojo no tiene que re-aprender el layout). */
function BotonSumar({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <IconButton
      aria-label={`Agregar ${label}`}
      onClick={onClick}
      className="shrink-0 text-muted-foreground hover:text-ink"
    >
      <Plus className="h-4 w-4" />
    </IconButton>
  );
}

/** Cuadrito de identidad de una fila sin foto (espacio / pack / pintura) — mismo
 *  tamaño y lenguaje que el `EquipoThumb` de un suelto y que el placeholder de
 *  línea libre de `ItemRow`, para que la columna izquierda alinee en todas. */
function FilaIcono({ icon: Icon }: { icon: typeof Package }) {
  return (
    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-dashed hairline text-muted-foreground/60">
      <Icon className="h-4 w-4" />
    </div>
  );
}

/**
 * Esqueleto ÚNICO de fila de "qué incluye", calcado del `ItemRow` de la sección
 * "Equipos" del pedido (pedido del dueño: "el turno y los add-on del turno, ¿se
 * pueden ver como los equipos? así en una sola línea, más legible"). Antes cada
 * clase de fila (espacio / pack / pintura / suelto) armaba su propio layout: el
 * thumb del suelto era 8×8 y el resto no tenía, el subtotal caía en una posición
 * distinta en cada una (en el suelto incluso ANTES de la cantidad, invertido
 * respecto de Equipos) y el espacio directamente no mostraba el suyo. Nada
 * alineaba verticalmente → se leía como un formulario, no como una lista.
 *
 * La clave de la alineación son las DOS columnas finales de ancho fijo
 * (subtotal + hueco de la acción): como el bloque de controles va
 * `justify-end`, los subtotales quedan a la misma altura y en la misma columna
 * aunque cada fila tenga controles distintos adelante.
 *
 * Sirve para las DOS clases de fila (#1308, pedido del dueño: "el pack, el
 * pintado y un equipo, ¿los podemos hacer como una lista? así como está el
 * botón del +, pero en lista, más prolijo"): lo que YA está incluido (✕ para
 * sacarlo) y lo que se PUEDE sumar (`atenuado`, + para agregarlo). Antes lo
 * disponible eran dos chips dashed sueltos debajo de la lista y un buscador a
 * ancho completo más abajo — tres lenguajes visuales distintos para lo mismo, y
 * con la lista casi vacía costaba ver qué era parte del turno y qué no.
 */
function FilaIncluye({
  icono,
  titulo,
  controles,
  subtotal,
  accion,
  atenuado = false,
}: {
  icono: ReactNode;
  titulo: ReactNode;
  /** Lo editable propio de esta fila (franja, cantidad, precio…). */
  controles?: ReactNode;
  /** Plata de la línea, ya resuelta por el backend. `undefined` → "…". */
  subtotal?: number;
  /** Botón de la última columna (✕ para quitar, + para sumar). Sin acción, la
   *  columna queda vacía pero PRESENTE (el espacio no se puede quitar) — si no,
   *  su subtotal se correría respecto del resto. */
  accion?: ReactNode;
  /** Fila todavía no incluida en el turno: se atenúa y su plata es el precio de
   *  lista (cuánto sumaría), no una línea ya cotizada. */
  atenuado?: boolean;
}) {
  return (
    <li
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-2 px-2.5 py-2",
        // Lo disponible se lee como "todavía no": fondo hundido + todo el
        // contenido atenuado. El gris del texto solo no alcanzaba — el dueño
        // seguía viendo las dos filas como incluidas ("parece que siempre
        // está"), así que el estado se marca con VARIAS señales a la vez
        // (fondo, opacidad, "+ $" en vez de "$", y el rótulo de arriba).
        atenuado && "bg-muted/40 opacity-90",
      )}
    >
      <div className="flex min-w-[160px] flex-1 items-center gap-2">
        {icono}
        <div
          className={cn(
            "min-w-0 flex-1 truncate text-sm",
            atenuado ? "text-muted-foreground" : "text-ink",
          )}
        >
          {titulo}
        </div>
      </div>
      <div className="ml-auto flex flex-wrap items-center justify-end gap-x-2 gap-y-1.5">
        {controles}
        <div
          className={cn(
            "w-24 text-right font-mono text-sm tabular-nums",
            atenuado ? "font-normal text-muted-foreground" : "font-semibold text-ink",
          )}
        >
          {subtotal === undefined ? (
            <span className="text-muted-foreground">…</span>
          ) : atenuado ? (
            // "+ $X" = cuánto SUMARÍA, no cuánto se está cobrando.
            `+ ${formatARS(subtotal)}`
          ) : (
            formatARS(subtotal)
          )}
        </div>
        <div className="flex w-9 shrink-0 justify-end">{accion}</div>
      </div>
    </li>
  );
}

/** Rótulo que parte la lista en dos: arriba lo que el turno incluye, abajo lo
 *  que se le puede sumar. Es la señal más barata y más fuerte de todas — con un
 *  encabezado que dice "se le puede sumar", ninguna fila de abajo se puede leer
 *  como ya incluida. */
function FilaRotulo({ children }: { children: ReactNode }) {
  return (
    <li className="bg-muted/40 px-2.5 py-1.5">
      <span className="t-eyebrow">{children}</span>
    </li>
  );
}

/**
 * Banda de tiempo del turno — CUÁNDO, arriba de todo, separada de "qué
 * incluye". Es el espejo de la píldora "Retiro → Devolución" del alquiler
 * (`pedidos.$id.lazy.tsx`): mismo contenedor, mismos eyebrows, misma posición
 * dentro de la sección, para que las dos secciones se lean como hermanas
 * (pedido del dueño: "al Estudio, separar las fechas a un coso arriba, como en
 * el rental, y así visualmente están hermanados").
 *
 * Diferencia honesta con el alquiler: allá la píldora es un BOTÓN que abre el
 * selector y las jornadas son un número derivado; acá los tres campos se
 * editan en el lugar y la duración ES un campo. No se fuerza el parecido hasta
 * fingir un control que no existe.
 *
 * (Estos campos vivieron un tiempo adentro de la fila "Espacio". Salieron de
 * ahí por este pedido — pero NO vuelven al grid suelto de antes: ahora son una
 * banda con la forma de la del alquiler, dentro de la misma sección.)
 */
function BandaFranja({
  fecha,
  onChangeFecha,
  start,
  onChangeStart,
  horas,
  onChangeHoras,
  minHoras,
  slots,
  accion,
}: {
  fecha: string;
  onChangeFecha: (v: string) => void;
  start: string;
  onChangeStart: (v: string) => void;
  horas: number;
  onChangeHoras: (v: number) => void;
  minHoras: number;
  slots: { value: string; label: string }[];
  accion?: ReactNode;
}) {
  return (
    <div className="@container flex items-start gap-3 rounded-lg border hairline bg-surface-elevated px-3.5 py-2.5">
      <Clapperboard className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="grid min-w-0 flex-1 grid-cols-1 gap-x-6 gap-y-2 @xl:grid-cols-3">
        <div className="min-w-0">
          <div className="t-eyebrow">Fecha</div>
          <Input
            type="date"
            aria-label="Fecha del turno"
            value={fecha}
            onChange={(e) => onChangeFecha(e.target.value)}
            className="mt-0.5 h-9 w-full max-w-[150px] text-sm"
          />
        </div>
        <div className="min-w-0">
          <div className="t-eyebrow">Empieza</div>
          <select
            aria-label="Hora de inicio"
            value={start}
            onChange={(e) => onChangeStart(e.target.value)}
            className="mt-0.5 h-9 w-full max-w-[110px] rounded-md border hairline bg-surface-elevated px-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {slots.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-0">
          <div className="t-eyebrow">Duración</div>
          <div className="mt-0.5 flex items-center gap-1.5">
            <Input
              type="number"
              aria-label="Horas"
              min={minHoras}
              value={horas}
              onChange={(e) => onChangeHoras(Number(e.target.value) || 0)}
              className="h-9 w-16 text-center text-sm"
            />
            <span className="t-eyebrow">{horas === 1 ? "hora" : "horas"}</span>
          </div>
        </div>
      </div>
      {accion && <div className="-mr-1.5 shrink-0">{accion}</div>}
    </div>
  );
}

export function EstudioIncluyeList({
  estudio,
  fecha,
  onChangeFecha,
  start,
  onChangeStart,
  horas,
  onChangeHoras,
  conPromo,
  onTogglePromo,
  pinturaReciente,
  onTogglePintura,
  sueltos,
  onAddSuelto,
  onRemoveSuelto,
  onChangeSueltoCantidad,
  espacioOverride,
  onChangeEspacioOverride,
  cotiz,
  accion,
}: {
  estudio: EstudioConfig;
  fecha: string;
  onChangeFecha: (v: string) => void;
  start: string;
  onChangeStart: (v: string) => void;
  horas: number;
  onChangeHoras: (v: number) => void;
  conPromo: boolean;
  onTogglePromo: (v: boolean) => void;
  pinturaReciente: boolean;
  onTogglePintura: (v: boolean) => void;
  sueltos: SueltoLocal[];
  onAddSuelto: (eq: Equipo) => void;
  onRemoveSuelto: (equipoId: number) => void;
  onChangeSueltoCantidad: (equipoId: number, cantidad: number) => void;
  espacioOverride: string;
  onChangeEspacioOverride: (v: string) => void;
  cotiz?: EstudioCotizacion;
  /** Acción a la derecha del label, para el bloque ENTERO (no una fila): hoy,
   *  el ✕ que descarta un turno todavía sin crear. */
  accion?: ReactNode;
}) {
  const slots = useMemo(
    () => buildTimeSlots(estudio.open_hour, estudio.close_hour, estudio.min_horas || 1),
    [estudio.open_hour, estudio.close_hour, estudio.min_horas],
  );

  // Un solo nombre para la promo: la fila incluida, la disponible y los
  // aria-label de ✕/+ tienen que decir exactamente lo mismo.
  const nombrePromo = estudio.promo?.nombre || "Pack";
  const hayDisponibles = (!conPromo && !!estudio.promo_combo_id) || !pinturaReciente;

  const existingAsDraftItems: DraftItem[] = useMemo(
    () =>
      sueltos.map((s) => ({
        uid: String(s.equipo_id),
        equipo_id: s.equipo_id,
        cantidad: s.cantidad,
        precio_jornada: s.precio_jornada ?? 0,
        nombre: s.nombre,
        marca: s.marca,
        nombre_publico: s.nombre_publico,
        foto_url: s.foto_url,
      })),
    [sueltos],
  );

  return (
    <div className="space-y-3">
      {/* CUÁNDO arriba (banda), QUÉ INCLUYE abajo (lista) — la misma forma que
          la sección "Alquiler" del pedido, para que se lean como hermanas. */}
      <BandaFranja
        fecha={fecha}
        onChangeFecha={onChangeFecha}
        start={start}
        onChangeStart={onChangeStart}
        horas={horas}
        onChangeHoras={onChangeHoras}
        minHoras={estudio.min_horas || 1}
        slots={slots}
        accion={accion}
      />

      <Field label="Qué incluye este turno">
        {/* Orden de lectura (pedido del dueño): PRIMERO el turno — su precio —,
            después lo que se le suma. Antes el buscador de equipos abría la
            sección, así que lo primero que se veía era cómo agregar equipo y no
            el turno en sí. */}
        <ul className="divide-y hairline rounded-md border hairline">
          {/* Espacio — siempre presente, no se puede quitar (es la base del
            turno); su TARIFA se edita acá, en la misma fila — la franja
            horaria vive arriba, en la banda de tiempo. */}
          <FilaIncluye
            icono={<FilaIcono icon={Clapperboard} />}
            titulo="Espacio"
            subtotal={cotiz?.espacio}
            controles={
              <Input
                type="number"
                min={0}
                aria-label="Precio del espacio"
                value={espacioOverride}
                onChange={(e) => onChangeEspacioOverride(e.target.value)}
                placeholder={String((estudio.precio_hora || 0) * horas)}
                className="h-9 w-24 text-right text-sm"
              />
            }
          />

          {conPromo && (
            <FilaIncluye
              icono={<FilaIcono icon={Package} />}
              titulo={nombrePromo}
              subtotal={cotiz?.promo}
              accion={<BotonQuitar label={nombrePromo} onClick={() => onTogglePromo(false)} />}
            />
          )}

          {pinturaReciente && (
            <FilaIncluye
              icono={<FilaIcono icon={Paintbrush} />}
              titulo="Recién pintado"
              subtotal={cotiz?.pintura_reciente}
              accion={<BotonQuitar label="Recién pintado" onClick={() => onTogglePintura(false)} />}
            />
          )}

          {sueltos.map((s) => (
            <FilaIncluye
              key={s.equipo_id}
              icono={<EquipoThumb src={s.foto_url} alt={s.nombre} className="h-10 w-10 shrink-0" />}
              titulo={s.nombre}
              subtotal={cotiz?.sueltos.find((cs) => cs.equipo_id === s.equipo_id)?.subtotal}
              accion={<BotonQuitar label={s.nombre} onClick={() => onRemoveSuelto(s.equipo_id)} />}
              controles={
                // Mismo stepper del DS que usa la fila de un equipo del pedido —
                // antes era un `<input type=number>` pelado, otra forma de hacer
                // exactamente lo mismo.
                <QtyInput
                  value={s.cantidad}
                  onChange={(v) => onChangeSueltoCantidad(s.equipo_id, Math.max(1, v))}
                  min={1}
                />
              }
            />
          ))}

          {/* Lo que se PUEDE sumar, como una fila más de la misma lista (atenuada,
            con + en vez de ✕, bajo su propio rótulo). El precio que muestran es
            el de lista que ya resolvió el backend (`estudio.promo.precio` /
            `precio_pintura_reciente`) — el front no lo calcula, solo lo muestra
            (MEMORIA 2026-06-29); al agregarlas, la línea pasa arriba con su
            plata cotizada. */}
          {hayDisponibles && <FilaRotulo>Se le puede sumar</FilaRotulo>}

          {!conPromo && estudio.promo_combo_id && (
            <FilaIncluye
              atenuado
              icono={<FilaIcono icon={Package} />}
              titulo={nombrePromo}
              subtotal={estudio.promo?.precio}
              accion={<BotonSumar label={nombrePromo} onClick={() => onTogglePromo(true)} />}
            />
          )}

          {!pinturaReciente && (
            <FilaIncluye
              atenuado
              icono={<FilaIcono icon={Paintbrush} />}
              titulo="Recién pintado"
              subtotal={estudio.precio_pintura_reciente || 0}
              accion={<BotonSumar label="Recién pintado" onClick={() => onTogglePintura(true)} />}
            />
          )}

          {/* Sumar equipo suelto — ÚLTIMA fila de la lista: es lo último que se
            agrega, no lo primero que se lee (antes abría la sección y tapaba al
            turno; después quedó afuera de la lista, como una caja aparte). */}
          <li className="px-2.5 py-2">
            <EquipoComboSearch
              existing={existingAsDraftItems}
              stockMap={{}}
              onAdd={onAddSuelto}
              placeholder="Buscar equipo para sumar…"
            />
          </li>
        </ul>
      </Field>
    </div>
  );
}
