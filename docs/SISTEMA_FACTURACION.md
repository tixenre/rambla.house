# Sistema de facturación electrónica ARCA

> **Manual técnico vivo.** Describe la arquitectura, flujo y puntos de entrada del sistema
> de facturación ARCA (ex-AFIP). El **por qué** de cada decisión vive en
> [`MEMORIA.md`](MEMORIA.md) / [`DECISIONES.md`](DECISIONES.md) y se **linkea**, no se copia.

---

## 1. Arquitectura en dos capas

```
backend/arca_fe/                  ← Core portable (librería, SemVer)
backend/services/facturacion/     ← Adapter Rambla (persistencia, PDF, routes)
```

### Core portable `backend/arca_fe/`

Zero imports de `backend.*` / FastAPI / psycopg. Puede extraerse a un paquete pip propio sin
cambios. Exporta su contrato público en `__init__.py` (`__all__`); `__version__` queda **fijo en
`"0.0.0"`** hasta la primera emisión real en producción (decisión explícita — no bumpea por
feature). `FEATURES.md`/`README.md`/`TRAMITES_AFIP.md` documentan el paquete en detalle; acá solo
el mapa de responsabilidad.

| Módulo | Responsabilidad |
|---|---|
| `modelos.py` | Enums y dataclasses fiscales (`CbteTipo`, `CondicionIva`, `ComprobanteRequest`, `CaeResult`, `ComprobanteFiscal`, `ItemFactura`, …) |
| `comprobante.py` | `tipo_comprobante`, `calcular_importes` (`Decimal` exacto), `armar_fecae`, `armar_fecae_lote` |
| `qr.py` | `armar_qr`/`qr_svg` → URL AFIP-QR embebida en el PDF |
| `wsaa.py` | `login_con_cert`/`login_con_cert_async` → Ticket de Autorización (TA); firma CMS del TRA |
| `wsfe.py` | `WsfeClient` → `ultimo_autorizado`, `solicitar_cae`/`solicitar_cae_lote`, `consultar` (idempotencia), `param_puntos_venta`/`param_tipos_*` |
| `padron.py` | `PadronClient.get_persona(cuit)` → razón social/domicilio/condición IVA (Consulta Constancia de Inscripción) |
| `render.py` | `renderizar_comprobante_html` → HTML del comprobante, 3 layouts (`oficial`/`detallada`/`simplificada`, `LAYOUTS_INFO`) |
| `seguridad.py` | `asegurar_pdf` (protección + firma digital + sello de tiempo RFC 3161 opcional), `generar_cert_autofirmado` |
| `errores.py` | Jerarquía tipada: `ArcaAuthError`/`ArcaNetworkError`/`ArcaResponseError`/`ArcaBusinessError` |
| `retry.py` / `asyncio_support.py` | `with_retry` portable + wrappers async de las operaciones de red |
| `validadores.py` | `cuit_valido`, normalización/formato de CUIT (mod-11, con o sin guiones) |
| `ejemplos.py` | Galería HTML de muestra con datos ficticios (`python -m arca_fe.ejemplos`) |
| `tests/` | Tests unitarios del core (sin IO ni DB real) |

### Adapter Rambla `backend/services/facturacion/`

