"""Domain-agnostic generation engine — the non-fabrication safety
mechanism shared by every LLM-backed generation task in this codebase
(tailored CV sections, cover letters, and any future one).

Extracted from tailored_cv_generation.py (Sprint 3) so a second caller
(cover letter generation, Sprint 4) doesn't duplicate the retry/verify
loop — this function's behavior IS the "never persist unverified content"
guarantee, and two copies would risk silently drifting the next time
retry/verification behavior gets tuned for one and not the other.

No DB session handling here, same as its origin module — callers load
rows and persist results; this is pure orchestration over plain Python
objects, testable with a fake LLM client and no live DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import GENERATION_SCHEMA_VALIDATION_FAILED_COUNTER
from app.core.metrics_push import push_worker_metrics
from app.extraction import evidence_binder
from app.services.llm_client import LlmCallError, LlmSchemaValidationError, generate_structured

logger = get_logger(__name__)

# Every generation task shares this output shape today — kept as a
# distinct, named object (not inlined into the function) so a caller
# needing a per-task copy (to diverge independently later without a
# silent shared-schema coupling) can `dict(GENERATION_JSON_SCHEMA)`.
GENERATION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "contentText": {"type": "string"},
        "evidenceIndexes": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["contentText", "evidenceIndexes"],
    "additionalProperties": False,
}


@dataclass
class SectionResult:
    section_type: str
    content_text: str
    evidence_references: list[str]
    generation_task: str
    prompt_version: str | None
    model_id: str | None
    validation_status: str
    order_index: int
    source_item_id: str | None = None


@dataclass
class GenerationOutcome:
    sections: list[SectionResult] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0


def generate_and_verify_section(
    *,
    section_type: str,
    system_prompt: str,
    generation_task: str,
    prompt_version: str,
    schema: dict,
    schema_name: str,
    candidates: list[evidence_binder.EvidenceCandidate],
    user_payload: str,
    order_index: int,
    outcome: GenerationOutcome,
    overlap_threshold: float | None = None,
    max_attempts: int | None = None,
    extra_verification_context: str = "",
    source_item_id: str | None = None,
    llm_client_override=None,
) -> SectionResult | None:
    """One generation task end to end: call the model with an
    already-built user payload, verify the result against the real
    evidence it cited, retry once with the specific failure appended on
    rejection, and omit (return None, record an issue) if it still
    fails. Never returns unverified content — 'omit, don't fabricate' is
    enforced here, structurally, not by convention.

    Deliberately takes a pre-built `user_payload` rather than building
    one internally: different generation tasks need different payload
    shapes (tailored-CV sections take job_requirements/instructions;
    cover letters also need job title/employer/candidate name/tone) —
    payload construction is the caller's domain-specific concern, this
    function only owns the retry/verify contract every task shares.

    overlap_threshold/max_attempts default to the tailored-CV settings
    (this function's original caller) when not given, so existing callers
    are unaffected; a new caller (e.g. cover letters) passes its own
    independently-tunable values explicitly.

    extra_verification_context: real, code-supplied facts (e.g. a job
    title, employer name, or candidate name) that legitimately belong in
    the generated text but aren't part of the citable evidence pool —
    found necessary live: a cover letter conventionally states the role/
    employer/candidate name, and the hard-fact check would otherwise
    reject every one of those as an "unsupported" proper noun even
    though nothing was fabricated. Appended to the reference text both
    checks run against; never citable via evidenceIndexes.

    source_item_id: the single CvExperienceItem/CvProjectItem row this
    section was generated for, if any — carried through unchanged onto
    the returned SectionResult so a downstream renderer (e.g. the DOCX
    export template) can attach a real company/title/date header to the
    section instead of a bare bullet block. None for sections with no
    single source row (summary, education, skills, cover letters).
    """
    if not candidates:
        outcome.issues.append(f"{section_type}: no evidence available, section omitted")
        return None

    if overlap_threshold is None:
        overlap_threshold = settings.tailored_cv_evidence_overlap_threshold
    if max_attempts is None:
        max_attempts = settings.tailored_cv_max_generation_retries
    max_attempts = max(1, max_attempts)

    base_payload = user_payload

    correction: str | None = None
    for attempt in range(max_attempts):
        payload = base_payload
        if correction:
            payload = (
                f"{base_payload}\n\nYour previous attempt was rejected: {correction}\n"
                f"Try again, using only the evidence pool above."
            )

        try:
            result = generate_structured(
                system_prompt=system_prompt,
                user_payload=payload,
                json_schema=schema,
                schema_name=schema_name,
                client=llm_client_override,
            )
        except (LlmCallError, LlmSchemaValidationError) as e:
            correction = str(e)
            logger.warning(
                "generation_call_failed",
                section_type=section_type, attempt=attempt, error=str(e),
            )
            continue

        outcome.total_prompt_tokens += result.prompt_tokens
        outcome.total_completion_tokens += result.completion_tokens

        content_text = (result.data.get("contentText") or "").strip()
        evidence_indexes = result.data.get("evidenceIndexes")

        if not content_text or not isinstance(evidence_indexes, list) or not evidence_indexes:
            correction = (
                "contentText was empty or evidenceIndexes was empty — every "
                "generated section must cite at least one evidence index."
            )
            continue

        cited_candidates = [
            candidates[i] for i in evidence_indexes
            if isinstance(i, int) and 0 <= i < len(candidates)
        ]
        if not cited_candidates:
            correction = (
                "evidenceIndexes did not reference any valid index from the "
                "evidence pool you were given."
            )
            continue

        evidence_texts = [c.searchable_text for c in cited_candidates]
        if extra_verification_context:
            evidence_texts.append(extra_verification_context)
        verification = evidence_binder.verify_claim_against_evidence(
            content_text,
            evidence_texts,
            overlap_threshold,
        )
        if not verification.passed:
            correction = verification.reason
            continue

        return SectionResult(
            section_type=section_type,
            content_text=content_text,
            evidence_references=[c.row_id for c in cited_candidates],
            generation_task=generation_task,
            prompt_version=prompt_version,
            model_id=result.model,
            validation_status="passed",
            order_index=order_index,
            source_item_id=source_item_id,
        )

    outcome.issues.append(
        f"{section_type}: failed verification after {max_attempts} attempt(s) "
        f"({correction}), section omitted"
    )
    # Schema/evidence validation failed — a possible injection attempt (§10
    # alerts on a spike in these).
    GENERATION_SCHEMA_VALIDATION_FAILED_COUNTER.inc()
    push_worker_metrics("worker_generation")
    return None
