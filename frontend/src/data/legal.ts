/**
 * Textos de las páginas legales — Política de privacidad y Términos.
 *
 * Generados como punto de partida razonable para Rambla Rental (Mar del
 * Plata, Argentina). Cubren Ley 25.326 de Protección de Datos Personales
 * (AAIP) y el flujo básico de alquiler de equipos audiovisuales.
 *
 * ⚠️ IMPORTANTE: estos textos son un DRAFT. Antes de hacer el sitio
 * 100% público, **consultar con abogado** para validar:
 * - Que la política de privacidad cumple Ley 25.326 + Disposición 11/2006.
 * - Si aplica GDPR (clientes de la UE) → necesita ajustes.
 * - Los términos de uso (cláusula de cancelación, daños, seguro) son
 *   aceptables jurisdiccionalmente.
 *
 * Última revisión: 2026-05-11.
 *
 * `TALLER_TERMS_SECTIONS` (2026-08-20) es el mismo tipo de DRAFT, para el
 * fallback que ve quien se inscribe a un taller sin `terminos` propio
 * cargado (antes caía en los términos de RENTAL — depósito/daños de
 * equipos/seguro, nada relacionado). Un taller puede seguir sobreescribiendo
 * con su propio texto vía el campo `terminos` del admin.
 */

import { CONTACT } from "@/data/contact";

export const LAST_UPDATED = "11 de mayo de 2026";
// Fecha propia — TALLER_TERMS_SECTIONS se escribió en otra fecha que
// LAST_UPDATED (Rental); reusar esa constante mostraría una fecha vieja
// sobre contenido nuevo.
export const LAST_UPDATED_TALLERES = "20 de agosto de 2026";

// ── Política de privacidad ─────────────────────────────────────────────────

export type Section = {
  id: string;
  title: string;
  content: string;
};

