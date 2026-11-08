#!/usr/bin/env bash
# Lanzador común para cron. Uso: scripts/run_report.sh <gespro|gitlab|trends> [args...]
#
# Responsabilidades (solo orquestación; generar y enviar es trabajo del .py):
#   - resolver la raíz del proyecto sin rutas absolutas
#   - elegir el intérprete (REPORTS_PYTHON > .venv > python3)
#   - evitar ejecuciones solapadas (flock) y registrar en logs/<reporte>.log
#   - exportar el proxy corporativo si REPORTS_PROXY está definido
#   - exigir entrega: sin canales habilitados o con un canal fallido, sale != 0
#
# Variables opcionales (se pueden fijar en .env o en la línea del crontab):
#   REPORTS_PYTHON            intérprete a usar
#   REPORTS_PROXY             p. ej. http://proxy.local:3128
#   REPORTS_LOG_DIR           directorio de logs (por defecto <raíz>/logs)
#   REPORTS_REQUIRE_DELIVERY  0 para permitir ejecuciones sin canales de entrega
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${1:-}"
[ "$#" -gt 0 ] && shift

case "$REPORT" in
  gespro) ENTRY="gespro/gespro_report.py" ;;
  gitlab) ENTRY="gitlab/gitlab_report.py" ;;
  trends) ENTRY="trends/trends_report.py" ;;
  *)
    echo "Uso: $0 <gespro|gitlab|trends> [args...]" >&2
    exit 2
    ;;
esac

# .env: solo las variables REPORTS_* de este script (el .py carga el resto por su cuenta).
load_env_var() {
  local name="$1" line value
  [ -n "${!name:-}" ] && return 0
  [ -f "$ROOT/.env" ] || return 0
  line="$(grep -E "^[[:space:]]*${name}=" "$ROOT/.env" | tail -n 1 || true)"
  [ -n "$line" ] || return 0
  value="${line#*=}"; value="${value%\"}"; value="${value#\"}"
  export "$name=$value"
}
for var in REPORTS_PYTHON REPORTS_PROXY REPORTS_LOG_DIR REPORTS_REQUIRE_DELIVERY; do
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
  echo "ERROR: no se encontró un intérprete Python. Crea .venv (./install.sh) o define REPORTS_PYTHON." >&2
  exit 127
fi

LOG_DIR="${REPORTS_LOG_DIR:-$ROOT/logs}"
mkdir -p "$LOG_DIR" "$ROOT/.locks"
LOG="$LOG_DIR/$REPORT.log"

stamp() { date '+%Y-%m-%d %H:%M:%S'; }
log()   { printf '%s [%s] %s\n' "$(stamp)" "$REPORT" "$*" >> "$LOG"; }

if [ -n "${REPORTS_PROXY:-}" ]; then
  export HTTP_PROXY="$REPORTS_PROXY" HTTPS_PROXY="$REPORTS_PROXY"
  export http_proxy="$REPORTS_PROXY" https_proxy="$REPORTS_PROXY"
fi
export REPORTS_REQUIRE_DELIVERY="${REPORTS_REQUIRE_DELIVERY:-1}"

# Un reporte a la vez: si el anterior sigue corriendo, se omite sin error.
exec 9>"$ROOT/.locks/$REPORT.lock"
if command -v flock >/dev/null 2>&1; then
  if ! flock -n 9; then
    log "OMITIDO: la ejecución anterior sigue en curso"
    exit 0
  fi
else
  log "AVISO: flock no disponible; no se evitan ejecuciones solapadas"
fi

log "INICIO ($PY $ENTRY)"
cd "$ROOT"
set +e
"$PY" "$ENTRY" "$@" >> "$LOG" 2>&1
RC=$?
set -e
case "$RC" in
  0) log "FIN ok" ;;
  3) log "FIN con error: falló al menos un canal de entrega (código 3)" ;;
  4) log "FIN con error: no hay canales de entrega habilitados (código 4)" ;;
  5) log "FIN con error: datos desactualizados, no se generó el boletín (código 5)" ;;
  *) log "FIN con error (código $RC)" ;;
esac
exit "$RC"
