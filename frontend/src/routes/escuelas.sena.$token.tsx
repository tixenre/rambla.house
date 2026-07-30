import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/escuelas/sena/$token")({
  head: () => ({
    meta: [{ title: "Completá tu seña — Rambla Escuelas" }, { name: "robots", content: "noindex" }],
  }),
});
