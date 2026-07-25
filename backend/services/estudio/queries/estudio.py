"""Lectura de la fila singleton `estudio` (id=1)."""

from fastapi import HTTPException


def _get_estudio_row(conn):
    cur = conn.execute("SELECT * FROM estudio WHERE id = 1")
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Fila estudio no encontrada — ejecutá init_db")
    return row
