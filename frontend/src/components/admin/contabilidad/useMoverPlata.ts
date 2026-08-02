/**
 * useMoverPlata.ts — el estado del formulario de "Mover plata".
 *
 * Vive aparte de `MoverPlataForm.tsx` porque son dos cosas distintas: acá está la
 * máquina (13 campos, las listas que alimentan los selectores, la validación y el
 * envío), allá solo el layout. Antes estaban juntos en un archivo de ~390 líneas
 * donde había que leer el JSX para entender qué se manda.
 *
 * La DERIVACIÓN (qué `tipo` de movimiento sale de cada respuesta) no está acá:
 * vive en `lib/admin/mover-plata.ts`, puro y testeado sin React. Este hook solo
 * junta las respuestas y se las pasa.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { adminApi, type Cuenta } from "@/lib/admin/api";
import {
  camposVisibles,
  derivarMovimiento,
  esCambioDeDivisa,
  MoverPlataInvalido,
  type QuePaso,
  type RespuestasMoverPlata,
} from "@/lib/admin/mover-plata";

export function useMoverPlata({
  inicial,
  onCreated,
}: {
  inicial?: Partial<RespuestasMoverPlata>;
  onCreated: () => void;
}) {
  const [quePaso, setQuePaso] = useState<QuePaso>(inicial?.quePaso ?? "pague");
  const [monto, setMonto] = useState(inicial?.monto ? String(inicial.monto) : "");
  const [origen, setOrigen] = useState(
    inicial?.cuentaOrigenId ? String(inicial.cuentaOrigenId) : "",
  );
  const [destino, setDestino] = useState(
    inicial?.cuentaDestinoId ? String(inicial.cuentaDestinoId) : "",
  );
  const [categoria, setCategoria] = useState("");
  const [esDelSocio, setEsDelSocio] = useState(false);
  const [cotizacion, setCotizacion] = useState("");
  const [montoDestino, setMontoDestino] = useState("");
  const [metodo, setMetodo] = useState("");
  const [fecha, setFecha] = useState("");
  const [nota, setNota] = useState("");
  const [beneficiario, setBeneficiario] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const cuentasQ = useQuery({
    queryKey: ["admin", "contabilidad", "cuentas-list"],
    queryFn: () => adminApi.listCuentas(),
  });
  const catsQ = useQuery({
    queryKey: ["admin", "contabilidad", "categorias"],
    queryFn: () => adminApi.listGastoCategorias(),
  });
  const benQ = useQuery({
    queryKey: ["admin", "contabilidad", "beneficiarios"],
    queryFn: () => adminApi.listBeneficiarios(),
  });

  // Estabilizadas: si no, cada render devuelve un array nuevo y el `useMemo` de
  // abajo se recalcula siempre.
  const cuentas: Cuenta[] = useMemo(() => cuentasQ.data?.cuentas ?? [], [cuentasQ.data]);
  const categorias = useMemo(() => catsQ.data?.categorias ?? [], [catsQ.data]);
  const beneficiarios = useMemo(() => benQ.data?.beneficiarios ?? [], [benQ.data]);

  const respuestas: RespuestasMoverPlata = useMemo(() => {
    const monedaDe = (id: string) => cuentas.find((c) => String(c.id) === id)?.moneda ?? null;
    return {
      quePaso,
      monto: Number(monto) || 0,
      cuentaOrigenId: origen ? Number(origen) : null,
      cuentaDestinoId: destino ? Number(destino) : null,
      categoriaId: categoria ? Number(categoria) : null,
      esDelSocio,
      monedaOrigen: monedaDe(origen),
      monedaDestino: monedaDe(destino),
      cotizacion: cotizacion ? Number(cotizacion) : null,
      montoDestino: montoDestino ? Number(montoDestino) : null,
      metodo: metodo || null,
      fecha: fecha || null,
      nota: nota || null,
      beneficiario: beneficiario || null,
    };
  }, [
    quePaso,
    monto,
    origen,
    destino,
    categoria,
    esDelSocio,
    cotizacion,
    montoDestino,
    metodo,
    fecha,
    nota,
    beneficiario,
    cuentas,
  ]);

  const campos = camposVisibles(quePaso);
  const cambioDivisa = esCambioDeDivisa(respuestas);

  // La cuenta corriente de un socio (`tipo === "socio"`) NO es plata real, así que
  // el backend BLOQUEA `retiro`/`aporte` contra ella (`_validar_cuentas_y_categoria`,
  // MEMORIA 2026-07-02). Sacarla del selector en esos dos casos evita ofrecer una
  // combinación que termina en un 400 cuyo mensaje habla de "gasto, transferencia o
  // ajuste" — justo las palabras que este form esconde. Para todo lo demás (un gasto
  // que pagó el socio con su plata, un reparto) la cuenta sigue disponible.
  //
  // Las cuentas NO se filtran por moneda: si el admin elige dos monedas distintas,
  // eso ES un cambio de divisa y el form se adapta solo (`esCambioDeDivisa`).
  const sinCC = cuentas.filter((c) => c.tipo !== "socio");
  const cuentasOrigen = quePaso === "pague" && esDelSocio ? sinCC : cuentas;
  const cuentasDestino = quePaso === "entro" ? sinCC : cuentas;

  /** Marca "no es un gasto del negocio" y limpia la cuenta si quedó una que el
   *  backend va a rechazar (un `retiro` no puede salir de la CC de un socio). */
  const marcarEsDelSocio = (v: boolean) => {
    setEsDelSocio(v);
    if (v && cuentas.find((c) => String(c.id) === origen)?.tipo === "socio") setOrigen("");
  };

  // A propósito NO resetea `quePaso`: se suelen cargar varios movimientos del
  // mismo tipo seguidos, y volver a "Pagué algo" cada vez obliga a re-elegir.
  const reset = () => {
    setMonto("");
    setOrigen("");
    setDestino("");
    setCategoria("");
    setEsDelSocio(false);
    setCotizacion("");
    setMontoDestino("");
    setMetodo("");
    setFecha("");
    setNota("");
    setBeneficiario("");
    setFile(null);
  };

  const crear = useMutation({
    mutationFn: async () => {
      const d = derivarMovimiento(respuestas);
      if (d.kind === "cambio_divisa") return adminApi.createCambioDivisa(d.body);
      const mov = await adminApi.createMovimiento(d.body);
      if (file) await adminApi.uploadComprobante(mov.id, file);
      return mov;
    },
    onSuccess: () => {
      reset();
      toast.success("Movimiento registrado");
      onCreated();
    },
    onError: (e) => toast.error("No se pudo registrar", { description: (e as Error).message }),
  });

  /** Valida en castellano ANTES de mandar: el mismo módulo puro que deriva el
   *  cuerpo sabe qué falta, así no se manda un request que ya sabemos que falla.
   *  El backend revalida todo igual. */
  const enviar = () => {
    try {
      derivarMovimiento(respuestas);
    } catch (err) {
      if (err instanceof MoverPlataInvalido) return toast.error(err.message);
      throw err;
    }
    crear.mutate();
  };

  return {
    // respuestas
    quePaso,
    setQuePaso,
    monto,
    setMonto,
    origen,
    setOrigen,
    destino,
    setDestino,
    categoria,
    setCategoria,
    esDelSocio,
    marcarEsDelSocio,
    cotizacion,
    setCotizacion,
    montoDestino,
    setMontoDestino,
    metodo,
    setMetodo,
    fecha,
    setFecha,
    nota,
    setNota,
    beneficiario,
    setBeneficiario,
    setFile,
    // listas y derivados que necesita el layout
    categorias,
    beneficiarios,
    cuentasOrigen,
    cuentasDestino,
    campos,
    cambioDivisa,
    // acción
    enviando: crear.isPending,
    enviar,
  };
}