| Módulo | Responsabilidad |
|---|---|
| `config.py` | Lee CUIT/PtoVta de `app_settings` + cert/clave de ENV → `CredARCA`. **Gating aquí.** |
| `emisores.py` | `emisor_para(perfil_impuestos, conn, *, override_emisor_id=None)` → resuelve DINÁMICAMENTE contra `emisores_arca`, con override excepcional (ver §6) |
| `emisores_repo.py` | DAL de `emisores_arca` (CRUD, `get_activo_para_condicion`, cert cifrado) |
| `crypto.py` | Fernet encrypt/decrypt de cert/clave (`ARCA_MASTER_KEY`) |
| `wsaa_cache.py` | Caché de TA en tabla `afip_ta` (evita llamar WSAA en cada factura) |
| `catalogos.py` | Refresca/cachea catálogos de ARCA (tipos de comprobante/doc/concepto/IVA/tributos) |
| `puntos_venta.py` | `consultar_puntos_venta` → wrapper de `WsfeClient.param_puntos_venta()` |
| `padron.py` | `resolver_persona`/`verificar_y_actualizar_receptor` (regla "AFIP verificado gana", §4); `verificar_y_crear_perfil_fiscal`/`verificar_y_crear_productora` (§5) |
| `diagnostico.py` | `diagnosticar_emisor`/`cert_info` — chequeo previo de config (2 capas: local + AFIP), ver `arca_fe/TRAMITES_AFIP.md` |
| `comprobante_pedido.py` | Mapea un pedido + emisor → `ComprobanteRequest` (receptor, importe, concepto) |
| `signing_cert.py` | Certificado autofirmado para la firma digital del PDF (`seguridad.asegurar_pdf`) |
| `engine.py` | `emitir_factura`, `emitir_nota_credito`, `previsualizar_factura`/`previsualizar_factura_html` |
| `repo.py` | DAL: `insert_factura`, `update_cae`, `update_error`, `marcar_anulada`, `list_facturas`, etc. |
| `comprobante_render.py` | `factura_html`/`factura_filename` — arma el `ComprobanteFiscal` del pedido y llama a `arca_fe.render` (reemplazó al viejo `pdf.py`, adapter delgado) |

### Routes HTTP

`backend/routes/facturacion.py` (todas las escrituras llevan `@limiter.limit(ADMIN_WRITE_LIMIT)` +
`@map_pg_errors`, salvo los 2 endpoints `async` que no son compatibles con el decorator):

| Método | Path | Quién lo llama |
|---|---|---|
| `GET` | `/api/admin/facturacion/estado` | Panel de config |
| `GET` | `/api/admin/facturacion/layouts` | Selector de layout del PDF (`LAYOUTS_INFO`) |
| `POST` | `/api/admin/arca/catalogos/refrescar` | Refrescar catálogos ARCA cacheados |
| `GET` | `/api/admin/arca/padron/{cuit}` | Autocompletar CUIT (consulta padrón) |
| `GET`/`POST`/`DELETE` | `/api/admin/emisores-arca[/{id}][/cert\|/cert-info\|/puntos-venta\|/diagnostico]` | CRUD de emisores + cert + diagnóstico previo |
| `GET` | `/api/admin/emisores-arca/guia` | Guía de trámites (espeja `TRAMITES_AFIP.md`) |
| `GET` | `/api/alquileres/{id}/facturar/preview[-html]` | Preview de factura antes de emitir |
| `POST` | `/api/alquileres/{id}/facturar` | Admin — botón "Emitir factura" en pedido |
| `POST` | `/api/facturas/{id}/nota-credito` | Admin — botón "Anular con NC" |
| `GET` | `/api/alquileres/{id}/facturas` | Admin — section Facturación en pedido |
| `GET` | `/api/admin/facturas` | Admin — listado global `/admin/facturas` |
| `GET` | `/api/facturas/{id}/pdf` | Admin — descarga PDF desde R2 |
| `POST` | `/api/facturas/{id}/enviar-mail` (async) | Admin — reenviar factura por mail |

---

## 2. Flujo de emisión (`emitir_factura`)

