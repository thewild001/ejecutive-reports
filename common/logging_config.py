"""Centralized logging setup for the reports suite.

All modules should use ``logging.getLogger(__name__)``. Entry points call
:func:`setup_logging` once, after loading configuration.

Config section (optional) in config.yaml:

    logging:
      level: "INFO"          # DEBUG | INFO | WARNING | ERROR
      file: "output/reports.log"   # vacío = solo consola
      max_bytes: 1048576           # rotación del archivo (1 MB default)
      backup_count: 3
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_initialized = False


def setup_logging(cfg: dict | None = None, root: Path | None = None) -> None:
    """Configure root logger from the optional ``logging`` config section.

    Idempotente: llamadas posteriores no duplican handlers.
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    section = (cfg or {}).get("logging", {}) or {}
    level_name = str(section.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    log_file = section.get("file")
    if log_file:
        log_path = Path(log_file)
        if not log_path.is_absolute() and root is not None:
            log_path = root / log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_path,
                maxBytes=int(section.get("max_bytes", 1_048_576)),
                backupCount=int(section.get("backup_count", 3)),
                encoding="utf-8",
            )
        )

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)
    for h in handlers:
        h.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=handlers, force=True)
    logging.getLogger(__name__).debug(
        "Logging inicializado (nivel=%s, archivo=%s)", level_name, log_file or "no"
    )
