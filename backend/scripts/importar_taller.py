"""Importa un taller completo (concepto + 1ª edición + instructor) desde una
ficha estructurada — vía la API real (`/api/admin/talleres`), no SQL directo.
Así corren TODAS las validaciones/gates que corre un alta manual desde el
admin: `_gate_conflicto_estudio`, slugs únicos, la transacción de
`crear_edicion` — el backend ya acepta el payload completo en un solo POST
(`TallerConceptoCreateBody`/`EdicionCreateBody`, `routes/talleres.py`); este
script solo arma ese payload desde una ficha legible y lo manda.

Formato de la ficha (JSON) — ver `scripts/fichas/` para ejemplos reales:
{
  "nombre": "...", "subtitulo": "", "descripcion": "...",
  "publico_objetivo": "...", "notif_email": "",
  "instructor": {"nombre": "...", "rol": "", "descripcion": "", "instagram": "",
                 "web": "", "proyectos": "A, B, C"},
  "edicion": {
    "tipo_taller": "intensivo" | "semanal", "horario": "...",
    "cupos_total": 12, "precio_total": 0, "precio_sena": 0,
    "direccion": null,  // null/omitido → se resuelve solo (ver abajo)
    "pago_alias": "", "pago_cbu": "", "pago_banco": "",
    "usa_estudio": false, "valor_estudio": 0, "valor_estudio_modo": "mensual",
    "usa_equipos": false, "valor_equipos": 0, "valor_equipos_modo": "mensual",
    "clases": [{"fecha": "2026-09-03", "hora_inicio_min": 1140, "hora_fin_min": 1260,
                "titulo": "Clase 1"}, ...]
  }
}

`edicion.direccion`: si se omite (o es null/""), se resuelve sola desde
`GET /api/settings/business_address` (setting única, lectura pública) — no
hace falta repetir la dirección de Rambla ficha por ficha.

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
import os
import sys

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


def importar(client: httpx.Client, base: str, ficha: dict) -> dict:
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
            "clases": edicion["clases"],
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
    # nombre; el resto se completa acá con un PATCH aparte.
    campos_ricos = {k: v for k, v in instructor.items() if k != "nombre" and v}
    if campos_ricos and creado.get("instructores"):
        instructor_id = creado["instructores"][0]["id"]
        r2 = client.patch(f"{base}/api/admin/instructores/{instructor_id}", json=campos_ricos)
        if r2.status_code != 200:
            print(f"  aviso: no pude completar el perfil del instructor ({r2.status_code}): {r2.text}", file=sys.stderr)
        else:
            print(f"  perfil del instructor completado: {list(campos_ricos.keys())}")

    return creado


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ficha", help="Path al JSON de la ficha del taller")
    ap.add_argument("--base-url", default=None, help="Default: $BASE_URL o http://localhost:8000")
    ap.add_argument("--cookie", default=None, help="Cookie de sesión admin ya lista (salta staging-login)")
    args = ap.parse_args()

    base = (args.base_url or _base_url()).rstrip("/")
    with open(args.ficha, encoding="utf-8") as f:
        ficha = json.load(f)

    with httpx.Client(timeout=30) as client:
        if args.cookie:
            client.headers["Cookie"] = args.cookie
        else:
            _login(client, base)

        print(f"Importando {ficha['nombre']!r} contra {base}…")
        creado = importar(client, base, ficha)

    print(f"\nListo. Revisalo en {base.replace('8000', '3000') if 'localhost' in base else base}/admin/talleres")
    print(f"(taller_id={creado['id']}, ediciones[0].id={creado['ediciones'][0]['id']})")


if __name__ == "__main__":
    main()