```
emitir_factura(pedido_id)
  │
  ├─ 1. Valida estado pedido ≥ 'confirmado'
  ├─ 2. Resuelve emisor: emisor_para(perfil_impuestos) → 'pablo' | 'santini'
  ├─ 3. credenciales(emisor, conn) → CredARCA  [config.py — GATING aquí]
  ├─ 4. construir_comprobante(pedido, emisor) → ComprobanteRequest
  ├─ 5. pg_advisory_xact_lock(hash(pto_vta, cbte_tipo))  ← mantiene hasta commit
  ├─ 6. Idempotencia: si ya hay factura 'emitida' → devuelve la existente
  ├─ 7. INSERT facturas estado='pendiente'  ← ANTES de llamar al WS
  ├─ 8. get_ta(emisor) → (token, sign)  [wsaa_cache.py]
  ├─ 9. WsfeClient.ultimo_autorizado()  → consulta si hay timeout anterior
  ├─ 10. WsfeClient.solicitar_cae(fecae)
  │     ├─ Aprobado → update_cae(..., estado='emitida') + armar_qr()
  │     └─ Rechazado → update_error(..., errores=[...])  estado='error'
  └─ 11. PDF best-effort (_generar_pdf_background) → R2 / update_pdf_key()
```

**Invariante de lock:** el `pg_advisory_xact_lock` cubre toda la llamada SOAP para que dos
requests simultáneos para el mismo (pto_vta, cbte_tipo) no generen huecos en la numeración.
Namespace distinto al lock de pedidos (`_LOCK_NS = 0xFA0C0000`).

**Nunca DELETE:** toda factura es inmutable. Si falla → `estado='error'` (reintentable).
Anulación = Nota de Crédito (ver §3).

---

## 3. Nota de crédito (`emitir_nota_credito`)

Igual a emisión pero con `es_nota_credito=True` y `CbteAsoc` apuntando a la factura original.
Al aprobar la NC:
- La NC pasa a `estado='emitida'`.
- La factura original pasa a `estado='anulada'` (`marcar_anulada`).
- La relación se guarda en `facturas.nota_credito_de = factura_id`.

---

## 4. Padrón AFIP y verificación del receptor

`services/facturacion/padron.py` — dos funciones sobre el mismo `resolver_persona` (consulta
`PadronClient.get_persona`, reintenta con cada emisor activo con cert hasta que uno resuelva):

- **`verificar_y_actualizar_receptor`** — participa del flujo de EMISIÓN real. **Regla del dueño
  (2026-07-05): la razón social/domicilio/condición IVA de la factura son SIEMPRE los que AFIP
  devuelve para el CUIT usado — nunca lo guardado en la cuenta.** El dato de AFIP tiene prioridad,
  NO es un fallback-si-falta; esto vale tanto en `emitir_factura` como en `previsualizar_factura`
  (ambos deben mostrar/emitir lo mismo). Bloquea la emisión (no factura con un dato sin confirmar)
  si AFIP no puede clasificar la condición IVA.
- **`resolver_persona`** (autocompletado, best-effort) — usado por `GET /api/admin/arca/padron/{cuit}`
  y por el alta de perfiles fiscales/productoras (§5). Nunca devuelve `None` en silencio: o
  devuelve la persona, o levanta `RuntimeError` con el motivo real de AFIP + el ambiente consultado.

El supervisor marca cualquier construcción de datos del receptor (nombre/domicilio) que use el dato
guardado en la cuenta como preferente sobre el resuelto vía AFIP para el CUIT que se está facturando.

---

## 5. Perfiles fiscales múltiples + productoras (#1240/#1242)

Un pedido puede facturarse a nombre de tres niveles, en orden de prioridad — resueltos **en vivo**
(nunca se congela razón social/domicilio, solo el puntero elegido):

```
productora elegida  >  perfil personal elegido  >  default de la cuenta (clientes.*, comportamiento de siempre)
```

- **Perfiles fiscales personales** (`cliente_perfiles_fiscales`, self-service): el cliente puede
  tener varios CUITs propios (personal/freelance). Cada fila nace de una verificación BLOQUEANTE
  contra AFIP (`verificar_y_crear_perfil_fiscal` — 422 si no confirma; sin fallback de entrada
  manual). Uno marcado `es_default=TRUE` (único por cliente, `pg_advisory_xact_lock` por
  `cliente_id` serializa el alta del primero para evitar una carrera de dos altas concurrentes).
