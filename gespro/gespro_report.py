#!/usr/bin/env python3
"""
GESPRO/Redmine — Informe ejecutivo de estado de proyectos.
Genérico: cualquier instancia Redmine/GESPRO vía config.yaml + REDMINE_API_KEY.

Salida: PDF con indicadores consolidados, salud por proyecto, carga por miembro,
tareas atrasadas y recomendaciones accionables.
"""
from __future__ import annotations

import datetime
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.settings import load_config, require_env
from common.delivery import deliver, delivery_exit_code
from common.settings import rotate_outputs
from common.cache import ApiCache
from common.exporters import export_rows
from common.http_client import ApiError, build_client, checked_json
from common.plugins import load_plugins, run_hook
from gespro.analytics import analyze_trends

log = logging.getLogger(__name__)


class RedmineAPI:
    def __init__(self, base_url: str, api_key: str, verify_ssl: bool = False,
                 timeout: float = 30.0, cache=None):
        self.cache = cache
        self.client = build_client(
            base_url,
            headers={"X-Redmine-API-Key": api_key, "Content-Type": "application/json"},
            verify_ssl=verify_ssl,
            timeout=timeout,
        )

    def _get(self, path, params=None):
        return checked_json(self.client, path, params, cache=self.cache)

    def paginate(self, path, key, params=None, limit=100):
        params = dict(params or {}, limit=limit)
        records, offset = [], 0
        while True:
            params["offset"] = offset
            data = self._get(path, params)
            batch = data.get(key, [])
            records.extend(batch)
            if offset + len(batch) >= data.get("total_count", len(batch)):
                break
            offset += limit
        return records

    def projects(self):
        return self.paginate("/projects.json", "projects")

    def project(self, pid):
        return self._get(f"/projects/{pid}.json").get("project", {})

    def memberships(self, pid):
        try:
            return self._get(f"/projects/{pid}/memberships.json", {"limit": 100}).get("memberships", [])
        except ApiError:
            log.warning("Memberships no disponibles para el proyecto %s", pid)
            return []

    def issues(self, pid, limit=200):
        return self.paginate("/issues.json", "issues", {"project_id": pid}, limit=limit)


def field_name(issue: dict, field: str) -> str:
    val = issue.get(field)
    return val.get("name", "") if isinstance(val, dict) else (str(val) if val else "")


def is_overdue(issue: dict, closed_names: set) -> bool:
    if field_name(issue, "status").lower() in closed_names:
        return False
    due = issue.get("due_date")
    if not due:
        return False
    try:
        return datetime.date.fromisoformat(due) < datetime.date.today()
    except (ValueError, TypeError):
        return False


def collect(rm: RedmineAPI, pid: int, closed_names: set, period_days: int = 30) -> dict | None:
    try:
        proj = rm.project(pid)
    except Exception as e:
        log.warning("Proyecto %s: %s", pid, e)
        return None

    members = []
    for m in rm.memberships(pid):
        user = m.get("user", {})
        members.append({
            "id": user.get("id"),
            "name": user.get("name", f"User {user.get('id')}"),
            "roles": [r.get("name", "") for r in m.get("roles", [])],
        })

    try:
        issues = rm.issues(pid)
    except Exception:
        log.warning("Issues no disponibles para el proyecto %s", pid)
        issues = []

    status_counts = Counter(field_name(i, "status") for i in issues)
    for member in members:
        mine = [i for i in issues if (i.get("assigned_to") or {}).get("id") == member["id"]]
        open_t = sum(1 for i in mine if field_name(i, "status").lower() not in closed_names)
        member.update(
            total=len(mine), open=open_t,
            closed=len(mine) - open_t,
            overdue=sum(1 for i in mine if is_overdue(i, closed_names)),
        )

    total = len(issues)
    total_open = sum(1 for i in issues if field_name(i, "status").lower() not in closed_names)
    total_overdue = sum(1 for i in issues if is_overdue(i, closed_names))
    return {
        "id": pid,
        "name": proj.get("name", f"Proyecto {pid}"),
        "description": (proj.get("description") or "").strip(),
        "members": members,
        "status_counts": status_counts,
        "total": total,
        "open": total_open,
        "closed": total - total_open,
        "overdue": total_overdue,
        "health": (total - total_open) / total * 100 if total else 0.0,
        "analytics": analyze_trends(issues, members, closed_names, period_days),
    }


