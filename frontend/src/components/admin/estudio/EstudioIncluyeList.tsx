/**
 * EstudioIncluyeList — "qué incluye este turno" como un solo listado: Espacio
 * (siempre, franja horaria + precio editables INLINE en la misma fila) +
 * Pack + Recién pintado (chips para agregar/quitar, se muestran como fila
 * una vez agregados) + Equipos sueltos. Reemplaza los switches sueltos + el
 * campo de override separado + el desglose por-componente duplicado — una
 * sola forma de ver y tocar cada línea, con su precio en vivo al lado (el
 * front no calcula plata, MEMORIA 2026-06-29: los precios de Pack/Pintura/
 * sueltos vienen de `cotiz`, ya resuelto por el backend).
 *
 * El buscador de sueltos replica la misma lógica que "Equipos" del pedido:
 * SIEMPRE visible, sin colapsar detrás de ningún chip/toggle (el dueño lo
 * pidió así explícitamente, viendo esa sección como referencia). NO es
 * redundante con "Equipos": ese reserva/cobra por el rango de días completo,
 * un suelto reserva/cobra solo la franja horaria puntual del turno (cargo
 * fijo, stock duro) — y en una reserva standalone del Estudio es la ÚNICA
 * vía de sumar equipo.
 *
 * La fila "Espacio" absorbe fecha/hora/horas (#1308, pedido del dueño: "no
 * quiero el modal... quiero una lista para seleccionar, como con los
 * equipos") — antes vivían en un grid de 3 columnas aparte, arriba de esta
 * lista, en cada caller (duplicado 2 veces); ahora es UNA sola fila de UNA
 * sola lista, igual de simple que la sección "Equipos" del pedido.
 *
 * Presentacional puro — sin query/mutation propias. Compartido por
 * `ReservaEstudioSection` (editar) y `NuevoTurnoEstudioForm` (alta): cada uno
 * maneja su propio estado y le pasa acá los callbacks, así las dos
 * superficies se ven y comportan igual sin duplicar el layout.
 */
import { useMemo, type ReactNode } from "react";
import { Clapperboard, Package, Paintbrush, Plus, X } from "lucide-react";

import { Input } from "@/design-system/ui/input";
import { QtyInput } from "@/design-system/ui/qty-input";
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

