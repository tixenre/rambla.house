import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ArrowLeft, AlertCircle, AlertTriangle, ShieldCheck } from "lucide-react";
import { format } from "date-fns";
import { es } from "date-fns/locale";

import { Button } from "@/design-system/ui/button";
import { Spinner } from "@/design-system/ui/spinner";
import { RadioGroup, RadioGroupItem } from "@/design-system/ui/radio-group";
import { formatARS } from "@/lib/format";
import { descuentoLabel, type DescuentoOrigen } from "@/lib/cotizacion";
import { PERFIL_IMPUESTOS_LABEL, facturaTipoLabel, type PerfilImpuestos } from "@/lib/iva";
import {
  listarPerfilesFiscales,
  listarProductoras,
  type PerfilFiscal,
  type Productora,
} from "@/lib/cuit";
import { useBusinessContact } from "@/hooks/useBusinessContact";
import { aceptarTyc, validarCheckout, type FaltanItem } from "@/lib/checkout";
import { chequearEstadoVerificacion, iniciarVerificacionIdentidad } from "@/lib/verificacion";
import { firmarConPasskey, listPasskeys, passkeyErrorMessage } from "@/lib/passkey";
import {
  VerificacionRequeridaPanel,
  type VerificacionPanelEstado,
} from "@/components/rental/account/VerificacionRequeridaPanel";
import { FacturacionModal } from "@/components/rental/account/FacturacionModal";
import { TerminosModal } from "@/components/rental/account/TerminosModal";
import { ContratoPreviewModal } from "@/components/rental/ContratoPreviewModal";
import { OptInWhatsApp } from "@/components/rental/cart/OptInWhatsApp";
import { DOC_DESCRIPTION, DOC_LABEL } from "@/components/cliente/ClientePortalTypes";

/** Los 4 docs disponibles desde "solicitado" (ver `_documentos_disponibles`
 *  en el backend) — "factura" queda afuera, no existe hasta que se facture. */
const DOCS_CHECKOUT = ["remito", "contrato", "albaran", "packing-list"] as const;

/** El return_to que le pasamos a Didit para que, al volver verificado, el
 *  carrito se reabra directo en ESTE paso (no en la lista de ítems). Espeja
 *  `?openCarrito=1` (RESUME_FLAG de verificacion.ts) sumando el paso. */
export const RESUME_STEP_PARAM = "carritoPaso";
export const RESUME_STEP_VALUE = "resumen";

/** #1240: a nombre de quién se factura ESTE pedido puntual — mutuamente
 *  excluyentes, `{}` = perfil default de la cuenta (comportamiento de siempre). */
export type FacturacionTarget = { perfilFiscalId?: number; productoraId?: number };

/** Forma mínima de un ítem para el resumen — compacta (sin steppers ni foto,
 *  eso vive en el paso "carrito"): solo lo necesario para confirmar QUÉ se
 *  está pidiendo, no solo cuánto sale. */
export interface ResumenItem {
  id: string;
  nombre: string;
  marca?: string;
  cantidad: number;
}

/**
 * CheckoutResumen — el paso de revisión entre "Revisar pedido" (carrito) y
 * la creación real del pedido. NO hardcodea el orden de las validaciones: le
 * pregunta al backend (`validar_checkout`, el portero de `services/checkout/`)
 * qué falta (`{listo, faltan}`). Un solo botón "Confirmar" resuelve T&C y firma
 * (Face ID/huella) EN EL MISMO click, sin tarjetas intermedias — el usuario no
 * ve un paso separado por cada check, solo Fechas/Total/Tus datos + un botón.
 * La única excepción es **identidad**: como exige salir a Didit, no se puede
 * resolver en un click → mientras falte, el botón queda deshabilitado y se
 * muestra el panel de verificación (con su propio link a Didit) debajo.
 * Fuente única del paso de resumen — la usan el drawer desktop y el sheet
 * mobile por igual.
 *
 * El login (401 del guard `require_cliente`, que el portero no valida — es
 * responsabilidad del route) lo filtra el caller ANTES de montar este
 * componente; acá asumimos sesión de cliente ya presente.
 */
