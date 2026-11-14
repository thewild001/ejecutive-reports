#!/usr/bin/env bash
# Lanzador común para cron. Uso: scripts/run_report.sh <gespro|gitlab|trends> [args...]
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${1:-}"
[ "$#" -gt 0 ] && shift
case "$REPORT" in
  gespro) ENTRY="gespro/gespro_report.py" ;;
  gitlab) ENTRY="gitlab/gitlab_report.py" ;;
  trends) ENTRY="trends/trends_report.py" ;;
  *) echo "Uso: $0 <gespro|gitlab|trends> [args...]" >&2; exit 2 ;;
esac

# Cargar únicamente variables propias del wrapper; nunca ejecutar .env como shell.
load_env_var() {
  local name="$1" line value
  [ -n "${!name:-}" ] && return 0
  [ -f "$ROOT/.env" ] || return 0
  line="$(grep -E "^[[:space:]]*${name}=" "$ROOT/.env" | tail -n 1 || true)"
  [ -n "$line" ] || return 0
  value="${line#*=}"; value="${value%\\"}"; value="${value#\\"}"
  export "$name=$value"
}
for var in REPORTS_PYTHON REPORTS_PROXY REPORTS_LOG_DIR REPORTS_REQUIRE_DELIVERY REPORTS_STATE_DB; do
  load_env_var "$var"
done

if [ -n "${REPORTS_PYTHON:-}" ]; then
  PY="$REPORTS_PYTHON"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="$(command -v python3 || true)"
fi
if [ -z "$PY" ] || ! "$PY" --version >/dev/null 2>&1; then
  echo "ERROR: no se encontró Python. Crea .venv o define REPORTS_PYTHON." >&2
  exit 127
fi

LOG_DIR="${REPORTS_LOG_DIR:-$ROOT/logs}"
mkdir -p "$LOG_DIR" "$ROOT/.locks" "$ROOT/output/.state"
LOG="$LOG_DIR/$REPORT.log"
export REPORTS_STATE_DB="${REPORTS_STATE_DB:-$ROOT/output/.state/execution-ledger.sqlite3}"
stamp() { date '+%Y-%m-%d %H:%M:%S'; }
log() { printf '%s [%s] %s
' "$(stamp)" "$REPORT" "$*" >> "$LOG"; }

if [ -n "${REPORTS_PROXY:-}" ]; then
  export HTTP_PROXY="$REPORTS_PROXY" HTTPS_PROXY="$REPORTS_PROXY"
  export http_proxy="$REPORTS_PROXY" https_proxy="$REPORTS_PROXY"
fi
export REPORTS_REQUIRE_DELIVERY="${REPORTS_REQUIRE_DELIVERY:-1}"

# El registro RUNNING se crea antes del lock para conservar los intentos omitidos.
RUN_ID="$("$PY" -m common.execution_ledger start --report "$REPORT" --log-path "$LOG" --pid "$" --host "$(hostname)")" || {
  echo "ERROR: no se pudo registrar el inicio en el ledger; ejecución cancelada." >&2
  exit 70
}
export REPORTS_RUN_ID="$RUN_ID"
FINISHED=0
finish_run() {
  local status="$1" code="$2"
  [ "$FINISHED" -eq 1 ] && return 0
  FINISHED=1
  if ! "$PY" -m common.execution_ledger finish --run-id "$RUN_ID" --status "$status" --exit-code "$code"; then
    echo "ERROR: fallo al cerrar el ledger (run_id=$RUN_ID)." >&2
    return 1
  fi
}
handle_signal() {
  local signal="$1" code="$2"
  trap - INT TERM HUP
  log "INTERRUMPIDO por señal $signal (run_id=$RUN_ID)"
  finish_run INTERRUPTED "$code" || true
  echo "Ejecución $REPORT interrumpida por señal $signal (run_id=$RUN_ID)." >&2
  exit "$code"
}
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM
trap 'handle_signal HUP 129' HUP

exec 9>"$ROOT/.locks/$REPORT.lock"
if command -v flock >/dev/null 2>&1; then
  if ! flock -n 9; then
    log "OMITIDO: ejecución concurrente (run_id=$RUN_ID)"
    finish_run SKIPPED_LOCKED 75
    echo "Ejecución $REPORT omitida: ya existe otra instancia (run_id=$RUN_ID)." >&2
    exit 75
  fi
else
  log "AVISO: flock no disponible; se continúa sin exclusión mutua (run_id=$RUN_ID)" >&2
fi

log "INICIO run_id=$RUN_ID pid=$$ host=$(hostname) python=$PY entry=$ENTRY"
cd "$ROOT"
set +e
"$PY" "$ENTRY" "$@" >> "$LOG" 2>&1
RC=$?
set -e
if [ "$RC" -eq 0 ]; then STATUS=SUCCEEDED; else STATUS=FAILED; fi
log "FIN status=$STATUS code=$RC run_id=$RUN_ID"
if ! finish_run "$STATUS" "$RC"; then
  echo "ERROR: no se pudo persistir el resultado final (run_id=$RUN_ID)." >&2
  exit 70
fi
case "$RC" in
  0) ;;
  3) echo "Fallo de entrega en $REPORT (run_id=$RUN_ID; código 3)." >&2 ;;
  4) echo "Sin canales de entrega habilitados para $REPORT (run_id=$RUN_ID; código 4)." >&2 ;;
  5) echo "Datos desactualizados; no se generó el boletín (run_id=$RUN_ID; código 5)." >&2 ;;
  6) echo "El MCP no devolvió datos; no se generó el informe (run_id=$RUN_ID; código 6)." >&2 ;;
  *) echo "Falló $REPORT con código $RC (run_id=$RUN_ID)." >&2 ;;
esac
exit "$RC"
