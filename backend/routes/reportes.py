"""routes/reportes.py — Generador de reportes financieros (#88).

Liquidación por dueño: cuánto entró (pedidos 100% pagados, fechados al día en que
quedaron saldados) y cómo se reparte entre beneficiarios. La lógica vive en el
motor `backend/reportes/` — acá solo va el transporte HTTP + el CSV.
"""

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, Response
from pydantic import BaseModel

from database import get_db
from auth.guards import require_admin
from rate_limit import limiter, ADMIN_WRITE_LIMIT
from reportes.liquidacion import excluir_dueno, liquidar
from reportes.reconciliacion import reconciliar
from reportes.cierres import (
    cerrar_mes,
    liquidar_rango,
    mes_de_rango,
    reabrir_mes,
    snapshot_de,
    validar_mes,
)

router = APIRouter()


def _validar_rango(desde: str, hasta: str) -> None:
    try:
        datetime.strptime(desde, "%Y-%m-%d")
        datetime.strptime(hasta, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Fechas inválidas — usá el formato YYYY-MM-DD.")
    if desde > hasta:
        raise HTTPException(400, "El rango es inválido: 'desde' es posterior a 'hasta'.")


def _liquidacion_csv(data: dict) -> str:
    """CSV de la liquidación: una grilla mes × beneficiario + detalle por dueño.
    Pura (testeable sin DB)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    beneficiarios = data.get("beneficiarios", [])

    w.writerow(["Liquidación por mes (ingreso 100% pagado, repartido)"])
    w.writerow(["Mes", *beneficiarios, "Total"])
    for fila in data["por_mes"]:
        pb = fila["por_beneficiario"]
        w.writerow([fila["mes"], *[pb.get(b, 0) for b in beneficiarios], fila["total"]])
    res = data["resumen"]
    w.writerow(["TOTAL", *[res["por_beneficiario"].get(b, 0) for b in beneficiarios], res["total"]])

    w.writerow([])
    w.writerow(["Detalle por dueño"])
    w.writerow(["Dueño", "Equipo", "Veces alquilado", "Generado (ARS)"])
    for d in data["por_dueno"]:
        for eq in d["equipos"]:
            w.writerow([d["dueno"], eq["equipo"], eq.get("veces", ""), eq["monto"]])
        w.writerow([
            f"{d['dueno']} — TOTAL ({d.get('pedidos', 0)} alquileres)",
            "", "", d["monto_generado"],
        ])
    return buf.getvalue()


def _data_liquidacion(conn, desde: str, hasta: str) -> dict:
    """Carga la liquidación de un rango con la lógica de cierre (#721, #1209): si
    el rango es EXACTAMENTE un mes calendario cerrado, sirve su FOTO inmutable
    directa. Si es un rango de VARIOS meses (ej. "Mes a mes"/el total anual),
    delega en `liquidar_rango`, que usa la foto de cada mes cerrado que el rango
    cubre y calcula en vivo el resto — así un mes cerrado nunca muestra un número
    distinto entre la tarjeta del mes y la vista multi-mes/anual. Fuente única
    usada por el endpoint JSON/CSV, el PDF y el envío por mail.

    Excluye al Estudio (`excluir_dueno`, 2026-08-03): esta página es el reparto
    real entre dueños de EQUIPO (Pablo/Tincho/Rental); el Estudio es otra
    economía, todavía en desarrollo — se ve aparte (Caja Estudio / Finanzas),
    no acá. `liquidar`/`liquidar_rango`/`cerrar_mes` en sí NO se tocan (siguen
    calculando con el Estudio adentro) — el filtro es solo de presentación,
    aplicado acá porque este es el único punto de salida de la página."""
    mes = mes_de_rango(desde, hasta)
    if mes:
        snap = snapshot_de(conn, mes)
        if snap is not None:
            data = snap
        else:
            data = liquidar(conn, desde, hasta)
            data["cerrado"] = False
    else:
        data = liquidar_rango(conn, desde, hasta)
    if mes:
        data["mes"] = mes
    data["desde"] = desde
    data["hasta"] = hasta
    return excluir_dueno(data, "Estudio")


def _periodo_label(desde: str, hasta: str) -> str:
    """Rótulo legible del período: 'junio de 2026' si es un mes calendario
    exacto, si no 'desde … hasta …'."""
    from pdf import _es_month

    mes = mes_de_rango(desde, hasta)
    if mes:
        d = datetime.strptime(desde, "%Y-%m-%d")
        return _es_month(d.strftime("%B de %Y"))
    return f"{desde} a {hasta}"


@router.get("/admin/reportes/liquidacion")
def reporte_liquidacion(
    request: Request,
    desde: str = Query(..., description="YYYY-MM-DD"),
    hasta: str = Query(..., description="YYYY-MM-DD"),
    formato: str = Query("json", description="json | csv"),
):
    require_admin(request)
    _validar_rango(desde, hasta)
    with get_db() as conn:
        data = _data_liquidacion(conn, desde, hasta)

    if formato == "csv":
        filename = f"liquidacion_{desde}_a_{hasta}.csv"
        return StreamingResponse(
            iter([_liquidacion_csv(data)]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return data


_DESTINATARIOS_KEY = "reporte_liquidacion_destinatarios"


def _split_emails(raw: str) -> list[str]:
    """Parsea una lista de emails separados por coma / punto y coma / saltos."""
    import re

    partes = re.split(r"[,;\n]+", raw or "")
    return [p.strip() for p in partes if p.strip()]


@router.get("/admin/reportes/liquidacion/pdf")
async def reporte_liquidacion_pdf(
    request: Request,
    desde: str = Query(..., description="YYYY-MM-DD"),
    hasta: str = Query(..., description="YYYY-MM-DD"),
    format: str = Query("pdf", description="pdf | html"),
):
    """PDF branded del reporte (o su preview HTML con `format=html`). Misma
    maquinaria que los documentos de pedido (`pdf._render_pdf`)."""
    require_admin(request)
    _validar_rango(desde, hasta)
    from pdf import _liquidacion_html, _render_pdf
    from routes.estadisticas import compute_estadisticas

    with get_db() as conn:
        data = _data_liquidacion(conn, desde, hasta)
        stats = compute_estadisticas(conn)

    html = _liquidacion_html(data, _periodo_label(desde, hasta), stats=stats)
    if format == "html":
        return HTMLResponse(html)
    pdf_bytes = await _render_pdf(html)
    filename = f"liquidacion_{desde}_a_{hasta}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/admin/reportes/liquidacion/destinatarios")
def reporte_destinatarios(request: Request):
    """Lista de mails guardada para enviar el reporte (se prefilla en el diálogo).
    Default: el mail de admin configurado, si hay."""
    require_admin(request)
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = %s", (_DESTINATARIOS_KEY,)
        ).fetchone()
        if row and row["value"]:
            return {"destinatarios": _split_emails(row["value"])}
        from services.email import service as email_service

        return {"destinatarios": email_service.get_admin_tos()}


class EnviarReporteBody(BaseModel):
    desde: str
    hasta: str
    destinatarios: list[str]
    mensaje: str | None = None


@router.post("/admin/reportes/liquidacion/enviar-mail")
@limiter.limit(ADMIN_WRITE_LIMIT)
async def enviar_reporte_mail(request: Request, body: EnviarReporteBody):
    """Genera el PDF del reporte del período y lo manda adjunto a cada
    destinatario. Guarda la lista para prefillar la próxima vez."""
    admin = require_admin(request)
    _validar_rango(body.desde, body.hasta)

    destinatarios = _split_emails("\n".join(body.destinatarios or []))
    validos = [e for e in destinatarios if "@" in e and "." in e.split("@")[-1]]
    if not validos:
        raise HTTPException(400, "Agregá al menos un email válido.")

    import html as html_mod

    from pdf import _liquidacion_html, _render_pdf
    from routes.estadisticas import compute_estadisticas
    from services.email import send_raw_email
    from services.email.base import Attachment

    periodo = _periodo_label(body.desde, body.hasta)
    with get_db() as conn:
        data = _data_liquidacion(conn, body.desde, body.hasta)
        stats = compute_estadisticas(conn)
        # Persistir la lista de destinatarios para la próxima vez.
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at, updated_by)
            VALUES (%s, %s, NOW(), %s)
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = NOW(), updated_by = EXCLUDED.updated_by
            """,
            (_DESTINATARIOS_KEY, ", ".join(validos), (admin or {}).get("email")),
        )
        conn.commit()

    reporte_html = _liquidacion_html(data, periodo, stats=stats)
    pdf_bytes = await _render_pdf(reporte_html)
    adjunto = Attachment(
        filename=f"liquidacion_{body.desde}_a_{body.hasta}.pdf",
        content=pdf_bytes,
        mimetype="application/pdf",
    )

    total = data.get("resumen", {}).get("total", 0)
    intro = (body.mensaje or "").strip()
    intro_html = f"<p>{html_mod.escape(intro)}</p>" if intro else ""
    cuerpo = (
        f"<h2 style='margin:0 0 12px'>Reporte de liquidación</h2>"
        f"{intro_html}"
        f"<p>Adjuntamos el reporte de liquidación de <strong>{html_mod.escape(periodo)}</strong>. "
        f"El detalle por dueño y el reparto entre beneficiarios están en el PDF adjunto.</p>"
    )

    enviados, fallidos = [], []
    for to in validos:
        r = send_raw_email(
            to=to,
            subject=f"Reporte de liquidación — {periodo}",
            body_html=cuerpo,
            text=f"Reporte de liquidación de {periodo}. Total: {total}. Ver PDF adjunto.",
            attachments=[adjunto],
            log_key="reporte_liquidacion",
        )
        (enviados if r.get("ok") else fallidos).append(to)

    if not enviados:
        raise HTTPException(502, "No se pudo enviar el reporte a ningún destinatario.")
    return {"enviados": enviados, "fallidos": fallidos}


@router.get("/admin/reportes/reconciliacion")
def reporte_reconciliacion(request: Request):
    """Chequeos de integridad de los datos de liquidación (semáforo de confianza)."""
    require_admin(request)
    with get_db() as conn:
        return reconciliar(conn)


def _validar_mes_http(mes: str) -> None:
    try:
        validar_mes(mes)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/admin/reportes/cierres/{mes}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def cerrar_mes_liquidacion(request: Request, mes: str):
    """Cierra un mes: congela la foto inmutable del reporte (números + modelo).
    Idempotente: re-cerrar recalcula la foto con los datos actuales (#721)."""
    admin = require_admin(request)
    _validar_mes_http(mes)
    with get_db() as conn:
        return cerrar_mes(conn, mes, admin.get("email"))


@router.delete("/admin/reportes/cierres/{mes}")
@limiter.limit(ADMIN_WRITE_LIMIT)
def reabrir_mes_liquidacion(request: Request, mes: str):
    """Reabre un mes cerrado: borra la foto → el reporte vuelve a calcularse en
    vivo (para corregir; después se vuelve a cerrar) (#721)."""
    require_admin(request)
    _validar_mes_http(mes)
    with get_db() as conn:
        reabierto = reabrir_mes(conn, mes)
    return {"mes": mes, "cerrado": False, "reabierto": reabierto}