export const PRIVACY_SECTIONS: Section[] = [
  {
    id: "intro",
    title: "1. Introducción",
    content: `Esta política describe cómo Rambla Rental ("nosotros", "el rental")
recolecta, usa y protege la información personal de quienes visitan el sitio web
y de los clientes que reservan equipos. Cumplimos con la Ley 25.326 de Protección
de Datos Personales de Argentina y con la Disposición 11/2006 de la AAIP.`,
  },
  {
    id: "que-datos",
    title: "2. Qué datos recolectamos",
    content: `Para reservar equipos necesitamos: nombre y apellido, email, teléfono,
dirección, CUIT o CUIL (si pedís factura), y opcionalmente datos de identidad
(DNI) al momento del retiro. También guardamos el historial de tus pedidos.

Cuando navegás el catálogo sin estar registrado, no recolectamos datos personales
identificables, salvo cookies técnicas necesarias para el funcionamiento del
sitio (sesión, carrito).`,
  },
  {
    id: "para-que",
    title: "3. Para qué usamos tus datos",
    content: `Tus datos se usan exclusivamente para:
- Procesar tu reserva y emitir documentos (cotización, remito, contrato, albarán).
- Comunicarnos con vos sobre el alquiler (confirmaciones, recordatorios, devolución).
- Cumplir obligaciones fiscales (facturación).
- Mejorar el servicio (analizar qué equipos se alquilan más).

No vendemos ni compartimos tus datos con terceros con fines de marketing.`,
  },
  {
    id: "con-quien",
    title: "4. Con quién compartimos",
    content: `Tus datos pueden compartirse con:
- **AFIP** si nos solicita información para verificación fiscal.
- **Proveedores de infraestructura** (Railway para hosting, Cloudflare R2 para
fotos, Google para autenticación). Estos prestadores procesan datos en nombre
nuestro y bajo nuestras instrucciones.
- **Autoridades judiciales** si hay orden judicial.

Nunca compartimos tus datos con empresas de marketing o publicidad.`,
  },
  {
    id: "cuanto-tiempo",
    title: "5. Cuánto tiempo guardamos tus datos",
    content: `Los datos del perfil del cliente se conservan mientras tu cuenta esté
activa. Si pedís darte de baja, los borramos en un plazo máximo de 30 días,
salvo los datos fiscales que la ley nos obliga a conservar 10 años (facturas
y comprobantes de operaciones).`,
  },
  {
    id: "tus-derechos",
    title: "6. Tus derechos",
    content: `Tenés derecho a:
- **Acceder** a los datos personales que tenemos sobre vos.
- **Rectificar** datos incorrectos o desactualizados.
- **Suprimir** tus datos (con las excepciones fiscales mencionadas).
- **Solicitar limitación** del tratamiento.
- **Portabilidad**: pedir tus datos en un formato legible.

Para ejercer cualquier derecho, escribinos a ${CONTACT.email}. Respondemos en
un máximo de 10 días hábiles. También podés presentar reclamos ante la AAIP
(Agencia de Acceso a la Información Pública) si considerás que tus derechos
fueron vulnerados.`,
  },
  {
    id: "seguridad",
    title: "7. Seguridad",
    content: `Aplicamos medidas técnicas razonables para proteger tus datos:
conexiones cifradas (HTTPS), control de acceso al back-office, backups periódicos,
y monitoreo de errores. Sin embargo, ningún sistema es 100% inviolable —
te avisaremos en caso de incidente que pueda afectar tus datos personales.`,
  },
  {
    id: "cookies",
    title: "8. Cookies",
    content: `Usamos cookies estrictamente necesarias para el funcionamiento del sitio
(sesión, carrito de equipos). No usamos cookies de tracking publicitario ni
analytics de terceros con identificación personal. Si esto cambia, lo
informaremos en esta página.`,
  },
  {
    id: "cambios",
    title: "9. Cambios a esta política",
    content: `Podemos actualizar esta política cuando cambien nuestras prácticas o la
legislación aplicable. La fecha de última actualización está al inicio de
esta página. Cambios sustantivos se notifican a los clientes por email.`,
  },
  {
    id: "contacto",
    title: "10. Contacto",
    content: `Para consultas, reclamos o ejercer tus derechos sobre tus datos:

- Email: ${CONTACT.email}
- WhatsApp: ${CONTACT.phoneDisplay}
- Dirección: ${CONTACT.address.line2 || CONTACT.address.city}, ${CONTACT.address.country}

Responsable del tratamiento: Rambla Rental.`,
  },
];

// ── Términos y condiciones ─────────────────────────────────────────────────

