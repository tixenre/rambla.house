"""Sincronización (insert/upsert) de clases y modalidades de pago de una
edición de taller — move-verbatim desde `routes/talleres.py`. Consumidas por
`services.talleres.commands.ediciones` (alta) y por `admin_update_edicion`
(edición, se queda en el route)."""


def _insert_clases(conn, edicion_id: int, clases: list, start_orden: int = 0) -> None:
    """`start_orden` corrige la posición cuando `clases` es un sub-tramo (una
    sola clase nueva en medio de un upsert) — sin esto, cada llamada volvería
    a numerar desde 0 en vez de respetar su posición real en la lista completa."""
    for i, c in enumerate(clases, start=start_orden):
        conn.execute(
            "INSERT INTO clases_taller (edicion_id, fecha, hora_inicio_min, hora_fin_min, "
            "titulo, descripcion, nota, portada_media_id, portada_url, orden) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                edicion_id, c["fecha"], c["hora_inicio_min"], c["hora_fin_min"],
                c.get("titulo", ""), c.get("descripcion", ""), c.get("nota", ""),
                c.get("portada_media_id"), c.get("portada_url", ""), i,
            ),
        )


def _upsert_clases(conn, edicion_id: int, clases: list) -> None:
    """Sincroniza las clases de una edición SIN el delete+insert ciego de antes:
    - con `id` (y perteneciente a la edición) → UPDATE de fecha/horario/contenido
      — la PORTADA no se toca (solo cambia vía sus endpoints de upload/delete);
    - sin `id` → INSERT (acá sí puede traer portada_* — caso "copiar clases");
    - ids existentes que no vienen en la lista → DELETE.
    Preserva `portada_media_id` al reordenar/editar (el delete+insert la perdía).
    `orden` = posición en `clases` (el array que manda el front) — no lo decide
    el front con un campo explícito, ya viene implícito en el orden de la lista."""
    existentes = {
        r["id"]
        for r in conn.execute(
            "SELECT id FROM clases_taller WHERE edicion_id = %s", (edicion_id,)
        ).fetchall()
    }
    vistos: set[int] = set()
    for i, c in enumerate(clases):
        cid = c.get("id")
        if cid and cid in existentes:
            conn.execute(
                "UPDATE clases_taller SET fecha = %s, hora_inicio_min = %s, "
                "hora_fin_min = %s, titulo = %s, descripcion = %s, nota = %s, "
                "orden = %s WHERE id = %s AND edicion_id = %s",
                (
                    c["fecha"], c["hora_inicio_min"], c["hora_fin_min"],
                    c.get("titulo", ""), c.get("descripcion", ""), c.get("nota", ""),
                    i, cid, edicion_id,
                ),
            )
            vistos.add(cid)
        else:
            _insert_clases(conn, edicion_id, [c], start_orden=i)
    sobrantes = existentes - vistos
    for cid in sobrantes:
        conn.execute(
            "DELETE FROM clases_taller WHERE id = %s AND edicion_id = %s",
            (cid, edicion_id),
        )


def _upsert_modalidades(conn, edicion_id: int, modalidades: list) -> None:
    """Sincroniza las modalidades de pago de una edición (mismo patrón que
    _upsert_clases): con `id` → UPDATE; sin `id` → INSERT; ids que no vienen
    en la lista → DELETE. El `orden` es la posición en la lista recibida."""
    existentes = {
        r["id"]
        for r in conn.execute(
            "SELECT id FROM edicion_modalidades_pago WHERE edicion_id = %s", (edicion_id,)
        ).fetchall()
    }
    vistos: set[int] = set()
    for orden, m in enumerate(modalidades):
        mid = m.get("id")
        if mid and mid in existentes:
            conn.execute(
                "UPDATE edicion_modalidades_pago SET orden = %s, codigo = %s, "
                "label = %s, nota = %s, monto_total = %s, n_cuotas = %s "
                "WHERE id = %s AND edicion_id = %s",
                (
                    orden,
                    m["codigo"],
                    m["label"],
                    m["nota"],
                    m["monto_total"],
                    m["n_cuotas"],
                    mid,
                    edicion_id,
                ),
            )
            vistos.add(mid)
        else:
            conn.execute(
                "INSERT INTO edicion_modalidades_pago "
                "(edicion_id, orden, codigo, label, nota, monto_total, n_cuotas) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    edicion_id,
                    orden,
                    m["codigo"],
                    m["label"],
                    m["nota"],
                    m["monto_total"],
                    m["n_cuotas"],
                ),
            )
    sobrantes = existentes - vistos
    for mid in sobrantes:
        conn.execute(
            "DELETE FROM edicion_modalidades_pago WHERE id = %s AND edicion_id = %s",
            (mid, edicion_id),
        )
