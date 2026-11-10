"""Dashboard web de KPI (FastAPI): tareas de Redmine/GESPRO y proyectos de GitLab.

Servicio OPCIONAL — no forma parte del crontab:
    uvicorn web.app:app --port 8080

No consulta Redmine ni GitLab: lee los `output/.dashboard_*.json` que deja cada
ejecución del cron (common/dashboard_data.py), así que no necesita credenciales
y responde al instante. También lista los últimos informes para descargarlos.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from common.dashboard_data import load_dataset
from common.settings import REPORTS_ROOT, load_config

app = FastAPI(title="Panel de proyectos", docs_url=None, redoc_url=None)

STATIC = Path(__file__).resolve().parent / "static"
SOURCES = ("gespro", "gitlab")
# Umbrales de salud (el mismo criterio que usan los PDF): [bueno, regular]
BANDS = {"gespro": [80, 50], "gitlab": [75, 60]}


def _out_dir() -> Path:
    return REPORTS_ROOT / "output"


def _scan_reports(out_dir: Path, per_group: int = 5) -> list[dict]:
    """Últimos informes descargables, del más reciente al más antiguo."""
    files = [f for f in (out_dir.iterdir() if out_dir.is_dir() else [])
             if not f.name.startswith(".") and f.suffix in {".pdf", ".csv", ".json", ".xlsx"}]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    groups: dict[str, int] = {}
    out = []
    for f in files:
        key = f.name.rsplit("_", 2)[0] if f.name.count("_") >= 2 else f.stem
        groups[key] = groups.get(key, 0) + 1
        if groups[key] > per_group:
            continue
        st = f.stat()
        out.append({"name": f.name, "group": key, "kind": f.suffix[1:],
                    "size_kb": round(st.st_size / 1024, 1),
                    "mtime": datetime.datetime.fromtimestamp(
                        st.st_mtime, datetime.timezone.utc).isoformat(timespec="seconds")})
    return out


def _company() -> dict:
    try:
        c = load_config().get("company", {})
    except SystemExit:  # config inválida: el panel sigue mostrando los datos
        c = {}
    return {"name": c.get("name", ""), "unit": c.get("unit", "")}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC / "dashboard.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/dashboard")
def dashboard() -> JSONResponse:
    out_dir = _out_dir()
    sources = {s: load_dataset(out_dir, s) for s in SOURCES}
    return JSONResponse({
        "company": _company(),
        "now": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "bands": BANDS,
        "sources": {k: v for k, v in sources.items() if v},
        "reports": _scan_reports(out_dir),
    }, headers={"Cache-Control": "no-cache"})


@app.get("/download/{name}")
def download(name: str) -> FileResponse:
    # protege contra path traversal: solo nombres simples dentro de output/
    if "/" in name or "\\" in name or ".." in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="Nombre inválido")
    path = _out_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No encontrado")
    return FileResponse(path)
