"""Live-DB tests for the forgot-password flow (migration 023,
services/password_reset.py, POST /auth/password-reset/request + /confirm).

Same pattern as test_auth_endpoints.py: route functions called directly
with explicit kwargs, own NullPool engine.

What must hold (security plan §1):
- request replies identically for known and unknown emails;
- only the token's hash is stored; tokens are single-use and expire;
- a new request supersedes older links; per-account email cap;
- a completed reset revokes every session of the account;
- no configured email → honest 503, not a fake "sent".
"""
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.core.rate_limit as rl
from app.api.v1.auth import (
    _RESET_REQUESTED,
    confirm_password_reset,
    login,
    request_password_reset,
)
from app.core.config import settings
from app.core.security import hash_password, hash_token, verify_password
from app.db.models import AuditEvent, PasswordResetToken, User, UserSession
from app.schemas.auth import LoginRequest, PasswordResetConfirm, PasswordResetRequest
from app.services import password_reset as pr

_test_engine = create_async_engine(settings.database_url_async, poolclass=NullPool)
_session_factory = async_sessionmaker(_test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _reset_limiter():
    rl._attempts.clear()
    rl._blocked.clear()
    rl._last_cleanup = time.time()
    yield
    rl._attempts.clear()
    rl._blocked.clear()


@pytest.fixture(autouse=True)
def _email_configured():
    with patch.object(settings, "smtp_host", "smtp.test.invalid"), \
         patch.object(settings, "mail_from", "Fix+Apply <no-reply@test.invalid>"):
        yield


def _request(ip="203.0.113.77"):
    return SimpleNamespace(headers={}, client=SimpleNamespace(host=ip))


async def _user(session, password="OldPassword123!", status="active"):
    u = User(
        id=str(uuid.uuid4()),
        email=f"{uuid.uuid4().hex[:10]}@reset.example",
        password_hash=hash_password(password),
        status=status,
    )
    session.add(u)
    await session.commit()
    return u


async def _request_reset(email, ip="203.0.113.77"):
    tasks = BackgroundTasks()
    async with _session_factory() as s:
        resp = await request_password_reset(
            body=PasswordResetRequest(email=email), request=_request(ip),
            background_tasks=tasks, session=s,
        )
    return resp, tasks


def _emailed_token(tasks: BackgroundTasks) -> str:
    assert len(tasks.tasks) == 1
    task = tasks.tasks[0]
    assert task.func is pr.send_reset_email
    return task.args[0].token


async def _tokens_for(user_id):
    async with _session_factory() as s:
        rows = await s.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.user_id == user_id)
            .order_by(PasswordResetToken.created_at)
        )
        return list(rows.scalars())


class TestRequest:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_known_and_unknown_emails_get_the_identical_reply(self):
        async with _session_factory() as s:
            user = await _user(s)

        known, known_tasks = await _request_reset(user.email)
        unknown, unknown_tasks = await _request_reset("nobody-here@reset.example")

        assert known.model_dump() == unknown.model_dump()
        assert len(known_tasks.tasks) == 1      # email goes out after the response
        assert len(unknown_tasks.tasks) == 0    # nothing to send, nothing stored

    @pytest.mark.asyncio(loop_scope="function")
    async def test_stores_only_the_hash_and_a_short_expiry(self):
        async with _session_factory() as s:
            user = await _user(s)
        _, tasks = await _request_reset(user.email)
        token = _emailed_token(tasks)

        [row] = await _tokens_for(user.id)
        assert row.token_hash == hash_token(token)
        assert token not in row.token_hash
        assert row.used_at is None
        ttl = row.expires_at - row.created_at
        assert ttl == timedelta(minutes=settings.password_reset_token_ttl_minutes)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_new_request_supersedes_the_older_link(self):
        async with _session_factory() as s:
            user = await _user(s)
        _, first = await _request_reset(user.email)
        _, second = await _request_reset(user.email, ip="203.0.113.78")
        old_token = _emailed_token(first)

        rows = await _tokens_for(user.id)
        assert rows[0].used_at is not None and rows[1].used_at is None
        async with _session_factory() as s:
            with pytest.raises(HTTPException) as exc:
                await confirm_password_reset(
                    body=PasswordResetConfirm(token=old_token, password="NewPassword123!"),
                    request=_request(), session=s,
                )
        assert exc.value.status_code == 400
        assert _emailed_token(second)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_per_account_cap_stops_inbox_flooding_across_ips(self):
        async with _session_factory() as s:
            user = await _user(s)
        cap = settings.password_reset_max_emails_per_hour
        for i in range(cap):
            _, tasks = await _request_reset(user.email, ip=f"198.51.100.{i + 1}")
            assert len(tasks.tasks) == 1
        resp, tasks = await _request_reset(user.email, ip="198.51.100.200")
        assert len(tasks.tasks) == 0                    # silently not sent…
        assert resp.detail == _RESET_REQUESTED           # …same reply as always
        assert len(await _tokens_for(user.id)) == cap

    @pytest.mark.asyncio(loop_scope="function")
    async def test_suspended_accounts_get_no_email(self):
        async with _session_factory() as s:
            user = await _user(s, status="suspended")
        _, tasks = await _request_reset(user.email)
        assert len(tasks.tasks) == 0

    @pytest.mark.asyncio(loop_scope="function")
    async def test_503_when_email_is_not_configured(self):
        with patch.object(settings, "smtp_host", ""):
            with pytest.raises(HTTPException) as exc:
                await _request_reset("anyone@reset.example")
        assert exc.value.status_code == 503

    @pytest.mark.asyncio(loop_scope="function")
    async def test_per_ip_rate_limit(self):
        for _ in range(rl.MAX_ATTEMPTS_PER_WINDOW):
            await _request_reset("nobody-here@reset.example", ip="192.0.2.9")
        with pytest.raises(HTTPException) as exc:
            await _request_reset("nobody-here@reset.example", ip="192.0.2.9")
        assert exc.value.status_code == 429


