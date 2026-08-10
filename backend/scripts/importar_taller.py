"""Importa un taller completo (concepto + 1ª edición + instructor + fotos)
desde una ficha estructurada — vía la API real (`/api/admin/talleres`), no
SQL directo. Así corren TODAS las validaciones/gates que corre un alta manual
desde el admin: `_gate_conflicto_estudio`, slugs únicos, la transacción de
`crear_edicion` — el backend ya acepta el payload completo en un solo POST
(`TallerConceptoCreateBody`/`EdicionCreateBody`, `routes/talleres.py`); este
script solo arma ese payload desde una ficha legible y lo manda.

Formato de la ficha (JSON) — ver `scripts/fichas/` para ejemplos reales:
{
  "nombre": "...", "subtitulo": "", "descripcion": "...",
  "publico_objetivo": "...", "notif_email": "",
  "instructor": {"nombre": "...", "rol": "", "descripcion": "", "instagram": "",
                 "web": "", "proyectos": "A, B, C",
                 "foto": "instructor.jpg"},  // opcional, path relativo A LA FICHA
  "edicion": {
    "tipo_taller": "intensivo" | "semanal", "horario": "...",
    "cupos_total": 12, "precio_total": 0, "precio_sena": 0,
    "direccion": null,  // null/omitido → se resuelve solo (ver abajo)
    "pago_alias": "", "pago_cbu": "", "pago_banco": "",
    "usa_estudio": false, "valor_estudio": 0, "valor_estudio_modo": "mensual",
    "usa_equipos": false, "valor_equipos": 0, "valor_equipos_modo": "mensual",
    "clases": [{"fecha": "2026-09-03", "hora_inicio_min": 1140, "hora_fin_min": 1260,
                "titulo": "Clase 1", "portada": "clase-1.jpg"}, ...],  // portada opcional
    "modalidades": [{"codigo": "total", "label": "Pago total", "monto_total": 320000},
                     {"codigo": "mensual", "label": "Mensual", "monto_total": 80000,
                      "nota": "Se abona en la primera clase de cada mes"}]  // opcional
  }
}

`edicion.direccion`: si se omite (o es null/""), se resuelve sola desde
`GET /api/settings/business_address` (setting única, lectura pública) — no
hace falta repetir la dirección de Rambla ficha por ficha.

Fotos (`instructor.foto`, `clases[].portada`): opcionales, paths a archivos
locales — relativos a LA CARPETA DE LA FICHA (no al directorio desde donde se
corre el script), así una ficha con sus fotos puede vivir junta en
`scripts/fichas/<nombre>/`. No hay "galería" como entidad propia — la portada
es POR CLASE (`clases_taller.portada_*`); con 16 clases, cada una con su
portada, el efecto agregado en el calendario ES la galería. La foto de
instructor es la de perfil (`instructores.foto_*`). Cada subida es una
llamada aparte DESPUÉS de crear el taller (la clase necesita existir con id
real antes de poder subirle portada — mismo motivo por el que
`ClasesAsistente` deshabilita el botón de portada en clases sin guardar
todavía). Una foto que falla NO aborta el import — ya se creó el taller;
avisa y sigue.

La edición SIEMPRE nace en borrador (`activo=False`, default del propio
sistema — "F2 borradores: una edición NACE despublicada"). Alguien la revisa
y publica a mano desde /admin/talleres antes de que aparezca en la web —
mismo gate que "el dueño testea, no revisa código" (MEMORIA 2026-05-25):
este script no decide publicar nada.

Uso:
  # Contra el backend local (con STAGING_LOGIN_SECRET en backend/.env):
  cd backend && python scripts/importar_taller.py scripts/fichas/semiotica-ariel-perissinotti.json

  # Contra staging real (Railway) — mismo secreto que /auth/staging-login,
  # doble llave no-prod (404 en producción, ver auth/staging.py):
  BASE_URL=https://dev.rambla.house STAGING_LOGIN_SECRET=... \\
    python scripts/importar_taller.py scripts/fichas/semiotica-ariel-perissinotti.json

  # Contra prod: staging-login está bloqueado a propósito (404). Corré con
  # --cookie "session=<cookie de un admin logueado de verdad>" en vez de
  # depender de STAGING_LOGIN_SECRET.
"""

import argparse
import json
import mimetypes
import os
import sys
from pathlib import Path

import httpx


def _base_url() -> str:
    return os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")