export function CheckoutResumen({
  sessionId,
  startDate,
  endDate,
  startTime,
  endTime,
  d,
  items,
  subtotalTotal,
  descuentoPct,
  descuentoOrigen,
  descuentoMonto,
  totalNeto,
  conIva,
  clienteNombre,
  nombreLegal,
  emailComunicacion,
  telefonoContacto,
  direccionLegal,
  perfilImpuestos,
  onBack,
  onCrearPedido,
}: {
  sessionId: string;
  startDate?: Date;
  endDate?: Date;
  startTime: string;
  endTime: string;
  d: number;
  /** Composición del pedido — solo se usa para el contador del subtotal (no se
   *  vuelve a listar ítem por ítem: esa vista completa ya está en el carrito,
   *  un paso atrás — repetirla acá era ruido, no confirmación). */
  items: ResumenItem[];
  subtotalTotal: number;
  descuentoPct: number;
  descuentoOrigen: DescuentoOrigen;
  descuentoMonto: number;
  totalNeto: number;
  conIva: boolean;
  /** Nombre de pila (casual) — se usa para "Descuento para X". */
  clienteNombre?: string | null;
  /** "Tus datos" — ya resueltos por el backend (`GET /api/cliente/me`):
   *  RENAPER si está verificado (si no, el dato base) + contacto canónico
   *  (teléfono verificado por Didit si existe). Se muestran tal cual. */
  nombreLegal?: string | null;
  emailComunicacion?: string | null;
  telefonoContacto?: string | null;
  direccionLegal?: string | null;
  /** Perfil fiscal — el valor inicial (el editable en vivo vía
   *  `FacturacionModal` vive en estado local, sembrado con este prop). */
  perfilImpuestos?: PerfilImpuestos | null;
  onBack: () => void;
  /** Crea el pedido de verdad (createOrder) — cada superficie decide qué pasa
   *  después (desktop: toast + redirect al portal; mobile: banner inline). Si
   *  tira, este componente lo muestra como error inline sin perder el estado.
   *  `target` (#1240): a nombre de quién factura ESTE pedido, elegido acá. */
  onCrearPedido: (sessionConfirmed: boolean, target: FacturacionTarget) => Promise<void>;
}) {
  const itemCount = items.reduce((acc, it) => acc + it.cantidad, 0);
  const [cargando, setCargando] = useState(true);
  const [faltan, setFaltan] = useState<FaltanItem[]>([]);
  const [errorValidar, setErrorValidar] = useState<string | null>(null);
  const [creando, setCreando] = useState(false);
  const [errorCrear, setErrorCrear] = useState<string | null>(null);
  // Fallback de firma sin passkey (sin soporte / canceló): "Confirmo y acepto"
  // por sesión — ver services/checkout/validar.py::_check_firma.
  const [sessionConfirmed, setSessionConfirmed] = useState(false);
  // Sub-estado de identidad (no-verificado / en-revision / rechazado): el
  // portero solo dice "falta identidad" (booleano); para el copy correcto del
  // panel reusamos /api/cliente/me (misma fuente que el resto del checkout).
  const [identidadEstado, setIdentidadEstado] = useState<VerificacionPanelEstado>("no-verificado");
  const [identidadMotivo, setIdentidadMotivo] = useState<string | null>(null);
  // Perfil fiscal en vivo: arranca con lo que llegó por prop, pero si el
  // cliente lo edita desde `FacturacionModal` (sin salir del checkout) se
  // refleja al toque acá, sin esperar a que el caller vuelva a pedir la sesión.
  const [perfilImpuestosLive, setPerfilImpuestosLive] = useState(perfilImpuestos ?? null);
  const [facturacionOpen, setFacturacionOpen] = useState(false);
  const [terminosOpen, setTerminosOpen] = useState(false);
  const [contratoOpen, setContratoOpen] = useState(false);
  // #1240: a nombre de quién facturar ESTE pedido — perfiles personales
  // propios + productoras vinculadas (admin-managed), solo lectura acá (se
  // gestionan desde `FacturacionModal`/el portal). `{}` = default de la
  // cuenta, sin elegir nada.
  const [perfilesFiscales, setPerfilesFiscales] = useState<PerfilFiscal[] | null>(null);
  const [productorasFiscales, setProductorasFiscales] = useState<Productora[] | null>(null);
  const [facturacionTarget, setFacturacionTarget] = useState<FacturacionTarget>({});

  async function revalidar(nextSessionConfirmed = sessionConfirmed) {
    setCargando(true);
    setErrorValidar(null);
    try {
      const { listo, faltan: nuevo } = await validarCheckout(sessionId, nextSessionConfirmed);
      setFaltan(listo ? [] : nuevo);
      if (nuevo.some((f) => f.check === "identidad")) {
        const { estado, motivo } = await chequearEstadoVerificacion();
        if (estado === "en-revision" || estado === "rechazado") {
          setIdentidadEstado(estado);
          setIdentidadMotivo(motivo ?? null);
        } else {
          setIdentidadEstado("no-verificado");
          setIdentidadMotivo(null);
        }
      }
    } catch {
      setErrorValidar("No pudimos validar tu pedido. Reintentá en unos segundos.");
    } finally {
      setCargando(false);
    }
  }

  useEffect(() => {
    void revalidar(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- solo al entrar al paso; revalidar se llama explícitamente en las acciones
  }, [sessionId]);

  const [iniciandoVerif, setIniciandoVerif] = useState(false);
  async function resolverIdentidad() {
    setIniciandoVerif(true);
    try {
      await iniciarVerificacionIdentidad(
        `/?openCarrito=1&${RESUME_STEP_PARAM}=${RESUME_STEP_VALUE}`,
      );
    } catch {
      /* el helper ya hizo toast */
    } finally {
      setIniciandoVerif(false);
    }
  }

  const faltaIdentidad = faltan.some((f) => f.check === "identidad");
  const otrosFaltantes = faltan.filter((f) => !["identidad", "tyc", "firma"].includes(f.check));

  // Un solo click resuelve T&C + firma (sin tarjetas intermedias) y recién
  // ahí crea el pedido — identidad es la única excepción (exige salir a
  // Didit) y por eso el botón está deshabilitado mientras falte.
  async function handleConfirmar() {
    setCreando(true);
    setErrorCrear(null);
    try {
      if (faltan.some((f) => f.check === "tyc")) {
        await aceptarTyc();
      }
      let confirmado = sessionConfirmed;
      if (faltan.some((f) => f.check === "firma")) {
        const credenciales = await listPasskeys("cliente").catch(() => []);
        const resultado = await firmarConPasskey(credenciales.length > 0);
        if (resultado !== "passkey") {
          // Sin soporte de passkey o canceló el prompt: fallback "Confirmo y
          // acepto" por sesión (mismo criterio que el backend).
          confirmado = true;
          setSessionConfirmed(true);
        }
      }
      // Re-confirmamos contra el portero (fuente única) antes de crear — no
      // confiamos en el estado local de arriba.
      const { listo: listoAhora, faltan: faltanAhora } = await validarCheckout(
        sessionId,
        confirmado,
      );
      if (!listoAhora) {
        setFaltan(faltanAhora);
        setErrorCrear(faltanAhora.map((f) => f.mensaje).join(" • "));
        return;
      }
      await onCrearPedido(confirmado, facturacionTarget);
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? passkeyErrorMessage(err) : "No pudimos enviar el pedido, reintentá.";
      setErrorCrear(msg);
      toast.error(msg, { duration: 6000 });
    } finally {
      setCreando(false);
    }
  }

  const puedeConfirmar =
    !cargando && !errorValidar && !faltaIdentidad && otrosFaltantes.length === 0 && !creando;

  const { address: direccionRetiro } = useBusinessContact();
  // Facturación solo se muestra una vez que la identidad está confirmada —
  // antes de eso el perfil fiscal puede ni estar cargado, y no es un dato
  // que valga la pena mostrar mientras el pedido puede no prosperar.
  const mostrarFacturacion = !cargando && !faltaIdentidad && !!perfilImpuestosLive;

  // #1240: recién cuando corresponde mostrar facturación (identidad resuelta)
  // se trae la lista de perfiles/productoras — evita el viaje si el pedido
  // ni siquiera va a llegar hasta ahí.
  useEffect(() => {
    if (!mostrarFacturacion) return;
    let alive = true;
    Promise.all([listarPerfilesFiscales(), listarProductoras()])
      .then(([p, pr]) => {
        if (!alive) return;
        setPerfilesFiscales(p);
        setProductorasFiscales(pr);
      })
      .catch(() => {
        if (alive) {
          setPerfilesFiscales([]);
          setProductorasFiscales([]);
        }
      });
    return () => {
      alive = false;
    };
  }, [mostrarFacturacion]);

  const hayEleccionFiscal = !!(perfilesFiscales?.length || productorasFiscales?.length);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Área scrolleable — el footer con el botón de confirmar vive AFUERA
          (abajo), fijo, para que un pedido largo no lo empuje fuera de vista:
          no querés tener que scrollear para poder confirmar. */}
      <div className="flex-1 overflow-y-auto overscroll-contain px-5 py-4 sm:px-6">
        <button
          type="button"
          onClick={onBack}
          className="mb-4 flex w-fit items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-ink focus:outline-none focus-visible:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Volver al pedido
        </button>

        <div className="space-y-3">
          <div className="card p-3">
            <div className="mb-1 font-mono text-2xs uppercase tracking-widest text-muted-foreground">
              Fechas
            </div>
            {startDate && endDate ? (
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm font-semibold tabular-nums">
                <span>
                  {format(startDate, "EEE dd MMM", { locale: es })} {startTime}
                </span>
                <span className="text-muted-foreground">→</span>
                <span>
                  {format(endDate, "EEE dd MMM", { locale: es })} {endTime}
                </span>
                <span className="font-mono text-2xs uppercase tracking-wider text-muted-foreground">
                  · {d} {d === 1 ? "jornada" : "jornadas"}
                </span>
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">Sin fechas seleccionadas</div>
            )}

            {/* Detalle del retiro — el horario elegido ya está arriba; acá solo
              dónde retirar (sin link para no sacar al cliente del checkout). */}
            <div className="mt-2 border-t hairline pt-2 text-xs text-muted-foreground">
              Retirás en {direccionRetiro}
            </div>
          </div>

          {/* "Tus datos" + "Facturación" en una sola tarjeta (antes 2 — cada
            borde/padding propio sumaba altura sin aportar separación real:
            son ambos "tu info para este pedido"). */}
          {clienteNombre && (
            <div className="space-y-0.5 card p-3">
              <div className="mb-0.5 font-mono text-2xs uppercase tracking-widest text-muted-foreground">
                Tus datos
              </div>
              <div className="text-sm font-semibold text-ink">{nombreLegal || clienteNombre}</div>
              {emailComunicacion && (
                <div className="text-sm text-muted-foreground">{emailComunicacion}</div>
              )}
              {telefonoContacto && (
                <div className="text-sm text-muted-foreground">{telefonoContacto}</div>
              )}
              {direccionLegal && (
                <div className="text-sm text-muted-foreground">{direccionLegal}</div>
              )}

              {mostrarFacturacion && perfilImpuestosLive && (
                <div className="mt-2 flex items-center justify-between gap-2 border-t hairline pt-2">
                  <div className="text-sm">
                    <span className="font-semibold text-ink">
                      {PERFIL_IMPUESTOS_LABEL[perfilImpuestosLive]}
                    </span>
                    <span className="text-muted-foreground">
                      {" "}
                      · {facturaTipoLabel(perfilImpuestosLive)}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setFacturacionOpen(true)}
                    className="shrink-0 text-2xs text-muted-foreground underline underline-offset-2 hover:text-ink"
                  >
                    Modificar
                  </button>
                </div>
              )}

              {/* #1240: elegir a nombre de quién facturar ESTE pedido — solo si
                hay algo entre qué elegir (más de un CUIT propio y/o una
                productora vinculada); si no, el default de la cuenta de
                arriba es la única opción y no hace falta el selector. */}
              {mostrarFacturacion && hayEleccionFiscal && (
                <div className="mt-2 space-y-1.5 border-t hairline pt-2">
                  <div className="font-mono text-2xs uppercase tracking-widest text-muted-foreground">
                    Facturar a nombre de
                  </div>
                  <RadioGroup
                    value={
                      facturacionTarget.perfilFiscalId
                        ? `perfil-${facturacionTarget.perfilFiscalId}`
                        : facturacionTarget.productoraId
                          ? `productora-${facturacionTarget.productoraId}`
                          : "default"
                    }
                    onValueChange={(v) => {
                      if (v === "default") return setFacturacionTarget({});
                      const [tipo, idStr] = v.split("-");
                      const id = Number(idStr);
                      return tipo === "perfil"
                        ? setFacturacionTarget({ perfilFiscalId: id })
                        : setFacturacionTarget({ productoraId: id });
                    }}
                    className="gap-1.5"
                  >
                    <label className="flex items-center gap-2 text-sm text-ink">
                      <RadioGroupItem value="default" />
                      Mi cuenta (default)
                    </label>
                    {perfilesFiscales?.map((p) => (
                      <label
                        key={`perfil-${p.id}`}
                        className="flex items-center gap-2 text-sm text-ink"
                      >
                        <RadioGroupItem value={`perfil-${p.id}`} />
                        {p.etiqueta || p.razon_social || p.cuit}
                      </label>
                    ))}
                    {productorasFiscales?.map((pr) => (
                      <label
                        key={`productora-${pr.id}`}
                        className="flex items-center gap-2 text-sm text-ink"
                      >
                        <RadioGroupItem value={`productora-${pr.id}`} />
                        {pr.razon_social || pr.cuit}
                      </label>
                    ))}
                  </RadioGroup>
                </div>
              )}
            </div>
          )}

          {/* Documentos — antes esto se enfocaba solo en "Leer contrato"; ahora
            nombra y describe brevemente los 4 documentos que va a encontrar en
            su portal apenas confirme, para que sepa bien qué esperar (no solo
            el contrato). El contrato sigue siendo el único leíble ACÁ, antes
            de confirmar — por eso conserva su link propio en la fila. */}
          <div className="space-y-2 card p-3">
            <div className="font-mono text-2xs uppercase tracking-widest text-muted-foreground">
              Documentos de tu pedido
            </div>
            <p className="text-xs text-muted-foreground">
              En tu portal vas a encontrar estos documentos apenas hagas el pedido:
            </p>
            <ul className="space-y-1.5">
              {DOCS_CHECKOUT.map((tipo) => (
                <li key={tipo} className="flex items-start justify-between gap-3">
                  <div className="text-sm leading-snug">
                    <span className="font-semibold text-ink">{DOC_LABEL[tipo]}</span>
                    {DOC_DESCRIPTION[tipo] && (
                      <span className="text-muted-foreground"> — {DOC_DESCRIPTION[tipo]}</span>
                    )}
                  </div>
                  {tipo === "contrato" && (
                    <button
                      type="button"
                      onClick={() => setContratoOpen(true)}
                      className="shrink-0 text-xs text-muted-foreground underline underline-offset-2 hover:text-ink"
                    >
                      Leer contrato ahora
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>

          {/* Disclaimer de responsabilidad/seguro — debajo de los documentos
            (antes arriba): recién ahí el cliente ya sabe que existe el
            "Detalle de seguro" que este párrafo menciona, así que el orden de
            lectura tiene más sentido. Tiene que leerse igual, no pasar
            desapercibido: rojo suave del DS (mismo token que los alerts de
            error) y tamaño de texto normal (no letra chica). */}
          <div className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
            <p className="text-sm leading-relaxed text-destructive">
              A partir del retiro, sos responsable por daños evitables, pérdida o robo del equipo —
              te recomendamos contratar un seguro propio para tus producciones. Encontrás el Detalle
              de seguro en la sección de documentos de tu perfil apenas hacés el pedido (es
              provisorio hasta que lo confirmemos). Al confirmar aceptás nuestros{" "}
              <button
                type="button"
                onClick={() => setTerminosOpen(true)}
                className="underline underline-offset-2 hover:text-ink"
              >
                Términos y Condiciones
              </button>
              .
            </p>
          </div>

          {/* Consentimiento para avisarle por WhatsApp. Va acá, junto al resto de
            lo que acepta al confirmar: Meta exige un OK explícito del cliente —
            no alcanza con que haya cargado un teléfono. */}
          <OptInWhatsApp className="rounded-lg border border-hairline px-3 py-2.5" />

          {cargando && (
            <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
              <Spinner size="sm" />
              Revisando tu pedido…
            </div>
          )}

          {errorValidar && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{errorValidar}</span>
              <button
                onClick={() => void revalidar()}
                className="ml-auto shrink-0 underline underline-offset-2"
              >
                Reintentar
              </button>
            </div>
          )}

          {/* Identidad — única excepción que no se resuelve en el mismo click (exige
            salir a Didit). Reusa el panel existente (distingue no-verificado/
            en-revisión/rechazado); el botón de confirmar abajo queda deshabilitado
            mientras tanto. */}
          {!cargando && faltaIdentidad && (
            <VerificacionRequeridaPanel
              estado={identidadEstado}
              motivo={identidadMotivo}
              iniciando={iniciandoVerif}
              onVerificar={resolverIdentidad}
            />
          )}

          {/* Cualquier otro faltante (carrito/fechas/stock/precio/contacto/antelación…):
            no tiene una resolución automática acá — el mensaje del backend YA dice
            qué hacer. Un solo "Volver al carrito" al final (no uno por mensaje: son
            la misma acción repetida, y con 2+ faltantes simultáneos quedaban varios
            botones idénticos apilados). */}
          {!cargando && otrosFaltantes.length > 0 && (
            <div className="space-y-2">
              {otrosFaltantes.map((f) => (
                <div
                  key={f.check}
                  role="alert"
                  className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive"
                >
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span className="flex-1">{f.mensaje}</span>
                </div>
              ))}
              <button
                onClick={onBack}
                className="text-sm font-medium text-destructive underline underline-offset-2"
              >
                Volver al carrito
              </button>
            </div>
          )}

          {errorCrear && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{errorCrear}</span>
            </div>
          )}
        </div>
      </div>

      {/* Footer fijo — mismo criterio que el paso "carrito" (footer sticky con
        totales). El Total vive ACÁ (no en una tarjeta más arriba en el
        scroll): es el dato que más importa para decidir + el botón, así que
        tiene que verse siempre sin scrollear, sea cual sea la altura de las
        tarjetas de arriba. */}
      <div
        className="border-t hairline bg-background px-5 py-3 sm:px-6"
        style={{ paddingBottom: "max(1rem, env(safe-area-inset-bottom))" }}
      >
        <div className="mb-2.5 space-y-1">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              Subtotal · {itemCount} {itemCount === 1 ? "ítem" : "ítems"} · {d}{" "}
              {d === 1 ? "jornada" : "jornadas"}
            </span>
            <span className="tabular">{formatARS(subtotalTotal)}</span>
          </div>
          {descuentoPct > 0 && (
            <div className="flex items-center justify-between text-xs text-verde-ink">
              <span>
                {descuentoLabel(descuentoOrigen, d, clienteNombre)} · {descuentoPct}%
              </span>
              <span className="tabular">−{formatARS(descuentoMonto)}</span>
            </div>
          )}
          <div className="flex items-center justify-between border-t hairline pt-1.5">
            <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              Total
            </span>
            <span className="font-display text-2xl tabular text-ink">
              {formatARS(totalNeto)}
              {conIva && (
                <span className="ml-1 align-baseline font-sans text-sm text-muted-foreground">
                  {" "}
                  + IVA
                </span>
              )}
            </span>
          </div>
        </div>
        <Button
          variant="amber"
          size="lg"
          className="w-full uppercase tracking-widest"
          disabled={!puedeConfirmar}
          loading={creando}
          onClick={() => void handleConfirmar()}
        >
          {creando ? (
            "Enviando…"
          ) : (
            <span className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4" />
              Confirmar pedido
            </span>
          )}
        </Button>
      </div>

      <FacturacionModal
        open={facturacionOpen}
        onOpenChange={setFacturacionOpen}
        onPerfilChange={(p) =>
          setPerfilImpuestosLive((p.perfil_impuestos ?? null) as PerfilImpuestos | null)
        }
      />
      <TerminosModal open={terminosOpen} onOpenChange={setTerminosOpen} />
      <ContratoPreviewModal
        open={contratoOpen}
        onOpenChange={setContratoOpen}
        sessionId={sessionId}
        facturacionTarget={facturacionTarget}
      />
    </div>
  );
}