class TestConfirm:
    async def _issue(self, password="OldPassword123!"):
        async with _session_factory() as s:
            user = await _user(s, password=password)
        _, tasks = await _request_reset(user.email)
        return user, _emailed_token(tasks)

    async def _confirm(self, token, password="NewPassword123!", ip="203.0.113.90"):
        async with _session_factory() as s:
            return await confirm_password_reset(
                body=PasswordResetConfirm(token=token, password=password),
                request=_request(ip), session=s,
            )

    @pytest.mark.asyncio(loop_scope="function")
    async def test_sets_the_password_revokes_sessions_and_audits(self):
        user, token = await self._issue()
        # A live session from before the reset (e.g. an attacker's).
        async with _session_factory() as s:
            await login(
                body=LoginRequest(email=user.email, password="OldPassword123!"),
                request=_request("203.0.113.91"), session=s,
            )

        await self._confirm(token)

        async with _session_factory() as s:
            fresh = (await s.execute(select(User).where(User.id == user.id))).scalar_one()
            assert verify_password("NewPassword123!", fresh.password_hash)
            assert not verify_password("OldPassword123!", fresh.password_hash)
            sessions = (await s.execute(
                select(UserSession).where(UserSession.user_id == user.id)
            )).scalars().all()
            assert sessions and all(x.revoked_at is not None for x in sessions)
            audit = (await s.execute(
                select(AuditEvent).where(
                    AuditEvent.user_id == user.id, AuditEvent.event_type == "password_reset"
                )
            )).scalars().all()
            assert len(audit) == 1
        [row] = await _tokens_for(user.id)
        assert row.used_at is not None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_token_works_only_once(self):
        _, token = await self._issue()
        await self._confirm(token)
        with pytest.raises(HTTPException) as exc:
            await self._confirm(token, password="AnotherPassword1!")
        assert exc.value.status_code == 400

    @pytest.mark.asyncio(loop_scope="function")
    async def test_expired_token_is_rejected(self):
        user, token = await self._issue()
        async with _session_factory() as s:
            row = (await s.execute(
                select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
            )).scalar_one()
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await s.commit()
        with pytest.raises(HTTPException) as exc:
            await self._confirm(token)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio(loop_scope="function")
    async def test_unknown_token_gets_the_same_error(self):
        with pytest.raises(HTTPException) as exc:
            await self._confirm("not-a-real-token")
        assert exc.value.status_code == 400
        assert "invalid or has expired" in exc.value.detail

    def test_new_password_must_meet_the_12_char_policy(self):
        with pytest.raises(ValidationError):
            PasswordResetConfirm(token="t", password="Short1!")


class TestEmail:
    def test_link_carries_the_token_in_the_fragment_not_the_query(self):
        with patch.object(settings, "frontend_base_url", "https://app.example/"):
            link = pr.reset_link("abc123")
        assert link == "https://app.example/reset-password#token=abc123"

    def test_send_failure_is_logged_without_the_token(self):
        msg = pr.ResetEmail(to="a@reset.example", token="SECRET-TOKEN-VALUE")
        with patch.object(pr, "send_email", side_effect=OSError("smtp down")), \
             patch.object(pr.logger, "error") as log_error:
            pr.send_reset_email(msg)  # must not raise
        assert log_error.called
        assert "SECRET-TOKEN-VALUE" not in repr(log_error.call_args)

    def test_email_contains_the_link(self):
        msg = pr.ResetEmail(to="a@reset.example", token="tok-xyz")
        with patch.object(pr, "send_email") as send:
            pr.send_reset_email(msg)
        kwargs = send.call_args.kwargs
        assert kwargs["to"] == "a@reset.example"
        assert "#token=tok-xyz" in kwargs["text"]
        assert "#token=tok-xyz" in kwargs["html"]
