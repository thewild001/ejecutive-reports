"""Reusable PDF base class (fpdf2 + DejaVu) for executive reports."""
from __future__ import annotations

import datetime
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

INK = (33, 37, 41)
GOLD = (176, 141, 66)
GRAY = (110, 118, 129)
LIGHT = (245, 246, 248)
WHITE = (255, 255, 255)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/dejavu",
]


def find_fonts() -> tuple[str, str] | tuple[None, None]:
    """Locate DejaVu regular/bold TTF. Returns (regular, bold) or (None, None)."""
    import os

    extra = os.environ.get("REPORTS_FONTS_DIR")
    for d in ([extra] if extra else []) + FONT_CANDIDATES:
        if not d:
            continue
        reg, bold = Path(d) / "DejaVuSans.ttf", Path(d) / "DejaVuSans-Bold.ttf"
        if reg.is_file() and bold.is_file():
            return str(reg), str(bold)
    return None, None


class ReportPDF(FPDF):
    """Base PDF: header with company/unit, footer with page numbers and issuer."""

    def __init__(self, company: dict, report_title: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.company = company
        self.report_title = report_title
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(15, 22, 15)
        reg, bold = find_fonts()
        if reg:
            self.add_font("DejaVu", "", reg)
            self.add_font("DejaVu", "B", bold)
            self._font = "DejaVu"
        else:
            self._font = "helvetica"
        self.alias_nb_pages()

    # ── fpdf hooks ────────────────────────────────────────────────────────
    def header(self):
        self.set_font(self._font, "B", 9)
        self.set_text_color(*GOLD)
        self.cell(0, 5, self.company.get("name", ""), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font(self._font, "", 8)
        self.set_text_color(*GRAY)
        self.cell(0, 4, self.company.get("unit", ""), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*GOLD)
        self.set_line_width(0.4)
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.ln(4)

    def footer(self):
        self.set_y(-14)
        self.set_font(self._font, "", 7)
        self.set_text_color(*GRAY)
        issued = self.company.get("issued_by", "")
        self.cell(0, 4, f"{issued} | Página {self.page_no()}/{{nb}}", align="C")

    # ── Building blocks ───────────────────────────────────────────────────
    def cover(self, subtitle: str = "") -> None:
        self.add_page()
        self.ln(40)
        self.set_font(self._font, "B", 24)
        self.set_text_color(*INK)
        self.multi_cell(0, 12, self.report_title, align="C")
        self.ln(4)
        self.set_font(self._font, "", 13)
        self.set_text_color(*GOLD)
        if subtitle:
            self.multi_cell(0, 8, subtitle, align="C")
        self.ln(10)
        self.set_font(self._font, "", 11)
        self.set_text_color(*GRAY)
        self.multi_cell(
            0, 7,
            f"{self.company.get('name', '')}\n{self.company.get('unit', '')}\n"
            f"{datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}",
            align="C",
        )
        self.ln(20)
        self.set_font(self._font, "", 10)
        self.set_text_color(*INK)
        self.multi_cell(0, 6, self.company.get("issued_by", ""), align="C")

    def section(self, title: str) -> None:
        self.ln(3)
        self.set_font(self._font, "B", 13)
        self.set_text_color(*GOLD)
        self.cell(0, 8, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*INK)

    def para(self, text: str, size: int = 10) -> None:
        self.set_font(self._font, "", size)
        self.set_text_color(*INK)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def bullet(self, text: str) -> None:
        self.set_font(self._font, "", 10)
        x = self.get_x()
        self.cell(5, 5.5, "-")
        self.multi_cell(0, 5.5, text)
        self.set_x(x)

    def kv_row(self, label: str, value: str) -> None:
        self.set_font(self._font, "B", 10)
        self.cell(70, 6, label)
        self.set_font(self._font, "", 10)
        self.cell(0, 6, value, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def table(self, headers: list[str], rows: list[list[str]], widths: list[float] | None = None) -> None:
        if not widths:
            usable = self.w - self.l_margin - self.r_margin
            widths = [usable / len(headers)] * len(headers)
        self.set_font(self._font, "B", 9)
        self.set_fill_color(*LIGHT)
        self.set_text_color(*INK)
        for h, w in zip(headers, widths):
            self.cell(w, 7, str(h), border=1, fill=True, align="C")
        self.ln()
        self.set_font(self._font, "", 8.5)
        fill = False
        for row in rows:
            self.set_fill_color(*(WHITE if not fill else LIGHT))
            for cell, w in zip(row, widths):
                self.cell(w, 6, str(cell), border=1, fill=True, align="C")
            self.ln()
            fill = not fill
        self.ln(2)

    def card(self, title: str, body: str) -> None:
        self.set_fill_color(*LIGHT)
        self.set_draw_color(*GOLD)
        self.set_font(self._font, "B", 10)
        y0 = self.get_y()
        self.multi_cell(0, 6, title, border=0, fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font(self._font, "", 9.5)
        self.multi_cell(0, 5, body, border=0, fill=True)
        y1 = self.get_y()
        self.rect(self.l_margin, y0, self.w - self.l_margin - self.r_margin, y1 - y0)
        self.ln(3)
