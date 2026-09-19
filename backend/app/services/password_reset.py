"""Forgot-password flow: issue, email and redeem single-use reset tokens.

Security plan §1 requirements this satisfies:
- No user enumeration: the request endpoint replies identically whether or
  not the email has an account, and the email itself is sent after the
  response (BackgroundTasks), so latency doesn't reveal it either.
- No unlimited attempts: per-IP limiter on both endpoints (api/v1/auth.py)
  plus a per-account email cap here, so rotating IPs can't flood an inbox.
- All sessions invalidated on password change.

Tokens are 256-bit random values; only their SHA-256 is stored.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password, hash_token
from app.db.models import PasswordResetToken, User, UserSession
from app.services.email_sender import send_email

logger = get_logger(__name__)


class InvalidResetTokenError(Exception):
    """Unknown, used, expired, or belongs to an inactive account. One type
    on purpose: which of those it was is not the caller's business."""


@dataclass
class ResetEmail:
    to: str
    token: str


async def issue_reset_token(
    session: AsyncSession, email: str, requested_ip: str | None
) -> ResetEmail | None:
    """Create a token for `email` if it belongs to an active account and
    the per-account cap allows. Returns what to email, or None when nothing
    should be sent. Never raises for "no such account" — the caller must
    respond the same way in every case."""
    now = datetime.now(timezone.utc)
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None or user.status != "active":
        return None

    recent = (
        await session.execute(
            select(func.count())
            .select_from(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.created_at > now - timedelta(hours=1),
            )
        )
    ).scalar_one()
    if recent >= settings.password_reset_max_emails_per_hour:
        logger.warning("password_reset_throttled", user_id=user.id)
        return None

    # Only the newest emailed link should work.
    await session.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    token = secrets.token_urlsafe(32)
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            created_at=now,
            expires_at=now + timedelta(minutes=settings.password_reset_token_ttl_minutes),
            requested_ip=requested_ip,
        )
    )
    return ResetEmail(to=user.email, token=token)


async def redeem_reset_token(
    session: AsyncSession, token: str, new_password: str
) -> User:
    """Set a new password from a valid token. Marks the token used, revokes
    every session of the account (security plan §1), and returns the user.
    The caller commits."""
    now = datetime.now(timezone.utc)
    # FOR UPDATE: two concurrent redemptions of one token must not both win.
    row = (
        await session.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == hash_token(token))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise InvalidResetTokenError()

    user = (
        await session.execute(select(User).where(User.id == row.user_id))
    ).scalar_one_or_none()
    if user is None or user.status != "active":
        raise InvalidResetTokenError()

    user.password_hash = hash_password(new_password)
    row.used_at = now
    await session.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return user


def reset_link(token: str) -> str:
    # Token in the URL fragment, not the query string: browsers never send
    # the fragment to any server, so it can't land in proxy/access logs or
    # a Referer header.
    base = (settings.frontend_base_url or settings.cors_origin).rstrip("/")
    return f"{base}/reset-password#token={token}"


def send_reset_email(message: ResetEmail) -> None:
    """Run from BackgroundTasks. Failures are logged (never the token) and
    swallowed — the HTTP response has already gone out."""
    link = reset_link(message.token)
    minutes = settings.password_reset_token_ttl_minutes
    text = (
        "We received a request to reset your Fix+Apply password.\n\n"
        f"Choose a new password here (the link works once, for {minutes} minutes):\n"
        f"{link}\n\n"
        "If you didn't ask for this, you can ignore this email — your password "
        "won't change."
    )
    html = (
        "<p>We received a request to reset your Fix+Apply password.</p>"
        f'<p><a href="{escape(link)}">Choose a new password</a></p>'
        f"<p>The link works once, for {minutes} minutes. If you didn't ask for "
        "this, you can ignore this email — your password won't change.</p>"
    )
    try:
        send_email(to=message.to, subject="Reset your Fix+Apply password", text=text, html=html)
        logger.info("password_reset_email_sent")
    except Exception as exc:  # noqa: BLE001 — background task, nothing to re-raise to
        logger.error("password_reset_email_failed", error_type=type(exc).__name__)
