"""Resumen ejecutivo de salud GitLab para la suite REPORTS.

Reimplementa el formato del script aislado sobre los datos normalizados por
`gitlab.gitlab_report.collect_project_data`, sin Docker/MCP ni rutas locales.
"""
from __future__ import annotations

import datetime
from collections import defaultdict
from pathlib import Path

from fpdf.enums import XPos, YPos

from common.pdfbase import ReportPDF
from common.themes import get_theme


def health_score(row: dict) -> int:
    """Puntaje 0-100 derivado de métricas ya recolectadas por GitLab REST."""
    score = 100.0

    pipe_rate = row.get("pipe_rate")
    if pipe_rate is None:
        score -= 8
    else:
        score -= max(0.0, 100.0 - float(pipe_rate)) * 0.35

    branches = int(row.get("branches", 0))
    stale = int(row.get("stale", 0))
    if branches:
        score -= (stale / branches) * 30.0

    issues = row.get("open_issues")
    if isinstance(issues, int):
        score -= min(15.0, issues * 0.5)

    last_activity = (row.get("last_activity") or "")[:10]
    if last_activity:
        try:
            activity = datetime.date.fromisoformat(last_activity)
            age = (datetime.date.today() - activity).days
            if age > 60:
                score -= min(20.0, (age - 60) * 0.08)
        except (TypeError, ValueError):
            score -= 5

    mrs = (row.get("metrics") or {}).get("mrs") or {}
    mrs_open = int(mrs.get("mr_open") or 0)
    score -= min(10.0, mrs_open * 1.5)

    return max(0, min(100, round(score)))


def health_label(score: int) -> str:
    if score >= 75:
        return "BUENA"
    if score >= 60:
        return "REGULAR"
    return "CRÍTICA"


def health_color(score: int) -> tuple[int, int, int]:
    if score >= 75:
        return (40, 167, 69)
    if score >= 60:
        return (200, 160, 30)
    return (220, 53, 69)


