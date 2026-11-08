"""Render detallado del informe GESPRO/Redmine.

Mantiene el formato ejecutivo del script aislado, pero usa la configuración,
el sistema de temas y la recolección ya implementados por la suite.
"""
from __future__ import annotations

from pathlib import Path

from fpdf.enums import XPos, YPos

from common.pdfbase import ReportPDF
from common.themes import get_theme


def project_health(project: dict) -> tuple[str, tuple[int, int, int]]:
    pct = float(project.get("health", 0))
    if pct >= 80:
        return "BUENA", (40, 167, 69)
    if pct >= 50:
        return "REGULAR", (200, 160, 30)
    return "CRÍTICA", (220, 53, 69)


def analyze_strengths(project: dict) -> list[str]:
    strengths: list[str] = []
    health = float(project.get("health", 0))
    total = int(project.get("total", 0))
    members = project.get("members", [])

    if health >= 80:
        strengths.append(f"Alta tasa de cierre ({health:.0f}%), indicando buena gestión y cumplimiento de tareas.")
    elif health >= 60:
        strengths.append(f"Tasa de cierre aceptable ({health:.0f}%), con avance sostenido.")
    if total > 50:
        strengths.append(f"Alto volumen de tareas registradas ({total}), reflejando uso activo del sistema.")

    active = [m for m in members if int(m.get("total", 0)) > 0]
    if members and len(active) > len(members) * 0.7:
        strengths.append(f"Alta participación ({len(active)}/{len(members)} miembros con tareas).")

    top = [m for m in active
           if int(m.get("total", 0)) >= 3 and int(m.get("closed", 0)) / int(m.get("total", 0)) >= 0.7]
    if top:
        strengths.append(f"{len(top)} miembro(s) con alto desempeño (≥70% cierre).")

    overdue = sum(int(m.get("overdue", 0)) for m in members) or int(project.get("overdue", 0))
    if total > 0 and overdue == 0:
        strengths.append("No hay tareas vencidas, indica buena planificación.")
    if not strengths:
        strengths.append(f"Proyecto en fase de {'inicio' if total < 10 else 'desarrollo'} con {total} tareas.")
    return strengths


def analyze_weaknesses(project: dict) -> list[str]:
    weaknesses: list[str] = []
    health = float(project.get("health", 0))
    total = int(project.get("total", 0))
    opened = int(project.get("open", 0))
    closed = int(project.get("closed", 0))
    overdue = int(project.get("overdue", 0))
    members = project.get("members", [])

    if health < 40:
        weaknesses.append(f"Baja tasa de cierre ({health:.0f}%), solo {closed} de {total} completadas.")
    elif health < 60:
        weaknesses.append(f"Tasa de cierre baja ({health:.0f}%), con {opened} tareas abiertas.")
    if overdue > 5:
        weaknesses.append(f"{overdue} tareas vencidas sin cerrar, problemas de planificación o carga excesiva.")
    elif overdue > 0:
        weaknesses.append(f"{overdue} tarea(s) vencida(s), requieren atención inmediata.")

    unassigned = [m for m in members if int(m.get("total", 0)) == 0]
    if members and len(unassigned) > len(members) * 0.3:
        weaknesses.append(f"{len(unassigned)} miembros sin tareas ({len(unassigned)}/{len(members)}), posible subutilización.")
    if opened > 100:
        weaknesses.append(f"Alta acumulación de tareas abiertas ({opened}), posible falta de recursos.")

    critical = [m for m in members if int(m.get("overdue", 0)) >= 3]
    if critical:
        names = ", ".join(str(m.get("name", "")).split()[0] for m in critical[:3])
        weaknesses.append(f"{len(critical)} miembro(s) con 3+ tareas atrasadas ({names}{'...' if len(critical) > 3 else ''}).")
    if total == 0:
        weaknesses.append("Proyecto sin tareas registradas en GESPRO.")

    new_count = int(dict(project.get("status_counts", {})).get("Nueva", 0))
    if total and new_count / total > 0.4:
        weaknesses.append(f"{new_count} tareas en estado 'Nueva' ({new_count / total * 100:.0f}%), sin asignar.")
    return weaknesses


