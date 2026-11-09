"""Tests de integración para los reportes aislados portados a la suite."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trends.tech_trends_v2 import (  # noqa: E402
    auto_generate_summary,
    branding_from_config,
    build_report,
    group_signals_by_topic,
    is_v2_data,
)
from trends.trends_report import build_pdf as build_trends_pdf  # noqa: E402


CFG = {
    "company": {
        "name": "ACME",
        "unit": "Desarrollo",
        "issued_by": "Grupo BI",
        "logo_path": "",
        "locale": "es",
    },
    "ui": {"theme": "corporativo"},
    "trends": {"header_title": "Vigilancia Tecnológica"},
}


def _premium_data() -> dict:
    return {
        "metadata": {"week": "2026-W38", "period": "Semana 38", "cutoff_date": "2026-09-14"},
        "sources_count": 4,
        "total_signals": 3,
        "top_signals": [
            {"title": "Agentes para desarrollo", "summary": "Automatizan tareas de programación.",
             "source": "InfoQ", "url": "https://example.com/ia", "category": "IA para Desarrollo",
             "maturity": "EARLY ADOPTER", "impact_score": 92},
            {"title": "Pipelines reproducibles", "summary": "Estandarización del delivery.",
             "source": "CNCF", "url": "https://example.com/cicd", "category": "DevOps",
             "maturity": "PRODUCTION", "impact_score": 88},
        ],
        "other_signals": [
            {"title": "Pruebas contractuales", "summary": "Contratos consumidor-proveedor.",
             "source": "Blog", "url": "https://example.com/testing", "category": "Testing",
             "maturity": "EXPERIMENTAL", "impact_score": 76},
        ],
    }


def test_trends_premium_grouping_summary_and_pdf():
    data = _premium_data()
    assert is_v2_data(data)
    grouped = group_signals_by_topic(data)
    assert "IA para Desarrollo" in grouped
    assert "DevOps e Infraestructura" in grouped
    assert "Pruebas de Software" in grouped
    assert all(grouped[key] for key in grouped)

    summary = auto_generate_summary(data)
    assert "3 señales" in summary or "3 señales" in summary.replace("signals", "señales")
    assert "Agentes para desarrollo" in summary
    assert "Semana 38" in summary

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "trends.pdf"
        build_report(data, out, branding_from_config(CFG))
        assert out.is_file()
        assert out.stat().st_size > 4_000


def test_trends_branding_viene_de_config_y_no_del_codigo():
    """Genericidad: el boletín muestra la empresa de config y ninguna fija en código."""
    from pypdf import PdfReader

    cfg = {**CFG, "company": {**CFG["company"], "name": "EmpresaPrueba", "issued_by": "Equipo X"}}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "t.pdf"
        build_report(_premium_data(), out, branding_from_config(cfg))
        text = "\n".join(p.extract_text() for p in PdfReader(str(out)).pages)
    assert "EmpresaPrueba" in text and "Equipo X" in text
    for literal in ("FORTES", "UCI"):
        assert literal not in text


def test_trends_report_supports_classic_and_premium_data():
    premium = _premium_data()
    classic = {
        "periodo": "Quincena de prueba",
        "resumen_ejecutivo": "Resumen clásico.",
        "secciones": [{"titulo": "General", "items": [
            {"nombre": "Tema", "detalle": "Detalle", "impacto": "alto"},
        ]}],
        "fuentes": ["https://example.com"],
    }
    with tempfile.TemporaryDirectory() as tmp:
        premium_out = Path(tmp) / "premium.pdf"
        classic_out = Path(tmp) / "classic.pdf"
        build_trends_pdf(premium, CFG, premium_out)
        build_trends_pdf(classic, CFG, classic_out)
        assert premium_out.is_file() and premium_out.stat().st_size > 4_000
        assert classic_out.is_file() and classic_out.stat().st_size > 2_000


def main() -> int:
    tests = [value for name, value in globals().items()
             if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"{len(tests)}/{len(tests)} tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
