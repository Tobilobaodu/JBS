"""Match endpoints — POST /matches, GET /matches/{matchId}.

Phase 3: creates a match analysis between a CV profile version and a job post.
All matching runs through the queue — the API returns 202 immediately.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.db import get_session
from app.db.models import (
    AuditEvent,
    CvProfile,
    CvProfileVersion,
    CvSkillItem,
    JobPostProfile,
    MatchRun,
    MatchEvidenceItem,
    ProcessingJob,
    User,
)
from app.core.security import get_current_user
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
    requirementText: str = Field(alias="requirement_text")
    requirementType: str = Field(alias="requirement_type")
    supportLevel: str = Field(alias="support_level")
    confidence: float | None = None
    sourceReferences: list[str] | None = Field(None, alias="source_references")
    suggestion: str | None = None
    warning: str | None = None

    class Config:
        from_attributes = True
        populate_by_name = True


class MatchResponse(BaseModel):
    id: str
    status: str
    score: float | None = None
    supportedCount: int | None = Field(None, alias="supported_count")
    partialCount: int | None = Field(None, alias="partial_count")
    unsupportedCount: int | None = Field(None, alias="unsupported_count")
    totalRequirements: int | None = Field(None, alias="total_requirements")
    summaryAnalysis: str | None = Field(None, alias="summary_analysis")
    evidenceItems: list[EvidenceItemOut] | None = Field(None, alias="evidence_items")
    errorMessage: str | None = Field(None, alias="error_message")
    createdAt: str = Field(alias="created_at")
    completedAt: str | None = Field(None, alias="completed_at")

    class Config:
        from_attributes = True
        populate_by_name = True


# ──────────────────────────────────────────────────────────────────────
# POST /matches
# ──────────────────────────────────────────────────────────────────────


@router.post("/matches", response_model=MatchAccepted, status_code=202)
async def create_match(
    request: Request,
    body: MatchRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Create a match analysis between a CV profile and a job post."""
    # Validate CV profile version exists and belongs to user
    cv_result = await session.execute(
        select(CvProfileVersion).where(
            CvProfileVersion.id == body.cvProfileVersionId,
            CvProfileVersion.user_id == current_user.id,
        )
    )
    cv_profile = cv_result.scalar_one_or_none()
    if cv_profile is None:
        raise HTTPException(status_code=404, detail="CV profile version not found")

    # Look up job post profile from jobPostId (1:1 relationship)
    jp_result = await session.execute(
        select(JobPostProfile).where(
            JobPostProfile.job_post_id == body.jobPostId,
        )
    )
    jp_profile = jp_result.scalar_one_or_none()
    if jp_profile is None:
        raise HTTPException(status_code=404, detail="Job post not found or not yet structured")

    # Create match_run row
    match_run = MatchRun(
        user_id=current_user.id,
        cv_profile_version_id=body.cvProfileVersionId,
        job_post_profile_id=jp_profile.id,
        status="pending",
    )
    session.add(match_run)
    await session.flush()

    # Create processing job
    proc_job = ProcessingJob(
        job_type="match",
        source_entity_type="match_run",
        source_entity_id=match_run.id,
        user_id=current_user.id,
        status="pending",
    )
    session.add(proc_job)

    session.add(AuditEvent(
        user_id=current_user.id,
        entity_type="match_run",
        entity_id=match_run.id,
        event_type="match",
        actor_type="user",
    ))

    await session.commit()

    enqueue_match(proc_job.id)

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
# GET /matches/{matchId}
# ──────────────────────────────────────────────────────────────────────


@router.get("/matches/{matchId}", response_model=MatchResponse)
async def get_match(
    matchId: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get a match analysis with its evidence items (IDOR-safe)."""
    result = await session.execute(
        select(MatchRun).where(
            MatchRun.id == matchId,
            MatchRun.user_id == current_user.id,
        )
    )
    match_run = result.scalar_one_or_none()
    if match_run is None:
        raise HTTPException(status_code=404, detail="Match not found")

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