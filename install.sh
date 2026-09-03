#!/bin/bash
# Instalación local con uv + entorno virtual.
# Uso: ./install.sh
set -e
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "Instalando uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt

[ -f .env ] || cp .env.example .env
[ -f trends/trends_data.json ] || cp trends/trends_data.example.json trends/trends_data.json

echo
echo "Listo. Edita .env y config.yaml, luego ejecuta por ejemplo:"
echo "  ./run.sh gespro"
