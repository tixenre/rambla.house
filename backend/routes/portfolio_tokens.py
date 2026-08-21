"""Endpoint público (con API key) que expone los design tokens de marca de
Rambla — para que el portfolio de Mancino (mancino.dev) muestre a Rambla con
su estética real en vez de una instantánea vieja hardcodeada en otro repo.

Protegido por PORTFOLIO_API_KEY (fail-closed: sin key configurada o header
que no matchea → 401), mismo criterio que los webhooks de Didit/WhatsApp
(ver services/didit/webhook.py). El contenido en sí no es sensible — son los
mismos colores ya visibles en cualquier visita al sitio — la key es solo
para no dejar el endpoint abierto a cualquiera igual.

Valores calcados a mano de design-system/styles/tokens/{colors,shadows}.css
(--color-amber, --color-ink, --color-background, --color-surface, y el
shadow-md). Si esos tokens cambian, actualizar acá también — es una
publicación deliberada, no una lectura en vivo del CSS del frontend.
"""
from fastapi import APIRouter, Header, HTTPException
import hmac

from config import settings

router = APIRouter(tags=["portfolio"])


@router.get("/public/portfolio/brand-tokens")
def get_brand_tokens(x_portfolio_key: str = Header(default="")):
    if not settings.PORTFOLIO_API_KEY or not hmac.compare_digest(
        x_portfolio_key, settings.PORTFOLIO_API_KEY
    ):
        raise HTTPException(status_code=401, detail="unauthorized")

    return {
        "bg": "oklch(0.985 0.012 90)",
        "surface": "oklch(0.97 0.008 85)",
        "ink": "oklch(0.14 0.01 60)",
        "inkDim": "oklch(0.42 0.01 70)",
        "accent": "#fab428",
        "radius": "12px",
        "shadow": "0 4px 12px oklch(0.14 0.01 60 / 10%), 0 1px 3px oklch(0.14 0.01 60 / 6%)",
    }
