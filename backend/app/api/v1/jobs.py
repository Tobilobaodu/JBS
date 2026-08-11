"""Jobs endpoint — GET /jobs/{jobId}.

Matches 05-openapi.yaml. The single source of truth for async processing status
(per modelling rule 6: the frontend must poll here, not infer from domain tables).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.db.models import ProcessingJob
from app.schemas.jobs import ProcessingJobResponse
from app.core.security import RequestIdentity, get_current_user_or_trial_session, identity_owner_filter
from app.core.logging import get_logger

router = APIRouter(tags=["jobs"])
logger = get_logger(__name__)


@router.get("/jobs/{job_id}", response_model=ProcessingJobResponse)
async def get_job_status(
    job_id: str,
    identity: RequestIdentity = Depends(get_current_user_or_trial_session),
    session: AsyncSession = Depends(get_session),
):
    """Get the status of an async processing job.

    Returns 404 if the job doesn't exist or belongs to another identity.
    Trial-accessible (Sprint 2) — this is the only way a trial session can
    know when its upload/match finished processing.
    """
    result = await session.execute(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            identity_owner_filter(ProcessingJob, identity),
        )
    )
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found."
        )

    return ProcessingJobResponse(
        id=job.id,
        job_type=job.job_type,
        source_entity_type=job.source_entity_type,
        source_entity_id=job.source_entity_id,
        status=job.status,
        retry_count=job.retry_count,
        last_error=job.last_error,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )