#!/usr/bin/env python3
"""
|Tech Trends v3 — Boletín de Tendencias Tecnológicas (fpdf2 + DejaVu)
|22 temáticas dinámicas de Ingeniería de Software (SDLC completo).
|SOLO muestra categorías con datos reales — sin relleno.
|Principio rector: si no hay señales trending para una temática,
|simplemente no aparece en el boletín.

Uso: python3 trends/tech_trends_v2.py <data_semanal.json> [salida.pdf]
La identidad (empresa, unidad, logo, título) y el directorio de salida salen de
config.yaml (company.*, trends.*, output.dir); nada de eso vive en el código.

Estructura JSON esperada:
{
  "metadata": {"period": "...", "week": "...", "cutoff_date": "..."},
  "executive_summary": "...",
  "sources_count": 4,
  "total_signals": 32,
  "top_signals": [{"title":"...", "summary":"...", "source":"...", "url":"...", "maturity":"EARLY ADOPTER", "impact_score":92, "category":"IA para Desarrollo"}, ...],
  "other_signals": [{"title":"...", "category":"..."}, ...]
}
"""

import json, sys, os, datetime
from dataclasses import dataclass
from pathlib import Path

from fpdf import FPDF

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.pdfbase import find_font_dir


@dataclass(frozen=True)
class Branding:
    """Identidad del boletín: viene de config.yaml (company.*), nunca del código."""
    company: str = ""
    unit: str = ""
    issued_by: str = ""
    logo_path: str = ""
    header_title: str = "Vigilancia Tecnológica"

# ============================================================
# Paleta premium — misma que el cron validado
# ============================================================
INK       = (18, 22, 38)
INK_MUTED = (82, 86, 100)
DARK_NAVY = (16, 28, 56)
MID_NAVY  = (26, 42, 78)
GOLD      = (200, 155, 50)
GOLD_LIGHT= (245, 230, 185)
SURFACE   = (245, 247, 250)
WHITE     = (255, 255, 255)
CARD_BG   = (238, 242, 248)
LINE_MUTED= (215, 220, 228)

# Badges
BADGE_PROD = (28, 110, 60)
BADGE_EARLY= (180, 130, 30)
BADGE_EXP  = (180, 50, 40)
BADGE_NA   = (130, 135, 145)

# ============================================================
# Layout grid
# ============================================================
LM = 14
RM = 14
TM = 16
PW = 210
CW = PW - LM - RM

SEC_GAP   = 6
LH_BODY = 5.0

