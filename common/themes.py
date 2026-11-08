"""Temas visuales para los PDF (Fase 4). Paletas en RGB (0-255)."""
from __future__ import annotations

THEMES: dict[str, dict[str, tuple[int, int, int]]] = {
    "corporativo": {  # paleta histórica — pixel-idéntica a la versión original
        "ink": (33, 37, 41),
        "accent": (176, 141, 66),
        "gray": (110, 118, 129),
        "light": (245, 246, 248),
        "white": (255, 255, 255),
    },
    "minimal": {
        "ink": (17, 17, 17),
        "accent": (17, 17, 17),
        "gray": (120, 120, 120),
        "light": (250, 250, 250),
        "white": (255, 255, 255),
    },
    "ejecutivo": {
        "ink": (15, 23, 42),
        "accent": (37, 99, 235),
        "gray": (100, 116, 139),
        "light": (241, 245, 249),
        "white": (255, 255, 255),
    },
}

DEFAULT_THEME = "corporativo"


def get_theme(name: str | None) -> dict[str, tuple[int, int, int]]:
    """Devuelve el tema pedido; nombre desconocido → error accionable."""
    key = (name or DEFAULT_THEME).lower()
    if key not in THEMES:
        valid = ", ".join(sorted(THEMES))
        raise SystemExit(f"ERROR: tema desconocido {name!r}. Válidos: {valid}")
    return THEMES[key]
