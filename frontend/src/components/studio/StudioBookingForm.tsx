import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import { format } from "date-fns";
import { es } from "date-fns/locale";
import { Calendar as CalendarIcon, Check, Clock, MessageCircle, Minus, Plus } from "lucide-react";
import { Button } from "@/design-system/ui/button";
import { Pill } from "@/design-system/ui/Pill";
import { Spinner } from "@/design-system/ui/spinner";
import { GoogleIcon } from "@/design-system/ui/GoogleIcon";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/design-system/ui/dialog";
import { FieldLabel } from "@/design-system/ui/Field";
import { cn } from "@/lib/utils";
import { formatARS } from "@/lib/format";
import { authedFetch } from "@/lib/authedFetch";
import { chequearEstadoVerificacion, iniciarVerificacionIdentidad } from "@/lib/verificacion";
import {
  VerificacionRequeridaPanel,
  type VerificacionPanelEstado,
} from "@/components/rental/account/VerificacionRequeridaPanel";
import { STUDIO, STUDIO_PHONE } from "@/data/studio";
import { apiGetEstudioDisponibilidad, apiCrearReservaEstudio, type EstudioPromo } from "@/lib/api";
import { pad, buildTimeSlots } from "@/lib/estudio-slots";
import { EstudioWeekGrid } from "@/components/studio/EstudioWeekGrid";

export type StudioBookingConfig = {
  pricePerHour: number;
  minHours: number;
  openHour: number;
  closeHour: number;
  promo?: EstudioPromo | null;
};

type Disponibilidad = "idle" | "checking" | "libre" | "ocupado" | "error";

function Section({
  step,
  title,
  children,
  className,
}: {
  step: number;
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-2xl border hairline bg-surface p-5 sm:p-6", className)}>
      <header className="flex items-baseline gap-2 mb-4">
        <span className="t-eyebrow tabular">{pad(step)}</span>
        <h3 className="font-display text-lg sm:text-xl">{title}</h3>
      </header>
      {children}
    </section>
  );
}

const QUERY_KEYS = { d: "d", h: "h", dur: "dur", promo: "promo" } as const;

function readBookingFromQuery() {
  if (typeof window === "undefined") return null;
  const sp = new URLSearchParams(window.location.search);
  const d = sp.get(QUERY_KEYS.d);
  const h = sp.get(QUERY_KEYS.h);
  const dur = sp.get(QUERY_KEYS.dur);
  const promo = sp.get(QUERY_KEYS.promo);
  if (!d && !h && !dur && !promo) return null;
  let parsedDate: Date | undefined;
  if (d) {
    const [y, mo, da] = d.split("-").map((n) => parseInt(n, 10));
    if (y && mo && da) {
      const dt = new Date(y, mo - 1, da);
      if (!isNaN(dt.getTime())) parsedDate = dt;
    }
  }
  return {
    date: parsedDate,
    start: h && /^\d{2}:\d{2}$/.test(h) ? h : null,
    hours: dur && /^\d+$/.test(dur) ? parseInt(dur, 10) : null,
    withPromo: promo === "1",
  };
}

function clearBookingQuery() {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  Object.values(QUERY_KEYS).forEach((k) => url.searchParams.delete(k));
  if (url.toString() !== window.location.href) window.history.replaceState({}, "", url.toString());
}

