"""Live-DB tests for the auth endpoints and get_current_user()'s
session-validity checks — the Sprint 6 hardening gaps a security-plan
audit found untested: no test previously exercised an expired/tampered/
alg=none JWT, post-logout token reuse, a valid-JWT-with-no-backing-
session, the login enumeration-timing side-channel, or the 12-char
password minimum.

Calls route functions directly (bypassing FastAPI's DI), matching the
established live-DB pattern (own NullPool engine, no conftest.py,
explicit kwargs) used throughout tests/test_*_endpoints.py — see
test_matches_endpoints.py for the canonical example of this pattern.
"""
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

import app.core.rate_limit as rl
from app.api.v1.auth import login, logout, register
from app.core.config import settings
from app.core.security import create_access_token, get_current_user, hash_password
from app.core.security import verify_password as _real_verify_password
from app.db.models import AuditEvent, User
from app.schemas.auth import LoginRequest, RegisterRequest

_test_engine = create_async_engine(settings.database_url_async, poolclass=NullPool)
_test_session_factory = async_sessionmaker(_test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _reset_limiter_global_state():
    """Register/login share one auth-tier rate-limit bucket per client IP
    (see test_rate_limit_identity.py) — reset between tests so one test's
    attempts can't trip another's limiter."""
    rl._attempts.clear()
    rl._blocked.clear()
    rl._last_cleanup = time.time()
    yield
    rl._attempts.clear()
    rl._blocked.clear()
    rl._last_cleanup = time.time()


def _request(client_host="203.0.113.55", headers=None):
    req = SimpleNamespace()
    req.headers = headers or {}
    req.client = SimpleNamespace(host=client_host)
    return req


async def _user(session, tag="", password="RealPassword123!"):
    u = User(
        id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:8]}{tag}@test.example",
        password_hash=hash_password(password), status="active",
    )
    session.add(u)
    await session.flush()
    return u


# ── Password policy (§1: min 12 chars) ──────────────────────────────────

def test_register_rejects_password_under_12_chars():
    with pytest.raises(ValidationError):
        RegisterRequest(email="short@test.example", password="Short11!")  # 8 chars


def test_register_accepts_password_at_exactly_12_chars():
    req = RegisterRequest(email="ok@test.example", password="TwelveChars1")  # 12 chars
    assert req.password == "TwelveChars1"


# ── Register endpoint ────────────────────────────────────────────────────

class TestRegisterEndpoint:

    @pytest.mark.asyncio(loop_scope="function")
    async def test_creates_user_and_returns_active_status(self):
        async with _test_session_factory() as s:
            email = f"{uuid.uuid4().hex[:8]}-register@test.example"
            resp = await register(
                body=RegisterRequest(email=email, password="ValidPassword123!"),
                request=_request(),
                session=s,
            )
            assert resp.email == email
            assert resp.account_status == "active"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_rejects_duplicate_email(self):
        async with _test_session_factory() as s:
            email = f"{uuid.uuid4().hex[:8]}-dupe@test.example"
            await register(
                body=RegisterRequest(email=email, password="ValidPassword123!"),
                request=_request(),
                session=s,
            )
            with pytest.raises(HTTPException) as exc:
                await register(
                    body=RegisterRequest(email=email, password="AnotherPassword123!"),
                    request=_request(),
                    session=s,
                )
            assert exc.value.status_code == 409


# ── Login enumeration-timing side-channel ───────────────────────────────
# Not a wall-clock timing assertion (flaky under CI load) — instead proves
# both failure branches now pay the same bcrypt cost by asserting
# verify_password() is called exactly once either way.

