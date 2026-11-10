"""Datos del dashboard web: cada ejecución de un reporte deja un JSON con sus KPI.

`output/.dashboard_<fuente>.json` = {generated_at, totals, projects, extra, history[]}.
El dashboard (web/app.py) solo lee estos archivos: no consulta Redmine ni GitLab ni
necesita credenciales. `history` conserva un punto por ejecución para las tendencias.
"""
from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

HISTORY_KEEP = 120


def dataset_path(out_dir: Path, source: str) -> Path:
    return Path(out_dir) / f".dashboard_{source}.json"


def load_dataset(out_dir: Path, source: str) -> dict:
    path = dataset_path(out_dir, source)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Dataset de dashboard ilegible %s: %s", path, exc)
        return {}


def save_dataset(out_dir: Path, source: str, totals: dict, projects: list[dict],
                 extra: dict | None = None, now: datetime.datetime | None = None) -> dict:
    """Guarda el dataset y añade un punto (los totales numéricos) al histórico."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    previous = load_dataset(out_dir, source)
    point = {"ts": now.isoformat(timespec="seconds"),
             **{k: v for k, v in totals.items() if isinstance(v, (int, float))}}
    history = (previous.get("history") or [])[-(HISTORY_KEEP - 1):] + [point]
    payload = {"generated_at": point["ts"], "totals": totals, "projects": projects,
               "extra": extra or {}, "history": history}
    path = dataset_path(out_dir, source)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)  # escritura atómica: el dashboard nunca lee un JSON a medias
    return payload
