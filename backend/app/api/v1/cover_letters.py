"""Cover letter workflow endpoints — Phase 4.

POST /cover-letters/start
GET  /cover-letters/{workflowId}/questions
POST /cover-letters/{workflowId}/answers
GET  /cover-letters/{workflowId}/draft
POST /cover-letters/{workflowId}/regenerate
POST /cover-letters/{workflowId}/approve

Per the non-fabrication rule: unsupported evidence produces a user
question, never an invented claim. Drafts carry non-empty evidence
references.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.rate_limit import check_generation_rate_limit, get_client_key
from app.core.security import get_current_user
from app.db import get_session
from app.db.models import (
    AuditEvent, CoverLetterAnswer, CoverLetterDraft, CoverLetterQuestion,
    CoverLetterWorkflow, CvFile, CvProfile, CvProfileVersion, JobPost,
    JobPostProfile, MatchEvidenceItem, MatchRun, ProcessingJob, User,
)
from app.schemas.cover_letter import (
    StartWorkflowRequest, CoverLetterWorkflowResponse,
    CoverLetterQuestionResponse, SubmitAnswersRequest,
    CoverLetterDraftResponse,
)
from app.schemas.jobs import ProcessingJobRef
from app.services.cover_letter import generate_questions, assemble_draft

router = APIRouter(tags=["cover-letters"])
logger = get_logger(__name__)


def _map_workflow(wf: CoverLetterWorkflow) -> CoverLetterWorkflowResponse:
    return CoverLetterWorkflowResponse(
        id=wf.id,
        cvId=wf.cv_profile_version_id,
        jobPostId=wf.job_post_profile_id,
        matchId=wf.match_run_id,
        current_step=wf.current_step,
        status=wf.status,
        question_set_version=wf.question_set_version,
        created_at=wf.created_at,
    )


async def _verify_ownership(
    session: AsyncSession, workflow_id: str, user_id: str,
) -> CoverLetterWorkflow:
    result = await session.execute(
        select(CoverLetterWorkflow).where(
            CoverLetterWorkflow.id == workflow_id,
            CoverLetterWorkflow.user_id == user_id,
        )
    )
    wf = result.scalar_one_or_none()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


# ──────────────────────────────────────────────────────────────────────
# POST /cover-letters/start
# ──────────────────────────────────────────────────────────────────────


@router.post("/cover-letters/start", response_model=CoverLetterWorkflowResponse, status_code=201)
async def start_workflow(
    request: Request,
    body: StartWorkflowRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Start a guided cover letter workflow from a CV and job post.

    Rate-limited per client IP (generation tier, see `10-security-plan.md` §9).
    """
    client_key = get_client_key(request)
    if not check_generation_rate_limit(client_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many cover letter requests. Please wait and try again.",
        )

    # Verify CV profile version exists (via current profile pointer),
    # scoped to the caller — without this join, any authenticated user
    # could start a workflow against another user's CV.
    profile_result = await session.execute(
        select(CvProfile)
        .join(CvFile, CvFile.id == CvProfile.cv_file_id)
        .where(
            CvProfile.cv_file_id == body.cvId,
            CvFile.user_id == current_user.id,
        )
    )
    profile = profile_result.scalar_one_or_none()
    if profile is None or profile.current_version_id is None:
        raise HTTPException(
            status_code=404,
            detail="No parsed CV profile found. Process a CV first.",
        )

    # Verify job post profile exists (1:1 with job_posts), scoped to the
    # caller for the same reason.
    jp_result = await session.execute(
        select(JobPostProfile)
        .join(JobPost, JobPost.id == JobPostProfile.job_post_id)
        .where(
            JobPostProfile.job_post_id == body.jobPostId,
            JobPost.user_id == current_user.id,
        )
    )
    jp_profile = jp_result.scalar_one_or_none()
    if jp_profile is None:
        raise HTTPException(
            status_code=404,
            detail="Job post not found or not yet structured.",
        )

    # Verify match if provided
    if body.matchId:
        match_result = await session.execute(
            select(MatchRun).where(
                MatchRun.id == body.matchId,
                MatchRun.user_id == current_user.id,
            )
        )
        if match_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Match not found")

    # Load CV profile version for name extraction
    cv_version_result = await session.execute(
        select(CvProfileVersion).where(
            CvProfileVersion.id == profile.current_version_id,
        )
    )
    cv_version = cv_version_result.scalar_one_or_none()

    cv_name = None
    if cv_version and cv_version.structured_payload:
        basics = cv_version.structured_payload.get("basics", {}) or {}
        cv_name = basics.get("name")

    # Load match evidence if a match exists
    match_evidence: list[dict] = []
    if body.matchId:
        evidence_result = await session.execute(
            select(MatchEvidenceItem).where(
                MatchEvidenceItem.match_run_id == body.matchId,
            )
        )
        for ei in evidence_result.scalars().all():
            match_evidence.append({
                "id": ei.id,
                "support_level": ei.support_level,
                "requirement_text": ei.requirement_text,
                "requirement_type": ei.requirement_type,
                "suggestion": ei.suggestion,
                "warning": ei.warning,
            })

    # Generate questions
    questions = generate_questions(
        cv_name=cv_name,
        employer_name=jp_profile.employer,
        job_title=jp_profile.job_title or "this role",
        match_evidence=match_evidence,
    )

    # Create workflow
    wf = CoverLetterWorkflow(
        user_id=current_user.id,
        cv_profile_version_id=profile.current_version_id,
        job_post_profile_id=jp_profile.id,
        match_run_id=body.matchId,
        status="awaiting_answers",
        current_step=1,
        total_steps=3,
        question_set_version=1,
    )
    session.add(wf)
    await session.flush()

    # Store questions
    for q in questions:
        session.add(CoverLetterQuestion(
            workflow_id=wf.id,
            step_number=q.step_number,
            question_text=q.question_text,
            question_category=q.question_category,
            required=q.required,
            help_text=q.help_text,
            source_evidence_item_id=q.source_evidence_item_id,
        ))

    # Audit
    session.add(AuditEvent(
        user_id=current_user.id,
        entity_type="cover_letter_workflow",
        entity_id=wf.id,
        event_type="workflow_started",
        actor_type="user",
        ip_address=request.client.host if request.client else None,
    ))

    await session.commit()

    logger.info("cover_letter_workflow_started", workflow_id=wf.id, user_id=current_user.id)

    return _map_workflow(wf)


