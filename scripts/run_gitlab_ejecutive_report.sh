#!/usr/bin/env bash
# Pipeline GITLAB/FORTES: genera el PDF, envía por Telegram y por correo.
# Cron: cada 2 días a las 08:00 -> 0 8 */2 * * *
set -u
source /home/fortes/.hermes/.env

SCRIPTS=/home/fortes/scripts
OUTPUT_DIR=/home/fortes
LOG="$SCRIPTS/gitlab_ejecutive_cron.log"
CHAT_ID="${TELEGRAM_HOME_CHANNEL:-764852598}"

echo "$(date) - Generando reporte ejecutivo GitLab FORTES..." >> "$LOG"
if ! /home/fortes/.hermes/hermes-agent/venv/bin/python3 "$SCRIPTS/generate_gitlab_ejecutive_report2.py" >> "$LOG" 2>&1; then
  echo "$(date) - ERROR generando PDF" >> "$LOG"
  exit 1
fi

# Buscar el PDF generado más reciente (patrón con fecha)
PDF=$(ls -t "$OUTPUT_DIR"/resumen_ejecutivo_gitlab_fortes_*.pdf 2>/dev/null | head -1)
if [ -z "$PDF" ] || [ ! -f "$PDF" ]; then
  echo "$(date) - ERROR: PDF no encontrado en $OUTPUT_DIR" >> "$LOG"
  exit 1
fi

echo "$(date) - PDF generado: $PDF" >> "$LOG"

# 1. Telegram
if curl -s -F chat_id="$CHAT_ID" -F document=@"$PDF" \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument" \
    > "$SCRIPTS/gilap_telegram.log" 2>&1; then
  echo "$(date) - Enviado a Telegram ($CHAT_ID)" >> "$LOG"
else
  echo "$(date) - ERROR enviando a Telegram" >> "$LOG"
fi

# 2. Correo - usar el mismo PDF encontrado
if /home/fortes/.hermes/hermes-agent/venv/bin/python3 "$SCRIPTS/send_gitlab_report.py" "$PDF" >> "$LOG" 2>&1; then
  echo "$(date) - Enviado por correo a fortes@uci.cu" >> "$LOG"
else
  echo "$(date) - ERROR enviando correo" >> "$LOG"
fi