export function StudioBookingForm({
  config,
  withPromo,
  onPromoChange,
}: {
  config?: StudioBookingConfig;
  /** Estado controlado por el padre — permite que el aside sea reactivo */
  withPromo: boolean;
  onPromoChange: (v: boolean) => void;
}) {
  const navigate = useNavigate();
  const pricePerHour = config?.pricePerHour ?? STUDIO.pricePerHour;
  const minHours = config?.minHours ?? STUDIO.minHours;
  const openHour = config?.openHour ?? STUDIO.openHour;
  const closeHour = config?.closeHour ?? STUDIO.closeHour;
  const promo = config?.promo ?? null;

  const initial = useMemo(() => readBookingFromQuery(), []);
  const [date, setDate] = useState<Date | undefined>(initial?.date);
  const [startSlot, setStartSlot] = useState<string>(initial?.start ?? `${pad(openHour)}:00`);
  const [hours, setHours] = useState<number>(initial?.hours ?? minHours);
  const [returnedFromLogin, setReturnedFromLogin] = useState<boolean>(!!initial);

  useEffect(() => {
    if (initial) {
      clearBookingQuery();
      if (initial.withPromo) onPromoChange(true);
      const t = setTimeout(() => setReturnedFromLogin(false), 12_000);
      return () => clearTimeout(t);
    }
  }, [initial, onPromoChange]);

  const [auth, setAuth] = useState<"checking" | "in" | "out">("checking");
  const [verificado, setVerificado] = useState(false);
  // Sub-estado de identidad (no-verificado / en-revision / rechazado) — mismo
  // patrón que CheckoutResumen/IdentidadSection: sin esto, un cliente en
  // revisión o rechazado veía el CTA genérico "Verificar mi identidad" y podía
  // reintentar creyendo que nunca había empezado (#1169 seguimiento).
  const [identidadEstado, setIdentidadEstado] = useState<VerificacionPanelEstado>("no-verificado");
  const [identidadMotivo, setIdentidadMotivo] = useState<string | null>(null);
  useEffect(() => {
    let cancelado = false;
    authedFetch("/api/cliente/me")
      .then(async (r) => {
        if (cancelado) return;
        if (!r.ok) {
          setAuth("out");
          return;
        }
        setAuth("in");
        const me = await r.json().catch(() => null);
        setVerificado(!!me?.dni_validado_at);
      })
      .catch(() => {
        if (!cancelado) setAuth("out");
      });
    void chequearEstadoVerificacion().then(({ estado, motivo }) => {
      if (cancelado) return;
      if (estado === "en-revision" || estado === "rechazado") {
        setIdentidadEstado(estado);
        setIdentidadMotivo(motivo ?? null);
      }
    });
    return () => {
      cancelado = true;
    };
  }, []);

  const [disponibilidad, setDisponibilidad] = useState<Disponibilidad>("idle");
  const [motivo, setMotivo] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [loginModalOpen, setLoginModalOpen] = useState(false);
  const [needsVerif, setNeedsVerif] = useState(false);
  const [iniciandoVerif, setIniciandoVerif] = useState(false);

  const slots = useMemo(
    () => buildTimeSlots(openHour, closeHour, minHours),
    [openHour, closeHour, minHours],
  );

  const slot = useMemo(
    () =>
      slots.find((s) => s.value === startSlot) ??
      slots[0] ?? {
        value: `${pad(openHour)}:00`,
        label: `${pad(openHour)}:00`,
        hour: openHour,
        minute: 0 as const,
      },
    [slots, startSlot, openHour],
  );

  const maxHours = useMemo(() => {
    const startDecimal = slot.hour + slot.minute / 60;
    return Math.max(minHours, Math.min(12, Math.floor(closeHour - startDecimal)));
  }, [slot, closeHour, minHours]);

  useEffect(() => {
    if (hours > maxHours) setHours(maxHours);
  }, [hours, maxHours]);
  useEffect(() => {
    if (slots.length > 0 && !slots.some((s) => s.value === startSlot)) setStartSlot(slots[0].value);
  }, [slots, startSlot]);

  const subtotal = pricePerHour * hours;
  const promoTotal = withPromo ? (promo?.precio ?? 0) : 0;
  const total = subtotal + promoTotal;

  const fechaISO = date ? format(date, "yyyy-MM-dd") : null;
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  const dateLabel = date ? cap(format(date, "EEE d 'de' MMM", { locale: es })) : "Elegir fecha";
  const dateLabelFull = date
    ? cap(format(date, "EEEE d 'de' MMMM, yyyy", { locale: es }))
    : "Elegir fecha";

  const endTime = useMemo(() => {
    const totalMin = slot.hour * 60 + slot.minute + hours * 60;
    return `${pad(Math.floor(totalMin / 60) % 24)}:${pad(totalMin % 60)}`;
  }, [slot, hours]);

  useEffect(() => {
    setErrorMsg(null);
    if (!fechaISO) {
      setDisponibilidad("idle");
      return;
    }
    let cancelado = false;
    setDisponibilidad("checking");
    setMotivo(null);
    apiGetEstudioDisponibilidad(fechaISO, startSlot, hours)
      .then((res) => {
        if (cancelado) return;
        setDisponibilidad(res.libre ? "libre" : "ocupado");
        setMotivo(res.motivo ?? null);
      })
      .catch(() => {
        if (!cancelado) setDisponibilidad("error");
      });
    return () => {
      cancelado = true;
    };
  }, [fechaISO, startSlot, hours]);

  const canSubmit = !!fechaISO && disponibilidad === "libre" && !submitting;

  const buildEstudioReturnParams = () =>
    new URLSearchParams({
      [QUERY_KEYS.d]: fechaISO ?? "",
      [QUERY_KEYS.h]: startSlot,
      [QUERY_KEYS.dur]: String(hours),
      [QUERY_KEYS.promo]: withPromo ? "1" : "0",
    }).toString();

  const handleVerificar = async () => {
    setIniciandoVerif(true);
    try {
      await iniciarVerificacionIdentidad(`/estudio?${buildEstudioReturnParams()}`);
    } catch {
      /* el helper ya hizo toast */
    } finally {
      setIniciandoVerif(false);
    }
  };

  const handleReservarClick = () => {
    if (!canSubmit) return;
    if (auth !== "in") {
      setLoginModalOpen(true);
      return;
    }
    if (!verificado) {
      setNeedsVerif(true);
      return;
    }
    void handleReservar();
  };

  const handleReservar = async () => {
    if (!fechaISO) return;
    setSubmitting(true);
    setErrorMsg(null);
    try {
      const res = await apiCrearReservaEstudio({
        fecha: fechaISO,
        start: startSlot,
        horas: hours,
        con_promo: withPromo,
      });
      toast.success(`Reserva #${res.numero_pedido ?? res.id} enviada`, {
        description: "Te llevamos a tu portal para seguir el estado.",
        duration: 6000,
      });
      if (res.promo_advertencia) {
        toast.warning("La promo se reservó incompleta", {
          description: res.promo_advertencia,
          duration: 7000,
        });
      }
      setReturnedFromLogin(false);
      navigate({ to: "/cliente/portal", search: { nuevo: res.id } });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "No se pudo crear la reserva";
      if (/401|sesión/i.test(msg)) {
        setAuth("out");
        setLoginModalOpen(true);
      }
      if (/disponible|409/.test(msg)) setDisponibilidad("ocupado");
      setErrorMsg(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleContinuarConGoogle = () => {
    if (!fechaISO) return;
    window.location.href = `/cliente/auth/google?${new URLSearchParams({ next: `/estudio?${buildEstudioReturnParams()}` }).toString()}`;
  };

  const handleWhatsapp = () => {
    if (!date) return;
    const lines = [
      `Hola! Quiero consultar por el estudio.`,
      `📅 ${format(date, "EEEE d 'de' MMMM, yyyy", { locale: es })}`,
      `🕒 ${startSlot} – ${endTime} (${hours} h)`,
      withPromo && promo ? `➕ ${promo.nombre}` : null,
      total > 0 ? `💵 Total estimado: ${formatARS(total)}` : null,
    ].filter(Boolean);
    window.open(
      `https://wa.me/${STUDIO_PHONE}?text=${encodeURIComponent(lines.join("\n"))}`,
      "_blank",
    );
  };

  const ctaLabel = auth === "out" ? "Iniciar sesión y reservar" : "Reservar";

  return (
    <div className="space-y-4">
      {returnedFromLogin && auth === "in" && (
        <div className="rounded-xl border border-verde/30 bg-verde/10 px-4 py-3 text-sm text-verde-ink">
          <span className="font-medium">Todo listo.</span> Revisá los datos y apretá Reservar para
          confirmar.
        </div>
      )}

      {/* ── 1. ¿Cuándo? ─────────────────────────────────────────────── */}
      <Section step={1} title="¿Cuándo?">
        <div className="mb-4 grid gap-3 sm:grid-cols-[1.4fr_1fr_1fr]">
          {/* Fecha — solo lectura: se elige clickeando la grilla de abajo,
              no tiene sentido un segundo selector (calendario) en paralelo. */}
          <div>
            <FieldLabel>Fecha</FieldLabel>
            <div
              className={cn(
                "mt-1.5 flex h-11 w-full items-center rounded-md border hairline bg-muted/20 px-3 text-sm text-ink",
                !date && "text-muted-foreground",
              )}
            >
              <CalendarIcon className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="truncate">{date ? dateLabel : "Elegí un día en la grilla"}</span>
            </div>
          </div>

          {/* Hora inicio */}
          <div>
            <FieldLabel>Hora</FieldLabel>
            <select
              value={startSlot}
              onChange={(e) => setStartSlot(e.target.value)}
              className="mt-1.5 h-11 w-full rounded-md border hairline bg-background px-3 text-base sm:text-sm focus:border-amber/60 focus:outline-none"
            >
              {slots.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          {/* Duración */}
          <div>
            <FieldLabel>Duración · mín {minHours}h</FieldLabel>
            <div className="mt-1.5 flex h-11 items-center gap-1 card px-1">
              <button
                type="button"
                onClick={() => setHours((h) => Math.max(minHours, h - 1))}
                disabled={hours <= minHours}
                aria-label="Restar hora"
                className="grid h-9 w-9 place-items-center rounded text-muted-foreground hover:bg-ink/5 hover:text-ink disabled:opacity-40"
              >
                <Minus className="h-4 w-4" />
              </button>
              <div className="flex-1 text-center text-base font-semibold tabular">
                {hours} <span className="text-sm font-normal text-muted-foreground">h</span>
              </div>
              <button
                type="button"
                onClick={() => setHours((h) => Math.min(maxHours, h + 1))}
                disabled={hours >= maxHours}
                aria-label="Sumar hora"
                className="grid h-9 w-9 place-items-center rounded text-muted-foreground hover:bg-ink/5 hover:text-ink disabled:opacity-40"
              >
                <Plus className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        <EstudioWeekGrid
          openHour={openHour}
          closeHour={closeHour}
          minHours={minHours}
          hours={hours}
          selected={date ? { date, startSlot } : null}
          onSelectSlot={(d, slot) => {
            setDate(d);
            setStartSlot(slot);
          }}
        />

        {/* ¿Qué reservás? — sin expansión de equipos inline */}
        {promo && (
          <fieldset
            className="mt-5 grid gap-2.5 sm:grid-cols-2"
            role="radiogroup"
            aria-label="¿Qué reservás?"
          >
            <legend className="t-eyebrow mb-2 sm:col-span-2">¿Qué reservás?</legend>

            {/* Card A — Solo el estudio */}
            <label
              className={cn(
                "flex cursor-pointer flex-col gap-1 rounded-xl border p-4 transition",
                !withPromo
                  ? "border-[var(--area-accent)] bg-[color-mix(in_oklch,var(--area-accent)_10%,transparent)]"
                  : "hairline hover:border-ink/40",
              )}
            >
              <input
                type="radio"
                name="studio-modalidad"
                checked={!withPromo}
                onChange={() => onPromoChange(false)}
                className="sr-only"
              />
              <span className="font-semibold">Solo el estudio</span>
              <p className="text-xs text-muted-foreground">
                Reservás el estudio por las horas elegidas. Traés tu equipamiento.
              </p>
            </label>

            {/* Card B — Estudio + promo de equipos */}
            <label
              className={cn(
                "flex cursor-pointer flex-col gap-1 rounded-xl border p-4 transition",
                withPromo
                  ? "border-[var(--area-accent)] bg-[color-mix(in_oklch,var(--area-accent)_10%,transparent)]"
                  : "hairline hover:border-ink/40",
              )}
            >
              <input
                type="radio"
                name="studio-modalidad"
                checked={withPromo}
                onChange={() => onPromoChange(true)}
                className="sr-only"
              />
              <span className="font-semibold">Estudio + {promo.nombre}</span>
              <p className="text-xs text-muted-foreground">{promo.descripcion}</p>
            </label>
          </fieldset>
        )}
      </Section>

      {/* ── 2. Confirmar y reservar ──────────────────────────────────── */}
      <Section step={2} title="Confirmar y reservar">
        {/* Confirm card: líneas → banda verde → total */}
        <div className="rounded-[14px] border border-hairline overflow-hidden mb-4">
          {/* Líneas de desglose */}
          <div className="p-4 flex flex-col gap-1.5">
            <div className="flex justify-between items-baseline text-sm text-muted-foreground">
              <span>
                Estudio · {hours} h{pricePerHour > 0 && ` × ${formatARS(pricePerHour)}`}
              </span>
              <span className="font-mono tabular text-ink">
                {subtotal > 0 ? formatARS(subtotal) : "—"}
              </span>
            </div>
            {withPromo && promo && (
              <div className="flex justify-between items-baseline text-sm text-muted-foreground">
                <span>{promo.nombre}</span>
                <span className="font-mono tabular text-ink">
                  {promo.precio > 0 ? formatARS(promo.precio) : "—"}
                </span>
              </div>
            )}
          </div>

          {/* Banda verde — solo cuando hay fecha y está libre */}
          {fechaISO && disponibilidad === "libre" && (
            <div className="flex items-center gap-2.5 px-4 py-2.5 bg-verde/5 border-y border-verde/10">
              <Pill tone="success" className="gap-1 px-2.5 py-1 text-xs">
                <Check className="h-3 w-3" /> Disponible
              </Pill>
              <span className="text-xs text-muted-foreground tabular">
                {dateLabel} · {startSlot} a {endTime}
              </span>
            </div>
          )}

          {/* Ocupado */}
          {fechaISO && disponibilidad === "ocupado" && (
            <div className="flex items-center gap-2 px-4 py-2.5 bg-destructive/5 border-y border-destructive/10">
              <Pill tone="danger" className="px-2.5 py-1 text-xs">
                {motivo ?? "Ocupado en esa franja"}
              </Pill>
            </div>
          )}

          {/* Verificando */}
          {disponibilidad === "checking" && (
            <div className="flex items-center gap-2 px-4 py-2.5 bg-ink/3 border-y border-hairline">
              <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                <Clock className="h-3 w-3 animate-pulse" /> Verificando disponibilidad…
              </span>
            </div>
          )}

          {/* Total */}
          <div className="px-4 py-3.5">
            <div className="flex justify-between items-baseline text-15 font-bold text-ink">
              <span>Total</span>
              <span className="font-mono tabular">{total > 0 ? formatARS(total) : "—"}</span>
            </div>
          </div>
        </div>

        {errorMsg && (
          <p className="mb-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {errorMsg}
          </p>
        )}

        {needsVerif ? (
          <VerificacionRequeridaPanel
            estado={identidadEstado}
            motivo={identidadMotivo}
            onVerificar={() => void handleVerificar()}
            iniciando={iniciandoVerif}
          />
        ) : (
          <Button
            onClick={handleReservarClick}
            disabled={!canSubmit}
            className="w-full bg-ink text-[var(--area-accent)] hover:bg-[color-mix(in_oklch,var(--color-ink)_82%,var(--area-accent))]"
            size="lg"
          >
            {submitting ? (
              <>
                <Spinner size="sm" className="mr-2" /> Reservando…
              </>
            ) : (
              ctaLabel
            )}
          </Button>
        )}

        <button
          type="button"
          onClick={handleWhatsapp}
          disabled={!date}
          className={cn(
            "mt-2 inline-flex w-full items-center justify-center gap-2 rounded-md py-2 text-sm transition",
            date
              ? "text-muted-foreground hover:text-ink"
              : "text-muted-foreground/50 cursor-not-allowed",
          )}
        >
          <MessageCircle className="h-4 w-4" />
          ¿Preferís coordinarlo por WhatsApp?
        </button>

        {!date && (
          <p className="mt-3 text-center text-xs text-muted-foreground">
            Elegí una fecha para continuar.
          </p>
        )}
        {date && disponibilidad === "error" && (
          <p className="mt-3 text-center text-xs text-destructive">
            No pudimos verificar disponibilidad — reintentá.
          </p>
        )}

        <p className="mt-3 text-center text-xs text-muted-foreground flex items-center justify-center gap-1.5">
          <Check className="h-3 w-3" /> Cancelación gratis hasta 48hs antes
        </p>
      </Section>

      {/* Modal de login — sin cambios visuales */}
      <Dialog open={loginModalOpen} onOpenChange={setLoginModalOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Iniciá sesión para reservar</DialogTitle>
            <DialogDescription>
              Usamos los datos de tu cuenta — no te pedimos formularios.
            </DialogDescription>
          </DialogHeader>
          <div className="card px-4 py-3 text-sm">
            <div className="font-medium text-ink">{dateLabelFull}</div>
            <div className="mt-1 text-muted-foreground">
              <span className="font-medium text-ink tabular">
                {startSlot} a {endTime}
              </span>{" "}
              · {hours} h
            </div>
            {withPromo && promo && (
              <div className="mt-1 text-muted-foreground">
                + <span className="text-ink">{promo.nombre}</span>
              </div>
            )}
            <div className="mt-2 flex items-baseline justify-between border-t hairline pt-2">
              <span className="t-eyebrow">Total estimado</span>
              <span className="font-semibold tabular">
                {total > 0 ? formatARS(total) : "A consultar"}
              </span>
            </div>
          </div>
          <Button
            onClick={handleContinuarConGoogle}
            className="w-full bg-[var(--area-accent)] text-ink hover:bg-[var(--area-accent-hot)]"
            size="lg"
          >
            <GoogleIcon size={16} /> <span className="ml-2">Continuar con Google</span>
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            Te llevamos a Google y volvés acá automáticamente para confirmar.
          </p>
        </DialogContent>
      </Dialog>
    </div>
  );
}
