"""Orchestrates tailored CV draft generation.

Binds evidence, calls the LLM per generation task, verifies every result
against the real content it claims to be grounded in, assembles sections,
and synthesizes the improvement checklist (product extension #3, no
separate model call). No DB session handling here —
worker_jobs.py::process_cv_generate loads rows and persists the result;
this module is pure orchestration logic over plain Python objects,
testable with a fake LLM client and no live DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import settings
from app.core.logging import get_logger
from app.extraction import evidence_binder
from app.prompts import tailored_cv_prompts as prompts
from app.services.llm_client import LlmCallError, LlmSchemaValidationError, generate_structured

logger = get_logger(__name__)

SECTION_SUMMARY = "summary"
SECTION_EXPERIENCE = "experience"
SECTION_SKILLS = "skills"

SKILLS_GENERATION_TASK = "tailored_cv_skills"
SKILLS_MODEL_ID = "rules-based"

# Every support level except "supported" — surfaced via the improvement
# checklist instead of generation. Includes partially_supported (usable
# in generation, but still worth flagging as incomplete) and
# contradictory/unclear (never usable in generation at all — this is
# their only path to visibility, per product-extensions.md #3 and
# 09-test-plan.md §6's "never silently resolved" requirement).
_CHECKLIST_ELIGIBLE_SUPPORT_LEVELS = frozenset(
    {"partially_supported", "unsupported", "contradictory", "unclear"}
)

_PRIORITY_HIGH = "high"
_PRIORITY_MEDIUM = "medium"
_PRIORITY_LOW = "low"

_SUGGESTION_TEMPLATES = {
    "unsupported": "No evidence of '{req}' found in your CV. If you have relevant experience not currently listed, add it before reapplying, or address it directly in your cover letter.",
    "contradictory": "Your CV has conflicting information related to '{req}'. Review and resolve the conflicting entries — this can't be used in a tailored draft until it's clear which is correct.",
    "unclear": "The evidence for '{req}' extracted with low confidence. Check the formatting of that section of your CV, or reprocess it.",
    "partially_supported": "Your CV touches on '{req}' but doesn't fully demonstrate it. Consider adding more specific detail if you have it.",
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


@dataclass
class GenerationOutcome:
    sections: list[SectionResult] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0


def _generate_and_verify_section(
    *,
    section_type: str,
    system_prompt: str,
    generation_task: str,
    prompt_version: str,
    schema: dict,
    schema_name: str,
    candidates: list[evidence_binder.EvidenceCandidate],
    job_requirements: list[str],
    instructions: str | None,
    order_index: int,
    outcome: GenerationOutcome,
    llm_client_override=None,
) -> SectionResult | None:
    """One generation task end to end: build the prompt, call the model,
    verify the result against the real evidence it cited, retry once with
    the specific failure appended on rejection, and omit (return None,
    record an issue) if it still fails. Never returns unverified content —
    'omit, don't fabricate' is enforced here, structurally, not by
    convention.
    """
    if not candidates:
        outcome.issues.append(f"{section_type}: no evidence available, section omitted")
        return None

    evidence_pool_text = prompts.format_evidence_pool(candidates)
    base_payload = prompts.build_user_payload(
        evidence_pool_text=evidence_pool_text,
        job_requirements=job_requirements,
        instructions=instructions,
    )

    correction: str | None = None
    max_attempts = max(1, settings.tailored_cv_max_generation_retries)
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
                "tailored_cv_generation_call_failed",
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

        verification = evidence_binder.verify_claim_against_evidence(
            content_text,
            [c.searchable_text for c in cited_candidates],
            settings.tailored_cv_evidence_overlap_threshold,
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
        )

    outcome.issues.append(
        f"{section_type}: failed verification after {max_attempts} attempt(s) "
        f"({correction}), section omitted"
    )
    return None


def _generate_skills_section(
    *, match_evidence_items, all_candidates, order_index: int,
) -> SectionResult | None:
    """Deterministic filter of matched CvSkillItem rows — no LLM call, no
    judgment call, zero marginal fabrication risk. Per the architecture
    doc's own principle of reserving model calls for genuinely judgment-
    requiring tasks."""
    bound = evidence_binder.bind_evidence_pool(match_evidence_items, all_candidates)
    skill_candidates = [c for c in bound if c.row_type == evidence_binder.SKILL]
    if not skill_candidates:
        return None

    content_text = ", ".join(c.searchable_text for c in skill_candidates)
    return SectionResult(
        section_type=SECTION_SKILLS,
        content_text=content_text,
        evidence_references=[c.row_id for c in skill_candidates],
        generation_task=SKILLS_GENERATION_TASK,
        prompt_version=None,
        model_id=SKILLS_MODEL_ID,
        validation_status="passed",
        order_index=order_index,
    )


def generate_draft_sections(
    *,
    match_evidence_items: list,
    experience_items: list,
    education_items: list,
    skill_items: list,
    job_requirements: list[str],
    instructions: str | None = None,
    llm_client_override=None,
) -> GenerationOutcome:
    """Generates every section of a tailored CV draft. education/
    certifications/projects sections are never attempted — there's no
    populated evidence source for them in this codebase today
    (CvEducationItem rows are never inserted anywhere; no certification/
    project tables exist at all) — omitting what has no evidence is
    correct non-fabrication behavior, not a gap in this function.
    """
    outcome = GenerationOutcome()
    order_index = 0

    all_candidates = evidence_binder.build_candidate_pool(experience_items, education_items, skill_items)
    candidates_by_id = {c.row_id: c for c in all_candidates}
    full_pool = evidence_binder.bind_evidence_pool(match_evidence_items, all_candidates)

    summary = _generate_and_verify_section(
        section_type=SECTION_SUMMARY,
        system_prompt=prompts.TAILORED_CV_SUMMARY_SYSTEM_PROMPT,
        generation_task=prompts.SUMMARY_GENERATION_TASK,
        prompt_version=prompts.SUMMARY_PROMPT_VERSION,
        schema=prompts.SUMMARY_JSON_SCHEMA,
        schema_name="tailored_cv_summary",
        candidates=full_pool,
        job_requirements=job_requirements,
        instructions=instructions,
        order_index=order_index,
        outcome=outcome,
        llm_client_override=llm_client_override,
    )
    if summary:
        outcome.sections.append(summary)
        order_index += 1

    relevance = evidence_binder.count_experience_relevance(match_evidence_items, all_candidates)
    ranked_experience_ids = sorted(relevance, key=lambda rid: relevance[rid], reverse=True)
    ranked_experience_ids = ranked_experience_ids[: settings.tailored_cv_max_experience_items]

    for exp_id in ranked_experience_ids:
        exp_candidate = candidates_by_id.get(exp_id)
        if exp_candidate is None:
            continue

        exp_item = next((e for e in experience_items if e.id == exp_id), None)
        related_skill_names = {
            t.strip().lower() for t in (exp_item.technologies or [])
        } if exp_item else set()
        related_skills = [
            c for c in all_candidates
            if c.row_type == evidence_binder.SKILL
            and c.searchable_text.strip().lower() in related_skill_names
        ]
        item_candidates = [exp_candidate] + related_skills

        section = _generate_and_verify_section(
            section_type=SECTION_EXPERIENCE,
            system_prompt=prompts.TAILORED_CV_EXPERIENCE_BULLET_SYSTEM_PROMPT,
            generation_task=prompts.EXPERIENCE_BULLET_GENERATION_TASK,
            prompt_version=prompts.EXPERIENCE_BULLET_PROMPT_VERSION,
            schema=prompts.EXPERIENCE_BULLET_JSON_SCHEMA,
            schema_name="tailored_cv_experience_bullet",
            candidates=item_candidates,
            job_requirements=job_requirements,
            instructions=instructions,
            order_index=order_index,
            outcome=outcome,
            llm_client_override=llm_client_override,
        )
        if section:
            outcome.sections.append(section)
            order_index += 1

    skills_section = _generate_skills_section(
        match_evidence_items=match_evidence_items,
        all_candidates=all_candidates,
        order_index=order_index,
    )
    if skills_section:
        outcome.sections.append(skills_section)
        order_index += 1

    return outcome


def assemble_content_json(sections: list[SectionResult]) -> dict:
    return {
        "sections": [
            {
                "sectionType": s.section_type,
                "contentText": s.content_text,
                "orderIndex": s.order_index,
            }
            for s in sorted(sections, key=lambda s: s.order_index)
        ]
    }


def render_text_from_sections(sections: list[SectionResult]) -> str:
    ordered = sorted(sections, key=lambda s: s.order_index)
    return "\n\n".join(s.content_text for s in ordered)


def build_validation_result(outcome: GenerationOutcome) -> dict:
    return {"passed": len(outcome.sections) > 0, "issues": outcome.issues}


def _priority_for(support_level: str, requirement_type: str) -> str:
    if requirement_type == "required" and support_level in ("unsupported", "contradictory", "unclear"):
        return _PRIORITY_HIGH
    if requirement_type == "required" and support_level == "partially_supported":
        return _PRIORITY_MEDIUM
    if requirement_type == "preferred" and support_level == "unsupported":
        return _PRIORITY_MEDIUM
    return _PRIORITY_LOW


def build_improvement_checklist(match_evidence_items) -> list[dict]:
    """Deterministic, no model call — the same discipline as extension
    #3's design note: keep judgment-light, deterministic steps
    deterministic, reserve LLM calls for genuinely judgment-requiring
    tasks. Surfaces every requirement not fully supported, including
    contradictory/unclear items excluded from generation entirely, so
    they're visible to the user instead of silently vanishing.
    """
    checklist = []
    for item in match_evidence_items:
        if item.support_level not in _CHECKLIST_ELIGIBLE_SUPPORT_LEVELS:
            continue
        suggestion = (
            item.suggestion
            or item.warning
            or _SUGGESTION_TEMPLATES.get(
                item.support_level, "Review this requirement against your CV."
            ).format(req=item.requirement_text)
        )
        checklist.append({
            "requirementText": item.requirement_text,
            "supportLevel": item.support_level,
            "suggestion": suggestion,
            "priority": _priority_for(item.support_level, item.requirement_type),
        })
    return checklist
