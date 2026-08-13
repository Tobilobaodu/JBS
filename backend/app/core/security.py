"""Authentication and security utilities.

- bcrypt password hashing (cost factor >= 12)
- JWT access token issuance and verification (short-lived, per spec)
- Refresh token generation (revocable, stored in user_sessions)
- get_current_user() checks both the JWT itself AND that a live,
  non-revoked user_sessions row backs it — a token surviving logout
  (revoked_at set) or an expired session is rejected immediately rather
  than remaining bearer-valid until its own JWT exp.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import get_session
from app.db.models import TrialSession, User, UserSession
from app.core.metrics import AUTH_FAILURE_COUNTER, AUTHZ_DENIED_COUNTER


def hash_password(password: str) -> str:
    """Hash a password with bcrypt (cost factor >= 12 per security plan)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its bcrypt hash. Timing-safe by bcrypt library."""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    """Issue a short-lived JWT access token.

    Payload contains ONLY user_id and expiry — no PII, roles, or sensitive data
    (per security plan §1: JWT is base64, not encrypted).
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(seconds=settings.jwt_expiry),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT access token. Raises JWTError on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


def generate_refresh_token() -> str:
    """Generate a secure random refresh token for server-side storage."""
    return secrets.token_urlsafe(64)


def hash_token(token: str) -> str:
    """One-way hash a token for storage lookup (displayed token vs stored hash)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Bearer token security scheme
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """FastAPI dependency: authenticate via Bearer token, return the User.

    Returns 401 for missing/invalid/expired tokens. Does NOT return 403 directly
    — that's the authorization layer's responsibility (IDOR checks per endpoint).
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )

    token = credentials.credentials

    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        AUTH_FAILURE_COUNTER.labels(reason="expired_token").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # A valid signature/expiry alone isn't enough — the session backing this
    # exact token must still be live. Without this check, logout's
    # revoked_at write (auth.py) is pure bookkeeping: the bearer token
    # itself stays usable until its own JWT exp, up to jwt_expiry seconds
    # later, contradicting the "invalidate on logout" requirement.
    session_result = await session.execute(
        select(UserSession).where(
            UserSession.access_token_hash == hash_token(token),
            UserSession.revoked_at.is_(None),
        )
    )
    user_session = session_result.scalar_one_or_none()

    if user_session is None:
        AUTH_FAILURE_COUNTER.labels(reason="revoked_token").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked or is invalid",
        )

    if user_session.expires_at <= datetime.now(timezone.utc):
        AUTH_FAILURE_COUNTER.labels(reason="revoked_token").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired",
        )

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not active",
        )

    return user


# ── Anonymous trial support (Sprint 2) ─────────────────────────────────


@dataclass
class RequestIdentity:
    """Whichever identity resolved a request: a real user, or a trial
    session — never both, never neither. Lets the small set of
    trial-eligible routes write `identity.user_id`/`identity.trial_session_id`
    instead of branching on which one is set at every call site.
    """

    user: User | None
    trial_session: TrialSession | None

    @property
    def user_id(self) -> str | None:
        return self.user.id if self.user else None

    @property
    def trial_session_id(self) -> str | None:
        return self.trial_session.id if self.trial_session else None


def ownership_denied(detail: str) -> HTTPException:
    """Central IDOR-denial chokepoint.

    Every route that 404s because the requester doesn't own the resource
    should ``raise ownership_denied(...)`` rather than raising HTTPException
    404 directly — this counts the denial once, in one place, so the §10
    IDOR-probing alert (prometheus/alert_rules.yml) is wired regardless of
    which route raised it, instead of being scattered per-route where a new
    route can forget to count it.
    """
    AUTHZ_DENIED_COUNTER.inc()
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def identity_owner_filter(model, identity: RequestIdentity):
    """Build the ownership WHERE clause for a trial-eligible model given a
    RequestIdentity: `model.user_id == ...` or `model.trial_session_id ==
    ...`, whichever the identity actually resolved to. Shared by every
    route that reads back a resource created via
    get_current_user_or_trial_session, so the two-way branch lives in one
    place instead of being re-derived per route.
    """
    if identity.user_id is not None:
        return model.user_id == identity.user_id
    return model.trial_session_id == identity.trial_session_id


async def get_current_user_or_trial_session(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> RequestIdentity:
    """FastAPI dependency for the small set of routes that support both a
    real authenticated user and an anonymous trial session (Sprint 2:
    POST /cvs, POST /job-posts/url, POST /job-posts/text, POST /matches,
    and their read-back counterparts).

    Deliberately NOT a modification of get_current_user() above — that
    function is used throughout the authenticated API surface and its
    behavior must not change for this one new use case. This wraps it
    instead: a valid Bearer token always resolves via get_current_user()
    unchanged and wins over a trial header, so a logged-in user hitting
    one of these routes is never accidentally treated as anonymous.
    Falls back to the X-Trial-Session-Id header only when no Bearer
    credentials are present at all.

    Every route that should stay authenticated-only (dashboard, cover
    letters, company tracking) keeps using get_current_user directly and
    is unaffected by this function's existence. Sprint 5 adds exports as
    a partial exception: POST /exports/cv/{draftId} uses this dependency
    too, since tailored CV generation itself is already trial-accessible
    end to end and exporting a CV a trial identity was allowed to
    generate shouldn't hit an account wall mid-flow — but
    POST /exports/cover-letter/{workflowId} and
    POST /exports/application-pack stay get_current_user-only, since both
    require a CoverLetterWorkflow, which is itself account-only.
    """
    if credentials is not None:
        user = await get_current_user(request, credentials, session)
        return RequestIdentity(user=user, trial_session=None)

    trial_session_id = request.headers.get("X-Trial-Session-Id")
    if not trial_session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token or trial session.",
        )

    result = await session.execute(
        select(TrialSession).where(TrialSession.id == trial_session_id)
    )
    trial_session = result.scalar_one_or_none()

    if trial_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid trial session.",
        )

    if trial_session.claimed_by_user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Trial session has already been claimed — sign in instead.",
        )

    if trial_session.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Trial session has expired.",
        )

    return RequestIdentity(user=None, trial_session=trial_session)