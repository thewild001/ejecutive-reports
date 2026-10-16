#!/usr/bin/env python3
"""
════════════════════════════════════════════════════════════════════════
  RESUMEN EJECUTIVO CONSOLIDADO — PROYECTOS FORTES EN GITLAB
════════════════════════════════════════════════════════════════════════
  Genera UN único PDF con la información agregada de todos los proyectos
  del grupo FORTES: salud, pipelines, MRs, colaboradores, tendencias,
  distribución de código, alertas y recomendaciones.

  Uso:
    python3 resumen_ejecutivo_fortes.py                  # todo el portafolio
    python3 resumen_ejecutivo_fortes.py conectus oj-uci  # subconjunto

  Salida:
    /home/fortes/reporte_portafolio_gitlab_<YYYYMMDD>.pdf
════════════════════════════════════════════════════════════════════════
"""
import subprocess
import json
import sys
import os
import re
import datetime
from fpdf import FPDF
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator


# ══════════════════════════════════════════════════════════════════════
# 1 · CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════
OUTPUT_DIR      = os.environ.get("REPORT_OUT", "/home/fortes")
OUTPUT_BASENAME = "reporte_portafolio_fortes"
CHART_TMP_DIR   = os.path.join(OUTPUT_DIR, "_charts_fortes")

AUTHOR         = "Oficina de Arquitectura y Desarrollo — Grupo FORTES"
CLASSIFICATION = "USO INTERNO — CONFIDENCIAL"
GITLAB_HOST    = "gitlab.prod.uci.cu"
GROUP_ID       = "fortes"
PERIOD_LABEL   = "Ventana de análisis: últimos 12 meses"

MCP_CMD = [
    "docker", "exec", "-i", "gitlab-analytics-mcp",
    "python3", "gitlab_analytics_mcp.py", "--transport", "stdio",
]

# Mapa display_name → project_id completo en GitLab
PROJECT_MAP = {
    "sigies-support":          "fortes/sigies2/sigies-support",
    "sigies-new-api":          "fortes/sigies2/sigies-new-api",
    "sigies-new-front":        "fortes/sigies2/sigies-new-front",
    "sigies-dashboard2":       "fortes/sigies2/sigies-dashboard2",
    "ak-mined-arch-test":      "fortes/ak-mined-arch-test",
    "akademos-sig":            "fortes/xauce-akademos/akademos-sig",
    "akademos-apk":            "fortes/xauce-akademos/akademos-apk",
    "akademos-apk-dashboards": "fortes/xauce-akademos/akademos-apk-dashboards",
    "conectus":                "fortes/xauce-akademos/conectus",
    "certifications":          "fortes/certifications",
    "oj-uci":                  "fortes/oj-uci",
    "fortes-hesk":             "fortes/fortes-hesk",
}

# ─── Paleta corporativa ───
C_NAVY   = (15, 46, 92)
C_BLUE   = (31, 78, 140)
C_GOLD   = (201, 162, 39)
C_GREEN  = (21, 128, 61)
C_AMBER  = (217, 119, 6)
C_RED    = (185, 28, 28)
C_INK    = (15, 23, 42)
C_INK2   = (71, 85, 105)
C_MUTED  = (148, 163, 184)
C_LINE   = (226, 232, 240)
C_SOFT   = (248, 250, 252)
C_WHITE  = (255, 255, 255)


def health_color(score):
    if score >= 75: return C_GREEN
    if score >= 60: return C_AMBER
    return C_RED


def health_label(score):
    if score >= 75: return "BUENA"
    if score >= 60: return "REGULAR"
    return "CRITICA"


