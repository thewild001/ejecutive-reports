"""Tests de common/delivery.py: adjunto, plantillas, aislamiento de canales y exit codes."""
from __future__ import annotations

import email
import smtplib
import ssl
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import delivery  # noqa: E402
from common.delivery import (  # noqa: E402
    EXIT_DELIVERY_FAILED,
    EXIT_NO_CHANNEL,
    DeliveryResult,
    deliver,
    delivery_exit_code,
    render_message,
    send_email,
)

PDF_BYTES = b"%PDF-1.4 contenido de prueba"


def _cfg(**mail_over) -> dict:
    mail = {
        "enabled": True, "smtp_host": "smtp.test", "smtp_port": 587, "starttls": True,
        "verify_ssl": True, "user_env": "T_SMTP_USER", "pass_env": "T_SMTP_PASS",
        "sender": "reportes@example.org", "recipients": ["a@example.org", "b@example.org"],
        "messages": {},
    }
    mail.update(mail_over)
    return {
        "company": {"name": "ACME", "unit": "Desarrollo", "issued_by": "BI", "locale": "es"},
        "delivery": {"email": mail, "telegram": {"enabled": False}},
    }


class FakeSMTP:
    """Sustituto de smtplib.SMTP que captura lo enviado."""

    sent: list[dict] = []
    fail_login = False

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        FakeSMTP.sent.append({"starttls": True})

    def login(self, user, password):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"credenciales rechazadas")

    def sendmail(self, sender, recipients, raw):
        FakeSMTP.sent.append({"sender": sender, "recipients": recipients, "raw": raw})


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    FakeSMTP.sent, FakeSMTP.fail_login = [], False
    monkeypatch.setattr(delivery.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("T_SMTP_USER", "reportes@example.org")
    monkeypatch.setenv("T_SMTP_PASS", "no-es-un-secreto-real")
    monkeypatch.delenv(delivery.REQUIRE_DELIVERY_ENV, raising=False)


@pytest.fixture
def pdf(tmp_path) -> Path:
    p = tmp_path / "informe_x_20260101_0800.pdf"
    p.write_bytes(PDF_BYTES)
    return p


def _message(captured: dict):
    return email.message_from_string(captured["raw"])


def test_email_lleva_el_pdf_adjunto_y_destinatarios(pdf):
    assert send_email(pdf, _cfg(), "Asunto X", "Cuerpo X") is True
    sent = [s for s in FakeSMTP.sent if "raw" in s][0]
    assert sent["recipients"] == ["a@example.org", "b@example.org"]
    msg = _message(sent)
    assert msg["Subject"] == "Asunto X"
    attachments = [p for p in msg.walk() if p.get_filename()]
    assert [a.get_filename() for a in attachments] == [pdf.name]
    assert attachments[0].get_payload(decode=True) == PDF_BYTES


def test_email_deshabilitado_no_envia(pdf):
    assert send_email(pdf, _cfg(enabled=False), "s", "b") is False
    assert FakeSMTP.sent == []


def test_email_sin_destinatarios_falla_claro(pdf):
    with pytest.raises(SystemExit, match="recipients"):
        send_email(pdf, _cfg(recipients=[]), "s", "b")


def test_plantilla_por_reporte_y_variables():
    cfg = _cfg(messages={"gespro": {"subject": "{company} · {report} · {date}",
                                    "body": "Hola desde {signature}. {desconocida}"}})
    subject, body = render_message(cfg, "gespro", "Estado")
    assert subject.startswith("ACME · Estado · ")
    assert "Hola desde ACME — Desarrollo." in body
    assert "{desconocida}" in body  # variable desconocida no rompe el render


def test_plantilla_por_defecto_viene_de_i18n():
    subject, body = render_message(_cfg(), "trends", "Boletín")
    assert subject.startswith("Boletín | ")
    assert "ACME — Desarrollo" in body


def test_deliver_aisla_canales_y_reporta_fallo(pdf, monkeypatch):
    cfg = _cfg()
    cfg["delivery"]["telegram"] = {"enabled": True}
    FakeSMTP.fail_login = True
    monkeypatch.setattr(delivery, "send_telegram", lambda *a, **k: True)
    results = deliver(pdf, cfg, "Informe", report_key="gitlab")
    assert results == [
        DeliveryResult("email", False, results[0].detail),
        DeliveryResult("telegram", True, "enviado"),
    ]
    assert "credenciales rechazadas" in results[0].detail or "535" in results[0].detail
    assert delivery_exit_code(results) == EXIT_DELIVERY_FAILED


def test_secreto_ausente_es_fallo_de_canal_no_crash(pdf, monkeypatch):
    monkeypatch.delenv("T_SMTP_PASS")
    results = deliver(pdf, _cfg(), "Informe")
    assert len(results) == 1 and results[0].ok is False
    assert "T_SMTP_PASS" in results[0].detail
    assert "no-es-un-secreto-real" not in results[0].detail


def test_exit_code_ok_cuando_todo_se_envia(pdf):
    results = deliver(pdf, _cfg(), "Informe")
    assert [r.ok for r in results] == [True]
    assert delivery_exit_code(results) == 0


def test_sin_canales_es_ok_manual_y_error_bajo_cron(pdf, monkeypatch):
    results = deliver(pdf, _cfg(enabled=False), "Informe")
    assert results == []
    assert delivery_exit_code(results) == 0
    monkeypatch.setenv(delivery.REQUIRE_DELIVERY_ENV, "1")
    assert delivery_exit_code(results) == EXIT_NO_CHANNEL


def test_ca_bundle_se_pasa_al_contexto_ssl(monkeypatch):
    captured = {}
    monkeypatch.setattr(ssl, "create_default_context",
                        lambda **kw: captured.update(kw) or ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    delivery._ssl_context({"verify_ssl": True, "ca_bundle": "/etc/ssl/ca-interna.pem"})
    assert captured == {"cafile": "/etc/ssl/ca-interna.pem"}
