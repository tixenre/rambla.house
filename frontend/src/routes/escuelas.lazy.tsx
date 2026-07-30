import { createLazyFileRoute } from "@tanstack/react-router";

// El listado vive en escuelas.index.lazy.tsx (ruta /escuelas/).
// Este archivo existe vacío para que el generador de TanStack Router no cree
// un componente extra para /escuelas — el Outlet viene de escuelas.tsx.
export const Route = createLazyFileRoute("/escuelas")({});
