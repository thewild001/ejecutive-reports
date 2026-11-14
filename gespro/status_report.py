#!/usr/bin/env python3
"""
Informe de estado de proyectos GESPRO/Redmine — formato heredado, genérico,
enriquecido con la analítica de gespro/analytics.py (evolución por período,
velocidad, cuellos de botella, tendencia de carga) y los cambios vs la ejecución anterior.

Es el generador "heredado" (fuente de la verdad del formato: portada, resumen,
detalle por proyecto con tabla de miembros, fortalezas/debilidades/sugerencias y
resumen ejecutivo) sin literales de organización: empresa, unidad, host y nombres
de estado salen de config.yaml. Los datos los recolecta gespro/gespro_report.py
(`collect`); este módulo solo los maqueta.
"""
from __future__ import annotations

import datetime
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.pdfbase import find_font_dir  # noqa: E402


@dataclass
class StatusSettings:
    company: str = ""
    unit: str = ""
    issued_by: str = ""
    host: str = ""
    system: str = "GESPRO"
    new_status_names: list[str] = field(default_factory=lambda: ["nueva", "new"])
    in_progress_status_names: list[str] = field(default_factory=lambda: ["ejecución", "in progress"])

    @property
    def author(self) -> str:
        return " — ".join(x for x in (self.unit, self.company) if x)


S = StatusSettings()


def configure(cfg: dict) -> StatusSettings:
    global S
    c, g = cfg.get("company", {}) or {}, cfg.get("gespro", {}) or {}
    S = StatusSettings(
        company=c.get("name", ""), unit=c.get("unit", ""), issued_by=c.get("issued_by", ""),
        host=re.sub(r"^https?://", "", str(g.get("base_url", ""))).rstrip("/"),
        system=g.get("system_name", "GESPRO"),
        new_status_names=[s.lower() for s in g.get("new_status_names", ["Nueva", "New"])],
        in_progress_status_names=[s.lower() for s in
                                  g.get("in_progress_status_names", ["Ejecución", "In Progress"])],
    )
    return S


def _count_status(proj: dict, names: list[str]) -> int:
    return sum(v for k, v in proj["status_counts"].items() if str(k).lower() in names)


def adapt(p: dict) -> dict:
    """Datos de gespro_report.collect() → forma que consumen los analizadores/PDF."""
    if "total_tasks" in p:  # ya adaptado
        return p
    pct = p["health"]
    label, color = (("BUENA", (40, 167, 69)) if pct >= 80 else
                    ("REGULAR", (255, 193, 7)) if pct >= 50 else ("CRÍTICA", (220, 53, 69)))
    members = [{"id": m.get("id"), "name": m["name"], "roles": m.get("roles", []),
                "total_tasks": m["total"], "open_tasks": m["open"],
                "closed_tasks": m["closed"], "overdue_tasks": m["overdue"]}
               for m in p["members"]]
    return {
        "id": p["id"], "name": p["name"], "description": p.get("description", ""),
        "members": members, "total_members": len(members),
        "total_tasks": p["total"], "total_open": p["open"], "total_closed": p["closed"],
        "health_pct": pct, "health_label": label, "health_color": color,
        "status_counts": dict(p["status_counts"]),
        "open_by_status": dict(p.get("open_by_status", {})),
        "overdue": p.get("overdue", 0),
        "analytics": p.get("analytics") or {},
    }


def _analyze_strengths(proj):
    strengths = []
    if proj["health_pct"] >= 80:
        strengths.append(f"Alta tasa de cierre ({proj['health_pct']:.0f}%), indicando buena gestión y cumplimiento de tareas.")
    elif proj["health_pct"] >= 60:
        strengths.append(f"Tasa de cierre aceptable ({proj['health_pct']:.0f}%), con avance sostenido.")
    if proj["total_tasks"] > 50:
        strengths.append(f"Alto volumen de tareas registradas ({proj['total_tasks']}), reflejando uso activo del sistema.")
    active = [m for m in proj["members"] if m["total_tasks"] > 0]
    if len(active) > len(proj["members"]) * 0.7:
        strengths.append(f"Alta participación ({len(active)}/{proj['total_members']} miembros con tareas).")
    top = [m for m in active if m["total_tasks"] >= 3 and m["closed_tasks"] / m["total_tasks"] >= 0.7]
    if top:
        strengths.append(f"{len(top)} miembro(s) con alto desempeño (≥70% cierre).")
    overdue = sum(m.get("overdue_tasks", 0) for m in proj["members"])
    if proj["total_tasks"] > 0 and overdue == 0:
        strengths.append("No hay tareas vencidas, indica buena planificación.")
    if not strengths:
        strengths.append(f"Proyecto en fase de {'inicio' if proj['total_tasks'] < 10 else 'desarrollo'} con {proj['total_tasks']} tareas.")
    return strengths


