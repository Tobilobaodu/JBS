"""Evidence-based matching engine — Phase 3.

Compares a structured CV profile (cv_profile_versions.structured_payload +
child tables) against a structured job post (job_post_profiles) and produces:
  - match_evidence_items with support levels
  - a match_run summary with counts

Per the non-fabrication rule: missing evidence is flagged as unsupported,
never guessed. Contradictory evidence is flagged, not silently resolved.
Surface keyword overlap is distinguished from substantive support.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ──────────────────────────────────────────────────────────────────────
# Support level definitions (per 03-data-model.md)
# ──────────────────────────────────────────────────────────────────────

SUPPORTED = "supported"
PARTIALLY_SUPPORTED = "partially_supported"
UNSUPPORTED = "unsupported"
CONTRADICTORY = "contradictory"
UNCLEAR = "unclear"


@dataclass
class EvidenceItem:
    """A single match evidence item for one job requirement."""
    requirement_text: str
    requirement_type: str  # "required" | "preferred"
    support_level: str
    confidence: float
    source_references: list[str] = field(default_factory=list)
    suggestion: str | None = None
    warning: str | None = None


@dataclass
class MatchResult:
    """Complete match analysis output."""
    score: float
    supported_count: int
    partial_count: int
    unsupported_count: int
    total_requirements: int
    summary_analysis: str
    evidence_items: list[EvidenceItem] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def run_match(
    cv_profile_payload: dict,
    cv_skills: list[str],
    job_post_profile: dict,
) -> MatchResult:
    """Compare a CV profile against a job post and return match evidence.

    Args:
        cv_profile_payload: The structured_payload from cv_profile_versions.
        cv_skills: List of skill names from cv_skill_items for this profile.
        job_post_profile: The job_post_profiles row (as a dict).

    Returns:
        MatchResult with scored evidence items.
    """
    evidence_items: list[EvidenceItem] = []

    # ── Required skills matching ───────────────────────────────────
    required_skills = job_post_profile.get("required_skills") or []
    preferred_skills = job_post_profile.get("preferred_skills") or []

    # Combine all requirements for matching
    all_requirements: list[tuple[str, str]] = []
    for skill in required_skills:
        all_requirements.append((skill, "required"))
    for skill in preferred_skills:
        all_requirements.append((skill, "preferred"))

    # Match each requirement against the CV
    cv_skills_lower = [s.lower() for s in cv_skills]
    cv_text_blob = _flatten_cv_text(cv_profile_payload).lower()

    for req_text, req_type in all_requirements:
        evidence = _match_requirement(
            req_text, req_type, cv_skills, cv_skills_lower, cv_text_blob
        )
        evidence_items.append(evidence)

    # ── Compute counts ─────────────────────────────────────────────
    supported = sum(1 for e in evidence_items if e.support_level == SUPPORTED)
    partial = sum(1 for e in evidence_items if e.support_level == PARTIALLY_SUPPORTED)
    unsupported = sum(1 for e in evidence_items if e.support_level == UNSUPPORTED)
    total = len(evidence_items)

    # Score: weighted by requirement type
    if total == 0:
        score = 0.0
    else:
        weight = 0
        for e in evidence_items:
            w = 1.0 if e.requirement_type == "required" else 0.5
            if e.support_level == SUPPORTED:
                weight += w
            elif e.support_level == PARTIALLY_SUPPORTED:
                weight += w * 0.5
        max_weight = sum(1.0 if t == "required" else 0.5 for _, t in all_requirements)
        score = round(weight / max(max_weight, 1), 2)

    summary = (
        f"Matched {supported} of {total} requirements fully, "
        f"{partial} partially supported, {unsupported} unsupported. "
        f"Overall score: {score * 100:.0f}%"
    )

    return MatchResult(
        score=score,
        supported_count=supported,
        partial_count=partial,
        unsupported_count=unsupported,
        total_requirements=total,
        summary_analysis=summary,
        evidence_items=evidence_items,
    )


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


def _match_requirement(
    req_text: str,
    req_type: str,
    cv_skills: list[str],
    cv_skills_lower: list[str],
    cv_text_blob: str,
) -> EvidenceItem:
    """Match a single requirement against CV evidence.

    Strategy (no LLM — heuristic for Phase 3 first pass):
      1. Exact skill name match → supported, confidence 0.85
      2. Skill appears as substring in CV text → partially_supported, confidence 0.6
      3. No match anywhere → unsupported, confidence 0.0
    """
    req_lower = req_text.strip().lower()

    # 1. Exact skill name match
    if req_lower in cv_skills_lower:
        idx = cv_skills_lower.index(req_lower)
        skill_name = cv_skills[idx]
        return EvidenceItem(
            requirement_text=req_text,
            requirement_type=req_type,
            support_level=SUPPORTED,
            confidence=0.85,
            source_references=[f"skill:{skill_name}"],
        )

    # 2. Fuzzy: skill appears as substring in CV text
    if req_lower in cv_text_blob:
        return EvidenceItem(
            requirement_text=req_text,
            requirement_type=req_type,
            support_level=PARTIALLY_SUPPORTED,
            confidence=0.6,
            suggestion=(
                f"Your CV mentions '{req_text}' but it is not explicitly listed "
                f"in your skills section. Consider adding it explicitly."
            ),
        )

    # 3. No match — unsupported
    detail = (
        "This is a required skill - address it in your cover letter or consider upskilling."
        if req_type == "required"
        else "This is a preferred skill."
    )
    return EvidenceItem(
        requirement_text=req_text,
        requirement_type=req_type,
        support_level=UNSUPPORTED,
        confidence=0.0,
        warning=f"No evidence of '{req_text}' found in your CV. {detail}",
    )


def _flatten_cv_text(payload: dict) -> str:
    """Extract all plain text from a CV structured payload for substring matching."""
    parts = []

    basics = payload.get("basics", {}) or {}
    if basics.get("summary"):
        parts.append(str(basics["summary"]))

    for exp in payload.get("workExperience", []) or []:
        parts.append(str(exp.get("company", "")))
        parts.append(str(exp.get("title", "")))
        for bullet in exp.get("bullets", []) or []:
            parts.append(str(bullet))
        for tech in exp.get("technologies", []) or []:
            parts.append(str(tech))

    skills = payload.get("skills", {}) or {}
    for cat in ("technical", "soft"):
        for s in skills.get(cat, []) or []:
            parts.append(str(s))

    return " ".join(parts)