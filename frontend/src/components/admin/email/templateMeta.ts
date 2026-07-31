/**
 * Vocabulario humano de los templates de mail: cómo se llama cada uno en la UI y
 * qué variables se pueden usar al editarlo.
 *
 * Vive aparte de los componentes para que el editor y el log lo compartan sin
 * duplicarlo. Un template sin entry acá se muestra con su `key` cruda (no rompe).
 */

export const TEMPLATE_META: Record<string, { label: string; description: string }> = {
  // ── Pedidos (los dispara el registro de eventos, services/comunicacion) ──
  pedido_creado_cliente: {
    label: "Pedido creado — cliente",
    description: "Confirmación automática al cliente cuando entra un pedido nuevo.",
  },
  pedido_creado_admin: {
    label: "Pedido creado — admin",
    description: "Notificación al equipo cuando entra un pedido nuevo.",
  },
  pedido_confirmado_cliente: {
    label: "Pedido confirmado — cliente",
    description: "Aviso al cliente cuando el admin pasa el pedido a 'confirmado'.",
  },
  recordatorio_retiro: {
    label: "Recordatorio de retiro",
    description: "Recordatorio automático al cliente antes del retiro.",
  },
  // ── Talleres (los manda services/talleres directo, no el registro) ──────
  taller_inscripcion_cliente: {
    label: "Inscripción a un taller — cliente",
    description: "Al inscribirse: le confirma el lugar o le avisa que quedó en lista de espera.",
  },
  taller_inscripcion_admin: {
    label: "Inscripción a un taller — admin",
    description: "Le avisa al equipo que entró una inscripción nueva.",
  },
  taller_sena_confirmada: {
    label: "Seña de taller confirmada",
    description: "Al registrarse la seña: su lugar queda confirmado.",
  },
  taller_cupo_ofrecido: {
    label: "Se liberó un cupo",
    description: "A quien está en lista de espera cuando se libera un lugar.",
  },
  taller_cambio_datos: {
    label: "Cambio de datos de un taller",
    description: "Aviso a los inscriptos cuando cambian fecha, horario o lugar.",
  },
  taller_interesado_nueva_edicion: {
    label: "Nueva edición de un taller",
    description: "A quienes dejaron su interés cuando se abre una edición nueva.",
  },
};

/**
 * Variables comunes de los mails de pedido. Mantener en sincronía con
 * `pedido_email_context()` en backend/services/comunicacion/despacho.py.
 */
export const AVAILABLE_VARS: { name: string; help: string }[] = [
  { name: "cliente_nombre", help: "Nombre completo del cliente" },
  { name: "cliente_email", help: "Email del cliente" },
  { name: "cliente_telefono", help: "Teléfono del cliente" },
  { name: "numero_pedido", help: "Número público del pedido" },
  { name: "fecha_desde", help: "Fecha de retiro" },
  { name: "fecha_hasta", help: "Fecha de devolución" },
  { name: "total", help: "Monto total del pedido" },
  { name: "notas", help: "Notas que dejó el cliente" },
  { name: "items_html", help: "Lista de equipos como tabla HTML" },
  { name: "items_text", help: "Lista de equipos como texto plano" },
  { name: "admin_url", help: "Link al pedido en el back-office (solo admin)" },
  { name: "portal_url", help: "Link al portal del cliente (seguir el pedido)" },
  { name: "dias_antes", help: "Días de anticipación (solo recordatorio)" },
];
