"""Delivery channels: SMTP email and Telegram. All config-driven, no hardcoded secrets."""
from __future__ import annotations

import datetime
import json
import smtplib
import ssl
import urllib.request
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from .settings import require_env


def send_email(pdf_path: Path, cfg: dict, subject: str, body: str) -> bool:
    mail = cfg.get("delivery", {}).get("email", {})
    if not mail.get("enabled"):
        return False
    user = require_env(mail.get("user_env", "SMTP_USER"), "usuario SMTP")
    password = require_env(mail.get("pass_env", "SMTP_PASS"), "contraseña SMTP")

    msg = MIMEMultipart()
    msg["From"] = mail.get("sender", user)
    msg["To"] = ", ".join(mail.get("recipients", []))
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with open(pdf_path, "rb") as f:
        att = MIMEApplication(f.read(), _subtype="pdf")
    att.add_header("Content-Disposition", "attachment", filename=pdf_path.name)
    msg.attach(att)

    context = ssl.create_default_context()
    if not mail.get("verify_ssl", True):
        context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    with smtplib.SMTP(mail["smtp_host"], int(mail.get("smtp_port", 587)), timeout=30) as server:
        server.ehlo()
        if mail.get("starttls", True):
            server.starttls(context=context)
            server.ehlo()
        server.login(user, password)
        server.sendmail(msg["From"], mail.get("recipients", []), msg.as_string())
    print(f"[delivery] Email enviado a {msg['To']}")
    return True


def send_telegram(pdf_path: Path, cfg: dict, caption: str) -> bool:
    tg = cfg.get("delivery", {}).get("telegram", {})
    if not tg.get("enabled"):
        return False
    token = require_env(tg.get("bot_token_env", "TELEGRAM_BOT_TOKEN"), "token bot Telegram")
    chat_id = require_env(tg.get("chat_id_env", "TELEGRAM_CHAT_ID"), "chat id Telegram")

    url = f"https://api.telegram.org/bot{token}/sendDocument"
    boundary = "----reportsboundary"
    parts: list[bytes] = []

    def field(name: str, value: str, filename: str | None = None, ctype: str = "text/plain"):
        disp = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
        parts.append(f"--{boundary}\r\nContent-Disposition: {disp}\r\nContent-Type: {ctype}\r\n\r\n".encode())
        parts.append(value if isinstance(value, bytes) else str(value).encode())
        parts.append(b"\r\n")

    field("chat_id", chat_id)
    field("caption", caption[:1024])
    field("document", pdf_path.read_bytes(), filename=pdf_path.name, ctype="application/pdf")
    parts.append(f"--{boundary}--\r\n".encode())
    payload = b"".join(parts)

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        ok = resp.status == 200
    print(f"[delivery] Telegram {'enviado' if ok else 'falló'} a chat {chat_id}")
    return ok


def deliver(pdf_path: Path, cfg: dict, report_label: str, email_body: str = "") -> None:
    """Deliver via all enabled channels; always leaves the PDF in output dir."""
    now = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    subject = f"{report_label} | {datetime.datetime.now().strftime('%d/%m/%Y')}"
    if not email_body:
        email_body = f"Adjunto: {report_label}, generado el {now}."
    send_email(pdf_path, cfg, subject, email_body)
    send_telegram(pdf_path, cfg, caption=f"{report_label} — {now}")


def dumps(obj) -> str:  # helper for debug
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
