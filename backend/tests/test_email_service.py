from types import SimpleNamespace

import pytest

from app.services import email_service
from app.services.email_service import EmailConfigError


@pytest.mark.asyncio
async def test_send_email_accepts_long_unicode_subject(monkeypatch):
    captured = {}

    async def fake_send(message, **kwargs):
        captured["message"] = message
        captured["kwargs"] = kwargs

    monkeypatch.setattr(
        email_service,
        "get_settings",
        lambda: SimpleNamespace(
            SMTP_HOST="smtp.example.com",
            SMTP_PORT=587,
            SMTP_USER="sender@example.com",
            SMTP_PASSWORD="secret",
            SMTP_FROM="sender@example.com",
        ),
    )
    monkeypatch.setattr(email_service.aiosmtplib, "send", fake_send)

    await email_service.send_email(
        "ops@example.com",
        "[Fengdiao PHM] HI阈值告警 12台风机低于70，需要立即巡检并安排工单闭环",
        "body",
    )

    message = captured["message"]
    assert str(message["Subject"]) == "[Fengdiao PHM] HI阈值告警 12台风机低于70，需要立即巡检并安排工单闭环"
    assert captured["kwargs"]["sender"] == "sender@example.com"
    assert captured["kwargs"]["recipients"] == ["ops@example.com"]


def test_plain_email_rejects_line_breaks():
    with pytest.raises(EmailConfigError, match="line breaks"):
        email_service._plain_email("ops@example.com\r\nBcc: bad@example.com", "recipient_email")
