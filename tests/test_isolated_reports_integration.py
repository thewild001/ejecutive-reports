"""Tests de integración para los reportes aislados portados a la suite."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gespro.detailed_pdf import (  # noqa: E402
    analyze_strengths,
    analyze_suggestions,
    analyze_weaknesses,
    build_detailed_pdf,
    project_health,
)
from gitlab.executive_pdf import (  # noqa: E402
    build_executive_pdf,
    group_rows,
    health_label,
    health_score,
)
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


def _gespro_project() -> dict:
    return {
        "name": "Portal Académico",
        "description": "Portal para gestión docente y consulta estudiantil.",
        "members": [
            {"name": "Ana Pérez", "roles": ["Desarrollo"], "total": 8, "open": 2, "closed": 6, "overdue": 1},
            {"name": "Luis Díaz", "roles": [], "total": 0, "open": 0, "closed": 0, "overdue": 0},
        ],
        "status_counts": {"Nueva": 1, "En ejecución": 1, "Cerrada": 6},
        "total": 8,
        "open": 2,
        "closed": 6,
        "overdue": 1,
        "health": 75.0,
        "analytics": {
            "windows": {"days": 30, "created_current": 4, "created_previous": 2,
                         "closed_current": 3, "closed_previous": 2},
            "velocity": 0.75,
            "member_trends": {"Ana Pérez": "creciente"},
            "bottlenecks": [],
        },
    }


def _gitlab_rows() -> list[dict]:
    today = "2026-09-14"
    high = {
        "name": "certifications",
        "path": "fortes/certifications",
        "last_activity": today,
        "branches": 5,
        "stale": 0,
        "open_issues": 0,
        "pipe_rate": 100.0,
        "web_url": "https://gitlab.example.com/fortes/certifications",
        "metrics": {
            "mrs": {"mr_open": 1, "mr_merged": 9, "mr_merge_rate": 90.0,
                    "mr_avg_review_days": 2.0},
            "activity": {"commits": 12, "active_contributors": ["Ana"],
                         "inactive_contributors": []},
            "topics": ["fastapi"],
        },
    }
    low = {
        "name": "legacy-app",
        "path": "fortes/legacy-app",
        "last_activity": "2021-10-01",
        "branches": 20,
        "stale": 19,
        "open_issues": 30,
        "pipe_rate": 10.0,
        "web_url": "https://gitlab.example.com/fortes/legacy-app",
        "metrics": {"mrs": None, "activity": None, "topics": []},
    }
    other = {
        "name": "subproject",
        "path": "sigies/support",
        "last_activity": today,
        "branches": 3,
        "stale": 1,
        "open_issues": 2,
        "pipe_rate": None,
        "web_url": "",
        "metrics": {},
    }
    return [high, low, other]


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


def test_gespro_analysis_and_pdf():
    project = _gespro_project()
    label, color = project_health(project)
    assert label == "REGULAR"
    assert color == (200, 160, 30)
    strengths = analyze_strengths(project)
    weaknesses = analyze_weaknesses(project)
    suggestions = analyze_suggestions(project)
    assert any("desempeño" in item.lower() for item in strengths)
    assert any("venc" in item.lower() for item in weaknesses)
    assert any(len(pair) == 2 for pair in suggestions)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "gespro.pdf"
        build_detailed_pdf([project], CFG, out, deltas=["Portal Académico: abiertas ↑2"])
        assert out.is_file()
        assert out.stat().st_size > 4_000


def test_gitlab_health_grouping_and_pdf():
    rows = _gitlab_rows()
    high_score = health_score(rows[0])
    low_score = health_score(rows[1])
    assert 0 <= high_score <= 100
    assert 0 <= low_score <= 100
    assert high_score > low_score
    assert health_label(high_score) in {"BUENA", "REGULAR"}
    assert health_label(low_score) == "CRÍTICA"

    grouped = group_rows(rows)
    assert "fortes" in grouped
    assert "sigies" in grouped
    assert len(grouped["fortes"]) == 2

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "gitlab.pdf"
        build_executive_pdf(rows, CFG, out, deltas=["certifications: ramas +1"])
        assert out.is_file()
        assert out.stat().st_size > 4_000


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
