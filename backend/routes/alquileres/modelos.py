"""routes/alquileres/modelos.py — modelos Pydantic del pedido (split de `core.py`).

El contrato HTTP de creación/edición de un pedido: `PedidoItem` (línea de catálogo o
personalizada, #805), `PedidoCreate`, `PedidoDatos` (edición parcial), `PedidoEstado`,
`PedidoItemUpdate`. Move-verbatim desde `core.py` (issue de tracking del split) — sin
cambio de validación; `core.py` re-importa estos nombres para no romper los ~57
call-sites existentes (`routes/alquileres/__init__.py` sigue importando de `core`).
"""
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from services.fechas import validar_fecha_iso


def _parse_precio(v) -> int:
    """Acepta int, float o string con formato '$15.000' → 15000."""
    if v is None:
        return 0
    s = str(v).replace("$", "").replace(".", "").replace(",", "").strip()
    try:
        return int(float(s)) if s else 0
    except (ValueError, TypeError):
        return 0


# La validación de formato vive en la puerta única `services/fechas.py`. Se
# mantiene el nombre `_validar_fecha_iso` como alias para los field_validators de
# este módulo y la re-exportación de `routes/alquileres/__init__.py`.
_validar_fecha_iso = validar_fecha_iso


class PedidoItem(BaseModel):
    # equipo_id None = línea personalizada (#805): no es del catálogo, no reserva
    # stock; lleva `nombre_libre`. `cobro_modo`: 'jornada' (× jornadas, default) |
    # 'fijo' (monto único — normalmente una línea libre, pero un ítem de
    # catálogo también puede serlo, ver validate_linea_libre).
    equipo_id:      Optional[int] = Field(default=None, gt=0, lt=2_147_483_647)
    cantidad:       int
    precio_jornada: int = 0
    nombre_libre:   Optional[str] = None
    cobro_modo:     str = "jornada"

    @field_validator("precio_jornada", mode="before")
    @classmethod
    def coerce_precio(cls, v):
        return _parse_precio(v)

    @field_validator("cantidad")
    @classmethod
    def validate_cantidad(cls, v: int) -> int:
        if v is None or v < 1:
            raise ValueError("cantidad debe ser >= 1")
        if v > 999:
            raise ValueError("cantidad demasiado alta (máx 999)")
        return v

    @field_validator("precio_jornada")
    @classmethod
    def validate_precio(cls, v):
        if v is not None and v < 0:
            raise ValueError("precio_jornada no puede ser negativo")
        return v

    @field_validator("cobro_modo")
    @classmethod
    def validate_cobro_modo(cls, v):
        if v not in ("jornada", "fijo"):
            raise ValueError("cobro_modo debe ser 'jornada' o 'fijo'")
        return v

    @model_validator(mode="after")
    def validate_linea_libre(self):
        # Una línea personalizada (sin equipo_id) necesita un nombre. Un ítem
        # de catálogo SÍ puede llevar cobro_modo='fijo' (Talleres,
        # `_regenerar_pedidos_taller`: el centinela del Estudio se factura a
        # monto fijo dentro de un pedido editable, no ×jornadas) — el front no
        # expone el control para elegirlo a mano en una línea de catálogo, así
        # que esto solo se ve en pedidos que ya lo traían así de fábrica.
        if self.equipo_id is None and not (self.nombre_libre or "").strip():
            raise ValueError("una línea personalizada necesita un nombre")
        return self


class PedidoCreate(BaseModel):
    cliente_nombre:   Optional[str] = ""
    cliente_email:    Optional[str] = None
    cliente_telefono: Optional[str] = None
    cliente_id:       Optional[int] = Field(default=None, gt=0, lt=2_147_483_647)
    notas:            Optional[str] = None
    fecha_desde:      Optional[str] = None
    fecha_hasta:      Optional[str] = None
    items:            list[PedidoItem] = []
    estado:           Optional[str] = "solicitado"
    # #1240: a nombre de quién se factura este pedido — mutuamente excluyentes
    # (validado por el caller, ej. `cliente_crear_pedido`), NULL/NULL = perfil
    # default de la cuenta. El admin (builder de pedidos) no los usa hoy.
    perfil_fiscal_id: Optional[int] = Field(default=None, gt=0, lt=2_147_483_647)
    productora_id:    Optional[int] = Field(default=None, gt=0, lt=2_147_483_647)

    @field_validator("fecha_desde", "fecha_hasta")
    @classmethod
    def _v_fechas(cls, v):
        return _validar_fecha_iso(v)


