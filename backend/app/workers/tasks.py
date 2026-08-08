"""Celery task enqueue helpers.

These functions are called synchronously from the orchestration service
to dispatch jobs to Celery workers. The actual task implementations
(which run inside Celery worker processes) are in worker_jobs.py.
"""

from celery import Celery
from app.core.config import settings

# Celery app instance — shared between the API (for enqueueing) and workers
celery_app = Celery(
    "cv_tailoring",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Autodiscover tasks from worker_jobs (avoids circular import)
    imports=("app.workers.worker_jobs",),
)


def enqueue_docling_extract(job_id: str) -> None:
    """Dispatch a Docling extraction job to the docling_extract queue."""
    celery_app.send_task(
        "app.workers.worker_jobs.process_docling_extract",
        args=[job_id],
        queue="docling_extract",
    )


def enqueue_textract_extract(job_id: str) -> None:
    """Dispatch a Textract extraction job to the textract_extract queue."""
    celery_app.send_task(
        "app.workers.worker_jobs.process_textract_extract",
        args=[job_id],
        queue="textract_extract",
    )


def enqueue_merge_parse(job_id: str) -> None:
    """Dispatch a merge + parse job to the merge_parse queue."""
    celery_app.send_task(
        "app.workers.worker_jobs.process_merge_parse",
        args=[job_id],
        queue="merge_parse",
    )


# ──────────────────────────────────────────────────────────────────────
# Phase 2: Job post ingestion
# ──────────────────────────────────────────────────────────────────────


def enqueue_job_post_fetch(job_id: str) -> None:
    """Dispatch an SSRF-safe URL fetch job to the job_post_fetch queue."""
    celery_app.send_task(
        "app.workers.worker_jobs.process_job_post_fetch",
        args=[job_id],
        queue="job_post_fetch",
    )


def enqueue_cv_parse(job_id: str) -> None:
    """Dispatch a CV structured-profile extraction job to the cv_parse queue."""
    celery_app.send_task(
        "app.workers.worker_jobs.process_cv_parse",
        args=[job_id],
        queue="cv_parse",
    )


def enqueue_match(job_id: str) -> None:
    """Dispatch a match analysis job to the match queue."""
    celery_app.send_task(
        "app.workers.worker_jobs.process_match",
        args=[job_id],
        queue="match",
    )


def enqueue_job_post_parse(job_id: str) -> None:
    """Dispatch a job post structuring job to the job_post_parse queue."""
    celery_app.send_task(
        "app.workers.worker_jobs.process_job_post_parse",
        args=[job_id],
        queue="job_post_parse",
    )
