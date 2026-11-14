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
from common.delivery import deliver, delivery_exit_code
from common.exporters import export_rows
from common.http_client import build_client, checked_json
from common.plugins import load_plugins, run_hook

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


def portfolio_projects(api: GitLabAPI | None, g: dict) -> dict[str, str]:
    """{nombre_visible: ruta_completa} desde `gitlab.projects` o descubiertos por la API."""
    explicit = g.get("projects") or []
    if isinstance(explicit, dict):
        return {str(k): str(v) for k, v in explicit.items()}
    if explicit:
        return {str(path).rstrip("/").split("/")[-1]: str(path) for path in explicit}
    found = api.projects(g.get("group") or None, int(g.get("max_projects", 25)))
    names: dict[str, str] = {}
    for p in found:
        path = p.get("path_with_namespace", "")
        if not path:
            continue
        key = p.get("path") or path.split("/")[-1]
        names[key if key not in names else path] = path  # colisión → ruta completa
    return names


def main_portfolio(cfg: dict, g: dict) -> int:
    """Resumen ejecutivo consolidado (formato heredado) vía servidor MCP."""
    from gitlab import portfolio_report as pr

    api = None
    if not g.get("projects"):
        token = require_env(g.get("token_env", "GITLAB_TOKEN"), "token de GitLab")
        api = GitLabAPI(g["base_url"], token, verify_ssl=g.get("verify_ssl", False),
                        timeout=float(g.get("timeout_seconds", 30)))
    projects = portfolio_projects(api, g)
    if not projects:
        log.error("No hay proyectos que analizar (gitlab.projects vacío y la API no devolvió ninguno)")
        return pr.EXIT_NO_DATA

    pr.configure(cfg)
    log.info("Consultando %d proyectos vía MCP (ventana %d días) ...", len(projects),
             pr.S.window_days)
    portfolio, group = pr.collect(projects)
    plugins = load_plugins(cfg)
    for result in run_hook(plugins, "post_collect", "gitlab", portfolio, cfg):
        if result is not None:
            portfolio = result
    if not portfolio:
        log.error("El MCP no devolvió datos de ningún proyecto: no se genera ni envía el informe")
        return pr.EXIT_NO_DATA

    out_dir = cfg["output"]["dir"]
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    prefix = g.get("filename_prefix", "informe_gitlab")
    out_path = out_dir / f"{prefix}_{stamp}.pdf"
    from common import snapshots
    current = pr.snapshot_of(portfolio)
    deltas = snapshots.diff(snapshots.load(out_dir, prefix), current, pr.SNAPSHOT_LABELS)
    snapshots.save(out_dir, prefix, current)

    from common import dashboard_data
    totals = pr.portfolio_totals(portfolio)
    alerts = totals.pop("alerts")
    dashboard_data.save_dataset(
        out_dir, "gitlab", {**totals, "pipelines_ok": pr.avg_pipelines_ok(portfolio)},
        pr.dashboard_projects(portfolio),
        {"alerts": alerts[:30], "contributors": pr.consolidated_contributors(portfolio)[:10],
         "window_days": pr.S.window_days, "host": pr.S.host})

    pages = pr.build_portfolio_pdf(portfolio, group, out_path, deltas)
    log.info("PDF generado: %s (%d páginas, %d/%d proyectos)", out_path, pages,
             len(portfolio), len(projects))

    headers, data = pr.summary_rows(portfolio)
    created = export_rows(headers, data, out_path,
                          cfg.get("export", {}).get("formats", ["pdf"]))
    run_hook(plugins, "post_export", "gitlab", [out_path, *created], cfg)
    exts = tuple(f".{f}" for f in cfg.get("export", {}).get("formats", ["pdf"]))
    rotate_outputs(out_dir, prefix, cfg["output"].get("keep_last", 10), exts=exts)

    results = deliver(out_path, cfg, "Resumen Ejecutivo de Proyectos GitLab",
                      report_key="gitlab")
    return delivery_exit_code(results)


def main() -> int:
    cfg = load_config()
    g = cfg.get("gitlab", {})
    if not g.get("enabled"):
        log.info("GitLab deshabilitado en config.yaml"); return 0
    return main_portfolio(cfg, g)


if __name__ == "__main__":
    raise SystemExit(main())
