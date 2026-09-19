"""Outgoing email over SMTP.

Deliberately stdlib-only (smtplib) and provider-agnostic: every mainstream
transactional provider (Resend, Postmark, Amazon SES, Gmail) offers SMTP,
so switching provider is a settings change, not a code change.

Synchronous on purpose — callers run it off the request path (FastAPI
BackgroundTasks run sync callables in a worker thread), so a slow mail
server never holds a request open.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_TIMEOUT_SECONDS = 15


class EmailNotConfiguredError(RuntimeError):
    """SMTP settings are missing; nothing can be sent."""


def send_email(*, to: str, subject: str, text: str, html: str | None = None) -> None:
    """Send one message. Raises on any SMTP failure — the caller decides
    whether that is fatal."""
    if not settings.email_configured:
        raise EmailNotConfiguredError("SMTP_HOST and MAIL_FROM must be set")

    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    if settings.smtp_port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=_TIMEOUT_SECONDS, context=context
        )
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=_TIMEOUT_SECONDS)
    with server:
        if settings.smtp_port != 465:
            server.starttls(context=context)
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)
