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

import json
import re
import time
import structlog
from datetime import datetime, timezone

import sqlalchemy as sa  # noqa: F401 — used by cv_parse helpers

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import select, delete, create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import (
    JOB_THROUGHPUT,
    JOB_DURATION_SECONDS,
    EXTRACTION_CHARS,
    MERGE_STRATEGY_COUNTER,
    STRUCTURAL_ANOMALY_COUNTER,
    LLM_TOKENS_COUNTER,
    LLM_GENERATION_COUNTER,
)
from app.core.storage import download_file
from app.db.models import (
    AtsReadinessCheck,
    CvEducationItem,
    CvExperienceItem,
    CvFile,
    CvExtractionPass,
    CvProfile,
    CvProfileVersion,
    CvRawText,
    CvSkillItem,
    JobPost,
    JobPostProfile,
    MatchEvidenceItem,
    MatchRun,
    ProcessingJob,
    TailoredCvDraft,
    TailoredCvSection,
    TrialSession,
)
from app.extraction.parser_interface import ExtractionResult
from app.extraction.docling_parser import DoclingParser
from app.extraction.merge import merge_extractions
from app.workers.tasks import (
    enqueue_textract_extract,
    enqueue_merge_parse,
    enqueue_cv_parse,
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
# Phase 3: Match analysis worker
# ──────────────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="app.workers.worker_jobs.process_match",
    queue="match",
)
def process_match(self, job_id: str) -> None:
    """Run evidence-based matching between a CV profile and a job post.

    Uses the rules-based match engine (heuristic, no LLM) for a fast first
    pass. An LLM-backed engine can be swapped in later.
    """
    structlog.contextvars.bind_contextvars(job_id=job_id)
    t_start = time.monotonic()
    session = _get_sync_session()
    try:
        from app.extraction.match_engine import run_match
        from app.db.models import (
            CvProfileVersion, CvSkillItem, JobPostProfile,
        )

        job = session.get(ProcessingJob, job_id)
        if job is None:
            logger.error("job_not_found", job_id=job_id)
            return

        job.status = "processing"
        session.commit()

        match_run = session.get(MatchRun, job.source_entity_id)
        if match_run is None:
            raise ValueError(f"MatchRun {job.source_entity_id} not found")

        # Load CV profile
        cv_version = session.get(CvProfileVersion, match_run.cv_profile_version_id)
        if cv_version is None:
            raise ValueError(f"CvProfileVersion {match_run.cv_profile_version_id} not found")

        # Load CV skills
        skill_items = session.execute(
            select(CvSkillItem).where(
                CvSkillItem.cv_profile_version_id == cv_version.id
            )
        ).scalars().all()
        cv_skills = [s.skill_name for s in skill_items]

        # Load job post profile
        jp_profile = session.get(JobPostProfile, match_run.job_post_profile_id)
        if jp_profile is None:
            raise ValueError(f"JobPostProfile {match_run.job_post_profile_id} not found")

        # Build dict for matching
        jp_dict = {
            "required_skills": jp_profile.required_skills or [],
            "preferred_skills": jp_profile.preferred_skills or [],
        }

        # Run matching
        result = run_match(cv_version.structured_payload, cv_skills, jp_dict)

        # Store evidence items
        for item in result.evidence_items:
            session.add(MatchEvidenceItem(
                match_run_id=match_run.id,
                requirement_text=item.requirement_text,
                requirement_type=item.requirement_type,
                support_level=item.support_level,
                confidence=item.confidence,
                source_references=item.source_references or None,
                suggestion=item.suggestion,
                warning=item.warning,
            ))

        # Update match_run
        match_run.score = result.score
        match_run.supported_count = result.supported_count
        match_run.partial_count = result.partial_count
        match_run.unsupported_count = result.unsupported_count
        match_run.contradictory_count = result.contradictory_count
        match_run.unclear_count = result.unclear_count
        match_run.total_requirements = result.total_requirements
        match_run.summary_analysis = result.summary_analysis
        match_run.status = "completed"
        match_run.completed_at = datetime.now(timezone.utc)

        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

        duration_s = time.monotonic() - t_start
        logger.info(
            "match_complete",
            match_id=match_run.id,
            score=result.score,
            supported=result.supported_count,
            unsupported=result.unsupported_count,
            duration_ms=int(duration_s * 1000),
        )

    except Exception as e:
        duration_s = time.monotonic() - t_start
        logger.error("match_failed", job_id=job_id, error=str(e))
        try:
            job.status = "failed"
            job.last_error = str(e)
            job.failed_at = datetime.now(timezone.utc)
            match_run = session.get(MatchRun, job.source_entity_id)
            if match_run:
                match_run.status = "failed"
                match_run.error_message = str(e)
            session.commit()
        except Exception:
            session.rollback()
        raise
    finally:
        session.close()
        structlog.contextvars.unbind_contextvars("job_id")


