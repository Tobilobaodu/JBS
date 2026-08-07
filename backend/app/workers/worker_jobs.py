"""Celery task implementations for the extraction pipeline.

Each task:
1. Loads the processing_job from the database
2. Runs the extraction/merge logic
3. Writes results to the database
4. Enqueues the next step in the pipeline
5. Updates job status (processing → completed / failed)

Per security plan §2: Docling worker runs with no outbound network.
Textract worker needs outbound to AWS Textract endpoint only.
"""

import time
import structlog
from datetime import datetime, timezone

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import select, create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import (
    JOB_THROUGHPUT,
    JOB_DURATION_SECONDS,
    EXTRACTION_CHARS,
    MERGE_STRATEGY_COUNTER,
    STRUCTURAL_ANOMALY_COUNTER,
)
from app.core.storage import download_file
from app.db.models import (
    CvFile,
    CvExtractionPass,
    CvRawText,
    ProcessingJob,
)
from app.extraction.parser_interface import ExtractionResult
from app.extraction.docling_parser import DoclingParser
from app.extraction.merge import merge_extractions
from app.workers.tasks import (
    enqueue_textract_extract,
    enqueue_merge_parse,
)

logger = get_logger(__name__)

# Synchronous engine for Celery workers (Celery tasks are not async)
_sync_engine = create_engine(settings.database_url)


def _get_sync_session() -> Session:
    return Session(_sync_engine)


# ──────────────────────────────────────────────────────────────────────
# Docling extraction worker
# ──────────────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
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

        job.status = "processing"
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
        job.status = "completed"
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

        # Enqueue Textract as the next step
        enqueue_textract_extract(job_id)

    except Exception as e:
        duration_s = time.monotonic() - t_start
        logger.error("docling_extract_failed", job_id=job_id, error=str(e))
        JOB_THROUGHPUT.labels(job_type="docling_extract", status="failed").inc()
        JOB_DURATION_SECONDS.labels(job_type="docling_extract").observe(duration_s)
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


