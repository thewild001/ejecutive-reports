#!/usr/bin/env bash
# Cron: ejecuta el reporte 'gespro' (ver run_report.sh para variables y códigos de salida).
exec "$(dirname "${BASH_SOURCE[0]}")/run_report.sh" gespro "$@"