# ──────────────────────────────────────────────────────────────────────
# Phase 2: CV structured profile extraction worker
# ──────────────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="app.workers.worker_jobs.process_cv_parse",
    queue="cv_parse",
)
def process_cv_parse(self, job_id: str) -> None:
    """Build a structured candidate profile from the canonical merged text.

    1. Load cv_raw_text for the CV file
    2. Segment sections using heading canonicalization
    3. Extract experience, education, skills, certifications, projects
    4. Pperating cv_profile_versions + child tables
    5. Update cv_profiles pointer
    6. Mark CV file status as 'parsed'
    """
    structlog.contextvars.bind_contextvars(job_id=job_id)
    t_start = time.monotonic()
    session = _get_sync_session()
    try:
        from app.db.models import (
            CvProfile, CvProfileVersion,
            CvExperienceItem, CvEducationItem, CvSkillItem,
        )
        from app.extraction.heading_canonicalizer import (
            canonicalize_heading,
            WORK_EXPERIENCE, EDUCATION, SKILLS, CERTIFICATIONS, PROJECTS, SUMMARY,
            UNKNOWN,
        )
        import hashlib

        job = session.get(ProcessingJob, job_id)
        if job is None:
            logger.error("job_not_found", job_id=job_id)
            return

        job.status = "processing"
        session.commit()

        cv_file = session.get(CvFile, job.source_entity_id)
        if cv_file is None:
            raise ValueError(f"CV file {job.source_entity_id} not found")

        # Load canonical text
        raw_text_row = session.execute(
            select(CvRawText).where(CvRawText.cv_file_id == cv_file.id)
        ).scalar_one_or_none()

        if raw_text_row is None:
            raise ValueError(f"No canonical text for CV file {cv_file.id} — cannot parse.")

        canonical_text = raw_text_row.canonical_text

        # ── Section segmentation ────────────────────────────────────
        lines = canonical_text.split("\n")
        sections: dict[str, list[str]] = {}
        current_section = "preamble"

        # Simple heuristic: a line that is short, possibly uppercase,
        # and matches a known heading pattern starts a new section.
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Check if this line looks like a section heading
            if len(stripped) < 80 and (
                stripped.isupper() or
                stripped[0].isupper() and not stripped.startswith(("http", "www"))
            ):
                section_type, confidence = canonicalize_heading(stripped)
                if section_type != UNKNOWN and confidence >= 0.5:
                    current_section = section_type
                    continue

            sections.setdefault(current_section, []).append(stripped)

        # ── Extract experience items ────────────────────────────────
        experience_items: list[dict] = []
        exp_lines = sections.get(WORK_EXPERIENCE, [])
        current_role: dict | None = None

        for line in exp_lines:
            # Detect company/title lines (often have date ranges or look like "Title at Company")
            date_match = re.search(
                r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b.*?(?:-|–|to).*?(?:\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b|\bPresent\b|\bCurrent\b))",
                line, re.I,
            )
            if date_match and current_role is None:
                # Start a new role
                current_role = {"line": line}
                continue

            if date_match and current_role is not None:
                # Start a new role, flush previous
                experience_items.append(current_role)
                current_role = {"line": line}
                continue

            if current_role is not None:
                current_role.setdefault("bullets", []).append(line.strip())

        if current_role is not None:
            experience_items.append(current_role)

        # ── Build cv_profile_versions ───────────────────────────────
        profile_payload = {
            "basics": {
                "name": None,
                "email": None,
                "phone": None,
                "location": None,
                "summary": "\n".join(sections.get(SUMMARY, [])) or None,
            },
            "workExperience": [
                _make_experience_entry(e) for e in experience_items[:20]
            ],
            "education": [],
            "skills": {
                "technical": _extract_skills_from_lines(sections.get(SKILLS, [])),
                "soft": [],
            },
            "certifications": [],
            "projects": [],
        }

        # Compute profile hash
        payload_str = json.dumps(profile_payload, sort_keys=True, default=str)
        profile_hash = hashlib.sha256(payload_str.encode()).hexdigest()

        # Get next version number
        max_ver = session.execute(
            select(sa.func.max(CvProfileVersion.version_number)).where(
                CvProfileVersion.cv_file_id == cv_file.id
            )
        ).scalar() or 0
        version_number = max_ver + 1

        # Get source pass IDs
        passes = session.execute(
            select(CvExtractionPass.id).where(
                CvExtractionPass.cv_file_id == cv_file.id
            )
        ).scalars().all()

        # Insert profile version
        pv = CvProfileVersion(
            cv_file_id=cv_file.id,
            user_id=cv_file.user_id,
            trial_session_id=cv_file.trial_session_id,
            version_number=version_number,
            profile_hash=profile_hash,
            schema_version="1.0",
            source_pass_ids=passes if passes else None,
            structured_payload=profile_payload,
            confidence_summary={"overall": 0.75},
            validation_status="partial",
        )
        session.add(pv)
        session.flush()

        # ── Insert child rows ───────────────────────────────────────
        for entry in experience_items[:20]:
            session.add(CvExperienceItem(
                cv_profile_version_id=pv.id,
                company=entry.get("company"),
                title=entry.get("title"),
                start_date=entry.get("start_date"),
                end_date=entry.get("end_date"),
                current=entry.get("current", False),
                bullets=entry.get("bullets"),
                technologies=entry.get("technologies"),
                confidence=entry.get("confidence", 0.6),
                source_reference=entry.get("source_reference"),
            ))

        for skill_name in (profile_payload.get("skills", {}).get("technical") or []):
            session.add(CvSkillItem(
                cv_profile_version_id=pv.id,
                skill_name=skill_name,
                category="technical",
                confidence=0.7,
            ))

        # ── Update cv_profiles pointer ──────────────────────────────
        existing_profile = session.execute(
            select(CvProfile).where(CvProfile.cv_file_id == cv_file.id)
        ).scalar_one_or_none()

        if existing_profile:
            existing_profile.current_version_id = pv.id
            existing_profile.updated_at = datetime.now(timezone.utc)
        else:
            session.add(CvProfile(
                cv_file_id=cv_file.id,
                current_version_id=pv.id,
            ))

        cv_file.status = "parsed"
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

        duration_s = time.monotonic() - t_start
        logger.info(
            "cv_parse_complete",
            job_id=job_id,
            cv_id=cv_file.id,
            version=version_number,
            experience_count=len(experience_items),
            duration_ms=int(duration_s * 1000),
        )

    except Exception as e:
        duration_s = time.monotonic() - t_start
        logger.error("cv_parse_failed", job_id=job_id, error=str(e))
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


