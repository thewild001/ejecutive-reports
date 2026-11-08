"""i18n mínimo (Fase 4): catálogos YAML en locales/, fallback a español.

Uso::

    from common.i18n import t
    t("executive_summary", locale)  # "Resumen ejecutivo" / "Executive summary"

El contenido dinámico (nombres de proyectos, fuentes RSS) no se traduce.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

DEFAULT_LOCALE = "es"
_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"


@lru_cache(maxsize=8)
def _catalog(locale: str) -> dict:
    path = _LOCALES_DIR / f"{locale}.yaml"
    if not path.is_file():
        log.warning("Catálogo i18n no encontrado: %s", path)
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def t(key: str, locale: str = DEFAULT_LOCALE) -> str:
    """Traduce key al locale; fallback es → la propia clave."""
    for loc in (locale, DEFAULT_LOCALE):
        text = _catalog(loc).get(key)
        if text:
            return text
    log.warning("i18n: clave sin traducción: %s", key)
    return key
