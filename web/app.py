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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from common.dashboard_data import load_dataset
from common.settings import REPORTS_ROOT, load_config

app = FastAPI(title="Panel de proyectos", docs_url=None, redoc_url=None)

# La página es un único HTML con CSS/JS en línea y sin CDN: la política lo refleja.
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
       "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


STATIC = Path(__file__).resolve().parent / "static"
SOURCES = ("gespro", "gitlab")
# Umbrales de salud (el mismo criterio que usan los PDF): [bueno, regular]
BANDS = {"gespro": [80, 50], "gitlab": [75, 60]}


def _out_dir() -> Path:
    return REPORTS_ROOT / "output"


def _group(name: str) -> str:
    """Tipo de informe: el nombre sin la fecha final (gitlab_..._2026-11-10.pdf -> gitlab)."""
    return name.rsplit("_", 2)[0] if name.count("_") >= 2 else Path(name).stem


def _scan_reports(out_dir: Path, per_group: int = 5) -> list[dict]:
    """Últimos informes descargables, del más reciente al más antiguo."""
    files = [f for f in (out_dir.iterdir() if out_dir.is_dir() else [])
             if not f.name.startswith(".") and f.suffix in {".pdf", ".csv", ".json", ".xlsx"}]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    groups: dict[str, int] = {}
    out = []
    for f in files:
        key = _group(f.name)
        groups[key] = groups.get(key, 0) + 1
        if groups[key] > per_group:
            continue
        st = f.stat()
        out.append({"name": f.name, "group": key, "kind": f.suffix[1:],
                    "size_kb": round(st.st_size / 1024, 1),
                    "mtime": datetime.datetime.fromtimestamp(
                        st.st_mtime, datetime.timezone.utc).isoformat(timespec="seconds")})
    return out


def _parse_ts(value: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _iso_week(d: datetime.datetime) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-S{w:02d}"


def _activity(sources: dict, out_dir: Path) -> dict:
    """Uso de la suite a partir de lo que ya dejó el cron: ejecuciones registradas
    por fuente (del histórico de cada dataset) e informes generados por tipo."""
    runs = {}
    for name, ds in sources.items():
        stamps = sorted(t for t in (_parse_ts(h.get("ts")) for h in ds.get("history", [])) if t)
        weeks: dict[str, int] = {}
        for t in stamps:
            weeks[_iso_week(t)] = weeks.get(_iso_week(t), 0) + 1
        runs[name] = {
            "count": len(stamps),
            "first": stamps[0].isoformat(timespec="seconds") if stamps else None,
            "last": stamps[-1].isoformat(timespec="seconds") if stamps else None,
            "per_week": [{"week": k, "runs": v} for k, v in sorted(weeks.items())][-12:],
        }
    groups: dict[str, dict] = {}
    if out_dir.is_dir():
        for f in out_dir.iterdir():
            if f.name.startswith(".") or f.suffix not in {".pdf", ".csv", ".json", ".xlsx"}:
                continue
            st = f.stat()
            g = groups.setdefault(_group(f.name), {"group": _group(f.name), "files": 0, "size_kb": 0.0, "last": 0.0})
            g["files"] += 1
            g["size_kb"] += st.st_size / 1024
            g["last"] = max(g["last"], st.st_mtime)
    reports = [{"group": g["group"], "files": g["files"], "size_kb": round(g["size_kb"], 1),
                "last": datetime.datetime.fromtimestamp(g["last"], datetime.timezone.utc).isoformat(timespec="seconds")}
               for g in sorted(groups.values(), key=lambda x: -x["last"])]
    return {"runs": runs, "reports": reports}


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
        "activity": _activity({k: v for k, v in sources.items() if v}, out_dir),
    }, headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/download/{name}")
def download(name: str) -> FileResponse:
    # protege contra path traversal: solo nombres simples dentro de output/
    if "/" in name or "\\" in name or ".." in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="Nombre inválido")
    path = _out_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No encontrado")
    return FileResponse(path)