# ──────────────────────────────────────────────────────────────────────
# Textract extraction worker
# ──────────────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    name="app.workers.worker_jobs.process_textract_extract",
    queue="textract_extract",
)
def process_textract_extract(self, job_id: str) -> None:
    """Run Amazon Textract second-pass extraction.

    If TEXTRACT_ENABLED is false, writes a placeholder pass and continues.
    Per spec: Textract is a core part of the pipeline, not optional — but
    local dev can run without it while credentials are pending.
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

        if not settings.textract_enabled:
            logger.warning(
                "textract_disabled_skipping",
                cv_id=cv_file.id,
                hint="Set TEXTRACT_ENABLED=true and configure AWS credentials.",
            )
            # Write a placeholder pass so merge can continue
            pass_record = CvExtractionPass(
                cv_file_id=cv_file.id,
                pass_type="textract",
                attempt_number=_get_next_attempt(session, cv_file.id, "textract"),
                extracted_text="[Textract disabled — Docling-only extraction]",
                engine="amazon-textract",
                engine_version="pending",
                confidence_score=None,
                characters=0,
                pages=None,
                processing_duration_ms=0,
            )
            session.add(pass_record)
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            session.commit()

            # Still enqueue merge so the pipeline continues with Docling-only data
            enqueue_merge_parse(job_id)
            return

        # Real Textract call — uses async API (start → poll → collect)
        # because detect_document_text (sync) only supports images, not PDFs.
        import boto3
        from botocore.config import Config as BotoConfig

        s3 = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            config=BotoConfig(signature_version="s3v4"),
        )
        textract = boto3.client(
            "textract",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )

        # Download from MinIO (where the upload service stored it)
        file_content = download_file_sync(cv_file.storage_key)

        # Upload to real AWS S3 so Textract async API can reach it
        textract_s3_key = f"textract-input/{cv_file.id}/{cv_file.filename}"
        s3.put_object(
            Bucket=settings.s3_bucket_name,
            Key=textract_s3_key,
            Body=file_content,
            ContentType=cv_file.mime_type or "application/pdf",
        )
        logger.info("textract_s3_uploaded", key=textract_s3_key, size=len(file_content))

        start = time.monotonic()

        try:
            # Start async text detection
            start_response = textract.start_document_text_detection(
                DocumentLocation={
                    "S3Object": {
                        "Bucket": settings.s3_bucket_name,
                        "Name": textract_s3_key,
                    }
                }
            )
            textract_job_id = start_response["JobId"]
            logger.info("textract_async_started", textract_job_id=textract_job_id)

            # Poll for completion (max ~120 seconds)
            max_polls = 60
            poll_interval = 2  # seconds
            response = None

            for attempt in range(max_polls):
                response = textract.get_document_text_detection(
                    JobId=textract_job_id
                )
                status = response["JobStatus"]
                if status == "SUCCEEDED":
                    logger.info(
                        "textract_async_complete",
                        textract_job_id=textract_job_id,
                        attempts=attempt + 1,
                    )
                    break
                elif status == "FAILED":
                    raise RuntimeError(
                        f"Textract async job failed: {response.get('StatusMessage', 'unknown')}"
                    )
                elif status == "PARTIAL_SUCCESS":
                    logger.warning(
                        "textract_partial_success",
                        textract_job_id=textract_job_id,
                    )
                    break
                time.sleep(poll_interval)
            else:
                raise TimeoutError(
                    f"Textract async job {textract_job_id} did not complete within {max_polls * poll_interval}s"
                )

            # Collect all pages of results
            lines = []
            pages = set()
            all_blocks = []
            next_token = response.get("NextToken") if response else None

            while True:
                kwargs = {"JobId": textract_job_id}
                if next_token:
                    kwargs["NextToken"] = next_token
                page_response = textract.get_document_text_detection(**kwargs)
                blocks = page_response.get("Blocks", [])
                all_blocks.extend(blocks)
                for block in blocks:
                    if block.get("BlockType") == "LINE":
                        lines.append(block.get("Text", ""))
                    if block.get("BlockType") == "PAGE":
                        pages.add(block.get("Page", 0))
                next_token = page_response.get("NextToken")
                if not next_token:
                    break

            extracted_text = "\n".join(lines)
            duration_ms = int((time.monotonic() - start) * 1000)

            pass_record = CvExtractionPass(
                cv_file_id=cv_file.id,
                pass_type="textract",
                attempt_number=_get_next_attempt(session, cv_file.id, "textract"),
                extracted_text=extracted_text,
                raw_output={"blocks": all_blocks},
                engine="amazon-textract",
                engine_version="start_document_text_detection",
                confidence_score=_average_textract_confidence(
                    {"Blocks": all_blocks}
                ),
                characters=len(extracted_text),
                pages=len(pages) if pages else None,
                processing_duration_ms=duration_ms,
            )
            session.add(pass_record)

            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            session.commit()

            duration_s = time.monotonic() - t_start
            logger.info(
                "textract_extract_complete",
                job_id=job_id,
                cv_id=cv_file.id,
                chars=len(extracted_text),
                pages=len(pages),
                duration_ms=duration_ms,
            )

            # Metrics
            JOB_THROUGHPUT.labels(job_type="textract_extract", status="completed").inc()
            JOB_DURATION_SECONDS.labels(job_type="textract_extract").observe(duration_s)
            EXTRACTION_CHARS.labels(pass_type="textract").observe(len(extracted_text))

            # Enqueue merge
            enqueue_merge_parse(job_id)

        finally:
            # Clean up the temporary S3 object
            try:
                s3.delete_object(
                    Bucket=settings.s3_bucket_name,
                    Key=textract_s3_key,
                )
                logger.info("textract_s3_cleaned_up", key=textract_s3_key)
            except Exception as cleanup_err:
                logger.warning(
                    "textract_s3_cleanup_failed",
                    key=textract_s3_key,
                    error=str(cleanup_err),
                )

    except Exception as e:
        duration_s = time.monotonic() - t_start
        logger.error("textract_extract_failed", job_id=job_id, error=str(e))
        JOB_THROUGHPUT.labels(job_type="textract_extract", status="failed").inc()
        JOB_DURATION_SECONDS.labels(job_type="textract_extract").observe(duration_s)
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


# ──────────────────────────────────────────────────────────────────────
# Merge + structural validation worker
# ──────────────────────────────────────────────────────────────────────


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


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def download_file_sync(storage_key: str) -> bytes:
    """Synchronous wrapper for storage download (Celery tasks are sync)."""
    import boto3
    from botocore.config import Config as BotoConfig

    if settings.minio_endpoint and "minio" in settings.minio_endpoint:
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            aws_access_key_id=settings.minio_root_user,
            aws_secret_access_key=settings.minio_root_password,
            region_name=settings.aws_region,
            config=BotoConfig(signature_version="s3v4"),
        )
    else:
        s3 = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )

    response = s3.get_object(Bucket=settings.s3_bucket_name, Key=storage_key)
    return response["Body"].read()


def _get_next_attempt(session: Session, cv_file_id: str, pass_type: str) -> int:
    """Get the next attempt_number for a given pass_type on a cv_file."""
    from sqlalchemy import text

    max_attempt = session.execute(
        text(
            "SELECT COALESCE(MAX(attempt_number), 0) FROM cv_extraction_passes "
            "WHERE cv_file_id = :cv_id AND pass_type = :pt"
        ),
        {"cv_id": cv_file_id, "pt": pass_type},
    ).scalar()
    return (max_attempt or 0) + 1


def _average_textract_confidence(response: dict) -> float | None:
    """Compute average confidence from Textract LINE blocks."""
    confidences = []
    for block in response.get("Blocks", []):
        if block.get("BlockType") == "LINE" and "Confidence" in block:
            confidences.append(block["Confidence"])
    if not confidences:
        return None
    return round(sum(confidences) / len(confidences) / 100, 2)