class TestLoginTimingEqualization:

    @pytest.mark.asyncio(loop_scope="function")
    async def test_email_not_found_still_calls_verify_password_once(self):
        async with _test_session_factory() as s:
            with patch("app.api.v1.auth.verify_password", wraps=_real_verify_password) as spy:
                with pytest.raises(HTTPException) as exc:
                    await login(
                        body=LoginRequest(email="nobody-here@test.example", password="whatever12345"),
                        request=_request(),
                        session=s,
                    )
                assert exc.value.status_code == 401
                assert spy.call_count == 1, (
                    "email-not-found branch must run a dummy bcrypt check "
                    "so it costs the same as the wrong-password branch"
                )

    @pytest.mark.asyncio(loop_scope="function")
    async def test_wrong_password_calls_verify_password_once(self):
        async with _test_session_factory() as s:
            u = await _user(s, "wrongpw")
            await s.commit()
            with patch("app.api.v1.auth.verify_password", wraps=_real_verify_password) as spy:
                with pytest.raises(HTTPException) as exc:
                    await login(
                        body=LoginRequest(email=u.email, password="TotallyWrongPassword1"),
                        request=_request(),
                        session=s,
                    )
                assert exc.value.status_code == 401
                assert spy.call_count == 1

    @pytest.mark.asyncio(loop_scope="function")
    async def test_both_failure_branches_return_identical_error_body(self):
        async with _test_session_factory() as s:
            u = await _user(s, "identicalerr")
            await s.commit()
            with pytest.raises(HTTPException) as not_found_exc:
                await login(
                    body=LoginRequest(email="nobody-at-all@test.example", password="whatever12345"),
                    request=_request(),
                    session=s,
                )
            with pytest.raises(HTTPException) as wrong_pw_exc:
                await login(
                    body=LoginRequest(email=u.email, password="TotallyWrongPassword1"),
                    request=_request(),
                    session=s,
                )
            assert not_found_exc.value.status_code == wrong_pw_exc.value.status_code == 401
            assert not_found_exc.value.detail == wrong_pw_exc.value.detail


# ── Session revocation on logout ────────────────────────────────────────

class TestSessionRevocation:

    @pytest.mark.asyncio(loop_scope="function")
    async def test_token_rejected_immediately_after_logout(self):
        """The core Sprint 6 fix: logout must invalidate the bearer token
        itself, not just mark a DB row for bookkeeping while the token
        keeps working until its own JWT exp."""
        async with _test_session_factory() as s:
            password = "RealPassword123!"
            u = await _user(s, "logout", password=password)
            await s.commit()

            login_resp = await login(
                body=LoginRequest(email=u.email, password=password),
                request=_request(),
                session=s,
            )
            creds = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials=login_resp.access_token
            )

            resolved = await get_current_user(request=_request(), credentials=creds, session=s)
            assert resolved.id == u.id

            await logout(current_user=u, session=s)

            with pytest.raises(HTTPException) as exc:
                await get_current_user(request=_request(), credentials=creds, session=s)
            assert exc.value.status_code == 401

    @pytest.mark.asyncio(loop_scope="function")
    async def test_valid_jwt_with_no_backing_session_rejected(self):
        """A syntactically valid, unexpired, correctly-signed token is not
        enough on its own — get_current_user() also requires a live
        user_sessions row. A token minted without going through POST
        /auth/login (as create_access_token() does here) has no such row
        and must be rejected, not silently accepted."""
        async with _test_session_factory() as s:
            u = await _user(s, "nobacking")
            await s.commit()
            token = create_access_token(u.id)
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
            with pytest.raises(HTTPException) as exc:
                await get_current_user(request=_request(), credentials=creds, session=s)
            assert exc.value.status_code == 401


# ── JWT validation edge cases ────────────────────────────────────────────

