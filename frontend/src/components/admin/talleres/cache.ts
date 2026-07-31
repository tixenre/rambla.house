import type { QueryClient } from "@tanstack/react-query";
import type { EdicionAdmin, TallerConcepto } from "@/lib/admin/api/types";

export function updateEdicionInCache(qc: QueryClient, updated: EdicionAdmin) {
  qc.setQueryData(["admin", "talleres"], (prev: TallerConcepto[] | undefined) =>
    prev?.map((c) => ({
      ...c,
      ediciones: c.ediciones.map((e) => (e.id === updated.id ? updated : e)),
    })),
  );
}

export function updateConceptoInCache(qc: QueryClient, updated: TallerConcepto) {
  qc.setQueryData(["admin", "talleres"], (prev: TallerConcepto[] | undefined) =>
    prev?.map((c) => (c.id === updated.id ? updated : c)),
  );
}

// F3: setTallerInstructores devuelve solo { instructores }, no el concepto
// completo — se aplica ese campo puntual en vez de reemplazar la fila.
export function updateConceptoInstructoresInCache(
  qc: QueryClient,
  conceptoId: number,
  instructores: TallerConcepto["instructores"],
) {
  qc.setQueryData(["admin", "talleres"], (prev: TallerConcepto[] | undefined) =>
    prev?.map((c) => (c.id === conceptoId ? { ...c, instructores } : c)),
  );
}

// Mismo patrón: setTallerInstituciones devuelve solo { instituciones }.
export function updateConceptoInstitucionesInCache(
  qc: QueryClient,
  conceptoId: number,
  instituciones: TallerConcepto["instituciones"],
) {
  qc.setQueryData(["admin", "talleres"], (prev: TallerConcepto[] | undefined) =>
    prev?.map((c) => (c.id === conceptoId ? { ...c, instituciones } : c)),
  );
}
