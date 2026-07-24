/**
 * ClienteAutocomplete — buscador de fichas de cliente para el pedido.
 *
 * Fuente única (reusada por el editor v2 `pedidos.$id.lazy.tsx`, el legacy
 * `PedidoPage.tsx` y `ReservaDialog.tsx` del Estudio): se escribe, se debouncea,
 * se busca contra /api/clientes y al elegir una ficha el caller decide qué
 * campos del pedido completar (cliente_id + contacto + descuento). Ver MEMORIA
 * _Datos del pedido: contacto en vivo, plata congelada_ — al vincular
 * `cliente_id`, el backend sirve el contacto en vivo desde la ficha.
 *
 * Si no hay ficha, ofrece crear una in-place (`POST /api/clientes`, mismo
 * mínimo que exige el backend: nombre + apellido) sin salir del picker — el
 * texto tipeado se precarga partido en nombre/apellido, editable antes de
 * confirmar. Al crearse, se resuelve por el mismo `onPick` que una ficha
 * existente — los 3 callers no necesitan saber que la ficha es nueva.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { UserPlus } from "lucide-react";

import { SearchInput } from "@/design-system/ui/search-input";
import { Input } from "@/design-system/ui/input";
import { Button } from "@/design-system/ui/button";
import { adminApi, type Cliente } from "@/lib/admin/api";
import { nombreCliente } from "@/lib/cliente-nombre";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";

function splitNombre(q: string): { nombre: string; apellido: string } {
  const partes = q.trim().split(/\s+/);
  if (partes.length <= 1) return { nombre: partes[0] ?? "", apellido: "" };
  return { nombre: partes[0], apellido: partes.slice(1).join(" ") };
}

export function ClienteAutocomplete({
  onPick,
  placeholder = "Buscar ficha existente…",
  className,
}: {
  onPick: (c: Cliente) => void;
  placeholder?: string;
  className?: string;
}) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [creando, setCreando] = useState(false);
  const [nombre, setNombre] = useState("");
  const [apellido, setApellido] = useState("");
  const debouncedQ = useDebouncedValue(q.trim(), 250);

  const clientesQ = useQuery({
    queryKey: ["admin", "clientes", { q: debouncedQ }],
    queryFn: () => adminApi.listClientes({ q: debouncedQ || undefined, per_page: 20 }),
    enabled: open && debouncedQ.length > 0,
  });

  const crearMut = useMutation({
    mutationFn: () => adminApi.createCliente({ nombre: nombre.trim(), apellido: apellido.trim() }),
    onSuccess: (c) => {
      toast.success("Cliente creado");
      qc.invalidateQueries({ queryKey: ["admin", "clientes"] });
      onPick(c);
      setQ("");
      setOpen(false);
      setCreando(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const abrirCreacion = () => {
    const partes = splitNombre(q);
    setNombre(partes.nombre);
    setApellido(partes.apellido);
    setCreando(true);
  };

  return (
    <div className={className}>
      <div className="relative">
        <SearchInput
          value={q}
          role="combobox"
          aria-expanded={open && q.trim().length > 0}
          aria-haspopup="listbox"
          aria-autocomplete="list"
          aria-controls="cliente-autocomplete-list"
          onValueChange={(v) => {
            setQ(v);
            setOpen(true);
            setCreando(false);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder={placeholder}
        />
        {open && q.trim().length > 0 && (
          <div
            role="listbox"
            id="cliente-autocomplete-list"
            className="absolute z-30 left-0 right-0 mt-1 card shadow-md max-h-72 overflow-auto"
          >
            {creando ? (
              <div className="space-y-2 p-3" onMouseDown={(e) => e.preventDefault()}>
                <div className="grid grid-cols-2 gap-2">
                  <Input
                    autoFocus
                    value={nombre}
                    onChange={(e) => setNombre(e.target.value)}
                    placeholder="Nombre"
                    className="h-8 text-sm"
                  />
                  <Input
                    value={apellido}
                    onChange={(e) => setApellido(e.target.value)}
                    placeholder="Apellido"
                    className="h-8 text-sm"
                  />
                </div>
                <div className="flex justify-end gap-2">
                  <Button type="button" variant="ghost" size="sm" onClick={() => setCreando(false)}>
                    Cancelar
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    disabled={!nombre.trim() || !apellido.trim() || crearMut.isPending}
                    loading={crearMut.isPending}
                    onClick={() => crearMut.mutate()}
                  >
                    Crear ficha
                  </Button>
                </div>
              </div>
            ) : (
              <>
                {clientesQ.isLoading && (
                  <div className="p-3 text-xs text-muted-foreground">Buscando…</div>
                )}
                {clientesQ.data?.items.length === 0 && (
                  <div className="p-3 text-xs text-muted-foreground">Sin resultados</div>
                )}
                {(clientesQ.data?.items ?? []).map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    role="option"
                    aria-selected={false}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      onPick(c);
                      setQ("");
                      setOpen(false);
                    }}
                    className="w-full text-left px-3 py-2 hover:bg-accent/50 transition"
                  >
                    <div className="text-sm text-ink">{nombreCliente(c)}</div>
                    <div className="text-xs text-muted-foreground">
                      {[c.email, c.telefono].filter(Boolean).join(" · ") || "—"}
                    </div>
                  </button>
                ))}
                <button
                  type="button"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    abrirCreacion();
                  }}
                  className="flex w-full items-center gap-1.5 border-t hairline px-3 py-2 text-left text-sm text-ink hover:bg-accent/50 transition"
                >
                  <UserPlus className="h-3.5 w-3.5 shrink-0" />
                  Crear ficha nueva{q.trim() ? `: "${q.trim()}"` : ""}
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