class TestJwtValidation:

    @pytest.mark.asyncio(loop_scope="function")
    async def test_expired_jwt_rejected(self):
        from datetime import datetime, timedelta, timezone

        async with _test_session_factory() as s:
            u = await _user(s, "expired")
            await s.commit()
            expired_payload = {
                "sub": u.id,
                "iat": datetime.now(timezone.utc) - timedelta(hours=2),
                "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            }
            expired_token = jwt.encode(expired_payload, settings.jwt_secret, algorithm="HS256")
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=expired_token)
            with pytest.raises(HTTPException) as exc:
                await get_current_user(request=_request(), credentials=creds, session=s)
            assert exc.value.status_code == 401

    @pytest.mark.asyncio(loop_scope="function")
    async def test_tampered_signature_rejected(self):
        async with _test_session_factory() as s:
            u = await _user(s, "tampered")
            await s.commit()
            token = create_access_token(u.id)
            last_char = token[-1]
            tampered = token[:-1] + ("A" if last_char != "A" else "B")
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tampered)
            with pytest.raises(HTTPException) as exc:
                await get_current_user(request=_request(), credentials=creds, session=s)
            assert exc.value.status_code == 401

    @pytest.mark.asyncio(loop_scope="function")
    async def test_alg_none_token_rejected(self):
        """Classic JWT vuln: an attacker crafts alg=none with no
        signature, hoping the verifier trusts the token's own header.
        decode_access_token() passes algorithms=["HS256"] explicitly,
        which PyJWT enforces as an allow-list regardless of what the
        token claims — this regression-proofs that."""
        async with _test_session_factory() as s:
            u = await _user(s, "algnone")
            await s.commit()
            forged = jwt.encode({"sub": u.id}, key=None, algorithm="none")
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=forged)
            with pytest.raises(HTTPException) as exc:
                await get_current_user(request=_request(), credentials=creds, session=s)
            assert exc.value.status_code == 401

    @pytest.mark.asyncio(loop_scope="function")
    async def test_malformed_token_rejected(self):
        async with _test_session_factory() as s:
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-real-jwt")
            with pytest.raises(HTTPException) as exc:
                await get_current_user(request=_request(), credentials=creds, session=s)
            assert exc.value.status_code == 401


# ── audit_events immutability (DB-level trigger, migration 012) ─────────

class TestAuditEventsImmutability:

    @pytest.mark.asyncio(loop_scope="function")
    async def test_update_rejected_by_db_trigger(self):
        async with _test_session_factory() as s:
            u = await _user(s, "auditupd")
            event = AuditEvent(
                id=str(uuid.uuid4()), user_id=u.id, event_type="login",
                entity_type="user", entity_id=u.id, actor_type="user",
            )
            s.add(event)
            await s.commit()

            with pytest.raises(Exception) as exc:
                await s.execute(
                    text("UPDATE audit_events SET event_type = 'tampered' WHERE id = :id"),
                    {"id": event.id},
                )
            assert "append-only" in str(exc.value).lower()
            await s.rollback()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_delete_rejected_by_db_trigger(self):
        async with _test_session_factory() as s:
            u = await _user(s, "auditdel")
            event = AuditEvent(
                id=str(uuid.uuid4()), user_id=u.id, event_type="login",
                entity_type="user", entity_id=u.id, actor_type="user",
            )
            s.add(event)
            await s.commit()

            with pytest.raises(Exception) as exc:
                await s.execute(text("DELETE FROM audit_events WHERE id = :id"), {"id": event.id})
            assert "append-only" in str(exc.value).lower()
            await s.rollback()


# ── Security response headers ────────────────────────────────────────────

def test_security_headers_present_on_every_response():
    """main.py's security_headers_middleware must set all three headers
    on every response. Built on a throwaway minimal app (not app.main's
    real `app`) with the real middleware function attached, so this
    exercises the actual dispatch logic without needing `with
    TestClient(app):` (which would run app.main's real lifespan,
    including ensure_bucket_exists()'s call to MinIO at the Docker-
    internal `minio` hostname — unreachable from the host).

    Importing app.main at all pulls in app.api.v1.cvs ->
    app.services.file_validation -> `import magic` (python-magic).
    On this Windows host that segfaults the interpreter outright — the
    real libmagic1 is only ever installed inside the Docker image (see
    Dockerfile), nothing on the host provides a working one, and this is
    the first test in the suite to transitively import app.main at all.
    Pre-existing environment gap, unrelated to this module's own logic —
    stub `magic` before importing so this test can still exercise the
    real security_headers_middleware function. The actual header values
    were also verified directly against the live Docker API
    (curl -i http://localhost:8000/health), independent of this test.
    """
    import sys
    import types

    if "magic" not in sys.modules:
        _magic_stub = types.ModuleType("magic")
        _magic_stub.from_buffer = lambda *a, **k: "application/octet-stream"
        sys.modules["magic"] = _magic_stub

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.main import security_headers_middleware

    probe_app = FastAPI()
    probe_app.middleware("http")(security_headers_middleware)

    @probe_app.get("/probe")
    def probe():
        return {"ok": True}

    client = TestClient(probe_app)
    resp = client.get("/probe")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Content-Security-Policy") == "default-src 'none'"