# ── cv_parse helpers ─────────────────────────────────────────────────


def _make_experience_entry(entry: dict) -> dict:
    return {
        "id": None,
        "company": entry.get("company"),
        "title": entry.get("title"),
        "startDate": entry.get("start_date"),
        "endDate": entry.get("end_date"),
        "current": entry.get("current", False),
        "bullets": entry.get("bullets") or [],
        "technologies": entry.get("technologies") or [],
    }


def _extract_skills_from_lines(lines: list[str]) -> list[str]:
    """Extract comma-separated or bullet-separated skills from a block of lines."""
    skills = []
    for line in lines:
        # Split on commas, bullets, or common separators
        parts = re.split(r"[,;•✦➤►|/]", line)
        for part in parts:
            cleaned = part.strip().strip("•-*").strip()
            if cleaned and len(cleaned) > 1 and len(cleaned) < 60:
                skills.append(cleaned)
    # Deduplicate while preserving order
    seen = set()
    result = []
    for s in skills:
        lower = s.lower()
        if lower not in seen:
            seen.add(lower)
            result.append(s)
    return result[:50]  # cap at 50 skills


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


# ──────────────────────────────────────────────────────────────────────
# Phase 2: Job post fetch worker (SSRF-safe)
# ──────────────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    name="app.workers.worker_jobs.process_job_post_fetch",
    queue="job_post_fetch",
)
def process_job_post_fetch(self, job_id: str) -> None:
    """Fetch a job post URL with SSRF-safe validation.

    Uses ssrf_safe_fetch() which validates scheme, DNS/IP, redirect chain,
    timeout, and response size per 10-security-plan.md §4.
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

        jp = session.get(JobPost, job.source_entity_id)
        if jp is None:
            raise ValueError(f"JobPost {job.source_entity_id} not found")

        if not jp.source_url:
            raise ValueError("Job post has no source_url to fetch")

        from app.services.ssrf_safe_fetch import ssrf_safe_fetch, SSRFRejection, FetchError

        try:
            raw_text = ssrf_safe_fetch(jp.source_url)
        except SSRFRejection as e:
            logger.warning("ssrf_rejected", url=jp.source_url, reason=str(e))
            jp.status = "failed"
            jp.error_message = (
                f"URL rejected for security reasons. {e} "
                "Please paste the job description text directly instead."
            )
            job.status = "failed"
            job.last_error = str(e)
            job.failed_at = datetime.now(timezone.utc)
            session.commit()
            return
        except FetchError as e:
            logger.warning("fetch_failed", url=jp.source_url, reason=str(e))
            jp.status = "failed"
            jp.error_message = (
                f"Could not fetch the job posting. {e} "
                "Please paste the job description text directly instead."
            )
            job.status = "failed"
            job.last_error = str(e)
            job.failed_at = datetime.now(timezone.utc)
            session.commit()
            return

        # Store fetched text and enqueue the parse step
        jp.raw_text = raw_text
        jp.status = "structuring"
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

        logger.info(
            "job_post_fetched",
            job_post_id=jp.id,
            url=jp.source_url,
            char_count=len(raw_text),
        )

        # Update job_type to reflect current pipeline stage before handoff
        job.job_type = "job_post_parse"
        session.commit()

        # Enqueue the parse worker as the next step
        from app.workers.tasks import enqueue_job_post_parse

        enqueue_job_post_parse(job_id)

    except Exception as e:
        logger.error("job_post_fetch_failed", job_id=job_id, error=str(e))
        try:
            job.status = "failed"
            job.last_error = str(e)
            job.failed_at = datetime.now(timezone.utc)
            jp = session.get(JobPost, job.source_entity_id)
            if jp:
                jp.status = "failed"
                jp.error_message = str(e)
            session.commit()
        except Exception:
            session.rollback()
        raise
    finally:
        session.close()
        structlog.contextvars.unbind_contextvars("job_id")


# ──────────────────────────────────────────────────────────────────────
# Phase 2: Job post structuring worker
# ──────────────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="app.workers.worker_jobs.process_job_post_parse",
    queue="job_post_parse",
)
def process_job_post_parse(self, job_id: str) -> None:
    """Structure a fetched or pasted job post into a JobPostProfile.

    Uses RulesBasedJobPostParser (via the JobPostParser ABC) for a
    fast, no-LLM first pass. An LLM-backed parser can be swapped in
    later without changing this worker.
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

        jp = session.get(JobPost, job.source_entity_id)
        if jp is None:
            raise ValueError(f"JobPost {job.source_entity_id} not found")

        if not jp.raw_text:
            raise ValueError("Job post has no raw_text to parse")

        # Parse using the rules-based parser via the ABC
        from app.extraction.job_post_parser import RulesBasedJobPostParser

        parser = RulesBasedJobPostParser()
        result = parser.parse(jp.raw_text)

        # Upsert the profile row
        existing = session.execute(
            select(JobPostProfile).where(
                JobPostProfile.job_post_id == jp.id
            )
        ).scalar_one_or_none()

        if existing:
            existing.job_title = result.job_title
            existing.employer = result.employer
            existing.location = result.location
            existing.required_skills = result.required_skills
            existing.preferred_skills = result.preferred_skills
            existing.responsibilities = result.responsibilities
            existing.qualifications = result.qualifications
            existing.keywords = result.keywords
            existing.seniority = result.seniority
            existing.structured_json = result.model_dump()
            existing.confidence = result.confidence
        else:
            profile = JobPostProfile(
                job_post_id=jp.id,
                job_title=result.job_title,
                employer=result.employer,
                location=result.location,
                required_skills=result.required_skills,
                preferred_skills=result.preferred_skills,
                responsibilities=result.responsibilities,
                qualifications=result.qualifications,
                keywords=result.keywords,
                seniority=result.seniority,
                structured_json=result.model_dump(),
                confidence=result.confidence,
            )
            session.add(profile)

        jp.status = "completed"
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

        duration_s = time.monotonic() - t_start
        logger.info(
            "job_post_parsed",
            job_post_id=jp.id,
            title=result.job_title,
            skill_count=len(result.required_skills or []),
            confidence=result.confidence,
            duration_ms=int(duration_s * 1000),
        )

    except Exception as e:
        duration_s = time.monotonic() - t_start
        logger.error("job_post_parse_failed", job_id=job_id, error=str(e))
        try:
            job.status = "failed"
            job.last_error = str(e)
            job.failed_at = datetime.now(timezone.utc)
            jp = session.get(JobPost, job.source_entity_id)
            if jp:
                jp.status = "failed"
                jp.error_message = str(e)
            session.commit()
        except Exception:
            session.rollback()
        raise
    finally:
        session.close()
        structlog.contextvars.unbind_contextvars("job_id")