def _analyze_weaknesses(proj):
    weaknesses = []
    if proj["health_pct"] < 40:
        weaknesses.append(f"Baja tasa de cierre ({proj['health_pct']:.0f}%), solo {proj['total_closed']} de {proj['total_tasks']} completadas.")
    elif proj["health_pct"] < 60:
        weaknesses.append(f"Tasa de cierre baja ({proj['health_pct']:.0f}%), con {proj['total_open']} tareas abiertas.")
    overdue = sum(m.get("overdue_tasks", 0) for m in proj["members"])
    if overdue > 5:
        weaknesses.append(f"{overdue} tareas vencidas sin cerrar, problemas de planificación o carga excesiva.")
    elif overdue > 0:
        weaknesses.append(f"{overdue} tarea(s) vencida(s), requieren atención inmediata.")
    unassigned = [m for m in proj["members"] if m["total_tasks"] == 0]
    if len(unassigned) > len(proj["members"]) * 0.3:
        weaknesses.append(f"{len(unassigned)} miembros sin tareas ({len(unassigned)}/{proj['total_members']}), posible subutilización.")
    if proj["total_open"] > 100:
        weaknesses.append(f"Alta acumulación de tareas abiertas ({proj['total_open']}), posible falta de recursos.")
    critical = [m for m in proj["members"] if m.get("overdue_tasks", 0) >= 3]
    if critical:
        names = ", ".join(m["name"].split()[0] for m in critical[:3])
        weaknesses.append(f"{len(critical)} miembro(s) con 3+ tareas atrasadas ({names}{'...' if len(critical) > 3 else ''}).")
    if proj["total_tasks"] == 0:
        weaknesses.append(f"Proyecto sin tareas registradas en {S.system}.")
    an = proj.get("analytics") or {}
    for b in an.get("bottlenecks", []):
        weaknesses.append(f"Cuello de botella: {b['share']:.0f}% de las tareas abiertas están en '{b['status']}' ({b['count']}).")
    growing = [n for n, t in (an.get("member_trends") or {}).items() if t == "creciente"]
    if growing:
        weaknesses.append(f"Carga creciente (abren más de lo que cierran) en: {', '.join(n.split()[0] for n in growing[:4])}{'...' if len(growing) > 4 else ''}.")
    new_count = _count_status(proj, S.new_status_names)
    if proj["total_tasks"] > 0 and new_count / max(proj["total_tasks"], 1) > 0.4:
        weaknesses.append(f"{new_count} tareas en estado inicial ('Nueva') ({new_count/max(proj['total_tasks'],1)*100:.0f}%), sin asignar.")
    return weaknesses


def _analyze_suggestions(proj):
    suggestions = []
    if proj["health_pct"] < 50:
        suggestions.append(("Revisión urgente de backlog",
            f"Convocar sesión para revisar {proj['total_open']} tareas abiertas. Priorizar por impacto y redistribuir carga."))
    overdue = sum(m.get("overdue_tasks", 0) for m in proj["members"])
    if overdue > 0:
        suggestions.append(("Atención a tareas vencidas",
            f"Identificar {overdue} tareas vencidas, validar fechas y establecer compromisos."))
    unassigned = [m for m in proj["members"] if m["total_tasks"] == 0]
    if len(unassigned) >= 3:
        suggestions.append(("Optimizar asignación",
            f"{len(unassigned)} miembros sin tareas. Evaluar reasignación o capacitación."))
    if proj["total_open"] > proj["total_closed"] * 2 and proj["total_tasks"] > 20:
        suggestions.append(("Balancear abiertas vs cerradas",
            f"Proporción desfavorable ({proj['total_open']} abiertas / {proj['total_closed']} cerradas). Cerrar completadas y definir WIP limit."))
    exec_count = _count_status(proj, S.in_progress_status_names)
    if exec_count > 20:
        suggestions.append(("Gestionar WIP",
            f"{exec_count} tareas en ejecución. Mantener WIP limit por miembro para mejorar entrega."))
    heavy = [m for m in proj["members"] if m["total_tasks"] >= 15]
    if heavy:
        suggestions.append(("Distribuir carga",
            f"Alta carga detectada ({', '.join(m['name'].split()[0] for m in heavy[:2])}). Redistribuir para evitar cuellos de botella."))
    if not suggestions:
        suggestions.append(("Mantener ritmo actual", "Indicadores saludables. Continuar prácticas actuales."))
    return suggestions