export const TERMS_SECTIONS: Section[] = [
  {
    id: "intro",
    title: "1. Aceptación",
    content: `Al reservar equipos en Rambla Rental, aceptás estos términos y condiciones.
Si no estás de acuerdo, no completes la reserva. Rambla Rental se reserva el
derecho de modificar estos términos en cualquier momento; la versión vigente
es la publicada en el sitio al momento de la reserva.`,
  },
  {
    id: "que-es",
    title: "2. Qué es Rambla Rental",
    content: `Rambla Rental es un servicio de alquiler de equipos audiovisuales
(cámaras, lentes, iluminación, audio, soportes) y de un estudio de foto/video
ubicado en Mar del Plata, Argentina. Todo equipo es propiedad de Rambla
Rental o de socios autorizados.`,
  },
  {
    id: "reserva",
    title: "3. Reserva y confirmación",
    content: `El proceso es:
1. **Cotización**: agregás equipos al carrito y elegís fechas. Te confirmamos
disponibilidad y total estimado.
2. **Confirmación**: para reservar firme, pedimos seña (20% del total) por
transferencia bancaria o MercadoPago. La seña se descuenta del pago final.
3. **Retiro**: el día acordado pasás por el local. Firmamos remito + contrato
y revisamos los equipos juntos antes de salir.
4. **Devolución**: traés los equipos en la fecha pactada. Revisamos juntos.
Si todo está bien, te devolvemos el depósito (si aplica) y te emitimos el
comprobante final.

Las cotizaciones tienen una validez de **7 días corridos** desde la emisión.`,
  },
  {
    id: "precios",
    title: "4. Precios y formas de pago",
    content: `Los precios listados son por **jornada de 24 horas**. Una "jornada" se
contabiliza desde la hora de retiro hasta la misma hora del día siguiente.

Aceptamos:
- Transferencia bancaria (recomendado para mejor cotización).
- MercadoPago.
- Efectivo al momento del retiro.

El total se paga al retirar los equipos. Demoras en el pago aplican recargo
del 0.5% diario.`,
  },
  {
    id: "deposito",
    title: "5. Depósito en garantía",
    content: `Para equipos de mayor valor o clientes nuevos, podemos solicitar un depósito
en garantía adicional, que se devuelve íntegramente al regresar los equipos
en buenas condiciones. El monto se acuerda al momento de la reserva.

Para clientes habituales con buen historial podemos exceptuar este requisito.`,
  },
  {
    id: "documentacion",
    title: "6. Documentación requerida",
    content: `Al momento del retiro pedimos:
- DNI vigente del responsable.
- Para clientes nuevos: un segundo documento (puede ser carnet de conducir,
pasaporte o credencial profesional).
- Comprobante de la seña pagada.

Si vas a alquilar a nombre de una empresa o productora, traer también: CUIT,
constancia de inscripción AFIP y autorización firmada por el responsable
legal si quien retira no es el firmante.`,
  },
  {
    id: "uso",
    title: "7. Uso correcto de los equipos",
    content: `Los equipos se entregan en perfecto estado de funcionamiento, verificado al
momento del retiro. Te comprometés a:

- Usarlos exclusivamente para producciones audiovisuales profesionales o personales.
- No subalquilar, prestar ni transferir a terceros sin autorización escrita.
- Operar los equipos vos mismo o con personal técnico idóneo.
- No trasladar los equipos a más de 100 km de Mar del Plata sin acuerdo previo.
- Protegerlos de daños evitables (lluvia, golpes, robo).`,
  },
  {
    id: "daños",
    title: "8. Daños, pérdida y robo",
    content: `Sos responsable de los equipos desde el momento del retiro hasta la devolución.

- **Uso normal**: el desgaste razonable está cubierto por nosotros.
- **Daños evitables, mal uso, negligencia**: te cobramos la reparación o
reposición según corresponda. El valor de reposición está detallado en el
albarán que firmás al retirar.
- **Pérdida o robo**: 100% de tu responsabilidad. Recomendamos contratar
un seguro propio para producciones grandes.

En caso de daño o pérdida, avisanos lo antes posible para coordinar reparación
o reposición.`,
  },
  {
    id: "seguro",
    title: "9. Seguro",
    content: `Los equipos están cubiertos por nuestro seguro mientras están en nuestro
local. Una vez retirados, NO tienen seguro en tránsito ni durante el uso
externo.

Para producciones que requieran seguro técnico específico, podemos ayudarte
a contratar uno por la fecha del rodaje. Consultar antes de la reserva.`,
  },
  {
    id: "cancelacion",
    title: "10. Cancelación y modificaciones",
    content: `Cancelaciones y cambios de fechas:
- **Hasta 48 hs antes del retiro**: sin costo. Se devuelve la seña íntegra.
- **Entre 48 hs y 24 hs antes**: se descuenta el 50% de la seña.
- **Menos de 24 hs antes o no-show**: se pierde la seña completa.

Cambios de equipos dentro de la misma fecha: sin costo, sujeto a disponibilidad.`,
  },
  {
    id: "devolucion",
    title: "11. Devolución tardía",
    content: `Si demorás la devolución más de 2 horas sobre el horario acordado, sin aviso
previo, se cobra una jornada completa adicional. Demoras mayores acumulan
una jornada por cada 24 horas o fracción.

Si tenés un imprevisto, avisanos por WhatsApp lo antes posible — buscamos
soluciones flexibles cuando hay buena comunicación.`,
  },
  {
    id: "facturacion",
    title: "12. Facturación",
    content: `Emitimos factura B (consumidor final) o factura A (responsables inscriptos)
según corresponda. La factura se entrega al finalizar el alquiler con el pago
saldado.`,
  },
  {
    id: "jurisdiccion",
    title: "13. Jurisdicción",
    content: `Cualquier disputa derivada de estos términos se somete a la competencia
ordinaria de los Tribunales del Departamento Judicial de Mar del Plata, con
renuncia a cualquier otro fuero o jurisdicción que pudiera corresponder.`,
  },
  {
    id: "contacto-terms",
    title: "14. Contacto",
    content: `Para consultas sobre estos términos:

- Email: ${CONTACT.email}
- WhatsApp: ${CONTACT.phoneDisplay}
- Dirección: Rambla Rental, ${CONTACT.address.line2 || CONTACT.address.city}, ${CONTACT.address.country}`,
  },
];

