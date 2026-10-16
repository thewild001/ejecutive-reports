#!/usr/bin/env bash
# Tech Trends quincenal: genera PDF + envía Telegram + correo.
# Cron: 0 8 */15 * *
set -euo pipefail

source /home/fortes/.hermes/.env

SCRIPTS=/home/fortes/scripts
LOG="$SCRIPTS/tech_trends_cron.log"
CHAT_ID="${TELEGRAM_HOME_CHANNEL:-764852598}"

echo "$(date) - Generando reporte Tech Trends v2..." >> "$LOG"

# Proxy para curl a api.telegram.org (Cntlm FORTES)
export HTTPS_PROXY=http://10.128.50.3:2568
export HTTP_PROXY=http://10.128.50.3:2568
export NO_PROXY="localhost,127.0.0.1,.internal.domain"

# 1. Generar PDF con fpdf2 + DejaVu
if ! /home/fortes/.hermes/hermes-agent/venv/bin/python3 "$SCRIPTS/tech_trends_v2.py" "$SCRIPTS/tech_trends_data.json" >> "$LOG" 2>&1; then
  echo "$(date) - ERROR generando PDF" >> "$LOG"
  exit 1
fi

PDF="$SCRIPTS/informe_tendencias_v2.pdf"
if [ ! -f "$PDF" ]; then
  echo "$(date) - ERROR: PDF no encontrado en $SCRIPTS" >> "$LOG"
  exit 1
fi

echo "$(date) - PDF generado: $PDF" >> "$LOG"

# 2. Enviar por Telegram
if curl -s -F chat_id="$CHAT_ID" -F document=@"$PDF" \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument" \
    > "$SCRIPTS/tech_trends_telegram.log" 2>&1; then
  echo "$(date) - Enviado a Telegram ($CHAT_ID)" >> "$LOG"
else
  echo "$(date) - ERROR enviando a Telegram" >> "$LOG"
fi

# 3. Enviar por correo (send_trends_report.py)
if /home/fortes/.hermes/hermes-agent/venv/bin/python3 "$SCRIPTS/send_trends_report.py" "$PDF" >> "$LOG" 2>&1; then
  echo "$(date) - Enviado por correo a fortes@uci.cu" >> "$LOG"
else
  echo "$(date) - ERROR enviando correo" >> "$LOG"
fi