def _login(client: httpx.Client, base: str) -> None:
    """Mintea la cookie de sesión admin vía `/auth/staging-login` (doble
    llave no-prod). Si el caller ya pasó `--cookie`, no se llama a esto."""
    secret = os.environ.get("STAGING_LOGIN_SECRET", "")
    if not secret:
        sys.exit(
            "Falta STAGING_LOGIN_SECRET en el entorno (o pasá --cookie con una "
            "sesión admin ya logueada, para prod)."
        )
    r = client.post(f"{base}/auth/staging-login", json={"secret": secret, "target": "admin"})
    if r.status_code != 200:
        sys.exit(f"staging-login falló ({r.status_code}): {r.text}")


def _resolver_direccion(client: httpx.Client, base: str, dada: str | None) -> str:
    if dada:
        return dada
    r = client.get(f"{base}/api/settings/business_address")
    if r.status_code != 200:
        print(
            f"  aviso: no pude leer business_address ({r.status_code}) — "
            "la edición queda con dirección vacía, completala a mano.",
            file=sys.stderr,
        )
        return ""
    valor = (r.json() or {}).get("value") or ""
    if valor:
        print(f"  dirección resuelta de app_settings.business_address: {valor!r}")
    return valor


def _subir_foto(client: httpx.Client, url: str, ficha_dir: Path, rel_path: str, etiqueta: str) -> None:
    """POST multipart genérico para las 2 rutas de subida de foto (instructor
    y clase) — mismo campo `file` en ambas. No propaga: una foto que falla no
    tira abajo un import que ya creó el taller."""
    path = (ficha_dir / rel_path).resolve()
    if not path.is_file():
        print(f"  aviso: no encontré {etiqueta} en {path} — se salteó.", file=sys.stderr)
        return
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with open(path, "rb") as fh:
        r = client.post(url, files={"file": (path.name, fh, ctype)})
    if r.status_code != 200:
        print(f"  aviso: no pude subir {etiqueta} ({r.status_code}): {r.text}", file=sys.stderr)
        return
    print(f"  {etiqueta} subida: {path.name}")


