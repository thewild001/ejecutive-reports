#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# run-mcp.sh — Wrapper para GitLab MCP Server
#
# Detecta automáticamente el mejor runtime disponible:
#   1. uv  (recomendado, gestiona deps automáticamente)
#   2. python3 directo (requiere pip install -r requirements.txt)
#
# Por defecto arranca en modo stdio (para clientes MCP / docker exec).
#
# Uso:
#   ./run-mcp.sh                          # modo stdio (default)
#   ./run-mcp.sh --transport sse          # SSE en http://localhost:8000/sse
#   ./run-mcp.sh --transport sse --port 8080 --host 0.0.0.0
#
# Configuración via .env o variables de entorno:
#   GITLAB_TOKEN=...          (obligatorio)
#   GITLAB_URL=https://...    (opcional; default https://gitlab.com)
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# ── Validar GITLAB_TOKEN (server.py también falla rápido, esto es cortesía) ─
if [[ -z "${GITLAB_TOKEN:-}" && ! -f ".env" ]]; then
    echo "ERROR: GITLAB_TOKEN no está configurado y no existe .env." >&2
    echo "Creá un .env a partir de .env.example:" >&2
    echo "  cp .env.example .env" >&2
    echo "Y editá GITLAB_TOKEN con tu token." >&2
    exit 1
fi

# ── Detectar runtime disponible (prioridad: .venv -> uv -> python3) ───────────
if [[ -x ".venv/bin/python" ]]; then
    echo "[run-mcp] Runtime: .venv ($(./.venv/bin/python --version 2>&1))" >&2
    exec .venv/bin/python main.py "$@"
elif command -v uv &>/dev/null; then
    echo "[run-mcp] Runtime: uv" >&2
    exec uv run python main.py "$@"
elif command -v python3 &>/dev/null; then
    echo "[run-mcp] Runtime: python3" >&2
    exec python3 main.py "$@"
else
    echo "ERROR: No se encuentra .venv/bin/python, ni uv, ni python3." >&2
    echo "Creá el entorno: uv venv && uv pip install -r requirements.txt" >&2
    exit 1
fi
