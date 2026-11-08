"""Plugin de ejemplo: registra en el log cada export generado (Fase 4).

Actívalo en config.yaml:

    plugins:
      enabled: ["logfile"]
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def post_export(report_type: str, paths, cfg) -> None:
    for p in paths:
        log.info("[plugin logfile] %s exportó %s", report_type, p)