# ============================================================
# Mapeo de categorías del JSON → títulos de sección (ordenado)
# Las categorías que aparecen en data_semanal.json se mapean
# automáticamente a estos títulos canónicos.
# Si una categoría del JSON no está en este mapeo, se usa tal cual.
# ============================================================
TOPIC_MAP = {
    # === Planificación y Gestión ===
    "Gestion de Proyectos": "Gestión de Proyectos",
    "Gestión de Proyectos": "Gestión de Proyectos",
    "Project Management": "Gestión de Proyectos",
    "Legal/Regulación": "Gestión de Proyectos",
    "Legal": "Gestión de Proyectos",
    "Gobierno TI": "Gestión de Proyectos",
    # ---
    "Metodologías": "Metodologías de Desarrollo",
    "Metodologias": "Metodologías de Desarrollo",
    "Agile": "Metodologías de Desarrollo",
    "Scrum": "Metodologías de Desarrollo",
    "Metodología": "Metodologías de Desarrollo",
    "Kanban": "Metodologías de Desarrollo",
    # ---
    "Requisitos": "Gestión de Requisitos",
    "Requirements": "Gestión de Requisitos",
    "Analisis": "Gestión de Requisitos",
    "Análisis": "Gestión de Requisitos",

    # === Diseño y Arquitectura ===
    "Arquitectura": "Arquitectura de Software",
    "Arquitectura de Software": "Arquitectura de Software",
    "Architecture": "Arquitectura de Software",
    "Microservicios": "Arquitectura de Software",
    "Microservices": "Arquitectura de Software",
    "Patrones": "Arquitectura de Software",
    "Design Patterns": "Arquitectura de Software",
    # ---
    "UX/UI": "Diseño UX/UI",
    "UX": "Diseño UX/UI",
    "UI": "Diseño UX/UI",
    "Diseño": "Diseño UX/UI",
    "Diseno": "Diseño UX/UI",
    "Design": "Diseño UX/UI",

    # === Construcción / Desarrollo ===
    "Ingeniería de Software": "Ingeniería de Software / Programación",
    "Ingenieria de Software": "Ingeniería de Software / Programación",
    "Ingeniería": "Ingeniería de Software / Programación",
    "Programación": "Ingeniería de Software / Programación",
    "Programming": "Ingeniería de Software / Programación",
    "DevTools": "Ingeniería de Software / Programación",
    "DevTools_Ingenieria": "Ingeniería de Software / Programación",
    # ---
    "Frontend": "Desarrollo Frontend",
    "Frontend/Web": "Desarrollo Frontend",
    "Frontend_Web": "Desarrollo Frontend",
    "Web": "Desarrollo Frontend",
    # ---
    "Backend": "Desarrollo Backend",
    "Backend/APIs": "Desarrollo Backend",
    "Backend_APIs": "Desarrollo Backend",
    # ---
    "Móvil": "Desarrollo Móvil",
    "Movil": "Desarrollo Móvil",
    "Mobile": "Desarrollo Móvil",
    "iOS": "Desarrollo Móvil",
    "Android": "Desarrollo Móvil",
    # ---
    "APIs": "APIs y Servicios Web",
    "API": "APIs y Servicios Web",
    "GraphQL": "APIs y Servicios Web",
    "gRPC": "APIs y Servicios Web",
    "REST": "APIs y Servicios Web",
    "Web Services": "APIs y Servicios Web",

    # === Datos ===
    "Bases de Datos": "Bases de Datos y Persistencia",
    "Databases": "Bases de Datos y Persistencia",
    "Base de Datos": "Bases de Datos y Persistencia",
    "SQL": "Bases de Datos y Persistencia",
    "NoSQL": "Bases de Datos y Persistencia",
    # ---
    "Gestion de Datos": "Gestión de Datos y Analítica",
    "Gestión de Datos": "Gestión de Datos y Analítica",
    "Data Engineering": "Gestión de Datos y Analítica",
    "Data": "Gestión de Datos y Analítica",
    "Analítica": "Gestión de Datos y Analítica",
    "Analitica": "Gestión de Datos y Analítica",
    "BI": "Gestión de Datos y Analítica",

    # === Calidad ===
    "Calidad de Software": "Calidad de Software",
    "Quality": "Calidad de Software",
    "QA": "Calidad de Software",
    # ---
    "Pruebas de Software": "Pruebas de Software",
    "Pruebas": "Pruebas de Software",
    "Testing": "Pruebas de Software",
    "TDD": "Pruebas de Software",

    # === Operaciones ===
    "DevOps": "DevOps e Infraestructura",
    "DevOps e Infraestructura": "DevOps e Infraestructura",
    "Infraestructura": "DevOps e Infraestructura",
    "Infra": "DevOps e Infraestructura",
    "Infra_Cloud_DevOps": "DevOps e Infraestructura",
    "SRE": "DevOps e Infraestructura",
    # ---
    "CI/CD": "CI/CD y Automatización",
    "CICD": "CI/CD y Automatización",
    "Automatización": "CI/CD y Automatización",
    "Automatizacion": "CI/CD y Automatización",
    "Continuous Delivery": "CI/CD y Automatización",
    "Pipelines": "CI/CD y Automatización",

    # === Seguridad ===
    "Seguridad": "Seguridad en Desarrollo",
    "Seguridad en Desarrollo": "Seguridad en Desarrollo",
    "Ciberseguridad": "Seguridad en Desarrollo",
    "Security": "Seguridad en Desarrollo",
    "Seguridad_Privacidad": "Seguridad en Desarrollo",
    "DevSecOps": "Seguridad en Desarrollo",
    "OWASP": "Seguridad en Desarrollo",

    # === Evolución y Mantenimiento ===
    "Modernización": "Modernización y Migración",
    "Modernizacion": "Modernización y Migración",
    "Migración": "Modernización y Migración",
    "Migracion": "Modernización y Migración",
    "Legacy": "Modernización y Migración",
    "Deuda Técnica": "Modernización y Migración",
    "Refactoring": "Modernización y Migración",

    # === Transversales ===
    "IA para Desarrollo": "IA para Desarrollo",
    "IA Generativa": "IA para Desarrollo",
    "IA/ML": "IA para Desarrollo",
    "IA_LLMs_Agentes": "IA para Desarrollo",
    "LLM": "IA para Desarrollo",
    "Machine Learning": "IA para Desarrollo",
    "ML": "IA para Desarrollo",
    "Agentes IA": "IA para Desarrollo",
    # ---
    "Cloud Native": "Cloud Computing",
    "Cloud": "Cloud Computing",
    "Cloud Computing": "Cloud Computing",
    "Kubernetes": "Cloud Computing",
    "K8s": "Cloud Computing",
    "Serverless": "Cloud Computing",
    # ---
    "Hardware": "Tecnologías Emergentes",
    "WASM": "Tecnologías Emergentes",
    "WebAssembly": "Tecnologías Emergentes",
    "Edge": "Tecnologías Emergentes",
    "Quantum": "Tecnologías Emergentes",
    "Emergentes": "Tecnologías Emergentes",
    "Blockchain": "Tecnologías Emergentes",

    # === Educación ===
    "Software Educativo": "Software Educativo y Formación",
    "Educación": "Software Educativo y Formación",
    "Educacion": "Software Educativo y Formación",
    "EdTech": "Software Educativo y Formación",
    "IA_Educacion_EdTech": "Software Educativo y Formación",
    "Formación": "Software Educativo y Formación",
    "Formacion": "Software Educativo y Formación",
    "Educational Software": "Software Educativo y Formación",
    "E-learning": "Software Educativo y Formación",
}