- **Productoras** (`productoras`/`productora_miembros`): entidad fiscal **compartida entre varias
  cuentas de cliente**, SIN login propio — el admin la crea (mismo `verificar_y_crear_productora`,
  bloqueante), y vincula/desvincula cuentas desde `/admin/productoras`. Una persona puede pertenecer
  a varias productoras y viceversa.
- **Único punto de palanca**: `services/pedidos_enriquecimiento.py::_resolver_datos_fiscales_pedido`
  implementa la prioridad de 3 niveles — todo consumidor de datos fiscales de un pedido pasa por acá,
  no reimplementa la rama condicional. `alquileres.perfil_fiscal_id`/`productora_id` son mutuamente
  excluyentes (`CHECK`).
- **Identity merge**: ambas tablas nuevas están clasificadas en `identity/merge.py::TABLAS_
  REASIGNADAS` (reasignación dedup-aware) y `auth/account_merge.py::account_is_absorbable` las
  chequea — una cuenta con un perfil fiscal o vínculo a productora no se considera "sin datos que
  perder".

El supervisor marca: un dato fiscal guardado a mano sin pasar por `verificar_y_crear_perfil_fiscal`/
`verificar_y_crear_productora`; un consumidor nuevo de datos fiscales de un pedido que no llame a
`_resolver_datos_fiscales_pedido`. Detalle completo → `MEMORIA.md`/`DECISIONES.md`,
_2026-07-05 — Perfiles fiscales múltiples por cliente + productoras_; tracking issue #1242.

---

## 6. Routing de emisor

**Dinámico, no hardcodeado a nombres fijos** — `emisor_para(perfil_impuestos, conn)` busca en
`emisores_arca` el primer emisor **activo** cuya `condicion_iva` corresponda:

```
perfil_impuestos == 'responsable_inscripto'  →  condicion_iva='responsable_inscripto' → Factura A
                          cualquier otro     →  condicion_iva='monotributo'           → Factura C
```

El admin agrega/cambia/desactiva emisores desde el back-office (`/admin/facturacion/emisores`) sin
tocar código — no hay nombres de emisor fijos en la lógica (los `'pablo'`/`'santini'` de ejemplos
anteriores de este doc eran datos de un momento dado, no una regla). Sin un emisor activo para la
condición → `ValueError` descriptivo antes de tocar ARCA.

**Override excepcional (`override_emisor_id`):** la tabla de arriba es un DEFAULT de Rambla, no una
regla de ARCA — la letra del comprobante depende solo de la `condicion_iva` del EMISOR, nunca del
receptor (un emisor Monotributo siempre factura C, sea quien sea el cliente). Caso real: un cliente
Responsable Inscripto que pide igual una Factura C. `emisor_para(perfil_impuestos, conn, *,
override_emisor_id=None)` acepta un id de emisor puntual que, si se pasa, IGNORA la resolución
automática de arriba (valida que exista y esté activo, nada más) — sigue siendo la única función que
decide "qué emisor factura", no un bypass paralelo. Threading completo: `emitir_factura`/
`previsualizar_factura`/`previsualizar_factura_html` (`emisor_id: Optional[int]`) →
`POST /alquileres/{id}/facturar` (`body.emisor_id`) / `GET .../preview[-html]` (`?emisor_id=`) → el
selector "Emisor" en `FacturaPreviewDialog` (solo visible con más de un emisor activo+con cert, mismo
criterio que "Facturar a nombre de" en checkout). Queda auditado como cualquier factura:
`facturas.emisor` guarda el `nombre` del emisor que realmente facturó, override o no.

Fuente única: `services/facturacion/emisores.py::emisor_para`. Mismo resolver que usa el
motor de contratos (`#1138`). No duplicar esta lógica.

---

## 7. Gating de ambiente (default-deny)

**Regla:** emite en **producción** solo si `config.settings.is_production is True`.
Ante cualquier duda → homologación. INVERSO a GA4 (que expone en prod).

