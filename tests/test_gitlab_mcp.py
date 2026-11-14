"""mcp/gitlab-mcp: tools registradas, allowlist y arranque stdio real (sin red)."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "mcp" / "gitlab-mcp"

pytest.importorskip("fastmcp")
pytest.importorskip("gitlab")
pytest.importorskip("pandas")

# Las tools que consume gitlab/portfolio_report.py: si una desaparece, el informe se rompe.
REQUIRED_TOOLS = {
    "reporte_salud_proyecto", "analizar_rendimiento_pipelines", "analizar_merge_requests",
    "analizar_colaboradores_activos", "analizar_distribucion_codigo_y_silos",
    "analizar_tendencia_contribuciones", "detectar_ramas_stale",
    "obtener_patrones_horarios_commits", "analizar_grupo_salud",
}


@pytest.fixture(scope="module")
def server():
    sys.path.insert(0, str(SERVER_DIR))
    try:
        import server as srv
        yield srv
    finally:
        sys.path.remove(str(SERVER_DIR))
        sys.modules.pop("server", None)


def test_tools_requeridas_por_el_informe_estan_registradas(server):
    from fastmcp import Client

    async def names():
        async with Client(server.mcp) as c:
            return {t.name for t in await c.list_tools()}

    got = asyncio.run(names())
    assert REQUIRED_TOOLS <= got
    assert {"list_projects", "get_project", "get_project_members", "search_issues"} <= got


def test_allowlist_por_id_ruta_y_grupo(server, monkeypatch):
    p = SimpleNamespace(id=7, path_with_namespace="acme/sub/api")
    monkeypatch.setattr(server, "GITLAB_PROJECT_FILTER", "")
    assert server._project_allowed(p)
    for flt, ok in [("7", True), ("acme/sub/api", True), ("acme", True), ("acme/sub", True),
                    ("acm", False), ("otro/api", False), ("8", False)]:
        monkeypatch.setattr(server, "GITLAB_PROJECT_FILTER", flt)
        assert server._project_allowed(p) is ok, flt


def test_sin_token_falla_con_mensaje_claro(server, monkeypatch):
    monkeypatch.setattr(server, "GITLAB_TOKEN", "")
    with pytest.raises(ValueError, match="GITLAB_TOKEN"):
        server.get_gitlab_client()


def test_arranque_stdio_real_responde_a_initialize():
    """El proceso arranca con `python main.py` y deja stdout limpio para el protocolo."""
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "1"}}}
    proc = subprocess.run([sys.executable, str(SERVER_DIR / "main.py"), "--transport", "stdio"],
                          input=json.dumps(init) + "\n", capture_output=True, text=True,
                          timeout=90, cwd=str(ROOT))
    first = json.loads(proc.stdout.strip().splitlines()[0])
    assert first["id"] == 1 and "result" in first


def test_sesion_mcp_habla_con_el_servidor_real_con_un_solo_proceso(monkeypatch):
    """Handshake completo y varias llamadas sobre el mismo proceso (stdin abierto)."""
    sys.path.insert(0, str(ROOT))
    from gitlab import portfolio_report as pr

    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    cmd = [sys.executable, str(SERVER_DIR / "main.py"), "--transport", "stdio"]
    with pr.McpSession(command=cmd, timeout=60) as s:
        first = s.call("detectar_ramas_stale", {"project_id": "a/b"})
        pid = s._proc.pid
        second = s.call("reporte_salud_proyecto", {"project_id": "a/b"})
        assert s._proc.pid == pid                      # sin reiniciar el proceso
        assert s.call("tool_que_no_existe", {}) is None  # error de protocolo → None
    assert first and "GITLAB_TOKEN" in first           # la tool corrió y reportó el motivo
    assert second and "GITLAB_TOKEN" in second
