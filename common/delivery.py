"""Canales de entrega: correo SMTP y Telegram. Todo desde config, sin secretos en código.

Garantías:
- Cada canal se intenta de forma aislada: el fallo de uno no impide el otro.
- ``deliver`` devuelve un resultado por canal y ``delivery_exit_code`` lo traduce
  a un código de salida, para que cron/monitorización vean los fallos.
- Asunto y cuerpo del correo se renderizan desde plantillas (config o i18n) con
  variables: {company} {unit} {issued_by} {signature} {report} {date} {datetime}.
"""
from __future__ import annotations

import datetime
import json
import logging
import mimetypes
import os
import smtplib
import ssl
import urllib.request
from dataclasses import dataclass
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from .i18n import t
from .settings import require_env

log = logging.getLogger(__name__)

EXIT_DELIVERY_FAILED = 3
EXIT_NO_CHANNEL = 4
REQUIRE_DELIVERY_ENV = "REPORTS_REQUIRE_DELIVERY"


@dataclass(frozen=True)
class DeliveryResult:
    channel: str
    ok: bool
    detail: str = ""


class _SafeDict(dict):
    """format_map tolerante: una variable desconocida se deja tal cual."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _render(template: str, ctx: dict) -> str:
    return template.format_map(_SafeDict(ctx))


def _context(cfg: dict, report_label: str, now: datetime.datetime) -> dict:
    company = cfg.get("company", {})
    name, unit = company.get("name", ""), company.get("unit", "")
    return {
        "company": name,
        "unit": unit,
        "issued_by": company.get("issued_by", ""),
        "signature": " — ".join(p for p in (name, unit) if p),
        "report": report_label,
        "date": now.strftime("%d/%m/%Y"),
        "datetime": now.strftime("%d/%m/%Y %H:%M"),
    }


def render_message(cfg: dict, report_key: str, report_label: str,
                   now: datetime.datetime | None = None) -> tuple[str, str]:
    """Asunto y cuerpo: config ``delivery.email.messages.<report_key>`` o i18n."""
    now = now or datetime.datetime.now()
    locale = cfg.get("company", {}).get("locale", "es")
    custom = (cfg.get("delivery", {}).get("email", {}).get("messages") or {}).get(report_key, {})
    ctx = _context(cfg, report_label, now)
    subject = _render(custom.get("subject") or t("email_subject", locale), ctx)
    body = _render(custom.get("body") or t("email_body", locale), ctx).rstrip() + "\n"
    return subject, body


def _ssl_context(mail: dict) -> ssl.SSLContext:
    if not mail.get("verify_ssl", True):
        log.warning("SMTP con verify_ssl=false: el certificado del servidor NO se valida. "
                    "Preferible configurar delivery.email.ca_bundle con la CA interna.")
        context = ssl.create_default_context()
        context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
        return context
    return ssl.create_default_context(cafile=mail.get("ca_bundle") or None)


def send_email(pdf_path: Path, cfg: dict, subject: str, body: str) -> bool:
    """Envía el PDF adjunto. False si el canal está deshabilitado; lanza si falla."""
    mail = cfg.get("delivery", {}).get("email", {})
    if not mail.get("enabled"):
        return False
    recipients = mail.get("recipients", [])
    if not recipients:
        raise SystemExit("ERROR: delivery.email.recipients está vacío; no hay a quién enviar.")
    user = require_env(mail.get("user_env", "SMTP_USER"), "usuario SMTP")
    password = require_env(mail.get("pass_env", "SMTP_PASS"), "contraseña SMTP")

    msg = MIMEMultipart()
    msg["From"] = mail.get("sender") or user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    subtype = (mimetypes.guess_type(pdf_path.name)[0] or "application/pdf").split("/")[-1]
    att = MIMEApplication(pdf_path.read_bytes(), _subtype=subtype)
    att.add_header("Content-Disposition", "attachment", filename=pdf_path.name)
    msg.attach(att)

    context = _ssl_context(mail)
    with smtplib.SMTP(mail["smtp_host"], int(mail.get("smtp_port", 587)), timeout=30) as server:
        server.ehlo()
        if mail.get("starttls", True):
            server.starttls(context=context)
            server.ehlo()
        server.login(user, password)
        server.sendmail(msg["From"], recipients, msg.as_string())
    log.info("Email enviado a %s", msg["To"])
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
    if ok:
        log.info("Telegram enviado a chat %s", chat_id)
    else:
        log.warning("Telegram falló (chat %s)", chat_id)
    return ok


def deliver(pdf_path: Path, cfg: dict, report_label: str, report_key: str = "",
            email_body: str = "", subject: str | None = None) -> list[DeliveryResult]:
    """Entrega por todos los canales habilitados, cada uno aislado de los demás.

    El PDF siempre queda en el directorio de salida. Devuelve un resultado por
    canal habilitado (lista vacía si no hay ninguno) — úsese ``delivery_exit_code``.
    """
    now = datetime.datetime.now()
    msg_subject, msg_body = render_message(cfg, report_key, report_label, now)
    caption = f"{report_label} — {now.strftime('%d/%m/%Y %H:%M')}"
    channels = (
        ("email", lambda: send_email(pdf_path, cfg, subject or msg_subject, email_body or msg_body)),
        ("telegram", lambda: send_telegram(pdf_path, cfg, caption=caption)),
    )
    results: list[DeliveryResult] = []
    for name, send in channels:
        if not cfg.get("delivery", {}).get(name, {}).get("enabled"):
            continue
        try:
            ok = send()
            results.append(DeliveryResult(name, bool(ok), "enviado" if ok else "no enviado"))
        except (Exception, SystemExit) as exc:  # SystemExit: require_env / config
            log.error("Entrega por %s falló: %s", name, exc)
            results.append(DeliveryResult(name, False, str(exc)))
    if not results:
        log.warning("Ningún canal de entrega habilitado (delivery.email / delivery.telegram): "
                    "el PDF quedó solo en %s", pdf_path.parent)
    return results


def delivery_exit_code(results: list[DeliveryResult]) -> int:
    """0 = ok · 3 = algún canal habilitado falló · 4 = sin canales y se exigía entrega.

    La entrega solo es obligatoria si ``REPORTS_REQUIRE_DELIVERY=1`` (lo exporta el
    wrapper de cron); en ejecuciones manuales no tener canales no es un error.
    """
    if any(not r.ok for r in results):
        return EXIT_DELIVERY_FAILED
    if not results and os.environ.get(REQUIRE_DELIVERY_ENV) == "1":
        log.error("Entrega requerida pero no hay canales habilitados.")
        return EXIT_NO_CHANNEL
    return 0


def dumps(obj) -> str:  # helper for debug
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