# ══════════════════════════════════════════════════════════════════════
# 2 · CLIENTE MCP
# ══════════════════════════════════════════════════════════════════════
def mcp_call(tool_name, args=None, timeout=90):
    """Invoca una tool MCP por stdio y devuelve su texto."""
    args = args or {}
    msgs = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05",
                               "capabilities": {},
                               "clientInfo": {"name": "fortes-report",
                                              "version": "1.0"}}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": tool_name, "arguments": args}}),
    ]
    payload = "\n".join(msgs) + "\n"
    try:
        proc = subprocess.run(MCP_CMD, input=payload, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None

    for line in proc.stdout.strip().splitlines():
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("id") != 2 or "result" not in data:
            continue
        res = data["result"]
        if isinstance(res, dict) and res.get("isError"):
            return None
        if isinstance(res, dict) and "content" in res:
            for item in res["content"]:
                if item.get("type") == "text":
                    return item.get("text", "")
        return None if res is None else str(res)
    return None


TOOLS = [
    ("health",        "reporte_salud_proyecto",               lambda p: {"project_id": p}),
    ("pipelines",     "analizar_rendimiento_pipelines",       lambda p: {"project_id": p, "limit": 20}),
    ("mrs",           "analizar_merge_requests",              lambda p: {"project_id": p, "limit": 20}),
    ("collaborators", "analizar_colaboradores_activos",       lambda p: {"project_id": p, "limit": 100, "days": 365}),
    ("distribution",  "analizar_distribucion_codigo_y_silos", lambda p: {"project_id": p, "limit": 100}),
    ("trend",         "analizar_tendencia_contribuciones",    lambda p: {"project_id": p, "months": 12}),
    ("stale",         "detectar_ramas_stale",                 lambda p: {"project_id": p, "days_threshold": 60}),
    ("patterns",      "obtener_patrones_horarios_commits",    lambda p: {"project_id": p, "limit": 150}),
]


def gather_project(project_id, verbose=True):
    out = {}
    for key, tool, params in TOOLS:
        if verbose:
            print(f"      · {key}...", end=" ", flush=True)
        out[key] = mcp_call(tool, params(project_id)) or ""
        if verbose:
            print("ok" if out[key] else "sin datos")
    return out


def gather_group_health():
    """Obtiene el panorama agregado del grupo FORTES."""
    return mcp_call("analizar_grupo_salud", {
        "group_id": GROUP_ID,
        "max_proyectos": 30,
        "min_actividad_dias": 90,
    }) or ""


# ══════════════════════════════════════════════════════════════════════
# 3 · PARSERS — alineados con la salida real del MCP
# ══════════════════════════════════════════════════════════════════════
def _num(pattern, text, cast=int, flags=re.IGNORECASE | re.DOTALL):
    m = re.search(pattern, text, flags)
    if not m:
        return None
    try:
        return cast(m.group(1).strip())
    except (ValueError, IndexError):
        return None


def parse_health(text):
    r = {"score": 0, "label": "N/A", "branches": 0, "protected": 0, "stale": 0,
         "issues_open": 0, "issues_unassigned": 0,
         "mrs_open": 0, "mrs_merged": 0,
         "last_commit": "N/A", "days_since": 9999}
    if not text:
        return r

    s = _num(r'Salud:[^\d(]*\((\d+)\s*/\s*100\)', text)
    if s is not None:
        r["score"] = s
        r["label"] = health_label(s)

    bm = re.search(
        r'Ramas\*?\s*—\s*(\d+)\s*total\s*·\s*(\d+)\s*protegidas\s*·\s*(\d+)\s*stale',
        text, re.IGNORECASE)
    if bm:
        r["branches"]  = int(bm.group(1))
        r["protected"] = int(bm.group(2))
        r["stale"]     = int(bm.group(3))

    im = re.search(
        r'Issues\*?\s*—\s*(\d+)\s*abiertos?\s*·\s*(\d+)\s*sin asignar',
        text, re.IGNORECASE)
    if im:
        r["issues_open"]       = int(im.group(1))
        r["issues_unassigned"] = int(im.group(2))

    mm = re.search(
        r'MRs\*?\s*—\s*(\d+)\s*abiertos?\s*·\s*(\d+)\s*mergeados?',
        text, re.IGNORECASE)
    if mm:
        r["mrs_open"]   = int(mm.group(1))
        r["mrs_merged"] = int(mm.group(2))

    cm_section = re.search(r'Últimos commits\*(.*)$', text,
                           re.IGNORECASE | re.DOTALL)
    if cm_section:
        cm = re.search(r'(\d{4}-\d{2}-\d{2})', cm_section.group(1))
        if cm:
            r["last_commit"] = cm.group(1)
            try:
                dt = datetime.datetime.strptime(r["last_commit"], "%Y-%m-%d")
                r["days_since"] = (datetime.datetime.now() - dt).days
            except ValueError:
                pass
    return r


def parse_pipelines(text):
    r = {"success": 0, "fail": 0, "total": 0, "avg_duration": "N/A"}
    if not text:
        return r
    r["total"]   = _num(r'(\d+)\s*pipelines?\s*analizados?', text) or 0
    r["success"] = _num(r'✅\s*Éxito:\s*(\d+)\s*%', text) or 0
    r["fail"]    = _num(r'❌\s*Fallos?:\s*(\d+)\s*%', text) or 0
    dur = _num(r'Duraci[oó]n promedio:\s*(\d+)\s*min', text, cast=str)
    if dur:
        r["avg_duration"] = f"{dur} min"
    return r


def parse_mrs(text):
    r = {"merged": 0, "open": 0, "total": 0, "avg_days": 0.0, "authors": []}
    if not text:
        return r
    r["total"]  = _num(r'(\d+)\s*analizados?', text) or 0
    r["merged"] = _num(r'·\s*Mergeados:\s*(\d+)', text) or 0
    r["open"]   = _num(r'·\s*Abiertos:\s*(\d+)', text) or 0
    d = _num(r'Tiempo promedio a merge:\s*([\d.]+)\s*d[ií]as', text, cast=float)
    if d:
        r["avg_days"] = d
    block = re.search(r'\*Top autores\*(.*?)(?:\*Ramas destino\*|\Z)',
                      text, re.DOTALL)
    if block:
        for name, cnt in re.findall(r'·\s*(.+?):\s*(\d+)\s*MRs', block.group(1)):
            r["authors"].append({"name": name.strip(), "mrs": int(cnt)})
    return r


def parse_collaborators(text):
    if not text:
        return []
    people = {}
    for m in re.finditer(r'`[▬\s]+`\s*\*(.+?)\*\s*—\s*(\d+)\s*\((\d+)%\)', text):
        name, commits, pct = m.group(1).strip(), int(m.group(2)), int(m.group(3))
        people[name] = {"name": name, "commits": commits, "mrs": 0, "pct": pct}
    if not people:
        for m in re.finditer(r'\*(.+?)\*\s*—\s*(\d+)\s*\((\d+)%\)', text):
            name, commits, pct = m.group(1).strip(), int(m.group(2)), int(m.group(3))
            people[name] = {"name": name, "commits": commits, "mrs": 0, "pct": pct}
    return sorted(people.values(), key=lambda x: x["commits"], reverse=True)


def parse_distribution(text):
    r = {"bus_factor": 0, "hhi": 0.0, "top_share": 0,
         "authors": [], "level": ""}
    if not text:
        return r
    r["bus_factor"] = _num(r'Factor Bus\*?:\s*~?(\d+)', text) or 0
    h = _num(r'HHI:\s*([\d.]+)', text, cast=float)
    if h is not None:
        r["hhi"] = h
    t = _num(r'Top contribuidor\*?:\s*(\d+)%', text)
    if t is not None:
        r["top_share"] = t
    if "Alto" in text:   r["level"] = "ALTO"
    elif "Medio" in text: r["level"] = "MEDIO"
    elif "Bajo" in text:  r["level"] = "BAJO"
    for m in re.finditer(r'`[▬\s]+`\s*(.+?):\s*(\d+)\s*\(([\d.]+)%\)', text):
        r["authors"].append({"name": m.group(1).strip(),
                             "commits": int(m.group(2)),
                             "pct": float(m.group(3))})
    return r


def parse_trend(text):
    r = {"months": [], "avg": 0, "peak_month": "", "peak_count": 0,
         "top": [], "declining": False}
    if not text:
        return r
    for m in re.finditer(r'`[▬\s]+`\s*(\d{4}-\d{2}):\s*(\d+)', text):
        r["months"].append({"month": m.group(1), "count": int(m.group(2))})
    r["avg"] = _num(r'Promedio:\s*(\d+)/mes', text) or 0
    pk = re.search(r'Pico:\s*(\d{4}-\d{2})\s*\((\d+)\s*commits?\)', text)
    if pk:
        r["peak_month"] = pk.group(1)
        r["peak_count"] = int(pk.group(2))
    block = re.search(r'\*Top contribuyentes\*(.*)$', text, re.DOTALL)
    if block:
        for m in re.finditer(r'·\s*(.+?):\s*(\d+)\s*\(([\d.]+)%\)', block.group(1)):
            r["top"].append({"name": m.group(1).strip(),
                             "commits": int(m.group(2)),
                             "pct": float(m.group(3))})
    if len(r["months"]) >= 6:
        recent = sum(x["count"] for x in r["months"][-3:])
        prev   = sum(x["count"] for x in r["months"][-6:-3])
        r["declining"] = prev > 0 and recent < prev * 0.7
    return r


def parse_patterns(text):
    r = {"morning": 0, "afternoon": 0, "evening": 0, "night": 0,
         "weekday_pct": 0, "weekend_pct": 0, "peak_hour": "N/A",
         "has_late_night": False}
    if not text:
        return r

    def grab(label, emoji=None):
        pat = (rf'{emoji}\s*{label}:\s*(\d+)' if emoji else rf'{label}:\s*(\d+)')
        m = re.search(pat, text, re.IGNORECASE)
        return int(m.group(1)) if m else 0

    r["morning"]   = grab("Mañana",    "☀️")
    r["afternoon"] = grab("Tarde",     "🌤️")
    r["evening"]   = grab("Noche",     "🌆")
    r["night"]     = grab("Madrugada", "🌙")

    ph = re.search(r'Hora pico:\s*~?(\d{1,2}:\d{2})', text)
    if ph:
        r["peak_hour"] = ph.group(1)

    def grab_day(day):
        m = re.search(rf'{day}:\s*(\d+)', text, re.IGNORECASE)
        return int(m.group(1)) if m else 0

    weekend = grab_day("Sábado") + grab_day("Domingo")
    weekday = sum(grab_day(d) for d in
                  ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"])
    total = weekend + weekday
    if total:
        r["weekend_pct"] = round(weekend / total * 100)
        r["weekday_pct"] = 100 - r["weekend_pct"]

    total_p = r["morning"] + r["afternoon"] + r["evening"] + r["night"]
    if total_p:
        r["has_late_night"] = (r["night"] / total_p) * 100 > 30
    return r


def parse_group_health(text):
    """Parsea la salida de analizar_grupo_salud."""
    r = {"total_projects": 0, "analyzed": 0,
         "pipelines_ok": 0, "stale_total": 0, "issues_total": 0,
         "projects": []}
    if not text:
        return r

    for line in text.splitlines():
        if line.startswith("▸"):
            name_m = re.search(r'\*([^*]+)\*', line)
            pipe_m = re.search(r'pipelines:\s*([\d/N A—\-]+?)\s*·', line)
            branch_m = re.search(r'ramas:\s*(\d+)\s*\((\d+)\s*stale\)', line)
            issue_m = re.search(r'issues:\s*(\d+)', line)
            if not name_m:
                continue
            name = name_m.group(1).strip()
            pipes = pipe_m.group(1).strip() if pipe_m else "—"
            branches = int(branch_m.group(1)) if branch_m else 0
            stale = int(branch_m.group(2)) if branch_m else 0
            issues = int(issue_m.group(1)) if issue_m else 0

            r["projects"].append({
                "name": name, "pipelines": pipes,
                "branches": branches, "stale": stale, "issues": issues,
            })
            r["stale_total"] += stale
            r["issues_total"] += issues
            if "/" in pipes:
                try:
                    ok, tot = pipes.split("/")
                    if int(ok) == int(tot) and int(tot) > 0:
                        r["pipelines_ok"] += 1
                except ValueError:
                    pass

    pm = re.search(r'(\d+)\s*proyectos?\s*activos', text, re.IGNORECASE)
    if pm:
        r["total_projects"] = int(pm.group(1))
    r["analyzed"] = len(r["projects"])
    r["projects"].sort(key=lambda p: p["stale"], reverse=True)
    return r


# ══════════════════════════════════════════════════════════════════════
# 4 · GRÁFICOS
# ══════════════════════════════════════════════════════════════════════
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.edgecolor": "#E2E8F0",
    "axes.labelcolor": "#0F172A",
    "axes.titlecolor": "#0F2E5C",
    "xtick.color": "#94A3B8",
    "ytick.color": "#94A3B8",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})