def _general_suggestions(all_projects, total_tasks_all, total_open_all, total_closed_all):
    recs = []
    overall_pct = total_closed_all / total_tasks_all * 100 if total_tasks_all > 0 else 0
    if overall_pct < 50:
        recs.append(("Priorizar cierre de tareas",
            f"Avance global del {overall_pct:.1f}% insuficiente. Establecer metas semanales de cierre por proyecto."))
    weak_projs = [p for p in all_projects if p["health_pct"] < 50]
    if weak_projs:
        recs.append(("Intervenir proyectos críticos",
            f"Proyectos {', '.join(p['name'][:25] for p in weak_projs)} necesitan atención inmediata."))
    overdue_total = sum(m.get("overdue_tasks", 0) for p in all_projects for m in p["members"])
    if overdue_total > 5:
        recs.append(("Sistema de alertas",
            f"{overdue_total} tareas vencidas en el portafolio. Implementar revisiones semanales de fechas."))
    unassigned = [m for p in all_projects for m in p["members"] if m["total_tasks"] == 0]
    if len(unassigned) > 3:
        recs.append(("Optimizar recursos",
            f"{len(unassigned)} miembros sin tareas asignadas. Reasignar a proyectos con mayor carga."))
    recs.append(("Estandarizar actualización",
        f"Tarea completada debe marcarse cerrada en {S.system} dentro de 2 días."))
    recs.append(("Reunión semanal de seguimiento",
        "Reuniones de 30 min por proyecto para revisar avance y bloqueos."))
    return recs


