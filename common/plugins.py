"""Cargador de plugins (Fase 4).

Los plugins son módulos Python en ``plugins/`` listados en
``plugins.enabled`` (config.yaml). Hooks soportados (opcionales):

- ``post_collect(report_type, rows, cfg) -> list | None`` — transforma/filtra
  las filas antes del render. Devolver None = sin cambios.
- ``post_export(report_type, paths, cfg) -> None`` — tras generar todos los
  formatos (PDF, CSV, JSON...).

Un plugin que falla se loggea y no rompe el reporte.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

log = logging.getLogger(__name__)

PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"


def load_plugins(cfg: dict) -> list:
    """Importa los plugins habilitados. Ignora los que fallen al importar."""
    enabled = (cfg.get("plugins") or {}).get("enabled") or []
    mods = []
    for name in enabled:
        path = PLUGINS_DIR / f"{name}.py"
        if not path.is_file():
            log.warning("Plugin no encontrado: %s (%s)", name, path)
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"plugins.{name}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mods.append(mod)
            log.info("Plugin cargado: %s", name)
        except Exception as e:
            log.warning("Plugin %s falló al importar: %s", name, e)
    return mods


def run_hook(mods: list, hook: str, *args):
    """Ejecuta el hook en cada plugin. Errores aislados por plugin."""
    results = []
    for mod in mods:
        fn = getattr(mod, hook, None)
        if not callable(fn):
            continue
        try:
            results.append(fn(*args))
        except Exception as e:
            log.warning("Plugin %s: hook %s falló: %s",
                        getattr(mod, "__name__", "?"), hook, e)
    return results
