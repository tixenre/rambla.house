/**
 * EquipoComboSearch — buscador de equipos inline para el editor de pedidos.
 *
 * Reemplaza al `EquipoSearchSheet` full-screen: los resultados aparecen en un
 * dropdown DEBAJO del input (patrón de `ClienteAutocomplete`), sin tapar el
 * formulario. Combina ese patrón inline con el motor de búsqueda compartido
 * (`filtrarOrdenar`, espejo del backend) y la carga client-side del catálogo
 * (per_page 500, cacheada) para filtrado instantáneo.
 *
 * Al agregar NO cierra ni limpia el input → se pueden cargar varios equipos
 * seguidos. El stock disponible se recalcula en vivo desde `existing` + `stockMap`.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { SearchInput } from "@/design-system/ui/search-input";
import { cn } from "@/lib/utils";
import { adminApi, type Equipo } from "@/lib/admin/api";
import { filtrarOrdenar } from "@/lib/search/normalize";
import { PrecioUnidad } from "@/components/admin/Monto";
import { EquipoThumb } from "./EquipoThumb";
import type { DraftItem } from "./usePedidoDraft";

/** Tope de filas visibles sin query (evita renderizar las ~500 del catálogo). */
const MAX_VISIBLE = 50;

export function EquipoComboSearch({
  existing,
  stockMap,
  stockConfiable = true,
  onAdd,
  placeholder = "Buscar para añadir equipos…",
  className,
}: {
  existing: DraftItem[];
  /** equipo_id → libres tras TODO el draft (backend, kits expandidos; con signo). */
  stockMap: Record<string, number>;
  /** `false` cuando `stockMap` no es un dato real (ej. el buscador de sueltos
   *  de un turno del Estudio, que no tiene un endpoint de disponibilidad por
   *  franja horaria todavía): sin esto, el fallback naive de `disponibleDe`
   *  ("cantidad total del equipo menos lo ya cargado EN ESTA lista", que
   *  ignora cualquier otra reserva superpuesta) se mostraba como si fuera la
   *  verdad — "5 libres" mintiendo cuando en realidad podían estar todas
   *  ocupadas en esa franja. El gate real sigue siendo el 409 del backend al
   *  guardar (los sueltos son stock DURO); acá solo se deja de fingir
   *  certeza que no existe. */
  stockConfiable?: boolean;
  onAdd: (eq: Equipo) => void;
  placeholder?: string;
  className?: string;
}) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [focusedIdx, setFocusedIdx] = useState(-1);
  const wrapRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // Cerrar al clickear afuera (el dropdown se mantiene abierto mientras se
  // agregan equipos, así que no alcanza con onBlur del input).
  useEffect(() => {
    if (!open) return;
    const h = (ev: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  // Reset del foco al cambiar la búsqueda.
  useEffect(() => setFocusedIdx(-1), [q]);

  // Scroll al ítem enfocado.
  useEffect(() => {
    if (focusedIdx < 0 || !listRef.current) return;
    const item = listRef.current.children[focusedIdx] as HTMLElement;
    item?.scrollIntoView({ block: "nearest" });
  }, [focusedIdx]);

  const equiposQ = useQuery({
    queryKey: ["admin", "equipos", "all"],
    queryFn: () => adminApi.listEquipos({ per_page: 500 }),
  });

  const matches = useMemo(() => {
    const all = (equiposQ.data?.items ?? []).filter((e) => e.estado !== "fuera_servicio");
    // Motor de búsqueda compartido (espejo del backend): sin tildes, sin
    // guiones, multi-palabra y ordenado por relevancia.
    return filtrarOrdenar(all, q, (e) => ({
      nombre: e.nombre,
      extra: [e.nombre_publico ?? "", e.marca ?? "", e.modelo ?? ""].join(" "),
    }));
  }, [equiposQ.data, q]);

  const visibles = matches.slice(0, MAX_VISIBLE);
  const overflow = matches.length - visibles.length;

  /** Unidades libres restantes para este equipo. El mapa del backend ya
   *  descuenta TODO el draft (con la expansión de kits del motor) — no se
   *  vuelve a restar. Sin fechas no hay mapa → fallback naive al stock total
   *  menos lo cargado (sin expansión, como antes). */
  const disponibleDe = (eq: Equipo): number => {
    const enMapa = stockMap[String(eq.id)];
    if (enMapa !== undefined) return enMapa;
    const inCart = existing.find((i) => i.equipo_id === eq.id);
    return eq.cantidad - (inCart?.cantidad ?? 0);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFocusedIdx((i) => Math.min(i + 1, visibles.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setFocusedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const eq = visibles[focusedIdx];
      if (eq && (!stockConfiable || disponibleDe(eq) > 0)) onAdd(eq);
    } else if (e.key === "Escape") {
      setOpen(false);
      setFocusedIdx(-1);
    }
  };

  return (
    <div ref={wrapRef} className={cn("relative", className)}>
      <SearchInput
        value={q}
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-autocomplete="list"
        aria-controls="equipo-combo-list"
        aria-activedescendant={focusedIdx >= 0 ? `equipo-opt-${focusedIdx}` : undefined}
        onValueChange={(v) => {
          setQ(v);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        // El placeholder NO es un nombre accesible (desaparece al tipear y los
        // lectores de pantalla no lo garantizan): sin esto el buscador se oía
        // como un campo de texto sin nombre. Se reusa el mismo texto.
        aria-label={placeholder}
      />

      {open && (
        <div className="absolute z-30 left-0 right-0 mt-1 card-elevated shadow-[var(--shadow-md)] max-h-80 overflow-auto">
          {equiposQ.isLoading ? (
            <div className="p-3 text-xs text-muted-foreground">Cargando catálogo…</div>
          ) : matches.length === 0 ? (
            <div className="p-3 text-xs text-muted-foreground">
              {q.trim() ? `Sin resultados para "${q.trim()}".` : "No hay equipos."}
            </div>
          ) : (
            <ul ref={listRef} role="listbox" id="equipo-combo-list" className="divide-y hairline">
              {visibles.map((eq, idx) => {
                const disponible = disponibleDe(eq);
                const sinStock = stockConfiable && disponible <= 0;
                const isFocused = idx === focusedIdx;
                return (
                  <li
                    key={eq.id}
                    id={`equipo-opt-${idx}`}
                    role="option"
                    aria-selected={isFocused}
                    aria-disabled={sinStock}
                  >
                    <button
                      type="button"
                      disabled={sinStock}
                      // onMouseDown + preventDefault: agregar sin perder el foco
                      // del input → el dropdown queda abierto para cargar más.
                      onMouseDown={(e) => {
                        e.preventDefault();
                        if (!sinStock) onAdd(eq);
                      }}
                      className={cn(
                        "flex w-full items-center gap-3 px-3 py-2 text-left transition-colors",
                        sinStock ? "cursor-not-allowed opacity-50" : "hover:bg-amber-soft",
                        isFocused && !sinStock && "bg-amber-soft",
                      )}
                    >
                      <EquipoThumb
                        src={eq.foto_url}
                        alt={eq.nombre_publico || eq.nombre}
                        className="h-10 w-10 shrink-0"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm text-ink truncate">
                          {eq.nombre_publico || eq.nombre}
                        </div>
                        <div className="font-mono text-xs text-muted-foreground truncate">
                          {[eq.marca, eq.modelo].filter(Boolean).join(" / ")}
                          {eq.precio_jornada ? (
                            <>
                              {" · "}
                              <PrecioUnidad value={eq.precio_jornada} />
                            </>
                          ) : (
                            ""
                          )}
                        </div>
                      </div>
                      <span
                        className={cn(
                          "shrink-0 rounded px-1.5 py-0.5 font-mono text-2xs",
                          sinStock
                            ? "bg-destructive/10 text-destructive"
                            : "bg-muted text-muted-foreground",
                        )}
                      >
                        {!stockConfiable
                          ? "stock sin verificar"
                          : sinStock
                            ? "sin stock"
                            : `${disponible} libres`}
                      </span>
                      <Plus
                        className={cn(
                          "h-4 w-4 shrink-0",
                          sinStock ? "text-muted-foreground/40" : "text-ink",
                        )}
                      />
                    </button>
                  </li>
                );
              })}
              {overflow > 0 && (
                <li className="px-3 py-2 text-center t-eyebrow">
                  +{overflow} más · seguí escribiendo para afinar
                </li>
              )}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
