"""Cover letter generator

This module implements a simple cover letter generator based on a
structured specification. It expects structured job and user data,
selects relevant achievements, and renders a short email style cover
letter.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict


@dataclass
class Achievement:
    context_org: str
    role: str
    task: str
    action: str
    result: str


@dataclass
class JobData:
    job_title: str
    company_name: str
    application_source: Optional[str]
    key_responsibilities: List[str]


@dataclass
class UserProfile:
    candidate_name: str
    current_role: str
    field_or_title: str
    key_skills: List[str]
    achievements: List[Achievement]
    motivation_hooks: List[str]
    email: str
    phone: str
    optional_links: List[str]


@dataclass
class GenerationSettings:
    experience_weight: str  # "light", "balanced", or "heavy"
    recruiter_name: Optional[str] = None


def validate_inputs(job: JobData, user: UserProfile, settings: GenerationSettings) -> None:
    if not job.job_title or not job.company_name:
        raise ValueError("job_title and company_name are required")
    if not job.key_responsibilities:
        raise ValueError("At least one key responsibility is required")
    if not user.key_skills:
        raise ValueError("At least one key skill is required")
    if not user.achievements:
        raise ValueError("At least one achievement is required")
    if not user.email or not user.phone:
        raise ValueError("Email and phone are required")
    if settings.experience_weight not in {"light", "balanced", "heavy"}:
        raise ValueError("experience_weight must be 'light', 'balanced' or 'heavy'")


def select_priority_responsibilities(job: JobData, max_count: int = 3) -> List[str]:
    return job.key_responsibilities[:max_count]


def _normalise(text: str) -> List[str]:
    return [t.strip().lower() for t in text.replace("/", " ").replace(",", " ").split() if t.strip()]


def map_achievements_to_responsibilities(
    responsibilities: List[str], achievements: List[Achievement]
) -> Dict[str, List[Achievement]]:
    mapping: Dict[str, List[Achievement]] = {r: [] for r in responsibilities}
    resp_tokens = {r: set(_normalise(r)) for r in responsibilities}
    for ach in achievements:
        ach_text = " ".join([ach.task, ach.action, ach.result])
        ach_tokens = set(_normalise(ach_text))
        for r, tokens in resp_tokens.items():
            if tokens & ach_tokens:
                mapping[r].append(ach)
    return mapping


def select_experience_stories(
    mapping: Dict[str, List[Achievement]],
    experience_weight: str,
    max_total: int = 3,
) -> List[Achievement]:
    ordered: List[Achievement] = []
    for resp, achs in mapping.items():
        for ach in achs:
            if ach not in ordered:
                ordered.append(ach)
    if experience_weight == "light":
        limit = 1
    elif experience_weight == "balanced":
        limit = min(2, max_total)
    else:
        limit = max_total
    return ordered[:limit] if ordered else []


def render_greeting(settings: GenerationSettings) -> str:
    if settings.recruiter_name:
        return f"Hi {settings.recruiter_name},"
    return "Hi,"


def render_opening(job: JobData, user: UserProfile) -> str:
    source_part = f" which I saw on {job.application_source}" if job.application_source else ""
    skills = ", ".join(user.key_skills[:2]) if user.key_skills else "relevant experience"
    return (
        f"I would like to apply for the {job.job_title} role at {job.company_name}{source_part}. "
        f"As a {user.field_or_title} with experience in {skills}, I can help you address "
        f"key priorities in this position."
    )


def render_experience_block(
    stories: List[Achievement], job: JobData, user: UserProfile, experience_weight: str
) -> str:
    if not stories:
        return (
            f"In my work as {user.current_role}, I have developed {', '.join(user.key_skills)} "
            f"that match the main responsibilities of this role."
        )
    sentences: List[str] = []
    for i, ach in enumerate(stories):
        prefix = "At" if i == 0 else "While at"
        sentences.append(
            f"{prefix} {ach.context_org}, working as {ach.role}, I {ach.task} by {ach.action}, "
            f"which resulted in {ach.result}."
        )
    return " " .join(sentences)


def select_motivation_hook(user: UserProfile, job: JobData) -> str:
    if user.motivation_hooks:
        return user.motivation_hooks[0]
    # simple fallback based on first responsibility
    return f"the focus on {job.key_responsibilities[0].lower()} in this role"


def render_motivation_block(hook: str, job: JobData, user: UserProfile) -> str:
    return (
        f"I am particularly interested in {job.company_name} because {hook}. "
        f"I would like to bring my {', '.join(user.key_skills[:2])} to support "
        f"your work in this area."
    )


def render_closing(job: JobData, user: UserProfile) -> str:
    return (
        f"I would welcome the chance to discuss how my experience can help {job.company_name} "
        f"with the responsibilities of this role. You can reach me on {user.phone} or at "
        f"{user.email} if you would like to arrange an interview."
    )


def render_signature(user: UserProfile) -> str:
    lines = ["Kind regards", "", user.candidate_name, user.phone, user.email]
    for link in user.optional_links:
        lines.append(link)
    return "
".join(lines)


def assemble_cover_letter(
    greeting: str,
    opening: str,
    experience_block: str,
    motivation_block: str,
    closing: str,
    signature: str,
) -> str:
    parts = [greeting, "", opening, "", experience_block, "", motivation_block, "", closing, "", signature]
    return "
".join(p for p in parts if p is not None and p != "")


def _word_count(text: str) -> int:
    return len([w for w in text.split() if w.strip()])


def enforce_length(letter_text: str) -> str:
    count = _word_count(letter_text)
    if count < 100 or count > 300:
        # For now, just return as is; a more advanced version could trim or extend.
        return letter_text
    return letter_text


def generate_cover_letter(job: JobData, user: UserProfile, settings: GenerationSettings) -> str:
    validate_inputs(job, user, settings)
    responsibilities = select_priority_responsibilities(job)
    mapping = map_achievements_to_responsibilities(responsibilities, user.achievements)
    stories = select_experience_stories(mapping, settings.experience_weight)

    greeting = render_greeting(settings)
    opening = render_opening(job, user)
    experience_block = render_experience_block(stories, job, user, settings.experience_weight)
    hook = select_motivation_hook(user, job)
    motivation_block = render_motivation_block(hook, job, user)
    closing = render_closing(job, user)
    signature = render_signature(user)

    letter = assemble_cover_letter(
        greeting,
        opening,
        experience_block,
        motivation_block,
        closing,
        signature,
    )
    return enforce_length(letter)
