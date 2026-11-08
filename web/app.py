"""Dashboard web mínimo (Fase 4, FastAPI + Jinja2).

Servicio OPCIONAL — no forma parte del crontab:
    uvicorn web.app:app --port 8080

Lista los últimos reportes generados (PDF y exports), permite su descarga
y muestra las métricas del último snapshot de cada reporte.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from common.settings import REPORTS_ROOT

app = FastAPI(title="REPORTS — Dashboard", docs_url=None)


def _scan_reports(out_dir: Path) -> dict[str, list[dict]]:
    """Últimos archivos por prefijo de reporte."""
    groups: dict[str, list] = {}
    for f in sorted(out_dir.iterdir() if out_dir.is_dir() else [],
                    key=lambda p: p.stat().st_mtime, reverse=True):
        if f.name.startswith(".") or f.suffix not in {".pdf", ".csv", ".json", ".xlsx"}:
            continue
        key = f.name.rsplit("_", 1)[0]
        groups.setdefault(key, [])
        if len(groups[key]) < 5:
            groups[key].append({
                "name": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "mtime": __import__("datetime").datetime.fromtimestamp(
                    f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
    return groups


def _snapshots(out_dir: Path) -> dict[str, dict]:
    out = {}
    for f in out_dir.glob(".snapshot_*.json"):
        try:
            out[f.stem.replace(".snapshot_", "")] = json.loads(
                f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return out


_PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>REPORTS — Dashboard</title>
<style>
body{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#212529}
h1{border-bottom:3px solid #B08D42;padding-bottom:.4rem}
h2{color:#B08D42;margin-top:2rem}
table{border-collapse:collapse;width:100%}
td,th{border:1px solid #ddd;padding:.4rem .6rem;font-size:.9rem}
th{background:#F5F6F8;text-align:left}
code{background:#F5F6F8;padding:.1rem .3rem;border-radius:4px}
</style></head><body>
<h1>REPORTS — Dashboard</h1>
{% for group, files in reports.items() %}
<h2>{{ group }}</h2>
<table><tr><th>Archivo</th><th>Tamaño</th><th>Fecha</th></tr>
{% for f in files %}<tr><td><a href="/download/{{ f.name }}">{{ f.name }}</a></td>
<td>{{ f.size_kb }} KB</td><td>{{ f.mtime }}</td></tr>{% endfor %}
</table>
{% endfor %}
<h2>Últimas métricas (snapshots)</h2>
{% for name, snap in snapshots.items() %}
<h3>{{ name }}</h3>
<table><tr><th>Proyecto</th>{% for m in metrics_keys %}<th>{{ m }}</th>{% endfor %}</tr>
{% for proj, metrics in snap.items() %}<tr><td>{{ proj }}</td>
{% for m in metrics_keys %}<td>{{ metrics.get(m, "—") }}</td>{% endfor %}</tr>{% endfor %}
</table>
{% endfor %}
{% if not reports %}<p>Sin reportes en <code>output/</code> todavía.</p>{% endif %}
</body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    from jinja2 import Template

    out_dir = REPORTS_ROOT / "output"
    reports = _scan_reports(out_dir)
    snaps = _snapshots(out_dir)
    metrics_keys = sorted({k for s in snaps.values()
                           for m in s.values() if isinstance(m, dict)
                           for k in m})
    return Template(_PAGE).render(reports=reports, snapshots=snaps,
                                  metrics_keys=metrics_keys)


@app.get("/download/{name}")
def download(name: str) -> FileResponse:
    # protege contra path traversal: solo nombres simples dentro de output/
    if "/" in name or ".." in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="Nombre inválido")
    path = REPORTS_ROOT / "output" / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No encontrado")
    return FileResponse(path)
