/**
 * WhatsAppButton — botón click-to-chat con dropdown de plantillas según el
 * estado del pedido. Abre wa.me en nueva tab con mensaje pre-cargado.
 *
 * Si el teléfono del cliente no es parseable, queda deshabilitado.
 */

import { MessageCircle, ChevronDown } from "lucide-react";

import { Button } from "@/design-system/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/design-system/ui/dropdown-menu";
import { whatsappLink } from "@/lib/whatsapp";
import { templatesForPedido, type PedidoMinimal } from "@/lib/admin/whatsapp-templates";
import { cn } from "@/lib/utils";

type Variant = "default" | "icon" | "compact";

export function WhatsAppButton({
  pedido,
  phone,
  variant = "default",
  className,
}: {
  pedido: PedidoMinimal;
  phone: string | null | undefined;
  variant?: Variant;
  className?: string;
}) {
  const templates = templatesForPedido(pedido);
  const disabled = !whatsappLink({ phone });

  const open = (message: string) => {
    const url = whatsappLink({ phone, message });
    if (url) window.open(url, "_blank", "noopener,noreferrer");
  };

  // Versión icon-only (filas de tabla, espacio chico).
  if (variant === "icon") {
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            disabled={disabled}
            className={cn(
              "grid h-11 w-11 place-items-center rounded-md transition hover:bg-green-50 hover:text-green-600 disabled:cursor-not-allowed disabled:opacity-30 md:h-8 md:w-8",
              !disabled && "text-green-600",
              className,
            )}
            aria-label="Mandar WhatsApp al cliente"
            title={disabled ? "Cliente sin teléfono" : "Mandar WhatsApp"}
          >
            <MessageCircle className="h-4 w-4" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          {templates.map((t) => (
            <DropdownMenuItem key={t.key} onClick={() => open(t.message)} disabled={disabled}>
              {t.label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  }

  // Versión compacta (botón chico, solo texto).
  if (variant === "compact") {
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            disabled={disabled}
            variant="outline"
            size="sm"
            className={cn(
              "gap-1.5 border-green-200 text-green-700 hover:bg-green-50 hover:border-green-300 hover:text-green-700",
              className,
            )}
          >
            <MessageCircle className="h-3.5 w-3.5" />
            WhatsApp
            <ChevronDown className="h-3 w-3" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          {templates.map((t) => (
            <DropdownMenuItem key={t.key} onClick={() => open(t.message)} disabled={disabled}>
              {t.label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  }

  // Default: botón completo con label "Mandar WhatsApp".
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          disabled={disabled}
          className={cn("gap-2 bg-green-600 text-white hover:bg-green-700", className)}
        >
          <MessageCircle className="h-4 w-4" />
          Mandar WhatsApp
          <ChevronDown className="h-4 w-4 opacity-70" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        {templates.map((t) => (
          <DropdownMenuItem
            key={t.key}
            onClick={() => open(t.message)}
            disabled={disabled}
            className="cursor-pointer"
          >
            <div>
              <div className="text-sm font-medium">{t.label}</div>
              {t.message && (
                <div className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{t.message}</div>
              )}
            </div>
          </DropdownMenuItem>
        ))}
        {disabled && (
          <div className="px-2 py-2 text-xs text-muted-foreground">
            El cliente no tiene teléfono cargado.
          </div>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
