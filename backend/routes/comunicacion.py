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
    de `email_templates` (editable en la misma pantalla) y el de WhatsApp
    del registro de plantillas (lo aprueba Meta, no se edita acá)."""
    require_admin(request)

    from services.comunicacion.eventos import (
        ESTRATEGIA_DETALLE,
        ESTRATEGIA_LABEL,
        REGISTRO,
    )
    from services.comunicacion.opciones import estado as estado_opciones
    from services.email.service import channel_status
    from services.whatsapp import REGISTRO as WA_REGISTRO
    from services.whatsapp import diagnosticar, estado_plantillas

    with get_db() as conn:
        wa_estado = diagnosticar(conn)
        opciones = estado_opciones(conn)
        # Asunto + on/off de TODOS los templates de mail en UNA query (no N+1): los
        # que un evento referencia se muestran adentro del evento, y el resto (los
        # mails que dispara Talleres) en su propia lista, para que no quede ninguno
        # sin lugar donde editarlo.
        mails: dict[str, dict] = {
            r["key"]: {"subject": r["subject"], "enabled": bool(r["enabled"])}
            for r in conn.execute(
                "SELECT key, subject, enabled FROM email_templates ORDER BY key"
            ).fetchall()
        }

    # Estado de aprobación real en Meta, por template (una llamada al Graph). Si el
    # canal no está configurado devuelve `disponible: False` y cada evento muestra
    # su plantilla igual, para copiarla a mano.
    remoto = estado_plantillas()
    estado_meta = {f["key"]: f.get("estado") for f in remoto.get("plantillas", [])}

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

    def _wa_info(key: str | None) -> dict | None:
        wa = WA_REGISTRO.get(key) if key else None
        if wa is None:
            return None
        return {
            "key": wa.key,
            "meta_name": wa.meta_name,
            "lang": wa.lang,
            "copy_ejemplo": wa.copy_ejemplo,
            "parametros": list(wa.campos_ctx),
            # None = no se pudo consultar (canal sin configurar / Meta no respondió).
            "estado_meta": estado_meta.get(wa.key),
        }

    usados_por_eventos: set[str] = set()
    eventos = []
    for ev in REGISTRO.values():
        for t in (ev.mail.template_cliente, ev.mail.template_admin) if ev.mail else ():
            if t:
                usados_por_eventos.add(t)
        eventos.append(
            {
                "key": ev.key,
                "titulo": ev.titulo or ev.key,
                "descripcion": ev.descripcion,
                "estrategia": ev.estrategia,
                "estrategia_label": ESTRATEGIA_LABEL.get(ev.estrategia, ev.estrategia),
                "estrategia_detalle": ESTRATEGIA_DETALLE.get(ev.estrategia, ""),
                "mail_cliente": _mail_info(ev.mail.template_cliente if ev.mail else None),
                "mail_admin": _mail_info(ev.mail.template_admin if ev.mail else None),
                "con_adjunto_ics": bool(ev.mail and ev.mail.con_adjunto_ics),
                "whatsapp": _wa_info(ev.whatsapp),
                "whatsapp_admin": _wa_info(ev.whatsapp_admin),
                # Perillas configurables de ESTE evento (horario, antelación,
                # destinatarios internos). Se guardan por PUT /api/admin/settings/{key}.
                "opciones": opciones.get(ev.key, []),
            }
        )

    return {
        "eventos": eventos,
        # Templates de mail que no dispara ningún evento del registro (hoy: los de
        # Talleres, que `services/talleres` manda directo). Se listan aparte —
        # decir que son eventos del registro sería mentir sobre quién los dispara.
        "otros_mails": [
            {"template": k, "asunto": v["subject"], "activo": v["enabled"]}
            for k, v in mails.items()
            if k not in usados_por_eventos
        ],
        "canales": {
            "mail": channel_status(),
            "whatsapp": {
                "listo": wa_estado["listo"],
                "chequeos": wa_estado["chequeos"],
                "ambiente": wa_estado["ambiente"],
                "gestion_plantillas": {
                    "disponible": remoto.get("disponible", False),
                    "motivo": remoto.get("motivo"),
                },
            },
        },
    }