function AddChip({
  label,
  icon: Icon,
  onClick,
}: {
  label: string;
  icon: typeof Package;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-md border border-dashed hairline px-2.5 py-1.5 text-xs text-muted-foreground transition hover:bg-muted/30 hover:text-ink"
    >
      <Plus className="h-3 w-3 shrink-0" />
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{label}</span>
    </button>
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
 * (subtotal + hueco del ✕): como el bloque de controles va `justify-end`, los
 * subtotales quedan a la misma altura y en la misma columna aunque cada fila
 * tenga controles distintos adelante.
 */
function FilaIncluye({
  icono,
  titulo,
  controles,
  subtotal,
  onQuitar,
}: {
  icono: ReactNode;
  titulo: ReactNode;
  /** Lo editable propio de esta fila (franja, cantidad, precio…). */
  controles?: ReactNode;
  /** Plata de la línea, ya resuelta por el backend. `undefined` → "…". */
  subtotal?: number;
  /** Sin handler → fila que no se puede quitar (el espacio), pero conserva el
   *  hueco para no desalinear la columna. */
  onQuitar?: () => void;
}) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 px-2.5 py-2">
      <div className="flex min-w-[160px] flex-1 items-center gap-2">
        {icono}
        <div className="min-w-0 flex-1 truncate text-sm text-ink">{titulo}</div>
      </div>
      <div className="ml-auto flex flex-wrap items-center justify-end gap-x-2 gap-y-1.5">
        {controles}
        <div className="w-24 text-right font-mono text-sm font-semibold tabular-nums text-ink">
          {subtotal === undefined ? (
            <span className="text-muted-foreground">…</span>
          ) : (
            formatARS(subtotal)
          )}
        </div>
        <div className="flex w-8 justify-end">
          {onQuitar && (
            <button
              type="button"
              onClick={onQuitar}
              aria-label={`Quitar ${typeof titulo === "string" ? titulo : "línea"}`}
              className="text-muted-foreground hover:text-destructive"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </li>
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
}) {
  const slots = useMemo(
    () => buildTimeSlots(estudio.open_hour, estudio.close_hour, estudio.min_horas || 1),
    [estudio.open_hour, estudio.close_hour, estudio.min_horas],
  );

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
    <Field label="Qué incluye este turno">
      {/* Orden de lectura (pedido del dueño): PRIMERO el turno — su franja y su
          precio —, después lo que se le suma. Antes el buscador de equipos
          abría la sección, así que lo primero que se veía era cómo agregar
          equipo y no el turno en sí. */}
      <ul className="divide-y hairline rounded-md border hairline">
        {/* Espacio — siempre presente, no se puede quitar (es la base del
            turno); franja horaria + precio se editan ACÁ, inline, en la
            misma fila (#1308 — antes vivían en un grid aparte arriba de
            toda la lista, que es justo lo que se leía como "un form"). */}
        <FilaIncluye
          icono={<FilaIcono icon={Clapperboard} />}
          titulo="Espacio"
          subtotal={cotiz?.espacio}
          controles={
            <>
              <Input
                type="date"
                aria-label="Fecha"
                value={fecha}
                onChange={(e) => onChangeFecha(e.target.value)}
                className="h-9 w-[136px] text-sm"
              />
              <select
                aria-label="Hora"
                value={start}
                onChange={(e) => onChangeStart(e.target.value)}
                className="h-9 rounded-md border hairline bg-surface-elevated px-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {slots.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
              <div className="flex items-center gap-1">
                <Input
                  type="number"
                  aria-label="Horas"
                  min={estudio.min_horas || 1}
                  value={horas}
                  onChange={(e) => onChangeHoras(Number(e.target.value) || 0)}
                  className="h-9 w-14 text-center text-sm"
                />
                <span className="text-xs text-muted-foreground">h</span>
              </div>
              <Input
                type="number"
                min={0}
                aria-label="Precio del espacio"
                value={espacioOverride}
                onChange={(e) => onChangeEspacioOverride(e.target.value)}
                placeholder={String((estudio.precio_hora || 0) * horas)}
                className="h-9 w-24 text-right text-sm"
              />
            </>
          }
        />

        {conPromo && (
          <FilaIncluye
            icono={<FilaIcono icon={Package} />}
            titulo={estudio.promo?.nombre || "Pack"}
            subtotal={cotiz?.promo}
            onQuitar={() => onTogglePromo(false)}
          />
        )}

        {pinturaReciente && (
          <FilaIncluye
            icono={<FilaIcono icon={Paintbrush} />}
            titulo="Recién pintado"
            subtotal={cotiz?.pintura_reciente}
            onQuitar={() => onTogglePintura(false)}
          />
        )}

        {sueltos.map((s) => (
          <FilaIncluye
            key={s.equipo_id}
            icono={<EquipoThumb src={s.foto_url} alt={s.nombre} className="h-10 w-10 shrink-0" />}
            titulo={s.nombre}
            subtotal={cotiz?.sueltos.find((cs) => cs.equipo_id === s.equipo_id)?.subtotal}
            onQuitar={() => onRemoveSuelto(s.equipo_id)}
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
      </ul>

      {/* Add-ons: una sola fila compacta de chips, no dos botones a ancho
          completo — espeja el "+ Agregar línea personalizada" de "Equipos". */}
      {(!conPromo && estudio.promo_combo_id) || !pinturaReciente ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {!conPromo && estudio.promo_combo_id && (
            <AddChip
              icon={Package}
              label={estudio.promo?.nombre || "Pack"}
              onClick={() => onTogglePromo(true)}
            />
          )}
          {!pinturaReciente && (
            <AddChip
              icon={Paintbrush}
              label="Recién pintado"
              onClick={() => onTogglePintura(true)}
            />
          )}
        </div>
      ) : null}

      {/* Sumar equipo suelto — AL FINAL: es lo último que se agrega, no lo
          primero que se lee. Antes abría la sección y tapaba al turno. */}
      <div className="mt-2">
        <EquipoComboSearch
          existing={existingAsDraftItems}
          stockMap={{}}
          onAdd={onAddSuelto}
          placeholder="Buscar equipo para sumar…"
        />
      </div>
    </Field>
  );
}
