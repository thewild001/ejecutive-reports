"""Informe de portafolio GitLab (formato heredado, genérico) con MCP simulado."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pypdf = pytest.importorskip("pypdf")

from common import delivery  # noqa: E402
from gitlab import gitlab_report, portfolio_report as pr  # noqa: E402

FAKE = str(ROOT / "tests" / "fake_mcp_gitlab.py")


def _cfg(tmp_path, **gitlab_over):
    gl = {"enabled": True, "base_url": "https://git.example.org",
          "group": "acme", "projects": {"alfa": "acme/sub/alfa", "beta": "acme/beta"},
          "mcp_command": [sys.executable, FAKE, "--transport", "stdio"],
          "stale_branch_days": 45, "classification": "INTERNO"}
    gl.update(gitlab_over)
    return {"company": {"name": "ACME", "unit": "Plataforma", "issued_by": "Oficina BI",
                        "locale": "es"},
            "gitlab": gl, "output": {"dir": tmp_path, "keep_last": 5},
            "export": {"formats": ["pdf"]}, "delivery": {"email": {"enabled": False}}}


def _text(path: Path) -> str:
    return "\n".join(p.extract_text() for p in pypdf.PdfReader(str(path)).pages)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("FAKE_MCP_FAIL", raising=False)
    monkeypatch.delenv(delivery.REQUIRE_DELIVERY_ENV, raising=False)


def test_pdf_usa_identidad_de_config_y_no_literales_del_codigo(tmp_path):
    cfg = _cfg(tmp_path)
    pr.configure(cfg)
    portfolio, group = pr.collect(gitlab_report.portfolio_projects(None, cfg["gitlab"]))
    out = tmp_path / "x.pdf"
    pages = pr.build_portfolio_pdf(portfolio, group, out, deltas=["alfa: salud ↑3"])
    text = _text(out)
    assert pages >= 6
    for esperado in ("ACME", "Oficina BI", "git.example.org", "INTERNO",
                     "últimos 2 días", ">45 días", "alfa", "Panorama del grupo acme", "Cambios vs ejecución anterior"):
        assert esperado in text, esperado
    assert "FORTES" not in text.upper() and "uci.cu" not in text


def test_parametros_enviados_al_mcp_respetan_la_config(tmp_path, monkeypatch):
    log = tmp_path / "args.log"
    monkeypatch.setenv("FAKE_MCP_ARGS_LOG", str(log))
    cfg = _cfg(tmp_path, window_days=2, trend_months=9, projects=["acme/beta"])
    pr.configure(cfg)
    pr.collect(gitlab_report.portfolio_projects(None, cfg["gitlab"]))
    calls = {}
    for line in log.read_text().splitlines():
        tool, args = line.split("\t")
        calls[tool] = json.loads(args)
    assert calls["analizar_colaboradores_activos"]["days"] == 2
    assert calls["analizar_tendencia_contribuciones"]["months"] == 9
    assert calls["detectar_ramas_stale"]["days_threshold"] == 45
    assert calls["analizar_grupo_salud"]["group_id"] == "acme"


def test_main_genera_pdf_y_lo_entrega(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg["delivery"] = {"email": {"enabled": True}}
    sent = {}
    monkeypatch.setattr(gitlab_report, "load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(gitlab_report, "deliver",
                        lambda pdf, c, label, report_key="": sent.update(pdf=pdf, key=report_key) or [])
    assert gitlab_report.main() == 0
    assert sent["key"] == "gitlab" and sent["pdf"].suffix == ".pdf" and sent["pdf"].exists()


def test_sin_datos_del_mcp_no_genera_ni_envia(tmp_path, monkeypatch):
    """Un MCP caído no debe producir un PDF lleno de 'CRÍTICO 0/100' enviado por correo."""
    monkeypatch.setenv("FAKE_MCP_FAIL", "1")
    cfg = _cfg(tmp_path)
    called = []
    monkeypatch.setattr(gitlab_report, "load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(gitlab_report, "deliver", lambda *a, **k: called.append(1) or [])
    assert gitlab_report.main() == pr.EXIT_NO_DATA
    assert not called and not list(tmp_path.glob("*.pdf"))


def test_descubre_proyectos_por_api_con_nombres_unicos():
    class API:
        def projects(self, group, n):
            return [{"path": "web", "path_with_namespace": "g/a/web"},
                    {"path": "web", "path_with_namespace": "g/b/web"},
                    {"path": "api", "path_with_namespace": "g/api"}]
    got = gitlab_report.portfolio_projects(API(), {"group": "g", "max_projects": 5})
    assert got == {"web": "g/a/web", "g/b/web": "g/b/web", "api": "g/api"}
