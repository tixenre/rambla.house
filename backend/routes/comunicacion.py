"""Routes admin del módulo de Comunicación (mail + WhatsApp).

Hace **visible** lo que ya es fuente única en el código: el `REGISTRO` de
`services/comunicacion/eventos.py` — qué le comunicamos al cliente, qué dice por
cada canal y por dónde sale. El back-office lo lee de acá en vez de tener su
propia copia (si no, se desincronizan).

No expone secretos: el estado de cada canal viene de su propio diagnóstico
(`services.email.channel_status`, `services.whatsapp.diagnosticar`), que ya están
hechos para eso.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from auth.guards import require_admin
from database import get_db

router = APIRouter()


@router.get("/admin/comunicacion/eventos")
def listar_eventos(request: Request):
    """Los eventos de comunicación + el estado de cada canal.

    Cada evento trae su copy por canal ya resuelto: el asunto/cuerpo del mail sale
    de `email_templates` (editable desde /admin/email-templates) y el de WhatsApp
    del registro de plantillas (lo aprueba Meta, no se edita acá)."""
    require_admin(request)

    from services.comunicacion.eventos import (
        ESTRATEGIA_DETALLE,
        ESTRATEGIA_LABEL,
        REGISTRO,
    )
    from services.email.service import channel_status
    from services.whatsapp import REGISTRO as WA_REGISTRO
    from services.whatsapp import diagnosticar

    with get_db() as conn:
        wa_estado = diagnosticar(conn)
        # Asunto + on/off de cada template de mail referenciado por el registro,
        # en UNA query (no N+1) — es lo que la pantalla muestra por evento.
        keys = sorted(
            {
                t
                for ev in REGISTRO.values()
                if ev.mail
                for t in (ev.mail.template_cliente, ev.mail.template_admin)
                if t
            }
        )
        mails: dict[str, dict] = {}
        if keys:
            ph = ",".join(["%s"] * len(keys))
            for r in conn.execute(
                f"SELECT key, subject, enabled FROM email_templates WHERE key IN ({ph})",
                keys,
            ).fetchall():
                mails[r["key"]] = {"subject": r["subject"], "enabled": bool(r["enabled"])}

    def _mail_info(key: str | None) -> dict | None:
        if not key:
            return None
        found = mails.get(key)
        return {
            "template": key,
            "asunto": found["subject"] if found else None,
            "activo": found["enabled"] if found else None,
            # Si el registro apunta a un template que no existe en la tabla, la
            # pantalla lo tiene que gritar: el evento no podría mandar ese mail.
            "existe": found is not None,
        }

    eventos = []
    for ev in REGISTRO.values():
        wa = WA_REGISTRO.get(ev.whatsapp) if ev.whatsapp else None
        eventos.append(
            {
                "key": ev.key,
                "descripcion": ev.descripcion,
                "estrategia": ev.estrategia,
                "estrategia_label": ESTRATEGIA_LABEL.get(ev.estrategia, ev.estrategia),
                "estrategia_detalle": ESTRATEGIA_DETALLE.get(ev.estrategia, ""),
                "mail_cliente": _mail_info(ev.mail.template_cliente if ev.mail else None),
                "mail_admin": _mail_info(ev.mail.template_admin if ev.mail else None),
                "con_adjunto_ics": bool(ev.mail and ev.mail.con_adjunto_ics),
                "whatsapp": (
                    {
                        "key": wa.key,
                        "meta_name": wa.meta_name,
                        "lang": wa.lang,
                        "copy_ejemplo": wa.copy_ejemplo,
                        "parametros": list(wa.campos_ctx),
                    }
                    if wa
                    else None
                ),
            }
        )

    return {
        "eventos": eventos,
        "canales": {
            "mail": channel_status(),
            "whatsapp": {
                "listo": wa_estado["listo"],
                "chequeos": wa_estado["chequeos"],
                "ambiente": wa_estado["ambiente"],
            },
        },
    }