def analyze_suggestions(project: dict) -> list[tuple[str, str]]:
    suggestions: list[tuple[str, str]] = []
    health = float(project.get("health", 0))
    opened = int(project.get("open", 0))
    closed = int(project.get("closed", 0))
    total = int(project.get("total", 0))
    overdue = int(project.get("overdue", 0))
    members = project.get("members", [])

    if health < 50:
        suggestions.append(("Revisión urgente de backlog",
                            f"Convocar sesión para revisar {opened} tareas abiertas. Priorizar por impacto y redistribuir carga."))
    if overdue:
        suggestions.append(("Atención a tareas vencidas",
                            f"Identificar {overdue} tareas vencidas, validar fechas y establecer compromisos."))

    unassigned = [m for m in members if int(m.get("total", 0)) == 0]
    if len(unassigned) >= 3:
        suggestions.append(("Optimizar asignación",
                            f"{len(unassigned)} miembros sin tareas. Evaluar reasignación o capacitación."))
    if total > 20 and opened > closed * 2:
        suggestions.append(("Balancear abiertas vs cerradas",
                            f"Proporción desfavorable ({opened} abiertas / {closed} cerradas). Cerrar completadas y definir WIP limit."))

    execution = int(dict(project.get("status_counts", {})).get("Ejecución", 0))
    if execution > 20:
        suggestions.append(("Gestionar WIP",
                            f"{execution} tareas en ejecución. Mantener WIP limit por miembro para mejorar entrega."))

    heavy = [m for m in members if int(m.get("total", 0)) >= 15]
    if heavy:
        names = ", ".join(str(m.get("name", "")).split()[0] for m in heavy[:2])
        suggestions.append(("Distribuir carga", f"Alta carga detectada ({names}). Redistribuir para evitar cuellos de botella."))
    if not suggestions:
        suggestions.append(("Mantener ritmo actual", "Indicadores saludables. Continuar prácticas actuales."))
    return suggestions


