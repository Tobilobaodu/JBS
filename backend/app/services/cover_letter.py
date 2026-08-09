"""Cover letter question generator and draft assembler.

Phase 4 first pass uses rules-based question generation and template-based
draft assembly. An LLM-backed generator can be swapped in later without
changing the API or worker.

Per the non-fabrication rule: questions are generated ONLY from match
evidence items flagged as unsupported, contradictory, or unclear. Missing
evidence results in a question, never an invented claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ──────────────────────────────────────────────────────────────────────
# Question categories (per 05-openapi.yaml)
# ──────────────────────────────────────────────────────────────────────

CAT_EMPLOYER_INTEREST = "employer_interest"
CAT_MOTIVATION = "motivation"
CAT_RELEVANT_EXAMPLE = "relevant_example"
CAT_TONE_PREFERENCE = "tone_preference"
CAT_AVAILABILITY = "availability"
CAT_CLARIFICATION = "clarification"


@dataclass
class GeneratedQuestion:
    """A question to present to the user at a specific workflow step."""
    step_number: int
    question_text: str
    question_category: str
    required: bool = True
    help_text: str | None = None
    source_evidence_item_id: str | None = None


# ──────────────────────────────────────────────────────────────────────
# Question generation
# ──────────────────────────────────────────────────────────────────────


def generate_questions(
    cv_name: str | None,
    employer_name: str | None,
    job_title: str,
    match_evidence: list[dict],
) -> list[GeneratedQuestion]:
    """Generate question sets from match evidence gaps.

    Each unsupported/contradictory/unclear evidence item becomes one
    clarification question. Standard motivation/interest/availability
    questions are added as a fixed set across all workflows.

    Args:
        cv_name: Candidate's name from the CV profile (or None).
        employer_name: Employer from the job post (or None).
        job_title: Job title from the job post.
        match_evidence: List of match evidence item dicts with keys
            support_level, requirement_text, requirement_type, suggestion, warning.

    Returns:
        List of GeneratedQuestion, organised by step_number.
    """
    questions: list[GeneratedQuestion] = []

    # ── Step 1: Employer interest & motivation ─────────────────────
    questions.append(GeneratedQuestion(
        step_number=1,
        question_text=f"Why are you interested in the {job_title} role"
                       f"{' at ' + employer_name if employer_name else ''}?",
        question_category=CAT_EMPLOYER_INTEREST,
        required=True,
        help_text="Mention what attracted you to this specific role and company.",
    ))
    questions.append(GeneratedQuestion(
        step_number=1,
        question_text="What about this role aligns with your career goals?",
        question_category=CAT_MOTIVATION,
        required=True,
        help_text="Connect this opportunity to where you want your career to go.",
    ))

    # ── Step 2: Clarification questions from match gaps ────────────
    gap_items = [
        e for e in match_evidence
        if e.get("support_level") in ("unsupported", "contradictory", "unclear")
    ]
    for i, item in enumerate(gap_items[:5]):  # cap at 5 gap questions per step
        req_text = item.get("requirement_text", "")
        support = item.get("support_level", "unsupported")
        suggestion = item.get("suggestion") or item.get("warning") or ""

        if support == "unsupported":
            prompt = f"The job requires '{req_text}'. Can you provide a relevant example from your experience?"
            help_text = suggestion or "Describe a specific project or achievement."
        elif support == "contradictory":
            prompt = f"Your CV shows conflicting information about '{req_text}'. Can you clarify which is correct?"
            help_text = suggestion
        else:  # unclear
            prompt = f"Your CV may mention '{req_text}' but our extraction was uncertain. Can you confirm or elaborate?"
            help_text = suggestion

        questions.append(GeneratedQuestion(
            step_number=2,
            question_text=prompt,
            question_category=CAT_CLARIFICATION,
            required=False,
            help_text=help_text if help_text else None,
            source_evidence_item_id=item.get("id"),
        ))

    if not gap_items:
        # If no gaps, ask for a general relevant example
        questions.append(GeneratedQuestion(
            step_number=2,
            question_text=(
                "What is one achievement or project you'd like to highlight "
                f"in relation to this {job_title} role?"
            ),
            question_category=CAT_RELEVANT_EXAMPLE,
            required=True,
        ))

    # ── Step 3: Tone, availability, closing preferences ────────────
    questions.append(GeneratedQuestion(
        step_number=3,
        question_text="What tone would you like for this letter?",
        question_category=CAT_TONE_PREFERENCE,
        required=False,
        help_text="e.g. formal, enthusiastic, concise, detailed",
    ))
    questions.append(GeneratedQuestion(
        step_number=3,
        question_text="Do you have any availability constraints or preferred start dates?",
        question_category=CAT_AVAILABILITY,
        required=False,
        help_text="Optional — leave blank if not applicable.",
    ))
    questions.append(GeneratedQuestion(
        step_number=3,
        question_text="Is there anything else the hiring manager should know?",
        question_category=CAT_CLARIFICATION,
        required=False,
        help_text="Any additional context, certifications, or achievements.",
    ))

    return questions


# ──────────────────────────────────────────────────────────────────────
# Draft assembly
# ──────────────────────────────────────────────────────────────────────


@dataclass
class AssembledDraft:
    """A cover letter draft assembled from CV data, match evidence, and user answers."""
    body_text: str
    evidence_references: list[str]


def assemble_draft(
    cv_name: str | None,
    cv_summary: str | None,
    employer_name: str | None,
    job_title: str,
    tone: str | None,
    answers_by_step: dict[int, list[str]],
    match_supported: list[dict],
) -> AssembledDraft:
    """Assemble a cover letter body from structured inputs.

    Uses template substitution — no LLM. Each paragraph is backed by
    either CV evidence or a user-submitted answer.

    Args:
        cv_name: Candidate name.
        cv_summary: Professional summary from the CV.
        employer_name: Employer name from the job post.
        job_title: Job title.
        tone: User-preferred tone (e.g. "formal", "enthusiastic").
        answers_by_step: dict mapping step_number → list of answer strings.
        match_supported: List of supported match evidence items.

    Returns:
        AssembledDraft with body_text and evidence_references.
    """
    evidence_refs: list[str] = []
    salutation = "Dear Hiring Manager"

    # ── Paragraph 1: Introduction (motivation + interest) ──────────
    intro_lines = [f"I am writing to express my interest in the {job_title} position"]
    if employer_name:
        intro_lines[-1] += f" at {employer_name}"
    intro_lines[-1] += "."

    # Use the step-1 answers (interest + motivation)
    step1_answers = answers_by_step.get(1, [])
    if len(step1_answers) >= 1:
        intro_lines.append(step1_answers[0])
        evidence_refs.append("answer:motivation")
    if len(step1_answers) >= 2:
        intro_lines.append(step1_answers[1])
        evidence_refs.append("answer:career_goals")

    intro = " ".join(intro_lines)

    # ── Paragraph 2: Relevant experience (step-2 answers + CV) ─────
    experience_lines = []
    if cv_summary:
        experience_lines.append(
            f"With my background — {cv_summary.strip('.')} — "
            f"I bring directly relevant experience to this role."
        )
        evidence_refs.append("cv:summary")

    step2_answers = answers_by_step.get(2, [])
    for ans in step2_answers:
        if ans.strip():
            experience_lines.append(ans)
            evidence_refs.append("answer:relevant_example")

    # Supported skills
    if match_supported:
        skills_list = [e.get("requirement_text", "") for e in match_supported[:6]]
        if skills_list:
            experience_lines.append(
                f"Through my career I have built expertise in "
                f"{', '.join(skills_list)}."
            )
            evidence_refs.append("match:supported_skills")

    experience_text = " ".join(experience_lines)

    # ── Paragraph 3: Closing ───────────────────────────────────────
    step3_answers = answers_by_step.get(3, [])
    closing_lines = [
        f"I would welcome the opportunity to discuss how my experience "
        f"aligns with the {job_title} role.",
    ]
    if step3_answers and step3_answers[-1]:
        closing_lines.append(step3_answers[-1])
        evidence_refs.append("answer:additional_context")
    closing_lines.append("Thank you for your consideration.")

    closing = " ".join(closing_lines)

    # ── Assemble full letter ───────────────────────────────────────
    parts = [salutation, "", intro, "", experience_text]
    if experience_text:
        parts += ["", closing]
    else:
        parts += ["", closing]

    if tone and tone.lower() != "formal":
        # Simple tone hint — future: pass through LLM for tone adaptation
        pass

    body = "\n\n".join(p for p in parts if p)
    if cv_name:
        body += f"\n\nSincerely,\n{cv_name}"

    return AssembledDraft(
        body_text=body,
        evidence_references=evidence_refs,
    )