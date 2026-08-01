/**
 * Feature flags de la app — apagar/encender features desde un solo lugar, reversible.
 */

/**
 * Descuento (jornadas o cliente, el que gane) visible en el catálogo/ficha
 * ANTES del carrito — precio original tachado + final + label ("−15% por 5
 * días"). Ver `PriceBlock` (equipment/shared).
 *
 * Poner en `false` para revertir al instante si no convence en staging: el
 * catálogo vuelve a mostrar solo el precio de lista, sin tocar nada más — el
 * backend sigue calculando y devolviendo el descuento igual (barato, mismo
 * costo fijo que la disponibilidad), simplemente el front deja de pedirlo/
 * mostrarlo. Nada que revertir en el backend.
 */
export const DESCUENTO_CATALOGO_HABILITADO = true;