class PedidoEstado(BaseModel):
    estado: str


def _validar_descuento_pct(v):
    """0-100 o None. Fuente única — la comparte `PedidoDatos` (acá abajo) con
    `CotizarRequest` (routes/alquileres/cotizacion.py): antes estaban duplicados
    byte a byte (el preview de cotización y el guardado real no deberían poder
    rechazar cosas distintas)."""
    if v is None:
        return v
    if v < 0 or v > 100:
        raise ValueError("descuento_pct debe estar entre 0 y 100")
    return v


def _validar_descuento_manual_tipo(v):
    """"pct" o "monto" (o None). Misma fuente única que `_validar_descuento_pct`."""
    if v is None:
        return v
    if v not in ("pct", "monto"):
        raise ValueError("descuento_manual_tipo debe ser 'pct' o 'monto'")
    return v


def _validar_descuento_manual_monto(v):
    """`alquileres.descuento_manual_monto` es INTEGER — sin este tope, un valor
    fuera de rango llega crudo a Postgres como `NumericValueOutOfRange` (mismo
    gap que cerró la auditoría de contabilidad, 2026-07-02). Misma fuente única
    que `_validar_descuento_pct`."""
    if v is None:
        return v
    if v < 0:
        raise ValueError("descuento_manual_monto no puede ser negativo")
    if v >= 2_147_483_647:
        raise ValueError("descuento_manual_monto demasiado alto")
    return v


class PedidoDatos(BaseModel):
    cliente_id:       Optional[int]   = Field(default=None, gt=0, lt=2_147_483_647)
    cliente_nombre:   Optional[str]   = None
    cliente_email:    Optional[str]   = None
    cliente_telefono: Optional[str]   = None
    fecha_desde:      Optional[str]   = None
    fecha_hasta:      Optional[str]   = None
    notas:            Optional[str]   = None
    descuento_pct:    Optional[float] = None
    # Override manual en % o en $ fijo (Fase C-2, #1219): mismo campo de la UI,
    # un selector al lado. `descuento_manual_tipo` decide cuál de los dos
    # honra la jerarquía — "pct" (default, usa `descuento_pct` de arriba) o
    # "monto" (usa `descuento_manual_monto`, pesos fijos).
    descuento_manual_tipo:  Optional[str]   = None
    descuento_manual_monto: Optional[float] = None
    # #1251: a nombre de quién se factura este pedido — mutuamente excluyentes
    # (validado abajo + membership en `_apply_pedido_datos`). NULL/NULL = perfil
    # default de la cuenta. El renter sigue siendo `cliente_id` — esto solo
    # cambia a quién se factura, nunca quién alquila.
    perfil_fiscal_id: Optional[int] = Field(default=None, gt=0, lt=2_147_483_647)
    productora_id:    Optional[int] = Field(default=None, gt=0, lt=2_147_483_647)

    @field_validator("fecha_desde", "fecha_hasta")
    @classmethod
    def _v_fechas(cls, v):
        return _validar_fecha_iso(v)

    @model_validator(mode="after")
    def _v_fiscal_excluyente(self):
        if self.perfil_fiscal_id and self.productora_id:
            raise ValueError(
                "Un pedido no puede facturar a un perfil personal y a una productora a la vez."
            )
        return self

    @field_validator("descuento_pct")
    @classmethod
    def validate_descuento(cls, v):
        return _validar_descuento_pct(v)

    @field_validator("descuento_manual_tipo")
    @classmethod
    def validate_descuento_manual_tipo(cls, v):
        return _validar_descuento_manual_tipo(v)

    @field_validator("descuento_manual_monto")
    @classmethod
    def validate_descuento_manual_monto(cls, v):
        return _validar_descuento_manual_monto(v)


class PedidoItemUpdate(BaseModel):
    items: list[PedidoItem]
