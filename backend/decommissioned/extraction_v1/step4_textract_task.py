"""DECOMMISSIONED — moved verbatim from app/workers/worker_jobs.py.
Not imported by the running pipeline. Kept for reference and restore.
See decommissioned/README.md.
"""

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

        # Textract's start_document_text_detection only accepts PDF/PNG/JPEG/
        # TIFF — DOCX (the only other type validate_file_type() lets through
        # on upload, see app/services/file_validation.py) always fails with
        # INVALID_IMAGE_TYPE. That's not a transient failure worth retrying
        # or worth failing the whole CV over — Docling already extracted it
        # fine — so DOCX takes the same skip-and-continue path as
        # TEXTRACT_ENABLED=false below, rather than reaching the real
        # Textract call at all.
        textract_unsupported_mime = cv_file.mime_type != "application/pdf"

        if not settings.textract_enabled or textract_unsupported_mime:
            logger.warning(
                "textract_skipped",
                cv_id=cv_file.id,
                reason="mime_type_unsupported" if textract_unsupported_mime else "textract_disabled",
                mime_type=cv_file.mime_type,
                hint="Set TEXTRACT_ENABLED=true and configure AWS credentials." if not textract_unsupported_mime else None,
            )
            # Write a placeholder pass so merge can continue
            pass_record = CvExtractionPass(
                cv_file_id=cv_file.id,
                pass_type="textract",
                attempt_number=_get_next_attempt(session, cv_file.id, "textract"),
                extracted_text="[Textract skipped — Docling-only extraction]",
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

            # Update job_type to reflect current pipeline stage before handoff
            job.job_type = "merge_parse"
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
            config=BotoConfig(signature_version="s3v4", connect_timeout=10, read_timeout=30),
        )
        textract = boto3.client(
            "textract",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            config=BotoConfig(connect_timeout=10, read_timeout=30),
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

        # Circuit breaker (§6): fail fast if Textract is degraded rather than
        # queuing a call that will only time out and hold worker capacity.
        if not TEXTRACT_CIRCUIT.allow():
            raise RuntimeError("Textract circuit open — failing fast.")

        try:
            # Start async text detection
            try:
                start_response = textract.start_document_text_detection(
                    DocumentLocation={
                        "S3Object": {
                            "Bucket": settings.s3_bucket_name,
                            "Name": textract_s3_key,
                        }
                    }
                )
            except Exception:
                TEXTRACT_CIRCUIT.record_failure()
                raise
            TEXTRACT_CIRCUIT.record_success()
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

            # Real spend (§10 CostSpikeSuspect): AWS Textract DetectDocumentText
            # is billed at $1.50/1,000 pages = $0.0015/page.
            COST_USD_COUNTER.labels(call_type="textract").inc(
                max(len(pages), 1) * 0.0015
            )
            push_worker_metrics("worker_textract")

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

            # Update job_type to reflect current pipeline stage before handoff
            job.job_type = "merge_parse"
            session.commit()

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
            config=BotoConfig(signature_version="s3v4", connect_timeout=10, read_timeout=30),
        )
    else:
        s3 = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            config=BotoConfig(connect_timeout=10, read_timeout=30),
        )

    response = s3.get_object(Bucket=settings.s3_bucket_name, Key=storage_key)
    return response["Body"].read()


def upload_file_sync(file_content: bytes, storage_key: str, content_type: str) -> None:
    """Synchronous wrapper for storage upload (Celery tasks are sync) —
    symmetric to download_file_sync above. Needed by process_export_docx/
    process_export_pdf since Celery tasks can't call the async
    app.core.storage.upload_file directly."""
    import boto3
    from botocore.config import Config as BotoConfig

    if settings.minio_endpoint and "minio" in settings.minio_endpoint:
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            aws_access_key_id=settings.minio_root_user,
            aws_secret_access_key=settings.minio_root_password,
            region_name=settings.aws_region,
            config=BotoConfig(signature_version="s3v4", connect_timeout=10, read_timeout=30),
        )
    else:
        s3 = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            config=BotoConfig(connect_timeout=10, read_timeout=30),
        )

    s3.put_object(Bucket=settings.s3_bucket_name, Key=storage_key, Body=file_content, ContentType=content_type)


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


