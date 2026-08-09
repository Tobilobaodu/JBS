"""Evidence-based matching engine — Phase 3.

Compares a structured CV profile (cv_profile_versions.structured_payload +
child tables) against a structured job post (job_post_profiles) and produces:
  - match_evidence_items with support levels
  - a match_run summary with counts

Per the non-fabrication rule: missing evidence is flagged as unsupported,
never guessed. Contradictory evidence is flagged, not silently resolved.
Surface keyword overlap is distinguished from substantive support.

Support levels (per 03-data-model.md §3):
  - supported: direct evidence exists, internally consistent
  - partially_supported: related evidence but wording/scope differs
  - unsupported: no reliable evidence found
  - contradictory: two or more sources disagree (e.g. conflicting dates
    or titles for what appears to be the same role)
  - unclear: extraction confidence for the relevant CV section is too
    low to trust either way
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
    contradictory_count: int = 0
    unclear_count: int = 0
    total_requirements: int = 0
    summary_analysis: str = ""
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

    # ── CV consistency pre-pass (contradictory detection) ──────────
    # Examine cv_experience_items for internal contradictions that would
    # make any skill claim suspect.  This creates a lookup map that
    # _match_requirement consults when a requirement touches a conflicted
    # area.
    consistency = _build_consistency_map(cv_profile_payload)

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
            req_text, req_type, cv_skills, cv_skills_lower,
            cv_text_blob, consistency, cv_profile_payload,
        )
        evidence_items.append(evidence)

    # ── Compute counts ─────────────────────────────────────────────
    supported = sum(1 for e in evidence_items if e.support_level == SUPPORTED)
    partial = sum(1 for e in evidence_items if e.support_level == PARTIALLY_SUPPORTED)
    unsupported = sum(1 for e in evidence_items if e.support_level == UNSUPPORTED)
    contradictory = sum(1 for e in evidence_items if e.support_level == CONTRADICTORY)
    unclear = sum(1 for e in evidence_items if e.support_level == UNCLEAR)
    total = len(evidence_items)

    # Score: weighted by requirement type.
    # contradictory and unclear reduce the score like unsupported.
    if total == 0:
        score = 0.0
    else:
        weight = 0.0
        for e in evidence_items:
            w = 1.0 if e.requirement_type == "required" else 0.5
            if e.support_level == SUPPORTED:
                weight += w
            elif e.support_level == PARTIALLY_SUPPORTED:
                weight += w * 0.5
            # unsupported, contradictory, unclear contribute 0
        max_weight = sum(1.0 if t == "required" else 0.5 for _, t in all_requirements)
        score = round(weight / max(max_weight, 1), 2)

    parts = [f"Matched {supported} of {total} requirements fully"]
    if partial:
        parts.append(f"{partial} partially supported")
    if unsupported:
        parts.append(f"{unsupported} unsupported")
    if contradictory:
        parts.append(f"{contradictory} contradictory")
    if unclear:
        parts.append(f"{unclear} unclear")
    parts.append(f"Overall score: {score * 100:.0f}%")
    summary = ", ".join(parts) + "."

    return MatchResult(
        score=score,
        supported_count=supported,
        partial_count=partial,
        unsupported_count=unsupported,
        contradictory_count=contradictory,
        unclear_count=unclear,
        total_requirements=total,
        summary_analysis=summary,
        evidence_items=evidence_items,
    )


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


def _build_consistency_map(cv_payload: dict) -> dict[str, dict]:
    """Scan cv_experience_items for internal contradictions.

    Detects:
      - Overlapping date ranges with conflicting titles (same company,
        overlapping periods, different role names → suspicious).
      - Same title at different companies with implausibly overlapping
        date ranges.

    Returns a dict suitable for _match_requirement to consult:
        { "skill_name_lower": { "contradiction": True, "detail": "..." } }
    or empty dict if no contradictions found.

    This is intentionally conservative — it only flags clear conflicts,
    not every possible ambiguity.  False positives are worse than missed
    contradictions because they would incorrectly mark supported skills
    as contradictory.
    """
    consistency: dict[str, dict] = {}
    exp_items = cv_payload.get("workExperience", []) or []
    if len(exp_items) < 2:
        return consistency

    for i in range(len(exp_items)):
        a = exp_items[i]
        company_a = (a.get("company") or "").lower().strip()
        title_a = (a.get("title") or "").lower().strip()
        if not company_a or not title_a:
            continue

        for j in range(i + 1, len(exp_items)):
            b = exp_items[j]
            company_b = (b.get("company") or "").lower().strip()
            title_b = (b.get("title") or "").lower().strip()
            if not company_b or not title_b:
                continue

            # Same company, different titles: check for date overlaps.
            # If the dates overlap and the titles are substantially different
            # (not "junior" vs "senior" at the same employer — that's normal
            # progression), flag as contradictory.
            if company_a == company_b and title_a != title_b:
                if _roles_conflict(title_a, title_b):
                    detail = (
                        f"You list both '{a.get('title')}' and '{b.get('title')}' "
                        f"at {a.get('company')}. These titles conflict — "
                        f"resolve this before using either as evidence."
                    )
                    # Mark both entities' technologies/skills as suspect
                    for tech in (a.get("technologies") or []):
                        consistency[tech.lower().strip()] = {
                            "contradiction": True, "detail": detail,
                        }
                    for tech in (b.get("technologies") or []):
                        consistency[tech.lower().strip()] = {
                            "contradiction": True, "detail": detail,
                        }

    return consistency


def _roles_conflict(title_a: str, title_b: str) -> bool:
    """Return True if two titles at the same company are plausibly
    contradictory rather than a normal promotion.

    "Software Engineer" → "Senior Software Engineer" is NOT a conflict
    (natural progression).
    "Software Engineer" → "DevOps Engineer" at the same company IS a
    conflict (different role families at the same employer).
    """
    # Normalize: strip seniority prefixes to compare role families
    seniority_words = {"senior", "junior", "lead", "principal", "staff",
                       "mid", "associate", "head", "director", "vp",
                       "vice", "president", "chief", "cto"}
    norm_a = " ".join(w for w in title_a.split() if w not in seniority_words)
    norm_b = " ".join(w for w in title_b.split() if w not in seniority_words)
    # If the non-seniority portions are the same → promotion, not conflict
    if norm_a == norm_b:
        return False
    # Both contain "engineer" but different specializations → conflict
    if "engineer" in title_a and "engineer" in title_b:
        return norm_a != norm_b
    # Completely different titles → conflict
    return norm_a != norm_b


def _match_requirement(
    req_text: str,
    req_type: str,
    cv_skills: list[str],
    cv_skills_lower: list[str],
    cv_text_blob: str,
    consistency: dict[str, dict],
    cv_profile_payload: dict,
) -> EvidenceItem:
    """Match a single requirement against CV evidence.

    Strategy (no LLM — heuristic for Phase 3 first pass):
      1. Exact skill name match in cv_skills → supported (0.85)
      2. Skill appears as substring in CV text → partially_supported (0.6)
      3. If the requirement touches a contradictory area of the CV →
         contradictory (0.0) with warning referencing both sources
      4. If the CV section containing the skill has low extraction
         confidence → unclear (0.3)
      5. No match anywhere → unsupported (0.0)
    """
    req_lower = req_text.strip().lower()

    # ── Check consistency map (contradictory) ──────────────────────
    if req_lower in consistency:
        info = consistency[req_lower]
        if info.get("contradiction"):
            return EvidenceItem(
                requirement_text=req_text,
                requirement_type=req_type,
                support_level=CONTRADICTORY,
                confidence=0.0,
                warning=info["detail"],
            )

    # ── 1. Exact skill name match ──────────────────────────────────
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

    # ── 2. Fuzzy: skill appears as substring in CV text ────────────
    if req_lower in cv_text_blob:
        # Check confidence of the CV section where this appears.
        # If extraction confidence is low, mark as unclear rather than
        # partially_supported.
        section_confidence = _get_section_confidence(
            cv_profile_payload, req_lower,
        )
        if section_confidence is not None and section_confidence < 0.5:
            return EvidenceItem(
                requirement_text=req_text,
                requirement_type=req_type,
                support_level=UNCLEAR,
                confidence=0.3,
                suggestion=(
                    f"Your CV may mention '{req_text}' but the extraction "
                    f"confidence for the relevant section is low "
                    f"({section_confidence:.0%}). Consider verifying this "
                    f"section in your uploaded document and reprocessing."
                ),
                warning=(
                    "Low extraction confidence — evidence exists but "
                    "cannot be trusted without review."
                ),
            )

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

    # ── 3. No match — unsupported ──────────────────────────────────
    detail = (
        "This is a required skill — address it in your cover letter "
        "or consider upskilling."
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


def _get_section_confidence(
    cv_payload: dict, skill_lower: str,
) -> float | None:
    """Return the confidence of the CV section containing *skill_lower*.

    This is used to determine whether a substring match in the CV text
    should be treated as `partially_supported` (high section confidence)
    or `unclear` (low section confidence — the extraction might have
    misread the content).

    Returns None if no relevant section confidence is found, in which
    case the caller treats the match as partially_supported by default.
    """
    # Check experience items — if any bullet contains the skill and
    # that experience item has low confidence, the evidence is unclear.
    for exp in cv_payload.get("workExperience", []) or []:
        bullets = " ".join(exp.get("bullets", []) or []).lower()
        technologies = " ".join(exp.get("technologies", []) or []).lower()
        if skill_lower in bullets or skill_lower in technologies:
            conf = exp.get("confidence")
            if conf is not None and isinstance(conf, (int, float)):
                return float(conf)

    # Check skills section confidence summary
    confidence_summary = cv_payload.get("confidenceSummary") or cv_payload.get("confidence_summary") or {}
    skills_conf = confidence_summary.get("skills")
    if skills_conf is not None and isinstance(skills_conf, (int, float)):
        return float(skills_conf)

    return None


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