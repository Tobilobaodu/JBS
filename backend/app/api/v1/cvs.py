"""CV endpoints — POST /cvs (upload), GET /cvs, GET/DELETE /cvs/{cvId}, GET /jobs/{jobId}.

Matches 05-openapi.yaml. All heavy work (extraction, parsing) is async via
the queue — these endpoints only accept/validate/persist and return immediately.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.storage import generate_storage_key, upload_file
from app.db import get_session
from app.db.models import (
    AuditEvent,
    CvFile,
    CvExtractionPass,
    CvProfile,
    CvProfileVersion,
    CvRawText,
    ProcessingJob,
    User,
)
from app.schemas.cv import (
    CvUploadAccepted,
    CvFileResponse,
    CvListResponse,
    CvExtractionDetailResponse,
    CvExtractionPassResponse,
    CvRawTextResponse,
    StructuralValidationResult,
)
from app.schemas.jobs import ProcessingJobResponse
from app.services.file_validation import validate_file_type, validate_file_size
from app.services.malware_scan import scan_file
from app.services.orchestration import start_extraction_pipeline
from app.core.security import get_current_user

router = APIRouter(tags=["cvs"])
logger = get_logger(__name__)


def _active_cv_query(user_id: str):
    """Base query for non-deleted CVs owned by the given user."""
    return select(CvFile).where(
        CvFile.user_id == user_id,
        CvFile.deleted_at.is_(None),
    )


# ──────────────────────────────────────────────────────────────────────
# POST /cvs — upload
# ──────────────────────────────────────────────────────────────────────


@router.post("/cvs", response_model=CvUploadAccepted, status_code=202)
async def upload_cv(
    request: Request,
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Upload a CV file (PDF or DOCX). Validates, scans, stores, then enqueues extraction.

    Returns 202 immediately with cvId and processingJobId. The extraction pipeline
    (Docling → Textract → merge) runs asynchronously.
    """
    # Read file content
    file_content = await file.read()

    # Validate type (magic bytes) and size
    try:
        mime_type = validate_file_type(file.filename or "unnamed", file_content)
        file_size = validate_file_size(file_content)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Malware scan — blocking, must pass before storage
    try:
        await scan_file(file_content)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file failed security scan.",
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    # Generate non-guessable storage key
    storage_key = generate_storage_key(file.filename or "unnamed.pdf")

    # Store file
    await upload_file(file_content, storage_key, mime_type)

    # Create database records
    cv_file = CvFile(
        user_id=current_user.id,
        filename=file.filename or "unnamed",
        mime_type=mime_type,
        file_size=file_size,
        storage_key=storage_key,
        status="pending",
    )
    session.add(cv_file)
    await session.flush()

    # Audit
    session.add(
        AuditEvent(
            user_id=current_user.id,
            event_type="upload",
            entity_type="cv_file",
            entity_id=cv_file.id,
            actor_type="user",
            ip_address=request.client.host if request.client else None,
        )
    )

    # Kick off the extraction pipeline
    processing_job = await start_extraction_pipeline(
        session=session, cv_file_id=cv_file.id, user_id=current_user.id
    )

    await session.commit()

    logger.info(
        "cv_uploaded",
        cv_id=cv_file.id,
        job_id=processing_job.id,
        filename=file.filename,
    )

    return CvUploadAccepted(
        cv_id=cv_file.id,
        processing_job_id=processing_job.id,
        status="queued",
        filename=file.filename or "unnamed",
        file_size=file_size,
        mime_type=mime_type,
    )


# ──────────────────────────────────────────────────────────────────────
# GET /cvs — list
# ──────────────────────────────────────────────────────────────────────


