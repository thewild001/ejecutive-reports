"""Informe de estado GESPRO (formato heredado, genérico) con Redmine simulado."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
pypdf = pytest.importorskip("pypdf")

from gespro import gespro_report  # noqa: E402


class FakeRM:
    def project(self, pid):
        return {"name": f"Portal {pid}", "description": "Proyecto de prueba"}

    def memberships(self, pid):
        return [{"user": {"id": 1, "name": "Ana Pérez"}, "roles": [{"name": "Jefe"}]},
                {"user": {"id": 2, "name": "Luis Gómez"}, "roles": [{"name": "Dev"}]}]

    def issues(self, pid, limit=200):
        st = lambda n: {"name": n}  # noqa: E731
        return [{"status": st("Nueva"), "assigned_to": {"id": 1}, "due_date": "2020-01-01"},
                {"status": st("Ejecución"), "assigned_to": {"id": 1}},
                {"status": st("Cerrada"), "assigned_to": {"id": 2}},
                {"status": st("Nueva"), "assigned_to": None}]


def _cfg(tmp_path):
    return {"company": {"name": "ACME", "unit": "Plataforma", "issued_by": "BI"},
            "gespro": {"base_url": "https://pm.example.org", "mode": "status",
                       "closed_status_names": ["cerrada"], "system_name": "PM"},
            "output": {"dir": tmp_path}}


def test_pdf_estado_usa_identidad_de_config(tmp_path):
    cfg = _cfg(tmp_path)
    projects = [gespro_report.collect(FakeRM(), pid, {"cerrada"}, 30) for pid in (1, 2)]
    assert projects[0]["open_by_status"] == {"Nueva": 2, "Ejecución": 1}
    out = tmp_path / "e.pdf"
    gespro_report.build_pdf(projects, cfg, out)
    text = "\n".join(p.extract_text() for p in pypdf.PdfReader(str(out)).pages)
    for esperado in ("ACME", "pm.example.org", "Plataforma", "Fortalezas", "Debilidades",
                     "3. Resumen Ejecutivo Consolidado", "Recomendaciones para ACME",
                     "Ana Pérez", "tareas en estado inicial"):
        assert esperado in text, esperado
    assert "FORTES" not in text.upper() and "GESPRO" not in text


def test_modo_detallado_sigue_disponible(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["gespro"]["mode"] = "detailed"
    projects = [gespro_report.collect(FakeRM(), 1, {"cerrada"}, 30)]
    out = tmp_path / "d.pdf"
    gespro_report.build_pdf(projects, cfg, out)
    assert out.stat().st_size > 1000
