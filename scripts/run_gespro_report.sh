#!/usr/bin/env bash
# Pipeline GESPRO/FORTES: genera el PDF, envía por Telegram y por correo.
# Cron: cada 2 días a las 08:00 -> 0 8 */2 * * *
set -u
source /home/fortes/.hermes/.env

SCRIPTS=/home/fortes/scripts
OUTPUT_DIR=/home/fortes
LOG="$SCRIPTS/gitlab_cron.log"
CHAT_ID="${TELEGRAM_HOME_CHANNEL:-764852598}"

echo "$(date) - Generando reporte ejecutivo Gespro FORTES..." >> "$LOG"
if ! /home/fortes/.hermes/hermes-agent/venv/bin/python3 "$SCRIPTS/generate_gespro_report_fortes.py" >> "$LOG" 2>&1; then
  echo "$(date) - ERROR generando PDF" >> "$LOG"
  exit 1
fi

# Buscar el PDF generado (nombre fijo, ya que el generador no usa fecha)
PDF="$OUTPUT_DIR/informe_gespro_fortes.pdf"
if [ ! -f "$PDF" ]; then
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
if /home/fortes/.hermes/hermes-agent/venv/bin/python3 "$SCRIPTS/send_gespro_report.py" "$PDF" >> "$LOG" 2>&1; then
  echo "$(date) - Enviado por correo a fortes@uci.cu" >> "$LOG"
else
  echo "$(date) - ERROR enviando correo" >> "$LOG"
fi