# ──────────────────────────────────────────────────────────────────────
# Sprint 2: Anonymous trial support — expiry cleanup
# ──────────────────────────────────────────────────────────────────────


@shared_task(
    name="app.workers.worker_jobs.cleanup_expired_trial_sessions",
    queue="maintenance",
)
def cleanup_expired_trial_sessions() -> None:
    """Delete expired, unclaimed trial sessions and everything still
    attached to them, per 06-non-functional-requirements.md's retention
    discipline — unclaimed trial data shouldn't accumulate indefinitely.

    Only UNCLAIMED sessions are touched: claim-trial already reassigns a
    claimed session's rows to a real user_id and clears trial_session_id,
    so a claimed session's data is never visible to the queries below
    regardless of how old the trial_session row itself is.

    Deletes in FK-dependency order (children before parents) since these
    relationships aren't set up for ON DELETE CASCADE at the DB level:
    processing_jobs and match_evidence_items first, then match_runs; the
    three cv_profile_versions child tables, then cv_profiles (which
    points at both cv_profile_versions and cv_files) and
    cv_profile_versions itself; cv_extraction_passes/cv_raw_text, then
    cv_files; job_post_profiles, then job_posts; finally the
    trial_sessions rows.

    Invoked periodically by Celery beat (`beat_schedule` in
    app/workers/tasks.py, interval set by
    settings.trial_session_cleanup_interval_seconds), consumed by the
    `worker_maintenance` service (docker-compose.yml) on the `maintenance`
    queue. Can also be triggered manually via `celery -A
    app.workers.tasks.celery_app call
    app.workers.worker_jobs.cleanup_expired_trial_sessions`.
    """
    session = _get_sync_session()
    try:
        now = datetime.now(timezone.utc)
        expired_ids = session.execute(
            select(TrialSession.id).where(
                TrialSession.expires_at <= now,
                TrialSession.claimed_by_user_id.is_(None),
            )
        ).scalars().all()

        if not expired_ids:
            logger.info("trial_session_cleanup_none_expired")
            return

        cv_file_ids = session.execute(
            select(CvFile.id).where(CvFile.trial_session_id.in_(expired_ids))
        ).scalars().all()
        cv_profile_version_ids = session.execute(
            select(CvProfileVersion.id).where(CvProfileVersion.trial_session_id.in_(expired_ids))
        ).scalars().all()
        job_post_ids = session.execute(
            select(JobPost.id).where(JobPost.trial_session_id.in_(expired_ids))
        ).scalars().all()
        match_run_ids = session.execute(
            select(MatchRun.id).where(MatchRun.trial_session_id.in_(expired_ids))
        ).scalars().all()

        session.execute(delete(ProcessingJob).where(ProcessingJob.trial_session_id.in_(expired_ids)))
        session.execute(delete(MatchEvidenceItem).where(MatchEvidenceItem.match_run_id.in_(match_run_ids)))
        session.execute(delete(MatchRun).where(MatchRun.id.in_(match_run_ids)))

        session.execute(delete(CvExperienceItem).where(CvExperienceItem.cv_profile_version_id.in_(cv_profile_version_ids)))
        session.execute(delete(CvEducationItem).where(CvEducationItem.cv_profile_version_id.in_(cv_profile_version_ids)))
        session.execute(delete(CvSkillItem).where(CvSkillItem.cv_profile_version_id.in_(cv_profile_version_ids)))
        session.execute(delete(CvProfile).where(CvProfile.cv_file_id.in_(cv_file_ids)))
        session.execute(delete(CvProfileVersion).where(CvProfileVersion.id.in_(cv_profile_version_ids)))

        session.execute(delete(CvExtractionPass).where(CvExtractionPass.cv_file_id.in_(cv_file_ids)))
        session.execute(delete(CvRawText).where(CvRawText.cv_file_id.in_(cv_file_ids)))
        session.execute(delete(CvFile).where(CvFile.id.in_(cv_file_ids)))

        session.execute(delete(JobPostProfile).where(JobPostProfile.job_post_id.in_(job_post_ids)))
        session.execute(delete(JobPost).where(JobPost.id.in_(job_post_ids)))

        session.execute(delete(TrialSession).where(TrialSession.id.in_(expired_ids)))

        session.commit()
        logger.info(
            "trial_session_cleanup_complete",
            expired_sessions=len(expired_ids),
            cv_files=len(cv_file_ids),
            job_posts=len(job_post_ids),
            match_runs=len(match_run_ids),
        )
    except Exception as e:
        session.rollback()
        logger.error("trial_session_cleanup_failed", error=str(e))
        raise
    finally:
        session.close()