def summary_table(projects: list[dict]) -> tuple[list[str], list[list]]:
    """Tabla del resumen ejecutivo — compartida entre PDF y exports (Fase 3)."""
    headers = ["Proyecto", "Tareas", "Abiertas", "Cerradas", "Vencidas", "Avance %"]
    data = [[p["name"][:38], p["total"], p["open"], p["closed"], p["overdue"],
             f"{p['health']:.1f}"] for p in projects]
    return headers, data


def build_pdf(projects: list[dict], cfg: dict, out_path: Path,
              deltas: list[str] | None = None) -> None:
    from gespro.detailed_pdf import build_detailed_pdf

    build_detailed_pdf(projects, cfg, out_path, deltas)


def main() -> int:
    cfg = load_config()
    g = cfg.get("gespro", {})
    if not g.get("enabled"):
        log.info("GESPRO deshabilitado en config.yaml"); return 0

    api_key = require_env(g.get("api_key_env", "REDMINE_API_KEY"), "API key de Redmine/GESPRO")
    cache = ApiCache.from_config(cfg)
    rm = RedmineAPI(g["base_url"], api_key, verify_ssl=g.get("verify_ssl", False),
                    timeout=float(g.get("timeout_seconds", 30)), cache=cache)

    ids = g.get("project_ids") or []
    if not ids:
        log.info("Sin project_ids configurados: se tomarán todos los proyectos visibles.")
        ids = [p["id"] for p in rm.projects()]

    log.info("Recolectando %d proyectos desde %s ...", len(ids), g["base_url"])
    closed = set(g["closed_status_names"])
    days = int(g.get("previous_period_days", 30))
    workers = int(cfg.get("execution", {}).get("max_workers", 4))
    if workers > 1 and len(ids) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as pool:
            collected = list(pool.map(lambda pid: collect(rm, pid, closed, days), ids))
    else:
        collected = [collect(rm, pid, closed, days) for pid in ids]
    cache.close()
    projects = [d for d in collected if d]

    plugins = load_plugins(cfg)
    for result in run_hook(plugins, "post_collect", "gespro", projects, cfg):
        if result is not None:
            projects = result
    if not projects:
        log.error("No se recolectó ningún proyecto.")
        return 1

    out_dir = cfg["output"]["dir"]
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    prefix = g.get("filename_prefix", "informe_gespro")
    out_path = out_dir / f"{prefix}_{stamp}.pdf"

    from common import snapshots
    prev = snapshots.load(out_dir, prefix)
    current = {p["name"]: {"open": p["open"], "closed": p["closed"],
                           "overdue": p["overdue"], "health": round(p["health"], 1)}
               for p in projects}
    deltas = snapshots.diff(prev, current, {
        "open": "abiertas", "closed": "cerradas",
        "overdue": "vencidas", "health": "salud %",
    })
    snapshots.save(out_dir, prefix, current)

    build_pdf(projects, cfg, out_path, deltas)
    log.info("PDF generado: %s", out_path)

    headers, data = summary_table(projects)
    created = export_rows(headers, data, out_path,
                          cfg.get("export", {}).get("formats", ["pdf"]))
    run_hook(plugins, "post_export", "gespro", [out_path, *created], cfg)
    exts = tuple(f".{f}" for f in cfg.get("export", {}).get("formats", ["pdf"]))
    rotate_outputs(out_dir, prefix, cfg["output"].get("keep_last", 10), exts=exts)

    results = deliver(out_path, cfg, "Informe de Estado de Proyectos (GESPRO/Redmine)",
                      report_key="gespro")
    return delivery_exit_code(results)


if __name__ == "__main__":
    raise SystemExit(main())
