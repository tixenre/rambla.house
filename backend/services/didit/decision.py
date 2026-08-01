"""Extracción de los datos de RENAPER del objeto `decision` de Didit (API v3).

En la API v3 los datos del documento NO viven en un `kyc.document` singular
(shape viejo), sino en arrays **plurales** dentro de `decision`:

    decision = {
      "id_verifications": [
        { "status": "Approved", "document_number": "...", "personal_number": "...",
          "first_name": "...", "last_name": "...", "full_name": "...",
          "date_of_birth": "...", "formatted_address": "...",
          "gender": "M", "nationality": "ARG", "place_of_birth": "...",
          "expiration_date": "...", "date_of_issue": "...",
          "document_type": "Identity Card", "marital_status": "Single", ... }
      ],
      "face_matches": [...], "liveness_checks": [...], ...
    }

El mismo `decision` llega de dos fuentes equivalentes (mismo schema):
  - embebido en el webhook (`payload["decision"]`), o
  - vía `GET /v3/session/{id}/decision/` (fuente canónica, `client.retrieve_decision`).

Este módulo es **puro** (sin DB ni red) para poder testearlo de punta a punta.

Ley 25.326: devuelve solo texto plano. No se extraen URLs de imagen ni scores
biométricos — esas URLs (portrait_image, front_image, etc.) no se persisten.

Refs: https://docs.didit.me/sessions-api/retrieve-session
"""

from dataclasses import dataclass

from services.telefono import formatear_para_guardar


@dataclass
class DatosRenaper:
    """Datos del documento confirmados por RENAPER. Todos opcionales: una
    verificación puede venir incompleta y no queremos pisar lo ya guardado."""

    # Identidad principal
    dni: str | None = None
    cuil: str | None = None
    nombre: str | None = None
    apellido: str | None = None
    nombre_completo: str | None = None
    fecha_nacimiento: str | None = None
    direccion: str | None = None
    # Datos adicionales del documento
    genero: str | None = None
    nacionalidad: str | None = None
    lugar_nacimiento: str | None = None
    vencimiento_documento: str | None = None
    emision_documento: str | None = None
    tipo_documento: str | None = None
    estado_civil: str | None = None

    @property
    def tiene_datos(self) -> bool:
        """True si se extrajo al menos el DNI — la señal de que la decisión
        traía datos del documento (y no un webhook 'liviano' sin payload)."""
        return bool(self.dni)


@dataclass
class ContactoVerificado:
    """Un contacto (mail o teléfono) verificado por Didit durante el KYC.

    Verificado-**por-control** (código al mail / OTP-WhatsApp al teléfono) — NO sale
    de RENAPER, lo tipea el cliente en el flujo y Didit prueba que lo controla. Sirve
    como factor de comunicación y de recuperación. El `value` del teléfono viene en
    formato internacional (E.164, campo `full_number` de Didit)."""

    kind: str  # "email" | "phone"
    value: str
    verified_at: str | None = None
    metodo: str | None = None  # phone: "sms" | "whatsapp" / email: None
    # Señales anti-fraude (las trae Didit; opcionales)
    is_disposable: bool | None = None  # mail/número descartable
    is_virtual: bool | None = None  # solo phone: número virtual (VoIP)
    is_breached: bool | None = None  # solo email: aparece en filtraciones


@dataclass
class ContactosVerificados:
    """Mail + teléfono verificados que devuelve Didit (ambos opcionales)."""

    email: ContactoVerificado | None = None
    phone: ContactoVerificado | None = None

    @property
    def tiene_alguno(self) -> bool:
        return self.email is not None or self.phone is not None


def _limpiar(valor) -> str | None:
    """Normaliza un campo a texto plano o None (vacío/espacios → None)."""
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _elegir_verificacion(verifs: list) -> dict | None:
    """Elige la entrada de `id_verifications` con datos de documento, prefiriendo
    las Approved. Defensivo ante entradas malformadas (no-dict, sin número)."""
    candidato = None
    for v in verifs:
        if not isinstance(v, dict) or not _limpiar(v.get("document_number")):
            continue
        if (v.get("status") or "").strip().lower() == "approved":
            return v  # la mejor: aprobada y con número de documento
        candidato = candidato or v
    return candidato


