"""Orchestration service — creates processing jobs and enqueues worker tasks.

This is the synchronous handoff point from the API to the async queue.
API endpoints call these functions to persist job records and dispatch
tasks to Celery workers.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProcessingJob
from app.workers.tasks import (
    enqueue_docling_extract,
    enqueue_textract_extract,
    enqueue_merge_parse,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


async def create_processing_job(
    session: AsyncSession,
    job_type: str,
    source_entity_type: str,
    source_entity_id: str,
    user_id: str | None = None,
) -> ProcessingJob:
    """Create a processing_jobs row and enqueue the corresponding Celery task.

    Returns the job row so the API can return the job_id immediately.
    """
    job = ProcessingJob(
        job_type=job_type,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        user_id=user_id,
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


async def start_extraction_pipeline(
    session: AsyncSession, cv_file_id: str, user_id: str
) -> ProcessingJob:
    """Kick off the Docling → Textract → merge pipeline for a newly uploaded CV.

    Creates the first job (docling_extract) — the Docling worker will chain
    the Textract and merge jobs on completion.
    """
    return await create_processing_job(
        session=session,
        job_type="docling_extract",
        source_entity_type="cv_file",
        source_entity_id=cv_file_id,
        user_id=user_id,
    )