def group_rows(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        path = str(row.get("path") or row.get("name") or "Sin grupo")
        group = path.split("/", 1)[0] if "/" in path else "Sin grupo"
        grouped[group].append(row)
    return dict(sorted(grouped.items()))


class ExecutiveGitLabPDF(ReportPDF):
    """Presentación ejecutiva con tarjetas de salud y análisis del grupo."""

    def badge(self, row: dict) -> int:
        score = health_score(row)
        label = health_label(score)
        badge = f"  {label} ({score}/100)  "
        self.set_fill_color(*health_color(score))
        self.set_text_color(*self._theme["white"])
        self.set_font(self._font, "B", 9)
        self.cell(self.get_string_width(badge) + 4, 7, badge, fill=True, align="C")
        return score

    def project_card(self, row: dict) -> None:
        self.set_font(self._font, "", 10)
        self.badge(row)
        self.cell(0, 7, f"  {row.get('name', 'Proyecto')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pipes = "N/A" if row.get("pipe_rate") is None else f"{row['pipe_rate']}%"
        issues = "N/A" if row.get("open_issues") is None else str(row["open_issues"])
        mrs = (row.get("metrics") or {}).get("mrs") or {}
        mrs_text = "N/A"
        if mrs:
            mrs_text = f"{mrs.get('mr_open', 0)} abiertos / {mrs.get('mr_merged', 0)} mergeados"
        self.kv_row("Pipelines / Ramas", f"{pipes} / {row.get('branches', 0)} ({row.get('stale', 0)} stale)")
        self.kv_row("Issues / MRs", f"{issues} / {mrs_text}")
        self.kv_row("Última actividad", row.get("last_activity") or "No disponible")
        self.ln(2)

    def recommendation(self, title: str, text: str) -> None:
        self.bullet(f"{title}: {text}")


def _portfolio_stats(rows: list[dict]) -> dict:
    scores = [health_score(row) for row in rows]
    active_cutoff = datetime.date.today() - datetime.timedelta(days=60)
    active = 0
    for row in rows:
        try:
            last = datetime.date.fromisoformat((row.get("last_activity") or "")[:10])
            active += int(last >= active_cutoff)
        except (TypeError, ValueError):
            pass
    with_pipes = [r for r in rows if r.get("pipe_rate") is not None]
    good_pipes = [r for r in with_pipes if r["pipe_rate"] >= 90]
    return {
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "critical": [r for r in rows if health_score(r) < 60],
        "stale": sum(int(r.get("stale", 0)) for r in rows),
        "issues": sum(int(r["open_issues"]) for r in rows if isinstance(r.get("open_issues"), int)),
        "active": active,
        "good_pipes": len(good_pipes),
        "with_pipes": len(with_pipes),
    }


def _render_group_summary(pdf: ExecutiveGitLabPDF, rows: list[dict], cfg: dict,
                          deltas: list[str] | None) -> dict:
    stats = _portfolio_stats(rows)
    group = cfg.get("gitlab", {}).get("group") or "proyectos visibles"

    pdf.add_page()
    pdf.section("1. Resumen General del Grupo")
    pdf.para(
        f"El grupo {group} concentra {len(rows)} proyectos con actividad analizable. "
        "Se consolidan indicadores de pipelines, ramas, issues, merge requests y actividad como medida de salud."
    )
    pdf.kv_row("Total de proyectos", str(len(rows)))
    pdf.kv_row("Salud promedio", f"{stats['avg_score']}/100 ({health_label(round(stats['avg_score']))})")
    pdf.kv_row("Proyectos activos", f"{stats['active']} / {len(rows)}")
    pdf.kv_row("Ramas stale", str(stats["stale"]))
    pdf.kv_row("Issues abiertos", str(stats["issues"]))
    pdf.kv_row("Pipelines con ≥90% éxito", f"{stats['good_pipes']} / {stats['with_pipes']}")

    if deltas:
        pdf.section("Cambios vs ejecución anterior")
        for delta in deltas:
            pdf.bullet(delta)

    return stats


def _render_groups(pdf: ExecutiveGitLabPDF, rows: list[dict]) -> None:
    pdf.section("2. Proyectos por Estado de Salud")
    grouped = group_rows(rows)
    for group, group_rows_ in grouped.items():
        pdf.set_font(pdf._font, "B", 11)
        pdf.set_text_color(*pdf._theme["accent"])
        pdf.cell(0, 7, f"Subgrupo: {group}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1)
        for row in sorted(group_rows_, key=lambda item: health_score(item)):
            pdf.project_card(row)


def _analysis(rows: list[dict]) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    strengths: list[str] = []
    weaknesses: list[str] = []
    recommendations: list[tuple[str, str]] = []
    stats = _portfolio_stats(rows)

    if stats["active"]:
        strengths.append(f"{stats['active']} proyectos con actividad reciente en los últimos 60 días.")
    if stats["good_pipes"]:
        strengths.append(f"{stats['good_pipes']} proyectos mantienen pipelines con al menos 90% de éxito.")
    if stats["stale"]:
        weaknesses.append(f"Hay {stats['stale']} ramas stale acumuladas, concentrando deuda técnica.")
        recommendations.append(("Auditar ramas stale", "Definir una política de limpieza y revisar proyectos con mayor concentración."))
    if stats["issues"]:
        weaknesses.append(f"El portafolio acumula {stats['issues']} issues abiertos.")
        recommendations.append(("Revisión periódica de issues", "Aplicar triage semanal y cerrar elementos obsoletos."))
    if stats["critical"]:
        names = ", ".join(row.get("name", "?") for row in stats["critical"][:5])
        weaknesses.append(f"{len(stats['critical'])} proyecto(s) con salud crítica: {names}.")
        recommendations.append(("Intervenir proyectos críticos", "Priorizar proyectos con actividad detenida, pipelines rotos o alta proporción stale."))
    if not strengths:
        strengths.append("El grupo aún no muestra indicadores suficientes para resaltar fortalezas.")
    if not weaknesses:
        weaknesses.append("No se identifican riesgos críticos con las métricas disponibles.")
    if not recommendations:
        recommendations.append(("Mantener el ritmo", "Conservar las prácticas actuales y repetir el monitoreo en el próximo período."))
    return strengths, weaknesses, recommendations


def _render_analysis(pdf: ExecutiveGitLabPDF, rows: list[dict]) -> None:
    strengths, weaknesses, recommendations = _analysis(rows)
    pdf.section("3. Análisis y Recomendaciones")

    pdf.set_font(pdf._font, "B", 11)
    pdf.set_text_color(40, 120, 40)
    pdf.cell(0, 7, "Fortalezas", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for item in strengths:
        pdf.bullet(item)

    pdf.set_font(pdf._font, "B", 11)
    pdf.set_text_color(180, 30, 30)
    pdf.cell(0, 7, "Debilidades y Riesgos", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for item in weaknesses:
        pdf.bullet(item)

    pdf.set_font(pdf._font, "B", 11)
    pdf.set_text_color(*pdf._theme["accent"])
    pdf.cell(0, 7, "Recomendaciones Estratégicas", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for title, text in recommendations:
        pdf.recommendation(title, text)


def _render_detail(pdf: ExecutiveGitLabPDF, rows: list[dict]) -> None:
    pdf.section("4. Detalle por Proyecto")
    for row in rows:
        pdf.section(row.get("name", "Proyecto"))
        pdf.kv_row("Ruta", row.get("path", ""))
        pdf.kv_row("Última actividad", row.get("last_activity") or "Sin datos")
        pdf.kv_row("Ramas (stale)", f"{row.get('branches', 0)} ({row.get('stale', 0)})")
        pdf.kv_row("Issues abiertos", str(row.get("open_issues")) if row.get("open_issues") is not None else "No disponible")
        pdf.kv_row("Éxito pipelines", f"{row['pipe_rate']}%" if row.get("pipe_rate") is not None else "No disponible")
        metrics = row.get("metrics") or {}
        mrs = metrics.get("mrs")
        if mrs:
            pdf.kv_row("MRs abiertos / mergeados", f"{mrs.get('mr_open', 0)} / {mrs.get('mr_merged', 0)}")
            if mrs.get("mr_merge_rate") is not None:
                pdf.kv_row("Tasa de merge", f"{mrs['mr_merge_rate']}%")
            if mrs.get("mr_avg_review_days") is not None:
                pdf.kv_row("Revisión media", f"{mrs['mr_avg_review_days']} días")
        activity = metrics.get("activity")
        if activity:
            pdf.kv_row("Commits (ventana)", str(activity.get("commits", 0)))
            if activity.get("active_contributors"):
                pdf.kv_row("Contribuidores activos", ", ".join(activity["active_contributors"]))
            if activity.get("inactive_contributors"):
                pdf.kv_row("Sin actividad reciente", ", ".join(activity["inactive_contributors"]))
        if metrics.get("topics"):
            pdf.kv_row("Topics", ", ".join(metrics["topics"]))
        if row.get("web_url"):
            pdf.para(row["web_url"], size=8)


def build_executive_pdf(rows: list[dict], cfg: dict, out_path: Path,
                        deltas: list[str] | None = None) -> None:
    pdf = ExecutiveGitLabPDF(
        cfg["company"],
        "Informe de Salud de Repositorios GitLab",
        theme=get_theme(cfg.get("ui", {}).get("theme")),
    )
    pdf.cover("Actividad, ramas, issues, pipelines y merge requests del grupo")
    stats = _render_group_summary(pdf, rows, cfg, deltas)
    _render_groups(pdf, rows)
    _render_analysis(pdf, rows)
    _render_detail(pdf, rows)

    pdf.add_page()
    pdf.section("5. Conclusión")
    pdf.para(
        f"El grupo presenta una salud promedio de {stats['avg_score']}/100. "
        "Las acciones prioritarias se centran en limpieza de ramas, recuperación de pipelines y gestión activa de issues."
    )
    pdf.output(str(out_path))