@router.get("/cvs", response_model=CvListResponse)
async def list_cvs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """List uploaded CVs for the current user. Scoped by user_id (IDOR-safe)."""
    query = _active_cv_query(current_user.id)

    if status_filter:
        query = query.where(CvFile.status == status_filter)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    # Get page
    query = query.order_by(CvFile.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    cv_files = result.scalars().all()

    # Batch-query most recent processing job per CV for status visibility
    job_status_map: dict[str, str] = {}
    if cv_files:
        cv_ids = [f.id for f in cv_files]
        job_result = await session.execute(
            select(ProcessingJob.source_entity_id, ProcessingJob.status)
            .where(
                ProcessingJob.source_entity_type == "cv_file",
                ProcessingJob.source_entity_id.in_(cv_ids),
            )
            .order_by(ProcessingJob.created_at.desc())
        )
        for source_id, status in job_result.all():
            if source_id not in job_status_map:
                job_status_map[source_id] = status

    items = [
        CvFileResponse(
            id=f.id,
            original_filename=f.filename,
            mime_type=f.mime_type,
            file_size_bytes=f.file_size,
            upload_status="stored" if f.storage_key else "pending",
            processing_status=f.status,
            job_status=job_status_map.get(f.id),
            created_at=f.created_at,
            updated_at=f.updated_at,
        )
        for f in cv_files
    ]

    return CvListResponse(items=items, total=total, limit=limit, offset=offset)


# ──────────────────────────────────────────────────────────────────────
# GET /cvs/{cvId} — metadata
# ──────────────────────────────────────────────────────────────────────


@router.get("/cvs/{cv_id}", response_model=CvFileResponse)
async def get_cv(
    cv_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get CV metadata. Returns 404 if not found, not owned by current user, or soft-deleted."""
    result = await session.execute(
        select(CvFile).where(
            CvFile.id == cv_id,
            CvFile.user_id == current_user.id,
            CvFile.deleted_at.is_(None),
        )
    )
    cv_file = result.scalar_one_or_none()

    if cv_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found.")

    # Look up most recent processing job status for this CV
    job_result = await session.execute(
        select(ProcessingJob.status)
        .where(
            ProcessingJob.source_entity_type == "cv_file",
            ProcessingJob.source_entity_id == cv_id,
        )
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    job_status = job_result.scalar()

    return CvFileResponse(
        id=cv_file.id,
        original_filename=cv_file.filename,
        mime_type=cv_file.mime_type,
        file_size_bytes=cv_file.file_size,
        upload_status="stored" if cv_file.storage_key else "pending",
        processing_status=cv_file.status,
        job_status=job_status,
        created_at=cv_file.created_at,
        updated_at=cv_file.updated_at,
    )


# ──────────────────────────────────────────────────────────────────────
# DELETE /cvs/{cvId}
# ──────────────────────────────────────────────────────────────────────


@router.delete("/cvs/{cv_id}", status_code=202)
async def delete_cv(
    cv_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Delete a CV and derived records. Returns 404 if not owned by current user or already deleted."""
    result = await session.execute(
        select(CvFile).where(
            CvFile.id == cv_id,
            CvFile.user_id == current_user.id,
            CvFile.deleted_at.is_(None),
        )
    )
    cv_file = result.scalar_one_or_none()

    if cv_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found.")

    cv_file.deleted_at = func.now()
    cv_file.status = "deleted"

    session.add(
        AuditEvent(
            user_id=current_user.id,
            event_type="deletion_requested",
            entity_type="cv_file",
            entity_id=cv_file.id,
            actor_type="user",
        )
    )

    await session.commit()
    logger.info("cv_deleted", cv_id=cv_id, user_id=current_user.id)


# ──────────────────────────────────────────────────────────────────────
# POST /cvs/{cvId}/reprocess
# ──────────────────────────────────────────────────────────────────────


@router.post("/cvs/{cv_id}/reprocess", status_code=202)
async def reprocess_cv(
    cv_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Re-trigger the extraction pipeline. Creates new extraction passes."""
    result = await session.execute(
        select(CvFile).where(
            CvFile.id == cv_id,
            CvFile.user_id == current_user.id,
            CvFile.deleted_at.is_(None),
        )
    )
    cv_file = result.scalar_one_or_none()

    if cv_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found.")

    cv_file.status = "pending"
    processing_job = await start_extraction_pipeline(
        session=session, cv_file_id=cv_file.id, user_id=current_user.id
    )

    await session.commit()

    from app.schemas.jobs import ProcessingJobRef

    return ProcessingJobRef(job_id=processing_job.id, status="queued")


# ──────────────────────────────────────────────────────────────────────
# GET /cvs/{cvId}/raw-text
# ──────────────────────────────────────────────────────────────────────


@router.get("/cvs/{cv_id}/raw-text", response_model=CvRawTextResponse)
async def get_cv_raw_text(
    cv_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get canonical merged extracted text."""
    # Verify ownership via cv_file, excluding soft-deleted rows
    result = await session.execute(
        select(CvFile).where(
            CvFile.id == cv_id,
            CvFile.user_id == current_user.id,
            CvFile.deleted_at.is_(None),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found.")

    raw = await session.execute(
        select(CvRawText).where(CvRawText.cv_file_id == cv_id)
    )
    raw_text = raw.scalar_one_or_none()

    if raw_text is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raw text not available yet.")

    return CvRawTextResponse(
        canonical_text=raw_text.canonical_text,
        ocr_used=raw_text.ocr_used,
        merge_strategy_metadata=raw_text.merge_strategy_metadata,
    )


# ──────────────────────────────────────────────────────────────────────
# GET /cvs/{cvId}/extraction-detail
# ──────────────────────────────────────────────────────────────────────


@router.get("/cvs/{cv_id}/extraction-detail", response_model=CvExtractionDetailResponse)
async def get_cv_extraction_detail(
    cv_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get Docling and Textract pass outputs with completeness metadata."""
    result = await session.execute(
        select(CvFile).where(
            CvFile.id == cv_id,
            CvFile.user_id == current_user.id,
            CvFile.deleted_at.is_(None),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found.")

    passes_result = await session.execute(
        select(CvExtractionPass)
        .where(CvExtractionPass.cv_file_id == cv_id)
        .order_by(CvExtractionPass.created_at)
    )
    passes = passes_result.scalars().all()

    raw_result = await session.execute(
        select(CvRawText).where(CvRawText.cv_file_id == cv_id)
    )
    raw = raw_result.scalar_one_or_none()

    return CvExtractionDetailResponse(
        passes=[
            CvExtractionPassResponse(
                id=p.id,
                pass_type=p.pass_type,
                attempt_number=p.attempt_number,
                confidence_score=p.confidence_score,
                processing_duration_ms=p.processing_duration_ms,
                created_at=p.created_at,
            )
            for p in passes
        ],
        structural_validation=(
            StructuralValidationResult(**raw.structural_validation_result)
            if raw and raw.structural_validation_result
            else None
        ),
    )


# ──────────────────────────────────────────────────────────────────────
# GET /cvs/{cvId}/parsed-profile  — Phase 2
# ──────────────────────────────────────────────────────────────────────


@router.get("/cvs/{cv_id}/parsed-profile")
async def get_cv_parsed_profile(
    cv_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Return the current structured candidate profile (Phase 2)."""
    # Ownership check, excluding soft-deleted CVs
    cv_result = await session.execute(
        select(CvFile).where(
            CvFile.id == cv_id,
            CvFile.user_id == current_user.id,
            CvFile.deleted_at.is_(None),
        )
    )
    cv_file = cv_result.scalar_one_or_none()
    if cv_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV not found")

    # Get current profile pointer
    profile_result = await session.execute(
        select(CvProfile).where(CvProfile.cv_file_id == cv_id)
    )
    profile = profile_result.scalar_one_or_none()

    if profile is None or profile.current_version_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No structured profile available yet. Wait for CV parsing to complete.",
        )

    version_result = await session.execute(
        select(CvProfileVersion).where(
            CvProfileVersion.id == profile.current_version_id
        )
    )
    version = version_result.scalar_one_or_none()
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile version not found.",
        )

    return {
        "cvId": cv_id,
        "profileVersionId": version.id,
        "versionNumber": version.version_number,
        "profileHash": version.profile_hash,
        "schemaVersion": version.schema_version,
        "validationStatus": version.validation_status,
        "confidenceSummary": version.confidence_summary,
        "structuredPayload": version.structured_payload,
        "createdAt": version.created_at.isoformat() if version.created_at else None,
    }
