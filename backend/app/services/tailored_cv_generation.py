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

from app.core.config import settings
from app.core.logging import get_logger
from app.extraction import evidence_binder
from app.prompts import tailored_cv_prompts as prompts
from app.services.generation_core import (
    GenerationOutcome,
    SectionResult,
    generate_and_verify_section,
)

logger = get_logger(__name__)

SECTION_SUMMARY = "summary"
SECTION_EXPERIENCE = "experience"
SECTION_SKILLS = "skills"
SECTION_EDUCATION = "education"
SECTION_PROJECTS = "projects"

SKILLS_GENERATION_TASK = "tailored_cv_skills"
SKILLS_MODEL_ID = "rules-based"

EDUCATION_GENERATION_TASK = "tailored_cv_education"
EDUCATION_MODEL_ID = "rules-based"

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


def _format_education_line(item) -> str:
    degree_field = ", ".join(p for p in [item.degree, item.field] if p)
    tail_parts = [item.institution, f"({item.year})" if item.year else None]
    tail = " ".join(p for p in tail_parts if p)
    if degree_field and tail:
        return f"{degree_field} — {tail}"
    return degree_field or tail or ""


def _format_certification_line(item) -> str:
    parts = [item.name or ""]
    if item.issuer:
        parts.append(f"— {item.issuer}")
    if item.year:
        parts.append(f"({item.year})")
    return " ".join(p for p in parts if p)


def _generate_education_section(
    *, education_items, certification_items, order_index: int,
) -> SectionResult | None:
    """Deterministic, no LLM call — a factual listing, not a claim needing
    verification or creative rewriting, same reasoning as the skills
    section. Built from the raw, unfiltered CV rows (not job-match-
    relevance-filtered) — a real degree shouldn't disappear from a
    tailored CV just because this particular posting didn't ask for one.

    Certifications/diplomas are evaluated together with formal education
    as one combined gate: omit only if BOTH lists are empty, so a
    certification-only CV (no formal degree) still gets an education-type
    section — the direct implementation of the product requirement that
    certifications count as checkable qualifications evidence.
    """
    if not education_items and not certification_items:
        return None

    lines = [_format_education_line(e) for e in education_items]
    lines.extend(_format_certification_line(c) for c in certification_items)
    content_text = "\n".join(line for line in lines if line)

    evidence_references = [e.id for e in education_items] + [c.id for c in certification_items]

    return SectionResult(
        section_type=SECTION_EDUCATION,
        content_text=content_text,
        evidence_references=evidence_references,
        generation_task=EDUCATION_GENERATION_TASK,
        prompt_version=None,
        model_id=EDUCATION_MODEL_ID,
        validation_status="passed",
        order_index=order_index,
    )


def generate_draft_sections(
    *,
    match_evidence_items: list,
    experience_items: list,
    education_items: list,
    skill_items: list,
    certification_items: list = (),
    project_items: list = (),
    job_requirements: list[str],
    instructions: str | None = None,
    llm_client_override=None,
) -> GenerationOutcome:
    """Generates every section of a tailored CV draft.

    Section order: Summary → Education → Experience → Projects → Skills
    (conventional CV layout). Education is deterministic (factual
    listing); Projects are LLM-rewritten one call per project, mirroring
    the experience-bullet loop's per-item evidence scoping and
    verification. A project with zero job-match relevance is still
    attempted (relevance only ranks display order, never gates inclusion,
    unlike experience) — "if projects exist, give them a section" has no
    "only if relevant to this job" qualifier.
    """
    outcome = GenerationOutcome()
    order_index = 0

    all_candidates = evidence_binder.build_candidate_pool(
        experience_items, education_items, skill_items,
        certification_items=certification_items, project_items=project_items,
    )
    candidates_by_id = {c.row_id: c for c in all_candidates}
    full_pool = evidence_binder.bind_evidence_pool(match_evidence_items, all_candidates)

    summary = generate_and_verify_section(
        section_type=SECTION_SUMMARY,
        system_prompt=prompts.TAILORED_CV_SUMMARY_SYSTEM_PROMPT,
        generation_task=prompts.SUMMARY_GENERATION_TASK,
        prompt_version=prompts.SUMMARY_PROMPT_VERSION,
        schema=prompts.SUMMARY_JSON_SCHEMA,
        schema_name="tailored_cv_summary",
        candidates=full_pool,
        user_payload=prompts.build_user_payload(
            evidence_pool_text=prompts.format_evidence_pool(full_pool),
            job_requirements=job_requirements,
            instructions=instructions,
        ),
        order_index=order_index,
        outcome=outcome,
        llm_client_override=llm_client_override,
    )
    if summary:
        outcome.sections.append(summary)
        order_index += 1

    education_section = _generate_education_section(
        education_items=education_items,
        certification_items=certification_items,
        order_index=order_index,
    )
    if education_section:
        outcome.sections.append(education_section)
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

        section = generate_and_verify_section(
            section_type=SECTION_EXPERIENCE,
            system_prompt=prompts.TAILORED_CV_EXPERIENCE_BULLET_SYSTEM_PROMPT,
            generation_task=prompts.EXPERIENCE_BULLET_GENERATION_TASK,
            prompt_version=prompts.EXPERIENCE_BULLET_PROMPT_VERSION,
            schema=prompts.EXPERIENCE_BULLET_JSON_SCHEMA,
            schema_name="tailored_cv_experience_bullet",
            candidates=item_candidates,
            user_payload=prompts.build_user_payload(
                evidence_pool_text=prompts.format_evidence_pool(item_candidates),
                job_requirements=job_requirements,
                instructions=instructions,
            ),
            order_index=order_index,
            outcome=outcome,
            llm_client_override=llm_client_override,
        )
        if section:
            outcome.sections.append(section)
            order_index += 1

    # Projects: relevance ranks display order when there are more projects
    # than the cap, but a zero-relevance project is still attempted rather
    # than excluded (unlike experience) — see the docstring above.
    project_relevance = evidence_binder.count_project_relevance(match_evidence_items, all_candidates)
    ranked_project_ids = sorted(project_relevance, key=lambda rid: project_relevance[rid], reverse=True)
    remaining_project_ids = [p.id for p in project_items if p.id not in ranked_project_ids]
    ranked_project_ids = (ranked_project_ids + remaining_project_ids)[: settings.tailored_cv_max_project_items]

    for proj_id in ranked_project_ids:
        proj_candidate = candidates_by_id.get(proj_id)
        if proj_candidate is None:
            continue

        proj_item = next((p for p in project_items if p.id == proj_id), None)
        related_skill_names = {
            t.strip().lower() for t in (proj_item.technologies or [])
        } if proj_item else set()
        related_skills = [
            c for c in all_candidates
            if c.row_type == evidence_binder.SKILL
            and c.searchable_text.strip().lower() in related_skill_names
        ]
        item_candidates = [proj_candidate] + related_skills

        section = generate_and_verify_section(
            section_type=SECTION_PROJECTS,
            system_prompt=prompts.TAILORED_CV_PROJECT_SYSTEM_PROMPT,
            generation_task=prompts.PROJECT_GENERATION_TASK,
            prompt_version=prompts.PROJECT_PROMPT_VERSION,
            schema=prompts.PROJECT_JSON_SCHEMA,
            schema_name="tailored_cv_project",
            candidates=item_candidates,
            user_payload=prompts.build_user_payload(
                evidence_pool_text=prompts.format_evidence_pool(item_candidates),
                job_requirements=job_requirements,
                instructions=instructions,
            ),
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
