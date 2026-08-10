import { useEffect, useRef, useState } from "react";

/**
 * Fade en los bordes de un contenedor horizontal-scroll (`overflow-x-auto`)
 * que tiene más contenido del que entra en pantalla — señal visual de que se
 * puede scrollear, sin la cual el contenido más allá del viewport queda
 * invisible sin aviso (ej. tab-strips con muchas pestañas en mobile).
 *
 * `active` gatea el chequeo inicial + el listener de resize (false cuando el
 * contenedor todavía no es visible, ej. un acordeón colapsado).
 */
export function useScrollFadeMask(active: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  const [fade, setFade] = useState({ left: false, right: false });

  function update() {
    const el = ref.current;
    if (!el) return;
    setFade({
      left: el.scrollLeft > 1,
      right: el.scrollLeft + el.clientWidth < el.scrollWidth - 1,
    });
  }

  useEffect(() => {
    if (!active) return;
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [active]);

  const mask = fade.left
    ? fade.right
      ? "linear-gradient(to right, transparent, black 24px, black calc(100% - 24px), transparent)"
      : "linear-gradient(to right, transparent, black 24px)"
    : fade.right
      ? "linear-gradient(to right, black calc(100% - 24px), transparent)"
      : undefined;

  return {
    ref,
    onScroll: update,
    style: mask ? { maskImage: mask, WebkitMaskImage: mask } : undefined,
  };
}
