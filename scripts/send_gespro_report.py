#!/usr/bin/env python3
"""
Script de envío del Informe GESPRO - Proyectos FORTES por correo electrónico.
Usa smtp.uci.cu con STARTTLS en puerto 587.

Uso: python3 send_gespro_report.py [ruta_pdf]
Si no se proporciona ruta, usa la ruta por defecto.
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
DEFAULT_REPORT_PATH = "/home/fortes/informe_gespro_fortes.pdf"
RECIPIENTS = ["fortes@uci.cu"]
SENDER = "fortes@uci.cu"
SMTP_SERVER = "smtp.uci.cu"
SMTP_PORT = 587
SMTP_USER = "fortes@uci.cu"
SMTP_PASS = "Abril2026/*"

def main():
    # Permitir pasar la ruta del PDF como argumento
    if len(sys.argv) > 1:
        REPORT_PATH = sys.argv[1]
    else:
        REPORT_PATH = DEFAULT_REPORT_PATH

    now_str = datetime.datetime.now().strftime('%d/%m/%Y a las %H:%M')
    date_short = datetime.datetime.now().strftime('%d/%m/%Y')

    # Verificar que el PDF existe
    if not os.path.isfile(REPORT_PATH):
        print(f"ERROR: No se encontró el informe en {REPORT_PATH}")
        sys.exit(1)

    # Crear el mensaje
    msg = MIMEMultipart()
    msg['From'] = SENDER
    msg['To'] = ", ".join(RECIPIENTS)
    msg['Subject'] = f"Informe de Estado - Proyectos FORTES | {date_short}"

    # Cuerpo del correo
    body = f"""Adjunto el informe de estado de los proyectos FORTES generado el {now_str}.

Este informe incluye:
- Indicadores clave consolidados (proyectos, miembros, tareas)
- Estado de salud por proyecto (tasa de cierre, tareas abiertas/cerradas)
- Desglose de tareas abiertas por estado
- Carga de trabajo por miembro del equipo (con detección de tareas atrasadas)
- Análisis de fortalezas y debilidades por proyecto
- Sugerencias accionables para cada jefe de proyecto
- Recomendaciones estratégicas para el área FORTES

Generado: {now_str} | FORTES - https://gp.prod.uci.cu
"""

    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    # Adjuntar el PDF - usar el nombre base del archivo original
    with open(REPORT_PATH, 'rb') as f:
        pdf_data = f.read()
    attachment = MIMEApplication(pdf_data, _subtype='pdf')
    # Usar el nombre del archivo generado para el adjunto
    attachment_filename = os.path.basename(REPORT_PATH)
    attachment.add_header('Content-Disposition', 'attachment',
                          filename=attachment_filename)
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
