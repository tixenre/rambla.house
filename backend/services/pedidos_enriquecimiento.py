"""services.pedidos_enriquecimiento — enriquecer un `pedido: dict` con datos de items/cliente.

Extraído de `routes/alquileres/core.py` (auditoría cruzada de plata, 2026-07-02, encontró que
`services/facturacion/engine.py::_get_pedido` importaba estos helpers directo de un ROUTE — un
service no debería depender de un route, mismo motivo por el que `desglose_de_pedido` ya se había
movido a `services.finanzas_flujo.pedido`). Move-verbatim: mismo comportamiento, sin reescribir
lógica — `routes/alquileres/core.py` reexporta estos nombres para no tocar sus ~8 call-sites
existentes (routes de alquileres/portal cliente); código nuevo debería importar de acá directo."""
from database import row_to_dict, MARCA_SUBQUERY, marca_subquery
from clientes.queries.identidad import nombre_legal
from identity.contacts import contactos_verificados_batch, email_comunicacion, telefono_contacto


def _batch_get_alquiler_items(conn, pedido_ids: list[int]) -> dict[int, list[dict]]:
    """Trae items de múltiples pedidos en 2 queries en lugar de N+1.

    Retorna {pedido_id: [items...]} donde cada item ya tiene su lista 'componentes'.
    """
    if not pedido_ids:
        return {}

    ph = ",".join(["%s"] * len(pedido_ids))
    rows = conn.execute(f"""
        SELECT pi.*, COALESCE(e.nombre, pi.nombre_libre) AS nombre,
               {MARCA_SUBQUERY},
               e.modelo, e.serie, e.valor_reposicion,
               e.foto_url, e.foto_url_sm, e.foto_url_thumb, e.cantidad AS stock_total,
               e.nombre_publico, e.nombre_publico_largo, e.tipo AS equipo_tipo
        FROM alquiler_items pi
        LEFT JOIN equipos e ON e.id = pi.equipo_id
        WHERE pi.pedido_id IN ({ph})
        ORDER BY pi.orden, pi.id
    """, pedido_ids).fetchall()

    all_items   = [row_to_dict(r) for r in rows]
    # Las líneas personalizadas (#805) no tienen equipo → fuera del set de kits.
    equipo_ids  = list({item["equipo_id"] for item in all_items if item["equipo_id"] is not None})
    comp_map: dict[int, list[dict]] = {eid: [] for eid in equipo_ids}

    if equipo_ids:
        cph = ",".join(["%s"] * len(equipo_ids))
        comp_rows = conn.execute(f"""
            SELECT kc.*, ec.nombre, {marca_subquery('ec')}, ec.foto_url, ec.foto_url_sm, ec.foto_url_thumb, ec.cantidad AS stock_total,
                   ec.modelo, ec.serie, ec.valor_reposicion,
                   ec.nombre_publico, ec.nombre_publico_largo
            FROM kit_componentes kc
            JOIN equipos ec ON ec.id = kc.componente_id
            WHERE kc.equipo_id IN ({cph})
        """, equipo_ids).fetchall()
        for c in comp_rows:
            cd = row_to_dict(c)
            comp_map[cd["equipo_id"]].append(cd)

    result: dict[int, list[dict]] = {pid: [] for pid in pedido_ids}
    for item in all_items:
        item["componentes"] = comp_map.get(item["equipo_id"], [])
        result[item["pedido_id"]].append(item)

    return result


def _batch_count_turnos_vinculados(conn, pedido_ids: list[int]) -> dict[int, int]:
    """Cuenta, por pedido principal, cuántos turnos del Estudio tiene
    vinculados (`pedido_principal_id`) — para el badge de la lista de
    pedidos, en 1 query en vez de N+1. Un turno cancelado no cuenta (mismo
    criterio que la cascada de estado y el reparto de pago combinado, que
    también lo excluyen)."""
    if not pedido_ids:
        return {}

    ph = ",".join(["%s"] * len(pedido_ids))
    rows = conn.execute(f"""
        SELECT pedido_principal_id, COUNT(*) AS cnt
        FROM alquileres
        WHERE pedido_principal_id IN ({ph}) AND estado <> 'cancelado'
        GROUP BY pedido_principal_id
    """, pedido_ids).fetchall()
    return {r["pedido_principal_id"]: r["cnt"] for r in rows}


def _batch_plata_turnos_vinculados(conn, pedido_ids: list[int]) -> dict[int, tuple[int, int]]:
    """Plata de los turnos del Estudio de cada pedido principal → `(total,
    pagado)`, en 1 query.

    La LISTA de pedidos mostraba solo el `monto_total` de la fila del
    principal: un pedido de $90.000 en equipos + $120.000 de estudio se leía
    "$90.000" aunque su detalle (y la factura, y Cuentas por cobrar) dijeran
    $210.000. Media verdad de plata, la misma clase de bug que el rail que
    mentía al editar la tarifa.

    Suma montos YA persistidos — no recalcula nada (el IVA/descuento de cada
    fila es responsabilidad de su propio motor, ver `services/finanzas_flujo`).
    Mismo filtro de cancelados que el conteo de arriba, el pago combinado y la
    factura combinada."""
    if not pedido_ids:
        return {}

    ph = ",".join(["%s"] * len(pedido_ids))
    rows = conn.execute(f"""
        SELECT pedido_principal_id,
               COALESCE(SUM(monto_total), 0)  AS total,
               COALESCE(SUM(monto_pagado), 0) AS pagado
        FROM alquileres
        WHERE pedido_principal_id IN ({ph}) AND estado <> 'cancelado'
        GROUP BY pedido_principal_id
    """, pedido_ids).fetchall()
    return {r["pedido_principal_id"]: (int(r["total"]), int(r["pagado"])) for r in rows}


