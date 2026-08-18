"""Completa un taller EXISTENTE (concepto + una edición) desde una ficha — vía
PATCH real (`/api/admin/talleres/{id}`, `/api/admin/ediciones/{id}`), no SQL
directo. Hermano de `importar_taller.py` (que es solo-ALTA): usar este cuando
el taller y al menos una edición YA EXISTEN (ej. cargados como stub casi vacío
desde el admin) y lo que falta es completarlos con los datos de la ficha.

Mismo formato de ficha que `importar_taller.py` (ver su docstring) — la misma
ficha sirve para crear o para completar, no hace falta una versión distinta.

Reemplaza TODO lo que la ficha trae en el concepto y la edición. `clases` se
sincroniza por upsert (`services/talleres/commands/clases.py::_upsert_clases`):
las clases de la ficha no llevan `id` propio → se insertan como nuevas, y
CUALQUIER clase que ya existiera en esa edición y no esté en la ficha se
BORRA. Correcto para completar un stub sin clases reales todavía — si la
edición ya tiene clases con inscriptos o portadas cargadas, revisalo primero
con `--dry-run` antes de aplicar. `modalidades` reemplaza la lista completa
de modalidades de pago; el alias/CBU/banco de la ficha se manda como una
`cuenta_pago` (la forma que hoy edita el admin — los 3 campos legacy
`pago_alias/cbu/banco` quedan sin tocar).

Resuelve el taller por nombre (`--taller "substring"`, case-insensitive
contra `GET /api/admin/talleres`) o por id explícito (`--taller-id`). Si el
taller tiene más de una edición, toma la de `--numero-edicion` (default 1).

Uso:
  # Ver qué se mandaría, SIN tocar nada:
  python scripts/completar_taller.py scripts/fichas/mi-taller.json \\
    --taller "nivel avanzado" --dry-run

  # Aplicarlo de verdad, contra staging:
  BASE_URL=https://dev.rambla.house STAGING_LOGIN_SECRET=... \\
    python scripts/completar_taller.py scripts/fichas/mi-taller.json \\
    --taller "nivel avanzado"

  # Contra prod: staging-login está bloqueado (404) — usá --cookie con una
  # sesión de admin real, mismo criterio que importar_taller.py.
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

from importar_taller import _base_url, _login, _subir_foto


def _listar_talleres(client: httpx.Client, base: str) -> list[dict]:
    r = client.get(f"{base}/api/admin/talleres")
    if r.status_code != 200:
        sys.exit(f"No pude listar talleres ({r.status_code}): {r.text}")
    return r.json()


def _resolver_taller(client: httpx.Client, base: str, nombre_query: str | None, taller_id: int | None) -> dict:
    talleres = _listar_talleres(client, base)
    if taller_id is not None:
        for t in talleres:
            if t["id"] == taller_id:
                return t
        sys.exit(f"No encontré ningún taller con id={taller_id}")

    q = (nombre_query or "").strip().lower()
    matches = [t for t in talleres if q in t["nombre"].lower()]
    if not matches:
        sys.exit(f"No encontré ningún taller cuyo nombre contenga {nombre_query!r}")
    if len(matches) > 1:
        listado = "\n".join(f"  id={t['id']}  {t['nombre']!r}" for t in matches)
        sys.exit(f"Hay {len(matches)} talleres que matchean {nombre_query!r} — usá --taller-id:\n{listado}")
    return matches[0]


def completar(
    client: httpx.Client, base: str, ficha: dict, ficha_dir: Path,
    taller: dict, numero_edicion: int, dry_run: bool,
) -> None:
    ediciones = taller.get("ediciones") or []
    edicion = next((e for e in ediciones if e["numero_edicion"] == numero_edicion), None)
    if edicion is None:
        existentes = [e["numero_edicion"] for e in ediciones]
        sys.exit(
            f"El taller {taller['nombre']!r} (id={taller['id']}) no tiene una edición "
            f"#{numero_edicion} — ediciones existentes: {existentes}"
        )

    instructor = ficha.get("instructor") or {}
    ed_ficha = ficha["edicion"]

    concepto_payload = {
        "nombre": ficha["nombre"],
        "subtitulo": ficha.get("subtitulo", ""),
        "descripcion": ficha.get("descripcion", ""),
        "resumen": ficha.get("resumen", ""),
        "publico_objetivo": ficha.get("publico_objetivo", ""),
    }
    for opcional in ("notif_email", "terminos", "beneficios", "pregunta_experiencia", "mensaje_confirmacion"):
        if ficha.get(opcional):
            concepto_payload[opcional] = ficha[opcional]

    edicion_payload = {
        "tipo_taller": ed_ficha.get("tipo_taller", "intensivo"),
        "horario": ed_ficha.get("horario", ""),
        "cupos_total": ed_ficha.get("cupos_total", 12),
        "precio_total": ed_ficha.get("precio_total", 0),
        "precio_sena": ed_ficha.get("precio_sena", 0),
        # `portada` no es un campo de ClaseBody — se sube aparte, después de
        # completar (necesita el id real de la clase, que puede haber cambiado).
        "clases": [{k: v for k, v in c.items() if k != "portada"} for c in ed_ficha["clases"]],
    }
    if ed_ficha.get("modalidades"):
        edicion_payload["modalidades"] = ed_ficha["modalidades"]
    alias = ed_ficha.get("pago_alias", "")
    cbu = ed_ficha.get("pago_cbu", "")
    banco = ed_ficha.get("pago_banco", "")
    if alias or cbu or banco:
        edicion_payload["cuentas_pago"] = [{"alias": alias, "cbu": cbu, "banco": banco}]

    print(f"Taller: {taller['nombre']!r} (id={taller['id']}) → edición #{numero_edicion} (id={edicion['id']})")
    print(f"  PATCH /api/admin/talleres/{taller['id']}  →  {list(concepto_payload.keys())}")
    print(
        f"  PATCH /api/admin/ediciones/{edicion['id']}  →  {list(edicion_payload.keys())} "
        f"({len(edicion_payload['clases'])} clases)"
    )
    clases_previas = len(edicion.get("clases") or [])
    if clases_previas:
        print(
            f"  aviso: la edición ya tenía {clases_previas} clase(s) cargada(s) — "
            "ninguna de la ficha lleva `id`, así que se BORRAN y se reemplazan por las nuevas."
        )

    if dry_run:
        print("\n--dry-run: no se mandó nada. Payloads completos:")
        print(json.dumps({"concepto": concepto_payload, "edicion": edicion_payload}, indent=2, ensure_ascii=False))
        return

    r1 = client.patch(f"{base}/api/admin/talleres/{taller['id']}", json=concepto_payload)
    if r1.status_code != 200:
        sys.exit(f"Falló el PATCH del concepto ({r1.status_code}): {r1.text}")

    r2 = client.patch(f"{base}/api/admin/ediciones/{edicion['id']}", json=edicion_payload)
    if r2.status_code != 200:
        sys.exit(f"Falló el PATCH de la edición ({r2.status_code}): {r2.text}")
    ed_out = r2.json()
    print(f"\nListo. {len(ed_out.get('clases', []))} clases activas en la edición.")

    # Perfil rico del instructor — solo si la ficha trae un nombre real (no el
    # placeholder) y ese instructor ya existe en el taller (find-or-create lo
    # resuelve `admin_create_concepto`/el alta original, no este script).
    nombre_instructor = instructor.get("nombre", "")
    if nombre_instructor and nombre_instructor != "(a confirmar)":
        campos_ricos = {k: v for k, v in instructor.items() if k not in ("nombre", "foto") and v}
        instructor_id = next(
            (i["id"] for i in (taller.get("instructores") or []) if i.get("nombre") == nombre_instructor),
            None,
        )
        if instructor_id and campos_ricos:
            r3 = client.patch(f"{base}/api/admin/instructores/{instructor_id}", json=campos_ricos)
            if r3.status_code != 200:
                print(f"  aviso: no pude completar el perfil del instructor ({r3.status_code}): {r3.text}", file=sys.stderr)
            else:
                print(f"  perfil del instructor completado: {list(campos_ricos.keys())}")
        elif not instructor_id:
            print(
                f"  aviso: no encontré un instructor llamado {nombre_instructor!r} ya vinculado a este "
                "taller — el perfil rico no se completó (el nombre se resuelve en la creación, no acá).",
                file=sys.stderr,
            )

    # Portada por clase — matchea por (fecha, hora_inicio_min, hora_fin_min,
    # título), no por posición: robusto a que el backend reordene/dedupe.
    con_portada = [c for c in ed_ficha["clases"] if c.get("portada")]
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ficha", help="Path al JSON de la ficha (mismo formato que importar_taller.py)")
    ap.add_argument("--taller", default=None, help="Substring del nombre del taller a completar (case-insensitive)")
    ap.add_argument("--taller-id", type=int, default=None, help="Id explícito del taller (alternativa a --taller)")
    ap.add_argument("--numero-edicion", type=int, default=1, help="Qué edición completar (default: 1)")
    ap.add_argument("--base-url", default=None, help="Default: $BASE_URL o http://localhost:8000")
    ap.add_argument("--cookie", default=None, help="Cookie de sesión admin ya lista (salta staging-login)")
    ap.add_argument("--dry-run", action="store_true", help="Solo mostrar qué se mandaría, sin aplicar nada")
    args = ap.parse_args()

    if not args.taller and args.taller_id is None:
        sys.exit("Pasá --taller \"<substring del nombre>\" o --taller-id <id>")

    base = (args.base_url or _base_url()).rstrip("/")
    ficha_path = Path(args.ficha)
    with open(ficha_path, encoding="utf-8") as f:
        ficha = json.load(f)

    with httpx.Client(timeout=30) as client:
        if args.cookie:
            client.headers["Cookie"] = args.cookie
        else:
            _login(client, base)

        taller = _resolver_taller(client, base, args.taller, args.taller_id)
        completar(client, base, ficha, ficha_path.resolve().parent, taller, args.numero_edicion, args.dry_run)


if __name__ == "__main__":
    main()