```python
# config.py
ambiente = "produccion" if app_settings.is_production else "homologacion"
```

Credenciales **en la tabla `emisores_arca`**, cifradas con Fernet (`ARCA_MASTER_KEY`). El único
secreto que va en Railway ENV es `ARCA_MASTER_KEY`. Los cert+clave se cargan desde el
back-office en `/admin/facturacion/emisores` — nunca en `app_settings` (GET público + clon de staging).

Si falta `ARCA_MASTER_KEY` o el emisor no tiene cert cargado → `ValueError` descriptivo antes
de tocar ARCA (no 500 críptico).

Test de regresión: `backend/tests/test_facturacion_gating.py`.

---

## 8. Schema de base de datos

### Tabla `facturas`

| Columna | Tipo | Notas |
|---|---|---|
| `id` | SERIAL PK | |
| `pedido_id` | INTEGER FK → alquileres | CASCADE delete |
| `emisor` | TEXT | `nombre` del emisor en `emisores_arca` (dinámico, no un set fijo) |
| `ambiente` | TEXT | `'homologacion'` \| `'produccion'` |
| `cbte_tipo` | INTEGER | 1=FA, 3=NCA, 6=FB, 8=NCB, 11=FC, 13=NCC |
| `pto_vta` | INTEGER | Punto de venta habilitado ante ARCA |
| `cbte_nro` | INTEGER | Número asignado por ARCA (null hasta autorizado) |
| `cae` | TEXT | 14 dígitos, null hasta autorizado |
| `cae_vto` | DATE | |
| `doc_tipo` / `doc_nro` | INTEGER / TEXT | CUIT del receptor |
| `condicion_iva_receptor` | INTEGER | 1=RI, 4=Ex, 5=CF, 6=MT |
| `concepto` | INTEGER | 1=Productos, 2=Servicios, 3=Ambos |
| `imp_neto` / `imp_iva` / `imp_total` | NUMERIC(12,2) | Decimal exacto al centavo — igual al valor enviado a ARCA/QR (bug #1209) |
| `moneda` | TEXT | Siempre `'PES'` |
| `cliente_cuit` / `razon_social` | TEXT | Snapshot del receptor |
| `qr_payload` | TEXT | URL AFIP-QR embebida en el PDF |
| `pdf_key` | TEXT | Key en R2 (null hasta generado) |
| `estado` | TEXT | `pendiente` \| `emitida` \| `error` \| `anulada` |
| `nota_credito_de` | INTEGER FK → facturas | Self-ref; null para facturas originales |
| `raw_request` / `raw_response` / `errores` | JSONB | Debug + mensajes ARCA |
| `fecha_emision` | TIMESTAMPTZ | Seteado al persistir el CAE |
| `created_at` / `created_by` | TIMESTAMPTZ / TEXT | |

### Índice de idempotencia

```sql
CREATE UNIQUE INDEX uq_factura_vigente_por_pedido
  ON facturas (pedido_id)
  WHERE estado IN ('pendiente', 'emitida');
```

Garantiza que un pedido solo tenga una factura activa a la vez. La NC no viola esto (la
original pasa a `'anulada'` antes de que la NC pase a `'emitida'`, dentro de la misma TX).

### Tabla `afip_ta`

Caché del Ticket de Autorización (WSAA). PK = `(ambiente, emisor)`. Se renueva automáticamente
cuando expira (`wsaa_cache.py::get_ta`).

### Tabla `emisores_arca`

Gestión dinámica de emisores desde el back-office (Fase 7).

| Columna | Tipo | Notas |
|---|---|---|
| `id` | SERIAL PK | |
| `nombre` | TEXT UNIQUE | Identificador interno (`'pablo'`, `'santini'`, etc.) |
| `cuit` | TEXT | Con guiones: `'20-XXXXXXXX-X'` |
| `pto_vta` | INTEGER | Punto de venta habilitado ante ARCA |
| `condicion_iva` | TEXT | `'responsable_inscripto'` \| `'monotributo'` \| `'exento'` |
| `cert_enc` | BYTEA | Cert PEM cifrado con Fernet (`ARCA_MASTER_KEY`) |
| `key_enc` | BYTEA | Clave privada PEM cifrada con Fernet |
| `activo` | BOOLEAN | Solo los activos participan en la resolución de emisores |
| `notas` | TEXT | Libre |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

Módulos relacionados: `services/facturacion/emisores_repo.py` (DAL),
`services/facturacion/crypto.py` (Fernet encrypt/decrypt), `routes/facturacion.py` (CRUD REST).

### Tablas `cliente_perfiles_fiscales` / `productoras` / `productora_miembros` (§5)

| Tabla | Notas |
|---|---|
| `cliente_perfiles_fiscales` | `cliente_id` FK, `cuit`/`perfil_impuestos`/`razon_social`/`domicilio_fiscal`/`email_facturacion`/`etiqueta`/`es_default`. Único `(cliente_id, cuit)`; único parcial `es_default` por cliente. |
| `productoras` | `cuit` UNIQUE global, `perfil_impuestos`/`razon_social`/`domicilio_fiscal`/`email_facturacion`/`notas`. Sin login propio. |
| `productora_miembros` | PK compuesta `(productora_id, cliente_id)` — membership many-to-many, sin roles. |

`alquileres.perfil_fiscal_id`/`productora_id` (nullable, `CHECK` mutuamente excluyentes) apuntan a
estas tablas; se resuelven en vivo vía `_resolver_datos_fiscales_pedido` (§5), nunca se congelan.

### En `database.py::init_db()` y en Alembic

Todas las tablas del sistema están en ambas capas, conforme a la regla _2026-06-03_:
- `a2b3c4d5e6f7_facturas_arca.py` — tablas `facturas` y `afip_ta`
- `b1c2d3e4f5a6_emisores_arca.py` — tabla `emisores_arca`
- `c2d3e4f5a6b7_merge_facturacion_heads.py` — merge de los dos heads anteriores
- `h3i4j5k6l7m8_facturas_centavos_numeric.py` — `imp_neto`/`imp_iva`/`imp_total` INTEGER → NUMERIC(12,2) (bug #1209)
- `q7r8s9t0u1v2_perfiles_fiscales_y_productoras.py` — `cliente_perfiles_fiscales`/`productoras`/`productora_miembros` + columnas en `alquileres` (#1242)

---

## 9. Frontend

### Ruta `/admin/facturas`

Listado global de facturas con filtros por emisor, estado y rango de fechas.
Componente: `src/routes/admin/facturas.lazy.tsx`.
API: `facturacionApi.listFacturas(params)` → `GET /api/admin/facturas`.

### Sección Facturación en `/admin/pedidos/:id`

Componente `FacturacionRailSection` en `src/routes/admin/pedidos.$id.lazy.tsx`.

- Muestra la factura vigente del pedido: badge de estado, número, CAE, errores.
- Botón **"Emitir factura"** si el pedido está en estado facturable y no hay factura activa.
- Botón **"Anular con NC"** si la factura está emitida y no tiene NC.
- Link de descarga del PDF (cuando `pdf_key` está presente).
- Badge **"TEST"** si `ambiente == 'homologacion'`.
- **Selector "Emisor"** en el modal `FacturaPreviewDialog` (`PedidoPageHelpers.tsx`) — solo visible
  cuando hay más de un emisor activo+con cert (`useFacturacionArca.emisoresElegibles`). Default
  "Automático" (mismo comportamiento de siempre); elegir otro re-arma el preview y la factura real
  con `override_emisor_id` (§6). Caso de uso: un cliente RI que pide igual Factura C.

### Componente `FacturaBadge`

`src/components/kit/FacturaBadge.tsx` — badge de estado con colores del DS.
Importar de ahí; no recrear variantes.

### Selector "Facturar a nombre de" (checkout + portal)

`CheckoutResumen.tsx` gana el estado `facturacionTarget` (`{perfilFiscalId?, productoraId?}`,
solo se muestra el selector si hay más de una opción) → se propaga a `createOrder`
(`lib/orders.ts`) → `perfil_fiscal_id`/`productora_id` en el body de creación del pedido. Portal
cliente: `FacturacionForm` (solo CUIT + verificar, sin fallback manual) + pantalla "Mis
productoras" (solo lectura). Admin: `/admin/productoras` (CRUD + membership) y panel de solo
lectura de perfiles/productoras en la ficha de cliente (`clientes.lazy.tsx`). Ver §5.

---

## 10. Configuración inicial en Railway

1. **Variable de entorno** (única que va en Railway — tab Variables):
   ```
   ARCA_MASTER_KEY=<Fernet key de 44 chars, generada con: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
   ```
   Puede ser la misma key en staging y producción si comparten DB; si tienen DBs separadas,
   usar keys distintas (los blobs cifrados no son portables entre keys).

2. **Emisores** (Back-office → Finanzas → Emisores ARCA → "Nuevo emisor"):
   - Crear un emisor por CUIT que emite: nombre, CUIT, Punto de Venta, condición IVA.
   - En la card del emisor → "Subir certificado" → pegar cert PEM + clave privada PEM.
   - El cert+clave se cifran con `ARCA_MASTER_KEY` y se guardan en `emisores_arca`.

3. **Homologación primero:** con los cert de homologación y `is_production=False` (staging)
   se pueden emitir facturas de prueba sin afectar la numeración real. Las facturas de
   homologación quedan registradas en la tabla con `ambiente='homologacion'`.

4. **Producción:** subir los cert de producción al emisor (misma UI, distinto cert).
   El gating default-deny hace el resto — staging nunca emite en producción aunque tenga cert.

---

## 11. Reglas invariantes (no violar)

1. **Nunca DELETE de una factura emitida** → anulación siempre por NC.
2. **Gating default-deny** → homologación si hay duda; producción solo con `is_production`.
3. **Credenciales en `emisores_arca`** cifradas con Fernet (`ARCA_MASTER_KEY` en Railway ENV) → nunca en `app_settings` (GET público + clon de staging).
4. **No tocar el core de reservas** → `emitir_factura` hace SELECTs de lectura, sin locks del motor.
5. **Plata al centavo exacto, NUNCA enteros ARS** → `imp_neto`/`imp_iva`/`imp_total` persisten el mismo
   `Decimal` que ya se le mandó a ARCA (`calcular_importes`) y se codificó en el QR fiscal (`armar_qr`).
   Esta tabla es la ÚNICA excepción a la convención de "enteros ARS" de la plata interna
   (`backend/contabilidad/`, 2026-06-07): es un documento fiscal, no plata interna — redondear acá
   dejaba el comprobante impreso por debajo de lo que el CAE/QR autorizaron ante ARCA (bug #1209).
6. **Emisor resuelto por `emisor_para`** → fuente única, dinámico contra `emisores_arca` (§6); no
   hardcodear nombres de emisor ni duplicar la regla de routing. El único desvío sancionado del
   routing automático es `override_emisor_id` (§6) — un id de emisor explícito, nunca un bypass
   que reimplemente la elección en otro lugar.
7. **AFIP verificado gana, siempre** → razón social/domicilio/condición IVA del receptor se
   resuelven contra el padrón para el CUIT usado, nunca desde lo guardado en la cuenta (§4).
8. **Datos fiscales de un pedido: un único punto de palanca** → `_resolver_datos_fiscales_pedido`
   (§5); no reimplementar la prioridad productora>perfil>default en un consumidor nuevo.

El supervisor marca cualquier violación de estas reglas, incluida la reintroducción de un
`int(round(...))` sobre `imp_neto`/`imp_iva`/`imp_total`. Tracking: issue #1139, #1209, #1242.
