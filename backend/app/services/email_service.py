"""Email sending helpers."""

from email.message import EmailMessage
from email.utils import parseaddr

import aiosmtplib

from app.config import get_settings


class EmailConfigError(RuntimeError):
    """Raised when SMTP settings are incomplete."""


def _smtp_settings():
    settings = get_settings()
    missing = [
        name
        for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM")
        if not getattr(settings, name)
    ]
    if missing:
        raise EmailConfigError(f"Missing SMTP settings: {', '.join(missing)}")
    return settings


def _plain_email(value: str, field_name: str) -> str:
    """Return an ASCII SMTP envelope address from a header-like value."""
    if "\r" in value or "\n" in value:
        raise EmailConfigError(f"{field_name} must not contain line breaks")

    _, address = parseaddr(value)
    address = (address or value).strip()
    if "\r" in address or "\n" in address:
        raise EmailConfigError(f"{field_name} must not contain line breaks")
    try:
        address.encode("ascii")
    except UnicodeEncodeError as exc:
        raise EmailConfigError(f"{field_name} must be a plain email address, not a Chinese name") from exc
    if "@" not in address:
        raise EmailConfigError(f"{field_name} must be a valid email address")
    return address


def _single_line_header(value: str, field_name: str) -> str:
    text = " ".join(str(value or "").splitlines()).strip()
    if not text:
        raise EmailConfigError(f"{field_name} must not be empty")
    return text


async def send_email(to_email: str, subject: str, body: str, html_body: str | None = None) -> None:
    """Send an email with the configured SMTP server.

    When html_body is provided the message is sent as multipart/alternative
    so mail clients can render the HTML version while plain-text clients
    fall back to the text body.
    """
    settings = _smtp_settings()
    from_email = _plain_email(settings.SMTP_FROM, "SMTP_FROM")
    recipient = _plain_email(to_email, "recipient_email")
    message = EmailMessage()
    message["From"] = from_email
    message["To"] = recipient
    message["Subject"] = _single_line_header(subject, "subject")
    message.set_content(body, charset="utf-8")
    if html_body:
        message.add_alternative(html_body, subtype="html", charset="utf-8")

    await aiosmtplib.send(
        message,
        sender=from_email,
        recipients=[recipient],
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        username=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,
        local_hostname="localhost",
        start_tls=True,
    )
