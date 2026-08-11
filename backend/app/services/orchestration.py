"""Orchestration service — creates processing jobs and enqueues worker tasks.

This is the synchronous handoff point from the API to the async queue.
API endpoints call these functions to persist job records and dispatch
tasks to Celery workers.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.db.models import ProcessingJob, TrialSession, User
from fastapi import HTTPException, status as fastapi_status
from app.core.config import settings
from app.workers.tasks import (
    enqueue_docling_extract,
    enqueue_textract_extract,
    enqueue_merge_parse,
)
from datetime import datetime, timezone
from app.core.logging import get_logger

logger = get_logger(__name__)


_ACTIVE_JOB_STATUSES = frozenset({'pending', 'queued', 'processing', 'retrying'})


async def enforce_concurrent_job_limit(
    session, user_id: str | None = None, trial_session_id: str | None = None,
) -> None:
    """Enforce the per-identity concurrent-job cap, for a real user or a
    trial session — exactly one, never both (Sprint 2 extends this from
    user-only). Locks the owning row (User or TrialSession) with FOR
    UPDATE before counting, so two concurrent requests from the same
    identity can't both read "under limit" and both proceed — see
    test_job_concurrency_limit.py for the race test this closes.
    """
    if (user_id is None) == (trial_session_id is None):
        raise ValueError(
            "enforce_concurrent_job_limit requires exactly one of user_id/trial_session_id"
        )

    limit = settings.max_concurrent_jobs_per_user

    if user_id is not None:
        lock = await session.execute(
            select(User.id).where(User.id == user_id).with_for_update()
        )
        lock.all()
        owner_filter = ProcessingJob.user_id == user_id
    else:
        lock = await session.execute(
            select(TrialSession.id).where(TrialSession.id == trial_session_id).with_for_update()
        )
        lock.all()
        owner_filter = ProcessingJob.trial_session_id == trial_session_id

    active = (await session.execute(
        select(func.count()).select_from(ProcessingJob).where(
            owner_filter,
            ProcessingJob.status.in_(_ACTIVE_JOB_STATUSES),
        )
    )).scalar_one()
    if active >= limit:
        raise HTTPException(
            fastapi_status.HTTP_429_TOO_MANY_REQUESTS,
            detail='Too many active processing jobs. Wait for an existing job to finish, then try again.',
        )


async def create_processing_job(
    session: AsyncSession,
    job_type: str,
    source_entity_type: str,
    source_entity_id: str,
    user_id: str | None = None,
    trial_session_id: str | None = None,
) -> ProcessingJob:
    """Create a processing_jobs row and enqueue the corresponding Celery task.

    Exactly one of user_id/trial_session_id must be set — matches the
    ck_processing_jobs_exactly_one_owner DB constraint; this check exists
    so a caller bug surfaces here, not as an opaque constraint violation
    mid-transaction.

    Returns the job row so the API can return the job_id immediately.
    """
    if not user_id and not trial_session_id:
        raise ValueError("create_processing_job requires user_id or trial_session_id")

    await enforce_concurrent_job_limit(session, user_id=user_id, trial_session_id=trial_session_id)

    job = ProcessingJob(
        job_type=job_type,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        user_id=user_id,
        trial_session_id=trial_session_id,
        status="queued",
    )
    session.add(job)
    await session.flush()  # get the generated id without committing yet

    # Dispatch to the correct Celery queue based on job_type
    if job_type == "docling_extract":
        enqueue_docling_extract(str(job.id))
    elif job_type == "textract_extract":
        enqueue_textract_extract(str(job.id))
    elif job_type == "merge_parse":
        enqueue_merge_parse(str(job.id))
    else:
        logger.warning("unknown_job_type_not_enqueued", job_type=job_type)
        job.status = "failed"
        job.last_error = f"Unknown job type: {job_type}"

    logger.info(
        "job_created",
        job_id=str(job.id),
        job_type=job_type,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
    )

    return job




def mark_job_publish_failed(job: ProcessingJob, error: str) -> None:
    """Set the standard publish-failure terminal state on a job row.

    Called by every route that uses commit-then-enqueue when the broker
    publish fails, so the persisted job does not permanently occupy an
    active concurrency slot.
    """
    job.status = "failed"
    job.last_error = error
    job.failed_at = datetime.now(timezone.utc)
async def start_extraction_pipeline(
    session: AsyncSession,
    cv_file_id: str,
    user_id: str | None = None,
    trial_session_id: str | None = None,
) -> ProcessingJob:
    """Kick off the Docling → Textract → merge pipeline for a newly uploaded CV.

    Creates the first job (docling_extract) — the Docling worker will chain
    the Textract and merge jobs on completion. Accepts either a real user
    or a trial session (Sprint 2) — exactly one, per create_processing_job.
    """
    return await create_processing_job(
        session=session,
        job_type="docling_extract",
        source_entity_type="cv_file",
        source_entity_id=cv_file_id,
        user_id=user_id,
        trial_session_id=trial_session_id,
    )