"""Export de datos de reportes a formatos alternativos (Fase 3).

CSV y JSON con stdlib; Excel (xlsx) solo si openpyxl está instalado —
si falta, se omite con warning degradando en lugar de fallar.
"""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def _to_csv(headers: list[str], rows: list[list], out_path: Path) -> None:
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for row in rows:
            w.writerow(row)


def _to_json(headers: list[str], rows: list[list], out_path: Path) -> None:
    payload = [dict(zip(headers, row, strict=False)) for row in rows]
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _to_xlsx(headers: list[str], rows: list[list], out_path: Path) -> bool:
    try:
        from openpyxl import Workbook
    except ImportError:
        log.warning("openpyxl no instalado: se omite el export xlsx")
        return False
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(list(row))
    wb.save(out_path)
    return True


_WRITERS = {"csv": _to_csv, "json": _to_json, "xlsx": _to_xlsx}


def export_rows(headers: list[str], rows: list[list],
                out_path_base: Path, formats: list[str]) -> list[Path]:
    """Genera los formatos pedidos junto al PDF. Devuelve las rutas creadas."""
    created: list[Path] = []
    for fmt in formats:
        if fmt == "pdf":
            continue
        writer = _WRITERS.get(fmt)
        if writer is None:
            log.warning("Formato de export desconocido: %s", fmt)
            continue
        out = out_path_base.with_suffix(f".{fmt}")
        if writer(headers, rows, out) is False:
            continue
        created.append(out)
        log.info("Export generado: %s", out)
    return created