def importar(client: httpx.Client, base: str, ficha: dict, ficha_dir: Path) -> dict:
    instructor = ficha.get("instructor") or {}
    edicion = ficha["edicion"]

    direccion = _resolver_direccion(client, base, edicion.get("direccion"))

    payload = {
        "nombre": ficha["nombre"],
        "instructor_nombre": instructor.get("nombre", ""),
        "subtitulo": ficha.get("subtitulo", ""),
        "descripcion": ficha.get("descripcion", ""),
        "publico_objetivo": ficha.get("publico_objetivo", ""),
        "notif_email": ficha.get("notif_email", ""),
        "terminos": ficha.get("terminos", ""),
        "beneficios": ficha.get("beneficios", ""),
        "pregunta_experiencia": ficha.get("pregunta_experiencia", ""),
        "mensaje_confirmacion": ficha.get("mensaje_confirmacion", ""),
        "edicion": {
            "tipo_taller": edicion.get("tipo_taller", "intensivo"),
            # `portada` no es un campo de ClaseBody — se sube aparte, después
            # de crear (necesita el id real de la clase). Se lo saca acá para
            # no mandarlo en el POST de creación.
            "clases": [{k: v for k, v in c.items() if k != "portada"} for c in edicion["clases"]],
            "cupos_total": edicion.get("cupos_total", 12),
            "precio_total": edicion.get("precio_total", 0),
            "precio_sena": edicion.get("precio_sena", 0),
            "horario": edicion.get("horario", ""),
            "pago_alias": edicion.get("pago_alias", ""),
            "pago_cbu": edicion.get("pago_cbu", ""),
            "pago_banco": edicion.get("pago_banco", ""),
            "direccion": direccion,
            "activo": False,  # nace borrador — el dueño lo publica a mano
            "usa_estudio": edicion.get("usa_estudio", False),
            "valor_estudio": edicion.get("valor_estudio", 0),
            "valor_estudio_modo": edicion.get("valor_estudio_modo", "mensual"),
            "usa_equipos": edicion.get("usa_equipos", False),
            "valor_equipos": edicion.get("valor_equipos", 0),
            "valor_equipos_modo": edicion.get("valor_equipos_modo", "mensual"),
        },
    }

    r = client.post(f"{base}/api/admin/talleres", json=payload)
    if r.status_code != 201:
        sys.exit(f"Falló la creación del taller ({r.status_code}): {r.text}")
    creado = r.json()
    ed_out = creado["ediciones"][0]
    print(f"  taller creado: id={creado['id']} slug_base={creado['slug_base']!r}")
    print(
        f"  edición #{ed_out['numero_edicion']} (slug={ed_out['slug']!r}) — "
        f"{len(edicion['clases'])} clases, en BORRADOR"
    )

    # Perfil rico del instructor (rol/descripción/instagram/web/proyectos) —
    # `instructor_nombre` del POST anterior solo hace find-or-create por
    # nombre; el resto (y la foto, aparte) se completa acá.
    campos_ricos = {
        k: v for k, v in instructor.items() if k not in ("nombre", "foto") and v
    }
    instructor_id = creado["instructores"][0]["id"] if creado.get("instructores") else None
    if campos_ricos and instructor_id:
        r2 = client.patch(f"{base}/api/admin/instructores/{instructor_id}", json=campos_ricos)
        if r2.status_code != 200:
            print(f"  aviso: no pude completar el perfil del instructor ({r2.status_code}): {r2.text}", file=sys.stderr)
        else:
            print(f"  perfil del instructor completado: {list(campos_ricos.keys())}")

    # Modalidades de pago — `EdicionCreateBody` no las acepta en la creación
    # (mismo campo que `ModalidadesSection` en el admin, agregado aparte vía
    # PATCH). Con 2+ modalidades el público ve la LISTA (label+monto+nota);
    # con 1 sola, esa se vuelve "el" precio mostrado en vez de `precio_total`
    # (ver `PrecioCard.tsx`) — si la ficha quiere mostrar ambos, tiene que
    # traer explícitamente una modalidad "Pago total" además de la mensual.
    modalidades = edicion.get("modalidades")
    if modalidades:
        r3 = client.patch(f"{base}/api/admin/ediciones/{ed_out['id']}", json={"modalidades": modalidades})
        if r3.status_code != 200:
            print(f"  aviso: no pude cargar las modalidades de pago ({r3.status_code}): {r3.text}", file=sys.stderr)
        else:
            print(f"  modalidades de pago cargadas: {[m.get('label') for m in modalidades]}")

    # Foto de perfil del instructor.
    if instructor.get("foto") and instructor_id:
        _subir_foto(
            client, f"{base}/api/admin/instructores/{instructor_id}/upload-foto",
            ficha_dir, instructor["foto"], "foto de instructor",
        )

    # Portada por clase — matchea por (fecha, hora_inicio_min, hora_fin_min,
    # título), no por posición: robusto a que el backend reordene/dedupe.
    con_portada = [c for c in edicion["clases"] if c.get("portada")]
    if con_portada:
        por_clave = {
            (c["fecha"], c["hora_inicio_min"], c["hora_fin_min"], c.get("titulo", "")): c["id"]
            for c in ed_out["clases"]
        }
        for c in con_portada:
            clave = (c["fecha"], c["hora_inicio_min"], c["hora_fin_min"], c.get("titulo", ""))
            clase_id = por_clave.get(clave)
            if clase_id is None:
                print(f"  aviso: no encontré la clase creada para {clave} — portada salteada.", file=sys.stderr)
                continue
            _subir_foto(
                client, f"{base}/api/admin/clases/{clase_id}/portada",
                ficha_dir, c["portada"], f"portada de {c.get('titulo') or c['fecha']}",
            )

    return creado


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ficha", help="Path al JSON de la ficha del taller")
    ap.add_argument("--base-url", default=None, help="Default: $BASE_URL o http://localhost:8000")
    ap.add_argument("--cookie", default=None, help="Cookie de sesión admin ya lista (salta staging-login)")
    args = ap.parse_args()

    base = (args.base_url or _base_url()).rstrip("/")
    ficha_path = Path(args.ficha)
    with open(ficha_path, encoding="utf-8") as f:
        ficha = json.load(f)

    with httpx.Client(timeout=30) as client:
        if args.cookie:
            client.headers["Cookie"] = args.cookie
        else:
            _login(client, base)

        print(f"Importando {ficha['nombre']!r} contra {base}…")
        creado = importar(client, base, ficha, ficha_path.resolve().parent)

    print(f"\nListo. Revisalo en {base.replace('8000', '3000') if 'localhost' in base else base}/admin/talleres")
    print(f"(taller_id={creado['id']}, ediciones[0].id={creado['ediciones'][0]['id']})")


if __name__ == "__main__":
    main()