def generate_pdf(all_projects, out_path, deltas=None):
    """Compone el PDF de estado en `out_path` (formato heredado, genérico)."""
    all_projects = [adapt(p) for p in all_projects]
    org = S.company or "la organización"
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    fonts = find_font_dir()
    pdf.add_font("DejaVu", "", str(Path(fonts) / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", str(Path(fonts) / "DejaVuSans-Bold.ttf"))
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margin(10)

    now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    HEADER_TEXT = f"Informe de Estado - Proyectos {S.company} ({S.system})".replace("  ", " ")

    # ── Totales ──
    total_members_all = sum(p["total_members"] for p in all_projects)
    total_tasks_all = sum(p["total_tasks"] for p in all_projects)
    total_open_all = sum(p["total_open"] for p in all_projects)
    total_closed_all = sum(p["total_closed"] for p in all_projects)

    # ── Table of Contents tracking ──
    def header():
        if pdf.page_no() == 1:
            return
        pdf.set_y(8)
        pdf.set_font("DejaVu", "B", 8)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 5, HEADER_TEXT, align="L")
        pdf.cell(0, 5, f"Pág. {pdf.page_no()}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_y(15)
        pdf.line(10, 15, 200, 15)
        pdf.ln(6)

    def footer():
        pdf.set_y(-15)
        pdf.set_font("DejaVu", "", 7)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 10, "  |  ".join(x for x in (f"Generado: {now_str}", S.company, S.host) if x), align="C")

    pdf.header = header
    pdf.footer = footer

    def section_title(title):
        pdf.set_font("DejaVu", "B", 14)
        pdf.set_text_color(20, 60, 120)
        pdf.cell(0, 10, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_draw_color(20, 60, 120)
        pdf.set_line_width(0.5)
        y_line = pdf.get_y() + 1
        pdf.line(10, y_line, 200, y_line)
        pdf.set_y(y_line + 5)

    def body_text(text):
        pdf.set_font("DejaVu", "", 10)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 5.5, text)
        pdf.ln(3)

    def kv_line(key, value):
        pdf.set_font("DejaVu", "B", 10)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(pdf.get_string_width(key + ": "), 5.5, key + ": ")
        pdf.set_font("DejaVu", "", 10)
        pdf.cell(0, 5.5, str(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1)

    def bullet_item(text, indent=8):
        pdf.set_font("DejaVu", "", 10)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(indent, 5.5, "•")
        pdf.multi_cell(0, 5.5, f" {text}")
        pdf.ln(1)

    # ═══════════════ PORTADA ═══════════════
    pdf.add_page()
    pdf.ln(40)
    pdf.set_font("DejaVu", "B", 28)
    pdf.set_text_color(20, 60, 120)
    pdf.cell(0, 16, "INFORME DE ESTADO", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)
    pdf.set_font("DejaVu", "", 20)
    pdf.set_text_color(40, 80, 140)
    pdf.cell(0, 12, f"Proyectos {S.company}".strip(), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 12, f"({S.system})", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(10)
    pdf.set_draw_color(20, 60, 120)
    pdf.set_line_width(0.8)
    pdf.line(50, pdf.get_y(), 160, pdf.get_y())
    pdf.ln(12)
    pdf.set_font("DejaVu", "", 12)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, S.author, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 8, f"Generado: {now_str}", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(8)
    pdf.set_font("DejaVu", "", 11)
    pdf.cell(0, 8,
             f"{len(all_projects)} proyectos  |  {total_members_all} miembros  |  {total_tasks_all} tareas",
             align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)
    pdf.cell(0, 7,
             f"{total_open_all} abiertas  |  {total_closed_all} cerradas  |  Avance: {total_closed_all/total_tasks_all*100:.1f}%" if total_tasks_all > 0 else "",
             align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ═══════════════ ÍNDICE DE CONTENIDO ═══════════════

    # ═══════════════ RESUMEN GENERAL ═══════════════
    pdf.add_page()
    section_title(f"1. Resumen General de Proyectos {S.company}".strip())
    body_text(
        f"Este informe consolida el estado actual de los {len(all_projects)} proyectos de {org} "
        f"gestionados en {S.system} (Redmine). Se incluyen métricas de miembros, tareas, avance y salud general."
    )

    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(40, 80, 140)
    pdf.cell(0, 7, "Indicadores Clave Consolidados", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)
    kv_line("Total de proyectos", str(len(all_projects)))
    kv_line("Total de miembros", str(total_members_all))
    kv_line("Total de tareas", str(total_tasks_all))
    kv_line("Tareas abiertas", str(total_open_all))
    kv_line("Tareas cerradas", str(total_closed_all))
    if total_tasks_all > 0:
        kv_line("Avance global", f"{total_closed_all / total_tasks_all * 100:.1f}%")
    kv_line("Tareas vencidas", str(sum(p["overdue"] for p in all_projects)))

    if deltas:
        pdf.ln(4)
        pdf.set_font("DejaVu", "B", 11)
        pdf.set_text_color(40, 80, 140)
        pdf.cell(0, 7, "Cambios vs ejecución anterior", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)
        for d in deltas:
            bullet_item(d)

    pdf.ln(4)
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(40, 80, 140)
    pdf.cell(0, 7, "Distribución de Salud por Proyecto", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    for p in all_projects:
        hc = p["health_color"]
        pdf.set_fill_color(*hc)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("DejaVu", "B", 9)
        badge = f"  {p['health_label']} ({p['health_pct']:.0f}%)  "
        badge_w = pdf.get_string_width(badge) + 4
        pdf.cell(badge_w, 6, badge, fill=True, align="C")
        pdf.set_text_color(30, 30, 30)
        pdf.set_font("DejaVu", "", 9)
        pdf.cell(0, 6,
                 f"  {p['name']}  —  {p['total_open']} abiertas / {p['total_closed']} cerradas",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)

    # ── Recomendaciones para el área ──
    pdf.ln(4)
    pdf.set_font("DejaVu", "B", 12)
    pdf.set_text_color(40, 80, 140)
    pdf.cell(0, 8, f"Recomendaciones para {org}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(40, 80, 140)
    pdf.set_line_width(0.4)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 100, pdf.get_y())
    pdf.ln(4)

    recs = _general_suggestions(all_projects, total_tasks_all, total_open_all, total_closed_all)
    for bold_t, text in recs:
        pdf.set_font("DejaVu", "B", 10)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(8, 5.5, "•")
        pdf.cell(0, 5.5, f" {bold_t}: ", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("DejaVu", "", 10)
        pdf.set_x(18)
        pdf.multi_cell(0, 5.5, text)
        pdf.ln(2)

    # ═══════════════ DETALLE POR PROYECTO ═══════════════
    for idx, proj in enumerate(all_projects, 1):
        pdf.add_page()
        section_title(f"2.{idx}. Proyecto")

        pdf.set_font("DejaVu", "", 11)
        pdf.set_text_color(40, 40, 40)
        pdf.multi_cell(0, 6, proj["name"])
        pdf.ln(2)

        pdf.set_font("DejaVu", "", 9)
        pdf.set_text_color(80, 80, 80)
        pdf.multi_cell(0, 5, f"Descripción: {proj['description']}" if proj["description"] else "Sin descripción.")
        pdf.ln(4)

        # ── Project card ──
        all_statuses = list(proj["status_counts"].items())
        status_str = "   ".join(f"{k}: {v}" for k, v in all_statuses)
        y_start = pdf.get_y()
        if y_start + 30 > pdf.h - 25:
            pdf.add_page()
            y_start = pdf.get_y()

        pdf.set_xy(14, y_start + 3)
        hc = proj["health_color"]
        pdf.set_fill_color(*hc)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("DejaVu", "B", 9)
        badge = f"  {proj['health_label']} ({proj['health_pct']:.0f}%)  "
        badge_w = pdf.get_string_width(badge) + 4
        pdf.cell(badge_w, 7, badge, fill=True, align="C")
        pdf.set_text_color(40, 40, 40)
        pdf.set_font("DejaVu", "", 9)

        row2 = y_start + 12
        pdf.set_xy(14, row2)
        pdf.cell(0, 5, f"Miembros: {proj['total_members']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_x(14)
        pdf.cell(0, 5,
                 f"Tareas: {proj['total_tasks']} total  |  Abiertas: {proj['total_open']}  |  Cerradas: {proj['total_closed']}",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_x(14)
        pdf.set_font("DejaVu", "B", 8)
        pdf.cell(18, 4.5, "Estados:")
        pdf.set_font("DejaVu", "", 8)
        pdf.multi_cell(172, 4.5, status_str)

        y_end = pdf.get_y()
        pdf.set_fill_color(248, 249, 250)
        pdf.rect(10, y_start, 190, y_end - y_start + 3, style="F")
        pdf.set_xy(14, y_start + 3)
        pdf.set_fill_color(*hc)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("DejaVu", "B", 9)
        pdf.cell(badge_w, 7, badge, fill=True, align="C")
        pdf.set_y(y_end + 5)

        # ── Evolución del período ──
        an = proj.get("analytics") or {}
        w = an.get("windows")
        if w:
            pdf.set_font("DejaVu", "B", 11)
            pdf.set_text_color(40, 80, 140)
            pdf.cell(0, 7, f"Evolución (últimos {w['days']} días vs {w['days']} previos)",
                     new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1)
            kv_line("Creadas", f"{w['created_current']} vs {w['created_previous']}")
            kv_line("Cerradas", f"{w['closed_current']} vs {w['closed_previous']}")
            if an.get("velocity") is not None:
                kv_line("Velocidad (cerradas/semana)", str(an["velocity"]))
            pdf.ln(3)

        # ── Tareas Abiertas ──
        if proj["open_by_status"]:
            pdf.set_font("DejaVu", "B", 11)
            pdf.set_text_color(40, 80, 140)
            pdf.cell(0, 7, "Tareas Abiertas", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(2)
            cws = [120, 30]
            pdf.set_fill_color(230, 235, 245)
            pdf.set_font("DejaVu", "B", 9)
            pdf.set_text_color(30, 30, 30)
            pdf.cell(cws[0], 6, "Tarea", border=1, fill=True, align="C")
            pdf.cell(cws[1], 6, "Cantidad", border=1, fill=True, align="C")
            pdf.ln()
            pdf.set_font("DejaVu", "", 9)
            for sn, cnt in sorted(proj["open_by_status"].items(), key=lambda x: -x[1]):
                pdf.cell(cws[0], 5.5, f"  {sn}", border=1)
                pdf.cell(cws[1], 5.5, str(cnt), border=1, align="C")
                pdf.ln()
            pdf.ln(4)

        # ── Tabla de miembros ──
        pdf.set_font("DejaVu", "B", 11)
        pdf.set_text_color(40, 80, 140)
        pdf.cell(0, 7, "Miembros del Proyecto", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)

        col_ws = [70, 54, 14, 14, 14, 14, 12]
        headers = ["Miembro", "Rol(es)", "Total", "Abiertas", "Atrasadas", "Cerradas", "%"]
        pdf.set_fill_color(230, 235, 245)
        pdf.set_font("DejaVu", "B", 7.5)
        pdf.set_text_color(30, 30, 30)
        for i, h in enumerate(headers):
            pdf.cell(col_ws[i], 6, h, border=1, fill=True, align="C")
        pdf.ln()

        pdf.set_font("DejaVu", "", 7.5)
        for m in proj["members"]:
            total_m = m["total_tasks"]
            pct = (m["closed_tasks"] / total_m * 100) if total_m > 0 else 0
            overdue = m.get("overdue_tasks", 0)

            # Prepare cell texts (full, no truncation)
            cell_texts = [
                m["name"],
                ", ".join(m["roles"]),
                str(total_m),
                str(m["open_tasks"]),
                str(overdue) if overdue > 0 else "0",
                str(m["closed_tasks"]),
                f"{pct:.0f}%",
            ]
            cell_aligns = ["L", "L", "C", "C", "C", "C", "C"]
            line_h = 5

            # Step 1: Calculate row height based on text wrapping
            max_lines = 1
            for ci in range(len(col_ws)):
                tw = pdf.get_string_width(cell_texts[ci])
                available = col_ws[ci] - 2  # 1mm padding each side
                if available < 5:
                    available = 5
                n_lines = max(1, int(tw / available) + (1 if tw % available > 0 else 0))
                if n_lines > max_lines:
                    max_lines = n_lines
            row_h = max_lines * line_h
            if row_h < line_h:
                row_h = line_h

            # Check page break
            if pdf.get_y() + row_h > pdf.h - 20:
                pdf.add_page()
                # Re-draw header
                pdf.set_fill_color(230, 235, 245)
                pdf.set_font("DejaVu", "B", 7.5)
                pdf.set_text_color(30, 30, 30)
                for i, h in enumerate(headers):
                    pdf.cell(col_ws[i], 6, h, border=1, fill=True, align="C")
                pdf.ln()
                pdf.set_font("DejaVu", "", 7.5)

            y_row = pdf.get_y()
            x_row = pdf.l_margin

            # Step 2: Draw all cell borders
            for ci in range(len(col_ws)):
                pdf.rect(x_row + sum(col_ws[:ci]), y_row, col_ws[ci], row_h)

            # Step 3: Render text in each cell, vertically centered
            for ci in range(len(col_ws)):
                if ci == 4 and overdue > 0:
                    pdf.set_text_color(220, 53, 69)
                # Calculate vertical offset to center text
                tw = pdf.get_string_width(cell_texts[ci])
                available = col_ws[ci] - 2
                if available < 5:
                    available = 5
                n_lines = max(1, int(tw / available) + (1 if tw % available > 0 else 0))
                text_h = n_lines * line_h
                y_text = y_row + (row_h - text_h) / 2
                if y_text < y_row:
                    y_text = y_row
                pdf.set_xy(x_row + sum(col_ws[:ci]) + 1, y_text)
                pdf.multi_cell(col_ws[ci] - 2, line_h, cell_texts[ci], align=cell_aligns[ci], border=0)
                if ci == 4 and overdue > 0:
                    pdf.set_text_color(30, 30, 30)

            pdf.set_y(y_row + row_h)

        pdf.ln(3)

        # ── Análisis del Proyecto ──
        if pdf.get_y() + 80 > pdf.h - 20:
            pdf.add_page()
        pdf.set_font("DejaVu", "B", 13)
        pdf.set_text_color(20, 60, 120)
        pdf.cell(0, 10, "Análisis del Proyecto", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_draw_color(20, 60, 120)
        pdf.set_line_width(0.5)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)

        # Fortalezas
        pdf.set_font("DejaVu", "B", 11)
        pdf.set_text_color(40, 120, 40)
        pdf.cell(0, 7, "Fortalezas", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)
        strengths = _analyze_strengths(proj)
        for s in strengths:
            bullet_item(s)
        pdf.ln(3)

        # Debilidades
        pdf.set_font("DejaVu", "B", 11)
        pdf.set_text_color(180, 30, 30)
        pdf.cell(0, 7, "Debilidades y Riesgos", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)
        weaknesses = _analyze_weaknesses(proj)
        if weaknesses:
            for w in weaknesses:
                bullet_item(w)
        else:
            pdf.set_font("DejaVu", "", 10)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(0, 5.5, "No se identifican riesgos críticos.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)

        # Sugerencias
        pdf.set_font("DejaVu", "B", 11)
        pdf.set_text_color(40, 80, 140)
        pdf.cell(0, 7, "Sugerencias para el Jefe de Proyecto", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)
        suggestions = _analyze_suggestions(proj)
        for bt, tx in suggestions:
            pdf.set_font("DejaVu", "B", 10)
            pdf.set_text_color(30, 30, 30)
            pdf.cell(8, 5.5, "•")
            pdf.cell(0, 5.5, f" {bt}: ", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font("DejaVu", "", 10)
            pdf.set_x(18)
            pdf.multi_cell(0, 5.5, tx)
            pdf.ln(2)

    # ═══════════════ RESUMEN EJECUTIVO CONSOLIDADO ═══════════════
    pdf.add_page()
    section_title("3. Resumen Ejecutivo Consolidado")

    overall_pct = total_closed_all / total_tasks_all * 100 if total_tasks_all > 0 else 0

    # Fortalezas del Grupo
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(40, 120, 40)
    pdf.cell(0, 7, "Fortalezas del Grupo", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.set_font("DejaVu", "", 10)
    pdf.set_text_color(30, 30, 30)
    bullet_item(f"Portafolio de {len(all_projects)} proyectos activos con {total_members_all} miembros y {total_tasks_all} tareas registradas en {S.system}, demostrando uso del sistema de seguimiento.")
    if overall_pct >= 60:
        bullet_item(f"Avance global del {overall_pct:.1f}% indicando productividad adecuada en el portafolio.")
    best = [m for p in all_projects for m in p["members"] if m["total_tasks"] > 0 and m["closed_tasks"] / m["total_tasks"] >= 0.7]
    if best:
        bullet_item(f"{len(best)} miembros con alto desempeño (≥70% de cierre), destacando compromiso con la entrega.")
    pdf.ln(3)

    # Riesgos del Grupo
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(180, 30, 30)
    pdf.cell(0, 7, "Riesgos del Grupo", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.set_font("DejaVu", "", 10)
    pdf.set_text_color(30, 30, 30)
    wp = [p for p in all_projects if p["health_pct"] < 50]
    if wp:
        bullet_item(f"{len(wp)} proyecto(s) con salud crítica (<50%): {', '.join(p['name'][:35] for p in wp)}.")
    if overall_pct < 50:
        bullet_item(f"Avance global bajo ({overall_pct:.1f}%), requiere mejorar la tasa de cierre en el portafolio.")
    od = sum(m.get("overdue_tasks", 0) for p in all_projects for m in p["members"])
    if od > 0:
        bullet_item(f"{od} tareas vencidas sin cerrar en todo el portafolio.")
    ua = [m for p in all_projects for m in p["members"] if m["total_tasks"] == 0]
    if len(ua) > 5:
        bullet_item(f"{len(ua)} miembros sin tareas asignadas, posible subutilización de recursos.")
    pdf.ln(3)

    # Recomendaciones Estratégicas
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(40, 80, 140)
    pdf.cell(0, 7, "Recomendaciones Estratégicas", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    for bt, tx in recs:
        pdf.set_font("DejaVu", "B", 10)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(8, 5.5, "•")
        pdf.cell(0, 5.5, f" {bt}: ", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("DejaVu", "", 10)
        pdf.set_x(18)
        pdf.multi_cell(0, 5.5, tx)
        pdf.ln(2)

    pdf.ln(4)
    pdf.set_font("DejaVu", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "  |  ".join(x for x in (f"Generado: {now_str}", S.company, S.host) if x),
             align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.output(str(out_path))
    return out_path
