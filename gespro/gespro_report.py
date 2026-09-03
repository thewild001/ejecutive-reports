#!/usr/bin/env python3
"""
GESPRO/Redmine — Informe ejecutivo de estado de proyectos.
Genérico: cualquier instancia Redmine/GESPRO vía config.yaml + REDMINE_API_KEY.

Salida: PDF con indicadores consolidados, salud por proyecto, carga por miembro,
tareas atrasadas y recomendaciones accionables.
"""
from __future__ import annotations

import datetime
import sys
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.settings import load_config, require_env
from common.pdfbase import ReportPDF
from common.delivery import deliver
from common.settings import rotate_outputs


class RedmineAPI:
    def __init__(self, base_url: str, api_key: str, verify_ssl: bool = False):
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"), verify=verify_ssl, timeout=30.0,
            headers={"X-Redmine-API-Key": api_key, "Content-Type": "application/json"},
        )

    def _get(self, path, params=None):
        resp = self.client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

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
        except httpx.HTTPStatusError:
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


def collect(rm: RedmineAPI, pid: int, closed_names: set) -> dict | None:
    try:
        proj = rm.project(pid)
    except Exception as e:
        print(f"  [WARN] Proyecto {pid}: {e}")
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
    }


def build_pdf(projects: list[dict], cfg: dict, out_path: Path) -> None:
    pdf = ReportPDF(cfg["company"], "Informe de Estado de Proyectos")
    pdf.cover("Seguimiento y salud del portafolio de proyectos")

    # Resumen ejecutivo
    pdf.add_page()
    pdf.section("1. Resumen ejecutivo")
    total = sum(p["total"] for p in projects)
    opened = sum(p["open"] for p in projects)
    overdue = sum(p["overdue"] for p in projects)
    members = len({m["id"] for p in projects for m in p["members"]})
    pct = round(opened / total * 100, 1) if total else 0
    pdf.para(
        f"Se analizaron {len(projects)} proyectos con un total de {total} tareas registradas: "
        f"{opened} abiertas ({pct}%) y {overdue} vencidas. "
        f"Participan {members} miembros asignados en los proyectos."
    )
    pdf.table(
        ["Proyecto", "Tareas", "Abiertas", "Cerradas", "Vencidas", "Avance %"],
        [[p["name"][:38], p["total"], p["open"], p["closed"], p["overdue"], f"{p['health']:.1f}"] for p in projects],
        widths=[64, 22, 22, 22, 25, 25],
    )

    # Detalle por proyecto
    for idx, p in enumerate(projects, start=1):
        pdf.add_page()
        pdf.section(f"Proyecto {idx}: {p['name']}")
        if p["description"]:
            pdf.para(p["description"][:600], size=9)
        pdf.kv_row("Tareas totales / abiertas / cerradas", f"{p['total']} / {p['open']} / {p['closed']}")
        pdf.kv_row("Tareas vencidas", str(p["overdue"]))
        pdf.kv_row("Tasa de cierre (salud)", f"{p['health']:.1f}%")
        if p["status_counts"]:
            pdf.ln(2)
            pdf.para("Distribución por estado: " + ", ".join(f"{k}: {v}" for k, v in p["status_counts"].most_common()), size=9)
        if p["members"]:
            pdf.ln(2)
            pdf.section("Carga de trabajo por miembro")
            pdf.table(
                ["Miembro", "Rol(es)", "Total", "Abiertas", "Vencidas"],
                [[m["name"][:32], ", ".join(m["roles"])[:30], m["total"], m["open"], m["overdue"]] for m in p["members"]],
                widths=[55, 55, 22, 24, 24],
            )

        # Análisis automático
        pdf.section("Análisis y recomendaciones")
        if p["health"] >= 70 and p["overdue"] == 0:
            pdf.bullet("Salud del proyecto satisfactoria. Mantener la cadencia de cierre actual.")
        if p["overdue"] > 0:
            pdf.bullet(f"Atender las {p['overdue']} tareas vencidas: replanificar o reasignar antes de la próxima revisión.")
        if p["open"] > p["closed"] and p["total"] > 10:
            pdf.bullet("Las tareas abiertas superan a las cerradas: revisar capacidad del equipo y prioridades del sprint.")
        idle = [m for m in p["members"] if m["total"] == 0]
        if idle:
            pdf.bullet(f"Sin tareas asignadas: {', '.join(m['name'] for m in idle)}. Valorar redistribución de carga.")
        overloaded = sorted((m for m in p["members"] if m["open"] > 0), key=lambda m: -m["open"])[:1]
        if overloaded and overloaded[0]["open"] >= 5:
            pdf.bullet(f"Mayor carga abierta: {overloaded[0]['name']} ({overloaded[0]['open']}). Considerar apoyo o delegación.")

    pdf.output(str(out_path))


def main() -> int:
    cfg = load_config()
    g = cfg.get("gespro", {})
    if not g.get("enabled"):
        print("GESPRO deshabilitado en config.yaml"); return 0

    api_key = require_env(g.get("api_key_env", "REDMINE_API_KEY"), "API key de Redmine/GESPRO")
    rm = RedmineAPI(g["base_url"], api_key, verify_ssl=g.get("verify_ssl", False))

    ids = g.get("project_ids") or []
    if not ids:
        print("Sin project_ids configurados: se tomarán todos los proyectos visibles.")
        ids = [p["id"] for p in rm.projects()]

    print(f"Recolectando {len(ids)} proyectos desde {g['base_url']} ...")
    projects = [d for pid in ids if (d := collect(rm, pid, set(g["closed_status_names"])))]
    if not projects:
        print("ERROR: no se recolectó ningún proyecto."); return 1

    out_dir = cfg["output"]["dir"]
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    prefix = g.get("filename_prefix", "informe_gespro")
    out_path = out_dir / f"{prefix}_{stamp}.pdf"
    build_pdf(projects, cfg, out_path)
    rotate_outputs(out_dir, prefix, cfg["output"].get("keep_last", 10))
    print(f"PDF generado: {out_path}")

    deliver(out_path, cfg, "Informe de Estado de Proyectos (GESPRO/Redmine)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
