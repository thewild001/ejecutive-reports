"""Snapshots de métricas entre ejecuciones (Fase 3, incremental ligero).

Cada reporte guarda ``output/.snapshot_<prefix>.json`` con sus métricas
clave. En la ejecución siguiente se comparan y el resumen ejecutivo menciona
los deltas más relevantes.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_ARROW = {1: "↑", -1: "↓", 0: "="}


def snapshot_path(out_dir: Path, prefix: str) -> Path:
    return out_dir / f".snapshot_{prefix}.json"


def load(out_dir: Path, prefix: str) -> dict:
    path = snapshot_path(out_dir, prefix)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Snapshot ilegible %s: %s", path, e)
        return {}


def save(out_dir: Path, prefix: str, payload: dict) -> None:
    path = snapshot_path(out_dir, prefix)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                               default=str), encoding="utf-8")


def diff(previous: dict, current: dict, labels: dict[str, str]) -> list[str]:
    """Compara {proyecto: {metrica: numero}} y devuelve frases de delta.

    ``labels`` mapea nombre interno de métrica a texto legible en español.
    Solo se reportan métricas que cambian y proyectos presentes en ambos.
    """
    deltas: list[str] = []
    for name, curr_metrics in current.items():
        prev_metrics = previous.get(name)
        if not isinstance(prev_metrics, dict):
            continue
        for metric, curr_val in curr_metrics.items():
            prev_val = prev_metrics.get(metric)
            if not isinstance(curr_val, (int, float)) or not isinstance(prev_val, (int, float)):
                continue
            if curr_val == prev_val:
                continue
            arrow = _ARROW[(curr_val > prev_val) - (curr_val < prev_val)]
            label = labels.get(metric, metric)
            deltas.append(f"{name}: {label} {prev_val} → {curr_val} ({arrow}{abs(curr_val - prev_val):g})")
    return deltas