class DetailedGesproPDF(ReportPDF):
    """PDF detallado por proyecto, construido sobre la base común."""

    def title_value(self, title: str, value: str) -> None:
        self.set_font(self._font, "B", 11)
        self.set_text_color(*self._theme["accent"])
        self.cell(0, 7, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)
        self.para(value)

    def badge_line(self, project: dict) -> None:
        label, color = project_health(project)
        badge = f"  {label} ({float(project.get('health', 0)):.0f}%)  "
        self.set_fill_color(*color)
        self.set_text_color(*self._theme["white"])
        self.set_font(self._font, "B", 9)
        self.cell(self.get_string_width(badge) + 4, 7, badge, fill=True, align="C")
        self.set_text_color(*self._theme["ink"])
        self.cell(0, 7, f"  {project.get('name', '')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)

    def analysis_list(self, title: str, items: list[str], color: tuple[int, int, int]) -> None:
        self.set_font(self._font, "B", 11)
        self.set_text_color(*color)
        self.cell(0, 7, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)
        for item in items:
            self.bullet(item)
        self.ln(2)

    def suggestion_list(self, suggestions: list[tuple[str, str]]) -> None:
        self.set_font(self._font, "B", 11)
        self.set_text_color(*self._theme["accent"])
        self.cell(0, 7, "Sugerencias para el Jefe de Proyecto", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)
        for title, text in suggestions:
            self.bullet(f"{title}: {text}")
        self.ln(2)


def _general_suggestions(projects: list[dict]) -> list[tuple[str, str]]:
    total = sum(int(p.get("total", 0)) for p in projects)
    opened = sum(int(p.get("open", 0)) for p in projects)
    closed = sum(int(p.get("closed", 0)) for p in projects)
    overdue = sum(int(p.get("overdue", 0)) for p in projects)
    critical = [p for p in projects if float(p.get("health", 0)) < 50]

    recs: list[tuple[str, str]] = []
    if total and closed / total < 0.5:
        recs.append(("Priorizar cierre de tareas",
                     f"Avance global del {closed / total * 100:.1f}% insuficiente. Establecer metas semanales de cierre por proyecto."))
    if critical:
        recs.append(("Intervenir proyectos críticos",
                     f"Proyectos {', '.join(p.get('name', '')[:25] for p in critical)} necesitan atención inmediata."))
    if overdue > 5:
        recs.append(("Sistema de alertas",
                     f"{overdue} tareas vencidas en el portafolio. Implementar revisiones semanales de fechas."))
    recs.append(("Estandarizar actualización", "Tarea completada debe marcarse cerrada en GESPRO dentro de 2 días."))
    recs.append(("Reunión semanal de seguimiento", "Reuniones de 30 min por proyecto para revisar avance y bloqueos."))
    if opened < total:
        recs.append(("Mantener trazabilidad", "Consolidar el uso del tablero como fuente única de estado."))
    return recs


def _render_summary(pdf: DetailedGesproPDF, projects: list[dict], deltas: list[str] | None) -> None:
    total = sum(int(p.get("total", 0)) for p in projects)
    opened = sum(int(p.get("open", 0)) for p in projects)
    closed = sum(int(p.get("closed", 0)) for p in projects)
    overdue = sum(int(p.get("overdue", 0)) for p in projects)
    members = len({m.get("name") for p in projects for m in p.get("members", [])})

    pdf.add_page()
    pdf.section("1. Resumen General de Proyectos")
    pdf.para(
        f"Este informe consolida el estado actual de {len(projects)} proyectos gestionados en GESPRO (Redmine). "
        "Incluye métricas de miembros, tareas, avance y salud general."
    )
    pdf.kv_row("Total de proyectos", str(len(projects)))
    pdf.kv_row("Total de miembros", str(members))
    pdf.kv_row("Total de tareas", f"{total} ({opened} abiertas / {closed} cerradas)")
    pdf.kv_row("Tareas vencidas", str(overdue))
    if total:
        pdf.kv_row("Avance global", f"{closed / total * 100:.1f}%")

    if deltas:
        pdf.section("Cambios vs ejecución anterior")
        for delta in deltas:
            pdf.bullet(delta)

    pdf.section("Distribución de Salud por Proyecto")
    for project in projects:
        pdf.badge_line(project)

    pdf.section("Recomendaciones para el Área")
    for title, text in _general_suggestions(projects):
        pdf.bullet(f"{title}: {text}")


def _render_project(pdf: DetailedGesproPDF, project: dict) -> None:
    pdf.add_page()
    pdf.section(f"Proyecto: {project.get('name', 'Sin nombre')}")
    if project.get("description"):
        pdf.para(str(project["description"]), size=9)

    label, _ = project_health(project)
    pdf.kv_row("Estado general", f"{label} — {float(project.get('health', 0)):.1f}%")
    pdf.kv_row("Tareas totales / abiertas / cerradas",
               f"{project.get('total', 0)} / {project.get('open', 0)} / {project.get('closed', 0)}")
    pdf.kv_row("Tareas vencidas", str(project.get("overdue", 0)))

    analytics = project.get("analytics") or {}
    windows = analytics.get("windows") or {}
    if windows:
        days = windows["days"]
        pdf.kv_row(
            f"Creadas (últ. {days}d vs previos)",
            f"{windows['created_current']} vs {windows['created_previous']}",
        )
        pdf.kv_row(
            f"Cerradas (últ. {days}d vs previos)",
            f"{windows['closed_current']} vs {windows['closed_previous']}",
        )
    if analytics.get("velocity") is not None:
        pdf.kv_row("Velocidad (cerradas/semana)", str(analytics["velocity"]))

    status_counts = dict(project.get("status_counts", {}))
    if status_counts:
        pdf.ln(1)
        pdf.para("Distribución por estado: " + ", ".join(f"{k}: {v}" for k, v in status_counts.items()), size=9)

    members = project.get("members", [])
    if members:
        pdf.section("Miembros del Proyecto")
        pdf.table(
            ["Miembro", "Rol(es)", "Total", "Abiertas", "Atrasadas", "Cerradas", "%"],
            [[
                str(m.get("name", ""))[:32],
                ", ".join(m.get("roles", []))[:32],
                m.get("total", 0),
                m.get("open", 0),
                m.get("overdue", 0),
                m.get("closed", 0),
                f"{(int(m.get('closed', 0)) / max(1, int(m.get('total', 0))) * 100):.0f}%",
            ] for m in members],
            widths=[45, 45, 15, 22, 22, 22, 14],
        )

    pdf.analysis_list("Fortalezas", analyze_strengths(project), (40, 120, 40))
    weaknesses = analyze_weaknesses(project)
    if weaknesses:
        pdf.analysis_list("Debilidades y Riesgos", weaknesses, (180, 30, 30))
    else:
        pdf.para("No se identifican riesgos críticos.")
    pdf.suggestion_list(analyze_suggestions(project))


def build_detailed_pdf(projects: list[dict], cfg: dict, out_path: Path,
                       deltas: list[str] | None = None) -> None:
    pdf = DetailedGesproPDF(
        cfg["company"],
        "Informe de Estado de Proyectos",
        theme=get_theme(cfg.get("ui", {}).get("theme")),
    )
    pdf.cover("Seguimiento detallado y salud del portafolio")
    _render_summary(pdf, projects, deltas)
    for project in projects:
        _render_project(pdf, project)

    pdf.add_page()
    pdf.section("Resumen Ejecutivo Consolidado")
    total = sum(int(p.get("total", 0)) for p in projects)
    closed = sum(int(p.get("closed", 0)) for p in projects)
    overdue = sum(int(p.get("overdue", 0)) for p in projects)
    pdf.para(
        f"El portafolio contiene {len(projects)} proyectos, {total} tareas registradas "
        f"y un avance global de {(closed / total * 100 if total else 0):.1f}%."
    )
    if overdue:
        pdf.bullet(f"Existen {overdue} tareas vencidas que requieren revisión inmediata.")
    for title, text in _general_suggestions(projects):
        pdf.bullet(f"{title}: {text}")

    pdf.output(str(out_path))
