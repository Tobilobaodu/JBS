"""POST /resume-rewrites — single-call tailored CV.

Synchronous by design (see app/services/resume_rewrite.py): one LLM call,
nothing persisted, result returned on the response. No jobPostId is taken
— the job post text is passed straight through, because the model does
its own requirement extraction. That deliberately bypasses steps 7-9.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.rate_limit import check_generation_rate_limit, get_client_key
from app.core.security import (
    RequestIdentity,
    get_current_user_or_trial_session,
    identity_owner_filter,
    ownership_denied,
)
from app.db import get_session
from app.db.models import CvFile, CvRawText
from app.services.resume_pdf import (
    MAX_MARKDOWN_CHARS,
    ResumePdfError,
    render_resume_pdf,
)
from app.services.resume_rewrite import ResumeRewriteError, rewrite_resume

logger = get_logger(__name__)
router = APIRouter()


class ResumeRewriteRequest(BaseModel):
    cv_id: str = Field(alias="cvId")
    job_description: str = Field(alias="jobDescription", min_length=40)
    target_title: str | None = Field(default=None, alias="targetTitle")
    candidate_notes: str | None = Field(default=None, alias="candidateNotes")

    model_config = {"populate_by_name": True}


class ResumeRewriteStats(BaseModel):
    # Occupation of the CV vs the role. Surfaced so a low score explains
    # itself: "Product Designer" against "People / HR" is why the number
    # is capped, and a user who sees only a number cannot tell.
    cvOccupation: str = ""
    jobOccupation: str = ""
    sameOccupation: bool = True
    atsScore: float
    matchLabel: str
    matchedSkills: list[str]
    transferableSkills: list[str]
    missingSkills: list[str]
    priorityKeywords: list[str]


class ResumeRewriteResponse(BaseModel):
    tailoredResumeMarkdown: str
    matchNotes: list[str]
    informationNeeded: list[str]
    stats: ResumeRewriteStats
    promptVersion: str


@router.post("/resume-rewrites", response_model=ResumeRewriteResponse)
async def create_resume_rewrite(
    request: Request,
    body: ResumeRewriteRequest,
    identity: RequestIdentity = Depends(get_current_user_or_trial_session),
    session: AsyncSession = Depends(get_session),
):
    """Rewrite a CV for a job post in one call.

    Trial-accessible. Rate-limited per client IP (generation tier) — this
    is the most expensive call in the system now that it carries the whole
    CV and the whole job post in one prompt.
    """
    client_key = get_client_key(request)
    if not check_generation_rate_limit(client_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many rewrite requests. Please wait and try again.",
        )

    cv_file = (
        await session.execute(
            select(CvFile).where(
                CvFile.id == body.cv_id,
                identity_owner_filter(CvFile, identity),
                CvFile.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if cv_file is None:
        raise await ownership_denied(
            session, user_id=identity.user_id, entity_type="cv_file",
            entity_id=body.cv_id, detail="CV not found",
        )

    raw_text = (
        await session.execute(
            select(CvRawText).where(CvRawText.cv_file_id == cv_file.id)
        )
    ).scalar_one_or_none()
    if raw_text is None or not (raw_text.canonical_text or "").strip():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CV text is not ready yet. Wait for extraction to finish.",
        )

    try:
        result = rewrite_resume(
            cv_text=raw_text.canonical_text,
            job_post_text=body.job_description,
            target_title=body.target_title,
            candidate_notes=body.candidate_notes,
        )
    except ResumeRewriteError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)
        ) from e

    logger.info("resume_rewrite_served", cv_id=cv_file.id)
    return ResumeRewriteResponse(
        tailoredResumeMarkdown=result.tailored_resume_markdown,
        matchNotes=result.match_notes,
        informationNeeded=result.information_needed,
        stats=ResumeRewriteStats(**result.stats),
        promptVersion=result.prompt_version,
    )


class ResumePdfRequest(BaseModel):
    """The Markdown to render.

    Taken from the request rather than looked up, because the rewrite is
    stateless — there is no draft row to reference. The content is the
    caller's own CV either way, and it is HTML-escaped before rendering.
    """

    markdown: str = Field(
        alias="tailoredResumeMarkdown", min_length=1, max_length=MAX_MARKDOWN_CHARS
    )
    file_name: str | None = Field(default=None, alias="fileName")

    model_config = {"populate_by_name": True}


def _safe_filename(raw: str | None) -> str:
    """Keep the download name to characters that survive a Content-Disposition
    header unquoted — never let a caller inject header syntax."""
    cleaned = re.sub(r"[^A-Za-z0-9 ._-]", "", (raw or "").strip())[:80].strip()
    if not cleaned:
        cleaned = "tailored-cv"
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned


@router.post("/resume-rewrites/pdf")
async def create_resume_rewrite_pdf(
    request: Request,
    body: ResumePdfRequest,
    identity: RequestIdentity = Depends(get_current_user_or_trial_session),
):
    """Render tailored-CV Markdown to a PDF and return it inline.

    Synchronous like the rewrite itself: Gotenberg converts in well under
    a second, so a job row and a poll would cost more than they save.
    Requires an identity so it cannot be used as an open render service,
    and shares the generation rate-limit tier.
    """
    client_key = get_client_key(request)
    if not check_generation_rate_limit(client_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many export requests. Please wait and try again.",
        )

    try:
        pdf = render_resume_pdf(body.markdown)
    except ResumePdfError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)
        ) from e

    filename = _safe_filename(body.file_name)
    logger.info(
        "resume_pdf_rendered",
        user_id=identity.user_id,
        markdown_chars=len(body.markdown),
        pdf_bytes=len(pdf),
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
