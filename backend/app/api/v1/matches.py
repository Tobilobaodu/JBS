"""Match endpoints — POST /matches, GET /matches/{matchId}.

Phase 3: creates a match analysis between a CV profile version and a job post.
All matching runs through the queue — the API returns 202 immediately.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.core.rate_limit import check_generation_rate_limit, get_client_key
from app.services.orchestration import enforce_concurrent_job_limit, mark_job_publish_failed
from app.db import get_session
from app.db.models import (
    AuditEvent,
    CvProfile,
    CvProfileVersion,
    CvSkillItem,
    JobPost,
    JobPostProfile,
    MatchRun,
    MatchEvidenceItem,
    ProcessingJob,
    User,
)
from app.core.security import (
    RequestIdentity,
    get_current_user,
    get_current_user_or_trial_session,
    identity_owner_filter,
    ownership_denied,
)
from app.workers.tasks import enqueue_match

router = APIRouter(tags=["matches"])
logger = get_logger(__name__)


# ── Pydantic schemas ─────────────────────────────────────────────────


class MatchRequest(BaseModel):
    cvProfileVersionId: str = Field(alias="cvProfileVersionId")
    jobPostId: str = Field(alias="jobPostId")

    class Config:
        populate_by_name = True


class MatchAccepted(BaseModel):
    matchId: str
    processingJobId: str


class EvidenceItemOut(BaseModel):
    id: str
    requirement_text: str = Field(alias="requirementText")
    requirement_type: str = Field(alias="requirementType")
    support_level: str = Field(alias="supportLevel")
    confidence: float | None = None
    source_references: list[str] | None = Field(None, alias="sourceReferences")
    suggestion: str | None = None
    warning: str | None = None

    class Config:
        from_attributes = True
        populate_by_name = True


class MatchResponse(BaseModel):
    id: str
    status: str
    score: float | None = None
    supported_count: int | None = Field(None, alias="supportedCount")
    partial_count: int | None = Field(None, alias="partialCount")
    unsupported_count: int | None = Field(None, alias="unsupportedCount")
    total_requirements: int | None = Field(None, alias="totalRequirements")
    summary_analysis: str | None = Field(None, alias="summaryAnalysis")
    evidence_items: list[EvidenceItemOut] | None = Field(None, alias="evidenceItems")
    error_message: str | None = Field(None, alias="errorMessage")
    created_at: str = Field(alias="createdAt")
    completed_at: str | None = Field(None, alias="completedAt")

    class Config:
        from_attributes = True
        populate_by_name = True


class MatchListItem(BaseModel):
    id: str
    job_post_id: str = Field(alias="jobPostId")
    job_title: str | None = Field(None, alias="jobTitle")
    employer: str | None = None
    status: str
    score: float | None = None
    created_at: str = Field(alias="createdAt")
    completed_at: str | None = Field(None, alias="completedAt")

    class Config:
        populate_by_name = True


class MatchListResponse(BaseModel):
    items: list[MatchListItem]
    total: int
    limit: int
    offset: int


# ──────────────────────────────────────────────────────────────────────
# POST /matches
# ──────────────────────────────────────────────────────────────────────


@router.post("/matches", response_model=MatchAccepted, status_code=202)
async def create_match(
    request: Request,
    body: MatchRequest,
    identity: RequestIdentity = Depends(get_current_user_or_trial_session),
    session: AsyncSession = Depends(get_session),
):
    """Create a match analysis between a CV profile and a job post.

    Trial-accessible (Sprint 2). Rate-limited per client IP (generation
    tier, see `10-security-plan.md` §9).
    """
    client_key = get_client_key(request)
    if not check_generation_rate_limit(client_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many match requests. Please wait and try again.",
        )

    # Validate CV profile version exists and belongs to this identity
    cv_result = await session.execute(
        select(CvProfileVersion).where(
            CvProfileVersion.id == body.cvProfileVersionId,
            identity_owner_filter(CvProfileVersion, identity),
        )
    )
    cv_profile = cv_result.scalar_one_or_none()
    if cv_profile is None:
        raise await ownership_denied(
            session, user_id=identity.user_id, entity_type="cv_profile_version",
            entity_id=body.cvProfileVersionId, detail="CV profile version not found",
        )

    # Look up job post profile from jobPostId (1:1 relationship), scoped
    # to this identity — without this join, any identity could match
    # against any job post's structured profile, not just their own.
    jp_result = await session.execute(
        select(JobPostProfile)
        .join(JobPost, JobPost.id == JobPostProfile.job_post_id)
        .where(
            JobPostProfile.job_post_id == body.jobPostId,
            identity_owner_filter(JobPost, identity),
        )
    )
    jp_profile = jp_result.scalar_one_or_none()
    if jp_profile is None:
        raise await ownership_denied(
            session, user_id=identity.user_id, entity_type="job_post",
            entity_id=body.jobPostId, detail="Job post not found or not yet structured",
        )

    # Create match_run row
    match_run = MatchRun(
        user_id=identity.user_id,
        trial_session_id=identity.trial_session_id,
        cv_profile_version_id=body.cvProfileVersionId,
        job_post_profile_id=jp_profile.id,
        status="pending",
    )
    session.add(match_run)
    await session.flush()

    # Create processing job after concurrency check
    await enforce_concurrent_job_limit(session, user_id=identity.user_id, trial_session_id=identity.trial_session_id)

    proc_job = ProcessingJob(
        job_type="match",
        source_entity_type="match_run",
        source_entity_id=match_run.id,
        user_id=identity.user_id,
        trial_session_id=identity.trial_session_id,
        status="pending",
    )
    session.add(proc_job)

    session.add(AuditEvent(
        user_id=identity.user_id,
        entity_type="match_run",
        entity_id=match_run.id,
        event_type="match",
        actor_type="user" if identity.user else "trial_session",
    ))

    await session.commit()
    try:
        enqueue_match(proc_job.id)
    except Exception as e:
        mark_job_publish_failed(proc_job, 'Failed to publish task to message broker.')
        await session.commit()
        logger.error('match_publish_failed', job_id=proc_job.id, error=str(e))
        raise

    logger.info(
        "match_created",
        match_id=match_run.id,
        job_id=proc_job.id,
        cv_version=cv_profile.id,
        job_post=jp_profile.id,
    )

    return MatchAccepted(
        matchId=match_run.id,
        processingJobId=proc_job.id,
    )


# ──────────────────────────────────────────────────────────────────────
# GET /matches — list
# ──────────────────────────────────────────────────────────────────────


@router.get("/matches", response_model=MatchListResponse)
async def list_matches(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """List match runs for the current user, with pagination.

    Account-only, matching GET /cvs and GET /job-posts' precedent — a
    trial session can already see its own single match via GET
    /matches/{matchId}, but a browsable list is an account-only feature.
    """
    total = (
        await session.execute(
            select(func.count()).select_from(MatchRun).where(MatchRun.user_id == current_user.id)
        )
    ).scalar_one()

    result = await session.execute(
        select(MatchRun, JobPostProfile)
        .join(JobPostProfile, JobPostProfile.id == MatchRun.job_post_profile_id)
        .where(MatchRun.user_id == current_user.id)
        .order_by(MatchRun.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = result.all()

    items = [
        MatchListItem(
            id=match.id,
            job_post_id=profile.job_post_id,
            job_title=profile.job_title,
            employer=profile.employer,
            status=match.status,
            score=match.score,
            created_at=match.created_at.isoformat(),
            completed_at=match.completed_at.isoformat() if match.completed_at else None,
        )
        for match, profile in rows
    ]

    return MatchListResponse(items=items, total=total, limit=limit, offset=offset)


# ──────────────────────────────────────────────────────────────────────
# GET /matches/{matchId}
# ──────────────────────────────────────────────────────────────────────


@router.get("/matches/{matchId}", response_model=MatchResponse)
async def get_match(
    matchId: str,
    identity: RequestIdentity = Depends(get_current_user_or_trial_session),
    session: AsyncSession = Depends(get_session),
):
    """Get a match analysis with its evidence items (IDOR-safe).

    Trial-accessible (Sprint 2) — a trial session needs to see its own
    match result before deciding to register.
    """
    result = await session.execute(
        select(MatchRun).where(
            MatchRun.id == matchId,
            identity_owner_filter(MatchRun, identity),
        )
    )
    match_run = result.scalar_one_or_none()
    if match_run is None:
        raise await ownership_denied(
            session, user_id=identity.user_id, entity_type="match_run",
            entity_id=matchId, detail="Match not found",
        )

    # Load evidence items
    evidence_result = await session.execute(
        select(MatchEvidenceItem).where(
            MatchEvidenceItem.match_run_id == matchId
        )
    )
    evidence_items = evidence_result.scalars().all()

    return MatchResponse(
        id=match_run.id,
        status=match_run.status,
        score=match_run.score,
        supported_count=match_run.supported_count,
        partial_count=match_run.partial_count,
        unsupported_count=match_run.unsupported_count,
        total_requirements=match_run.total_requirements,
        summary_analysis=match_run.summary_analysis,
        evidence_items=[
            EvidenceItemOut(
                id=ei.id,
                requirement_text=ei.requirement_text,
                requirement_type=ei.requirement_type,
                support_level=ei.support_level,
                confidence=ei.confidence,
                source_references=ei.source_references,
                suggestion=ei.suggestion,
                warning=ei.warning,
            )
            for ei in evidence_items
        ] if evidence_items else None,
        error_message=match_run.error_message,
        created_at=match_run.created_at.isoformat() if match_run.created_at else "",
        completed_at=match_run.completed_at.isoformat() if match_run.completed_at else None,
    )