#!/usr/bin/env python3
"""
GitLab — Informe ejecutivo de salud del repositorio.
Genérico: cualquier instancia GitLab vía config.yaml + GITLAB_TOKEN (scope read_api).

Métricas por proyecto: última actividad, ramas totales/stale, issues abiertos,
tasa de éxito de pipelines (opcional). Incluye resumen ejecutivo y recomendaciones.
"""
from __future__ import annotations

import datetime
import logging
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.settings import load_config, require_env, rotate_outputs
from common.delivery import deliver
from common.cache import ApiCache
from common.exporters import export_rows
from common.http_client import ApiError, build_client, checked_json
from common.plugins import load_plugins, run_hook
from gitlab.metrics import collect_metrics

log = logging.getLogger(__name__)


class GitLabAPI:
    def __init__(self, base_url: str, token: str, verify_ssl: bool = False,
                 timeout: float = 30.0, cache=None):
        self.cache = cache
        self.client = build_client(
            base_url.rstrip("/") + "/api/v4",
            headers={"PRIVATE-TOKEN": token},
            verify_ssl=verify_ssl,
            timeout=timeout,
        )

    def _get(self, path, params=None):
        return checked_json(self.client, path, params, cache=self.cache)

    def paginate(self, path, params=None, per_page=100):
        params = dict(params or {}, per_page=per_page)
        records, page = [], 1
        while True:
            params["page"] = page
            data = self._get(path, params)
            records.extend(data)
            if len(data) < per_page:
                break
            page += 1
        return records

    def projects(self, group: str | None, max_projects: int):
        params = {"order_by": "last_activity_at", "sort": "desc", "statistics": False}
        if group:
            data = self.paginate(f"/groups/{httpx.URL(group).raw_path.decode().strip('/')}/projects", {**params, "include_subgroups": True})
        else:
            data = self.paginate("/projects", {**params, "membership": True})
        return data[:max_projects]

    def branches(self, pid):
        return self.paginate(f"/projects/{pid}/repository/branches")

    def open_issues(self, pid) -> int:
        data = self._get(f"/projects/{pid}/issues_statistics")
        return (data.get("statistics") or {}).get("counts", {}).get("opened", 0)

    def pipelines(self, pid, limit=20):
        try:
            return self._get(f"/projects/{pid}/pipelines", {"per_page": limit})
        except ApiError:
            log.warning("Pipelines no disponibles para el proyecto %s", pid)
            return []


def analyze_project(api: GitLabAPI, p: dict, cfg: dict) -> dict:
    pid = p["id"]
    stale_days = cfg["gitlab"].get("stale_branch_days", 60)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=stale_days)

    last_activity = p.get("last_activity_at", "")
    branches = []
    try:
        branches = api.branches(pid)
    except Exception:
        log.warning("Ramas no disponibles para el proyecto %s", pid)
    stale = 0
    for b in branches:
        committed = (b.get("commit") or {}).get("committed_date")
        if committed:
            dt = datetime.datetime.fromisoformat(committed.replace("Z", "+00:00"))
            if dt < cutoff:
                stale += 1

    try:
        open_issues = api.open_issues(pid)
    except Exception:
        log.warning("Issues no disponibles para el proyecto %s", pid)
        open_issues = None

    pipelines = api.pipelines(pid) if cfg["gitlab"].get("include_pipelines") else []
    if pipelines:
        success = sum(1 for pl in pipelines if pl.get("status") == "success")
        pipe_rate = round(success / len(pipelines) * 100, 1)
    else:
        pipe_rate = None

    return {
        "name": p.get("name", "?"),
        "path": p.get("path_with_namespace", ""),
        "last_activity": last_activity[:10],
        "branches": len(branches),
        "stale": stale,
        "open_issues": open_issues,
        "pipe_rate": pipe_rate,
        "web_url": p.get("web_url", ""),
        "metrics": collect_metrics(api, p, cfg),
    }


def summary_table(rows: list[dict]) -> tuple[list[str], list[list]]:
    """Tabla del resumen ejecutivo — compartida entre PDF y exports (Fase 3)."""
    headers = ["Proyecto", "Últ. actividad", "Ramas", "Stale", "Issues", "Pipeline %"]
    data = [[
        r["name"][:34], r["last_activity"], r["branches"], r["stale"],
        r["open_issues"] if r["open_issues"] is not None else "-",
        f"{r['pipe_rate']}" if r["pipe_rate"] is not None else "-",
    ] for r in rows]
    return headers, data


def build_pdf(rows: list[dict], cfg: dict, out_path: Path,
              deltas: list[str] | None = None) -> None:
    from gitlab.executive_pdf import build_executive_pdf

    build_executive_pdf(rows, cfg, out_path, deltas)


def main() -> int:
    cfg = load_config()
    g = cfg.get("gitlab", {})
    if not g.get("enabled"):
        log.info("GitLab deshabilitado en config.yaml"); return 0

    token = require_env(g.get("token_env", "GITLAB_TOKEN"), "token de GitLab")
    cache = ApiCache.from_config(cfg)
    api = GitLabAPI(g["base_url"], token, verify_ssl=g.get("verify_ssl", False),
                    timeout=float(g.get("timeout_seconds", 30)), cache=cache)

    projects = api.projects(g.get("group") or None, int(g.get("max_projects", 25)))
    log.info("Analizando %d proyectos de %s ...", len(projects), g["base_url"])

    workers = int(cfg.get("execution", {}).get("max_workers", 4))
    if workers > 1 and len(projects) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(lambda p: analyze_project(api, p, cfg), projects))
    else:
        rows = [analyze_project(api, p, cfg) for p in projects]
    cache.close()

    plugins = load_plugins(cfg)
    for result in run_hook(plugins, "post_collect", "gitlab", rows, cfg):
        if result is not None:
            rows = result

    out_dir = cfg["output"]["dir"]
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    prefix = g.get("filename_prefix", "informe_gitlab")
    out_path = out_dir / f"{prefix}_{stamp}.pdf"

    from common import snapshots
    prev = snapshots.load(out_dir, prefix)
    current = {
        r["name"]: {k: r[k] for k in ("branches", "stale", "open_issues")
                    if r[k] is not None}
        | ({"mr_open": r["metrics"]["mrs"]["mr_open"]}
           if r["metrics"].get("mrs") else {})
        for r in rows
    }
    deltas = snapshots.diff(prev, current, {
        "branches": "ramas", "stale": "stale",
        "open_issues": "issues abiertos", "mr_open": "MRs abiertos",
    })
    snapshots.save(out_dir, prefix, current)

    build_pdf(rows, cfg, out_path, deltas)
    log.info("PDF generado: %s", out_path)

    headers, data = summary_table(rows)
    created = export_rows(headers, data, out_path,
                          cfg.get("export", {}).get("formats", ["pdf"]))
    run_hook(plugins, "post_export", "gitlab", [out_path, *created], cfg)
    exts = tuple(f".{f}" for f in cfg.get("export", {}).get("formats", ["pdf"]))
    rotate_outputs(out_dir, prefix, cfg["output"].get("keep_last", 10), exts=exts)

    deliver(out_path, cfg, "Informe de Salud de Repositorios GitLab")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