def extraer_datos_renaper(decision: dict | None) -> DatosRenaper:
    """Extrae los datos del documento del objeto `decision` (API v3).

    Mapa de campos (Argentina / RENAPER vía Didit):
      Identidad:
        - dni              ← document_number
        - cuil             ← personal_number (fallbacks: tax_id, cuil)
        - nombre           ← first_name
        - apellido         ← last_name
        - nombre_completo  ← full_name  (autoritativo; p/ contratos)
        - fecha_nacimiento ← date_of_birth
        - direccion        ← formatted_address (fallback: address)
      Documento:
        - genero           ← gender          ("M" / "F")
        - nacionalidad     ← nationality     ("ARG")
        - lugar_nacimiento ← place_of_birth
        - vencimiento_documento ← expiration_date
        - emision_documento     ← date_of_issue
        - tipo_documento   ← document_type   ("Identity Card" / "Passport")
        - estado_civil     ← marital_status

    Campos NO extraídos (Ley 25.326): URLs de imagen/video (portrait_image,
    front_image, back_image, etc.) y scores biométricos.

    Tolerante a payloads incompletos o con shape inesperado: devuelve un
    DatosRenaper vacío en vez de romper (el webhook siempre responde 200).
    """
    if not isinstance(decision, dict):
        return DatosRenaper()
    verifs = decision.get("id_verifications")
    if not isinstance(verifs, list):
        return DatosRenaper()

    v = _elegir_verificacion(verifs)
    if v is None:
        return DatosRenaper()

    return DatosRenaper(
        dni=_limpiar(v.get("document_number")),
        cuil=_limpiar(v.get("personal_number") or v.get("tax_id") or v.get("cuil")),
        nombre=_limpiar(v.get("first_name")),
        apellido=_limpiar(v.get("last_name")),
        nombre_completo=_limpiar(v.get("full_name")),
        fecha_nacimiento=_limpiar(v.get("date_of_birth")),
        direccion=_limpiar(v.get("formatted_address") or v.get("address")),
        genero=_limpiar(v.get("gender")),
        nacionalidad=_limpiar(v.get("nationality")),
        lugar_nacimiento=_limpiar(v.get("place_of_birth")),
        vencimiento_documento=_limpiar(v.get("expiration_date")),
        emision_documento=_limpiar(v.get("date_of_issue")),
        tipo_documento=_limpiar(v.get("document_type")),
        estado_civil=_limpiar(v.get("marital_status")),
    )


def _a_bool(valor) -> bool | None:
    """Devuelve el bool si vino como tal; None si está ausente (no inventa False)."""
    return valor if isinstance(valor, bool) else None


def _elegir_contacto(items: list, value_key: str) -> dict | None:
    """Elige la entrada de contacto con `value_key` presente, prefiriendo las
    Approved (espeja `_elegir_verificacion`). Defensivo ante entradas malformadas."""
    candidato = None
    for it in items:
        if not isinstance(it, dict) or not _limpiar(it.get(value_key)):
            continue
        if (it.get("status") or "").strip().lower() == "approved":
            return it
        candidato = candidato or it
    return candidato


def extraer_contactos(decision: dict | None) -> ContactosVerificados:
    """Extrae mail + teléfono **verificados** del `decision` v3 (arrays plurales
    `email_verifications[]` / `phone_verifications[]`).

    Distinto de `extraer_datos_renaper`: eso saca la **identidad** del documento
    (RENAPER); esto saca los **contactos** que el cliente tipeó en el flujo y Didit
    verificó por control. Puro y tolerante a payloads incompletos (devuelve vacío,
    nunca rompe — el webhook siempre responde 200).

    Mapa de campos (Didit):
      email ← email_verifications[].email     (+ is_disposable, is_breached, verified_at)
      phone ← phone_verifications[].full_number  (E.164; fallback phone_number)
              (+ verification_method, is_disposable, is_virtual, verified_at)
    """
    if not isinstance(decision, dict):
        return ContactosVerificados()

    email = None
    evs = decision.get("email_verifications")
    if isinstance(evs, list):
        e = _elegir_contacto(evs, "email")
        if e is not None:
            email = ContactoVerificado(
                kind="email",
                value=_limpiar(e.get("email")),
                verified_at=_limpiar(e.get("verified_at")),
                is_disposable=_a_bool(e.get("is_disposable")),
                is_breached=_a_bool(e.get("is_breached")),
            )

    phone = None
    pvs = decision.get("phone_verifications")
    if isinstance(pvs, list):
        # Preferimos full_number (internacional / E.164); fallback al número local.
        p = _elegir_contacto(pvs, "full_number") or _elegir_contacto(pvs, "phone_number")
        if p is not None:
            # `full_number` ya viene E.164 de Didit; se re-chequea por el embudo único
            # (`services/telefono`) — no-op si está bien, pero nos asegura el formato.
            # El fallback `phone_number` local NO se normaliza: sin código de país es
            # ambiguo (móvil vs fijo), mejor guardar el crudo verificado que arriesgar.
            full = _limpiar(p.get("full_number"))
            phone_val = formatear_para_guardar(full) if full else _limpiar(p.get("phone_number"))
            phone = ContactoVerificado(
                kind="phone",
                value=phone_val,
                verified_at=_limpiar(p.get("verified_at")),
                metodo=_limpiar(p.get("verification_method")),
                is_disposable=_a_bool(p.get("is_disposable")),
                is_virtual=_a_bool(p.get("is_virtual")),
            )

    return ContactosVerificados(email=email, phone=phone)
