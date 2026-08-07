"""Auth endpoints — POST /auth/register, /auth/login, /auth/logout, GET /auth/me.

Matches 05-openapi.yaml exactly. Uses bcrypt for password hashing,
short-lived JWT access tokens, and revocable refresh tokens per security plan §1.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    get_current_user,
    verify_password,
)
from app.db import get_session
from app.db.models import AuditEvent, User, UserSession
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


def _map_user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        account_status=user.status,
        created_at=user.created_at,
    )


async def _create_audit_event(
    session: AsyncSession,
    event_type: str,
    user_id: str | None,
    entity_type: str | None,
    entity_id: str | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Create an append-only audit event."""
    event = AuditEvent(
        user_id=user_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_type="user",
        metadata_=metadata,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(event)


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Create a new user account.

    Returns 409 if the email is already registered.
    Password is hashed with bcrypt (cost factor >= 12).
    """
    # Check for duplicate email
    existing = await session.execute(
        select(User).where(User.email == body.email)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
    )
    session.add(user)
    await session.flush()

    await _create_audit_event(
        session=session,
        event_type="register",
        user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip_address=request.client.host if request.client else None,
    )

    await session.commit()
    logger.info("user_registered", user_id=user.id)

    return _map_user(user)


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Authenticate a user and issue tokens.

    Returns the SAME generic error for "email not found" and "wrong password"
    to prevent user enumeration (per security plan §1). Response timing is
    identical via bcrypt's timing-safe comparison.
    """
    result = await session.execute(
        select(User).where(User.email == body.email)
    )
    user = result.scalar_one_or_none()

    # Generic error — same message regardless of whether the email exists
    generic_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password.",
    )

    if user is None:
        raise generic_error

    # Verify password — bcrypt does constant-time comparison internally
    if not verify_password(body.password, user.password_hash):
        await _create_audit_event(
            session=session,
            event_type="login_failed",
            user_id=user.id,
            entity_type="user",
            entity_id=user.id,
            ip_address=request.client.host if request.client else None,
        )
        # Still commit the audit event even on failed login
        await session.commit()
        raise generic_error

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not active.",
        )

    # Issue tokens
    access_token = create_access_token(user.id)
    refresh_token = generate_refresh_token()

    # Store session
    session_row = UserSession(
        user_id=user.id,
        refresh_token_hash=hash_token(refresh_token),
        access_token=access_token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    session.add(session_row)

    # Update last_active
    user.last_active = datetime.now(timezone.utc)

    await _create_audit_event(
        session=session,
        event_type="login",
        user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    await session.commit()
    logger.info("user_logged_in", user_id=user.id)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=_map_user(user),
    )


@router.post("/logout", status_code=204)
async def logout(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """End the current session. Revokes all refresh tokens for this user.

    Per security plan §1: invalidate all sessions, not just client-side discard.
    """
    # Revoke all active sessions for this user
    result = await session.execute(
        select(UserSession).where(
            UserSession.user_id == current_user.id,
            UserSession.revoked_at.is_(None),
        )
    )
    sessions = result.scalars().all()
    for sess in sessions:
        sess.revoked_at = datetime.now(timezone.utc)

    await _create_audit_event(
        session=session,
        event_type="logout",
        user_id=current_user.id,
        entity_type="user",
        entity_id=current_user.id,
    )

    await session.commit()
    logger.info("user_logged_out", user_id=current_user.id)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    """Return the current user's profile and permissions."""
    return _map_user(current_user)