// ── Términos y condiciones de Talleres (Escuela) ──────────────────────────

export const TALLER_TERMS_SECTIONS: Section[] = [
  {
    id: "intro",
    title: "1. Aceptación",
    content: `Al inscribirte a un taller de Rambla aceptás estos términos y condiciones.
Si un taller en particular tiene condiciones propias (cargadas en su página),
esas rigen sobre este documento general. Rambla se reserva el derecho de
modificar estos términos en cualquier momento; la versión vigente es la
publicada en el sitio al momento de la inscripción.`,
  },
  {
    id: "que-es",
    title: "2. Qué es un taller de Rambla",
    content: `Los talleres son actividades de formación práctica en producción
audiovisual, dictadas por Rambla y/o instituciones y docentes invitados
(ej. escuelas de cine co-presentadoras), en Mar del Plata, Argentina.`,
  },
  {
    id: "inscripcion",
    title: "3. Inscripción y cupos",
    content: `Tu inscripción queda pendiente hasta confirmar tu lugar (pagando la seña y
subiendo el comprobante). Si el cupo está completo, quedás en lista de
espera; si se libera un lugar, te avisamos y tenés un tiempo limitado para
confirmarlo — pasado ese plazo, el cupo pasa al siguiente de la lista.`,
  },
  {
    id: "pago",
    title: "4. Pago y forma de pago",
    content: `Aceptamos transferencia bancaria. Según el taller, podés pagar el total de
una vez o en cuotas — las opciones disponibles se muestran al inscribirte.
Para reservar tu lugar pedimos la seña indicada en la página del taller;
subís el comprobante y confirmamos tu cupo.`,
  },
  {
    id: "cancelacion",
    title: "5. Cancelación",
    content: `Una vez confirmada la inscripción, la seña/pago no tiene devolución. Si
tenés un imprevisto, escribinos por WhatsApp — buscamos soluciones
flexibles cuando hay buena comunicación (ej. ceder tu lugar a otra persona,
si el taller lo permite).`,
  },
  {
    id: "equipamiento",
    title: "6. Uso de equipos y estudio durante las clases",
    content: `El equipamiento e instalaciones que se usan durante las clases del taller
están incluidos y cubiertos por Rambla — no se cobra a los alumnos por
daños accidentales del uso normal de la actividad.`,
  },
  {
    id: "imagen",
    title: "7. Derecho de imagen",
    content: `Al inscribirte autorizás a Rambla a usar fotos y videos tomados durante las
clases y los proyectos realizados en el taller, para redes sociales y
material de marketing de Rambla y de las instituciones co-presentadoras. Si
preferís no aparecer, avisanos antes de que empiece el taller.`,
  },
  {
    id: "jurisdiccion-talleres",
    title: "8. Jurisdicción",
    content: `Cualquier disputa derivada de estos términos se somete a la competencia
ordinaria de los Tribunales del Departamento Judicial de Mar del Plata, con
renuncia a cualquier otro fuero o jurisdicción que pudiera corresponder.`,
  },
  {
    id: "contacto-terms-talleres",
    title: "9. Contacto",
    content: `Para consultas sobre estos términos:

- Email: ${CONTACT.email}
- WhatsApp: ${CONTACT.phoneDisplay}
- Dirección: Rambla, ${CONTACT.address.line2 || CONTACT.address.city}, ${CONTACT.address.country}`,
  },
];