def _ensure_chart_dir():
    os.makedirs(CHART_TMP_DIR, exist_ok=True)


def _barh(labels, values, title, filename, colors=None, fmt="{:.0f}"):
    if not labels:
        return None
    _ensure_chart_dir()
    fig, ax = plt.subplots(figsize=(7.8, max(2.0, 0.42 * len(labels) + 1.0)))
    colors = colors or ["#1F4E8C"] * len(labels)
    bars = ax.barh(labels, values, color=colors, height=0.58, edgecolor="none")
    for bar, v in zip(bars, values):
        ax.text(v, bar.get_y() + bar.get_height() / 2,
                "  " + fmt.format(v), va="center", fontsize=9, color="#0F172A")
    ax.invert_yaxis()
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.tick_params(axis="y", labelsize=9)
    ax.set_title(title, fontsize=11, fontweight="bold", loc="left", pad=8)
    ax.grid(axis="x", color="#E2E8F0", linewidth=0.5, alpha=0.7)
    ax.set_axisbelow(True)
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    path = os.path.join(CHART_TMP_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _donut(parts, colors, center_label, filename):
    if not any(parts):
        return None
    _ensure_chart_dir()
    fig, ax = plt.subplots(figsize=(3.0, 3.0))
    ax.pie(parts, colors=colors, startangle=90,
           wedgeprops=dict(width=0.38, edgecolor="white", linewidth=2))
    if center_label:
        ax.text(0, 0, str(center_label), ha="center", va="center",
                fontsize=15, fontweight="bold", color="#0F2E5C")
    ax.axis("equal")
    fig.tight_layout()
    path = os.path.join(CHART_TMP_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def build_charts(portfolio, totals):
    if not portfolio:
        return {}

    def to_hex(c): return "#%02x%02x%02x" % c

    projs = sorted(portfolio, key=lambda p: p["score"], reverse=True)
    charts = {}

    charts["health"] = _barh(
        [p["name"] for p in projs], [p["score"] for p in projs],
        "Salud por proyecto (0–100)", "health.png",
        colors=[to_hex(health_color(p["score"])) for p in projs],
    )
    charts["commits"] = _barh(
        [p["name"] for p in portfolio],
        [p["total_commits"] for p in portfolio],
        "Commits totales (últimos 12 meses)", "commits.png",
        colors=["#1F4E8C"] * len(portfolio),
    )
    charts["mrs"] = _barh(
        [p["name"] for p in portfolio],
        [p["mrs_merged"] for p in portfolio],
        "Merge Requests mergeados", "mrs.png",
        colors=["#15803D"] * len(portfolio),
    )
    charts["stale"] = _barh(
        [p["name"] for p in projs], [p["stale"] for p in projs],
        "Ramas stale por proyecto", "stale.png",
        colors=[to_hex(C_RED if p["stale"] > 10 else C_AMBER if p["stale"] > 3 else C_GREEN)
                for p in projs],
    )
    charts["alerts_donut"] = _donut(
        [totals["crit"], totals["att"], totals["info"]],
        ["#B91C1C", "#D97706", "#1F4E8C"],
        totals["crit"] + totals["att"] + totals["info"],
        "alerts_donut.png",
    )
    return charts


# ══════════════════════════════════════════════════════════════════════
# 5 · CLASE PDF — Sistema de diseño
# ══════════════════════════════════════════════════════════════════════
class PortfolioPDF(FPDF):
    MARGIN    = 15
    CONTENT_W = 180

    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.add_font("D",  "",  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        self.add_font("D",  "B", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(self.MARGIN, self.MARGIN, self.MARGIN)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_y(8)
        self.set_font("D", "", 7.5)
        self.set_text_color(*C_MUTED)
        self.set_x(self.MARGIN)
        self.cell(self.CONTENT_W / 2, 5,
                  "RESUMEN EJECUTIVO · GRUPO FORTES", align="L")
        self.cell(self.CONTENT_W / 2, 5,
                  f"Página {self.page_no()}", align="R",
                  new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*C_LINE)
        self.set_line_width(0.2)
        self.line(self.MARGIN, 15, 210 - self.MARGIN, 15)
        self.set_y(20)

    def footer(self):
        self.set_y(-13)
        self.set_font("D", "", 7)
        self.set_text_color(*C_MUTED)
        self.set_x(self.MARGIN)
        self.cell(self.CONTENT_W, 8,
                  f"{AUTHOR}  ·  {GITLAB_HOST}", align="C")
        self.set_y(-9)
        self.set_font("D", "B", 6.5)
        self.set_text_color(*C_RED)
        self.cell(self.CONTENT_W, 5, CLASSIFICATION, align="C")

    def section_title(self, number, text):
        self.ln(2)
        self.set_font("D", "B", 15)
        self.set_text_color(*C_NAVY)
        self.set_x(self.MARGIN)
        self.cell(self.CONTENT_W, 9, f"{number} · {text}",
                  new_x="LMARGIN", new_y="NEXT")
        y = self.get_y() + 1
        self.set_draw_color(*C_NAVY)
        self.set_line_width(0.5)
        self.line(self.MARGIN, y, 210 - self.MARGIN, y)
        self.set_y(y + 5)

    def sub_title(self, text, color=None):
        self.ln(1)
        self.set_font("D", "B", 10.5)
        self.set_text_color(*(color or C_BLUE))
        self.set_x(self.MARGIN)
        self.cell(self.CONTENT_W, 7, text, new_x="LMARGIN", new_y="NEXT")
        y = self.get_y()
        self.set_draw_color(*C_LINE)
        self.set_line_width(0.2)
        self.line(self.MARGIN, y, 210 - self.MARGIN, y)
        self.ln(3)

    def paragraph(self, text, size=9, color=None):
        self.set_font("D", "", size)
        self.set_text_color(*(color or C_INK))
        self.set_x(self.MARGIN)
        self.multi_cell(self.CONTENT_W, 5, text)
        self.ln(1)

    def bullet(self, text, color=None, bold_prefix=""):
        self.set_font("D", "", 9)
        self.set_text_color(*(color or C_INK))
        self.set_x(self.MARGIN + 2)
        self.cell(4, 5, "▸")
        if bold_prefix:
            self.set_font("D", "B", 9)
            self.cell(self.get_string_width(bold_prefix) + 1, 5, bold_prefix)
            self.set_font("D", "", 9)
        self.multi_cell(self.CONTENT_W - 6, 5, text)
        self.ln(0.5)

    def kpi_card(self, x, y, w, h, label, value, sub="", color=None):
        color = color or C_NAVY
        self.set_fill_color(*C_SOFT)
        self.rect(x, y, w, h, "F")
        self.set_fill_color(*color)
        self.rect(x, y, 1.1, h, "F")
        self.set_xy(x + 3.5, y + 2.5)
        self.set_font("D", "", 6.5)
        self.set_text_color(*C_INK2)
        self.cell(w - 5, 3.5, label.upper())
        self.set_xy(x + 3.5, y + 7)
        self.set_font("D", "B", 18)
        self.set_text_color(*color)
        self.cell(w - 5, 9, str(value))
        if sub:
            self.set_xy(x + 3.5, y + h - 5.5)
            self.set_font("D", "", 6.5)
            self.set_text_color(*C_INK2)
            self.cell(w - 5, 4, sub)

    def data_table(self, headers, rows, widths, aligns=None):
        aligns = aligns or (["L"] + ["R"] * (len(headers) - 1))
        self.set_fill_color(*C_NAVY)
        self.set_text_color(*C_WHITE)
        self.set_font("D", "B", 7.5)
        self.set_x(self.MARGIN)
        for h, w, a in zip(headers, widths, aligns):
            txt = ("  " + h) if a == "L" else (h + "  ")
            self.cell(w, 7, txt, align=a, fill=True)
        self.ln()
        self.set_font("D", "", 8)
        for i, row in enumerate(rows):
            fill = i % 2 == 1
            self.set_fill_color(*(C_SOFT if fill else C_WHITE))
            self.set_x(self.MARGIN)
            for val, w, a in zip(row, widths, aligns):
                self.set_text_color(*C_INK)
                txt = ("  " + str(val)) if a == "L" else (str(val) + "  ")
                self.cell(w, 6, txt, align=a, fill=fill)
            self.ln()
        y = self.get_y()
        self.set_draw_color(*C_LINE)
        self.set_line_width(0.2)
        self.line(self.MARGIN, y, 210 - self.MARGIN, y)
        self.ln(3)

    def alert_box(self, severity, title, detail, project=""):
        sev_map = {
            "CRITICO":  (C_RED,   (254, 242, 242), "CRÍTICO"),
            "ATENCION": (C_AMBER, (255, 251, 235), "ATENCIÓN"),
            "INFO":     (C_BLUE,  (239, 246, 255), "INFO"),
        }
        accent, bg, label = sev_map.get(severity, (C_BLUE, C_SOFT, severity))

        self.set_fill_color(*bg)
        x = self.MARGIN
        y = self.get_y()
        h_title = 4.5
        h_detail = 4 * max(1, (len(detail) // 90) + 1)
        h = 3 + h_title + h_detail + 2

        self.rect(x, y, self.CONTENT_W, h, "F")
        self.set_fill_color(*accent)
        self.rect(x, y, 1.1, h, "F")

        self.set_xy(x + 4, y + 2)
        self.set_font("D", "B", 6.5)
        self.set_text_color(*accent)
        self.cell(18, 4, label)

        self.set_xy(x + 22, y + 2)
        self.set_font("D", "B", 8.5)
        self.set_text_color(*C_INK)
        self.cell(0, 4, title + (f"  ·  {project}" if project else ""))

        self.set_xy(x + 4, y + 7)
        self.set_font("D", "", 8)
        self.set_text_color(*C_INK2)
        self.multi_cell(self.CONTENT_W - 6, 4, detail)
        self.set_y(y + h + 1.5)


# ══════════════════════════════════════════════════════════════════════
# 6 · AGREGACIÓN Y REGLAS DE NEGOCIO
# ══════════════════════════════════════════════════════════════════════
def subgroup_of(project_id):
    """Deriva el subgrupo visible a partir del path."""
    parts = project_id.split("/")
    if len(parts) <= 2:
        return "fortes"
    return "/".join(parts[:-1])


def build_project_metrics(name, project_id):
    raw = gather_project(project_id)

    health = parse_health(raw["health"])
    pipes  = parse_pipelines(raw["pipelines"])
    mrs    = parse_mrs(raw["mrs"])
    people = parse_collaborators(raw["collaborators"])
    dist   = parse_distribution(raw["distribution"])
    trend  = parse_trend(raw["trend"])
    patt   = parse_patterns(raw["patterns"])

    p = {
        "name":              name,
        "project_id":        project_id,
        "subgroup":          subgroup_of(project_id),
        "score":             health["score"],
        "label":             health["label"],
        "pipelines_ok":      pipes["success"],
        "pipelines_fail":    pipes["fail"],
        "pipelines_total":   pipes["total"],
        "pipelines_dur":     pipes["avg_duration"],
        "branches":          health["branches"],
        "protected":         health["protected"],
        "stale":             health["stale"],
        "issues_open":       health["issues_open"],
        "issues_unassigned": health["issues_unassigned"],
        "mrs_open":          health["mrs_open"] or mrs["open"],
        "mrs_merged":        health["mrs_merged"] or mrs["merged"],
        "mrs_avg_days":      mrs["avg_days"],
        "mrs_authors":       mrs["authors"],
        "last_commit":       health["last_commit"],
        "days_since":        health["days_since"],
        "collaborators":     people,
        "bus_factor":        dist["bus_factor"],
        "hhi":               dist["hhi"],
        "top_share":         dist["top_share"],
        "dist_level":        dist["level"],
        "trend":             trend,
        "patterns":          patt,
        "total_commits":     sum(c["commits"] for c in people),
    }
    p["alerts"], p["recommendations"] = derive_alerts(p)
    return p


def derive_alerts(p):
    alerts, recs = [], []

    if p["score"] and p["score"] < 60:
        alerts.append({"sev": "CRITICO", "title": "Salud crítica del proyecto",
                       "detail": f"Score {p['score']}/100. Requiere intervención inmediata."})
        recs.append("Convocar revisión de causas raíz y definir plan de recuperación con hitos semanales.")
    elif p["score"] and p["score"] < 75:
        alerts.append({"sev": "ATENCION", "title": "Salud regular",
                       "detail": f"Score {p['score']}/100. Existen áreas de mejora identificables."})

    if p["days_since"] > 30:
        sev = "CRITICO" if p["days_since"] > 180 else "ATENCION"
        alerts.append({"sev": sev, "title": "Proyecto inactivo",
                       "detail": f"Sin commits desde {p['last_commit']} ({p['days_since']} días)."})
        recs.append("Confirmar si el proyecto está en pausa, requiere recursos o debe archivarse.")

    if p["pipelines_total"] and p["pipelines_fail"] > 0:
        sev = "CRITICO" if p["pipelines_fail"] >= 30 else "ATENCION"
        alerts.append({"sev": sev, "title": "Fallos en CI/CD",
                       "detail": f"{p['pipelines_fail']}% de pipelines fallidos sobre {p['pipelines_total']} ejecuciones."})
        recs.append("Revisar pruebas automatizadas y estabilidad del entorno de integración.")

    if p["stale"] > 5:
        sev = "CRITICO" if p["stale"] > 20 else "ATENCION"
        alerts.append({"sev": sev, "title": "Ramas obsoletas acumuladas",
                       "detail": f"{p['stale']} de {p['branches']} ramas sin actividad >60 días."})
        recs.append("Aplicar política de poda automática post-merge.")

    if p["issues_open"] and p["issues_unassigned"] > p["issues_open"] * 0.4:
        alerts.append({"sev": "ATENCION", "title": "Issues sin asignar",
                       "detail": f"{p['issues_unassigned']} de {p['issues_open']} issues abiertos sin responsable."})
        recs.append("Asignar responsables a issues abiertos para asegurar seguimiento.")

    if p["mrs_avg_days"] > 5:
        alerts.append({"sev": "ATENCION", "title": "Lead time elevado",
                       "detail": f"Tiempo promedio a merge: {p['mrs_avg_days']:.1f} días."})
        recs.append("Reducir tamaño de MRs y asignar revisores rotativos.")
    if p["mrs_open"] > 5:
        alerts.append({"sev": "ATENCION", "title": "MRs estancados",
                       "detail": f"{p['mrs_open']} MRs abiertos. Posible cuello de botella en revisión."})

    if 0 < p["bus_factor"] <= 2:
        alerts.append({"sev": "CRITICO", "title": "Factor Bus crítico",
                       "detail": f"Solo {p['bus_factor']} desarrollador(es) concentran el conocimiento."})
        recs.append("Implementar pairing y rotación para distribuir conocimiento.")

    if p["hhi"] and p["hhi"] > 0.5:
        alerts.append({"sev": "ATENCION", "title": "Concentración de código alta",
                       "detail": f"HHI={p['hhi']:.3f} · Top contribuidor con {p['top_share']}%."})

    if p["patterns"]["has_late_night"]:
        alerts.append({"sev": "ATENCION", "title": "Riesgo de sobrecarga",
                       "detail": ">30% de commits en horario de madrugada."})
        recs.append("Revisar carga laboral y equilibrar distribución horaria del equipo.")
    if p["patterns"]["weekend_pct"] > 20:
        alerts.append({"sev": "INFO", "title": "Actividad en fin de semana",
                       "detail": f"{p['patterns']['weekend_pct']}% de commits en sábado/domingo."})

    if p["trend"].get("declining"):
        alerts.append({"sev": "ATENCION", "title": "Tendencia decreciente",
                       "detail": "Los últimos 3 meses muestran una caída >30% en commits."})
        recs.append("Reevaluar prioridades y asignación de esfuerzo del equipo.")

    return alerts, recs


def portfolio_totals(portfolio):
    unique_devs = set()
    for p in portfolio:
        for c in p["collaborators"]:
            unique_devs.add(c["name"])

    active = sum(1 for p in portfolio if p["days_since"] <= 30)
    avg_health = (round(sum(p["score"] for p in portfolio) / len(portfolio), 1)
                  if portfolio else 0)

    all_alerts = []
    for p in portfolio:
        for a in p["alerts"]:
            a2 = dict(a); a2["project"] = p["name"]
            all_alerts.append(a2)
    order = {"CRITICO": 0, "ATENCION": 1, "INFO": 2}
    all_alerts.sort(key=lambda a: order.get(a["sev"], 3))

    return {
        "projects":    len(portfolio),
        "active":      active,
        "commits":     sum(p["total_commits"] for p in portfolio),
        "mrs_merged":  sum(p["mrs_merged"] for p in portfolio),
        "mrs_open":    sum(p["mrs_open"] for p in portfolio),
        "stale_total": sum(p["stale"] for p in portfolio),
        "issues_total":sum(p["issues_open"] for p in portfolio),
        "unique_devs": len(unique_devs),
        "avg_health":  avg_health,
        "alerts":      all_alerts,
        "crit":        sum(1 for a in all_alerts if a["sev"] == "CRITICO"),
        "att":         sum(1 for a in all_alerts if a["sev"] == "ATENCION"),
        "info":        sum(1 for a in all_alerts if a["sev"] == "INFO"),
    }


def consolidated_contributors(portfolio):
    people = {}
    for p in portfolio:
        for c in p["collaborators"]:
            d = people.setdefault(c["name"], {
                "name": c["name"], "commits": 0, "mrs": 0, "projects": set()
            })
            d["commits"] += c["commits"]
            d["mrs"]     += c["mrs"]
            if c["commits"] or c["mrs"]:
                d["projects"].add(p["name"])
    out = list(people.values())
    for d in out:
        d["projects"] = len(d["projects"])
    return sorted(out, key=lambda x: (x["commits"], x["mrs"]), reverse=True)


# ══════════════════════════════════════════════════════════════════════
# 7 · COMPOSICIÓN DEL PDF
# ══════════════════════════════════════════════════════════════════════
def render_cover(pdf, totals, group):
    pdf.add_page()
    pdf.set_fill_color(*C_NAVY)
    pdf.rect(0, 0, 210, 14, "F")
    pdf.set_fill_color(*C_GOLD)
    pdf.rect(150, 0, 60, 14, "F")

    pdf.set_xy(pdf.MARGIN, 25)
    pdf.set_fill_color(*C_NAVY)
    pdf.rect(pdf.MARGIN, 25, 14, 14, "F")
    pdf.set_xy(pdf.MARGIN, 25)
    pdf.set_font("D", "B", 18)
    pdf.set_text_color(*C_WHITE)
    pdf.cell(14, 14, "F", align="C")
    pdf.set_xy(pdf.MARGIN + 18, 26)
    pdf.set_font("D", "B", 11)
    pdf.set_text_color(*C_NAVY)
    pdf.cell(100, 5, "GRUPO FORTES")
    pdf.set_xy(pdf.MARGIN + 18, 31)
    pdf.set_font("D", "", 8)
    pdf.set_text_color(*C_INK2)
    pdf.cell(100, 5, "Arquitectura y Desarrollo")

    pdf.set_xy(pdf.MARGIN, 90)
    pdf.set_font("D", "B", 9)
    pdf.set_text_color(*C_GOLD)
    pdf.cell(0, 6, "R E S U M E N   E J E C U T I V O   D E   P O R T A F O L I O")

    pdf.set_xy(pdf.MARGIN, 102)
    pdf.set_font("D", "B", 34)
    pdf.set_text_color(*C_NAVY)
    pdf.cell(0, 16, "Proyectos FORTES", new_x="LMARGIN", new_y="NEXT")

    pdf.set_xy(pdf.MARGIN, 122)
    pdf.set_fill_color(*C_GOLD)
    pdf.rect(pdf.MARGIN, 122, 22, 1.6, "F")

    pdf.set_xy(pdf.MARGIN, 130)
    pdf.set_font("D", "", 10.5)
    pdf.set_text_color(*C_INK2)
    pdf.multi_cell(140, 6,
                   f"Análisis consolidado de {totals['projects']} proyectos · "
                   f"{totals['unique_devs']} colaboradores · "
                   f"{totals['commits']} commits registrados")

    kpi_y = 165
    kpi_h = 30
    gap = 4
    n = 5
    w = (pdf.CONTENT_W - gap * (n - 1)) / n
    x0 = pdf.MARGIN
    kpis = [
        ("Proyectos",      totals["projects"],     "",                               C_NAVY),
        ("Activos",        totals["active"],       "últimos 30 días",                C_GREEN),
        ("Commits",        totals["commits"],      "",                               C_BLUE),
        ("MRs mergeados",  totals["mrs_merged"],   f"{totals['mrs_open']} abiertos", C_BLUE),
        ("Salud promedio", totals["avg_health"],   "sobre 100",                      health_color(totals["avg_health"])),
    ]
    for i, (lbl, val, sub, col) in enumerate(kpis):
        x = x0 + i * (w + gap)
        pdf.kpi_card(x, kpi_y, w, kpi_h, lbl, val, sub, col)

    pdf.set_draw_color(*C_LINE)
    pdf.set_line_width(0.3)
    pdf.line(pdf.MARGIN, 265, 210 - pdf.MARGIN, 265)
    pdf.set_xy(pdf.MARGIN, 268)
    pdf.set_font("D", "", 8)
    pdf.set_text_color(*C_INK2)
    pdf.cell(100, 5, AUTHOR)
    pdf.set_xy(pdf.MARGIN, 273)
    pdf.cell(100, 5, PERIOD_LABEL)
    pdf.set_xy(210 - pdf.MARGIN - 80, 268)
    pdf.set_font("D", "B", 8)
    pdf.set_text_color(*C_RED)
    pdf.cell(80, 5, CLASSIFICATION, align="R")
    pdf.set_xy(210 - pdf.MARGIN - 80, 273)
    pdf.set_font("D", "", 8)
    pdf.set_text_color(*C_INK2)
    pdf.cell(80, 5,
             f"Generado {datetime.datetime.now():%d/%m/%Y %H:%M}",
             align="R")


def render_exec_summary(pdf, totals):
    pdf.add_page()
    pdf.section_title("1", "Resumen Ejecutivo")

    kpi_y = pdf.get_y() + 2
    kpi_h = 26
    gap = 4
    n = 4
    w = (pdf.CONTENT_W - gap * (n - 1)) / n
    kpis = [
        ("Proyectos",      totals["projects"],              f"{totals['active']} activos",       C_NAVY),
        ("Colaboradores",  totals["unique_devs"],           "únicos en portafolio",              C_BLUE),
        ("MRs mergeados",  totals["mrs_merged"],            f"{totals['mrs_open']} abiertos",    C_GREEN),
        ("Salud promedio", f"{totals['avg_health']}/100",   "promedio ponderado",                health_color(totals["avg_health"])),
    ]
    for i, (lbl, val, sub, col) in enumerate(kpis):
        pdf.kpi_card(pdf.MARGIN + i * (w + gap), kpi_y, w, kpi_h, lbl, val, sub, col)
    pdf.set_y(kpi_y + kpi_h + 6)

    pdf.sub_title("Hallazgos clave")
    findings = [
        f"Se detectaron {totals['crit']} alertas críticas y {totals['att']} de atención. "
        f"Requieren plan de acción formal con responsables e hitos.",
        f"{totals['active']} de {totals['projects']} proyectos presentan actividad reciente "
        f"(<30 días). Los inactivos deben revisarse con sus responsables.",
    ]
    if totals["avg_health"] < 60:
        findings.append("La salud promedio del portafolio está por debajo del umbral aceptable. Requiere intervención inmediata.")
    elif totals["avg_health"] < 75:
        findings.append(f"La salud promedio del portafolio es {totals['avg_health']}/100 y requiere un plan de mejora estructurado.")
    else:
        findings.append(f"La salud promedio del portafolio ({totals['avg_health']}/100) se mantiene en rango saludable.")
    findings.append(
        f"Se acumulan {totals['stale_total']} ramas stale y {totals['issues_total']} issues abiertos en el portafolio."
    )
    for f in findings:
        pdf.bullet(f)

    pdf.ln(3)
    pdf.sub_title("Distribución de alertas")
    bar_y = pdf.get_y()
    bar_h = 12
    total_a = totals["crit"] + totals["att"] + totals["info"]
    if total_a == 0:
        pdf.paragraph("No se detectaron alertas.", color=C_GREEN)
    else:
        segs = [("CRÍTICO", totals["crit"], C_RED),
                ("ATENCIÓN", totals["att"], C_AMBER),
                ("INFO", totals["info"], C_BLUE)]
        x = pdf.MARGIN
        for label, val, color in segs:
            if val == 0: continue
            w_seg = pdf.CONTENT_W * (val / total_a)
            pdf.set_fill_color(*color)
            pdf.rect(x, bar_y, w_seg, bar_h, "F")
            pdf.set_xy(x, bar_y)
            pdf.set_font("D", "B", 9)
            pdf.set_text_color(*C_WHITE)
            if w_seg > 14:
                pdf.cell(w_seg, bar_h, f"{val}", align="C")
            x += w_seg
        pdf.set_y(bar_y + bar_h + 3)
        lx = pdf.MARGIN
        for label, val, color in segs:
            pdf.set_fill_color(*color)
            pdf.rect(lx, pdf.get_y() + 1.5, 3, 3, "F")
            pdf.set_xy(lx + 4, pdf.get_y())
            pdf.set_font("D", "", 8)
            pdf.set_text_color(*C_INK2)
            pdf.cell(40, 5, f"{label} ({val})")
            lx += 60


def render_group_overview(pdf, group):
    if not group["projects"]:
        return
    pdf.add_page()
    pdf.section_title("2", "Panorama del Grupo FORTES")

    pdf.paragraph(
        f"El grupo {GROUP_ID} aglutina {group['total_projects']} proyectos activos "
        f"en la instancia GitLab. Se muestran {group['analyzed']} con métricas consolidadas.",
        size=9, color=C_INK2)
    pdf.ln(1)

    # KPIs rápidos
    kpi_y = pdf.get_y() + 2
    kpi_h = 22
    gap = 4
    n = 4
    w = (pdf.CONTENT_W - gap * (n - 1)) / n
    kpis = [
        ("Proyectos activos",   group["total_projects"],                                     "", C_NAVY),
        ("Pipelines OK",        f"{group['pipelines_ok']}/{group['analyzed']}",              "proyectos", C_GREEN),
        ("Ramas stale (total)", group["stale_total"],                                        "", C_AMBER if group["stale_total"] else C_GREEN),
        ("Issues abiertos",     group["issues_total"],                                       "", C_AMBER if group["issues_total"] else C_GREEN),
    ]
    for i, (lbl, val, sub, col) in enumerate(kpis):
        pdf.kpi_card(pdf.MARGIN + i * (w + gap), kpi_y, w, kpi_h, lbl, val, sub, col)
    pdf.set_y(kpi_y + kpi_h + 5)

    # Tabla de proyectos del grupo
    pdf.sub_title("Estado por proyecto (vista grupo)")
    headers = ["Proyecto", "Pipelines", "Ramas", "Stale", "Issues"]
    widths  = [90, 30, 20, 20, 20]
    aligns  = ["L", "R", "R", "R", "R"]
    rows = []
    for p in group["projects"][:25]:
        rows.append([p["name"], p["pipelines"], p["branches"], p["stale"], p["issues"]])
    pdf.data_table(headers, rows, widths, aligns)


def render_portfolio_dashboard(pdf, portfolio, charts):
    pdf.add_page()
    pdf.section_title("3", "Tablero de Portafolio")

    headers = ["Proyecto", "Subgrupo", "Salud", "Commits", "MRs ↗", "MRs ●", "Pipe OK", "Stale", "Última act."]
    widths  = [35, 30, 15, 15, 13, 13, 15, 12, 32]
    aligns  = ["L", "L", "R", "R", "R", "R", "R", "R", "R"]
    rows = []
    for p in sorted(portfolio, key=lambda x: x["score"], reverse=True):
        rows.append([
            p["name"],
            p["subgroup"],
            f"{p['score']} · {p['label']}",
            p["total_commits"],
            p["mrs_merged"],
            p["mrs_open"],
            f"{p['pipelines_ok']}%" if p["pipelines_total"] else "—",
            p["stale"],
            p["last_commit"],
        ])
    pdf.data_table(headers, rows, widths, aligns)

    if charts.get("health") and os.path.exists(charts["health"]):
        pdf.sub_title("Salud comparada por proyecto")
        pdf.image(charts["health"], x=pdf.MARGIN, w=pdf.CONTENT_W)
        pdf.ln(2)

    if charts.get("commits") and os.path.exists(charts["commits"]):
        pdf.add_page()
        pdf.sub_title("Volumen de actividad (commits últimos 12 meses)")
        pdf.image(charts["commits"], x=pdf.MARGIN, w=pdf.CONTENT_W)
        pdf.ln(2)

    if charts.get("mrs") and os.path.exists(charts["mrs"]):
        pdf.sub_title("Merge Requests mergeados")
        pdf.image(charts["mrs"], x=pdf.MARGIN, w=pdf.CONTENT_W)

    if charts.get("stale") and os.path.exists(charts["stale"]):
        pdf.add_page()
        pdf.sub_title("Deuda de ramas stale")
        pdf.image(charts["stale"], x=pdf.MARGIN, w=pdf.CONTENT_W)


def render_alerts_section(pdf, totals):
    if not totals["alerts"]:
        return
    pdf.add_page()
    pdf.section_title("4", "Alertas y Riesgos Consolidados")
    pdf.paragraph(
        f"Se listan {len(totals['alerts'])} alertas ordenadas por severidad. "
        f"Las críticas requieren acción inmediata y deben registrarse en el plan de mitigación.",
        size=9, color=C_INK2)
    pdf.ln(1)

    MAX = 40
    for a in totals["alerts"][:MAX]:
        if pdf.get_y() > 250:
            pdf.add_page()
        pdf.alert_box(a["sev"], a["title"], a["detail"], a["project"])

    if len(totals["alerts"]) > MAX:
        pdf.ln(2)
        pdf.paragraph(
            f"Se muestran las primeras {MAX} alertas. Consulte el detalle por proyecto para el resto.",
            size=8, color=C_MUTED)


def render_project_cards(pdf, portfolio):
    pdf.add_page()
    pdf.section_title("5", "Fichas por Proyecto")

    for p in sorted(portfolio, key=lambda x: x["score"]):
        if pdf.get_y() > 200:
            pdf.add_page()

        y0 = pdf.get_y()
        h_head = 11
        pdf.set_fill_color(*C_NAVY)
        pdf.rect(pdf.MARGIN, y0, pdf.CONTENT_W, h_head, "F")
        pdf.set_xy(pdf.MARGIN + 3, y0 + 1)
        pdf.set_font("D", "B", 12)
        pdf.set_text_color(*C_WHITE)
        pdf.cell(120, 5.5, p["name"])
        pdf.set_xy(pdf.MARGIN + 3, y0 + 6)
        pdf.set_font("D", "", 7)
        pdf.set_text_color(200, 210, 230)
        pdf.cell(120, 4, p["project_id"])

        col = health_color(p["score"])
        badge_txt = f"{p['score']}/100 · {p['label']}"
        pdf.set_font("D", "B", 9)
        bw = pdf.get_string_width(badge_txt) + 6
        bx = 210 - pdf.MARGIN - bw - 3
        pdf.set_fill_color(*col)
        pdf.rect(bx, y0 + 2.5, bw, 6, "F")
        pdf.set_xy(bx, y0 + 2.5)
        pdf.set_text_color(*C_WHITE)
        pdf.cell(bw, 6, badge_txt, align="C")
        pdf.set_y(y0 + h_head + 3)

        mets = [
            ("Commits",         p["total_commits"]),
            ("MRs mergeados",   p["mrs_merged"]),
            ("MRs abiertos",    p["mrs_open"]),
            ("Lead time",       f"{p['mrs_avg_days']:.1f} d"),
            ("Pipelines OK",    f"{p['pipelines_ok']}%" if p["pipelines_total"] else "—"),
            ("Issues abiertos", p["issues_open"]),
            ("Bus factor",      p["bus_factor"] or "—"),
            ("Ramas stale",     f"{p['stale']}/{p['branches']}"),
        ]
        col_w = pdf.CONTENT_W / 4
        y_met = pdf.get_y()
        for i, (lbl, val) in enumerate(mets):
            cx = pdf.MARGIN + (i % 4) * col_w
            cy = y_met + (i // 4) * 11
            pdf.set_xy(cx, cy)
            pdf.set_font("D", "", 6.5)
            pdf.set_text_color(*C_MUTED)
            pdf.cell(col_w - 2, 4, lbl.upper())
            pdf.set_xy(cx, cy + 3.5)
            pdf.set_font("D", "B", 10)
            pdf.set_text_color(*C_INK)
            pdf.cell(col_w - 2, 5, str(val))
        pdf.set_y(y_met + 24)

        if p["alerts"]:
            pdf.sub_title("Alertas", color=C_RED)
            for a in p["alerts"][:4]:
                pdf.alert_box(a["sev"], a["title"], a["detail"])

        if p["recommendations"]:
            pdf.sub_title("Recomendaciones", color=C_GREEN)
            for r in p["recommendations"][:4]:
                pdf.bullet(r, color=C_INK2)

        pdf.ln(5)
        pdf.set_draw_color(*C_LINE)
        pdf.set_line_width(0.3)
        pdf.line(pdf.MARGIN, pdf.get_y(), 210 - pdf.MARGIN, pdf.get_y())
        pdf.ln(4)


def render_contributors(pdf, portfolio):
    people = consolidated_contributors(portfolio)
    if not people:
        return
    pdf.add_page()
    pdf.section_title("6", "Contribuyentes Destacados")

    top = people[:30]
    headers = ["#", "Colaborador", "Commits", "MRs", "Proyectos"]
    widths  = [12, 90, 26, 26, 26]
    aligns  = ["R", "L", "R", "R", "R"]
    rows = []
    for i, c in enumerate(top, 1):
        rows.append([i, c["name"], c["commits"], c["mrs"], c["projects"]])
    pdf.data_table(headers, rows, widths, aligns)

    pdf.ln(2)
    pdf.paragraph(
        f"Total de contribuyentes únicos en el portafolio: {len(people)}. "
        f"Se muestran los 30 de mayor actividad por commits.",
        size=8, color=C_MUTED)


def render_methodology(pdf):
    pdf.add_page()
    pdf.section_title("7", "Anexo — Metodología")

    glosario = [
        ("Salud del proyecto",
         "Índice compuesto (0–100) que pondera actividad reciente, estabilidad de CI/CD, "
         "deuda de ramas, velocidad de merge y distribución del conocimiento."),
        ("Lead time a merge",
         "Tiempo promedio transcurrido entre la apertura y el merge de un Merge Request."),
        ("Factor Bus",
         "Número mínimo de desarrolladores que concentran la mayoría del conocimiento del "
         "proyecto. Valores ≤ 2 indican riesgo crítico de continuidad."),
        ("HHI (Herfindahl-Hirschman Index)",
         "Medida de concentración de aportes. Valores > 0.5 indican alta dependencia de pocos "
         "contribuyentes."),
        ("Ramas stale",
         "Ramas sin actividad en los últimos 60 días. Acumulaciones altas sugieren deuda operativa."),
        ("Fuente de datos",
         f"GitLab Enterprise — {GITLAB_HOST}, vía herramientas MCP internas. {PERIOD_LABEL}."),
    ]
    for term, desc in glosario:
        pdf.set_font("D", "B", 9.5)
        pdf.set_text_color(*C_NAVY)
        pdf.set_x(pdf.MARGIN)
        pdf.cell(pdf.CONTENT_W, 5.5, term, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("D", "", 9)
        pdf.set_text_color(*C_INK2)
        pdf.set_x(pdf.MARGIN)
        pdf.multi_cell(pdf.CONTENT_W, 5, desc)
        pdf.ln(2)

    pdf.ln(6)
    pdf.set_draw_color(*C_LINE)
    pdf.set_line_width(0.3)
    pdf.line(pdf.MARGIN, pdf.get_y(), 210 - pdf.MARGIN, pdf.get_y())
    pdf.ln(4)
    pdf.set_font("D", "", 8)
    pdf.set_text_color(*C_MUTED)
    pdf.set_x(pdf.MARGIN)
    pdf.multi_cell(
        pdf.CONTENT_W, 4.5,
        f"Documento generado automáticamente el {datetime.datetime.now():%d/%m/%Y %H:%M}. "
        f"Para aclaraciones o solicitud de detalle por proyecto, contactar a {AUTHOR}.",
        align="C")


# ══════════════════════════════════════════════════════════════════════
# 8 · ORQUESTADOR
# ══════════════════════════════════════════════════════════════════════
def build_portfolio_pdf(portfolio, group):
    totals = portfolio_totals(portfolio)
    charts = build_charts(portfolio, totals)

    pdf = PortfolioPDF()
    render_cover(pdf, totals, group)
    render_exec_summary(pdf, totals)
    render_group_overview(pdf, group)
    render_portfolio_dashboard(pdf, portfolio, charts)
    render_alerts_section(pdf, totals)
    render_project_cards(pdf, portfolio)
    render_contributors(pdf, portfolio)
    render_methodology(pdf)

    today = datetime.datetime.now().strftime("%Y%m%d")
    out = os.path.join(OUTPUT_DIR, f"{OUTPUT_BASENAME}_{today}.pdf")
    pdf.output(out)
    return out, pdf.page_no()


# ══════════════════════════════════════════════════════════════════════
# 9 · MAIN
# ══════════════════════════════════════════════════════════════════════
def main():
    names = sys.argv[1:] or list(PROJECT_MAP.keys())
    selected = {n: PROJECT_MAP[n] for n in names if n in PROJECT_MAP}
    if not selected:
        print("No hay proyectos válidos en:", names)
        sys.exit(1)

    print(f"► Consultando panorama del grupo {GROUP_ID}...")
    group_text = gather_group_health()
    group = parse_group_health(group_text)
    print(f"  → {group['analyzed']} proyectos en el grupo\n")

    print(f"► Recolectando métricas de {len(selected)} proyecto(s)...\n")
    portfolio = []
    for i, (name, pid) in enumerate(selected.items(), 1):
        print(f"  [{i}/{len(selected)}] {name}  ({pid})")
        portfolio.append(build_project_metrics(name, pid))
        print()

    print("► Generando PDF...")
    pdf_path, pages = build_portfolio_pdf(portfolio, group)

    print(f"\n✅ PDF generado: {pdf_path}")
    print(f"   Páginas: {pages}")
    print(f"   Tamaño:  {os.path.getsize(pdf_path):,} bytes")
    print(f"\nMEDIA:{pdf_path}")


if __name__ == "__main__":
    main()