_CAMPOS_FISCALES = "perfil_impuestos, razon_social, domicilio_fiscal, email_facturacion, cuit"


def _resolver_datos_fiscales_pedido(
    conn, cliente_id: int, perfil_fiscal_id=None, productora_id=None
) -> dict:
    """Resuelve los 5 campos fiscales de UN pedido con 3 niveles de prioridad
    (#1240 — perfiles fiscales múltiples + productoras): **productora elegida**
    > **perfil personal elegido** > **perfil default de la cuenta** (`clientes`,
    comportamiento de siempre). Devuelve `{perfil_impuestos, razon_social,
    domicilio_fiscal, email_facturacion, cuit}` — mismas claves que el SELECT
    directo a `clientes` que reemplaza, para que los call sites existentes (que
    leen `cliente_perfil_impuestos`/`cliente_cuit`/etc. ya resueltos en el dict
    de pedido) no necesiten cambiar. `perfil_fiscal_id`/`productora_id` NULL =
    comportamiento de hoy sin ningún cambio."""
    if productora_id:
        row = conn.execute(
            f"SELECT {_CAMPOS_FISCALES} FROM productoras WHERE id = %s",
            (productora_id,),
        ).fetchone()
        if row:
            return row_to_dict(row)
    if perfil_fiscal_id:
        row = conn.execute(
            f"""SELECT {_CAMPOS_FISCALES} FROM cliente_perfiles_fiscales
                WHERE id = %s AND cliente_id = %s""",
            (perfil_fiscal_id, cliente_id),
        ).fetchone()
        if row:
            return row_to_dict(row)
    row = conn.execute(
        f"SELECT {_CAMPOS_FISCALES} FROM clientes WHERE id = %s",
        (cliente_id,),
    ).fetchone()
    return row_to_dict(row) if row else {}


def _enriquecer_pedido_con_cliente_fiscal(conn, pedido: dict) -> dict:
    """Mergea perfil_impuestos + datos de Factura A del cliente en el pedido.

    Usado por los endpoints de PDF para que `_pedido_html` pueda decidir si
    discriminar IVA (Factura A para Responsable Inscripto). Resuelve vía
    `_resolver_datos_fiscales_pedido` — si el pedido eligió una productora o un
    perfil personal alternativo (`pedido["productora_id"]`/`["perfil_fiscal_id"]`,
    columnas reales de `alquileres`), usa esos datos en vez de los de `clientes`.
    """
    cid = pedido.get("cliente_id")
    if not cid:
        return pedido
    c = _resolver_datos_fiscales_pedido(
        conn, cid, pedido.get("perfil_fiscal_id"), pedido.get("productora_id")
    )
    if not c:
        return pedido
    pedido["cliente_perfil_impuestos"] = c.get("perfil_impuestos")
    pedido["cliente_razon_social"] = c.get("razon_social")
    pedido["cliente_domicilio_fiscal"] = c.get("domicilio_fiscal")
    pedido["cliente_email_facturacion"] = c.get("email_facturacion")
    if c.get("cuit"):
        pedido["cliente_cuit"] = c["cuit"]
    return pedido


def _aplicar_contacto_cliente(
    pedido: dict, c: dict, *, email: str | None = None, telefono: str | None = None
) -> None:
    """Sobrescribe nombre/email/teléfono del pedido con los datos `c` del cliente.

    El nombre: si hay datos RENAPER (identidad verificada), se usa el nombre
    legal confirmado; si no, el nombre ingresado por el cliente.

    El email/teléfono: `email`/`telefono` son el CONTACTO DE COMUNICACIÓN ya
    resuelto por el caller vía `identity.contacts.email_comunicacion`/
    `telefono_contacto` (Google/Didit-OTP en `verified_contacts` vs. columna
    base `clientes.email`/`telefono` — prioridad distinta para cada uno, ver ese
    módulo). Mismo resolvedor que ya usan el portero del checkout, el envío real
    de WhatsApp y el portal del cliente — antes esta función leía `c["email"]`/
    `c["telefono"]` crudos: un cliente cuyo ÚNICO contacto verificado vivía en
    `verified_contacts` (cuenta passkey-only sin Google, o un teléfono
    confirmado por OTP de Didit distinto del autodeclarado) se mostraba "sin
    contacto" acá aunque el sistema SÍ le mandaría WhatsApp/mail. Si el caller
    no resuelve (`email`/`telefono` ausentes), cae a las columnas base de `c` —
    mismo comportamiento de siempre.

    También pone `cliente_dni` si el DNI fue verificado por RENAPER, y
    `cliente_dni_validado_at` para que el back-office pueda mostrar el aviso de
    identidad sin verificar.
    """
    # Nombre: legal de RENAPER si está verificado, si no el base (clientes.queries.identidad).
    pedido["cliente_nombre"] = nombre_legal(c)
    email = email or c.get("email")
    if email:
        pedido["cliente_email"] = email
    telefono = telefono or c.get("telefono")
    if telefono:
        pedido["cliente_telefono"] = telefono
    if c.get("dni"):
        pedido["cliente_dni"] = c["dni"]
    pedido["cliente_dni_validado_at"] = c.get("dni_validado_at")


