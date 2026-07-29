import * as React from "react";
import { useLayoutEffect, useRef } from "react";

import { formatARS } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Input } from "./input";

function soloDigitos(s: string): string {
  return s.replace(/\D/g, "");
}

/** Cuántos dígitos hay en `s` antes de la posición `pos`. */
function digitosAntesDe(s: string, pos: number): number {
  let n = 0;
  for (let i = 0; i < pos && i < s.length; i++) {
    if (/\d/.test(s[i])) n++;
  }
  return n;
}

/** Posición en `s` que deja exactamente `count` dígitos antes — el inverso
 *  de `digitosAntesDe`, para reubicar el cursor tras reformatear. */
function posicionParaDigitos(s: string, count: number): number {
  if (count <= 0) return 0;
  let n = 0;
  for (let i = 0; i < s.length; i++) {
    if (/\d/.test(s[i])) {
      n++;
      if (n === count) return i + 1;
    }
  }
  return s.length;
}

/**
 * MoneyInput — se ve formateado como plata ("$791.100") SIEMPRE, incluso
 * mientras se edita: el usuario solo tipea dígitos, nunca separadores (el
 * valor real que se guarda siempre es el número crudo). El formato sale de
 * `formatARS` — la misma fuente única de toda la plata del back-office — no
 * se le pregunta al backend, es presentación fija, no un cálculo.
 *
 * `type="text"` a propósito (no "number"): un input nativo `number` no puede
 * mostrar "$791.100" (el navegador rechaza caracteres no numéricos). El
 * enmascarado se arma a mano:
 *  - Tipear un dígito en cualquier posición: se recalcula contando dígitos
 *    antes del cursor en el texto YA reformateado (funciona para insertar en
 *    cualquier lugar, no solo al final).
 *  - Backspace/Delete se interceptan (no se dejan en manos del navegador):
 *    borrar sobre el texto formateado puede caer justo en un "." separador
 *    — el navegador lo borra pero ningún dígito cambia, y el usuario ve que
 *    "no pasó nada". Acá se resuelve sobre los dígitos crudos directo.
 *  - Flechas arriba/abajo incrementan/decrementan de a `step` (el input ya
 *    no es nativo `number`, así que el spinner nativo desaparece — se repone
 *    el mismo gesto por teclado).
 */
export function MoneyInput({
  value,
  onChange,
  min = 0,
  max,
  step = 100,
  className,
  ariaLabel,
  disabled,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  className?: string;
  ariaLabel?: string;
  disabled?: boolean;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const pendingCursorDigits = useRef<number | null>(null);

  // Restaura el cursor en el mismo "dígito lógico" después de reformatear —
  // sin esto, cada tecla reposicionaba el cursor al final del texto (el bug
  // típico de un input enmascarado que reemplaza el value entero).
  useLayoutEffect(() => {
    const el = ref.current;
    if (pendingCursorDigits.current == null || !el) return;
    const pos = posicionParaDigitos(el.value, pendingCursorDigits.current);
    el.setSelectionRange(pos, pos);
    pendingCursorDigits.current = null;
  });

  function commit(n: number) {
    const clamped = Math.max(min, max != null ? Math.min(max, n) : n);
    onChange(clamped);
  }

  return (
    <Input
      ref={ref}
      type="text"
      inputMode="numeric"
      value={formatARS(value)}
      onChange={(e) => {
        const el = e.target;
        const cursor = el.selectionStart ?? el.value.length;
        pendingCursorDigits.current = digitosAntesDe(el.value, cursor);
        commit(Number(soloDigitos(el.value)) || 0);
      }}
      onKeyDown={(e) => {
        const el = e.currentTarget;
        const pos = el.selectionStart ?? 0;
        const selEnd = el.selectionEnd ?? pos;
        const sinSeleccion = pos === selEnd; // sin esto, un rango seleccionado usa el borrado nativo (onChange lo resuelve igual)
        if (e.key === "Backspace" && sinSeleccion && pos > 0) {
          e.preventDefault();
          const digitos = digitosAntesDe(el.value, pos);
          if (digitos > 0) {
            const raw = soloDigitos(el.value);
            pendingCursorDigits.current = digitos - 1;
            commit(Number(raw.slice(0, digitos - 1) + raw.slice(digitos)) || 0);
          }
        } else if (e.key === "Delete" && sinSeleccion && pos < el.value.length) {
          e.preventDefault();
          const digitos = digitosAntesDe(el.value, pos);
          const raw = soloDigitos(el.value);
          if (digitos < raw.length) {
            pendingCursorDigits.current = digitos;
            commit(Number(raw.slice(0, digitos) + raw.slice(digitos + 1)) || 0);
          }
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          commit(value + step);
        } else if (e.key === "ArrowDown") {
          e.preventDefault();
          commit(value - step);
        }
      }}
      className={cn("tabular-nums", className)}
      aria-label={ariaLabel}
      disabled={disabled}
    />
  );
}