# ──────────────────────────────────────────────────────────────────────
# Product Extension #1: ATS structural-readiness check
# ──────────────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="app.workers.worker_jobs.process_ats_check",
    queue="ats_check",
)
def process_ats_check(self, job_id: str) -> None:
    """Run the rules-based ATS readiness check against a CV's merged
    extraction and structured profile.

    This is a one-shot terminal job (like 'match' / 'cv_generate') — it
    never transitions to another job_type, only completes or fails.
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
        job.started_at = datetime.now(timezone.utc)
        session.commit()

        cv_file = session.get(CvFile, job.source_entity_id)
        if cv_file is None:
            raise ValueError(f"CV file {job.source_entity_id} not found")

        # Resolve the current profile version via the pointer row
        profile = session.execute(
            select(CvProfile).where(CvProfile.cv_file_id == cv_file.id)
        ).scalar_one_or_none()

        cv_profile_version_id = None
        structured_payload = None
        if profile is not None and profile.current_version_id is not None:
            cv_profile_version_id = profile.current_version_id
            pv = session.get(CvProfileVersion, profile.current_version_id)
            if pv is not None:
                structured_payload = pv.structured_payload

        # Gather extraction data
        raw_text = session.execute(
            select(CvRawText).where(CvRawText.cv_file_id == cv_file.id)
        ).scalar_one_or_none()

        canonical_text = raw_text.canonical_text if raw_text else ""
        ocr_used = raw_text.ocr_used if raw_text else False
        merge_meta = raw_text.merge_strategy_metadata if raw_text else None
        structural_validation = (
            raw_text.structural_validation_result if raw_text else None
        )

        # Docling and Textract pass texts (needed for text_in_image check)
        passes = session.execute(
            select(CvExtractionPass)
            .where(CvExtractionPass.cv_file_id == cv_file.id)
        ).scalars().all()

        docling_text = ""
        textract_text = ""
        for p in passes:
            if p.pass_type == "docling":
                docling_text = p.extracted_text or ""
            elif p.pass_type == "textract":
                textract_text = p.extracted_text or ""

        from app.extraction.ats_check import run_ats_check as ats_scorer

        result = ats_scorer(
            canonical_text=canonical_text,
            docling_text=docling_text,
            textract_text=textract_text,
            ocr_used=ocr_used,
            structural_validation=structural_validation,
            structured_payload=structured_payload,
            mime_type=cv_file.mime_type or "",
            merge_strategy_metadata=merge_meta,
        )

        check_row = AtsReadinessCheck(
            cv_file_id=cv_file.id,
            cv_profile_version_id=cv_profile_version_id,
            overall_score=result.overall_score,
            checks=result.checks,
            contact_info_parseable=result.contact_info_parseable,
        )
        session.add(check_row)

        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

        JOB_THROUGHPUT.labels(job_type="ats_check", status="completed").inc()
        duration_s = time.monotonic() - t_start
        JOB_DURATION_SECONDS.labels(job_type="ats_check").observe(duration_s)
        logger.info(
            "ats_check_complete",
            job_id=job_id,
            cv_id=cv_file.id,
            overall_score=result.overall_score,
        )

    except Exception as e:
        session.rollback()
        duration_s = time.monotonic() - t_start
        logger.error("ats_check_failed", job_id=job_id, error=str(e))
        JOB_THROUGHPUT.labels(job_type="ats_check", status="failed").inc()
        JOB_DURATION_SECONDS.labels(job_type="ats_check").observe(duration_s)
        try:
            job = session.get(ProcessingJob, job_id)
            if job is not None:
                job.status = "failed"
                job.last_error = str(e)
                job.failed_at = datetime.now(timezone.utc)
                session.commit()
        except Exception as finalize_err:
            logger.error(
                "ats_check_finalize_failed",
                job_id=job_id, error=str(finalize_err),
            )
        raise
    finally:
        session.close()


# ──────────────────────────────────────────────────────────────────────
# Sprint 3: Tailored CV generation
# ──────────────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    max_retries=1,
    default_retry_delay=30,
    name="app.workers.worker_jobs.process_cv_generate",
    queue="cv_generate",
)
def process_cv_generate(self, job_id: str) -> None:
    """Generate a tailored CV draft's sections from its match_run's
    evidence. One-shot terminal job, like 'match'/'ats_check' — never
    transitions to another job_type.

    Deliberately low max_retries (1, not the usual 3): a schema/
    verification failure inside generate_draft_sections() already retries
    internally per section (settings.tailored_cv_max_generation_retries)
    and degrades gracefully by omitting sections, not by raising — this
    task only raises for something outside that (DB error, missing rows),
    which a Celery-level retry is unlikely to fix by itself.
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
        job.started_at = datetime.now(timezone.utc)
        session.commit()

        draft = session.get(TailoredCvDraft, job.source_entity_id)
        if draft is None:
            raise ValueError(f"TailoredCvDraft {job.source_entity_id} not found")

        match_run = session.get(MatchRun, draft.match_run_id)
        if match_run is None:
            raise ValueError(f"MatchRun {draft.match_run_id} not found")

        match_evidence_items = session.execute(
            select(MatchEvidenceItem).where(MatchEvidenceItem.match_run_id == match_run.id)
        ).scalars().all()

        experience_items = session.execute(
            select(CvExperienceItem).where(
                CvExperienceItem.cv_profile_version_id == match_run.cv_profile_version_id
            )
        ).scalars().all()
        education_items = session.execute(
            select(CvEducationItem).where(
                CvEducationItem.cv_profile_version_id == match_run.cv_profile_version_id
            )
        ).scalars().all()
        skill_items = session.execute(
            select(CvSkillItem).where(
                CvSkillItem.cv_profile_version_id == match_run.cv_profile_version_id
            )
        ).scalars().all()

        jp_profile = session.get(JobPostProfile, match_run.job_post_profile_id)
        job_requirements = [
            *(jp_profile.required_skills or [] if jp_profile else []),
            *(jp_profile.preferred_skills or [] if jp_profile else []),
        ]

        from app.services.tailored_cv_generation import (
            generate_draft_sections, assemble_content_json, render_text_from_sections,
            build_validation_result, build_improvement_checklist,
        )

        outcome = generate_draft_sections(
            match_evidence_items=match_evidence_items,
            experience_items=experience_items,
            education_items=education_items,
            skill_items=skill_items,
            job_requirements=job_requirements,
            instructions=draft.instructions,
        )

        for section in outcome.sections:
            session.add(TailoredCvSection(
                draft_id=draft.id,
                section_type=section.section_type,
                content_text=section.content_text,
                evidence_references=section.evidence_references,
                generation_task=section.generation_task,
                prompt_version=section.prompt_version,
                model_id=section.model_id,
                validation_status=section.validation_status,
                order_index=section.order_index,
            ))

        draft.content_json = assemble_content_json(outcome.sections)
        draft.render_text = render_text_from_sections(outcome.sections)
        draft.validation_result = build_validation_result(outcome)
        draft.improvement_checklist = build_improvement_checklist(match_evidence_items)
        draft.status = "generated" if outcome.sections else "failed"
        draft.updated_at = datetime.now(timezone.utc)

        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

        LLM_TOKENS_COUNTER.labels(generation_task="tailored_cv_all", token_type="prompt").inc(
            outcome.total_prompt_tokens
        )
        LLM_TOKENS_COUNTER.labels(generation_task="tailored_cv_all", token_type="completion").inc(
            outcome.total_completion_tokens
        )
        LLM_GENERATION_COUNTER.labels(
            generation_task="tailored_cv_draft",
            outcome="success" if outcome.sections else "verification_failed",
        ).inc()

        JOB_THROUGHPUT.labels(job_type="cv_generate", status="completed").inc()
        duration_s = time.monotonic() - t_start
        JOB_DURATION_SECONDS.labels(job_type="cv_generate").observe(duration_s)
        logger.info(
            "cv_generate_complete",
            job_id=job_id,
            draft_id=draft.id,
            sections_generated=len(outcome.sections),
            issues=outcome.issues,
        )

    except Exception as e:
        session.rollback()
        duration_s = time.monotonic() - t_start
        logger.error("cv_generate_failed", job_id=job_id, error=str(e))
        LLM_GENERATION_COUNTER.labels(generation_task="tailored_cv_draft", outcome="api_error").inc()
        JOB_THROUGHPUT.labels(job_type="cv_generate", status="failed").inc()
        JOB_DURATION_SECONDS.labels(job_type="cv_generate").observe(duration_s)
        try:
            job = session.get(ProcessingJob, job_id)
            if job is not None:
                job.status = "failed"
                job.last_error = str(e)
                job.failed_at = datetime.now(timezone.utc)
            draft = session.get(TailoredCvDraft, job.source_entity_id) if job is not None else None
            if draft is not None:
                draft.status = "failed"
            session.commit()
        except Exception as finalize_err:
            logger.error(
                "cv_generate_finalize_failed",
                job_id=job_id, error=str(finalize_err),
            )
        raise
    finally:
        session.close()

