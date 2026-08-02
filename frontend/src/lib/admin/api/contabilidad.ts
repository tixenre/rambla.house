import { authedFetch, authedJson, authedPostJson } from "@/lib/authedFetch";
import type {
  TableroData,
  SaldosData,
  Cuenta,
  CuentaInput,
  Movimiento,
  MovimientoInput,
  CambioDivisaInput,
  CambioDivisaResult,
  CobroMensual,
  GastoCategoria,
  GastosPorCategoria,
  ReporteMensual,
  RendicionData,
  PosicionesData,
  ReconciliacionContable,
} from "./types";

export const contabilidadMethods = {
  // Contabilidad (#809) — Fase 1: cuentas/cajas con saldo + tablero. Los ingresos
  // por alquiler salen derivados de alquiler_pagos (no se cargan a mano).
  getTablero: (mes?: string) =>
    authedJson<TableroData>(`/api/admin/contabilidad/tablero${mes ? `?mes=${mes}` : ""}`),
  getSaldos: () => authedJson<SaldosData>("/api/admin/contabilidad/saldos"),
  listCuentas: (incluirInactivas = false) =>
    authedJson<{ cuentas: Cuenta[] }>(
      `/api/admin/contabilidad/cuentas${incluirInactivas ? "?incluir_inactivas=true" : ""}`,
    ),
  createCuenta: (data: CuentaInput) =>
    authedPostJson<Cuenta>("/api/admin/contabilidad/cuentas", data),
  updateCuenta: (id: number, data: Partial<CuentaInput> & { activa?: boolean }) =>
    authedJson<Cuenta>(`/api/admin/contabilidad/cuentas/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deactivateCuenta: async (id: number) => {
    const res = await authedFetch(`/api/admin/contabilidad/cuentas/${id}`, { method: "DELETE" });
    if (!res.ok && res.status !== 204) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail?.detail ?? `DELETE → ${res.status}`);
    }
    return res.json().catch(() => ({}));
  },

  // Contabilidad — movimientos (gasto/transferencia/retiro/aporte/ajuste) + categorías
  listMovimientos: (params?: {
    tipo?: string;
    cuenta_id?: number;
    categoria_id?: number;
    beneficiario?: string;
    desde?: string;
    hasta?: string;
    incluir_anulados?: boolean;
  }) => {
    const sp = new URLSearchParams();
    if (params?.tipo) sp.set("tipo", params.tipo);
    if (params?.cuenta_id) sp.set("cuenta_id", String(params.cuenta_id));
    if (params?.categoria_id) sp.set("categoria_id", String(params.categoria_id));
    if (params?.beneficiario) sp.set("beneficiario", params.beneficiario);
    if (params?.desde) sp.set("desde", params.desde);
    if (params?.hasta) sp.set("hasta", params.hasta);
    if (params?.incluir_anulados) sp.set("incluir_anulados", "true");
    const qs = sp.toString();
    return authedJson<{ movimientos: Movimiento[]; cobros: CobroMensual[]; count: number }>(
      `/api/admin/contabilidad/movimientos${qs ? `?${qs}` : ""}`,
    );
  },
  listBeneficiarios: () =>
    authedJson<{ beneficiarios: string[] }>("/api/admin/contabilidad/beneficiarios"),
  createMovimiento: (data: MovimientoInput) =>
    authedPostJson<Movimiento>("/api/admin/contabilidad/movimientos", data),
  createCambioDivisa: (data: CambioDivisaInput) =>
    authedPostJson<CambioDivisaResult>("/api/admin/contabilidad/cambio-divisa", data),
  updateMovimiento: (id: number, data: Partial<MovimientoInput>) =>
    authedJson<Movimiento>(`/api/admin/contabilidad/movimientos/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  /** Borra un movimiento (deja de contar y desaparece de la lista). El `motivo`
   *  es opcional — ver `contabilidad/commands/movimientos.py::anular_movimiento`. */
  anularMovimiento: (id: number, motivo?: string) =>
    authedPostJson<Movimiento>(`/api/admin/contabilidad/movimientos/${id}/anular`, {
      motivo: motivo ?? null,
    }),
  uploadComprobante: async (id: number, file: File): Promise<{ comprobante_url: string }> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await authedFetch(`/api/admin/contabilidad/movimientos/${id}/comprobante`, {
      method: "POST",
      body: fd,
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(json?.detail ?? `POST → ${res.status}`);
    return json;
  },
  listGastoCategorias: () =>
    authedJson<{ categorias: GastoCategoria[] }>("/api/admin/contabilidad/categorias"),
  createGastoCategoria: (nombre: string) =>
    authedPostJson<GastoCategoria>("/api/admin/contabilidad/categorias", { nombre }),
  getGastos: (desde?: string, hasta?: string) => {
    const sp = new URLSearchParams();
    if (desde) sp.set("desde", desde);
    if (hasta) sp.set("hasta", hasta);
    const qs = sp.toString();
    return authedJson<GastosPorCategoria>(`/api/admin/contabilidad/gastos${qs ? `?${qs}` : ""}`);
  },
  getReporteMensual: (mes: string) =>
    authedJson<ReporteMensual>(`/api/admin/contabilidad/reporte/${mes}`),
  // Rendición de cuentas mensual entre socios
  getRendicion: (mes: string) =>
    authedJson<RendicionData>(`/api/admin/contabilidad/rendicion/${mes}`),
  // Posición ACUMULADA de las 4 partes (la lectura que dice si mover plata tiene
  // sentido — la mensual de arriba arranca de cero cada mes).
  getPosiciones: () => authedJson<PosicionesData>(`/api/admin/contabilidad/posiciones`),
  saldarRendicion: (
    mes: string,
    body: {
      de: string;
      a: string;
      monto: number;
      metodo?: string | null;
      fecha?: string | null;
      nota?: string | null;
    },
  ) => authedPostJson<Movimiento>(`/api/admin/contabilidad/rendicion/${mes}/saldar`, body),
  getPyl: (mes: string) =>
    authedJson<{
      mes: string;
      ingresos: number;
      gastos: number;
      ganancia_neta: number;
      gastos_por_categoria: { categoria: string; monto: number }[];
    }>(`/api/admin/contabilidad/pyl/${mes}`),
  getReconciliacionContable: () =>
    authedJson<ReconciliacionContable>("/api/admin/contabilidad/reconciliacion"),
  cerrarMesContable: (mes: string) =>
    authedJson<{ mes: string; cerrado: boolean }>(`/api/admin/contabilidad/cierres/${mes}`, {
      method: "POST",
    }),
  reabrirMesContable: async (mes: string) => {
    const res = await authedFetch(`/api/admin/contabilidad/cierres/${mes}`, { method: "DELETE" });
    if (!res.ok && res.status !== 204) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail?.detail ?? `DELETE → ${res.status}`);
    }
    return res.json().catch(() => ({}));
  },
};
