"""DECOMMISSIONED — moved verbatim from app/workers/worker_jobs.py.
Not imported by the running pipeline. Kept for reference and restore.
See decommissioned/README.md.
"""

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    # Only retryable-classified failures (timeouts, connection errors,
    # 429/5xx) get Celery's automatic retry — a malformed-file/validation
    # failure retrying 3 times just delays the same inevitable failure by
    # ~a minute. See classify_error/RetryableWorkerError/PermanentWorkerError
    # in app/core/job_states.py; this is the one task piloting the pattern,
    # not yet rolled out to the other 13 (a deliberate, separate follow-up —
    # each needs its own verification, same reasoning as the docling version
    # bump's risk-tiering).
    autoretry_for=(RetryableWorkerError,),
    name="app.workers.worker_jobs.process_docling_extract",
    queue="docling_extract",
)
def process_docling_extract(self, job_id: str) -> None:
    """Run Docling first-pass extraction against an uploaded CV.

    1. Load the job and CV file
    2. Download from storage
    3. Parse with DoclingParser
    4. Write CvExtractionPass row
    5. Update job status
    6. Enqueue Textract pass
    """
    # Bind correlation ID so all log lines carry this job_id
    structlog.contextvars.bind_contextvars(job_id=job_id)

    t_start = time.monotonic()
    session = _get_sync_session()
    try:
        job = session.get(ProcessingJob, job_id)
        if job is None:
            logger.error("job_not_found", job_id=job_id)
            return

        transition_job_status(job, ProcessingStatus.PROCESSING)
        job.started_at = datetime.now(timezone.utc)
        session.commit()

        cv_file = session.get(CvFile, job.source_entity_id)
        if cv_file is None:
            raise ValueError(f"CV file {job.source_entity_id} not found")

        # Download the file
        file_content = download_file_sync(cv_file.storage_key)
        logger.info("docling_downloaded", cv_id=cv_file.id, size=len(file_content))

        # Parse
        parser = DoclingParser()
        result = parser.parse_sync(file_content, cv_file.mime_type)

        # Store extraction pass
        pass_record = CvExtractionPass(
            cv_file_id=cv_file.id,
            pass_type="docling",
            attempt_number=_get_next_attempt(session, cv_file.id, "docling"),
            extracted_text=str(result.extracted_text),
            raw_output=result.raw_output,
            engine=result.engine,
            engine_version=result.engine_version,
            confidence_score=result.confidence_score,
            characters=result.characters,
            pages=result.pages,
            processing_duration_ms=result.processing_duration_ms,
        )
        session.add(pass_record)

        # Update CV file status
        cv_file.status = "extracting"

        # Mark job complete
        transition_job_status(job, ProcessingStatus.COMPLETED)
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

        duration_s = time.monotonic() - t_start
        logger.info(
            "docling_extract_complete",
            job_id=job_id,
            cv_id=cv_file.id,
            characters=result.characters,
            duration_ms=result.processing_duration_ms,
        )

        # Metrics
        JOB_THROUGHPUT.labels(job_type="docling_extract", status="completed").inc()
        JOB_DURATION_SECONDS.labels(job_type="docling_extract").observe(duration_s)
        EXTRACTION_CHARS.labels(pass_type="docling").observe(result.characters)

        # Update job_type to reflect current pipeline stage before handoff
        job.job_type = "textract_extract"
        session.commit()

        # Enqueue Textract as the next step
        enqueue_textract_extract(job_id)

    except Exception as e:
        duration_s = time.monotonic() - t_start
        logger.error("docling_extract_failed", job_id=job_id, error=str(e))
        JOB_THROUGHPUT.labels(job_type="docling_extract", status="failed").inc()
        JOB_DURATION_SECONDS.labels(job_type="docling_extract").observe(duration_s)

        error_type = classify_error(e)
        # Celery only auto-retries RetryableWorkerError (see autoretry_for
        # above) and only up to max_retries — anything else, or a
        # retryable error on its last allowed attempt, is genuinely done.
        is_final_attempt = (
            error_type is not RetryableWorkerError
            or self.request.retries >= self.max_retries
        )
        try:
            target_status = ProcessingStatus.FAILED if is_final_attempt else ProcessingStatus.RETRYING
            transition_job_status(job, target_status, error=str(e))
            if is_final_attempt:
                job.failed_at = datetime.now(timezone.utc)
                cv_file = session.get(CvFile, job.source_entity_id)
                if cv_file:
                    cv_file.status = "failed"
                    cv_file.error_message = str(e)
            session.commit()
        except Exception:
            session.rollback()
        raise error_type(str(e)) from e
    finally:
        session.close()
        structlog.contextvars.unbind_contextvars("job_id")


