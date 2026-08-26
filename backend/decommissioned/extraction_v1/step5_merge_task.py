"""DECOMMISSIONED — moved verbatim from app/workers/worker_jobs.py.
Not imported by the running pipeline. Kept for reference and restore.
See decommissioned/README.md.
"""

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="app.workers.worker_jobs.process_merge_parse",
    queue="merge_parse",
)
def process_merge_parse(self, job_id: str) -> None:
    """Merge Docling and Textract passes into canonical extraction.

    1. Load both extraction passes
    2. Run structural validation
    3. Write cv_raw_text row
    4. Update cv_files status to 'completed'
    """
    structlog.contextvars.bind_contextvars(job_id=job_id)
    t_start = time.monotonic()
    session = _get_sync_session()
    try:
        job = session.get(ProcessingJob, job_id)
        if job is None:
            logger.error("job_not_found", job_id=job_id)
            return

        job.status = "processing"
        session.commit()

        cv_file = session.get(CvFile, job.source_entity_id)
        if cv_file is None:
            raise ValueError(f"CV file {job.source_entity_id} not found")

        # Load both passes
        docling_pass = session.execute(
            select(CvExtractionPass).where(
                CvExtractionPass.cv_file_id == cv_file.id,
                CvExtractionPass.pass_type == "docling",
            ).order_by(CvExtractionPass.attempt_number.desc())
        ).scalar_one_or_none()

        textract_pass = session.execute(
            select(CvExtractionPass).where(
                CvExtractionPass.cv_file_id == cv_file.id,
                CvExtractionPass.pass_type == "textract",
            ).order_by(CvExtractionPass.attempt_number.desc())
        ).scalar_one_or_none()

        if docling_pass is None:
            raise ValueError("No Docling pass found — cannot merge.")

        docling_result = ExtractionResult(
            extracted_text=docling_pass.extracted_text,
            raw_output=docling_pass.raw_output,
            confidence_score=docling_pass.confidence_score,
            characters=docling_pass.characters,
            pages=docling_pass.pages,
            processing_duration_ms=docling_pass.processing_duration_ms,
        )

        if textract_pass is not None:
            textract_result = ExtractionResult(
                extracted_text=textract_pass.extracted_text,
                raw_output=textract_pass.raw_output,
                confidence_score=textract_pass.confidence_score,
                characters=textract_pass.characters,
                pages=textract_pass.pages,
                processing_duration_ms=textract_pass.processing_duration_ms,
            )
        else:
            # No Textract pass — use Docling alone
            textract_result = docling_result

        # Merge
        canonical_text, merge_strategy, structural_validation = merge_extractions(
            docling_result, textract_result
        )

        # Write merged result
        raw_text = CvRawText(
            cv_file_id=cv_file.id,
            canonical_text=canonical_text,
            characters=len(canonical_text),
            merge_strategy=merge_strategy,
            merge_strategy_metadata={
                "docling_pass_id": str(docling_pass.id) if docling_pass else None,
                "textract_pass_id": str(textract_pass.id) if textract_pass else None,
            },
            ocr_used=textract_pass is not None,
            structural_validation_result=structural_validation,
        )
        session.add(raw_text)

        # Update CV file status
        cv_file.status = "completed"

        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

        duration_s = time.monotonic() - t_start
        logger.info(
            "merge_parse_complete",
            job_id=job_id,
            cv_id=cv_file.id,
            strategy=merge_strategy,
            anomaly=structural_validation.get("anomaly_detected"),
            duration_ms=int(duration_s * 1000),
        )

        # Metrics
        JOB_THROUGHPUT.labels(job_type="merge_parse", status="completed").inc()
        JOB_DURATION_SECONDS.labels(job_type="merge_parse").observe(duration_s)
        MERGE_STRATEGY_COUNTER.labels(strategy=merge_strategy).inc()
        anomaly_detected = str(
            structural_validation.get("anomaly_detected", False)
        )
        STRUCTURAL_ANOMALY_COUNTER.labels(
            anomaly_detected=anomaly_detected
        ).inc()

        # Update job_type to reflect current pipeline stage before handoff
        job.job_type = "cv_parse"
        session.commit()

        # Phase 2: enqueue CV structured profile extraction
        enqueue_cv_parse(job_id)

    except Exception as e:
        duration_s = time.monotonic() - t_start
        logger.error("merge_parse_failed", job_id=job_id, error=str(e))
        JOB_THROUGHPUT.labels(job_type="merge_parse", status="failed").inc()
        JOB_DURATION_SECONDS.labels(job_type="merge_parse").observe(duration_s)
        try:
            job.status = "failed"
            job.last_error = str(e)
            job.failed_at = datetime.now(timezone.utc)
            cv_file = session.get(CvFile, job.source_entity_id)
            if cv_file:
                cv_file.status = "failed"
                cv_file.error_message = str(e)
            session.commit()
        except Exception:
            session.rollback()
        raise
    finally:
        session.close()
        structlog.contextvars.unbind_contextvars("job_id")