# Orden canónico de las temáticas en el boletín (22 roles del SDLC)
TOPIC_ORDER = [
    # Planificación y Gestión
    "Gestión de Proyectos",
    "Metodologías de Desarrollo",
    "Gestión de Requisitos",
    # Diseño y Arquitectura
    "Arquitectura de Software",
    "Diseño UX/UI",
    # Construcción / Desarrollo
    "Ingeniería de Software / Programación",
    "Desarrollo Frontend",
    "Desarrollo Backend",
    "Desarrollo Móvil",
    "APIs y Servicios Web",
    # Datos
    "Bases de Datos y Persistencia",
    "Gestión de Datos y Analítica",
    # Calidad
    "Calidad de Software",
    "Pruebas de Software",
    # Operaciones
    "DevOps e Infraestructura",
    "CI/CD y Automatización",
    # Seguridad
    "Seguridad en Desarrollo",
    # Evolución y Mantenimiento
    "Modernización y Migración",
    # Transversales
    "IA para Desarrollo",
    "Cloud Computing",
    "Tecnologías Emergentes",
    # Educación
    "Software Educativo y Formación",
]


class TechTrendsPDF(FPDF):

    def __init__(self, branding: Branding | None = None):
        super().__init__('P', 'mm', 'A4')
        self.branding = branding or Branding()
        font_dir = find_font_dir()
        self.add_font("Sans", "", os.path.join(font_dir, "DejaVuSans.ttf"))
        self.add_font("Sans", "B", os.path.join(font_dir, "DejaVuSans-Bold.ttf"))
        self.add_font("Serif", "", os.path.join(font_dir, "DejaVuSerif.ttf"))
        self.add_font("Serif", "B", os.path.join(font_dir, "DejaVuSerif-Bold.ttf"))
        self.add_font("Mono", "", os.path.join(font_dir, "DejaVuSansMono.ttf"))
        self.add_font("Mono", "B", os.path.join(font_dir, "DejaVuSansMono-Bold.ttf"))
        self.set_auto_page_break(True, 18)
        self.set_margins(LM, TM, RM)

    # ========== HEADER / FOOTER ==========

    def header(self):
        if self.page_no() > 1:
            logo = self.branding.logo_path
            if logo and os.path.isfile(logo):
                self.image(logo, x=LM, y=3.5, h=10)  # solo h: conserva la proporción real

            self.set_xy(PW - RM, 4)
            self.set_font("Sans", "", 7.5)
            self.set_text_color(*INK_MUTED)
            self.cell(0, 4, f"Pag. {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")

            self.set_xy(LM, 4)
            self.set_font("Sans", "B", 7.5)
            self.set_text_color(*INK)
            self.cell(0, 4, "BOLETÍN DE TENDENCIAS TECNOLÓGICAS", align="C")
            self.set_xy(LM, 8.5)
            self.set_font("Sans", "", 7)
            self.set_text_color(*INK_MUTED)
            b = self.branding
            subtitle = " | ".join(p for p in (b.issued_by, b.company, b.header_title) if p)
            self.cell(0, 4, subtitle.upper(), align="C")

            self.set_draw_color(*GOLD)
            self.set_line_width(0.7)
            self.line(LM, 14.5, PW - RM, 14.5)
            self.set_draw_color(*LINE_MUTED)
            self.set_line_width(0.2)
            self.line(LM, 15.1, PW - RM, 15.1)
            self.ln(7)

    def footer(self):
        if self.page_no() > 1:
            self.set_y(-15)
            self.set_font("Sans", "", 6.5)
            self.set_text_color(*INK_MUTED)
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            prefix = f"{self.branding.company} - " if self.branding.company else ""
            self.cell(0, 8, f"{prefix}Generado: {ts}", align="C")

    # ========== HELPERS ==========

    def check_page_break(self, needed):
        if self.get_y() + needed > self.h - 18:
            self.add_page()

    # ========== COVER PAGE ==========

    def cover_page(self, data):
        meta = data.get("metadata", {})
        week = meta.get("week", "N/A")
        cutoff = meta.get("cutoff_date", "N/A")
        sources = data.get("sources_count", 0)
        all_signals = data.get("top_signals", []) + data.get("other_signals", [])
        signals = len(all_signals)

        self.add_page()

        self.set_fill_color(*DARK_NAVY)
        self.rect(0, 0, PW, 297, "F")

        self.set_fill_color(*GOLD)
        self.rect(0, 0, PW, 3, "F")

        self.set_y(48)
        self.set_font("Serif", "B", 24)
        self.set_text_color(*WHITE)
        self.multi_cell(0, 12.5, "BOLETÍN DE TENDENCIAS TECNOLÓGICAS", align="C")

        self.ln(6)
        self.set_font("Sans", "", 10)
        self.set_text_color(*GOLD)
        self.cell(0, 7, f"Entrega {week}", align="C", new_x="LMARGIN", new_y="NEXT")

        self.ln(2)
        self.set_font("Sans", "", 8.5)
        self.set_text_color(*WHITE)
        self.cell(0, 5.5, f"Fecha de corte: {cutoff}", align="C", new_x="LMARGIN", new_y="NEXT")

        author = data.get("author") or self.branding.issued_by or self.branding.company
        author_role = data.get("author_role") or self.branding.unit
        self.ln(1.5)
        self.set_font("Sans", "B", 9)
        self.set_text_color(*GOLD)
        self.cell(0, 5.5, f"{author}", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Sans", "", 7.5)
        self.set_text_color(*WHITE)
        self.cell(0, 5, author_role, align="C", new_x="LMARGIN", new_y="NEXT")

        self.ln(14)
        y_card = self.get_y()
        card_w = 160
        card_x = (PW - card_w) / 2
        self.set_fill_color(22, 36, 68)
        self.rect(card_x, y_card, card_w, 30, "F")

        stats = [(str(sources), "FUENTES"), (str(signals), "SEÑALES"), (str(week), "ENTREGA")]
        for i, (val, label) in enumerate(stats):
            x = card_x + 8 + i * 50
            self.set_xy(x, y_card + 5)
            self.set_font("Serif", "B", 15)
            self.set_text_color(*GOLD)
            self.cell(48, 7, val, align="C")
            self.set_xy(x, y_card + 14)
            self.set_font("Sans", "", 7)
            self.set_text_color(*WHITE)
            self.cell(48, 5, label, align="C")

        self.set_y(272)
        self.set_draw_color(*GOLD)
        self.set_line_width(1)
        self.line(30, 272, PW - 30, 272)

    # ========== SECTION TITLE ==========

    def section_title(self, num, title):
        # Solo salta página si estamos muy abajo — no fuerza add_page() siempre
        if self.get_y() + 30 > self.h - 18:
            self.add_page()
        # Posiciona cursor al inicio del área de contenido (header ya corrió)
        self.set_y(TM)
        self.set_fill_color(*MID_NAVY)
        self.rect(LM, TM, CW, 11, "F")
        self.set_fill_color(*GOLD)
        self.rect(LM, TM, 2.5, 11, "F")
        self.set_xy(LM + 6, TM + 1.8)
        self.set_font("Sans", "B", 9)
        self.set_text_color(*WHITE)
        self.cell(CW - 6, 7, f"{num}. {title}")
        self.set_y(TM + 11 + SEC_GAP)

    # ========== BODY LINE ==========

    def body_line(self, text, size=8):
        self.set_font("Sans", "", size)
        self.set_text_color(*INK)
        self.set_x(LM)
        self.multi_cell(CW, LH_BODY, text)

    # ========== SUMMARY CARD ==========

    def summary_card(self, text, size=8):
        """Renderiza texto en una card con fondo, como las signal cards."""
        # Calcular altura dinámica
        self.set_font("Sans", "", size)
        padding_top = 3
        padding_sides = 4
        line_h = 4.5
        max_w = CW - padding_sides * 2
        lines = self.multi_cell(max_w, line_h, text, dry_run=True, output="LINES")
        num_lines = len(lines) if lines else 1
        card_h = padding_top + num_lines * line_h + 3

        self.check_page_break(card_h + 6)
        y0 = self.get_y()

        # Fondo de card
        self.set_fill_color(*CARD_BG)
        self.rect(LM, y0, CW, card_h, "F")
        self.set_fill_color(*GOLD)
        self.rect(LM, y0, CW, 1, "F")

        # Texto
        self.set_xy(LM + padding_sides, y0 + padding_top)
        self.set_font("Sans", "", size)
        self.set_text_color(*INK)
        self.multi_cell(max_w, line_h, text)

        self.set_y(y0 + card_h + 2)

    # ========== SIGNAL CARD ==========

    def signal_card(self, s):
        self.check_page_break(55)
        y0 = self.get_y()

        self.set_fill_color(*CARD_BG)
        self.rect(LM, y0, CW, 50, "F")
        self.set_fill_color(*GOLD)
        self.rect(LM, y0, CW, 1, "F")

        self.set_xy(LM + 4, y0 + 2.5)
        self.set_font("Sans", "B", 8)
        self.set_text_color(*DARK_NAVY)
        title = s.get("title", "")[:120]
        self.multi_cell(CW - 8, 4.2, title)

        self.set_xy(LM + 4, y0 + 8)
        self.set_font("Sans", "", 7.5)
        self.set_text_color(*INK)
        impact = s.get("impact_score", 0)
        if impact:
            self.multi_cell(CW - 8, 4, f"Impacto: {impact}/100")
        else:
            engagement = s.get("engagement", 0)
            self.multi_cell(CW - 8, 4, f"Engagement social: {engagement:,}")

        self.set_xy(LM + 4, y0 + 13.5)
        self.set_font("Sans", "", 7)
        self.set_text_color(*INK_MUTED)
        fuente = s.get("source", "Red social")
        url = s.get("url", "")
        self.multi_cell(CW - 8, 4, f"{fuente}  |  {url}")

        maturity = s.get("maturity", "")
        ml = maturity.lower()
        if "production" in ml:
            badge_color = BADGE_PROD
            badge = "EN PRODUCCIÓN"
        elif "early" in ml:
            badge_color = BADGE_EARLY
            badge = "ADOPCIÓN TEMPRANA"
        elif "urgent" in ml or "experimental" in ml:
            badge_color = BADGE_EXP
            badge = "URGENTE" if "urgent" in ml else "EXPERIMENTAL"
        else:
            badge_color = BADGE_NA
            badge = "SIN CLASIFICAR"

        yb = y0 + 19.5
        self.set_xy(LM + 4, yb)
        self.set_font("Sans", "B", 6.5)
        self.set_text_color(*WHITE)
        self.set_fill_color(*badge_color)
        bw = self.get_string_width(badge) + 5
        self.rect(LM + 4, yb, bw, 4.5, "F")
        self.set_xy(LM + 4, yb + 0.3)
        self.cell(bw, 4, badge, align="C")

        summary = s.get("summary", "")
        if summary:
            self.set_xy(LM + 4, yb + 6)
            self.set_font("Sans", "", 7)
            self.set_text_color(*INK_MUTED)
            self.multi_cell(CW - 8, 4, summary[:250])

        self.set_y(y0 + 52)


# ============================================================
# CARGA DE DATOS
# ============================================================

def load_data(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_v2_data(data: dict) -> bool:
    """True si el JSON usa el esquema v2 (señales) y no el clásico (secciones)."""
    return any(k in data for k in ("top_signals", "other_signals", "sources_count", "total_signals"))


# ============================================================
# AGRUPACIÓN DINÁMICA DE SEÑALES POR TEMÁTICA
# ============================================================

def group_signals_by_topic(data):
    """Agrupa todas las señales (top + other) por temática usando TOPIC_MAP."""
    all_signals = data.get("top_signals", []) + data.get("other_signals", [])
    grouped = {}
    for s in all_signals:
        raw_cat = s.get("category", "").strip()
        canonical = TOPIC_MAP.get(raw_cat, raw_cat)
        if canonical not in grouped:
            grouped[canonical] = []
        grouped[canonical].append(s)
    return grouped


# ============================================================
# GENERACIÓN PRINCIPAL — SOLO TEMÁTICAS CON DATOS REALES
# ============================================================

def auto_generate_summary(data):
    """Genera resumen ejecutivo describiendo el alcance del boletín en esta edición."""
    meta = data.get("metadata", {})
    period = meta.get("period", meta.get("week", "este período"))
    total_signals = data.get("total_signals", 0)
    sources = data.get("sources_count", 0)
    all_signals = data.get("top_signals", []) + data.get("other_signals", [])

    # Agrupar señales por temática para saber qué secciones aparecen
    grouped = group_signals_by_topic(data)
    active_topics = [t for t in TOPIC_ORDER if grouped.get(t)]

    parts = []

    # Párrafo de alcance general con temáticas activas en esta edición
    if active_topics:
        if len(active_topics) > 1:
            topics_str = ", ".join(active_topics[:-1]) + " y " + active_topics[-1]
        else:
            topics_str = active_topics[0]
        parts.append(
            f"El presente boletín de Vigilancia Tecnológica correspondiente a {period} "
            f"presenta un análisis de las señales y tendencias más relevantes detectadas "
            f"en el ciclo de desarrollo de software. En esta edición se abordan "
            f"{len(active_topics)} temáticas: {topics_str}."
        )

    # Cifras del informe
    if total_signals:
        parts.append(
            f"Se analizaron un total de {total_signals} señales procedentes de "
            f"{sources} fuentes especializadas del sector."
        )

    # Señales más impactantes
    if all_signals:
        sorted_sigs = sorted(
            all_signals,
            key=lambda s: s.get("impact_score", 0) or 0,
            reverse=True
        )
        top_3 = sorted_sigs[:3]
        if top_3:
            highlights = [s.get("title", "").rstrip(".") for s in top_3]
            parts.append(
                "Entre las señales más impactantes destacan: " +
                "; ".join(highlights) + "."
            )

    return " ".join(parts) if parts else ""


def build_report(data, out_path, branding=None):
    """Maqueta el boletín v2 desde un dict ya cargado. Devuelve la ruta escrita."""
    pdf = TechTrendsPDF(branding)

    # ===== PORTADA =====
    pdf.cover_page(data)

    # ===== 1. RESUMEN EJECUTIVO — generado dinámicamente con alcance y temáticas activas =====
    exec_summary = auto_generate_summary(data)

    has_real_summary = bool(exec_summary)

    if has_real_summary:
        pdf.add_page()
        pdf.section_title("1", "RESUMEN EJECUTIVO")
        pdf.summary_card(exec_summary)
        section_num = 2
    else:
        section_num = 1  # Sin resumen → empezamos directo con temáticas

    # ===== 2-N. TEMÁTICAS CON DATOS REALES (sin relleno) =====
    grouped = group_signals_by_topic(data)

    had_topics = False

    for topic in TOPIC_ORDER:
        signals = grouped.get(topic, [])
        if not signals:
            continue  # SKIP: no hay datos para esta temática
        had_topics = True

        pdf.add_page()
        pdf.section_title(str(section_num), topic)
        pdf.body_line(f"Señales detectadas en este período: {len(signals)}", 7)
        pdf.ln(2)

        for s in signals:
            pdf.signal_card(s)

        section_num += 1

    # Si hubo resumen ejecutivo pero ninguna temática con datos
    if has_real_summary and not had_topics:
        pdf.add_page()
        pdf.set_font("Sans", "", 9)
        pdf.set_text_color(*INK_MUTED)
        pdf.cell(0, 10, "No se detectaron señales en otras temáticas en este período.",
                 align="C", new_x="LMARGIN", new_y="NEXT")

    # ===== SALIDA =====
    pdf.output(str(out_path))
    return str(out_path)


def generate_report(data_file, output_path, branding=None):
    return build_report(load_data(data_file), output_path, branding)


# ============================================================
# MAIN
# ============================================================

def branding_from_config(cfg: dict) -> Branding:
    """Identidad del boletín desde config.yaml (company.* y trends.header_title)."""
    from common.settings import REPORTS_ROOT

    company, trends = cfg.get("company", {}), cfg.get("trends", {})
    logo = company.get("logo_path") or ""
    if logo and not Path(logo).is_absolute():
        logo = str(REPORTS_ROOT / logo)
    return Branding(
        company=company.get("name", ""), unit=company.get("unit", ""),
        issued_by=company.get("issued_by", ""), logo_path=logo,
        header_title=trends.get("header_title", "Vigilancia Tecnológica"),
    )


def main() -> int:
    from common.settings import load_config

    if len(sys.argv) < 2:
        print("Uso: python3 trends/tech_trends_v2.py <data.json> [salida.pdf]", file=sys.stderr)
        return 2
    data_file = Path(sys.argv[1])
    if not data_file.is_file():
        print(f"ERROR: archivo no encontrado: {data_file}", file=sys.stderr)
        return 1

    cfg = load_config()
    if len(sys.argv) > 2:
        out_path = Path(sys.argv[2])
    else:
        prefix = cfg.get("trends", {}).get("filename_prefix", "informe_tendencias")
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        out_path = cfg["output"]["dir"] / f"{prefix}_{stamp}.pdf"
    path = generate_report(data_file, out_path, branding_from_config(cfg))
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
