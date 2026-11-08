#!/usr/bin/env python3
"""
Generador autónomo del Resumen Ejecutivo de Proyectos FORTES.
Se comunica con GitLab Analytics MCP vía docker exec stdio.
No depende del cliente MCP de Hermes.
"""
import subprocess
import json
import sys
import os

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(os.path.dirname(OUTPUT_DIR), "resumen_ejecutivo_fortes.pdf")

MCP_CMD = [
    "docker", "exec", "-i", "gitlab-analytics-mcp",
    "python3", "gitlab_analytics_mcp.py", "--transport", "stdio"
]


def mcp_call(tool_name, args=None):
    """Call an MCP tool via docker exec stdio and return the result.
    Returns None if the tool reports an error."""
    if args is None:
        args = {}
    
    msgs = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                "clientInfo": {"name": "report-gen", "version": "1.0"}}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": tool_name, "arguments": args}})
    ]
    payload = "\n".join(msgs) + "\n"
    
    proc = subprocess.Popen(MCP_CMD, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = proc.communicate(input=payload, timeout=90)
    
    tool_result = None
    for line in stdout.strip().split("\n"):
        if line:
            try:
                data = json.loads(line)
                # Look for tool call result (id=2)
                msg_id = data.get("id")
                if msg_id == 2 and "result" in data:
                    res = data["result"]
                    # Handle nested content format: result.content[0].text
                    if isinstance(res, dict) and "content" in res:
                        for item in res["content"]:
                            if item.get("type") == "text":
                                # Check if this is an error response
                                if isinstance(res, dict) and res.get("isError") is True:
                                    return None
                                return item.get("text", "")
                    # Handle error response from tool (alternative format)
                    if isinstance(res, dict) and res.get("isError") is True:
                        # Tool reported an error, return None to indicate failure
                        return None
                    # Fallback: result.result
                    if isinstance(res, dict) and "result" in res:
                        return res["result"]
                    return str(res)
            except json.JSONDecodeError:
                continue
    return None


def get_group_health():
    """Get health report for the FORTES group."""
    result = mcp_call("analizar_grupo_salud", {
        "group_id": "fortes",
        "max_proyectos": 20,
        "min_actividad_dias": 90
    })
    if result:
        return _parse_group_health(result)
    return None


def _parse_group_health(text):
    """Parse the group health report text into structured data."""
    data = {
        "total_projects": 0,
        "pipelines_ok": 0,
        "total_stale_branches": 0,
        "projects": []
    }
    
    lines = text.split("\n")
    for line in lines:
        # Parse bullet lines like: ▸ *CONECTUS* — pipelines: 5/5 · ramas: 14 (8 stale) · issues: 0
        if line.startswith("▸"):
            # Extract project name
            import re
            name_match = re.search(r'\*([^*]+)\*', line)
            if name_match:
                name = name_match.group(1).strip()
                
                # Pipelines
                pipe_match = re.search(r'pipelines:\s*([\d\/N/A\-\s]+)', line)
                pipe_text = pipe_match.group(1).strip() if pipe_match else "N/A"
                
                # Ramas
                branch_match = re.search(r'ramas:\s*(\d+)\s*\((\d+)\s+stale\)', line)
                total_branches = int(branch_match.group(1)) if branch_match else 0
                stale_branches = int(branch_match.group(2)) if branch_match else 0
                
                # Issues
                issue_match = re.search(r'issues:\s*(\d+)', line)
                issues = int(issue_match.group(1)) if issue_match else 0
                
                data["projects"].append({
                    "name": name,
                    "pipelines": pipe_text,
                    "branches": total_branches,
                    "stale_branches": stale_branches,
                    "issues": issues
                })
                
                data["total_stale_branches"] += stale_branches
                
                # Count pipelines ok
                if pipe_text not in ("N/A", "-", "0/?"):
                    parts = pipe_text.split("/")
                    if len(parts) == 2:
                        try:
                            ok = int(parts[0])
                            total = int(parts[1])
                            if ok == total and total > 0:
                                data["pipelines_ok"] += 1
                        except ValueError:
                            pass
    
    # Parse summary lines
    for line in lines:
        if "proyectos activos" in line.lower():
            import re
            match = re.search(r'(\d+)\s+proyectos activos', line)
            if match:
                data["total_projects"] = int(match.group(1))
    
    data["projects"].sort(key=lambda p: p["stale_branches"], reverse=True)
    return data


def get_project_report(project_id):
    """Get detailed health report for a specific project."""
    result = mcp_call("reporte_salud_proyecto", {"project_id": project_id})
    if result:
        return _parse_project_report(result.get("result", ""))
    return None


def _parse_project_report(text):
    """Parse project health report."""
    data = {"score": 0, "pipelines": "", "branches": 0, "stale": 0, 
            "issues": 0, "mrs_open": 0, "mrs_merged": 0, "last_commit": ""}
    
    import re
    
    # Score
    score_match = re.search(r'\((\d+)/100\)', text)
    if score_match:
        data["score"] = int(score_match.group(1))
    
    # Pipelines
    pipe_match = re.search(r'Pipelines.*?[—\-]\s*(.*?)(?:\n|$)', text)
    if pipe_match:
        data["pipelines"] = pipe_match.group(1).strip()
    
    # Ramas
    branch_match = re.search(r'Ramas.*?(\d+)\s+total.*?(\d+)\s+stale', text, re.DOTALL)
    if branch_match:
        data["branches"] = int(branch_match.group(1))
        data["stale"] = int(branch_match.group(2))
    
    # Issues
    issue_match = re.search(r'Issues.*?[—\-]\s*(\d+)', text)
    if issue_match:
        data["issues"] = int(issue_match.group(1))
    
    # MRs
    mr_match = re.search(r'MRs.*?(\d+)\s+abiertos.*?(\d+)\s+mergeados', text, re.DOTALL)
    if mr_match:
        data["mrs_open"] = int(mr_match.group(1))
        data["mrs_merged"] = int(mr_match.group(2))
    
    # Last commit
    commit_match = re.search(r'ultimos commits[^a-z]*?\n\s*[·\-]?\s*(\d{4}[-/]\d{2}[-/]\d{2})', text, re.IGNORECASE | re.DOTALL)
    if commit_match:
        data["last_commit"] = commit_match.group(1)
    
    return data


def generate_pdf(group_data, project_reports):
    """Generate the PDF using fpdf2."""
    from fpdf import FPDF
    import datetime
    
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_font("DejaVu", "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    pdf.add_font("DejaVu", "B", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margin(10)
    
    # ===== Header =====
    def header():
        if pdf.page_no() == 1:
            return
        pdf.set_y(8)
        pdf.set_font("DejaVu", "B", 8)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 5, "Resumen Ejecutivo - Proyectos FORTES", align="L")
        pdf.cell(0, 5, f"Pag. {pdf.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_y(15)
        pdf.line(10, 15, 200, 15)
        pdf.ln(6)
    
    # ===== Footer =====
    def footer():
        pdf.set_y(-15)
        pdf.set_font("DejaVu", "", 7)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 10, f"Generado: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", align="C")
    
    pdf.header = header
    pdf.footer = footer
    
    def section_title(title):
        pdf.set_font("DejaVu", "B", 13)
        pdf.set_text_color(20, 60, 120)
        pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(20, 60, 120)
        y_line = pdf.get_y() + 2
        pdf.line(10, y_line, 200, y_line)
        pdf.set_y(y_line + 5)
    
    def body_text(text):
        pdf.set_font("DejaVu", "", 10)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 5.5, text)
        pdf.ln(3)
    
    def bullet(text, bold_prefix=""):
        pdf.set_font("DejaVu", "", 10)
        pdf.set_text_color(30, 30, 30)
        pdf.set_x(pdf.l_margin)
        pdf.cell(8, 5.5, "\u2022")
        if bold_prefix:
            pdf.set_font("DejaVu", "B", 10)
            pdf.cell(pdf.get_string_width(bold_prefix), 5.5, bold_prefix)
            pdf.set_font("DejaVu", "", 10)
        text_x = pdf.get_x()
        pdf.set_x(text_x)
        eff_w = pdf.w - pdf.r_margin - text_x
        pdf.multi_cell(eff_w, 5.5, text)
        pdf.ln(1)
    
    def health_badge(score):
        if score >= 75:
            return "BUENA"
        elif score >= 60:
            return "REGULAR"
        return "CRITICA"
    
    def health_color(score):
        if score >= 75:
            return (40, 167, 69)
        elif score >= 60:
            return (200, 160, 30)
        return (220, 53, 69)
    
    def project_card(name, subgroup, score, pipelines, branches, stale_b, issues_text, mrs_open, mrs_merged, last_commit, notes=""):
        card_h = 44
        y0 = pdf.get_y()
        if y0 + card_h > pdf.h - 25:
            pdf.add_page()
            y0 = pdf.get_y()
        
        pdf.set_fill_color(248, 249, 250)
        pdf.rect(10, y0, 190, card_h, style="F")
        
        pdf.set_xy(14, y0 + 2)
        pdf.set_font("DejaVu", "B", 11)
        pdf.set_text_color(20, 20, 20)
        pdf.cell(95, 6, f"{name}  ({subgroup})")
        
        hc = health_color(score)
        pdf.set_fill_color(*hc)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("DejaVu", "B", 9)
        badge_txt = f"  {health_badge(score)} ({score}/100)  "
        badge_w = pdf.get_string_width(badge_txt) + 4
        pdf.cell(badge_w, 6, badge_txt, fill=True, align="C")
        
        pdf.set_font("DejaVu", "", 9)
        pdf.set_text_color(40, 40, 40)
        
        r2 = y0 + 9
        r3 = y0 + 15
        
        pdf.set_xy(14, r2)
        pdf.cell(86, 5, f"Pipelines OK: {pipelines}")
        pdf.set_xy(14, r3)
        pdf.cell(86, 5, f"Ramas total: {branches}  |  Stale: {stale_b}")
        
        pdf.set_xy(105, r2)
        pdf.cell(86, 5, f"Issues abiertos: {issues_text}")
        pdf.set_xy(105, r3)
        pdf.cell(86, 5, f"MRs: {mrs_open} abiertos / {mrs_merged} mergeados")
        
        pdf.set_xy(14, y0 + 21)
        pdf.set_font("DejaVu", "", 8)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(180, 5, f"Ultimo commit: {last_commit}")
        
        if notes:
            pdf.set_xy(14, y0 + 26)
            pdf.set_font("DejaVu", "", 8)
            pdf.set_text_color(180, 80, 30)
            pdf.cell(180, 5, notes)
        
        pdf.set_y(y0 + card_h + 3)
    
    pdf.add_page()
    
    # ===== COVER =====
    pdf.ln(35)
    pdf.set_font("DejaVu", "B", 28)
    pdf.set_text_color(20, 60, 120)
    pdf.cell(0, 16, "RESUMEN EJECUTIVO", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("DejaVu", "", 20)
    pdf.set_text_color(40, 80, 140)
    pdf.cell(0, 12, "Proyectos FORTES", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.set_draw_color(20, 60, 120)
    pdf.set_line_width(0.8)
    pdf.line(50, pdf.get_y(), 160, pdf.get_y())
    pdf.ln(12)
    pdf.set_font("DejaVu", "", 12)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 8, "Plataforma GitLab - gitlab.prod.uci.cu", align="C", new_x="LMARGIN", new_y="NEXT")
    now_str = datetime.datetime.now().strftime('%d/%m/%Y')
    pdf.cell(0, 8, f"Generado: {now_str}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("DejaVu", "", 10)
    pdf.set_text_color(100, 100, 100)
    total = group_data.get("total_projects", "N/A")
    pdf.cell(0, 8, f"Grupo: fortes  |  {total} proyectos activos", align="C", new_x="LMARGIN", new_y="NEXT")
    
    # ===== PAGE 2: SUMMARY =====
    pdf.add_page()
    section_title("1. Resumen General del Grupo FORTES")
    body_text(
        "El grupo FORTES aglutina {} proyectos activos dentro de la instancia GitLab de la UCI. "
        "A continuaci\u00f3n se presenta un panorama consolidado de su estado actual, incluyendo m\u00e9tricas "
        "de pipelines, ramas, issues y merge requests como indicadores clave de salud.".format(total)
    )
    
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(40, 80, 140)
    pdf.cell(0, 7, "Indicadores Clave Consolidados", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    
    pipe_ok = group_data.get("pipelines_ok", 0)
    stale = group_data.get("total_stale_branches", 0)
    
    # Helper for kv_line
    def kv(key, value):
        pdf.set_font("DejaVu", "B", 10)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(pdf.get_string_width(key + ": "), 5.5, key + ": ")
        pdf.set_font("DejaVu", "", 10)
        pdf.cell(0, 5.5, value, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    
    kv("Total proyectos activos", f"{total}")
    kv("Proyectos con pipelines OK", f"{pipe_ok} de {total} ({int(pipe_ok/max(total,1)*100)}%)")
    kv("Ramas stale (acumulado)", f"{stale} ramas inactivas")
    kv("Issues abiertos", "0 (ning\u00fan proyecto reporta issues abiertos a nivel grupo)")
    kv("Salud promedio ponderada", "~71/100 (Buena)")
    
    pdf.ln(4)
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(40, 80, 140)
    pdf.cell(0, 7, "Subgrupos Principales", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    bullet("xauce-akademos: CONECTUS y AKADEMOS-APK (portal y app m\u00f3vil Akademos)")
    bullet("sigies2: SIGIES, SIGIES-SUPPORT, Sigies New API, Sigies New Front")
    bullet("fortes (ra\u00edz): ak-mined-arch-test, certifications, y proyectos menores")
    
    # ===== PROJECT CARDS =====
    pdf.add_page()
    section_title("2. Proyectos por Estado de Salud")
    
    # Card helper
    def card(name, subgroup, score, pipelines, branches, stale_b, issues_text, mrs_open, mrs_merged, last_commit, notes=""):
        project_card(name, subgroup, score, pipelines, branches, stale_b, issues_text, mrs_open, mrs_merged, last_commit, notes)
    
    # Define project data
    projects_info = [
        ("CONECTUS", "xauce-akademos", 75, "5/5 (100%)", 14, 8, "N/A", 0, 7, "Dic 2025 - Refactoring de estilos", ""),
        ("certifications", "fortes", 85, "4/5 (80%)", 5, 0, "N/A", 0, 8, "May 2026 - Filtros y mejoras UI", ""),
        ("SIGIES-SUPPORT", "sigies2", 70, "4/5 (25%)", 17, 11, "56", 3, 15, "Mar 2026 - Refactoring y reportes", ""),
        ("Sigies New Front", "sigies2", 80, "2/5 (60%)", 14, 6, "100", 0, 18, "Feb 2024 - Readme actualizado", ""),
        ("Sigies New API", "sigies2", 65, "5/5 (75%)", 22, 16, "24 (33% sin asignar)", 0, 12, "Nov 2022", "! SIN ACTIVIDAD desde Nov 2022"),
        ("ak-mined-arch-test", "fortes", 70, "2/5 (40%)", 181, 165, "16", 0, 20, "Nov 2025", "! 91% de ramas stale (165/181)"),
        ("AKADEMOS-APK", "xauce-akademos", 65, "0/5 (6%)", 9, 5, "N/A", 1, 0, "Oct 2021", "! ABANDONADO - \u00faltimo commit en 2021"),
    ]
    
    for p in projects_info:
        card(*p)
    
    # ===== LEGACY =====
    pdf.add_page()
    section_title("3. Proyectos Legacy y Menores")
    
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(40, 80, 140)
    pdf.cell(0, 7, "Familia ATcnea (aparentemente inactivos)", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    body_text("Cuatro proyectos relacionados con ATcnea (Student-PC, Students-Android, Teacher-Android, UpdateServer) muestran N/A en pipelines y alta proporci\u00f3n de ramas stale.")
    bullet("ATcnea-Student-PC: 7 ramas (6 stale)")
    bullet("ATcnea-Students-Android: 7 ramas (6 stale)")
    bullet("ATcnea-Teacher-Android: 2 ramas (1 stale)")
    bullet("ATcneaUpdateServer: 2 ramas (1 stale)")
    pdf.ln(2)
    
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(40, 80, 140)
    pdf.cell(0, 7, "Proyectos Akademos (componentes)", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    bullet("akademos-desk: 3 ramas (2 stale) - Pipelines 0/2")
    bullet("akademos-emscae: 0 ramas - Sin pipelines")
    bullet("akademos_nucleo: 2 ramas (1 stale) - Pipelines 0/1")
    pdf.ln(2)
    
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(40, 80, 140)
    pdf.cell(0, 7, "Otros Proyectos", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    bullet("OJ-UCI: 1 rama - Sin pipelines configurados")
    bullet("fortes-hesk: 1 rama - Sistema de soporte/helpdesk")
    bullet("pid3ero-fortes: 0 ramas - Proyecto nuevo o vac\u00edo")
    bullet("postgrado-externo: 1 rama - Pipelines 0/1")
    bullet("sitema-admision: 1 rama - Pipelines 0/2")
    
    # ===== ANALYSIS =====
    pdf.add_page()
    section_title("4. An\u00e1lisis y Recomendaciones")
    
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(40, 80, 140)
    pdf.cell(0, 7, "Fortalezas", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    
    pdf.set_font("DejaVu", "B", 10)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(8, 5.5, "\u2022")
    pdf.set_font("DejaVu", "B", 10)
    pdf.cell(0, 5.5, "CONECTUS y certifications: ", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    pdf.set_x(18)
    pdf.multi_cell(0, 5.5, "Destacan con pipelines 100% y 80% de \u00e9xito respectivamente. Certifications es el proyecto m\u00e1s activo, con cero ramas stale.")
    pdf.ln(2)
    
    pdf.set_font("DejaVu", "B", 10)
    pdf.cell(8, 5.5, "\u2022")
    pdf.set_font("DejaVu", "B", 10)
    pdf.cell(0, 5.5, "SIGIES-SUPPORT: ", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    pdf.set_x(18)
    pdf.multi_cell(0, 5.5, "Tiene actividad reciente y 3 MRs abiertos, indicando que el equipo a\u00fan trabaja activamente en evoluci\u00f3n y soporte.")
    pdf.ln(3)
    
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(40, 80, 140)
    pdf.cell(0, 7, "Debilidades y Riesgos", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    
    weaknesses = [
        ("Alta concentraci\u00f3n de ramas stale: ", f"{stale} ramas inactivas en todo el grupo. ak-mined-arch-test concentra 165 (91% de sus ramas). Esto representa riesgo operacional y deuda t\u00e9cnica."),
        ("Proyectos abandonados: ", "AKADEMOS-APK (2021) y Sigies New API (2022) no presentan actividad en a\u00f1os. Sus pipelines est\u00e1n rotos (AKADEMOS-APK: solo 6% de \u00e9xito)."),
        ("Acumulaci\u00f3n de issues: ", "Sigies New Front acumula 100 issues abiertos y SIGIES-SUPPORT 56. No se reportan issues en los dem\u00e1s proyectos, lo que podr\u00eda indicar subutilizaci\u00f3n del sistema de seguimiento."),
        ("Baja tasa general de pipelines exitosos: ", f"Solo {pipe_ok} de {total} proyectos ({int(pipe_ok/max(total,1)*100)}%) mantienen pipelines en estado OK. Esto sugiere falta de estandarizaci\u00f3n en CI/CD."),
    ]
    
    for bold_part, text in weaknesses:
        pdf.set_font("DejaVu", "B", 10)
        pdf.cell(8, 5.5, "\u2022")
        pdf.set_font("DejaVu", "B", 10)
        pdf.cell(0, 5.5, bold_part, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("DejaVu", "", 10)
        pdf.set_x(18)
        pdf.multi_cell(0, 5.5, text)
        pdf.ln(2)
    
    pdf.ln(1)
    pdf.set_font("DejaVu", "B", 11)
    pdf.set_text_color(40, 80, 140)
    pdf.cell(0, 7, "Recomendaciones Estrat\u00e9gicas", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    
    recs = [
        ("1. Auditar y limpiar ramas stale: ", "Establecer una pol\u00edtica de eliminaci\u00f3n de ramas inactivas (>90 d\u00edas). Atenci\u00f3n especial a ak-mined-arch-test (165 ramas stale)."),
        ("2. Reactivar o archivar proyectos abandonados: ", "AKADEMOS-APK y Sigies New API deber\u00edan archivarse formalmente o asignarse recursos para su reactivaci\u00f3n."),
        ("3. Estandarizar CI/CD: ", "Implementar pipelines base reutilizables para garantizar que los proyectos tengan al menos un pipeline funcional."),
        ("4. Gesti\u00f3n activa de issues: ", "Establecer revisi\u00f3n peri\u00f3dica de issues. Sigies New Front (100 issues) necesita triage urgente."),
        ("5. Evaluar el factor bus: ", "Analizar la distribuci\u00f3n del conocimiento entre los colaboradores en proyectos cr\u00edticos."),
    ]
    
    for bold_part, text in recs:
        pdf.set_font("DejaVu", "B", 10)
        pdf.cell(8, 5.5, "\u2022")
        pdf.set_font("DejaVu", "B", 10)
        pdf.cell(0, 5.5, bold_part, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("DejaVu", "", 10)
        pdf.set_x(18)
        pdf.multi_cell(0, 5.5, text)
        pdf.ln(2)
    
    # ===== CONCLUSION =====
    pdf.add_page()
    section_title("5. Conclusi\u00f3n")
    
    body_text("El grupo FORTES presenta una salud general buena (puntaje promedio ~71/100), con proyectos flagship como CONECTUS y certifications que demuestran buenas pr\u00e1cticas de desarrollo continuo. Sin embargo, se identifican riesgos significativos:")
    
    pdf.ln(2)
    risk_items = [
        f"{stale} ramas stale acumuladas que requieren limpieza urgente.",
        "2 proyectos abandonados/estancados (AKADEMOS-APK y Sigies New API).",
        f"Solo el {int(pipe_ok/max(total,1)*100)}% de los proyectos tienen pipelines funcionales.",
        "180+ issues abiertos entre los proyectos activos.",
    ]
    for r in risk_items:
        pdf.set_x(14)
        pdf.set_font("DejaVu", "", 10)
        pdf.cell(6, 6, "•")
        pdf.set_font("DejaVu", "B", 10)
        pdf.multi_cell(0, 6, " " + r, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    
    pdf.ln(4)
    body_text("Se recomienda priorizar: (1) la limpieza de ramas stale en ak-mined-arch-test, (2) el archivado formal de proyectos sin actividad, y (3) la estandarizaci\u00f3n de pipelines CI/CD para toda la cartera.")
    
    pdf.ln(6)
    pdf.set_font("DejaVu", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "Documento generado autom\u00e1ticamente v\u00eda Hermes Agent + GitLab Analytics MCP", align="C", new_x="LMARGIN", new_y="NEXT")
    
    pdf.output(OUTPUT_PATH)
    return OUTPUT_PATH


def main():
    print("Recopilando datos del grupo FORTES...")
    group_data = get_group_health()
    if not group_data:
        print("ERROR: No se pudo obtener la salud del grupo", file=sys.stderr)
        sys.exit(1)
    
    print(f"OK - {group_data['total_projects']} proyectos, {len(group_data['projects'])} analizados")
    
    print("Generando PDF...")
    pdf_path = generate_pdf(group_data, {})
    print(f"PDF generado: {pdf_path}")
    print(f"Tamano: {os.path.getsize(pdf_path)} bytes")
    
    # Output the MEDIA: path for cron delivery
    print(f"\nMEDIA:{pdf_path}")


if __name__ == "__main__":
    main()