# ──────────────────────────────────────────────────────────────────────
# GET /cover-letters/{workflowId}/questions
# ──────────────────────────────────────────────────────────────────────


@router.get("/cover-letters/{workflowId}/questions",
            response_model=list[CoverLetterQuestionResponse])
async def get_questions(
    workflowId: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Return the question set for the current step."""
    wf = await _verify_ownership(session, workflowId, current_user.id)

    result = await session.execute(
        select(CoverLetterQuestion).where(
            CoverLetterQuestion.workflow_id == wf.id,
            CoverLetterQuestion.step_number == wf.current_step,
        ).order_by(CoverLetterQuestion.created_at)
    )
    questions = result.scalars().all()

    return [
        CoverLetterQuestionResponse(
            id=q.id,
            step_number=q.step_number,
            question_text=q.question_text,
            question_category=q.question_category,
        )
        for q in questions
    ]


# ──────────────────────────────────────────────────────────────────────
# POST /cover-letters/{workflowId}/answers
# ──────────────────────────────────────────────────────────────────────


@router.post("/cover-letters/{workflowId}/answers",
             response_model=CoverLetterWorkflowResponse, status_code=202)
async def submit_answers(
    workflowId: str,
    body: SubmitAnswersRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Submit answers for the current step."""
    wf = await _verify_ownership(session, workflowId, current_user.id)

    if wf.status != "awaiting_answers":
        raise HTTPException(
            status_code=409,
            detail=f"Workflow is in '{wf.status}' state, not awaiting answers.",
        )

    for answer_item in body.answers:
        # Verify the question belongs to this workflow at the current step
        q_result = await session.execute(
            select(CoverLetterQuestion).where(
                CoverLetterQuestion.id == answer_item.questionId,
                CoverLetterQuestion.workflow_id == wf.id,
                CoverLetterQuestion.step_number == wf.current_step,
            )
        )
        question = q_result.scalar_one_or_none()
        if question is None:
            raise HTTPException(
                status_code=404,
                detail=f"Question {answer_item.questionId} not found for current step",
            )

        session.add(CoverLetterAnswer(
            workflow_id=wf.id,
            question_id=question.id,
            answer_text=answer_item.answerText,
        ))

    # Advance step
    if wf.current_step < wf.total_steps:
        wf.current_step += 1
    else:
        # All steps complete — generate draft
        wf.status = "generating"

    await session.commit()

    # If all steps done, enqueue draft generation
    if wf.status == "generating":
        await _enqueue_draft_generation(session, wf, current_user)

    logger.info("workflow_answers_submitted", workflow_id=wf.id, step=wf.current_step)

    return _map_workflow(wf)


# ──────────────────────────────────────────────────────────────────────
# GET /cover-letters/{workflowId}/draft
# ──────────────────────────────────────────────────────────────────────


@router.get("/cover-letters/{workflowId}/draft",
            response_model=CoverLetterDraftResponse)
async def get_draft(
    workflowId: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Return the current draft of the cover letter."""
    wf = await _verify_ownership(session, workflowId, current_user.id)

    result = await session.execute(
        select(CoverLetterDraft).where(
            CoverLetterDraft.workflow_id == wf.id,
        ).order_by(CoverLetterDraft.version_number.desc()).limit(1)
    )
    draft = result.scalar_one_or_none()
    if draft is None:
        raise HTTPException(status_code=404, detail="No draft yet — answer all questions first.")

    return CoverLetterDraftResponse(
        id=draft.id,
        workflow_id=draft.workflow_id,
        version_number=draft.version_number,
        status=draft.status,
        body_text=draft.body_text,
        evidence_references=draft.evidence_references,
        prompt_version=draft.prompt_version,
        model_id=draft.model_id,
        created_at=draft.created_at.isoformat() if draft.created_at else "",
        approved_at=draft.approved_at.isoformat() if draft.approved_at else None,
    )


# ──────────────────────────────────────────────────────────────────────
# POST /cover-letters/{workflowId}/regenerate
# ──────────────────────────────────────────────────────────────────────


@router.post("/cover-letters/{workflowId}/regenerate", status_code=202,
             response_model=ProcessingJobRef)
async def regenerate(
    request: Request,
    workflowId: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Regenerate the letter (after user edits or new answers).

    Rate-limited per client IP (generation tier).
    """
    client_key = get_client_key(request)
    if not check_generation_rate_limit(client_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many cover letter requests. Please wait and try again.",
        )

    wf = await _verify_ownership(session, workflowId, current_user.id)
    if wf.status not in ("draft_ready", "approved"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot regenerate in '{wf.status}' state.",
        )

    wf.status = "generating"
    proc_job = await _enqueue_draft_generation(session, wf, current_user)
    await session.commit()

    return ProcessingJobRef(job_id=proc_job.id, status="queued")


# ──────────────────────────────────────────────────────────────────────
# POST /cover-letters/{workflowId}/approve
# ──────────────────────────────────────────────────────────────────────


@router.post("/cover-letters/{workflowId}/approve",
             response_model=CoverLetterDraftResponse)
async def approve(
    workflowId: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Mark the current draft as approved."""
    wf = await _verify_ownership(session, workflowId, current_user.id)

    if wf.status != "draft_ready":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve in '{wf.status}' state — wait for draft generation.",
        )

    # Get latest draft
    result = await session.execute(
        select(CoverLetterDraft).where(
            CoverLetterDraft.workflow_id == wf.id,
        ).order_by(CoverLetterDraft.version_number.desc()).limit(1)
    )
    draft = result.scalar_one_or_none()
    if draft is None:
        raise HTTPException(status_code=404, detail="No draft to approve.")

    draft.status = "approved"
    draft.approved_at = datetime.now(timezone.utc)
    wf.status = "approved"
    wf.approved_at = datetime.now(timezone.utc)

    session.add(AuditEvent(
        user_id=current_user.id,
        entity_type="cover_letter_workflow",
        entity_id=wf.id,
        event_type="letter_approved",
        actor_type="user",
        ip_address=request.client.host if request.client else None,
    ))

    await session.commit()

    logger.info("cover_letter_approved", workflow_id=wf.id)

    return CoverLetterDraftResponse(
        id=draft.id,
        workflow_id=draft.workflow_id,
        version_number=draft.version_number,
        status=draft.status,
        body_text=draft.body_text,
        evidence_references=draft.evidence_references,
        prompt_version=draft.prompt_version,
        model_id=draft.model_id,
        created_at=draft.created_at.isoformat() if draft.created_at else "",
        approved_at=draft.approved_at.isoformat() if draft.approved_at else None,
    )


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


async def _enqueue_draft_generation(
    session: AsyncSession, wf: CoverLetterWorkflow, user: User,
) -> ProcessingJob:
    """Create a processing job and generate the draft synchronously.

    For Phase 4 first pass, draft generation is synchronous (template-based,
    no LLM). When an LLM-backed generator is added, this will enqueue to
    a Celery worker instead.
    """
    # Load answers grouped by step
    answers_result = await session.execute(
        select(CoverLetterAnswer).where(
            CoverLetterAnswer.workflow_id == wf.id,
        ).order_by(CoverLetterAnswer.submitted_at)
    )
    all_answers = answers_result.scalars().all()

    # Load questions to determine step mapping
    questions_result = await session.execute(
        select(CoverLetterQuestion).where(
            CoverLetterQuestion.workflow_id == wf.id,
        ).order_by(CoverLetterQuestion.step_number, CoverLetterQuestion.created_at)
    )
    all_questions = questions_result.scalars().all()

    # Map answers to their question's step number
    question_step_map = {q.id: q.step_number for q in all_questions}
    answers_by_step: dict[int, list[str]] = {}
    for ans in all_answers:
        step = question_step_map.get(ans.question_id, 1)
        answers_by_step.setdefault(step, []).append(ans.answer_text)

    # Load CV profile
    cv_result = await session.execute(
        select(CvProfileVersion).where(
            CvProfileVersion.id == wf.cv_profile_version_id,
        )
    )
    cv_version = cv_result.scalar_one()
    basics = (cv_version.structured_payload or {}).get("basics", {}) or {}
    cv_name = basics.get("name")
    cv_summary = basics.get("summary")

    # Load job post
    jp_result = await session.execute(
        select(JobPostProfile).where(
            JobPostProfile.id == wf.job_post_profile_id,
        )
    )
    jp = jp_result.scalar_one()

    # Load supported evidence
    match_supported = []
    if wf.match_run_id:
        evidence_result = await session.execute(
            select(MatchEvidenceItem).where(
                MatchEvidenceItem.match_run_id == wf.match_run_id,
                MatchEvidenceItem.support_level == "supported",
            )
        )
        match_supported = [
            {"requirement_text": e.requirement_text}
            for e in evidence_result.scalars().all()
        ]

    # Assemble draft
    assembled = assemble_draft(
        cv_name=cv_name,
        cv_summary=cv_summary,
        employer_name=jp.employer,
        job_title=jp.job_title or "this role",
        tone=next((a for a in answers_by_step.get(3, []) if "formal" in a.lower() or "enthusiastic" in a.lower()), None),
        answers_by_step=answers_by_step,
        match_supported=match_supported,
    )

    # Create processing job
    proc_job = ProcessingJob(
        job_type="cover_letter_generate",
        source_entity_type="cover_letter_workflow",
        source_entity_id=wf.id,
        user_id=user.id,
        status="completed",
        completed_at=datetime.now(timezone.utc),
    )
    session.add(proc_job)
    await session.flush()

    # Create draft
    max_ver_result = await session.execute(
        select(CoverLetterDraft.version_number).where(
            CoverLetterDraft.workflow_id == wf.id,
        ).order_by(CoverLetterDraft.version_number.desc()).limit(1)
    )
    max_ver = max_ver_result.scalar() or 0

    draft = CoverLetterDraft(
        workflow_id=wf.id,
        version_number=max_ver + 1,
        status="generated",
        body_text=assembled.body_text,
        evidence_references=assembled.evidence_references or None,
        tone=jp.job_title,
        prompt_version="cover_letter_template_v1",
        model_id="rules-based",
    )
    session.add(draft)

    wf.status = "draft_ready"
    wf.completed_at = datetime.now(timezone.utc)

    return proc_job