#!/usr/bin/env python3
"""
GitLab — Informe ejecutivo de salud del repositorio.
Genérico: cualquier instancia GitLab vía config.yaml + GITLAB_TOKEN (scope read_api).

Métricas por proyecto: última actividad, ramas totales/stale, issues abiertos,
tasa de éxito de pipelines (opcional). Incluye resumen ejecutivo y recomendaciones.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.settings import load_config, require_env, rotate_outputs
from common.pdfbase import ReportPDF
from common.delivery import deliver


class GitLabAPI:
    def __init__(self, base_url: str, token: str, verify_ssl: bool = False):
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v4",
            verify=verify_ssl, timeout=30.0,
            headers={"PRIVATE-TOKEN": token},
        )

    def _get(self, path, params=None):
        resp = self.client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

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
        except httpx.HTTPStatusError:
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
        pass
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
    }


def build_pdf(rows: list[dict], cfg: dict, out_path: Path) -> None:
    pdf = ReportPDF(cfg["company"], "Informe de Salud de Repositorios GitLab")
    pdf.cover("Actividad, ramas, issues y pipelines del grupo")

    pdf.add_page()
    pdf.section("1. Resumen ejecutivo")
    total_stale = sum(r["stale"] for r in rows)
    total_branches = sum(r["branches"] for r in rows)
    total_open = sum(r["open_issues"] for r in rows if isinstance(r["open_issues"], int))
    with_pipes = [r for r in rows if r["pipe_rate"] is not None]
    avg_pipe = round(sum(r["pipe_rate"] for r in with_pipes) / len(with_pipes), 1) if with_pipes else None
    pdf.para(
        f"Se analizaron {len(rows)} proyectos: {total_branches} ramas totales, de las cuales "
        f"{total_stale} están sin actividad por encima del umbral configurado (stale). "
        f"Issues abiertos acumulados: {total_open}."
        + (f" Tasa media de éxito de pipelines: {avg_pipe}%." if avg_pipe is not None else "")
    )

    pdf.table(
        ["Proyecto", "Últ. actividad", "Ramas", "Stale", "Issues", "Pipeline %"],
        [[
            r["name"][:34], r["last_activity"], r["branches"], r["stale"],
            r["open_issues"] if r["open_issues"] is not None else "-",
            f"{r['pipe_rate']}" if r["pipe_rate"] is not None else "-",
        ] for r in rows],
        widths=[60, 26, 20, 20, 24, 30],
    )

    pdf.section("2. Alertas y recomendaciones")
    worst_stale = sorted(rows, key=lambda r: -r["stale"])[:3]
    for r in worst_stale:
        if r["stale"] > 0:
            pdf.bullet(f"{r['name']}: {r['stale']} ramas sin actividad — valorar limpieza (deuda técnica / código abandonado).")
    low_pipes = [r for r in rows if r["pipe_rate"] is not None and r["pipe_rate"] < 70]
    for r in low_pipes:
        pdf.bullet(f"{r['name']}: pipelines con {r['pipe_rate']}% de éxito — revisar fallos recurrentes de CI/CD.")
    inactive = [r for r in rows if r["last_activity"] and
                (datetime.date.today() - datetime.date.fromisoformat(r["last_activity"])).days > 60]
    for r in inactive:
        pdf.bullet(f"{r['name']}: sin actividad desde {r['last_activity']} — confirmar si el proyecto sigue vivo o archivarlo.")
    if not (worst_stale[0]["stale"] if worst_stale else 0) and not low_pipes and not inactive:
        pdf.para("Sin alertas: todos los proyectos presentan actividad reciente, ramas saludables y pipelines estables.")

    pdf.section("3. Detalle por proyecto")
    for r in rows:
        pdf.section(r["name"])
        pdf.kv_row("Ruta", r["path"])
        pdf.kv_row("Última actividad", r["last_activity"] or "Sin datos")
        pdf.kv_row("Ramas (stale)", f"{r['branches']} ({r['stale']})")
        pdf.kv_row("Issues abiertos", str(r["open_issues"]) if r["open_issues"] is not None else "No disponible")
        pdf.kv_row("Éxito pipelines", f"{r['pipe_rate']}%" if r["pipe_rate"] is not None else "No disponible")
        if r["web_url"]:
            pdf.para(r["web_url"], size=8)

    pdf.output(str(out_path))


def main() -> int:
    cfg = load_config()
    g = cfg.get("gitlab", {})
    if not g.get("enabled"):
        print("GitLab deshabilitado en config.yaml"); return 0

    token = require_env(g.get("token_env", "GITLAB_TOKEN"), "token de GitLab")
    api = GitLabAPI(g["base_url"], token, verify_ssl=g.get("verify_ssl", False))

    projects = api.projects(g.get("group") or None, int(g.get("max_projects", 25)))
    print(f"Analizando {len(projects)} proyectos de {g['base_url']} ...")
    rows = [analyze_project(api, p, cfg) for p in projects]

    out_dir = cfg["output"]["dir"]
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    prefix = g.get("filename_prefix", "informe_gitlab")
    out_path = out_dir / f"{prefix}_{stamp}.pdf"
    build_pdf(rows, cfg, out_path)
    rotate_outputs(out_dir, prefix, cfg["output"].get("keep_last", 10))
    print(f"PDF generado: {out_path}")

    deliver(out_path, cfg, "Informe de Salud de Repositorios GitLab")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
