#!/usr/bin/env python3
"""
Script de envío del Boletín de Tendencias Tecnológicas por correo electrónico.
Usa smtp.uci.cu con STARTTLS en puerto 587 (misma configuración que send_gilap_report.py).
"""
import smtplib
import ssl
import datetime
import os
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# ── Configuración ──────────────────────────────────────────────────────────────
REPORT_PATH = "/home/fortes/scripts/informe_tendencias_v2.pdf"
RECIPIENTS = ["fortes@uci.cu"]
SENDER = "fortes@uci.cu"
SMTP_SERVER = "smtp.uci.cu"
SMTP_PORT = 587
SMTP_USER = "fortes@uci.cu"
SMTP_PASS = "Abril2026/*"

def main():
    now_str = datetime.datetime.now().strftime('%d/%m/%Y a las %H:%M')
    date_short = datetime.datetime.now().strftime('%d/%m/%Y')

    # Verificar que el PDF existe
    if not os.path.isfile(REPORT_PATH):
        print(f"ERROR: No se encontró el boletín en {REPORT_PATH}")
        sys.exit(1)

    # Crear el mensaje
    msg = MIMEMultipart()
    msg['From'] = SENDER
    msg['To'] = ", ".join(RECIPIENTS)
    msg['Subject'] = f"Boletín de Tendencias Tecnológicas | {date_short}"

    # Cuerpo del correo
    body = f"""Adjunto el Boletín de Tendencias Tecnológicas correspondiente al período {date_short}.

Este boletín incluye:
- Señales de vigilancia tecnológica recopiladas de múltiples fuentes
- Categorías temáticas priorizadas
- Análisis y tendencias emergentes relevantes para el área

Generado: {now_str} | Grupo de Inteligencia Empresarial
"""

    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    # Adjuntar el PDF
    with open(REPORT_PATH, 'rb') as f:
        pdf_data = f.read()
    attachment = MIMEApplication(pdf_data, _subtype='pdf')
    attachment.add_header('Content-Disposition', 'attachment',
                          filename=f'informe_tendencias_{datetime.datetime.now().strftime("%Y%m%d_%H%M")}.pdf')
    msg.attach(attachment)

    # Enviar el correo
    try:
        # Deshabilitar verificación de certificado para smtp.uci.cu (certificado autofirmado)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SENDER, RECIPIENTS, msg.as_string())
        print(f"OK - Correo enviado a {', '.join(RECIPIENTS)} el {now_str}")
    except smtplib.SMTPAuthenticationError:
        print("ERROR: Autenticación SMTP fallida. Verifique usuario/contraseña.")
        sys.exit(1)
    except smtplib.SMTPConnectError:
        print(f"ERROR: No se pudo conectar a {SMTP_SERVER}:{SMTP_PORT}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
