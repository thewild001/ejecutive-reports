"""Boletín premium de tendencias tecnológicas (esquema v2).

Usa el mapping canónico de temáticas del script aislado, pero parametriza
fuentes, logo, autoría y salida mediante la configuración común de REPORTS.
"""
from __future__ import annotations

import datetime
from pathlib import Path

from fpdf.enums import XPos, YPos

from common.pdfbase import ReportPDF
from common.themes import get_theme

BADGE_PROD = (28, 110, 60)
BADGE_EARLY = (180, 130, 30)
BADGE_EXP = (180, 50, 40)
BADGE_NA = (130, 135, 145)

TOPIC_MAP = {
    "Gestion de Proyectos": "Gestión de Proyectos",
    "Gestión de Proyectos": "Gestión de Proyectos",
    "Project Management": "Gestión de Proyectos",
    "Legal/Regulación": "Gestión de Proyectos",
    "Legal": "Gestión de Proyectos",
    "Gobierno TI": "Gestión de Proyectos",
    "Metodologías": "Metodologías de Desarrollo",
    "Metodologias": "Metodologías de Desarrollo",
    "Agile": "Metodologías de Desarrollo",
    "Scrum": "Metodologías de Desarrollo",
    "Metodología": "Metodologías de Desarrollo",
    "Kanban": "Metodologías de Desarrollo",
    "Requisitos": "Gestión de Requisitos",
    "Requirements": "Gestión de Requisitos",
    "Analisis": "Gestión de Requisitos",
    "Análisis": "Gestión de Requisitos",
    "Arquitectura": "Arquitectura de Software",
    "Arquitectura de Software": "Arquitectura de Software",
    "Architecture": "Arquitectura de Software",
    "Microservicios": "Arquitectura de Software",
    "Microservices": "Arquitectura de Software",
    "Patrones": "Arquitectura de Software",
    "Design Patterns": "Arquitectura de Software",
    "UX/UI": "Diseño UX/UI",
    "UX": "Diseño UX/UI",
    "UI": "Diseño UX/UI",
    "Diseño": "Diseño UX/UI",
    "Diseno": "Diseño UX/UI",
    "Design": "Diseño UX/UI",
    "Ingeniería de Software": "Ingeniería de Software / Programación",
    "Ingenieria de Software": "Ingeniería de Software / Programación",
    "Ingeniería": "Ingeniería de Software / Programación",
    "Programación": "Ingeniería de Software / Programación",
    "Programming": "Ingeniería de Software / Programación",
    "DevTools": "Ingeniería de Software / Programación",
    "DevTools_Ingenieria": "Ingeniería de Software / Programación",
    "Frontend": "Desarrollo Frontend",
    "Frontend/Web": "Desarrollo Frontend",
    "Frontend_Web": "Desarrollo Frontend",
    "Web": "Desarrollo Frontend",
    "Backend": "Desarrollo Backend",
    "Backend/APIs": "Desarrollo Backend",
    "Backend_APIs": "Desarrollo Backend",
    "Móvil": "Desarrollo Móvil",
    "Movil": "Desarrollo Móvil",
    "Mobile": "Desarrollo Móvil",
    "iOS": "Desarrollo Móvil",
    "Android": "Desarrollo Móvil",
    "APIs": "APIs y Servicios Web",
    "API": "APIs y Servicios Web",
    "GraphQL": "APIs y Servicios Web",
    "gRPC": "APIs y Servicios Web",
    "REST": "APIs y Servicios Web",
    "Web Services": "APIs y Servicios Web",
    "Bases de Datos": "Bases de Datos y Persistencia",
    "Databases": "Bases de Datos y Persistencia",
    "Base de Datos": "Bases de Datos y Persistencia",
    "SQL": "Bases de Datos y Persistencia",
    "NoSQL": "Bases de Datos y Persistencia",
    "Gestion de Datos": "Gestión de Datos y Analítica",
    "Gestión de Datos": "Gestión de Datos y Analítica",
    "Data Engineering": "Gestión de Datos y Analítica",
    "Data": "Gestión de Datos y Analítica",
    "Analítica": "Gestión de Datos y Analítica",
    "Analitica": "Gestión de Datos y Analítica",
    "BI": "Gestión de Datos y Analítica",
    "Calidad de Software": "Calidad de Software",
    "Quality": "Calidad de Software",
    "QA": "Calidad de Software",
    "Pruebas de Software": "Pruebas de Software",
    "Pruebas": "Pruebas de Software",
    "Testing": "Pruebas de Software",
    "TDD": "Pruebas de Software",
    "DevOps": "DevOps e Infraestructura",
    "DevOps e Infraestructura": "DevOps e Infraestructura",
    "Infraestructura": "DevOps e Infraestructura",
    "Infra": "DevOps e Infraestructura",
    "Infra_Cloud_DevOps": "DevOps e Infraestructura",
    "SRE": "DevOps e Infraestructura",
    "CI/CD": "CI/CD y Automatización",
    "CICD": "CI/CD y Automatización",
    "Automatización": "CI/CD y Automatización",
    "Automatizacion": "CI/CD y Automatización",
    "Continuous Delivery": "CI/CD y Automatización",
    "Pipelines": "CI/CD y Automatización",
    "Seguridad": "Seguridad en Desarrollo",
    "Seguridad en Desarrollo": "Seguridad en Desarrollo",
    "Ciberseguridad": "Seguridad en Desarrollo",
    "Security": "Seguridad en Desarrollo",
    "Seguridad_Privacidad": "Seguridad en Desarrollo",
    "DevSecOps": "Seguridad en Desarrollo",
    "OWASP": "Seguridad en Desarrollo",
    "Modernización": "Modernización y Migración",
    "Modernizacion": "Modernización y Migración",
    "Migración": "Modernización y Migración",
    "Migracion": "Modernización y Migración",
    "Legacy": "Modernización y Migración",
    "Deuda Técnica": "Modernización y Migración",
    "Refactoring": "Modernización y Migración",
    "IA para Desarrollo": "IA para Desarrollo",
    "IA Generativa": "IA para Desarrollo",
    "IA/ML": "IA para Desarrollo",
    "IA_LLMs_Agentes": "IA para Desarrollo",
    "LLM": "IA para Desarrollo",
    "Machine Learning": "IA para Desarrollo",
    "ML": "IA para Desarrollo",
    "Agentes IA": "IA para Desarrollo",
    "Cloud Native": "Cloud Computing",
    "Cloud": "Cloud Computing",
    "Cloud Computing": "Cloud Computing",
    "Kubernetes": "Cloud Computing",
    "K8s": "Cloud Computing",
    "Serverless": "Cloud Computing",
    "Hardware": "Tecnologías Emergentes",
    "WASM": "Tecnologías Emergentes",
    "WebAssembly": "Tecnologías Emergentes",
    "Edge": "Tecnologías Emergentes",
    "Quantum": "Tecnologías Emergentes",
    "Emergentes": "Tecnologías Emergentes",
    "Blockchain": "Tecnologías Emergentes",
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

TOPIC_ORDER = [
    "Gestión de Proyectos",
    "Metodologías de Desarrollo",
    "Gestión de Requisitos",
    "Arquitectura de Software",
    "Diseño UX/UI",
    "Ingeniería de Software / Programación",
    "Desarrollo Frontend",
    "Desarrollo Backend",
    "Desarrollo Móvil",
    "APIs y Servicios Web",
    "Bases de Datos y Persistencia",
    "Gestión de Datos y Analítica",
    "Calidad de Software",
    "Pruebas de Software",
    "DevOps e Infraestructura",
    "CI/CD y Automatización",
    "Seguridad en Desarrollo",
    "Modernización y Migración",
    "IA para Desarrollo",
    "Cloud Computing",
    "Tecnologías Emergentes",
    "Software Educativo y Formación",
]


def is_premium_data(data: dict) -> bool:
    return any(key in data for key in ("top_signals", "other_signals", "sources_count", "total_signals"))


def group_signals_by_topic(data: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for signal in data.get("top_signals", []) + data.get("other_signals", []):
        raw = str(signal.get("category", "")).strip()
        canonical = TOPIC_MAP.get(raw, raw or "Sin clasificar")
        grouped.setdefault(canonical, []).append(signal)
    return grouped


def auto_generate_summary(data: dict) -> str:
    meta = data.get("metadata", {})
    period = meta.get("period") or meta.get("week") or "este período"
    total_signals = int(data.get("total_signals", 0))
    sources = int(data.get("sources_count", 0))
    signals = data.get("top_signals", []) + data.get("other_signals", [])
    grouped = group_signals_by_topic(data)
    active_topics = [topic for topic in TOPIC_ORDER if grouped.get(topic)]

    parts: list[str] = []
    if active_topics:
        topics = ", ".join(active_topics[:-1]) + f" y {active_topics[-1]}" if len(active_topics) > 1 else active_topics[0]
        parts.append(
            f"El presente boletín de Vigilancia Tecnológica correspondiente a {period} "
            f"presenta {len(active_topics)} temáticas activas: {topics}."
        )
    if total_signals:
        parts.append(f"Se analizaron un total de {total_signals} señales procedentes de {sources} fuentes especializadas.")
    if signals:
        highlights = sorted(signals, key=lambda s: s.get("impact_score", 0) or 0, reverse=True)[:3]
        parts.append("Entre las señales más impactantes destacan: " + "; ".join(s.get("title", "").rstrip(".") for s in highlights) + ".")
    return " ".join(parts)


class PremiumTrendsPDF(ReportPDF):
    """Layout premium con portada oscura, grilla y tarjetas de señales."""

    def header(self):
        if self.page_no() == 1:
            return
        logo_path = self.company.get("logo_path") or ""
        if logo_path and Path(logo_path).is_file():
            self.image(logo_path, x=self.l_margin, y=3.5, h=10)
        self.set_xy(self.l_margin, 5)
        self.set_font(self._font, "B", 8)
        self.set_text_color(*self._theme["ink"])
        self.cell(0, 4, self.report_title, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font(self._font, "", 7)
        self.set_text_color(*self._theme["gray"])
        self.cell(0, 4, f"{self.company.get('issued_by', '')} | {self.company.get('unit', '')}", align="C")
        self.set_draw_color(*self._theme["accent"])
        self.set_line_width(0.7)
        self.line(self.l_margin, 15, self.w - self.r_margin, 15)
        self.ln(7)

    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-14)
        self.set_font(self._font, "", 6.5)
        self.set_text_color(*self._theme["gray"])
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M UTC")
        self.cell(0, 8, f"{self.company.get('issued_by', '')} — Generado: {timestamp}", align="C")

    def premium_cover(self, data: dict) -> None:
        meta = data.get("metadata", {})
        week = meta.get("week", "N/A")
        cutoff = meta.get("cutoff_date", "N/A")
        sources = data.get("sources_count", 0)
        signals = data.get("total_signals", len(data.get("top_signals", [])) + len(data.get("other_signals", [])))
        ink = self._theme["ink"]
        accent = self._theme["accent"]
        white = self._theme["white"]

        self.add_page()
        self.set_fill_color(*ink)
        self.rect(0, 0, self.w, self.h, "F")
        self.set_fill_color(*accent)
        self.rect(0, 0, self.w, 3, "F")

        self.set_y(48)
        self.set_font(self._font, "B", 24)
        self.set_text_color(*white)
        self.multi_cell(0, 12.5, self.report_title, align="C")
        self.ln(6)
        self.set_font(self._font, "", 10)
        self.set_text_color(*accent)
        self.cell(0, 7, f"Entrega {week}", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font(self._font, "", 8.5)
        self.set_text_color(*white)
        self.cell(0, 5.5, f"Fecha de corte: {cutoff}", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        author = data.get("author") or self.company.get("issued_by", "")
        author_role = data.get("author_role") or self.company.get("unit", "")
        self.ln(1.5)
        self.set_font(self._font, "B", 9)
        self.set_text_color(*accent)
        self.cell(0, 5.5, author, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font(self._font, "", 7.5)
        self.set_text_color(*white)
        self.cell(0, 5, author_role, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.ln(14)
        card_w = 160
        card_x = (self.w - card_w) / 2
        y_card = self.get_y()
        self.set_fill_color(min(255, ink[0] + 8), min(255, ink[1] + 8), min(255, ink[2] + 12))
        self.rect(card_x, y_card, card_w, 30, "F")
        stats = [(str(sources), "FUENTES"), (str(signals), "SEÑALES"), (str(week), "ENTREGA")]
        for index, (value, label) in enumerate(stats):
            x = card_x + 8 + index * 50
            self.set_xy(x, y_card + 5)
            self.set_font(self._font, "B", 15)
            self.set_text_color(*accent)
            self.cell(48, 7, value, align="C")
            self.set_xy(x, y_card + 14)
            self.set_font(self._font, "", 7)
            self.set_text_color(*white)
            self.cell(48, 5, label, align="C")

        self.set_y(272)
        self.set_draw_color(*accent)
        self.set_line_width(1)
        self.line(30, 272, self.w - 30, 272)

    def premium_section(self, number: int, title: str) -> None:
        if self.get_y() + 30 > self.h - 18:
            self.add_page()
        self.set_y(18)
        self.set_fill_color(*self._theme["ink"])
        self.rect(self.l_margin, 18, self.w - self.l_margin - self.r_margin, 11, "F")
        self.set_fill_color(*self._theme["accent"])
        self.rect(self.l_margin, 18, 2.5, 11, "F")
        self.set_xy(self.l_margin + 6, 19.8)
        self.set_font(self._font, "B", 9)
        self.set_text_color(*self._theme["white"])
        self.cell(self.w - self.l_margin - self.r_margin - 6, 7, f"{number}. {title}")
        self.set_y(32)

    def summary_card(self, text: str) -> None:
        self.set_font(self._font, "", 8)
        self.set_fill_color(*self._theme["light"])
        y0 = self.get_y()
        lines = self.multi_cell(self.w - self.l_margin - self.r_margin - 8, 4.5, text,
                                dry_run=True, output="LINES")
        card_h = 3 + max(1, len(lines)) * 4.5 + 3
        if y0 + card_h > self.h - 18:
            self.add_page()
            y0 = self.get_y()
        self.rect(self.l_margin, y0, self.w - self.l_margin - self.r_margin, card_h, "F")
        self.set_fill_color(*self._theme["accent"])
        self.rect(self.l_margin, y0, self.w - self.l_margin - self.r_margin, 1, "F")
        self.set_xy(self.l_margin + 4, y0 + 3)
        self.set_text_color(*self._theme["ink"])
        self.multi_cell(self.w - self.l_margin - self.r_margin - 8, 4.5, text)
        self.set_y(y0 + card_h + 3)

    def signal_card(self, signal: dict) -> None:
        card_h = 50
        if self.get_y() + card_h > self.h - 18:
            self.add_page()
        y0 = self.get_y()
        width = self.w - self.l_margin - self.r_margin
        self.set_fill_color(*self._theme["light"])
        self.rect(self.l_margin, y0, width, card_h, "F")
        self.set_fill_color(*self._theme["accent"])
        self.rect(self.l_margin, y0, width, 1, "F")

        self.set_xy(self.l_margin + 4, y0 + 2.5)
        self.set_font(self._font, "B", 8)
        self.set_text_color(*self._theme["ink"])
        self.multi_cell(width - 8, 4.2, str(signal.get("title", ""))[:120])

        self.set_xy(self.l_margin + 4, y0 + 8)
        self.set_font(self._font, "", 7.5)
        impact = signal.get("impact_score", 0)
        metric = f"Impacto: {impact}/100" if impact else f"Engagement social: {signal.get('engagement', 0):,}"
        self.multi_cell(width - 8, 4, metric)

        self.set_xy(self.l_margin + 4, y0 + 13.5)
        self.set_font(self._font, "", 7)
        self.set_text_color(*self._theme["gray"])
        self.multi_cell(width - 8, 4, f"{signal.get('source', 'Fuente')}  |  {signal.get('url', '')}")

        maturity = str(signal.get("maturity", "")).lower()
        if "production" in maturity:
            color, badge = BADGE_PROD, "EN PRODUCCIÓN"
        elif "early" in maturity:
            color, badge = BADGE_EARLY, "ADOPCIÓN TEMPRANA"
        elif "urgent" in maturity or "experimental" in maturity:
            color, badge = BADGE_EXP, "URGENTE" if "urgent" in maturity else "EXPERIMENTAL"
        else:
            color, badge = BADGE_NA, "SIN CLASIFICAR"
        y_badge = y0 + 19.5
        self.set_xy(self.l_margin + 4, y_badge)
        self.set_font(self._font, "B", 6.5)
        self.set_text_color(*self._theme["white"])
        self.set_fill_color(*color)
        badge_w = self.get_string_width(badge) + 5
        self.rect(self.l_margin + 4, y_badge, badge_w, 4.5, "F")
        self.cell(badge_w, 4, badge, align="C")

        summary = str(signal.get("summary", ""))
        if summary:
            self.set_xy(self.l_margin + 4, y_badge + 6)
            self.set_font(self._font, "", 7)
            self.set_text_color(*self._theme["gray"])
            self.multi_cell(width - 8, 4, summary[:250])
        self.set_y(y0 + card_h + 2)


def build_premium_pdf(data: dict, cfg: dict, out_path: Path) -> None:
    title = cfg.get("trends", {}).get("header_title", "Vigilancia Tecnológica")
    pdf = PremiumTrendsPDF(
        cfg["company"],
        title,
        theme=get_theme(cfg.get("ui", {}).get("theme")),
    )
    pdf.premium_cover(data)

    summary = (data.get("executive_summary") or "").strip() or auto_generate_summary(data)
    section = 1
    if summary:
        pdf.add_page()
        pdf.premium_section(section, "RESUMEN EJECUTIVO")
        pdf.summary_card(summary)
        section += 1

    grouped = group_signals_by_topic(data)
    rendered = 0
    for topic in TOPIC_ORDER:
        signals = grouped.get(topic, [])
        if not signals:
            continue
        pdf.add_page()
        pdf.premium_section(section, topic)
        pdf.para(f"Señales detectadas en este período: {len(signals)}", size=7)
        for signal in signals:
            pdf.signal_card(signal)
        section += 1
        rendered += 1

    if summary and not rendered:
        pdf.add_page()
        pdf.set_font(pdf._font, "", 9)
        pdf.set_text_color(*pdf._theme["gray"])
        pdf.cell(0, 10, "No se detectaron señales en otras temáticas en este período.",
                 align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.output(str(out_path))