def _cliente_id_efectivo(conn, pedido: dict) -> int | None:
    """El cliente a mostrar para UN pedido: si es un turno del Estudio vinculado
    (`pedido_principal_id`), el de SU PRINCIPAL EN VIVO — no la foto de
    `cliente_id` que el turno guardó al crearse (`_resolver_pedido_principal`),
    que queda stale si el principal no tenía cliente asignado todavía en ese
    momento y lo consigue después (el turno nunca se re-sincronizaba, aunque
    "el turno hereda SIEMPRE del principal" es la garantía documentada). Si no
    es un turno vinculado, el propio `cliente_id` — sin cambio de comportamiento."""
    principal_id = pedido.get("pedido_principal_id")
    if not principal_id:
        return pedido.get("cliente_id")
    row = conn.execute(
        "SELECT cliente_id FROM alquileres WHERE id = %s", (principal_id,)
    ).fetchone()
    return row["cliente_id"] if row else pedido.get("cliente_id")


def _enriquecer_pedido_con_cliente(conn, pedido: dict) -> dict:
    """Muestra los datos de contacto/identidad SIEMPRE en vivo desde la ficha.

    Los pedidos guardan una foto de nombre/email/teléfono al crearse, pero el
    contacto se muestra con el dato ACTUAL del cliente (decisión 2026-06-06):
    corregir un apellido o un teléfono en la ficha se refleja en todos los
    pedidos del cliente, en cualquier estado, en el back-office y en el portal.
    Si el pedido no tiene cliente vinculado (carga manual) o el cliente ya no
    existe, se conserva la foto. La plata (precio/descuento) NO se toca acá: esa
    sí queda congelada en confirmados/finalizados.
    """
    cid = _cliente_id_efectivo(conn, pedido)
    if not cid:
        return pedido
    row = conn.execute(
        """SELECT nombre, apellido, email, telefono,
                  dni, nombre_renaper, apellido_renaper, dni_validado_at
           FROM clientes WHERE id = %s""",
        (cid,),
    ).fetchone()
    if row:
        _aplicar_contacto_cliente(
            pedido, row_to_dict(row),
            email=email_comunicacion(conn, cid),
            telefono=telefono_contacto(conn, cid),
        )
    return pedido


def _enriquecer_pedidos_con_cliente(conn, pedidos: list[dict]) -> None:
    """Versión batch de `_enriquecer_pedido_con_cliente` para listados (sin N+1) —
    incluye `verified_contacts` batcheado (`identity.contacts.
    contactos_verificados_batch`, 1 query IN(...) más, no reintroduce N+1)."""
    principal_ids = sorted({p["pedido_principal_id"] for p in pedidos if p.get("pedido_principal_id")})
    cliente_id_de_principal: dict[int, int | None] = {}
    if principal_ids:
        ph_p = ",".join(["%s"] * len(principal_ids))
        rows_p = conn.execute(
            f"SELECT id, cliente_id FROM alquileres WHERE id IN ({ph_p})", principal_ids
        ).fetchall()
        cliente_id_de_principal = {r["id"]: r["cliente_id"] for r in rows_p}

    def _efectivo(p: dict) -> int | None:
        principal_id = p.get("pedido_principal_id")
        if principal_id:
            return cliente_id_de_principal.get(principal_id)
        return p.get("cliente_id")

    ids = sorted({cid for p in pedidos if (cid := _efectivo(p))})
    if not ids:
        return
    ph = ",".join(["%s"] * len(ids))
    rows = conn.execute(
        f"""SELECT id, nombre, apellido, email, telefono,
                   dni, nombre_renaper, apellido_renaper, dni_validado_at
            FROM clientes WHERE id IN ({ph})""",
        ids,
    ).fetchall()
    by_id = {r["id"]: row_to_dict(r) for r in rows}
    verificados = contactos_verificados_batch(conn, ids)  # {id: {"email":.., "phone":..}}
    for p in pedidos:
        cid = _efectivo(p)
        c = by_id.get(cid)
        if c:
            v = verificados.get(cid, {})
            # Misma prioridad que email_comunicacion/telefono_contacto
            # (identity/contacts.py) — repetida acá porque llamar al resolver
            # POR CLIENTE reintroduciría el N+1 que este batch existe para evitar.
            _aplicar_contacto_cliente(
                p, c,
                email=c.get("email") or v.get("email"),
                telefono=v.get("phone") or c.get("telefono"),
            )
