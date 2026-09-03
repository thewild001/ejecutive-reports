#!/bin/bash
# Ejecuta uno de los reportes con el entorno virtual local.
# Uso: ./run.sh [gespro|gitlab|trends|all]
set -e
cd "$(dirname "$0")"
PY=".venv/bin/python"

run_one() {
  case "$1" in
    gespro)  $PY gespro/gespro_report.py ;;
    gitlab)  $PY gitlab/gitlab_report.py ;;
    trends)  $PY trends/trends_report.py ;;
    *) echo "Reporte desconocido: $1 (usa gespro|gitlab|trends)"; exit 2 ;;
  esac
}

if [ "$1" = "all" ]; then
  run_one gespro && run_one gitlab && run_one trends
elif [ -n "$1" ]; then
  run_one "$1"
else
  echo "Uso: ./run.sh [gespro|gitlab|trends|all]"; exit 2
fi
